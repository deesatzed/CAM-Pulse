"""Tests for claw.logging_config — JSON formatter, context filter, setup_logging."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path

import pytest

from claw.logging_config import (
    ClawContextFilter,
    ClawJsonFormatter,
    clear_context,
    get_context,
    set_context,
    setup_logging,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_context():
    """Clear context before and after every test to avoid leakage."""
    clear_context()
    yield
    clear_context()


@pytest.fixture()
def _clean_root_logger():
    """Save and restore root-logger state so setup_logging tests don't leak."""
    root = logging.getLogger()
    old_level = root.level
    old_handlers = list(root.handlers)
    old_filters = list(root.filters)
    yield
    root.handlers = old_handlers
    root.filters = old_filters
    root.setLevel(old_level)


# ---------------------------------------------------------------------------
# Context store
# ---------------------------------------------------------------------------

class TestSetContext:
    def test_set_and_get(self):
        set_context(task_id="t-1", agent_id="claude")
        ctx = get_context()
        assert ctx == {"task_id": "t-1", "agent_id": "claude"}

    def test_clear_removes_all(self):
        set_context(task_id="t-1", session_id="s-abc")
        clear_context()
        assert get_context() == {}

    def test_ignores_unknown_keys(self):
        set_context(task_id="t-1", bogus_key="nope")
        ctx = get_context()
        assert "bogus_key" not in ctx
        assert ctx == {"task_id": "t-1"}

    def test_overwrite_existing_field(self):
        set_context(task_id="t-1")
        set_context(task_id="t-2")
        assert get_context()["task_id"] == "t-2"

    def test_partial_clear_via_set(self):
        set_context(task_id="t-1", agent_id="codex")
        # Setting new context does NOT clear previous fields
        set_context(agent_id="gemini")
        ctx = get_context()
        assert ctx["task_id"] == "t-1"
        assert ctx["agent_id"] == "gemini"

    def test_thread_isolation(self):
        """Context in one thread must not leak to another."""
        set_context(task_id="main-thread")
        child_ctx = {}

        def worker():
            child_ctx.update(get_context())

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        assert child_ctx == {}  # child thread sees nothing
        assert get_context()["task_id"] == "main-thread"


# ---------------------------------------------------------------------------
# ClawContextFilter
# ---------------------------------------------------------------------------

class TestClawContextFilter:
    def test_injects_context_fields(self):
        set_context(task_id="t-99", cycle_level="micro")
        flt = ClawContextFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        assert flt.filter(record) is True
        assert record.task_id == "t-99"  # type: ignore[attr-defined]
        assert record.cycle_level == "micro"  # type: ignore[attr-defined]

    def test_does_not_overwrite_existing_record_attrs(self):
        set_context(task_id="context-val")
        flt = ClawContextFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        record.task_id = "explicit-val"  # type: ignore[attr-defined]
        flt.filter(record)
        assert record.task_id == "explicit-val"  # type: ignore[attr-defined]

    def test_none_for_unset_fields(self):
        clear_context()
        flt = ClawContextFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        flt.filter(record)
        assert record.task_id is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# ClawJsonFormatter
# ---------------------------------------------------------------------------

