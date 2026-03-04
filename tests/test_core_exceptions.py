"""Tests for CLAW exception hierarchy."""

from claw.core.exceptions import (
    AgentError,
    AgentUnavailableError,
    BudgetExceededError,
    CheckpointError,
    ClawError,
    ConfigError,
    ConnectionError,
    DatabaseError,
    EscalationExhaustionError,
    GitOperationError,
    LLMError,
    ModelNotFoundError,
    RateLimitError,
    ResponseParseError,
    RoutingError,
    SchemaInitError,
    SearchError,
    ShellTimeoutError,
    ToolError,
    VerificationRejectionError,
)


def test_base_exception():
    assert issubclass(ClawError, Exception)


def test_database_hierarchy():
    assert issubclass(DatabaseError, ClawError)
    assert issubclass(SchemaInitError, DatabaseError)
    assert issubclass(ConnectionError, DatabaseError)


def test_llm_hierarchy():
    assert issubclass(LLMError, ClawError)
    assert issubclass(RateLimitError, LLMError)
    assert issubclass(AuthenticationError, LLMError)
    assert issubclass(ModelNotFoundError, LLMError)
    assert issubclass(ResponseParseError, LLMError)


def test_agent_hierarchy():
    assert issubclass(AgentError, ClawError)
    assert issubclass(AgentUnavailableError, AgentError)
    assert issubclass(CheckpointError, AgentError)
    assert issubclass(VerificationRejectionError, AgentError)
    assert issubclass(EscalationExhaustionError, AgentError)


def test_agent_unavailable_attrs():
    e = AgentUnavailableError("codex", "SDK not installed")
    assert e.agent_id == "codex"
    assert e.reason == "SDK not installed"
    assert "codex" in str(e)
    assert "SDK not installed" in str(e)


def test_budget_exceeded_attrs():
    e = BudgetExceededError("per_task", 1.0, 1.5)
    assert e.budget_type == "per_task"
    assert e.limit == 1.0
    assert e.current == 1.5
    assert "1.50" in str(e)


def test_routing_error_attrs():
    e = RoutingError("analysis", "all agents down")
    assert e.task_type == "analysis"
    assert "all agents down" in str(e)


def test_verification_rejection_attrs():
    violations = [{"check": "placeholder", "detail": "Found TODO"}]
    e = VerificationRejectionError(violations)
    assert e.violations == violations


def test_escalation_exhaustion_attrs():
    e = EscalationExhaustionError("task-123", 3)
    assert e.task_id == "task-123"
    assert e.escalation_count == 3
    assert "task-123" in str(e)


def test_tool_hierarchy():
    assert issubclass(ToolError, ClawError)
    assert issubclass(ShellTimeoutError, ToolError)
    assert issubclass(GitOperationError, ToolError)
    assert issubclass(SearchError, ToolError)


def test_config_hierarchy():
    assert issubclass(ConfigError, ClawError)


# Import needed for test_llm_hierarchy
from claw.core.exceptions import AuthenticationError
