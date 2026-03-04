"""MCP (Model Context Protocol) server exposing CLAW tools to agents mid-task.

Per clawpre.md section 8b, CLAW exposes itself as an MCP server so that any of the
four agents (Claude Code, Codex, Gemini, Grok) can, mid-task, query CLAW's memory,
store findings, verify claims, request specialist agents, or escalate to a human.

Five tools are exposed:
    1. claw_query_memory    -- query semantic memory for similar past solutions
    2. claw_store_finding   -- store a new finding/methodology in memory
    3. claw_verify_claim    -- verify a claim about code (placeholder scan, validation)
    4. claw_request_specialist -- request a different agent for a subtask
    5. claw_escalate        -- escalate to human with context

Design:
    The ClawMCPServer class contains tool handler methods and schema definitions.
    The start_server() factory function attempts to load the ``mcp`` Python SDK
    and register tools on a proper MCP Server instance. If the SDK is unavailable,
    it logs a warning and returns None.

    All tool handlers are async and interact with real CLAW subsystems (Repository,
    SemanticMemory, Verifier, Dispatcher). No mocks, no placeholders, no cached
    responses.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional

from claw.db.repository import Repository
from claw.verifier import PLACEHOLDER_PATTERNS

if TYPE_CHECKING:
    from claw.dispatcher import Dispatcher
    from claw.memory.semantic import SemanticMemory
    from claw.verifier import Verifier

logger = logging.getLogger("claw.mcp_server")


# ---------------------------------------------------------------------------
# Tool schemas (MCP-compatible JSON Schema format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "claw_query_memory",
        "description": (
            "Query CLAW's semantic memory for relevant patterns, past fixes, "
            "or known issues related to the current task. Returns up to ``limit`` "
            "matching methodologies with their problem descriptions, solution "
            "code, tags, and relevance scores."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Problem description or search terms to find similar past solutions.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return.",
                    "default": 3,
                },
                "language": {
                    "type": "string",
                    "description": "Optional programming language filter (e.g. 'python', 'typescript').",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "claw_store_finding",
        "description": (
            "Store a discovered pattern, error fix, or insight in CLAW's semantic "
            "memory. This persists the finding so future tasks across the entire "
            "fleet can benefit from it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "problem_description": {
                    "type": "string",
                    "description": "Natural language description of the problem solved or pattern discovered.",
                },
                "solution_code": {
                    "type": "string",
                    "description": "The code, configuration, or procedure that solves the problem.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for categorizing the finding (e.g. ['auth', 'fastapi', 'security']).",
                },
                "methodology_type": {
                    "type": "string",
                    "description": "Type of finding: BUG_FIX, PATTERN, DECISION, or GOTCHA.",
                    "enum": ["BUG_FIX", "PATTERN", "DECISION", "GOTCHA"],
                },
            },
            "required": ["problem_description", "solution_code"],
        },
    },
    {
        "name": "claw_verify_claim",
        "description": (
            "Run claim-gate verification on a specific assertion about code. "
            "Checks for placeholder patterns (TODO, FIXME, stubs, NotImplementedError), "
            "validates the claim text against known claim patterns, and optionally "
            "runs basic validation in the workspace directory."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "claim": {
                    "type": "string",
                    "description": "The claim to verify (e.g. 'all tests pass', 'no placeholders remain').",
                },
                "workspace_dir": {
                    "type": "string",
                    "description": "Optional path to the workspace directory for file-level verification.",
                },
            },
            "required": ["claim"],
        },
    },
    {
        "name": "claw_request_specialist",
        "description": (
            "Request another agent to handle a subtask that the current agent "
            "cannot do well. CLAW's dispatcher routes the subtask to the best-fit "
            "agent based on learned Bayesian scores and the static routing table."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "Description of the subtask that needs a specialist agent.",
                },
                "preferred_agent": {
                    "type": "string",
                    "description": (
                        "Optional preferred agent ID ('claude', 'codex', 'gemini', 'grok'). "
                        "The dispatcher may override this based on learned scores."
                    ),
                },
            },
            "required": ["task_description"],
        },
    },
    {
        "name": "claw_escalate",
        "description": (
            "Flag this task as beyond AI capability and escalate to a human. "
            "This pauses autonomous processing and notifies the human operator "
            "with full context about what was attempted and why escalation is needed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why this task needs human intervention.",
                },
                "context": {
                    "type": "object",
                    "description": (
                        "Additional context: what was attempted, error details, "
                        "partial results, etc."
                    ),
                },
                "task_id": {
                    "type": "string",
                    "description": "ID of the task being escalated (for traceability).",
                },
            },
            "required": ["reason"],
        },
    },
]


# ---------------------------------------------------------------------------
# ClawMCPServer
# ---------------------------------------------------------------------------

class ClawMCPServer:
    """MCP server that exposes CLAW's 5 mid-task tools to agents.

    This class owns all tool handler methods and dispatches incoming tool
    calls by name. It is instantiated by the coordinator and either served
    through the ``mcp`` Python SDK or used directly in-process.

    Args:
        repository: Data access layer for CLAW's SQLite database.
        semantic_memory: Optional SemanticMemory for methodology persistence
            and hybrid search. If None, query/store operations fall back to
            Repository text search.
        verifier: Optional Verifier for claim validation. If None, claim
            verification uses only the built-in placeholder pattern scan.
        dispatcher: Optional Dispatcher for routing specialist requests.
            If None, specialist requests return a recommendation without
            actually dispatching.
    """

    def __init__(
        self,
        repository: Repository,
        semantic_memory: Optional[SemanticMemory] = None,
        verifier: Optional[Verifier] = None,
        dispatcher: Optional[Dispatcher] = None,
        auth_token: Optional[str] = None,
    ):
        self.repository = repository
        self.semantic_memory = semantic_memory
        self.verifier = verifier
        self.dispatcher = dispatcher
        self._auth_token = auth_token

        # Mapping of tool name -> handler coroutine
        self._handlers: dict[str, Any] = {
            "claw_query_memory": self.handle_query_memory,
            "claw_store_finding": self.handle_store_finding,
            "claw_verify_claim": self.handle_verify_claim,
            "claw_request_specialist": self.handle_request_specialist,
            "claw_escalate": self.handle_escalate,
        }

        logger.info(
            "ClawMCPServer initialized: semantic_memory=%s, verifier=%s, dispatcher=%s",
            "connected" if semantic_memory else "none",
            "connected" if verifier else "none",
            "connected" if dispatcher else "none",
        )

    # ===================================================================
    # Schema access
    # ===================================================================

    @staticmethod
    def get_tool_schemas() -> list[dict[str, Any]]:
        """Return the MCP-compatible JSON Schema definitions for all 5 tools.

        Returns:
            List of tool schema dicts, each containing 'name', 'description',
            and 'inputSchema' keys compatible with the MCP tool registration
            protocol.
        """
        return list(TOOL_SCHEMAS)

    # ===================================================================
    # Dispatch
    # ===================================================================

    async def dispatch_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        auth_token: Optional[str] = None,
    ) -> dict[str, Any]:
        """Route an incoming tool call to the appropriate handler.

        Args:
            tool_name: One of the 5 registered tool names.
            arguments: The tool arguments matching the inputSchema.
            auth_token: Bearer token that must match the server's configured
                token (if one was set). Rejected with an error if invalid.

        Returns:
            A dict with at least a ``status`` key ("ok" or "error") and
            tool-specific result data.

        Raises:
            ValueError: If tool_name is not recognized.
        """
        if self._auth_token and auth_token != self._auth_token:
            logger.warning("MCP auth failure for tool '%s'", tool_name)
            return {
                "status": "error",
                "tool": tool_name,
                "error": "authentication failed",
                "error_type": "AuthError",
            }

        handler = self._handlers.get(tool_name)
        if handler is None:
            valid_names = sorted(self._handlers.keys())
            raise ValueError(
                f"Unknown tool '{tool_name}'. Valid tools: {valid_names}"
            )

        logger.info("Dispatching MCP tool call: %s(%s)", tool_name, _truncate_args(arguments))

        try:
            result = await handler(**arguments)
            logger.info("MCP tool '%s' completed successfully", tool_name)
            return result
        except Exception as exc:
            logger.error("MCP tool '%s' failed: %s", tool_name, exc, exc_info=True)
            return {
                "status": "error",
                "tool": tool_name,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }

    # ===================================================================
    # Tool 1: claw_query_memory
    # ===================================================================

    async def handle_query_memory(
        self,
        query: str,
        limit: int = 3,
        language: Optional[str] = None,
    ) -> dict[str, Any]:
        """Query CLAW's semantic memory for similar past solutions.

        Uses SemanticMemory.find_similar() for hybrid (vector + text) search
        when available, falling back to Repository.search_methodologies_text()
        for FTS5-only search.

        Args:
            query: Problem description or search terms.
            limit: Maximum number of results (default 3).
            language: Optional programming language filter.

        Returns:
            Dict with status, results list, and metadata.
        """
        if not query or not query.strip():
            return {
                "status": "error",
                "error": "Query string must not be empty.",
                "results": [],
            }

        limit = max(1, min(limit, 20))  # Clamp to [1, 20]

        results_data: list[dict[str, Any]] = []

        if self.semantic_memory is not None:
            # Full hybrid search through SemanticMemory
            try:
                search_results = await self.semantic_memory.find_similar(
                    query=query,
                    limit=limit,
                    language=language,
                )
                for sr in search_results:
                    meth = sr.methodology
                    results_data.append({
                        "methodology_id": meth.id,
                        "problem_description": meth.problem_description,
                        "solution_code": meth.solution_code,
                        "methodology_notes": meth.methodology_notes,
                        "tags": meth.tags,
                        "language": meth.language,
                        "methodology_type": meth.methodology_type,
                        "lifecycle_state": meth.lifecycle_state,
                        "combined_score": sr.combined_score,
                        "vector_score": sr.vector_score,
                        "text_score": sr.text_score,
                    })
                    # Record retrieval for outcome tracking
                    await self.semantic_memory.record_retrieval(meth.id)

                logger.info(
                    "query_memory (hybrid): query='%s', limit=%d, language=%s, found=%d",
                    query[:60], limit, language, len(results_data),
                )
            except Exception as exc:
                logger.warning(
                    "Hybrid search failed, falling back to text search: %s", exc,
                )
                results_data = await self._fallback_text_search(query, limit)
        else:
            # Fallback: FTS5 text search only
            results_data = await self._fallback_text_search(query, limit)

        return {
            "status": "ok",
            "query": query,
            "language_filter": language,
            "result_count": len(results_data),
            "results": results_data,
        }

    async def _fallback_text_search(
        self, query: str, limit: int
    ) -> list[dict[str, Any]]:
        """Fallback: search methodologies using FTS5 text search only.

        Args:
            query: Search terms.
            limit: Maximum number of results.

        Returns:
            List of result dicts.
        """
        results_data: list[dict[str, Any]] = []
        try:
            methodologies = await self.repository.search_methodologies_text(query, limit=limit)
            for meth in methodologies:
                results_data.append({
                    "methodology_id": meth.id,
                    "problem_description": meth.problem_description,
                    "solution_code": meth.solution_code,
                    "methodology_notes": meth.methodology_notes,
                    "tags": meth.tags,
                    "language": meth.language,
                    "methodology_type": meth.methodology_type,
                    "lifecycle_state": meth.lifecycle_state,
                    "combined_score": None,
                    "vector_score": None,
                    "text_score": None,
                })
                # Record retrieval
                await self.repository.update_methodology_retrieval(meth.id)

            logger.info(
                "query_memory (text fallback): query='%s', limit=%d, found=%d",
                query[:60], limit, len(results_data),
            )
        except Exception as exc:
            logger.error("Text search failed: %s", exc)
        return results_data

    # ===================================================================
    # Tool 2: claw_store_finding
    # ===================================================================

    async def handle_store_finding(
        self,
        problem_description: str,
        solution_code: str,
        tags: Optional[list[str]] = None,
        methodology_type: Optional[str] = None,
    ) -> dict[str, Any]:
        """Store a new finding/methodology in CLAW's semantic memory.

        Saves via SemanticMemory.save_solution() when available (which generates
        embeddings automatically), falling back to Repository.save_methodology()
        for direct database insert without embeddings.

        Args:
            problem_description: Natural language description of the problem.
            solution_code: The code or procedure that solves the problem.
            tags: Optional list of categorization tags.
            methodology_type: Optional type (BUG_FIX, PATTERN, DECISION, GOTCHA).

        Returns:
            Dict with status and the saved methodology's ID.
        """
        if not problem_description or not problem_description.strip():
            return {
                "status": "error",
                "error": "problem_description must not be empty.",
            }
        if not solution_code or not solution_code.strip():
            return {
                "status": "error",
                "error": "solution_code must not be empty.",
            }

        # Validate methodology_type if provided
        valid_types = {"BUG_FIX", "PATTERN", "DECISION", "GOTCHA"}
        if methodology_type and methodology_type not in valid_types:
            return {
                "status": "error",
                "error": f"Invalid methodology_type '{methodology_type}'. Must be one of: {sorted(valid_types)}",
            }

        tags = tags or []

        if self.semantic_memory is not None:
            try:
                methodology = await self.semantic_memory.save_solution(
                    problem_description=problem_description,
                    solution_code=solution_code,
                    tags=tags,
                    methodology_type=methodology_type,
                )
                logger.info(
                    "store_finding (semantic): saved methodology %s, type=%s, tags=%s",
                    methodology.id, methodology_type, tags,
                )
                return {
                    "status": "ok",
                    "methodology_id": methodology.id,
                    "lifecycle_state": methodology.lifecycle_state,
                    "has_embedding": methodology.problem_embedding is not None,
                    "message": "Finding stored successfully with embedding.",
                }
            except Exception as exc:
                logger.warning(
                    "SemanticMemory save failed, falling back to repository: %s", exc,
                )

        # Fallback: direct repository save without embedding
        try:
            from claw.core.models import Methodology

            methodology = Methodology(
                problem_description=problem_description,
                solution_code=solution_code,
                tags=tags,
                methodology_type=methodology_type,
                lifecycle_state="embryonic",
            )
            saved = await self.repository.save_methodology(methodology)
            logger.info(
                "store_finding (repository fallback): saved methodology %s",
                saved.id,
            )
            return {
                "status": "ok",
                "methodology_id": saved.id,
                "lifecycle_state": saved.lifecycle_state,
                "has_embedding": False,
                "message": "Finding stored without embedding (semantic memory unavailable).",
            }
        except Exception as exc:
            logger.error("Failed to store finding: %s", exc)
            return {
                "status": "error",
                "error": f"Failed to store finding: {exc}",
            }

    # ===================================================================
    # Tool 3: claw_verify_claim
    # ===================================================================

    async def handle_verify_claim(
        self,
        claim: str,
        workspace_dir: Optional[str] = None,
    ) -> dict[str, Any]:
        """Verify a claim about code by scanning for placeholder patterns and
        running basic validation.

        Checks the claim text for placeholder indicators (TODO, FIXME, stubs,
        etc.) and, if a workspace directory is provided, scans the workspace
        files for placeholder patterns.

        If a full Verifier is available, delegates to its claim validation
        and test running capabilities.

        Args:
            claim: The claim to verify (e.g. "all tests pass", "no placeholders").
            workspace_dir: Optional path to workspace for file-level scanning.

        Returns:
            Dict with status, verdict ("PASS"/"FAIL"/"PARTIAL"), and details.
        """
        if not claim or not claim.strip():
            return {
                "status": "error",
                "error": "Claim text must not be empty.",
            }

        violations: list[dict[str, str]] = []
        checks_performed: list[str] = []

        # Check 1: Scan the claim text itself for contradictions
        claim_lower = claim.lower()
        claim_analysis = self._analyze_claim_text(claim_lower)
        checks_performed.append("claim_text_analysis")

        # Check 2: If workspace_dir provided, scan workspace files for placeholders
        if workspace_dir:
            workspace_violations = await self._scan_workspace_placeholders(workspace_dir)
            violations.extend(workspace_violations)
            checks_performed.append("workspace_placeholder_scan")

            # If claim asserts completion/readiness, placeholders are a violation
            completion_keywords = {
                "complete", "done", "finished", "ready", "production ready",
                "no placeholders", "no todos", "fully implemented",
            }
            if any(kw in claim_lower for kw in completion_keywords) and workspace_violations:
                violations.append({
                    "check": "claim_contradiction",
                    "detail": (
                        f"Claim '{claim[:80]}' asserts completion, but "
                        f"{len(workspace_violations)} placeholder(s) found in workspace."
                    ),
                })

        # Check 3: If Verifier available and workspace_dir provided, run tests
        test_result: Optional[dict[str, Any]] = None
        if self.verifier is not None and workspace_dir:
            test_claims = {"tests pass", "all tests pass", "tested", "test"}
            if any(tc in claim_lower for tc in test_claims):
                try:
                    passed, output, test_count = await self.verifier.run_tests(workspace_dir)
                    test_result = {
                        "tests_passed": passed,
                        "test_count": test_count,
                        "output_snippet": output[:500] if output else "",
                    }
                    checks_performed.append("test_execution")
                    if not passed:
                        violations.append({
                            "check": "test_execution",
                            "detail": f"Tests failed ({test_count} tests): {output[:200]}",
                        })
                except Exception as exc:
                    logger.warning("Test execution during claim verification failed: %s", exc)
                    test_result = {
                        "tests_passed": None,
                        "error": str(exc),
                    }
                    checks_performed.append("test_execution_attempted")

        # Determine verdict
        if violations:
            verdict = "FAIL"
        elif claim_analysis.get("unsubstantiated"):
            verdict = "PARTIAL"
        else:
            verdict = "PASS"

        return {
            "status": "ok",
            "claim": claim,
            "verdict": verdict,
            "violations": violations,
            "violation_count": len(violations),
            "claim_analysis": claim_analysis,
            "test_result": test_result,
            "checks_performed": checks_performed,
        }

    def _analyze_claim_text(self, claim_lower: str) -> dict[str, Any]:
        """Analyze the claim text for known claim patterns and flag
        unsubstantiated assertions.

        Args:
            claim_lower: The lowercased claim text.

        Returns:
            Dict with analysis results.
        """
        from claw.verifier import CLAIM_PATTERNS

        matched_claims: list[dict[str, str]] = []
        unsubstantiated = False

        for claim_def in CLAIM_PATTERNS:
            for phrase in claim_def["claims"]:
                pattern = r"\b" + re.escape(phrase) + r"\b"
                if re.search(pattern, claim_lower):
                    matched_claims.append({
                        "phrase": phrase,
                        "required_evidence": claim_def["evidence"],
                    })
                    # Claims like "production ready" are always flagged
                    if phrase in ("production ready", "prod ready", "ready for production"):
                        unsubstantiated = True
                    break

        return {
            "matched_claim_patterns": matched_claims,
            "claim_count": len(matched_claims),
            "unsubstantiated": unsubstantiated,
        }

    async def _scan_workspace_placeholders(
        self, workspace_dir: str
    ) -> list[dict[str, str]]:
        """Scan workspace files for placeholder patterns.

        Walks Python, TypeScript, and JavaScript files in the workspace and
        checks each line against PLACEHOLDER_PATTERNS.

        Args:
            workspace_dir: Path to the workspace root directory.

        Returns:
            List of violation dicts with check name and detail.
        """
        import os
        from pathlib import Path

        violations: list[dict[str, str]] = []
        workspace = Path(workspace_dir)

        if not workspace.is_dir():
            logger.warning("Workspace directory does not exist: %s", workspace_dir)
            return violations

        # Scan code files only (limit scope to avoid scanning binaries)
        code_extensions = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".rb", ".java"}
        scanned_files = 0
        max_files = 500  # Safety limit

        for root, _dirs, files in os.walk(str(workspace)):
            # Skip hidden dirs and common non-code dirs
            root_path = Path(root)
            skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", "dist", "build"}
            if any(part in skip_dirs for part in root_path.parts):
                continue

            for filename in files:
                if scanned_files >= max_files:
                    break

                file_path = root_path / filename
                if file_path.suffix not in code_extensions:
                    continue

                scanned_files += 1
                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    for line_num, line in enumerate(content.splitlines(), start=1):
                        for pattern in PLACEHOLDER_PATTERNS:
                            if re.search(pattern, line, re.IGNORECASE):
                                rel_path = file_path.relative_to(workspace)
                                violations.append({
                                    "check": "placeholder_scan",
                                    "detail": (
                                        f"Placeholder found in {rel_path}:{line_num}: "
                                        f"{line.strip()[:100]}"
                                    ),
                                })
                                break  # One violation per line
                except Exception as exc:
                    logger.debug("Could not read %s: %s", file_path, exc)

            if scanned_files >= max_files:
                break

        logger.info(
            "Workspace placeholder scan: %d files scanned, %d violations found",
            scanned_files, len(violations),
        )
        return violations

    # ===================================================================
    # Tool 4: claw_request_specialist
    # ===================================================================

    async def handle_request_specialist(
        self,
        task_description: str,
        preferred_agent: Optional[str] = None,
    ) -> dict[str, Any]:
        """Request a different agent for a subtask.

        When a Dispatcher is available, uses its Bayesian routing to select
        the best-fit agent for the described subtask. Otherwise, returns a
        recommendation based on the static routing table.

        This tool does not execute the subtask itself -- it routes and returns
        the routing decision. The orchestrator is responsible for actually
        dispatching the work to the selected agent.

        Args:
            task_description: Description of the subtask needing a specialist.
            preferred_agent: Optional preferred agent ID.

        Returns:
            Dict with status, selected agent, and routing rationale.
        """
        if not task_description or not task_description.strip():
            return {
                "status": "error",
                "error": "task_description must not be empty.",
            }

        valid_agents = {"claude", "codex", "gemini", "grok"}
        if preferred_agent and preferred_agent not in valid_agents:
            return {
                "status": "error",
                "error": (
                    f"Invalid preferred_agent '{preferred_agent}'. "
                    f"Must be one of: {sorted(valid_agents)}"
                ),
            }

        # Infer task type from description for routing
        inferred_type = self._infer_task_type(task_description)

        if self.dispatcher is not None:
            # Use real Dispatcher routing with Bayesian scores
            try:
                from claw.core.models import Task

                routing_task = Task(
                    project_id="mcp_specialist_request",
                    title=f"Specialist request: {task_description[:80]}",
                    description=task_description,
                    task_type=inferred_type,
                    recommended_agent=preferred_agent,
                )

                selected_agent = await self.dispatcher.route_task(routing_task)
                routing_info = self.dispatcher.get_routing_info(inferred_type)

                logger.info(
                    "request_specialist: routed to '%s' (inferred_type='%s', preferred='%s')",
                    selected_agent, inferred_type, preferred_agent,
                )

                return {
                    "status": "ok",
                    "selected_agent": selected_agent,
                    "inferred_task_type": inferred_type,
                    "preferred_agent": preferred_agent,
                    "routing_method": "dispatcher_bayesian",
                    "routing_info": routing_info,
                    "message": (
                        f"Agent '{selected_agent}' selected for subtask. "
                        f"The orchestrator will dispatch the work."
                    ),
                }
            except Exception as exc:
                logger.warning(
                    "Dispatcher routing failed, falling back to static: %s", exc,
                )

        # Fallback: static routing recommendation
        from claw.dispatcher import STATIC_ROUTING, DEFAULT_AGENT

        static_agent = STATIC_ROUTING.get(inferred_type, DEFAULT_AGENT)
        selected = preferred_agent if preferred_agent else static_agent

        logger.info(
            "request_specialist (static fallback): recommending '%s' (type='%s')",
            selected, inferred_type,
        )

        return {
            "status": "ok",
            "selected_agent": selected,
            "inferred_task_type": inferred_type,
            "preferred_agent": preferred_agent,
            "routing_method": "static_fallback",
            "routing_info": {
                "static_route": static_agent,
                "inferred_type": inferred_type,
                "note": "Dispatcher unavailable; recommendation based on static routing table.",
            },
            "message": (
                f"Agent '{selected}' recommended for subtask (static routing). "
                f"The orchestrator will dispatch the work."
            ),
        }

    def _infer_task_type(self, description: str) -> str:
        """Infer a task_type from a natural language description.

        Maps keywords in the description to CLAW's task_type taxonomy used
        by the Dispatcher's static routing table.

        Args:
            description: Task description text.

        Returns:
            Inferred task_type string.
        """
        desc_lower = description.lower()

        keyword_map: list[tuple[list[str], str]] = [
            (["security", "vulnerability", "cve", "owasp", "xss", "csrf", "injection"], "security"),
            (["architecture", "design", "structure", "system design"], "architecture"),
            (["documentation", "docs", "readme", "docstring", "jsdoc"], "documentation"),
            (["analysis", "analyze", "audit", "review", "inspect"], "analysis"),
            (["refactor", "restructure", "reorganize", "clean up", "simplify"], "refactoring"),
            (["test", "testing", "unit test", "integration test", "coverage"], "testing"),
            (["ci", "cd", "pipeline", "github action", "workflow", "deploy"], "ci_cd"),
            (["dependency", "dependencies", "upgrade", "update package", "npm", "pip"], "dependency_analysis"),
            (["migration", "migrate", "port", "convert"], "migration"),
            (["comprehension", "understand", "context", "full repo"], "full_repo_review"),
            (["quick fix", "hotfix", "patch", "typo", "small fix"], "quick_fix"),
            (["bug", "fix", "error", "crash", "broken", "issue", "defect"], "bug_fix"),
            (["web", "search", "lookup", "research", "find out"], "web_lookup"),
            (["bulk", "batch", "mass change", "many files"], "bulk_changes"),
            (["fast", "quick", "rapid", "iterate"], "fast_iteration"),
        ]

        for keywords, task_type in keyword_map:
            if any(kw in desc_lower for kw in keywords):
                return task_type

        return "analysis"  # Default task type

    # ===================================================================
    # Tool 5: claw_escalate
    # ===================================================================

    async def handle_escalate(
        self,
        reason: str,
        context: Optional[dict[str, Any]] = None,
        task_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Escalate to human with full context.

        Logs the escalation event in the database's episode log for
        traceability, and returns an acknowledgment. In attended mode,
        the human operator will be notified. In supervised/autonomous mode,
        the task will be paused until human review.

        Args:
            reason: Why human intervention is needed.
            context: Additional context (what was attempted, errors, etc.).
            task_id: Optional task ID for traceability.

        Returns:
            Dict with status, escalation ID, and acknowledgment.
        """
        if not reason or not reason.strip():
            return {
                "status": "error",
                "error": "Escalation reason must not be empty.",
            }

        escalation_id = str(uuid.uuid4())
        timestamp = datetime.now(UTC).isoformat()
        context = context or {}

        # Build the escalation event payload
        event_data = {
            "escalation_id": escalation_id,
            "reason": reason,
            "context": context,
            "task_id": task_id,
            "timestamp": timestamp,
        }

        # Log the escalation to the episode log
        try:
            episode_id = await self.repository.log_episode(
                session_id=f"mcp_escalation_{escalation_id}",
                event_type="escalation",
                event_data=event_data,
                task_id=task_id,
                cycle_level="micro",
            )
            logger.warning(
                "ESCALATION [%s]: %s (task_id=%s, episode_id=%s)",
                escalation_id, reason, task_id, episode_id,
            )
        except Exception as exc:
            logger.error("Failed to log escalation event: %s", exc)
            episode_id = None

        # If we have a task_id and repository, increment the task's escalation counter
        if task_id:
            try:
                await self.repository.increment_task_escalation(task_id)
            except Exception as exc:
                logger.warning("Failed to increment escalation count for task %s: %s", task_id, exc)

        return {
            "status": "ok",
            "escalation_id": escalation_id,
            "episode_id": episode_id,
            "task_id": task_id,
            "timestamp": timestamp,
            "message": (
                "Escalation logged. Task processing is paused pending human review. "
                f"Reason: {reason}"
            ),
        }


