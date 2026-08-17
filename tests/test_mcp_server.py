"""MCP server contract: the MCP tools are a pure transport — their payloads are
byte-for-byte the CLI's `--json` output, and errors use the same error object.
The query helpers work without the optional `mcp` package; only server wiring
tests skip when it is absent."""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from whyloom.cli import app
from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.mcp_server import context_query, explain_query, flow_query, impact_query, path_query

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"

runner = CliRunner()


def _indexed_repo(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    index_project(root, DEFAULT_CONFIG)
    return root


def _cli_json(root, *args):
    result = runner.invoke(app, [*args, "--root", str(root), "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_explain_payload_equals_cli_json(tmp_path):
    root = _indexed_repo(tmp_path)
    cli = _cli_json(root, "explain", "src/sample/auth.py")
    mcp = explain_query(root, DEFAULT_CONFIG, "src/sample/auth.py")
    assert mcp == cli


def test_context_payload_equals_cli_json(tmp_path):
    root = _indexed_repo(tmp_path)
    cli = _cli_json(root, "context", "token storage")
    mcp = context_query(root, DEFAULT_CONFIG, "token storage")
    assert mcp == cli


def test_impact_payload_equals_cli_json(tmp_path):
    root = _indexed_repo(tmp_path)
    cli = _cli_json(root, "impact", "src/sample/auth.py")
    mcp = impact_query(root, DEFAULT_CONFIG, "src/sample/auth.py")
    assert mcp == cli


def test_path_payload_equals_cli_json(tmp_path):
    root = _indexed_repo(tmp_path)
    cli = _cli_json(root, "path", "DEC-0001", "src/sample/auth.py")
    mcp = path_query(root, DEFAULT_CONFIG, "DEC-0001", "src/sample/auth.py")
    assert mcp == cli


def test_flow_payload_equals_cli_json(tmp_path):
    root = _indexed_repo(tmp_path)
    cli = _cli_json(root, "flow", "src/sample/auth.py")
    mcp = flow_query(root, DEFAULT_CONFIG, "src/sample/auth.py")
    assert mcp == cli


def test_missing_index_returns_contract_error(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)  # records exist, but no index was built
    result = explain_query(root, DEFAULT_CONFIG, "src/sample/auth.py")
    assert result["ok"] is False
    assert result["error"]["code"] == "IDX001"
    assert result["schema_version"] == 1


def test_build_server_registers_read_only_tools(tmp_path):
    pytest.importorskip("mcp")
    import asyncio

    from whyloom.mcp_server import build_server

    root = _indexed_repo(tmp_path)
    server = build_server(root)
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert names == {"whyloom_context", "whyloom_explain", "whyloom_impact", "whyloom_path", "whyloom_flow"}


def test_cli_mcp_command_without_extra_fails_cleanly(tmp_path, monkeypatch):
    # Simulate the extra being absent even if `mcp` is installed in this env.
    import builtins

    real_import = builtins.__import__

    def missing_mcp(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp."):
            raise ModuleNotFoundError(f"No module named '{name}'", name=name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_mcp)
    root = _indexed_repo(tmp_path)
    result = runner.invoke(app, ["mcp", "--root", str(root)])
    assert result.exit_code == 2
    assert "MCP001" in result.output
    assert "whyloom[mcp]" in result.output
