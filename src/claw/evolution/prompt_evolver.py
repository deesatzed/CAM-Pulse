"""Prompt evolution with A/B testing for CLAW.

Manages prompt variants, schedules A/B tests, collects samples, and
promotes winning variants.  Also enriches static prompts with thriving
methodologies and top error patterns (the ``evolve_prompt`` path adapted
from ralfed's pattern enrichment).

Key design decisions:
- ``mutate_prompt()`` uses deterministic string transformations (emphasis,
  section reordering, constraint injection) -- NOT LLM-based mutation --
  so it incurs zero API cost.
- ``evaluate_test()`` requires MIN_SAMPLES (20) observations per variant
  before declaring a winner, using Bayesian Beta-distribution comparison.
- All DB access is async through ``Repository.engine.fetch_all/fetch_one/execute``.
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional

from claw.db.repository import Repository

if TYPE_CHECKING:
    from claw.memory.error_kb import ErrorKB
    from claw.memory.semantic import SemanticMemory

logger = logging.getLogger("claw.evolution.prompt_evolver")

# Minimum samples required per variant before an A/B test can be evaluated.
MIN_SAMPLES = 20

# Bayesian priors for Beta distribution comparison.
_PRIOR_ALPHA = 1.0
_PRIOR_BETA = 1.0

# Threshold: the winning variant's Bayesian score must exceed the
# loser's by at least this margin to be declared the winner.
_WIN_MARGIN = 0.05

# Supported mutation types for ``mutate_prompt()``.
MUTATION_TYPES = (
    "add_emphasis",
    "reorder_sections",
    "add_constraints",
    "simplify",
    "add_examples_placeholder",
)


class PromptEvolver:
    """Prompt variant management, A/B testing, and prompt enrichment.

    Injected dependencies:
        repository: Database access for prompt_variants table.
        semantic_memory: Optional — used by ``evolve_prompt`` to pull
            thriving methodologies for enrichment.
        error_kb: Optional — used by ``evolve_prompt`` to pull top error
            patterns for enrichment.
    """

    def __init__(
        self,
        repository: Repository,
        semantic_memory: Optional["SemanticMemory"] = None,
        error_kb: Optional["ErrorKB"] = None,
    ) -> None:
        self.repository = repository
        self.semantic_memory = semantic_memory
        self.error_kb = error_kb

    # ------------------------------------------------------------------
    # 1. mutate_prompt — deterministic string-level mutations
    # ------------------------------------------------------------------

    def mutate_prompt(self, base_prompt: str, mutation_type: str) -> str:
        """Create a variant of a prompt using string-level transformations.

        This does NOT use an LLM — mutations are purely mechanical text
        manipulations.  The caller should schedule the resulting variant
        as an A/B test to determine whether the mutation improves outcomes.

        Parameters
        ----------
        base_prompt:
            The prompt text to mutate.
        mutation_type:
            One of ``MUTATION_TYPES``:
            - ``"add_emphasis"``: wraps key instruction sentences in
              uppercase markers.
            - ``"reorder_sections"``: reverses the order of
              double-newline-delimited sections (except the first).
            - ``"add_constraints"``: appends explicit quality constraints.
            - ``"simplify"``: strips parenthetical remarks and reduces
              verbosity.
            - ``"add_examples_placeholder"``: appends a structured
              section reminding the agent to include concrete examples.

        Returns
        -------
        str
            The mutated prompt text.

        Raises
        ------
        ValueError
            If ``mutation_type`` is not recognised.
        """
        if mutation_type not in MUTATION_TYPES:
            raise ValueError(
                f"Unknown mutation_type '{mutation_type}'. "
                f"Must be one of: {MUTATION_TYPES}"
            )

        if mutation_type == "add_emphasis":
            return self._mutate_add_emphasis(base_prompt)
        if mutation_type == "reorder_sections":
            return self._mutate_reorder_sections(base_prompt)
        if mutation_type == "add_constraints":
            return self._mutate_add_constraints(base_prompt)
        if mutation_type == "simplify":
            return self._mutate_simplify(base_prompt)
        if mutation_type == "add_examples_placeholder":
            return self._mutate_add_examples(base_prompt)

        # Unreachable due to the check above, but keeps mypy happy.
        return base_prompt

    # --- Mutation helpers (private) ---

    @staticmethod
    def _mutate_add_emphasis(prompt: str) -> str:
        """Add IMPORTANT markers to sentences containing key directive words."""
        directive_keywords = (
            "must", "always", "never", "critical", "required",
            "ensure", "verify", "validate",
        )
        lines = prompt.split("\n")
        result_lines: list[str] = []
        for line in lines:
            lower = line.lower().strip()
            if any(kw in lower for kw in directive_keywords) and not line.strip().startswith("IMPORTANT"):
                result_lines.append(f"IMPORTANT: {line.strip()}")
            else:
                result_lines.append(line)
        return "\n".join(result_lines)

    @staticmethod
    def _mutate_reorder_sections(prompt: str) -> str:
        """Reverse the order of sections (double-newline delimited), keeping the first section fixed."""
        sections = prompt.split("\n\n")
        if len(sections) <= 2:
            return prompt
        # Keep the first section (usually the header/context) in place.
        header = sections[0]
        body_sections = sections[1:]
        body_sections.reverse()
        return "\n\n".join([header] + body_sections)

    @staticmethod
    def _mutate_add_constraints(prompt: str) -> str:
        """Append explicit quality constraints to the end of the prompt."""
        constraints = (
            "\n\n--- Additional Quality Constraints ---\n"
            "1. Every claim must be verifiable against the actual codebase.\n"
            "2. Do not introduce changes that break existing tests.\n"
            "3. Provide concrete file paths and line references where applicable.\n"
            "4. If uncertain about an approach, state the uncertainty explicitly.\n"
            "5. Prefer minimal, targeted changes over sweeping refactors."
        )
        return prompt.rstrip() + constraints

    @staticmethod
    def _mutate_simplify(prompt: str) -> str:
        """Strip parenthetical remarks and compress whitespace for brevity."""
        import re
        # Remove parenthetical asides: (some remark)
        simplified = re.sub(r"\s*\([^)]{5,}\)", "", prompt)
        # Collapse triple+ newlines to double
        simplified = re.sub(r"\n{3,}", "\n\n", simplified)
        # Collapse multiple spaces to single
        simplified = re.sub(r"  +", " ", simplified)
        return simplified.strip()

    @staticmethod
    def _mutate_add_examples(prompt: str) -> str:
        """Append a section reminding the agent to provide concrete examples."""
        example_section = (
            "\n\n--- Examples ---\n"
            "When providing recommendations or making changes, include at least "
            "one concrete example showing the before and after state. "
            "Examples should reference real files and real code from the project."
        )
        return prompt.rstrip() + example_section

    # ------------------------------------------------------------------
    # 2. schedule_ab_test — register control + variant for A/B testing
    # ------------------------------------------------------------------

    async def schedule_ab_test(
        self,
        prompt_name: str,
        control_content: str,
        variant_content: str,
        agent_id: Optional[str] = None,
    ) -> dict[str, str]:
        """Schedule an A/B test between a control prompt and a variant.

        Creates two rows in ``prompt_variants``: one labelled ``"control"``
        and one labelled ``"variant"``.  The control is set as active by
        default.

        If rows for the same (prompt_name, variant_label, agent_id) already
        exist they are updated with the new content and their counters are
        reset to zero.

        Parameters
        ----------
        prompt_name:
            Logical name of the prompt (e.g. ``"deepdive"``).
        control_content:
            The baseline prompt text.
        variant_content:
            The mutated prompt text to test against the control.
        agent_id:
            Optional agent scope.  ``None`` means the test applies to
            all agents.

        Returns
        -------
        dict[str, str]
            Mapping ``{"control_id": ..., "variant_id": ...}``.
        """
        now = datetime.now(UTC).isoformat()

        control_id = await self._upsert_variant(
            prompt_name=prompt_name,
            variant_label="control",
            content=control_content,
            agent_id=agent_id,
            is_active=True,
            now=now,
        )

        variant_id = await self._upsert_variant(
            prompt_name=prompt_name,
            variant_label="variant",
            content=variant_content,
            agent_id=agent_id,
            is_active=False,
            now=now,
        )

        logger.info(
            "Scheduled A/B test for prompt '%s' (agent=%s): control=%s variant=%s",
            prompt_name,
            agent_id or "all",
            control_id,
            variant_id,
        )
        return {"control_id": control_id, "variant_id": variant_id}

    async def _upsert_variant(
        self,
        prompt_name: str,
        variant_label: str,
        content: str,
        agent_id: Optional[str],
        is_active: bool,
        now: str,
    ) -> str:
        """Insert or update a prompt variant row; return its ID."""
        existing = await self.repository.engine.fetch_one(
            """SELECT id FROM prompt_variants
               WHERE prompt_name = ? AND variant_label = ? AND agent_id IS ?""",
            [prompt_name, variant_label, agent_id],
        )

        if existing:
            row_id = str(existing["id"])
            await self.repository.engine.execute(
                """UPDATE prompt_variants
                   SET content = ?, is_active = ?, sample_count = 0,
                       success_count = 0, avg_quality_score = 0.0,
                       updated_at = ?
                   WHERE id = ?""",
                [content, 1 if is_active else 0, now, row_id],
            )
            return row_id

        row_id = str(uuid.uuid4())
        await self.repository.engine.execute(
            """INSERT INTO prompt_variants
               (id, prompt_name, variant_label, content, agent_id,
                is_active, sample_count, success_count, avg_quality_score,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0.0, ?, ?)""",
            [row_id, prompt_name, variant_label, content, agent_id,
             1 if is_active else 0, now, now],
        )
        return row_id

    # ------------------------------------------------------------------
    # 3. record_sample — record an A/B outcome for a variant
    # ------------------------------------------------------------------

    async def record_sample(
        self,
        prompt_name: str,
        variant_label: str,
        agent_id: Optional[str],
        success: bool,
        quality_score: float = 0.0,
    ) -> bool:
        """Record an A/B test outcome for a prompt variant.

        Increments ``sample_count`` and optionally ``success_count``,
        and recomputes ``avg_quality_score`` using a running average.

        Parameters
        ----------
        prompt_name:
            The prompt being tested.
        variant_label:
            ``"control"`` or ``"variant"``.
        agent_id:
            Agent scope (or ``None`` for all agents).
        success:
            Whether this invocation succeeded.
        quality_score:
            Quality metric in [0.0, 1.0] for this sample.

        Returns
        -------
        bool
            ``True`` if the sample was recorded, ``False`` if the
            variant row was not found.
        """
        row = await self.repository.engine.fetch_one(
            """SELECT id, sample_count, success_count, avg_quality_score
               FROM prompt_variants
               WHERE prompt_name = ? AND variant_label = ? AND agent_id IS ?""",
            [prompt_name, variant_label, agent_id],
        )
        if row is None:
            logger.warning(
                "Cannot record sample: variant '%s/%s' (agent=%s) not found",
                prompt_name,
                variant_label,
                agent_id,
            )
            return False

        old_count = int(row["sample_count"])
        old_success = int(row["success_count"])
        old_avg = float(row["avg_quality_score"])

        new_count = old_count + 1
        new_success = old_success + (1 if success else 0)
        # Running average for quality score.
        new_avg = ((old_avg * old_count) + quality_score) / new_count

        now = datetime.now(UTC).isoformat()
        await self.repository.engine.execute(
            """UPDATE prompt_variants
               SET sample_count = ?, success_count = ?,
                   avg_quality_score = ?, updated_at = ?
               WHERE id = ?""",
            [new_count, new_success, new_avg, now, row["id"]],
        )

        logger.debug(
            "Recorded sample for '%s/%s' (agent=%s): success=%s quality=%.2f "
            "(total samples=%d)",
            prompt_name,
            variant_label,
            agent_id,
            success,
            quality_score,
            new_count,
        )
        return True

    # ------------------------------------------------------------------
    # 4. evaluate_test — Bayesian comparison after MIN_SAMPLES collected
    # ------------------------------------------------------------------

    async def evaluate_test(
        self,
        prompt_name: str,
        agent_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Evaluate an A/B test and determine if there is a winner.

        Requirements before a winner can be declared:
        - Both control and variant must have >= ``MIN_SAMPLES`` samples.
        - The winner's Bayesian score must exceed the loser's by at
          least ``_WIN_MARGIN``.

        The Bayesian score is the posterior mean of
        ``Beta(prior_alpha + successes, prior_beta + failures)``.

        Parameters
        ----------
        prompt_name:
            The prompt under test.
        agent_id:
            Agent scope (or ``None`` for all agents).

        Returns
        -------
        dict
            Keys:
            - ``ready``: bool — whether enough samples exist.
            - ``winner``: str or None — ``"control"``, ``"variant"``,
              or ``None`` if inconclusive.
            - ``control``: dict with ``sample_count``, ``success_count``,
              ``avg_quality_score``, ``bayesian_score``.
            - ``variant``: dict (same shape as control).
            - ``margin``: float — score difference (positive favours variant).
        """
        control = await self._fetch_variant_stats(prompt_name, "control", agent_id)
        variant = await self._fetch_variant_stats(prompt_name, "variant", agent_id)

        if control is None or variant is None:
            logger.warning(
                "Cannot evaluate test '%s' (agent=%s): "
                "control_exists=%s variant_exists=%s",
                prompt_name,
                agent_id,
                control is not None,
                variant is not None,
            )
            return {
                "ready": False,
                "winner": None,
                "control": control,
                "variant": variant,
                "margin": 0.0,
            }

        ready = (
            control["sample_count"] >= MIN_SAMPLES
            and variant["sample_count"] >= MIN_SAMPLES
        )

        # Compute Bayesian scores.
        ctrl_score = _bayesian_score(control["success_count"], control["sample_count"])
        var_score = _bayesian_score(variant["success_count"], variant["sample_count"])

        control["bayesian_score"] = ctrl_score
        variant["bayesian_score"] = var_score

        margin = var_score - ctrl_score

        winner: Optional[str] = None
        if ready:
            if margin > _WIN_MARGIN:
                winner = "variant"
            elif margin < -_WIN_MARGIN:
                winner = "control"
            # else: inconclusive — margin is within noise band.

        logger.info(
            "A/B evaluation for '%s' (agent=%s): ready=%s winner=%s "
            "ctrl_score=%.4f var_score=%.4f margin=%.4f",
            prompt_name,
            agent_id,
            ready,
            winner,
            ctrl_score,
            var_score,
            margin,
        )

        return {
            "ready": ready,
            "winner": winner,
            "control": control,
            "variant": variant,
            "margin": margin,
        }

    async def _fetch_variant_stats(
        self,
        prompt_name: str,
        variant_label: str,
        agent_id: Optional[str],
    ) -> Optional[dict[str, Any]]:
        """Fetch sample statistics for one variant."""
        row = await self.repository.engine.fetch_one(
            """SELECT id, sample_count, success_count, avg_quality_score, is_active
               FROM prompt_variants
               WHERE prompt_name = ? AND variant_label = ? AND agent_id IS ?""",
            [prompt_name, variant_label, agent_id],
        )
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "sample_count": int(row["sample_count"]),
            "success_count": int(row["success_count"]),
            "avg_quality_score": float(row["avg_quality_score"]),
            "is_active": bool(row["is_active"]),
        }

    # ------------------------------------------------------------------
    # 5. promote_variant — activate the winning variant
    # ------------------------------------------------------------------

    async def promote_variant(
        self,
        prompt_name: str,
        variant_label: str,
        agent_id: Optional[str] = None,
    ) -> bool:
        """Activate a winning variant and deactivate all others.

        Parameters
        ----------
        prompt_name:
            The prompt whose variant should be promoted.
        variant_label:
            The label of the winning variant (``"control"`` or ``"variant"``).
        agent_id:
            Agent scope.

        Returns
        -------
        bool
            ``True`` if the variant was found and promoted, ``False``
            if the variant row does not exist.
        """
        now = datetime.now(UTC).isoformat()

        # Check that the target variant exists.
        target = await self.repository.engine.fetch_one(
            """SELECT id FROM prompt_variants
               WHERE prompt_name = ? AND variant_label = ? AND agent_id IS ?""",
            [prompt_name, variant_label, agent_id],
        )
        if target is None:
            logger.warning(
                "Cannot promote: variant '%s/%s' (agent=%s) not found",
                prompt_name,
                variant_label,
                agent_id,
            )
            return False

        # Deactivate all variants for this prompt + agent.
        await self.repository.engine.execute(
            """UPDATE prompt_variants
               SET is_active = 0, updated_at = ?
               WHERE prompt_name = ? AND agent_id IS ?""",
            [now, prompt_name, agent_id],
        )

        # Activate the winner.
        await self.repository.engine.execute(
            """UPDATE prompt_variants
               SET is_active = 1, updated_at = ?
               WHERE id = ?""",
            [now, target["id"]],
        )

        logger.info(
            "Promoted variant '%s/%s' (agent=%s) to active",
            prompt_name,
            variant_label,
            agent_id,
        )
        return True

    # ------------------------------------------------------------------
    # 6. get_active_variant — retrieve the currently active prompt
    # ------------------------------------------------------------------

    async def get_active_variant(
        self,
        prompt_name: str,
        agent_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Get the currently active prompt variant for a given prompt and agent.

        Looks for an agent-specific active variant first; falls back to
        an agent-agnostic active variant (``agent_id IS NULL``).

        Parameters
        ----------
        prompt_name:
            Logical prompt name.
        agent_id:
            Agent to look up.  ``None`` matches only agent-agnostic rows.

        Returns
        -------
        dict or None
            Keys: ``id``, ``prompt_name``, ``variant_label``, ``content``,
            ``agent_id``, ``sample_count``, ``success_count``,
            ``avg_quality_score``.  ``None`` if no active variant exists.
        """
        row: Optional[dict[str, Any]] = None

        # Try agent-specific first.
        if agent_id is not None:
            row = await self.repository.engine.fetch_one(
                """SELECT id, prompt_name, variant_label, content, agent_id,
                          sample_count, success_count, avg_quality_score
                   FROM prompt_variants
                   WHERE prompt_name = ? AND agent_id = ? AND is_active = 1""",
                [prompt_name, agent_id],
            )

        # Fallback: agent-agnostic.
        if row is None:
            row = await self.repository.engine.fetch_one(
                """SELECT id, prompt_name, variant_label, content, agent_id,
                          sample_count, success_count, avg_quality_score
                   FROM prompt_variants
                   WHERE prompt_name = ? AND agent_id IS NULL AND is_active = 1""",
                [prompt_name],
            )

        if row is None:
            return None

        return {
            "id": str(row["id"]),
            "prompt_name": str(row["prompt_name"]),
            "variant_label": str(row["variant_label"]),
            "content": str(row["content"]),
            "agent_id": row["agent_id"],
            "sample_count": int(row["sample_count"]),
            "success_count": int(row["success_count"]),
            "avg_quality_score": float(row["avg_quality_score"]),
        }

    # ------------------------------------------------------------------
    # 7. evolve_prompt — enrich a static prompt with patterns and errors
    # ------------------------------------------------------------------

    async def evolve_prompt(
        self,
        static_prompt: str,
        project_id: Optional[str] = None,
    ) -> str:
        """Enrich a static prompt with thriving methodologies and top errors.

        Adapted from ralfed's pattern-enrichment flow:
        1. Pull up to 3 thriving methodologies from semantic memory.
        2. Pull up to 5 top error patterns from the error knowledge base.
        3. Append them as structured context sections to the prompt.

        If ``semantic_memory`` or ``error_kb`` are not configured, the
        corresponding section is simply omitted and the prompt is returned
        with whatever enrichment is available.

        Parameters
        ----------
        static_prompt:
            The base prompt to enrich.
        project_id:
            Project scope for error pattern lookup.  If ``None``, error
            patterns are not appended.

        Returns
        -------
        str
            The enriched prompt.
        """
        enrichment_sections: list[str] = []

        # --- Thriving methodologies ---
        if self.semantic_memory is not None:
            try:
                thriving = await self.semantic_memory.get_thriving(limit=3)
                if thriving:
                    lines = ["--- Thriving Methodologies (learned from past successes) ---"]
                    for idx, meth in enumerate(thriving, 1):
                        lines.append(
                            f"{idx}. [{meth.lifecycle_state}] "
                            f"{meth.problem_description[:120]}"
                        )
                        if meth.methodology_notes:
                            lines.append(f"   Notes: {meth.methodology_notes[:200]}")
                        lines.append(
                            f"   Success rate: {meth.success_count}/"
                            f"{meth.success_count + meth.failure_count}"
                        )
                    enrichment_sections.append("\n".join(lines))
                    logger.debug(
                        "Enriched prompt with %d thriving methodologies",
                        len(thriving),
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to fetch thriving methodologies for prompt enrichment: %s",
                    exc,
                )

        # --- Top error patterns ---
        if self.error_kb is not None and project_id is not None:
            try:
                patterns = await self.error_kb.get_common_failure_patterns(
                    project_id=project_id, min_count=2
                )
                # Take top 5 by urgency (already sorted).
                top_patterns = patterns[:5]
                if top_patterns:
                    lines = ["--- Known Error Patterns (avoid these pitfalls) ---"]
                    for idx, pat in enumerate(top_patterns, 1):
                        lines.append(
                            f"{idx}. [{pat.urgency.upper()}] "
                            f"{pat.error_signature[:120]} "
                            f"(seen {pat.count}x across {len(pat.task_ids)} tasks)"
                        )
                        if pat.successful_resolution:
                            lines.append(
                                f"   Resolution: {pat.successful_resolution[:200]}"
                            )
                    enrichment_sections.append("\n".join(lines))
                    logger.debug(
                        "Enriched prompt with %d error patterns",
                        len(top_patterns),
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to fetch error patterns for prompt enrichment: %s",
                    exc,
                )

        if not enrichment_sections:
            return static_prompt

        return static_prompt.rstrip() + "\n\n" + "\n\n".join(enrichment_sections)

    # ------------------------------------------------------------------
    # Convenience: select variant for an invocation (for routing)
    # ------------------------------------------------------------------

    async def select_variant_for_invocation(
        self,
        prompt_name: str,
        agent_id: Optional[str] = None,
    ) -> tuple[str, str]:
        """Select which variant to use for the next invocation.

        If an A/B test is active (both control and variant exist, and
        neither has reached MIN_SAMPLES), randomly assigns the invocation
        to one of the two variants with 50/50 probability.

        If no test is active, returns the currently active variant's
        content.

        Parameters
        ----------
        prompt_name:
            Logical prompt name.
        agent_id:
            Agent scope.

        Returns
        -------
        tuple[str, str]
            ``(variant_label, content)`` — the label and text of the
            selected variant.

        Raises
        ------
        ValueError
            If no variants exist at all for this prompt.
        """
        rows = await self.repository.engine.fetch_all(
            """SELECT variant_label, content, sample_count, is_active
               FROM prompt_variants
               WHERE prompt_name = ? AND agent_id IS ?
               ORDER BY is_active DESC""",
            [prompt_name, agent_id],
        )

        if not rows:
            raise ValueError(
                f"No variants found for prompt '{prompt_name}' (agent={agent_id})"
            )

        # If both control and variant exist and are still collecting samples,
        # randomly assign.
        by_label = {str(r["variant_label"]): r for r in rows}
        if "control" in by_label and "variant" in by_label:
            ctrl = by_label["control"]
            var = by_label["variant"]
            if (
                int(ctrl["sample_count"]) < MIN_SAMPLES
                or int(var["sample_count"]) < MIN_SAMPLES
            ):
                chosen_label = random.choice(["control", "variant"])
                chosen = by_label[chosen_label]
                return str(chosen["variant_label"]), str(chosen["content"])

        # Otherwise return the active variant.
        active = await self.get_active_variant(prompt_name, agent_id)
        if active is not None:
            return active["variant_label"], active["content"]

        # Last resort: return the first row.
        return str(rows[0]["variant_label"]), str(rows[0]["content"])

    # ------------------------------------------------------------------
    # Listing / inspection helpers
    # ------------------------------------------------------------------

    async def list_tests(
        self, agent_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """List all A/B tests, grouped by prompt_name.

        Returns a list of dicts, each with:
        - ``prompt_name``
        - ``agent_id``
        - ``variants``: list of variant summaries
        """
        if agent_id is not None:
            rows = await self.repository.engine.fetch_all(
                """SELECT prompt_name, variant_label, agent_id, sample_count,
                          success_count, avg_quality_score, is_active
                   FROM prompt_variants
                   WHERE agent_id = ?
                   ORDER BY prompt_name, variant_label""",
                [agent_id],
            )
        else:
            rows = await self.repository.engine.fetch_all(
                """SELECT prompt_name, variant_label, agent_id, sample_count,
                          success_count, avg_quality_score, is_active
                   FROM prompt_variants
                   ORDER BY prompt_name, variant_label"""
            )

        # Group by (prompt_name, agent_id).
        groups: dict[tuple[str, Optional[str]], list[dict[str, Any]]] = {}
        for row in rows:
            key = (str(row["prompt_name"]), row.get("agent_id"))
            if key not in groups:
                groups[key] = []
            groups[key].append({
                "variant_label": str(row["variant_label"]),
                "sample_count": int(row["sample_count"]),
                "success_count": int(row["success_count"]),
                "avg_quality_score": float(row["avg_quality_score"]),
                "is_active": bool(row["is_active"]),
            })

        result: list[dict[str, Any]] = []
        for (pname, aid), variants in groups.items():
            result.append({
                "prompt_name": pname,
                "agent_id": aid,
                "variants": variants,
            })
        return result


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _bayesian_score(successes: int, total_samples: int) -> float:
    """Compute Bayesian posterior mean from Beta distribution.

    ``E[Beta(alpha, beta)] = alpha / (alpha + beta)``
    where ``alpha = prior_alpha + successes`` and
    ``beta = prior_beta + (total_samples - successes)``.
    """
    failures = total_samples - successes
    alpha = _PRIOR_ALPHA + successes
    beta = _PRIOR_BETA + failures
    return alpha / (alpha + beta)
