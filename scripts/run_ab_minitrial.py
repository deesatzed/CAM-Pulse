#!/usr/bin/env python3
"""A/B Mini-Trial Experiment — Targets repos with achievable test suites.

Instead of multiclaw's 3,590 tests, these repos have 100-400 tests that run
in 0.6-41 seconds, giving agents a realistic chance to succeed. This lets
the KB signal emerge instead of drowning in the noise floor.

Usage:
    PYTHONPATH=src python scripts/run_ab_minitrial.py --repo graphify --max-tasks 20
    PYTHONPATH=src python scripts/run_ab_minitrial.py --repo sentrysearch --max-tasks 20
    PYTHONPATH=src python scripts/run_ab_minitrial.py --repo anton --max-tasks 20
    PYTHONPATH=src python scripts/run_ab_minitrial.py --repo all --max-tasks 15
"""

import asyncio
import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from claw.core.factory import ClawFactory
from claw.core.models import Project, Task, TaskStatus
from claw.cycle import MicroClaw

logger = logging.getLogger("ab_minitrial")

# ---------------------------------------------------------------------------
# Task definitions per repo — difficulty-calibrated for ~40-60% success rate
# ---------------------------------------------------------------------------

GRAPHIFY_TASKS = [
    # graphify: 326 tests, 0.6s, Python, code-to-knowledge-graph tool
    # Modules: detect, extract, build, cluster, analyze, report, export,
    #          cache, validate, security, hooks, ingest, watch, wiki,
    #          benchmark, serve, __main__
    # All 326 tests pass. Tasks calibrated for ~60-80% agent success rate.
    # ---------------------------------------------------------------
    # BATCH 1: Original 10 tasks (bug fixes + enhancements)
    # ---------------------------------------------------------------
    {
        "title": "Fix rationale extraction for function docstrings",
        "description": "tests/test_rationale.py::test_function_docstring_extracted is failing. The rationale module should extract Python function docstrings as design rationale. Investigate the rationale extractor in graphify/ and fix the extraction logic so the test passes.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Fix rationale extraction for class docstrings",
        "description": "tests/test_rationale.py::test_class_docstring_extracted is failing. The rationale module should extract Python class docstrings as design rationale. Fix the class docstring extraction so the test passes.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Fix rationale comment extraction",
        "description": "tests/test_rationale.py::test_rationale_comment_extracted is failing. The rationale module should extract inline comments marked as design rationale. Fix the comment extraction logic.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add edge handling for empty source files in parser",
        "description": "The extract module's _extract_generic function in graphify/extract.py should handle empty source files gracefully. Add a guard at the top that returns an empty dict with 'nodes': [] and 'edges': [] for zero-length input instead of letting tree-sitter fail.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add node count validation to graph builder",
        "description": "In graphify/build.py, the build() function does not validate the resulting graph. Add a check after graph construction that logs a warning (using the logging module) if the graph has fewer than 2 nodes.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for multilang parser with unsupported language",
        "description": "In tests/test_multilang.py, add a test that verifies extract.collect_files returns an empty list when given a directory with only files of an unsupported extension (e.g., '.brainfuck'). The test should use tmp_path to create a temp file.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Improve security module error message for invalid URL scheme",
        "description": "In graphify/security.py, the validate_url function raises ValueError for non-http URLs. Improve the error message to include the actual scheme that was rejected and suggest using http:// or https:// instead.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add docstring to graph export functions",
        "description": "In graphify/export.py, the to_json() and to_html() functions need better docstrings. Add clear docstrings explaining the parameters (G: nx.Graph, communities: dict, path: Path) and what each function outputs.",
        "task_type": "documentation",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add type hints to cluster module public API",
        "description": "In graphify/cluster.py, the cluster() function and cohesion_score() function lack complete type annotations. Add proper type hints: cluster(G: nx.Graph) -> dict[int, list[str]], cohesion_score(G: nx.Graph, community: list[str]) -> float.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Fix edge rationale presence assertion",
        "description": "tests/test_rationale.py::test_rationale_for_edges_present is failing with 'assert 0 >= 1'. The rationale module should detect design rationale on graph edges (e.g., why a dependency exists). Fix the edge rationale detection.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    # ---------------------------------------------------------------
    # BATCH 2: cache.py tasks (46% coverage — lots of room)
    # ---------------------------------------------------------------
    {
        "title": "Add test for cache load with corrupted JSON",
        "description": "In tests/test_cache.py, add a test that writes invalid JSON to a cache file and verifies that load_cached() returns None instead of raising an exception. Use tmp_path to create a temp directory.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for cache clear function",
        "description": "In tests/test_cache.py, add a test for the clear_cache() function. Save a cached result, call clear_cache(), then verify load_cached() returns None for the same file. Use tmp_path.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for cached_files listing",
        "description": "In tests/test_cache.py, add a test for cached_files() that saves two different files to the cache and verifies cached_files() returns a set with both hashes.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add guard for non-existent file in save_cached",
        "description": "In graphify/cache.py, the save_cached() function calls file_hash() which reads the file. If the file was deleted between extract and save, it will crash. Add a try/except OSError around file_hash() in save_cached() that logs a warning and returns early.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    # ---------------------------------------------------------------
    # BATCH 3: validate.py tasks (87% coverage)
    # ---------------------------------------------------------------
    {
        "title": "Add test for validate_extraction with missing nodes key",
        "description": "In tests/test_validate.py, add a test that calls validate_extraction() with a dict that has 'edges' but no 'nodes' key, and verifies it returns an error message about the missing key.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for validate_extraction with empty edges",
        "description": "In tests/test_validate.py, add a test that calls validate_extraction() with a dict containing 'nodes': [{'id': 'a', 'label': 'A', 'type': 'function'}] and 'edges': []. Verify it passes validation since an empty edge list is valid.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    # ---------------------------------------------------------------
    # BATCH 4: security.py tasks (95% coverage — targeted gaps)
    # ---------------------------------------------------------------
    {
        "title": "Add test for sanitize_label with control characters",
        "description": "In tests/test_security.py, add a test that calls sanitize_label() with a string containing control characters (e.g., '\\x00hello\\x1f') and verifies they are stripped from the output.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for validate_url with ftp scheme",
        "description": "In tests/test_security.py, add a test that calls validate_url('ftp://example.com/file.txt') and verifies it raises ValueError with a message about unsupported scheme.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    # ---------------------------------------------------------------
    # BATCH 5: detect.py tasks (59% coverage — good opportunity)
    # ---------------------------------------------------------------
    {
        "title": "Add test for detect with empty directory",
        "description": "In tests/test_detect.py, add a test that calls detect() on an empty tmp_path directory and verifies the result has total_files=0 and needs_graph=False.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for classify_file with Python extension",
        "description": "In tests/test_detect.py, add a test that calls classify_file() with a .py file path and verifies it returns 'code' as the file type.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for classify_file with markdown extension",
        "description": "In tests/test_detect.py, add a test that calls classify_file() with a .md file path and verifies it returns 'document' as the file type.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add sensitive file detection test for .env",
        "description": "In tests/test_detect.py, add a test that creates a .env file in tmp_path, runs detect(), and verifies the .env file is flagged or excluded from the file list as a sensitive file.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    # ---------------------------------------------------------------
    # BATCH 6: analyze.py tasks (88% coverage)
    # ---------------------------------------------------------------
    {
        "title": "Add test for god_nodes with single-node graph",
        "description": "In tests/test_analyze.py, add a test that creates a NetworkX graph with only one node and calls god_nodes(). Verify it returns a list containing that single node (it has highest degree by default).",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for surprising_connections with no cross-community edges",
        "description": "In tests/test_analyze.py, add a test with a graph where all edges are within the same community. Verify surprising_connections() returns an empty list.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for graph_diff with identical graphs",
        "description": "In tests/test_analyze.py, add a test that calls graph_diff() with two identical NetworkX graphs. Verify the result shows zero new nodes, zero removed nodes, zero new edges, zero removed edges.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    # ---------------------------------------------------------------
    # BATCH 7: build.py tasks (97% coverage — edge cases)
    # ---------------------------------------------------------------
    {
        "title": "Add test for build with duplicate node IDs",
        "description": "In tests/test_build.py, add a test that passes two extraction dicts to build() where both contain a node with the same ID but different labels. Verify the resulting graph has exactly one node with that ID (deduplication works).",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for build_from_json with empty input",
        "description": "In tests/test_build.py, add a test that calls build_from_json() with an empty list. Verify it returns a NetworkX graph with zero nodes and zero edges.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    # ---------------------------------------------------------------
    # BATCH 8: report.py tasks (99% coverage — tiny gap)
    # ---------------------------------------------------------------
    {
        "title": "Add test for report generation with empty graph",
        "description": "In tests/test_report.py, add a test that calls generate() with an empty NetworkX graph and empty communities dict. Verify it returns a non-empty markdown string without crashing.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    # ---------------------------------------------------------------
    # BATCH 9: wiki.py tasks (100% but can add robustness)
    # ---------------------------------------------------------------
    {
        "title": "Add test for to_wiki with single community",
        "description": "In tests/test_wiki.py, add a test that calls to_wiki() with a graph containing 3 nodes all in one community. Verify it creates an index.md file and one community article in the output directory.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    # ---------------------------------------------------------------
    # BATCH 10: hooks.py tasks (93% coverage)
    # ---------------------------------------------------------------
    {
        "title": "Add test for hooks status when not installed",
        "description": "In tests/test_hooks.py, add a test that calls status() on a fresh git repo (tmp_path with git init) and verifies it reports hooks as not installed.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for hooks install and uninstall roundtrip",
        "description": "In tests/test_hooks.py, add a test that calls install() then uninstall() on a tmp git repo and verifies the post-commit hook file is removed.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    # ---------------------------------------------------------------
    # BATCH 11: benchmark.py tasks (100% — add edge cases)
    # ---------------------------------------------------------------
    {
        "title": "Add test for benchmark with graph with no edges",
        "description": "In tests/test_benchmark.py, add a test that creates a NetworkX graph with 5 isolated nodes (no edges) and calls run_benchmark(). Verify it returns a result dict without crashing.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    # ---------------------------------------------------------------
    # BATCH 12: Enhancement tasks across modules
    # ---------------------------------------------------------------
    {
        "title": "Add logging to cache save and load",
        "description": "In graphify/cache.py, add logging.debug() calls in load_cached() (log cache hit/miss) and save_cached() (log cache write). Import logging at the top. Use logger = logging.getLogger(__name__).",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add docstring to detect module public functions",
        "description": "In graphify/detect.py, the detect() function has a docstring but classify_file() and detect_incremental() are missing docstrings. Add docstrings explaining parameters and return values.",
        "task_type": "documentation",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add type hints to validate module",
        "description": "In graphify/validate.py, add complete type hints to validate_extraction(data: dict) -> list[str] and assert_valid(data: dict) -> None. Import necessary types from typing if needed.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add type hints to cache module functions",
        "description": "In graphify/cache.py, add type hints to all public functions. file_hash should return str, load_cached should return dict | None, save_cached should return None, cached_files should return set[str], clear_cache should return None.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add docstring to analyze module suggest_questions function",
        "description": "In graphify/analyze.py, the suggest_questions() function lacks a docstring. Add a docstring explaining it generates review questions from AMBIGUOUS edges, bridge nodes, and isolated nodes.",
        "task_type": "documentation",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Improve build module error message for invalid extraction",
        "description": "In graphify/build.py, if build() receives a dict without 'nodes' or 'edges' keys, it should raise a ValueError with a clear message like 'Extraction dict must contain nodes and edges keys'. Add this validation.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add docstring to security module safe_fetch function",
        "description": "In graphify/security.py, the safe_fetch() function fetches URLs with size limits. Add a docstring explaining the 50MB binary / 10MB text limits, redirect re-validation, and the return type.",
        "task_type": "documentation",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add return type hint to report generate function",
        "description": "In graphify/report.py, the generate() function returns a markdown string. Add the return type hint -> str and ensure all parameters have type hints (G: nx.Graph, communities: dict).",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    # ---------------------------------------------------------------
    # BATCH 13: More testing tasks — exercise less-tested paths
    # ---------------------------------------------------------------
    {
        "title": "Add test for cluster with disconnected graph",
        "description": "In tests/test_cluster.py, add a test that creates a NetworkX graph with two disconnected components (e.g., nodes A-B connected, nodes C-D connected, no edges between groups). Verify cluster() returns at least 2 communities.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for export to_json output format",
        "description": "In tests/test_export.py, add a test that calls to_json() with a small graph and reads back the output file. Verify the JSON contains 'nodes' and 'links' keys (NetworkX node-link format).",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for confidence score on extracted edges",
        "description": "In tests/test_confidence.py, add a test that creates an extraction with an edge that has confidence='EXTRACTED'. Build the graph and verify the edge has confidence attribute equal to 1.0.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for file_hash determinism",
        "description": "In tests/test_cache.py, add a test that writes the same content to a file, calls file_hash() twice, and verifies both calls return the identical SHA256 hex digest.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for validate assert_valid raises on bad data",
        "description": "In tests/test_validate.py, add a test that calls assert_valid() with a dict missing the 'nodes' key and verifies it raises an exception (ValueError or AssertionError).",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for build preserves edge attributes",
        "description": "In tests/test_build.py, add a test that passes an extraction with an edge containing a custom attribute (e.g., 'confidence': 0.8). Build the graph and verify the edge in the resulting NetworkX graph has that attribute.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for cohesion_score returns float between 0 and 1",
        "description": "In tests/test_cluster.py, add a test that builds a small connected graph, runs cluster(), picks one community, and calls cohesion_score(). Verify the result is a float between 0.0 and 1.0.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for sanitize_label with HTML entities",
        "description": "In tests/test_security.py, add a test that calls sanitize_label('<script>alert(1)</script>') and verifies the angle brackets are escaped in the output (e.g., '&lt;script&gt;').",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
    {
        "title": "Add test for detect incremental with unchanged files",
        "description": "In tests/test_detect.py, add a test that calls detect_incremental() twice on the same directory without changing any files. Verify the second call returns an empty or reduced file list (no re-processing needed).",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/graphify",
    },
]

SENTRYSEARCH_TASKS = [
    # sentrysearch: 113 tests, 2.6s, Python, semantic video search
    # 73 pass / 26 fail / 14 errors — good improvement surface
    {
        "title": "Fix trimmer count validation",
        "description": "tests/test_trimmer.py::TestTrimTopResults::test_zero_count_raises is erroring. The trim_top_results function should raise a ValueError when count is zero. Fix the validation logic.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/sentrysearch",
    },
    {
        "title": "Fix trim results count limit",
        "description": "tests/test_trimmer.py::TestTrimTopResults::test_count_limits_output is failing. The trimmer should respect the count parameter to limit output length. Fix the limiting logic.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/sentrysearch",
    },
    {
        "title": "Add validation for empty search query",
        "description": "The search module does not validate empty query strings. Add a guard that raises ValueError for empty or whitespace-only queries.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/sentrysearch",
    },
    {
        "title": "Add docstring to embedder module public functions",
        "description": "The embedder module's public functions for generating embeddings lack docstrings. Add docstrings explaining the embedding model, input format, and output dimensions.",
        "task_type": "documentation",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/sentrysearch",
    },
    {
        "title": "Add type hints to chunker module",
        "description": "The video chunker module lacks type annotations on its public functions. Add proper type hints for all parameters and return types.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/sentrysearch",
    },
    {
        "title": "Add edge case test for metadata with missing fields",
        "description": "Add a test that verifies the metadata module handles video metadata with missing required fields gracefully (e.g., missing duration, missing title).",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/sentrysearch",
    },
    {
        "title": "Improve CLI error message for invalid video path",
        "description": "The CLI does not give a helpful error when the user provides a path to a non-existent video file. Improve the error message to suggest checking the path.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/sentrysearch",
    },
    {
        "title": "Add test for chunker with zero-length input",
        "description": "Add a test that verifies the chunker handles zero-length or empty transcript input without crashing.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/sentrysearch",
    },
]

ANTON_TASKS = [
    # anton: 405 tests, 41s, Python, AI chat assistant framework
    # 371 pass / 34 fail — 92% pass rate, good signal-to-noise
    {
        "title": "Fix session persistence file corruption check",
        "description": "tests/e2e/scenarios/test_session_persistence.py::test_two_runs_same_folder_no_corruption is failing. The session persistence module should detect and prevent file corruption when two sessions write to the same folder. Fix the corruption detection logic.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/anton",
    },
    {
        "title": "Fix scratchpad execution output capture",
        "description": "tests/e2e/scenarios/test_tool_execution.py::test_scratchpad_exec_produces_real_output is failing. The scratchpad tool should capture and return real execution output. Fix the output capture mechanism.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/anton",
    },
    {
        "title": "Add input validation to chat message handler",
        "description": "The chat message handler does not validate message length. Add a guard that rejects messages exceeding 100,000 characters with a clear error.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/anton",
    },
    {
        "title": "Add docstring to memory management functions",
        "description": "The memory management module's public functions lack docstrings. Add docstrings explaining the memory lifecycle (create, retrieve, update, evict).",
        "task_type": "documentation",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/anton",
    },
    {
        "title": "Add type hints to tool dispatch module",
        "description": "The tool dispatch module lacks type annotations. Add proper type hints for tool registration, dispatch, and result handling functions.",
        "task_type": "enhancement",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/anton",
    },
    {
        "title": "Add test for concurrent tool execution",
        "description": "Add a test that verifies two tools can execute concurrently without race conditions or state corruption.",
        "task_type": "testing",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/anton",
    },
    {
        "title": "Fix syntax error handling in tool execution",
        "description": "tests/e2e/scenarios/test_tool_execution.py::test_syntax_error_in_tool_does_not_kill_session is failing. A syntax error in a tool should be caught and reported, not crash the session. Fix the error handling.",
        "task_type": "bug_fix",
        "repo": "/Volumes/WS4TB/a_aSatzClaw/rep411/anton",
    },
]

REPO_TASKS = {
    "graphify": GRAPHIFY_TASKS,
    "sentrysearch": SENTRYSEARCH_TASKS,
    "anton": ANTON_TASKS,
}


async def seed_tasks(ctx, project_id: str, tasks: list[dict]) -> int:
    """Seed tasks into the database for a given project."""
    import uuid

    count = 0
    for t in tasks:
        task = Task(
            id=str(uuid.uuid4()),
            project_id=project_id,
            title=t["title"],
            description=t["description"],
            task_type=t.get("task_type", "enhancement"),
            status=TaskStatus.PENDING,
            priority=8,
        )
        await ctx.repository.engine.execute(
            """INSERT INTO tasks (id, project_id, title, description, task_type, status, priority)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [task.id, task.project_id, task.title, task.description,
             task.task_type, task.status.value, task.priority],
        )
        count += 1
        logger.info("Seeded: %s", t["title"][:60])

    return count


async def main(
    repo_name: str = "graphify",
    max_tasks: int = 20,
    project_id: str = "",
    skip_seed: bool = False,
) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    # Determine which repos to use
    if repo_name == "all":
        selected_repos = list(REPO_TASKS.keys())
    else:
        if repo_name not in REPO_TASKS:
            print(f"Unknown repo: {repo_name}. Choose from: {list(REPO_TASKS.keys())} or 'all'")
            sys.exit(1)
        selected_repos = [repo_name]

    # Build context
    ctx = await ClawFactory.create()

    for repo in selected_repos:
        tasks_def = REPO_TASKS[repo]
        repo_path = tasks_def[0]["repo"]

        # Point all agents' workspace_dir at the target repo
        for agent in ctx.agents.values():
            agent.workspace_dir = repo_path

        print(f"\n{'='*60}")
        print(f"  MINI-TRIAL: {repo}")
        print(f"  Repo: {repo_path}")
        print(f"  Tasks: {len(tasks_def)}")
        print(f"{'='*60}\n")

        # Create or reuse project
        import uuid
        if project_id and len(selected_repos) == 1:
            pid = project_id
        else:
            pid = str(uuid.uuid4())

        if not skip_seed:
            # Create project
            proj = Project(
                id=pid,
                name=f"ab-minitrial-{repo}",
                repo_path=repo_path,
            )
            await ctx.repository.engine.execute(
                """INSERT OR IGNORE INTO projects (id, name, repo_path)
                   VALUES (?, ?, ?)""",
                [proj.id, proj.name, proj.repo_path],
            )

            # Seed tasks
            use_tasks = tasks_def[:max_tasks]
            seeded = await seed_tasks(ctx, pid, use_tasks)
            print(f"  Seeded {seeded} tasks into project {pid[:12]}...")
        else:
            print(f"  Skipping seed, using project {pid[:12]}...")

        # Run MicroClaw cycles
        cycle = MicroClaw(ctx, project_id=pid)
        MAX_TASK_ATTEMPTS = 3
        seen_tasks: dict[str, int] = {}
        samples_collected = 0
        start = time.monotonic()

        total_cycles = max_tasks * MAX_TASK_ATTEMPTS  # Upper bound
        for i in range(total_cycles):
            # Reset target repo to clean state before each cycle
            import subprocess
            subprocess.run(
                ["git", "checkout", "."], cwd=repo_path,
                capture_output=True, timeout=10,
            )
            subprocess.run(
                ["git", "clean", "-fd"], cwd=repo_path,
                capture_output=True, timeout=10,
            )

            # Check remaining tasks
            pending = await ctx.repository.engine.fetch_all(
                "SELECT COUNT(*) as cnt FROM tasks WHERE project_id=? AND status IN ('PENDING','CODING')",
                [pid],
            )
            remaining = pending[0]["cnt"] if pending else 0
            if remaining == 0:
                print(f"\n  All tasks completed or retired.")
                break

            elapsed = time.monotonic() - start
            rate = (i + 1) / (elapsed / 60) if elapsed > 0 else 0

            print(f"\n  --- Cycle {i+1} (remaining={remaining}) ---")

            try:
                result = await cycle.run_cycle()
                if result:
                    task_id = getattr(result, "task_id", None) or "unknown"
                    variant = getattr(result, "variant_label", None) or "?"
                    success = getattr(result, "success", False)

                    # Track retries
                    seen_tasks[task_id] = seen_tasks.get(task_id, 0) + 1
                    if seen_tasks[task_id] >= MAX_TASK_ATTEMPTS:
                        # Retire this task
                        await ctx.repository.engine.execute(
                            "UPDATE tasks SET status='DONE' WHERE id=?", [task_id]
                        )
                        logger.info("Retired task %s after %d attempts", task_id[:12], MAX_TASK_ATTEMPTS)

                    print(f"  [{'OK' if success else 'FAIL'}] task={task_id[:12]}... variant={variant}")
                    samples_collected += 1
                else:
                    print(f"  [SKIP] No result returned")
            except Exception as e:
                logger.error("Cycle error: %s", e)
                print(f"  [ERROR] {e}")

            # Progress
            if (i + 1) % 5 == 0:
                # Count A/B samples
                ab = await ctx.repository.engine.fetch_all(
                    """SELECT variant_label, COUNT(*) as n, AVG(composite_score) as avg_comp
                       FROM ab_quality_samples WHERE project_id=?
                       GROUP BY variant_label""",
                    [pid],
                )
                print(f"\n  === Progress: {i+1} cycles, {rate:.1f}/min ===")
                for row in ab:
                    avg = row["avg_comp"] or 0
                    print(f"      {row['variant_label']}: n={row['n']}, avg_composite={avg:.3f}")

        # Final summary
        elapsed = time.monotonic() - start
        ab_final = await ctx.repository.engine.fetch_all(
            """SELECT variant_label, COUNT(*) as n, AVG(composite_score) as avg_comp,
                      SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successes
               FROM ab_quality_samples WHERE project_id=?
               GROUP BY variant_label""",
            [pid],
        )

        print(f"\n{'='*60}")
        print(f"  MINI-TRIAL COMPLETE: {repo}")
        print(f"  Duration: {elapsed/60:.1f} minutes")
        print(f"  Project: {pid}")
        print(f"{'='*60}")
        print(f"\n  A/B Quality Samples:")
        for row in ab_final:
            avg = row["avg_comp"] or 0
            succ = row["successes"] or 0
            print(f"    {row['variant_label']}: n={row['n']}, composite={avg:.3f}, success={succ}/{row['n']}")

    # Cross-project totals
    ab_all = await ctx.repository.engine.fetch_all(
        """SELECT variant_label, COUNT(*) as n, AVG(composite_score) as avg_comp
           FROM ab_quality_samples GROUP BY variant_label"""
    )
    print(f"\n  All-time A/B totals:")
    for row in ab_all:
        avg = row["avg_comp"] or 0
        print(f"    {row['variant_label']}: n={row['n']}, avg_composite={avg:.4f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A/B Mini-Trial Experiment")
    parser.add_argument("--repo", default="graphify", help="Repo: graphify, sentrysearch, anton, or all")
    parser.add_argument("--max-tasks", type=int, default=20, help="Max tasks per repo")
    parser.add_argument("--project-id", default="", help="Reuse existing project ID")
    parser.add_argument("--skip-seed", action="store_true", help="Skip task seeding")
    args = parser.parse_args()

    asyncio.run(main(
        repo_name=args.repo,
        max_tasks=args.max_tasks,
        project_id=args.project_id,
        skip_seed=args.skip_seed,
    ))
