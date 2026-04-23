"""Typer application construction + command registration."""

from __future__ import annotations

import typer


def _resolve_version() -> str:
    """Read installed package version; fall back to a hardcoded default.

    We avoid importing ``stays.__version__`` to keep ``stays/__init__.py``
    untouched — modifying it introduces back-compat risk on library imports.
    Narrow to ``PackageNotFoundError`` so any other metadata glitch surfaces
    loudly rather than silently returning a stale hardcoded version.
    """
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    try:
        return _pkg_version("stays")
    except PackageNotFoundError:  # pragma: no cover - editable installs without metadata
        return "0.1.0"


_STAYS_VERSION = _resolve_version()

app = typer.Typer(
    name="stays",
    help="Search Google Hotels from the command line (and run the MCP server).",
    add_completion=True,
    no_args_is_help=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"stays {_STAYS_VERSION}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show stays version and exit.",
    ),
) -> None:
    """Search Google Hotels from the command line (and run the MCP server)."""


from stays.cli.commands.search import search as _search  # noqa: E402

app.command(name="search")(_search)

from stays.cli.commands.details import details as _details  # noqa: E402

app.command(name="details")(_details)

from stays.cli.commands.enrich import enrich as _enrich  # noqa: E402

app.command(name="enrich")(_enrich)

from stays.cli.commands.mcp import mcp as _mcp  # noqa: E402
from stays.cli.commands.mcp import mcp_http as _mcp_http  # noqa: E402

app.command(name="mcp")(_mcp)
app.command(name="mcp-http")(_mcp_http)

from stays.cli.commands.setup import setup_app  # noqa: E402

app.add_typer(setup_app, name="setup")
