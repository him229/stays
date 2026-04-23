"""Protocol adapters over the three legacy setup backends.

Each adapter wraps one of the existing backend modules unchanged:

- ``ClaudeAdapter`` → ``stays.mcp.setup.claude``
- ``CodexAdapter`` → ``stays.mcp.setup.codex``
- ``ChatGPTAdapter`` → ``stays.mcp.setup.chatgpt`` (instructions-only)

Adapters exist so callers can hold a ``SetupBackend`` without knowing
which client they're targetting. ``BACKENDS`` is the canonical registry
keyed by ``Kind``.
"""

from __future__ import annotations

from typing import Any

from stays.mcp.setup import canonical_mcp_json
from stays.mcp.setup import chatgpt as chatgpt_backend
from stays.mcp.setup import claude as claude_backend
from stays.mcp.setup import codex as codex_backend
from stays.mcp.setup._backend import Kind, SetupBackend, SetupReport


def _claude_summary(report: claude_backend.ClaudeSetupReport) -> str:
    """Collapse a multi-message Claude report into one summary line."""
    if report.messages:
        return " ".join(report.messages)
    if report.claude_code_registered:
        return "Claude Code: registered 'stays' (user scope)."
    if report.claude_desktop_patched:
        return f"Claude Desktop: patched {report.desktop_config_path}."
    return "Claude setup: no-op."


def _claude_ok(report: claude_backend.ClaudeSetupReport) -> bool:
    """Claude registration is "ok" when any path produced a useful result.

    That is: either we auto-registered (CLI or Desktop), or we produced
    a ``fallback_json`` snippet the user can paste manually. Only a
    silent no-op would be "not ok" — which shouldn't happen in practice.
    """
    return bool(
        report.claude_code_registered
        or report.claude_desktop_patched
        or report.fallback_json is not None
        or any("already" in m for m in report.messages)
    )


class ClaudeAdapter:
    """Adapts ``stays.mcp.setup.claude`` to the ``SetupBackend`` Protocol."""

    kind: Kind = "claude"

    def register(self, **kwargs: Any) -> SetupReport:
        report = claude_backend.register(**kwargs)
        return SetupReport(
            kind=self.kind,
            ok=_claude_ok(report),
            message=_claude_summary(report),
            config_text=report.fallback_json,
        )

    def build_instructions(self) -> str:
        return canonical_mcp_json()


class CodexAdapter:
    """Adapts ``stays.mcp.setup.codex`` to the ``SetupBackend`` Protocol."""

    kind: Kind = "codex"

    def register(self, **kwargs: Any) -> SetupReport:
        report = codex_backend.register(**kwargs)
        ok = bool(report.registered or report.already_present or report.fallback_toml is not None)
        message = " ".join(report.messages) if report.messages else "Codex setup: no-op."
        return SetupReport(
            kind=self.kind,
            ok=ok,
            message=message,
            config_text=report.fallback_toml,
        )

    def build_instructions(self) -> str:
        return codex_backend.canonical_toml()


class ChatGPTAdapter:
    """Adapts ``stays.mcp.setup.chatgpt`` to the ``SetupBackend`` Protocol.

    ChatGPT has no automated registration — ``register()`` simply
    returns the instructions as ``config_text``.
    """

    kind: Kind = "chatgpt"

    def register(self, **kwargs: Any) -> SetupReport:
        # chatgpt_backend.build() takes no kwargs; callers get a report
        # back regardless of what they pass so the Protocol signature
        # stays uniform across backends.
        del kwargs
        return SetupReport(
            kind=self.kind,
            ok=True,
            message="ChatGPT: instructions generated (no automated registration path).",
            config_text=self.build_instructions(),
        )

    def build_instructions(self) -> str:
        out = chatgpt_backend.build()
        header = f"Settings: {out.settings_url}"
        body = "\n".join(out.messages)
        return f"{header}\n\n{body}"


BACKENDS: dict[Kind, SetupBackend] = {
    "claude": ClaudeAdapter(),
    "codex": CodexAdapter(),
    "chatgpt": ChatGPTAdapter(),
}
