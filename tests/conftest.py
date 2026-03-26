"""Shared fixtures for CLAW tests.

All tests use REAL dependencies — no mocks, no placeholders.
Tests requiring external services use skip markers when unavailable.

Database: SQLite in-memory (:memory:) for test isolation.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env from project root if available
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

from claw.core.config import ClawConfig, DatabaseConfig, load_config
from claw.core.models import Project, Task


# ---------------------------------------------------------------------------
# Service availability checks
# ---------------------------------------------------------------------------

def _anthropic_key_set() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _openai_key_set() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def _google_key_set() -> bool:
    return bool(os.getenv("GOOGLE_API_KEY"))


def _xai_key_set() -> bool:
    return bool(os.getenv("XAI_API_KEY"))


def _openrouter_key_set() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY"))


def _claude_code_available() -> bool:
    """Check if Claude Code CLI is installed and responds."""
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# Skip markers for external service dependencies
requires_anthropic = pytest.mark.skipif(
    not _anthropic_key_set(),
    reason="ANTHROPIC_API_KEY not set",
)

requires_openai = pytest.mark.skipif(
    not _openai_key_set(),
    reason="OPENAI_API_KEY not set",
)

requires_google = pytest.mark.skipif(
    not _google_key_set(),
    reason="GOOGLE_API_KEY not set",
)

requires_xai = pytest.mark.skipif(
    not _xai_key_set(),
    reason="XAI_API_KEY not set",
)

requires_openrouter = pytest.mark.skipif(
    not _openrouter_key_set(),
    reason="OPENROUTER_API_KEY not set",
)

requires_claude_code = pytest.mark.skipif(
    not _claude_code_available(),
    reason="Claude Code CLI not available",
)

# Unified integration gate — set CLAW_RUN_INTEGRATION=1 to include live tests
# that hit real external services (beyond simple API key checks).
# Inspired by Agent_Pidgeon's AGENT_PIDGIN_RUN_STDIO_INTEGRATION pattern.
requires_integration = pytest.mark.skipif(
    os.environ.get("CLAW_RUN_INTEGRATION", "") != "1",
    reason="Set CLAW_RUN_INTEGRATION=1 to run live integration tests",
)


# ---------------------------------------------------------------------------
# Config fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def claw_config() -> ClawConfig:
    """Load config from project claw.toml."""
    return load_config()


# ---------------------------------------------------------------------------
# Database fixtures (SQLite in-memory for isolation)
# ---------------------------------------------------------------------------

@pytest.fixture
async def db_engine():
    """Real SQLite in-memory engine — creates schema, yields, cleans up."""
    from claw.db.engine import DatabaseEngine
    config = DatabaseConfig(db_path=":memory:")
    engine = DatabaseEngine(config)
    await engine.connect()
    await engine.initialize_schema()
    yield engine
    await engine.close()


@pytest.fixture
async def repository(db_engine):
    """Repository wrapping in-memory engine."""
    from claw.db.repository import Repository
    return Repository(db_engine)


@pytest.fixture
async def claw_context():
    """Full ClawContext with in-memory DB for integration tests."""
    from claw.core.config import DatabaseConfig
    from claw.core.factory import ClawContext, ClawFactory
    from claw.db.engine import DatabaseEngine
    from claw.db.embeddings import EmbeddingEngine
    from claw.db.repository import Repository
    from claw.llm.client import LLMClient
    from claw.llm.token_tracker import TokenTracker
    from claw.security.policy import SecurityPolicy

    config = load_config()
    config.database.db_path = ":memory:"

    engine = DatabaseEngine(config.database)
    await engine.connect()
    await engine.initialize_schema()
    repo = Repository(engine)

    ctx = ClawContext(
        config=config,
        engine=engine,
        repository=repo,
        embeddings=EmbeddingEngine(config.embeddings),
        llm_client=LLMClient(config.llm),
        token_tracker=TokenTracker(repository=repo),
        security=SecurityPolicy(),
        agents={},
    )

    yield ctx
    await ctx.close()


# ---------------------------------------------------------------------------
# Sample data fixtures (real-shaped, not mocked)
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_project() -> Project:
    return Project(
        name="test-project",
        repo_path="/tmp/test-repo",
        tech_stack={"language": "python", "framework": "fastapi"},
        project_rules="No wildcard imports",
        banned_dependencies=["flask", "django"],
    )


@pytest.fixture
def sample_task(sample_project: Project) -> Task:
    return Task(
        project_id=sample_project.id,
        title="Implement user auth",
        description="Add JWT-based authentication to the API",
        priority=10,
        task_type="analysis",
    )
