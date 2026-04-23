from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from stays.cli import app
from tests.fixtures.cli_hotel_sample import make_detail, make_result


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _mk_item(
    ok: bool,
    *,
    error: str | None = None,
    error_kind: str | None = None,
):
    """Build a fake EnrichedResult-shaped object for the CLI tests.

    When ``ok`` is False, default ``error_kind`` to "fatal" — it matches
    the old stringified-error path for missing entity_key and keeps the
    existing test fixtures meaningful under the M4a contract.
    """
    result = make_result()
    if not ok and error_kind is None:
        error_kind = "fatal"
    return SimpleNamespace(
        ok=ok,
        result=result,
        detail=make_detail(result=result) if ok else None,
        error=error,
        error_kind=error_kind,
        is_retryable=error_kind == "transient",
    )


@pytest.fixture
def mock_enrich(monkeypatch):
    mock = MagicMock()
    mock.return_value.search_with_details.return_value = [
        _mk_item(True),
        _mk_item(False, error="hotel ID missing"),
    ]
    monkeypatch.setattr("stays.cli.commands.enrich.SearchHotels", mock)
    return mock


def test_enrich_text(runner, mock_enrich):
    result = runner.invoke(app, ["enrich", "tokyo", "--max-hotels", "2"])
    assert result.exit_code == 0
    assert "Deluxe Double" in result.stdout
    assert "hotel ID missing" in result.stdout


def test_enrich_json_surfaces_partial_failure(runner, mock_enrich):
    result = runner.invoke(app, ["enrich", "tokyo", "--max-hotels", "2", "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["count"] == 2
    statuses = [it["ok"] for it in payload["hotels"]]
    assert statuses == [True, False]
    assert payload["hotels"][1]["error"] == "hotel ID missing"


def test_enrich_jsonl_one_per_line(runner, mock_enrich):
    result = runner.invoke(app, ["enrich", "tokyo", "--max-hotels", "2", "--format", "jsonl"])
    assert result.exit_code == 0
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["ok"] is True


def test_enrich_max_hotels_limits_upper_bound(runner, mock_enrich):
    # max-hotels accepts 1..15 per typer, so 16 is a usage error:
    result = runner.invoke(app, ["enrich", "tokyo", "--max-hotels", "16"])
    assert result.exit_code == 2


def test_enrich_all_failures_returns_ok_envelope(runner, monkeypatch):
    mock = MagicMock()
    mock.return_value.search_with_details.return_value = [
        _mk_item(False, error="A"),
        _mk_item(False, error="B"),
    ]
    monkeypatch.setattr("stays.cli.commands.enrich.SearchHotels", mock)
    result = runner.invoke(app, ["enrich", "tokyo", "--max-hotels", "2", "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert all(not it["ok"] for it in payload["hotels"])


def test_enrich_network_error_json(runner, monkeypatch):
    """Covers lines 102-104: network error path in enrich."""
    from stays.search.client import BatchExecuteError

    mock = MagicMock()
    mock.return_value.search_with_details.side_effect = BatchExecuteError("down")
    monkeypatch.setattr("stays.cli.commands.enrich.SearchHotels", mock)
    result = runner.invoke(
        app,
        ["enrich", "tokyo", "--max-hotels", "2", "--format", "json"],
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]["type"] == "network_error"


def test_enrich_validation_error_json(runner, monkeypatch):
    """Covers lines 94-96: validation error path in enrich (bad date)."""
    result = runner.invoke(
        app,
        ["enrich", "tokyo", "--check-in", "bogus", "--format", "json"],
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]["type"] == "validation_error"
