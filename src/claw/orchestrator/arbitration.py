"""Agent candidate arbitration for multi-agent orchestration.

Scores agent outputs and selects the strongest candidate when multiple
agents attempt the same task. Used by the Micro Claw to pick the best
result from competing agent executions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from claw.core.models import AgentResult, TaskOutcome


@dataclass
class CandidateScore:
    """Score breakdown for one agent candidate."""

    agent_id: str
    total: float
    tests_signal: float
    output_signal: float
    reliability_signal: float
    risk_penalty: float
    notes: list[str] = field(default_factory=list)


@dataclass
class ArbitrationDecision:
    """Selected candidate and score evidence."""

    selected_agent_id: str
    selected_result: AgentResult
    selected_outcome: TaskOutcome
    scores: list[CandidateScore]
    ranked_agent_ids: list[str] = field(default_factory=list)
    tie_break_reason: str | None = None
    vetoed_candidates: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_agent_id": self.selected_agent_id,
            "ranked_agent_ids": list(self.ranked_agent_ids),
            "tie_break_reason": self.tie_break_reason,
            "vetoed_candidates": list(self.vetoed_candidates),
            "scores": [
                {
                    "agent_id": s.agent_id,
                    "total": round(s.total, 3),
                    "tests_signal": round(s.tests_signal, 3),
                    "output_signal": round(s.output_signal, 3),
                    "reliability_signal": round(s.reliability_signal, 3),
                    "risk_penalty": round(s.risk_penalty, 3),
                    "notes": list(s.notes),
                }
                for s in self.scores
            ],
        }


class AgentArbiter:
    """Scores agent outputs and selects the strongest candidate.

    Candidates are (agent_id, TaskOutcome) tuples paired with their
    AgentResult metadata. The scoring formula weights:
      - tests_signal:       0.70 (tests pass + agent success)
      - output_signal:      0.25 (files produced, bounded change set)
      - reliability_signal: 0.10 (agent status + retrieval confidence)
      - risk_penalty:       variable (no artifacts, large change set, failures)
    """

    def __init__(self, soft_file_limit: int = 12):
        self.soft_file_limit = soft_file_limit

    def choose(
        self,
        candidates: list[tuple[str, AgentResult, TaskOutcome]],
        retrieval_confidence: float = 0.0,
        vetoes: dict[str, list[str]] | None = None,
    ) -> ArbitrationDecision:
        """Select the best candidate from a list of (agent_id, AgentResult, TaskOutcome).

        Args:
            candidates: List of (agent_id, agent_result, task_outcome) tuples.
            retrieval_confidence: Confidence from retrieval/memory system.
            vetoes: Map of agent_id -> list of veto reasons.

        Returns:
            ArbitrationDecision with selected candidate and scoring evidence.

        Raises:
            ValueError: If candidates list is empty.
        """
        if not candidates:
            raise ValueError("AgentArbiter received no candidates")
        vetoes = vetoes or {}

        scored: list[tuple[CandidateScore, AgentResult, TaskOutcome]] = []
        for agent_id, agent_result, task_outcome in candidates:
            score = self._score_candidate(
                agent_id=agent_id,
                agent_result=agent_result,
                task_outcome=task_outcome,
                retrieval_confidence=retrieval_confidence,
            )
            scored.append((score, agent_result, task_outcome))

        ranked_all = sorted(scored, key=self._ranking_key, reverse=True)
        ranked_eligible = [
            row for row in ranked_all
            if row[0].agent_id not in vetoes
        ]
        ranked_pool = ranked_eligible or ranked_all
        best_score, best_result, best_outcome = ranked_pool[0]
        score_list = [row[0] for row in sorted(scored, key=lambda x: x[0].agent_id)]
        tie_break_reason = self._tie_break_reason(ranked_pool)
        vetoed_candidates = [
            {
                "agent_id": agent_id,
                "reasons": reasons,
            }
            for agent_id, reasons in sorted(vetoes.items())
        ]
        return ArbitrationDecision(
            selected_agent_id=best_score.agent_id,
            selected_result=best_result,
            selected_outcome=best_outcome,
            scores=score_list,
            ranked_agent_ids=[row[0].agent_id for row in ranked_pool],
            tie_break_reason=tie_break_reason,
            vetoed_candidates=vetoed_candidates,
        )

    def _ranking_key(
        self, row: tuple[CandidateScore, AgentResult, TaskOutcome]
    ) -> tuple[float, bool, int, float, str]:
        score, _agent_result, task_outcome = row
        # Explicit tie-break policy:
        # 1) higher total score
        # 2) tests passed
        # 3) smaller bounded change set
        # 4) lower risk penalty
        # 5) stable deterministic fallback by agent_id (alphabetical)
        return (
            score.total,
            task_outcome.tests_passed,
            -len(task_outcome.files_changed or []),
            -score.risk_penalty,
            score.agent_id,
        )

    @staticmethod
    def _tie_break_reason(
        ranked: list[tuple[CandidateScore, AgentResult, TaskOutcome]],
    ) -> str | None:
        if len(ranked) < 2:
            return None
        best = ranked[0]
        second = ranked[1]
        if abs(best[0].total - second[0].total) > 1e-9:
            return None
        if best[2].tests_passed != second[2].tests_passed:
            return "tests_passed_preference"
        if len(best[2].files_changed or []) != len(second[2].files_changed or []):
            return "smaller_change_set_preference"
        if abs(best[0].risk_penalty - second[0].risk_penalty) > 1e-9:
            return "lower_risk_penalty_preference"
        return "stable_agent_order_preference"

    def _score_candidate(
        self,
        agent_id: str,
        agent_result: AgentResult,
        task_outcome: TaskOutcome,
        retrieval_confidence: float,
    ) -> CandidateScore:
        notes: list[str] = []

        tests_signal = 0.70 if task_outcome.tests_passed and agent_result.status == "success" else 0.0
        if tests_signal:
            notes.append("tests_passed")

        file_count = len(task_outcome.files_changed or [])
        output_signal = 0.0
        if file_count > 0:
            output_signal = min(0.20, 0.04 * min(file_count, 5))
            notes.append(f"produced_files={file_count}")
            if file_count <= self.soft_file_limit:
                output_signal += 0.05
                notes.append("bounded_change_set")

        reliability_signal = 0.0
        if agent_result.status == "success":
            reliability_signal += 0.05
            if retrieval_confidence >= 0.75:
                reliability_signal += 0.05
                notes.append("high_retrieval_confidence")

        risk_penalty = 0.0
        if file_count == 0:
            risk_penalty += 0.30
            notes.append("no_artifacts")
        if file_count > self.soft_file_limit:
            risk_penalty += 0.10
            notes.append("large_change_set")
        if task_outcome.failure_reason:
            risk_penalty += 0.20
            notes.append(f"failure_reason={task_outcome.failure_reason}")
        if agent_result.status != "success":
            risk_penalty += 0.20
            notes.append(f"agent_status={agent_result.status}")

        total = tests_signal + output_signal + reliability_signal - risk_penalty
        return CandidateScore(
            agent_id=agent_id,
            total=total,
            tests_signal=tests_signal,
            output_signal=output_signal,
            reliability_signal=reliability_signal,
            risk_penalty=risk_penalty,
            notes=notes,
        )
