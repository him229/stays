"""Shared rich Console instance for CLI output.

Tests override ``console`` via ``monkeypatch`` or construct a fresh
``Console(record=True)`` and pass it into render helpers explicitly.
"""

from __future__ import annotations

from rich.console import Console

console = Console()
