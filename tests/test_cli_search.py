"""Offline CLI tests for `stays search`."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from stays.cli import app
from stays.search.client import BatchExecuteError
from tests.fixtures.cli_hotel_sample import make_result


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def mock_search(monkeypatch):
    mock = MagicMock()
    mock.return_value.search.return_value = [make_result(), make_result(name="Second Hotel")]
    monkeypatch.setattr("stays.cli.commands.search.SearchHotels", mock)
    return mock


class TestHappyPath:
    def test_basic_text(self, runner, mock_search):
        result = runner.invoke(app, ["search", "tokyo"])
        assert result.exit_code == 0
        # Rich may wrap long names across multiple lines — check stripped content.
        collapsed = " ".join(result.stdout.split())
        assert "Tokyo" in collapsed and "Central" in collapsed
        mock_search.return_value.search.assert_called_once()

    def test_json_envelope(self, runner, mock_search):
        result = runner.invoke(app, ["search", "tokyo", "--format", "json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert payload["search_type"] == "search"
        assert payload["count"] == 2
        assert payload["hotels"][0]["name"] == "Tokyo Central Hotel"

    def test_jsonl(self, runner, mock_search):
        result = runner.invoke(app, ["search", "tokyo", "--format", "jsonl"])
        assert result.exit_code == 0
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        assert len(lines) == 2
        assert json.loads(lines[0])["name"] == "Tokyo Central Hotel"

    def test_max_results_slices(self, runner, mock_search):
        result = runner.invoke(app, ["search", "tokyo", "--max-results", "1", "--format", "json"])
        payload = json.loads(result.stdout)
        assert payload["count"] == 1


class TestFilters:
    def test_stars_and_amenities_and_brands(self, runner, mock_search):
        result = runner.invoke(
            app,
            [
                "search",
                "tokyo",
                "--stars",
                "4",
                "--stars",
                "5",
                "--amenity",
                "POOL",
                "--amenity",
                "WIFI",
                "--brand",
                "HILTON",
                "--free-cancellation",
                "--price-min",
                "100",
                "--price-max",
                "300",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        # Verify the mock received a filters object with the right fields.
        call = mock_search.return_value.search.call_args
        filters = call.args[0]
        assert filters.hotel_class == [4, 5]
        assert filters.amenities and {a.name for a in filters.amenities} == {"POOL", "WIFI"}
        assert filters.brands and filters.brands[0].name == "HILTON"
        assert filters.free_cancellation is True
        assert filters.price_range == (100, 300)


class TestErrors:
    # Important: validation errors surfaced from inside the command body
    # (date, enum, price-range, asymmetric dates) exit 1 with our envelope
    # in JSON/JSONL mode, or a one-line "Error: …" in text mode. Only
    # typer's native parse-time validation (min/max, Enum coercion,
    # missing required) exits 2. See spec "Exit codes" table.

    def test_bad_date_text_mode(self, runner, mock_search):
        result = runner.invoke(app, ["search", "tokyo", "--check-in", "bogus"])
        assert result.exit_code == 1
        assert "YYYY-MM-DD" in result.stdout

    def test_bad_date_json_envelope(self, runner, mock_search):
        result = runner.invoke(app, ["search", "tokyo", "--check-in", "bogus", "--format", "json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["success"] is False
        assert payload["error"]["type"] == "validation_error"
        assert "YYYY-MM-DD" in payload["error"]["message"]

    def test_asymmetric_dates(self, runner, mock_search):
        result = runner.invoke(app, ["search", "tokyo", "--check-in", "2026-08-01"])
        # asymmetric dates raise typer.BadParameter inside the body -> exit 1
        assert result.exit_code == 1
        assert "both --check-in and --check-out" in result.stdout.lower()

    def test_price_min_ge_max(self, runner, mock_search):
        result = runner.invoke(
            app,
            ["search", "tokyo", "--price-min", "300", "--price-max", "100"],
        )
        assert result.exit_code == 1
        assert "price" in result.stdout.lower()

    def test_unknown_amenity(self, runner, mock_search):
        result = runner.invoke(app, ["search", "tokyo", "--amenity", "HELIPAD"])
        assert result.exit_code == 1
        assert "Amenity" in result.stdout

    def test_unknown_amenity_json_envelope(self, runner, mock_search):
        result = runner.invoke(
            app,
            ["search", "tokyo", "--amenity", "HELIPAD", "--format", "json"],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["success"] is False
        assert payload["error"]["type"] == "validation_error"

    def test_typer_parse_time_error_still_exits_2(self, runner, mock_search):
        # --max-results is typer.min=1/max=25 -> typer catches at parse time -> exit 2
        result = runner.invoke(app, ["search", "tokyo", "--max-results", "99"])
        assert result.exit_code == 2

    def test_network_error_becomes_json_envelope(self, runner, monkeypatch):
        mock = MagicMock()
        mock.return_value.search.side_effect = BatchExecuteError("upstream down")
        monkeypatch.setattr("stays.cli.commands.search.SearchHotels", mock)

        result = runner.invoke(app, ["search", "tokyo", "--format", "json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["success"] is False
        assert payload["error"]["type"] == "network_error"


class TestEmptyResults:
    def test_text_mode_prints_no_hotels(self, runner, monkeypatch):
        mock = MagicMock()
        mock.return_value.search.return_value = []
        monkeypatch.setattr("stays.cli.commands.search.SearchHotels", mock)
        result = runner.invoke(app, ["search", "tokyo"])
        assert result.exit_code == 0
        assert "No hotels" in result.stdout

    def test_json_mode_returns_zero_count(self, runner, monkeypatch):
        mock = MagicMock()
        mock.return_value.search.return_value = []
        monkeypatch.setattr("stays.cli.commands.search.SearchHotels", mock)
        result = runner.invoke(app, ["search", "tokyo", "--format", "json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["count"] == 0
        assert payload["hotels"] == []


def test_search_json_query_echo_includes_all_filters(runner, mock_search):
    """Regression: every filter the user passes must appear in the JSON
    query-record echo. Previously only a subset was echoed, making JSON
    output incomplete and hard to audit.
    """
    result = runner.invoke(
        app,
        [
            "search",
            "tokyo",
            "--check-in",
            "2026-09-01",
            "--check-out",
            "2026-09-04",
            "--currency",
            "EUR",
            "--property-type",
            "HOTELS",
            "--sort-by",
            "LOWEST_PRICE",
            "--min-rating",
            "FOUR_ZERO_PLUS",
            "--free-cancellation",
            "--eco-certified",
            "--special-offers",
            "--price-min",
            "100",
            "--price-max",
            "300",
            "--stars",
            "4",
            "--amenity",
            "POOL",
            "--brand",
            "HILTON",
            "--child-age",
            "8",
            "--children",
            "1",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0
    q = json.loads(result.stdout)["query"]
    assert q["query"] == "tokyo"
    assert q["check_in"] == "2026-09-01"
    assert q["check_out"] == "2026-09-04"
    assert q["currency"] == "EUR"
    assert q["property_type"] == "HOTELS"
    assert q["sort_by"] == "LOWEST_PRICE"
    assert q["min_rating"] == "FOUR_ZERO_PLUS"
    assert q["free_cancellation"] is True
    assert q["eco_certified"] is True
    assert q["special_offers"] is True
    assert q["price_min"] == 100
    assert q["price_max"] == 300
    assert q["stars"] == [4]
    assert q["amenities"] == ["POOL"]
    assert q["brands"] == ["HILTON"]
    assert q["child_ages"] == [8]
    assert q["children"] == 1