class TestClawJsonFormatter:
    def _make_record(self, msg="test msg", level=logging.INFO, **extras):
        record = logging.LogRecord(
            name="claw.test", level=level, pathname="", lineno=0,
            msg=msg, args=(), exc_info=None,
        )
        for k, v in extras.items():
            setattr(record, k, v)
        return record

    def test_basic_json_output(self):
        fmt = ClawJsonFormatter()
        record = self._make_record()
        line = fmt.format(record)
        data = json.loads(line)
        assert data["level"] == "INFO"
        assert data["logger"] == "claw.test"
        assert data["msg"] == "test msg"
        assert "ts" in data

    def test_context_fields_included(self):
        fmt = ClawJsonFormatter()
        record = self._make_record(task_id="t-1", agent_id="claude")
        line = fmt.format(record)
        data = json.loads(line)
        assert data["task_id"] == "t-1"
        assert data["agent_id"] == "claude"

    def test_metric_fields_included(self):
        fmt = ClawJsonFormatter()
        record = self._make_record(elapsed_ms=142, tokens=1200, cost_usd=0.003)
        line = fmt.format(record)
        data = json.loads(line)
        assert data["elapsed_ms"] == 142
        assert data["tokens"] == 1200
        assert data["cost_usd"] == 0.003

    def test_none_context_fields_omitted(self):
        fmt = ClawJsonFormatter()
        record = self._make_record(task_id=None)
        line = fmt.format(record)
        data = json.loads(line)
        assert "task_id" not in data

    def test_exception_included(self):
        fmt = ClawJsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="claw.test", level=logging.ERROR, pathname="", lineno=0,
                msg="failure", args=(), exc_info=sys.exc_info(),
            )
        line = fmt.format(record)
        data = json.loads(line)
        assert "exception" in data
        assert "boom" in data["exception"]

    def test_warning_level(self):
        fmt = ClawJsonFormatter()
        record = self._make_record(level=logging.WARNING)
        line = fmt.format(record)
        data = json.loads(line)
        assert data["level"] == "WARNING"


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------

class TestSetupLogging:
    @pytest.mark.usefixtures("_clean_root_logger")
    def test_default_text_mode(self):
        setup_logging(verbose=False)
        root = logging.getLogger()
        assert root.level == logging.INFO
        assert len(root.handlers) == 1
        assert not isinstance(root.handlers[0].formatter, ClawJsonFormatter)

    @pytest.mark.usefixtures("_clean_root_logger")
    def test_json_mode(self):
        setup_logging(verbose=False, json_mode=True)
        root = logging.getLogger()
        assert isinstance(root.handlers[0].formatter, ClawJsonFormatter)

    @pytest.mark.usefixtures("_clean_root_logger")
    def test_verbose_sets_debug(self):
        setup_logging(verbose=True)
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    @pytest.mark.usefixtures("_clean_root_logger")
    def test_log_file_creates_file_handler(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            setup_logging(verbose=False, log_file=path)
            root = logging.getLogger()
            assert len(root.handlers) == 2  # console + file
            file_handler = root.handlers[1]
            assert isinstance(file_handler, logging.FileHandler)
            assert isinstance(file_handler.formatter, ClawJsonFormatter)
        finally:
            os.unlink(path)

    @pytest.mark.usefixtures("_clean_root_logger")
    def test_repeated_setup_clears_old_handlers(self):
        setup_logging(verbose=False)
        setup_logging(verbose=False)
        root = logging.getLogger()
        # Should have exactly 1 handler, not 2
        assert len(root.handlers) == 1

    @pytest.mark.usefixtures("_clean_root_logger")
    def test_context_filter_attached_to_handlers(self):
        setup_logging(verbose=False)
        root = logging.getLogger()
        # Filter is on handlers, not root logger
        for handler in root.handlers:
            filter_types = [type(f) for f in handler.filters]
            assert ClawContextFilter in filter_types

    def test_json_mode_end_to_end(self, capsys):
        """JSON mode produces valid JSON to stderr with context fields."""
        root = logging.getLogger()
        old_level = root.level
        old_handlers = list(root.handlers)
        old_filters = list(root.filters)
        try:
            setup_logging(verbose=False, json_mode=True)
            set_context(task_id="t-e2e")
            test_logger = logging.getLogger("claw.e2e_test")
            test_logger.info("integration check")
            captured = capsys.readouterr()
            line = captured.err.strip()
            if line:
                data = json.loads(line)
                assert data["msg"] == "integration check"
                assert data["task_id"] == "t-e2e"
        finally:
            root.handlers = old_handlers
            root.filters = old_filters
            root.setLevel(old_level)