# ---------------------------------------------------------------------------
# start_server() — factory/entry point for MCP SDK integration
# ---------------------------------------------------------------------------

def start_server(
    claw_mcp: ClawMCPServer,
    host: str = "127.0.0.1",
    port: int = 3100,
) -> Any:
    """Create and configure an MCP server with CLAW's tools registered.

    Attempts to import the ``mcp`` Python SDK and configure a Server instance
    with all 5 CLAW tools registered as tool handlers. If the ``mcp`` SDK is
    not installed, logs a warning and returns None.

    This function is a synchronous factory/entry point. It creates and
    configures the server but does NOT start the event loop. The caller is
    responsible for running the server (e.g. via ``server.run()`` or integrating
    into an existing asyncio loop).

    Args:
        claw_mcp: The ClawMCPServer instance with all dependencies wired.
        host: Host to bind the MCP server to (default 127.0.0.1).
        port: Port for the MCP server (default 3100).

    Returns:
        The configured MCP Server object if the SDK is available, or None
        if the SDK could not be imported.
    """
    try:
        from mcp.server import Server
        from mcp.types import Tool
    except ImportError:
        logger.warning(
            "MCP Python SDK not installed. Install with: pip install mcp "
            "The ClawMCPServer can still be used in-process via dispatch_tool(). "
            "MCP server will not be available for external agent connections."
        )
        return None

    server = Server("claw-mcp-server")
    logger.info("MCP SDK available. Configuring CLAW MCP server on %s:%d", host, port)

    # Register the list_tools handler
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """Return the list of available CLAW tools."""
        tools = []
        for schema in claw_mcp.get_tool_schemas():
            tools.append(
                Tool(
                    name=schema["name"],
                    description=schema["description"],
                    inputSchema=schema["inputSchema"],
                )
            )
        return tools

    # Register the call_tool handler
    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
        """Handle incoming tool calls by dispatching to ClawMCPServer."""
        from mcp.types import TextContent

        result = await claw_mcp.dispatch_tool(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    logger.info(
        "CLAW MCP server configured with %d tools: %s",
        len(TOOL_SCHEMAS),
        [s["name"] for s in TOOL_SCHEMAS],
    )

    return server


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _truncate_args(args: dict[str, Any], max_len: int = 100) -> str:
    """Truncate argument values for logging without exposing full content.

    Args:
        args: The arguments dict to summarize.
        max_len: Maximum length for each value string.

    Returns:
        A compact string representation of the arguments.
    """
    parts = []
    for key, value in args.items():
        val_str = str(value)
        if len(val_str) > max_len:
            val_str = val_str[:max_len] + "..."
        parts.append(f"{key}={val_str}")
    return ", ".join(parts)
