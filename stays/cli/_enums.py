"""CLI-specific enums (output format)."""

from __future__ import annotations

from enum import Enum


class OutputFormat(str, Enum):
    """Supported CLI output formats."""

    TEXT = "text"
    JSON = "json"
    JSONL = "jsonl"
