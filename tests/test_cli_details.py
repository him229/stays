from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from stays.cli import app
from stays.search.hotels import MissingHotelIdError
from tests.fixtures.cli_hotel_sample import make_detail


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def mock_search(monkeypatch):
    mock = MagicMock()
    mock.return_value.get_details.return_value = make_detail()
    monkeypatch.setattr("stays.cli.commands.details.SearchHotels", mock)
    return mock


def test_details_text(runner, mock_search):
    result = runner.invoke(app, ["details", "ChkI_key", "--check-in", "2026-07-22", "--check-out", "2026-07-26"])
    assert result.exit_code == 0
    assert "Deluxe Double" in result.stdout


def test_details_json_envelope(runner, mock_search):
    result = runner.invoke(
        app,
        [
            "details",
            "ChkI_key",
            "--check-in",
            "2026-07-22",
            "--check-out",
            "2026-07-26",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["search_type"] == "details"
    assert payload["hotel"]["rooms"][0]["name"] == "Deluxe Double"


def test_details_missing_dates_fails(runner, mock_search):
    result = runner.invoke(app, ["details", "ChkI_key"])
    assert result.exit_code == 2


def test_details_missing_id_error(runner, monkeypatch):
    mock = MagicMock()
    mock.return_value.get_details.side_effect = MissingHotelIdError("no id")
    monkeypatch.setattr("stays.cli.commands.details.SearchHotels", mock)
    result = runner.invoke(
        app,
        [
            "details",
            "ChkI_bad",
            "--check-in",
            "2026-07-22",
            "--check-out",
            "2026-07-26",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]["type"] == "validation_error"


def test_details_with_currency_flag(runner, mock_search):
    """Covers line 49: currency passed to get_details when --currency set."""
    result = runner.invoke(
        app,
        [
            "details",
            "ChkI_key",
            "--check-in",
            "2026-07-22",
            "--check-out",
            "2026-07-26",
            "--currency",
            "EUR",
        ],
    )
    assert result.exit_code == 0
    kwargs = mock_search.return_value.get_details.call_args.kwargs
    assert kwargs["currency"].name == "EUR"


def test_details_jsonl_format(runner, mock_search):
    """Covers lines 67-68: JSONL output path."""
    result = runner.invoke(
        app,
        [
            "details",
            "ChkI_key",
            "--check-in",
            "2026-07-22",
            "--check-out",
            "2026-07-26",
            "--format",
            "jsonl",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["rooms"][0]["name"] == "Deluxe Double"


def test_details_network_error(runner, monkeypatch):
    """Covers lines 55-56: network error path."""
    from stays.search.client import BatchExecuteError

    mock = MagicMock()
    mock.return_value.get_details.side_effect = BatchExecuteError("upstream down")
    monkeypatch.setattr("stays.cli.commands.details.SearchHotels", mock)
    result = runner.invoke(
        app,
        [
            "details",
            "ChkI_key",
            "--check-in",
            "2026-07-22",
            "--check-out",
            "2026-07-26",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]["type"] == "network_error"


def test_details_text_error_path(runner, monkeypatch):
    """Covers lines 80-81: text-mode error path."""
    mock = MagicMock()
    mock.return_value.get_details.side_effect = MissingHotelIdError("no id")
    monkeypatch.setattr("stays.cli.commands.details.SearchHotels", mock)
    result = runner.invoke(
        app,
        [
            "details",
            "ChkI_bad",
            "--check-in",
            "2026-07-22",
            "--check-out",
            "2026-07-26",
        ],
    )
    assert result.exit_code == 1
    assert "Error:" in result.stdout
