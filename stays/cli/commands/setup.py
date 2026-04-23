"""`stays setup {claude,codex,chatgpt}` — per-client MCP registration.

Each subcommand is a thin typer wrapper over `stays.mcp.setup.*.register()`
(claude/codex) or `build()` (chatgpt, instructions-only).

There is no bare `stays setup` command — the user must name the client
explicitly, which makes it obvious what's being modified.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.panel import Panel
from rich.text import Text

from stays.cli._console import console
from stays.mcp.setup import chatgpt as chatgpt_backend
from stays.mcp.setup import claude as claude_backend
from stays.mcp.setup import codex as codex_backend

setup_app = typer.Typer(
    name="setup",
    help="Register the stays MCP server with a client.",
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@setup_app.callback()
def _setup_callback(ctx: typer.Context) -> None:
    """When invoked bare (no subcommand), print help and exit 0 instead of
    click's default exit 2 — it's a discovery path, not a usage error.
    """
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit(0)


@setup_app.command(name="claude")
def claude_cmd(
    replace: Annotated[bool, typer.Option("--replace", help="Re-register if already present.")] = False,
    print_json: Annotated[bool, typer.Option("--print-json", help="Print the canonical JSON and exit.")] = False,
    desktop_only: Annotated[
        bool,
        typer.Option(
            "--desktop-only",
            help="Skip Claude Code CLI detection; only patch Claude Desktop config.",
        ),
    ] = False,
) -> None:
    """Register `stays` with Claude Code (CLI) and/or Claude Desktop."""
    report = claude_backend.register(
        replace=replace,
        force_desktop_only=desktop_only,
        print_json_only=print_json,
    )
    for line in report.messages:
        console.print(f"[cyan]•[/cyan] {line}")
    if report.backup_path:
        console.print(f"[dim]Backup written to {report.backup_path}[/dim]")
    if report.fallback_json is not None:
        console.print(Panel(Text(report.fallback_json), title="Canonical MCP JSON", border_style="yellow"))
    if report.claude_code_registered or report.claude_desktop_patched:
        console.print("[green]Done.[/green] Restart your Claude client to pick up the server.")


@setup_app.command(name="codex")
def codex_cmd(
    replace: Annotated[bool, typer.Option("--replace", help="Re-register if already present.")] = False,
    print_toml: Annotated[bool, typer.Option("--print-toml", help="Print the canonical TOML block and exit.")] = False,
) -> None:
    """Register `stays` with the Codex CLI (`codex mcp add`)."""
    report = codex_backend.register(replace=replace, print_toml_only=print_toml)
    for line in report.messages:
        console.print(f"[cyan]•[/cyan] {line}")
    if report.fallback_toml is not None:
        console.print(Panel(Text(report.fallback_toml), title="Canonical Codex TOML", border_style="yellow"))
    if report.registered:
        console.print("[green]Done.[/green] Restart Codex CLI to pick up the server.")


@setup_app.command(name="chatgpt")
def chatgpt_cmd(
    open_settings: Annotated[
        bool,
        typer.Option("--open", help="Also attempt to open the ChatGPT Connectors settings page."),
    ] = False,
) -> None:
    """Print ChatGPT MCP setup instructions (no local registration possible)."""
    instructions = chatgpt_backend.build()
    for line in instructions.messages:
        console.print(line)
    if open_settings:
        import webbrowser

        webbrowser.open(instructions.settings_url)
        console.print(f"[dim]Opened {instructions.settings_url} in your browser.[/dim]")
