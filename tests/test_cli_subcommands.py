"""Root-level CLI subcommand tests (--version, --help, mcp, mcp-http)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from stays.cli import app
from stays.mcp import _entry as mcp_entry


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_root_version(runner):
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("stays ")


def test_root_help_lists_subcommands(runner):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    out = result.stdout
    for cmd in ("search", "details", "enrich", "mcp", "mcp-http", "setup"):
        assert cmd in out


def test_mcp_delegates_to_entry(runner, monkeypatch):
    sentinel = MagicMock()
    # `stays.mcp` is aliased to the FastMCP instance by the package's
    # re-exports, so monkeypatch.setattr("stays.mcp._entry.run", ...)
    # hits an attribute chain rather than the module. Reach into the
    # _entry module directly via its imported reference.
    monkeypatch.setattr(mcp_entry, "run", sentinel)
    result = runner.invoke(app, ["mcp"])
    assert result.exit_code == 0
    sentinel.assert_called_once()


def test_mcp_http_delegates_to_entry(runner, monkeypatch):
    sentinel = MagicMock()
    monkeypatch.setattr(mcp_entry, "run_http", sentinel)
    result = runner.invoke(app, ["mcp-http"])
    assert result.exit_code == 0
    sentinel.assert_called_once()
