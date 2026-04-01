"""Pydantic input schemas for CLAW MCP tools.

Each MCP tool has a corresponding Pydantic model that validates input
parameters and generates JSON Schema for the MCP protocol.  This replaces
the hardcoded TOOL_SCHEMAS dicts in mcp_server.py with type-safe models.

Usage:
    from claw.tools.schemas import generate_mcp_tool_schemas, validate_tool_input

    schemas = generate_mcp_tool_schemas()   # for MCP list_tools
    parsed = validate_tool_input("claw_query_memory", {"query": "retry logic"})
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Input models — one per MCP tool
# ---------------------------------------------------------------------------

class QueryMemoryInput(BaseModel):
    """Input for claw_query_memory: search semantic memory for past solutions."""
    query: str = Field(..., description="Search query describing the problem or pattern you need")
    limit: int = Field(default=3, ge=1, le=20, description="Maximum number of results to return")
    language: Optional[str] = Field(default=None, description="Filter results by programming language")


class StoreFindingInput(BaseModel):
    """Input for claw_store_finding: persist a discovered pattern or fix."""
    problem_description: str = Field(..., description="Description of the problem this finding solves")
    solution_code: str = Field(..., description="The solution code, pattern, or technique")
    tags: list[str] = Field(default_factory=list, description="Categorization tags")
    methodology_type: Optional[str] = Field(default=None, description="Type: PATTERN, FIX, ARCHITECTURE, TECHNIQUE")


class VerifyClaimInput(BaseModel):
    """Input for claw_verify_claim: validate a code assertion."""
    claim: str = Field(..., description="The claim to verify (e.g. 'all tests pass')")
    workspace_dir: Optional[str] = Field(default=None, description="Path to workspace for file-based checks")


class RequestSpecialistInput(BaseModel):
    """Input for claw_request_specialist: route a subtask to a different agent."""
    task_description: str = Field(..., description="Description of the subtask to delegate")
    preferred_agent: Optional[Literal["claude", "codex", "gemini", "grok"]] = Field(
        default=None, description="Preferred agent for the task"
    )


class EscalateInput(BaseModel):
    """Input for claw_escalate: flag a task as requiring human intervention."""
    reason: str = Field(..., description="Why this task cannot be completed autonomously")
    context: Optional[dict[str, Any]] = Field(default=None, description="Additional context for the human reviewer")
    task_id: Optional[str] = Field(default=None, description="ID of the task being escalated")


# ---------------------------------------------------------------------------
# Tool metadata registry
# ---------------------------------------------------------------------------

TOOL_METADATA: dict[str, tuple[type[BaseModel], str]] = {
    "claw_query_memory": (
        QueryMemoryInput,
        "Query CLAW's semantic memory for similar past solutions, patterns, and techniques.",
    ),
    "claw_store_finding": (
        StoreFindingInput,
        "Store a discovered pattern, fix, or technique in CLAW's semantic memory for fleet-wide reuse.",
    ),
    "claw_verify_claim": (
        VerifyClaimInput,
        "Verify a code assertion by scanning for placeholders, TODOs, and unsubstantiated claims.",
    ),
    "claw_request_specialist": (
        RequestSpecialistInput,
        "Request a different AI agent (claude, codex, gemini, grok) to handle a subtask.",
    ),
    "claw_escalate": (
        EscalateInput,
        "Flag a task as beyond AI capability and escalate to human review.",
    ),
}


# ---------------------------------------------------------------------------
# Schema generation and validation
# ---------------------------------------------------------------------------

def generate_mcp_tool_schemas() -> list[dict[str, Any]]:
    """Generate MCP-format tool schema list from Pydantic models.

    Returns a list of dicts, each with 'name', 'description', and 'inputSchema'
    keys, suitable for MCP's list_tools response.
    """
    schemas: list[dict[str, Any]] = []
    for tool_name, (model_cls, description) in TOOL_METADATA.items():
        json_schema = model_cls.model_json_schema()
        # MCP expects inputSchema at the top level, not wrapped in $defs
        schemas.append({
            "name": tool_name,
            "description": description,
            "inputSchema": json_schema,
        })
    return schemas


def validate_tool_input(tool_name: str, arguments: dict[str, Any]) -> BaseModel:
    """Validate tool arguments against the Pydantic model.

    Args:
        tool_name: The MCP tool name (e.g. 'claw_query_memory').
        arguments: Raw dict of arguments from the MCP call.

    Returns:
        A validated Pydantic model instance.

    Raises:
        KeyError: If tool_name is not recognized.
        pydantic.ValidationError: If arguments fail validation.
    """
    if tool_name not in TOOL_METADATA:
        raise KeyError(f"Unknown tool: {tool_name}")
    model_cls, _ = TOOL_METADATA[tool_name]
    return model_cls.model_validate(arguments)
