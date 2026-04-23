"""Top-level CLI package for stays.

The console-script entry point is ``stays.cli._entry:run``. The typer
application object is built in ``stays.cli._app`` and re-exported here
for unit tests (``from stays.cli import app``).
"""

from __future__ import annotations

from stays.cli._app import app

__all__ = ["app"]
