"""Codex CLI MCP registration.

Codex CLI stores MCP servers in ``~/.codex/config.toml`` under
``[mcp_servers.<name>]`` (snake_case, NOT the JSON ``mcpServers`` used
by Claude). The Codex CLI exposes ``codex mcp add/list/remove`` which
does a safe read-merge-write of the TOML; we shell out to it rather
than editing the file ourselves.

Fallback when ``codex`` is not on PATH: print a pasteable TOML block
targetting ``~/.codex/config.toml``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from stays.mcp.setup import SERVER_KEY, resolve_stays_command


@dataclass
class CodexSetupReport:
    registered: bool = False
    already_present: bool = False
    fallback_toml: str | None = None
    config_path: Path | None = None
    messages: list[str] = field(default_factory=list)


def _codex_bin() -> str | None:
    return shutil.which("codex")


def canonical_toml() -> str:
    """Return the TOML block a user can paste into ~/.codex/config.toml."""
    cmd, args = resolve_stays_command()
    return f"[mcp_servers.{SERVER_KEY}]\ncommand = {json.dumps(cmd)}\nargs = {json.dumps(args)}\n"


def _is_registered(codex: str) -> bool:
    result = subprocess.run(
        [codex, "mcp", "list", "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    if isinstance(entries, dict):
        return SERVER_KEY in entries
    if isinstance(entries, list):
        return any(isinstance(e, dict) and e.get("name") == SERVER_KEY for e in entries)
    return False


def register(
    *,
    replace: bool = False,
    print_toml_only: bool = False,
) -> CodexSetupReport:
    report = CodexSetupReport(config_path=Path.home() / ".codex" / "config.toml")

    if print_toml_only:
        report.fallback_toml = canonical_toml()
        report.messages.append(f"Paste the TOML below into {report.config_path}.")
        return report

    codex = _codex_bin()
    if codex is None:
        report.fallback_toml = canonical_toml()
        report.messages.append(f"Codex CLI not found on PATH. Paste the TOML below into {report.config_path}.")
        return report

    if _is_registered(codex):
        if not replace:
            report.already_present = True
            report.messages.append(f"Codex: '{SERVER_KEY}' already registered (pass --replace to overwrite).")
            return report
        subprocess.run([codex, "mcp", "remove", SERVER_KEY], check=False)

    cmd, args = resolve_stays_command()
    full = [codex, "mcp", "add", SERVER_KEY, "--", cmd, *args]
    rc = subprocess.call(full)
    if rc == 0:
        report.registered = True
        report.messages.append(f"Codex: registered '{SERVER_KEY}' in {report.config_path}.")
    else:
        report.fallback_toml = canonical_toml()
        report.messages.append(f"Codex: `codex mcp add` failed (exit {rc}). Paste the TOML below manually.")
    return report
