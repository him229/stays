"""Unified setup-backend Protocol + report type.

This is an *additive* surface: the three existing backend modules
(``stays.mcp.setup.{claude,codex,chatgpt}``) keep their current
``register(...)``/``build()`` signatures untouched. The
``SetupBackend`` protocol is a higher-level wrapper that adapters (in
``_adapters.py``) use to expose a uniform interface to callers that
don't want to care which client they're targetting.

``SetupReport`` deliberately uses a minimal shape: ``kind``, ``ok``,
``message``, ``config_text``. Richer per-backend details (e.g.
``ClaudeSetupReport.backup_path``) stay on the legacy reports; this
common shape is only for caller code that wants a uniform envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

Kind = Literal["claude", "codex", "chatgpt"]


@dataclass(frozen=True)
class SetupReport:
    """Uniform report returned by every ``SetupBackend.register`` call."""

    kind: Kind
    ok: bool
    message: str
    config_text: str | None = None


class SetupBackend(Protocol):
    """Common interface for per-client MCP registration backends."""

    kind: Kind

    def register(self, **kwargs: Any) -> SetupReport:
        """Attempt to register the ``stays`` MCP server for this client.

        ``ok=True`` means either the client is now registered or that
        the caller has been given everything needed to complete the
        registration manually (via ``config_text``).
        """

    def build_instructions(self) -> str:
        """Return a copy-pasteable config block / setup guide for this client."""
