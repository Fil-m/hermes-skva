# SKVA E2ETests — auto-generated
"""TZ gap closure"""
import sys, os, json, time, asyncio
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skva_core import log

#!/usr/bin/env python3
"""
End-to-end tests for SKVA core functionality.
Each test is self-contained, uses mocks, and verifies behavior without external dependencies.
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Dict, Any, List
import pytest
from unittest.mock import Mock, patch, call

# Import core components from skva_core (assumed to be in PYTHONPATH)
from skva_core import (
    log,
    StateMachine,
    RunReport,
    CheckpointSystem,
    Gate,
    Budget,
    ErrorCode,
    detect_error_code,
    extract_file_operations,
    split_into_modules,
)

# Constants
TEST_PROJECT_DIR = Path(".skva/test_e2e")
STATE_FILE = TEST_PROJECT_DIR / "state.json"
SKVA_DIR = TEST_PROJECT_DIR / ".skva"


@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Ensure clean test environment."""
    # Setup
    TEST_PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    SKVA_DIR.mkdir(exist_ok=True)

    yield

    # Teardown
    if TEST_PROJECT_DIR.exists():
        shutil.rmtree(TEST_PROJECT_DIR)


# ═══════════════════════════════════════════════════
# TEST 1: State Machine & state.json persistence
# ═══════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_state_machine():
    """Test DAG state transitions and JSON persistence."""
    sm = StateMachine(project_dir=TEST_PROJECT_DIR)

    # Add three nodes: analyze → design → implement
    sm.add_node("analyze", type="analyze", deps=[])
    sm.add_node("design", type="design", deps=["analyze"])
    sm.add_node("implement", type="implement", deps=["design"])

    # Initial state
    assert sm.get_status("analyze") == "pending"
    assert sm.get_status("design") == "pending"
    assert sm.get_status("implement") == "pending"

    # Transition analyze → success
    sm.transition("analyze", "running")
    sm.transition("analyze", "success")
    assert sm.get_status("analyze") == "success"
    assert sm.get_status("design") == "ready"

    # Transition design → failed
    sm.transition("design", "running")
    sm.transition("design", "failed")
    assert sm.get_status("design") == "failed"
    assert sm.get_status("implement") == "blocked"

    # Save state
    sm.save_state()

    # Verify state.json content
    assert STATE_FILE.exists(), "state.json should be created"
    with open(STATE_FILE) as f:
        state_data: Dict[str, Any] = json.load(f)

    assert state_data["nodes"]["analyze"]["status"] == "success"
    assert state_data["nodes"]["design"]["status"] == "failed"
    assert state_data["nodes"]["implement"]["status"] == "blocked"
    assert "analyze" in state_data["graph"]
    assert "design" in state_data["graph"]["analyze"]["children"]


# ═══════════════════════════════════════════════════
# TEST 2: Error Taxonomy — ErrorCode detection
# ═══════════════════════════════════════════════════

def test_error_taxonomy():
    """Test error message classification into ErrorCode enum."""
    test_cases: List[Dict[str, Any]] = [
        {
            "error": "File not found: /src/main.py",
            "expected": ErrorCode.FILE_NOT_FOUND,
        },
        {
            "error": "Permission denied accessing config.json",
            "expected": ErrorCode.PERMISSION_DENIED,
        },
        {
            "error": "SyntaxError: invalid syntax on line 10",
            "expected": ErrorCode.CODE_SYNTAX_ERROR,
        },
        {
            "error": "ModuleNotFoundError: No module named 'requests'",
            "expected": ErrorCode.DEPENDENCY_MISSING,
        },
        {
            "error": "Timeout during model generation",
            "expected": ErrorCode.MODEL_TIMEOUT,
        },
        {
            "error": "Invalid JSON in response",
            "expected": ErrorCode.MODEL_MALFORMED_OUTPUT,
        },
        {
            "error": "Quota exceeded for qwen-max",
            "expected": ErrorCode.QUOTA_EXCEEDED,
        },
        {
            "error": "Unknown error occurred",
            "expected": ErrorCode.UNKNOWN,
        },
    ]

    for case in test_cases:
        detected = detect_error_code(case["error"])
        assert detected == case["expected"], f"Failed on: {case['error']}"


# ═══════════════════════════════════════════════════
# TEST 3: Markdown Agent — Parse file blocks from LLM output
# ═══════════════════════════════════════════════════

def test_markdown_agent():
    """Test extraction of file operations from mock LLM markdown output."""
    mock_llm_output = '''
Here's the implementation:

