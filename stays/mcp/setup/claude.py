"""Claude Code (CLI) + Claude Desktop registration.

Detection order:
1. `claude` binary on PATH → register via ``claude mcp add``.
2. Claude Desktop config directory present → patch the JSON in place.
3. Neither → leave ``fallback_json`` populated on the report.

Both 1 and 2 can succeed in the same run; we honour whichever is present.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from stays.mcp.setup import (
    SERVER_KEY,
    canonical_mcp_json,
    canonical_server_block,
    resolve_stays_command,
)


class MalformedDesktopConfigError(RuntimeError):
    """Raised when claude_desktop_config.json cannot be safely edited."""


@dataclass
class ClaudeSetupReport:
    claude_code_registered: bool = False
    claude_desktop_patched: bool = False
    desktop_config_path: Path | None = None
    backup_path: Path | None = None
    fallback_json: str | None = None
    messages: list[str] = field(default_factory=list)


def claude_desktop_config_path(system: str | None = None) -> Path:
    system = system or platform.system()
    home = Path.home()
    if system == "Darwin":
        return home / "Library/Application Support/Claude/claude_desktop_config.json"
    if system == "Linux":
        return home / ".config/Claude/claude_desktop_config.json"
    if system == "Windows":
        return Path(os.environ.get("APPDATA", str(home))) / "Claude/claude_desktop_config.json"
    return home / ".claude_desktop_config.json"


def _is_registered_in_claude_code(claude: str) -> bool:
    """Check for exact registration — `stays` must be a server name, not
    a substring of another server's description. Uses `claude mcp get`
    which returns non-zero when the server isn't present.
    """
    result = subprocess.run(
        [claude, "mcp", "get", SERVER_KEY],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _register_claude_code(*, replace: bool, report: ClaudeSetupReport) -> None:
    claude = shutil.which("claude")
    if not claude:
        return
    if _is_registered_in_claude_code(claude):
        if not replace:
            report.messages.append(f"Claude Code: '{SERVER_KEY}' already registered (skipping — pass --replace).")
            return
        subprocess.run([claude, "mcp", "remove", SERVER_KEY, "-s", "user"], check=False)
    cmd, args = resolve_stays_command()
    # Claude CLI argv shape per `claude mcp add --help` v2.1.116+:
    #   claude mcp add [options] <name> <commandOrUrl> [args...]
    # Options MUST come before the name; COMMAND goes after `--`.
    full = [claude, "mcp", "add", "-s", "user", SERVER_KEY, "--", cmd, *args]
    rc = subprocess.call(full)
    if rc == 0:
        report.claude_code_registered = True
        report.messages.append(f"Claude Code: registered '{SERVER_KEY}' (user scope).")
    else:
        report.messages.append(f"Claude Code: registration failed (exit {rc}).")


def _patch_claude_desktop(path: Path, *, replace: bool, report: ClaudeSetupReport) -> None:
    def _write_backup() -> None:
        # Only invoked when we're about to mutate — or when we can't safely
        # parse the existing file and the caller needs the raw-state
        # preserved. A no-op re-run of `stays setup claude` does NOT touch
        # the filesystem, which keeps the user's config dir clean.
        if not raw or report.backup_path is not None:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_suffix(path.suffix + f".bak-{stamp}")
        backup.write_text(raw, encoding="utf-8")
        report.backup_path = backup

    raw = ""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        pass

    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            _write_backup()
            raise MalformedDesktopConfigError(
                f"{path} is not valid JSON ({exc}). Backup written; fix the file before retrying."
            ) from exc
    else:
        data = {}

    if not isinstance(data, dict):
        _write_backup()
        raise MalformedDesktopConfigError(f"{path} top-level value is not a JSON object. Backup written; fix manually.")

    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        _write_backup()
        raise MalformedDesktopConfigError(f"{path} has a non-object 'mcpServers' key. Backup written; fix manually.")

    if SERVER_KEY in servers and not replace:
        report.messages.append(f"Claude Desktop: '{SERVER_KEY}' already in {path} (skipping — pass --replace).")
        return

    _write_backup()
    servers[SERVER_KEY] = canonical_server_block()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    report.claude_desktop_patched = True
    report.desktop_config_path = path
    report.messages.append(f"Claude Desktop: patched {path}.")


def register(
    *,
    replace: bool = False,
    force_desktop_only: bool = False,
    print_json_only: bool = False,
) -> ClaudeSetupReport:
    report = ClaudeSetupReport()

    if print_json_only:
        report.fallback_json = canonical_mcp_json()
        return report

    desktop_path = claude_desktop_config_path()
    claude_code_detected = bool(shutil.which("claude")) and not force_desktop_only
    desktop_detected = force_desktop_only or desktop_path.parent.exists()

    if claude_code_detected:
        _register_claude_code(replace=replace, report=report)

    if desktop_detected:
        _patch_claude_desktop(desktop_path, replace=replace, report=report)

    # Only fall through to the JSON snippet when NEITHER client was detected.
    # An already-registered skip is silent success, not a failure.
    if not (claude_code_detected or desktop_detected):
        report.fallback_json = canonical_mcp_json()
        report.messages.append(
            "No Claude client detected (neither `claude` CLI nor Claude Desktop config dir). "
            "Paste the JSON below into your MCP client config."
        )
    return report
