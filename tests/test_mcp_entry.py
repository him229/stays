"""Smoke tests for the MCP entry module."""

from __future__ import annotations

from stays.mcp import _entry


def test_run_is_callable():
    assert callable(_entry.run)


def test_run_http_is_callable():
    assert callable(_entry.run_http)
