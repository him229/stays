"""End-to-end CLI smoke test — hits google.com. Gated by `-m live`."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from typer.testing import CliRunner

from stays.cli import app


@pytest.mark.live
def test_search_live() -> None:
    check_in = (date.today() + timedelta(days=30)).isoformat()
    check_out = (date.today() + timedelta(days=33)).isoformat()
    result = CliRunner().invoke(
        app,
        [
            "search",
            "new york hotels",
            "--check-in",
            check_in,
            "--check-out",
            check_out,
            "--max-results",
            "3",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["count"] >= 1
    assert payload["hotels"][0]["name"]
