"""`stays mcp` + `stays mcp-http` subcommands — thin delegations."""

from __future__ import annotations


def mcp() -> None:
    """Run the stays MCP server over stdio (what Claude Code / Desktop spawn)."""
    from stays.mcp._entry import run as _run

    _run()


def mcp_http() -> None:
    """Run the stays MCP server over streamable HTTP (dev / Docker)."""
    from stays.mcp._entry import run_http as _run_http

    _run_http()
