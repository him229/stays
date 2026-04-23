"""Thin entry-point wrappers for the stays MCP server.

Called by the `stays mcp` and `stays mcp-http` CLI subcommands. The
`__main__` guard at the bottom also makes
`python -m stays.mcp._entry` work as a PATH-independent fallback —
used by `stays.mcp.setup.resolve_stays_command()` when the `stays`
binary isn't on PATH (editable/dev installs).
"""

import sys


def run() -> None:
    """Run the MCP server on stdio."""
    try:
        from stays.mcp.server import run as _run
    except ModuleNotFoundError:
        print(
            "MCP dependencies are missing from this install.\n"
            "Normally they ship with the `stays` package. Reinstall with:\n"
            "    pipx install --force stays\n"
            "or re-sync your dev environment with:\n"
            "    uv sync --extra dev",
            file=sys.stderr,
        )
        sys.exit(1)
    _run()


def run_http() -> None:
    """Run the MCP server over HTTP (streamable) — local dev only."""
    try:
        from stays.mcp.server import run_http as _run_http
    except ModuleNotFoundError:
        print(
            "MCP dependencies are missing from this install.\n"
            "Normally they ship with the `stays` package. Reinstall with:\n"
            "    pipx install --force stays\n"
            "or re-sync your dev environment with:\n"
            "    uv sync --extra dev",
            file=sys.stderr,
        )
        sys.exit(1)
    _run_http()


if __name__ == "__main__":
    run()
