"""Per-client MCP registration helpers.

Each client module exposes a ``register(...)`` (auto-registers where it
can) or ``build()`` function (instructions-only clients like ChatGPT).

Shared helpers here:
- ``resolve_stays_command()`` — find the installed ``stays`` binary path
- ``canonical_server_block()`` — ``{"command", "args"}`` dict
- ``canonical_mcp_json()`` — Claude-style ``{"mcpServers": {...}}`` string
- ``SERVER_KEY`` — the well-known name "stays"

Protocol-path surface (additive — legacy ``register(...)`` / ``build()``
signatures are unchanged):
- ``SetupBackend`` / ``SetupReport`` — in ``_backend``
- ``BACKENDS`` — dict[Kind, SetupBackend] adapting the three backends
"""

from __future__ import annotations

import json
import shutil
import sys
from typing import Any

SERVER_KEY = "stays"


def resolve_stays_command() -> tuple[str, list[str]]:
    """Return (command, args) for launching the stays MCP stdio server.

    Prefers the installed ``stays`` binary so config blocks read naturally.
    Falls back to ``<sys.executable> -m stays.mcp._entry`` when ``stays``
    isn't on PATH (editable/dev install case).
    """
    stays_bin = shutil.which("stays")
    if stays_bin is not None:
        return stays_bin, ["mcp"]
    return sys.executable, ["-m", "stays.mcp._entry"]


def canonical_server_block() -> dict[str, Any]:
    cmd, args = resolve_stays_command()
    return {"command": cmd, "args": args}


def canonical_mcp_json() -> str:
    return json.dumps(
        {"mcpServers": {SERVER_KEY: canonical_server_block()}},
        indent=2,
    )


# Protocol-path re-exports (see stays/mcp/setup/_backend.py + _adapters.py).
# Placed AFTER the shared helpers to avoid circular imports during package init.
from stays.mcp.setup._adapters import BACKENDS  # noqa: E402, F401  (public API)
from stays.mcp.setup._backend import (  # noqa: E402, F401  (public API)
    Kind,
    SetupBackend,
    SetupReport,
)
