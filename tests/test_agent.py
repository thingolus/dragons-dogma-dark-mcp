import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import ddda_mcp
from ddda_mcp.copied_groups import GROUPS


def test_actual_agent_is_inert_and_preserves_abi_values():
    node = shutil.which("node")
    if not node:
        if os.environ.get("CI"):
            pytest.fail("CI must install Node.js to exercise the actual agent contract")
        pytest.skip("Node.js is required for the synthetic Frida agent contract")
    agent = Path(ddda_mcp.__file__).with_name("agent.js")
    contract = Path(__file__).with_name("agent_contract.cjs")
    result = subprocess.run(
        [node, str(contract), str(agent), json.dumps(GROUPS)], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "agent contract passed" in result.stdout


def test_actual_trace_callbacks_and_cleanup():
    node = shutil.which("node")
    if not node:
        if os.environ.get("CI"):
            pytest.fail("CI must install Node.js for trace contracts")
        pytest.skip("Node.js required")
    script = Path(ddda_mcp.__file__).with_name("tracing.js")
    result = subprocess.run(
        [
            node,
            str(Path(__file__).with_name("tracing_contract.cjs")),
            str(script),
            str(script.with_name("world.js")),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "tracing contract passed" in result.stdout
