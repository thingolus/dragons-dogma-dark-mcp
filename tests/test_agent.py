import shutil
import subprocess
from pathlib import Path

import pytest

import ddda_mcp


def test_actual_agent_is_inert_and_preserves_abi_values():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the synthetic Frida agent contract")
    agent = Path(ddda_mcp.__file__).with_name("agent.js")
    contract = Path(__file__).with_name("agent_contract.cjs")
    result = subprocess.run([node, str(contract), str(agent)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "agent contract passed" in result.stdout
