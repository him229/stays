"""Console-script entry for ``stays`` with smart-default routing.

If the user invokes ``stays "tokyo" --stars 4`` without explicitly saying
``search``, we rewrite argv so it becomes ``stays search "tokyo" --stars 4``.
This matches the ergonomic flow used by https://github.com/punitarani/fli.
"""

from __future__ import annotations

import sys

_KNOWN_COMMANDS: frozenset[str] = frozenset(
    {
        "search",
        "details",
        "enrich",
        "mcp",
        "mcp-http",
        "setup",
        "--help",
        "-h",
        "--version",
        "--install-completion",
        "--show-completion",
    }
)


def _rewrite_argv(argv: list[str]) -> list[str]:
    """Return the argv to hand to typer after smart-default routing.

    Rules (argv is sys.argv[1:]):
    - empty -> append --help
    - first token is a known command / top-level flag -> no change
    - first token starts with '-' -> no change (typer will produce an error)
    - otherwise -> prepend 'search'
    """
    if not argv:
        return ["--help"]
    head = argv[0]
    if head in _KNOWN_COMMANDS:
        return argv
    if head.startswith("-"):
        return argv
    return ["search", *argv]


def run() -> None:
    """Console-script entry point."""
    sys.argv = [sys.argv[0], *_rewrite_argv(sys.argv[1:])]
    from stays.cli._app import app

    app()


if __name__ == "__main__":
    run()
