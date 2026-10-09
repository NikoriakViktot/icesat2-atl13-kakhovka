"""The machine-readable API docs must match the code (scripts/export_agent_docs.py)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

ROOT = Path(__file__).resolve().parents[1]


def test_openapi_and_agent_tools_are_regenerated():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "export_agent_docs.py"),
                        "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_agent_tools_cover_the_api():
    tools = json.loads((ROOT / "docs" / "agent-tools.json").read_text())["tools"]
    paths = json.loads((ROOT / "docs" / "openapi.json").read_text())["paths"]
    for t in tools:
        assert t["http"]["path"] in paths, t["name"]
        assert t["input_schema"]["type"] == "object"
    assert {"create_job", "get_job", "register_region"} <= {t["name"] for t in tools}
