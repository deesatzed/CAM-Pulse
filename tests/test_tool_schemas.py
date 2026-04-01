"""Tests for claw.tools.schemas — Pydantic validation + MCP schema generation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from claw.tools.schemas import (
    EscalateInput,
    QueryMemoryInput,
    RequestSpecialistInput,
    StoreFindingInput,
    TOOL_METADATA,
    VerifyClaimInput,
    generate_mcp_tool_schemas,
    validate_tool_input,
)


# ---------------------------------------------------------------------------
# QueryMemoryInput
# ---------------------------------------------------------------------------

class TestQueryMemoryInput:
    def test_valid_minimal(self):
        m = QueryMemoryInput(query="retry logic")
        assert m.query == "retry logic"
        assert m.limit == 3
        assert m.language is None

    def test_valid_full(self):
        m = QueryMemoryInput(query="retry", limit=10, language="python")
        assert m.limit == 10
        assert m.language == "python"

    def test_missing_query_raises(self):
        with pytest.raises(ValidationError):
            QueryMemoryInput()  # type: ignore[call-arg]

    def test_limit_below_range(self):
        with pytest.raises(ValidationError):
            QueryMemoryInput(query="x", limit=0)

    def test_limit_above_range(self):
        with pytest.raises(ValidationError):
            QueryMemoryInput(query="x", limit=21)

    def test_limit_boundary_low(self):
        m = QueryMemoryInput(query="x", limit=1)
        assert m.limit == 1

    def test_limit_boundary_high(self):
        m = QueryMemoryInput(query="x", limit=20)
        assert m.limit == 20


# ---------------------------------------------------------------------------
# StoreFindingInput
# ---------------------------------------------------------------------------

class TestStoreFindingInput:
    def test_valid_minimal(self):
        m = StoreFindingInput(problem_description="disk full", solution_code="rm -rf /tmp/*")
        assert m.tags == []
        assert m.methodology_type is None

    def test_valid_full(self):
        m = StoreFindingInput(
            problem_description="disk full",
            solution_code="rm -rf /tmp/*",
            tags=["ops", "disk"],
            methodology_type="FIX",
        )
        assert m.tags == ["ops", "disk"]
        assert m.methodology_type == "FIX"

    def test_missing_required_raises(self):
        with pytest.raises(ValidationError):
            StoreFindingInput(problem_description="disk full")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# VerifyClaimInput
# ---------------------------------------------------------------------------

class TestVerifyClaimInput:
    def test_valid_minimal(self):
        m = VerifyClaimInput(claim="all tests pass")
        assert m.workspace_dir is None

    def test_valid_with_workspace(self):
        m = VerifyClaimInput(claim="all tests pass", workspace_dir="/tmp/ws")
        assert m.workspace_dir == "/tmp/ws"

    def test_missing_claim_raises(self):
        with pytest.raises(ValidationError):
            VerifyClaimInput()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# RequestSpecialistInput
# ---------------------------------------------------------------------------

class TestRequestSpecialistInput:
    def test_valid_minimal(self):
        m = RequestSpecialistInput(task_description="summarize file")
        assert m.preferred_agent is None

    def test_valid_agents(self):
        for agent in ("claude", "codex", "gemini", "grok"):
            m = RequestSpecialistInput(task_description="t", preferred_agent=agent)
            assert m.preferred_agent == agent

    def test_invalid_agent_raises(self):
        with pytest.raises(ValidationError):
            RequestSpecialistInput(task_description="t", preferred_agent="chatgpt")


# ---------------------------------------------------------------------------
# EscalateInput
# ---------------------------------------------------------------------------

class TestEscalateInput:
    def test_valid_minimal(self):
        m = EscalateInput(reason="requires database DBA access")
        assert m.context is None
        assert m.task_id is None

    def test_valid_full(self):
        m = EscalateInput(
            reason="need DBA",
            context={"tables": ["users", "orders"]},
            task_id="task-42",
        )
        assert m.context == {"tables": ["users", "orders"]}
        assert m.task_id == "task-42"

    def test_missing_reason_raises(self):
        with pytest.raises(ValidationError):
            EscalateInput()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# generate_mcp_tool_schemas
# ---------------------------------------------------------------------------

class TestGenerateMCPToolSchemas:
    def test_returns_list(self):
        schemas = generate_mcp_tool_schemas()
        assert isinstance(schemas, list)
        assert len(schemas) == len(TOOL_METADATA)

    def test_each_schema_has_required_keys(self):
        for schema in generate_mcp_tool_schemas():
            assert "name" in schema
            assert "description" in schema
            assert "inputSchema" in schema

    def test_names_match_metadata_keys(self):
        names = {s["name"] for s in generate_mcp_tool_schemas()}
        assert names == set(TOOL_METADATA.keys())

    def test_input_schema_has_properties(self):
        for schema in generate_mcp_tool_schemas():
            input_schema = schema["inputSchema"]
            assert "properties" in input_schema
            assert "type" in input_schema
            assert input_schema["type"] == "object"

    def test_query_memory_schema_fields(self):
        schemas = {s["name"]: s for s in generate_mcp_tool_schemas()}
        qm = schemas["claw_query_memory"]["inputSchema"]
        assert "query" in qm["properties"]
        assert "limit" in qm["properties"]
        assert "language" in qm["properties"]

    def test_required_fields_present(self):
        schemas = {s["name"]: s for s in generate_mcp_tool_schemas()}
        qm = schemas["claw_query_memory"]["inputSchema"]
        assert "query" in qm.get("required", [])


# ---------------------------------------------------------------------------
# validate_tool_input
# ---------------------------------------------------------------------------

class TestValidateToolInput:
    def test_valid_input(self):
        result = validate_tool_input("claw_query_memory", {"query": "retry logic"})
        assert isinstance(result, QueryMemoryInput)
        assert result.query == "retry logic"

    def test_unknown_tool_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown tool"):
            validate_tool_input("claw_nonexistent", {"query": "x"})

    def test_invalid_args_raises_validation_error(self):
        with pytest.raises(ValidationError):
            validate_tool_input("claw_query_memory", {})  # missing query

    def test_extra_fields_ignored(self):
        result = validate_tool_input("claw_query_memory", {"query": "x", "bogus": 99})
        assert result.query == "x"

    def test_all_tools_validate_with_required_args(self):
        """Smoke test: every registered tool can be validated with minimal args."""
        minimal_args = {
            "claw_query_memory": {"query": "test"},
            "claw_store_finding": {"problem_description": "p", "solution_code": "s"},
            "claw_verify_claim": {"claim": "tests pass"},
            "claw_request_specialist": {"task_description": "summarize"},
            "claw_escalate": {"reason": "need human"},
        }
        for tool_name, args in minimal_args.items():
            result = validate_tool_input(tool_name, args)
            assert result is not None
