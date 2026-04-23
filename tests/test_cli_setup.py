"""CliRunner tests for `stays setup {claude,codex,chatgpt}`."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from stays.cli import app
from stays.mcp.setup import claude as claude_backend
from stays.mcp.setup import codex as codex_backend


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_setup_no_subcommand_prints_help_and_exits_0(runner):
    result = runner.invoke(app, ["setup"])
    assert result.exit_code == 0
    assert "claude" in result.stdout
    assert "codex" in result.stdout
    assert "chatgpt" in result.stdout


def test_setup_claude_delegates_with_print_json(runner, monkeypatch):
    fake_report = MagicMock()
    fake_report.messages = ["Claude Code: OK"]
    fake_report.claude_code_registered = False
    fake_report.claude_desktop_patched = False
    fake_report.backup_path = None
    fake_report.fallback_json = json.dumps({"mcpServers": {"stays": {"command": "x"}}})
    mock_reg = MagicMock(return_value=fake_report)
    monkeypatch.setattr(claude_backend, "register", mock_reg)
    result = runner.invoke(app, ["setup", "claude", "--print-json"])
    assert result.exit_code == 0
    mock_reg.assert_called_once()
    kwargs = mock_reg.call_args.kwargs
    assert kwargs["print_json_only"] is True
    assert "mcpServers" in result.stdout


def test_setup_claude_passes_replace_and_desktop_flags(runner, monkeypatch):
    fake_report = MagicMock()
    fake_report.messages = []
    fake_report.claude_code_registered = True
    fake_report.claude_desktop_patched = False
    fake_report.backup_path = None
    fake_report.fallback_json = None
    mock_reg = MagicMock(return_value=fake_report)
    monkeypatch.setattr(claude_backend, "register", mock_reg)
    result = runner.invoke(app, ["setup", "claude", "--replace", "--desktop-only"])
    assert result.exit_code == 0
    kwargs = mock_reg.call_args.kwargs
    assert kwargs["replace"] is True
    assert kwargs["force_desktop_only"] is True


def test_setup_codex_happy_path(runner, monkeypatch):
    fake_report = MagicMock()
    fake_report.messages = ["Codex: registered"]
    fake_report.registered = True
    fake_report.already_present = False
    fake_report.fallback_toml = None
    fake_report.config_path = None
    mock_reg = MagicMock(return_value=fake_report)
    monkeypatch.setattr(codex_backend, "register", mock_reg)
    result = runner.invoke(app, ["setup", "codex"])
    assert result.exit_code == 0
    assert "Codex: registered" in result.stdout
    mock_reg.assert_called_once()


def test_setup_codex_print_toml_fallback(runner, monkeypatch):
    fake_report = MagicMock()
    fake_report.messages = ["Paste the TOML below"]
    fake_report.registered = False
    fake_report.already_present = False
    fake_report.fallback_toml = '[mcp_servers.stays]\ncommand = "/bin/stays"\n'
    fake_report.config_path = None
    mock_reg = MagicMock(return_value=fake_report)
    monkeypatch.setattr(codex_backend, "register", mock_reg)
    result = runner.invoke(app, ["setup", "codex", "--print-toml"])
    assert result.exit_code == 0
    assert "[mcp_servers.stays]" in result.stdout
    kwargs = mock_reg.call_args.kwargs
    assert kwargs["print_toml_only"] is True


def test_setup_chatgpt_prints_instructions(runner):
    result = runner.invoke(app, ["setup", "chatgpt"])
    assert result.exit_code == 0
    out = result.stdout
    assert "Developer Mode" in out
    assert "OAuth" in out
    assert "chatgpt.com" in out.lower() or "chatgpt.com" in out


def test_setup_chatgpt_open_flag_triggers_browser(runner, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    result = runner.invoke(app, ["setup", "chatgpt", "--open"])
    assert result.exit_code == 0
    assert opened and "chatgpt.com" in opened[0]
