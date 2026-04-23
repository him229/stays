"""Tests for the smart-default argv router in stays.cli._entry."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from stays.cli import app
from stays.cli._entry import _KNOWN_COMMANDS, _rewrite_argv


@pytest.mark.parametrize(
    "argv, expected",
    [
        ([], ["--help"]),
        (["--help"], ["--help"]),
        (["-h"], ["-h"]),
        (["--version"], ["--version"]),
        (["search", "tokyo"], ["search", "tokyo"]),
        (
            ["details", "ChkI_abc", "--check-in", "2026-07-22"],
            ["details", "ChkI_abc", "--check-in", "2026-07-22"],
        ),
        (
            ["enrich", "paris", "--max-hotels", "3"],
            ["enrich", "paris", "--max-hotels", "3"],
        ),
        (["setup", "--replace"], ["setup", "--replace"]),
        (["mcp"], ["mcp"]),
        (["mcp-http"], ["mcp-http"]),
        (["tokyo"], ["search", "tokyo"]),
        (["tokyo", "--stars", "4"], ["search", "tokyo", "--stars", "4"]),
        (["Hilton Paris"], ["search", "Hilton Paris"]),
        (["--install-completion"], ["--install-completion"]),
        (["--show-completion"], ["--show-completion"]),
        (["-x"], ["-x"]),
    ],
)
def test_rewrite_argv(argv, expected):
    assert _rewrite_argv(argv) == expected


def test_bare_query_routes_to_search(monkeypatch):
    """Smart-default: `stays "tokyo" --format json` dispatches to search."""
    mock = MagicMock()
    mock.return_value.search.return_value = []
    monkeypatch.setattr("stays.cli.commands.search.SearchHotels", mock)

    rewritten = _rewrite_argv(["tokyo", "--format", "json"])
    result = CliRunner().invoke(app, rewritten)
    assert result.exit_code == 0
    mock.return_value.search.assert_called_once()


def test_registered_command_names_match_router_whitelist():
    """Pin the router whitelist against the actual typer registration.

    If a command name in `_app.py` gets auto-normalized (e.g. hyphen ->
    underscore) and the router's `_KNOWN_COMMANDS` still has the hyphen,
    the smart-default would wrongly prepend 'search' to a valid subcommand.
    This test catches that drift.
    """
    registered = {cmd.name for cmd in app.registered_commands}
    # setup is an add_typer sub-app, not a command — check registered_groups
    group_names = {g.name for g in app.registered_groups}
    all_names = registered | group_names

    expected_subcommands = {"search", "details", "enrich", "mcp", "mcp-http", "setup"}
    assert expected_subcommands <= all_names
    assert expected_subcommands <= _KNOWN_COMMANDS


def test_top_level_help_lists_all_commands():
    """Regression guard: `stays --help` must surface every user-facing
    subcommand. If a command silently drops from the registered app
    (or its help panel visibility flips to hidden), this test catches it.
    """
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("search", "details", "enrich", "mcp", "mcp-http", "setup"):
        assert name in result.stdout, f"'stays --help' missing '{name}' in output"


def test_setup_help_lists_all_backends():
    """Regression guard: `stays setup --help` must show claude/codex/chatgpt."""
    result = CliRunner().invoke(app, ["setup", "--help"])
    assert result.exit_code == 0
    for backend in ("claude", "codex", "chatgpt"):
        assert backend in result.stdout, f"'stays setup --help' missing '{backend}' in output"
