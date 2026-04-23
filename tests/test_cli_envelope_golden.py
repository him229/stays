"""Byte-equality golden tests for CLI envelopes.

These tests characterize the exact stdout produced by every
``(command, format)`` × ``(happy-path, validation-error)`` combination
before the S2 runtime extraction refactor. Any drift means the CLI's
observable contract changed — which must be intentional.

Each fixture on disk is loaded as:
- ``.json``  → parsed into a dict, compared with ``==``
- ``.jsonl`` → split into lines, each parsed into a dict, list compared
- ``.txt``   → compared as raw string

Mocking strategy: we stub ``stays.search.hotels.SearchHotels`` at the
``stays.cli.commands.{search,details,enrich}`` import sites so no
network I/O occurs. The returned ``HotelResult`` / ``HotelDetail`` /
``EnrichedResult``-shaped objects come from
``tests.fixtures.cli_hotel_sample``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from stays.cli import app
from tests.fixtures.cli_hotel_sample import make_detail, make_result

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _fixture_path(name: str) -> Path:
    return FIXTURES_DIR / name


def _load_json(name: str) -> dict:
    return json.loads(_fixture_path(name).read_text(encoding="utf-8"))


def _load_jsonl(name: str) -> list[dict]:
    raw = _fixture_path(name).read_text(encoding="utf-8")
    return [json.loads(ln) for ln in raw.splitlines() if ln.strip()]


def _load_text(name: str) -> str:
    return _fixture_path(name).read_text(encoding="utf-8")


def _parse_stdout_json(stdout: str) -> dict:
    return json.loads(stdout)


def _parse_stdout_jsonl(stdout: str) -> list[dict]:
    return [json.loads(ln) for ln in stdout.splitlines() if ln.strip()]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---- search mocks ----------------------------------------------------


@pytest.fixture
def mock_search_two(monkeypatch):
    """Mock SearchHotels().search() to return exactly 2 fixed HotelResults."""
    mock = MagicMock()
    mock.return_value.search.return_value = [
        make_result(),
        make_result(
            name="Second Hotel",
            entity_key="CgoI_TEST_KEY_0002",
            display_price=240,
            star_class=5,
            overall_rating=4.7,
            review_count=980,
        ),
    ]
    monkeypatch.setattr("stays.cli.commands.search.SearchHotels", mock)
    return mock


# ---- details mocks ---------------------------------------------------


@pytest.fixture
def mock_details_one(monkeypatch):
    mock = MagicMock()
    mock.return_value.get_details.return_value = make_detail()
    monkeypatch.setattr("stays.cli.commands.details.SearchHotels", mock)
    return mock


# ---- enrich mocks ----------------------------------------------------


def _mk_enriched(ok: bool, *, error: str | None = None, error_kind: str | None = None):
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
def mock_enrich_two(monkeypatch):
    mock = MagicMock()
    mock.return_value.search_with_details.return_value = [
        _mk_enriched(True),
        _mk_enriched(False, error="hotel ID missing"),
    ]
    monkeypatch.setattr("stays.cli.commands.enrich.SearchHotels", mock)
    return mock


# ---- search envelope tests -------------------------------------------


class TestSearchHappy:
    def test_json(self, runner, mock_search_two):
        result = runner.invoke(app, ["search", "tokyo", "--format", "json"])
        assert result.exit_code == 0
        assert _parse_stdout_json(result.stdout) == _load_json("cli_envelope_search_happy.json")

    def test_jsonl(self, runner, mock_search_two):
        result = runner.invoke(app, ["search", "tokyo", "--format", "jsonl"])
        assert result.exit_code == 0
        assert _parse_stdout_jsonl(result.stdout) == _load_jsonl("cli_envelope_search_happy.jsonl")

    def test_text(self, runner, mock_search_two):
        result = runner.invoke(app, ["search", "tokyo"])
        assert result.exit_code == 0
        assert result.stdout == _load_text("cli_envelope_search_happy.txt")


class TestSearchValidationError:
    def test_json(self, runner, mock_search_two):
        result = runner.invoke(app, ["search", "tokyo", "--check-in", "bogus", "--format", "json"])
        assert result.exit_code == 1
        assert _parse_stdout_json(result.stdout) == _load_json("cli_envelope_search_validation_error.json")

    def test_jsonl(self, runner, mock_search_two):
        result = runner.invoke(app, ["search", "tokyo", "--check-in", "bogus", "--format", "jsonl"])
        assert result.exit_code == 1
        assert _parse_stdout_jsonl(result.stdout) == _load_jsonl("cli_envelope_search_validation_error.jsonl")

    def test_text(self, runner, mock_search_two):
        result = runner.invoke(app, ["search", "tokyo", "--check-in", "bogus"])
        assert result.exit_code == 1
        assert result.stdout == _load_text("cli_envelope_search_validation_error.txt")


# ---- details envelope tests ------------------------------------------


class TestDetailsHappy:
    def test_json(self, runner, mock_details_one):
        result = runner.invoke(
            app,
            ["details", "ChkI_key", "--check-in", "2026-07-22", "--check-out", "2026-07-26", "--format", "json"],
        )
        assert result.exit_code == 0
        assert _parse_stdout_json(result.stdout) == _load_json("cli_envelope_details_happy.json")

    def test_jsonl(self, runner, mock_details_one):
        result = runner.invoke(
            app,
            ["details", "ChkI_key", "--check-in", "2026-07-22", "--check-out", "2026-07-26", "--format", "jsonl"],
        )
        assert result.exit_code == 0
        assert _parse_stdout_jsonl(result.stdout) == _load_jsonl("cli_envelope_details_happy.jsonl")

    def test_text(self, runner, mock_details_one):
        result = runner.invoke(
            app,
            ["details", "ChkI_key", "--check-in", "2026-07-22", "--check-out", "2026-07-26"],
        )
        assert result.exit_code == 0
        assert result.stdout == _load_text("cli_envelope_details_happy.txt")


class TestDetailsValidationError:
    # Missing --check-in / --check-out is a typer parse-time error (exit 2).
    # The envelope stays empty — typer writes its own usage error to stderr.
    # To exercise our in-body validation error path we use MissingHotelIdError,
    # which the command maps to a validation_error envelope with exit 1.

    def test_json(self, runner, monkeypatch):
        from stays.search.hotels import MissingHotelIdError

        mock = MagicMock()
        mock.return_value.get_details.side_effect = MissingHotelIdError("hotel ID missing")
        monkeypatch.setattr("stays.cli.commands.details.SearchHotels", mock)
        result = runner.invoke(
            app,
            ["details", "ChkI_bad", "--check-in", "2026-07-22", "--check-out", "2026-07-26", "--format", "json"],
        )
        assert result.exit_code == 1
        assert _parse_stdout_json(result.stdout) == _load_json("cli_envelope_details_validation_error.json")

    def test_jsonl(self, runner, monkeypatch):
        from stays.search.hotels import MissingHotelIdError

        mock = MagicMock()
        mock.return_value.get_details.side_effect = MissingHotelIdError("hotel ID missing")
        monkeypatch.setattr("stays.cli.commands.details.SearchHotels", mock)
        result = runner.invoke(
            app,
            ["details", "ChkI_bad", "--check-in", "2026-07-22", "--check-out", "2026-07-26", "--format", "jsonl"],
        )
        assert result.exit_code == 1
        assert _parse_stdout_jsonl(result.stdout) == _load_jsonl("cli_envelope_details_validation_error.jsonl")

    def test_text(self, runner, monkeypatch):
        from stays.search.hotels import MissingHotelIdError

        mock = MagicMock()
        mock.return_value.get_details.side_effect = MissingHotelIdError("hotel ID missing")
        monkeypatch.setattr("stays.cli.commands.details.SearchHotels", mock)
        result = runner.invoke(
            app,
            ["details", "ChkI_bad", "--check-in", "2026-07-22", "--check-out", "2026-07-26"],
        )
        assert result.exit_code == 1
        assert result.stdout == _load_text("cli_envelope_details_validation_error.txt")


# ---- enrich envelope tests -------------------------------------------


class TestEnrichHappy:
    def test_json(self, runner, mock_enrich_two):
        result = runner.invoke(app, ["enrich", "tokyo", "--max-hotels", "2", "--format", "json"])
        assert result.exit_code == 0
        assert _parse_stdout_json(result.stdout) == _load_json("cli_envelope_enrich_happy.json")

    def test_jsonl(self, runner, mock_enrich_two):
        result = runner.invoke(app, ["enrich", "tokyo", "--max-hotels", "2", "--format", "jsonl"])
        assert result.exit_code == 0
        assert _parse_stdout_jsonl(result.stdout) == _load_jsonl("cli_envelope_enrich_happy.jsonl")

    def test_text(self, runner, mock_enrich_two):
        result = runner.invoke(app, ["enrich", "tokyo", "--max-hotels", "2"])
        assert result.exit_code == 0
        assert result.stdout == _load_text("cli_envelope_enrich_happy.txt")


class TestEnrichValidationError:
    def test_json(self, runner, mock_enrich_two):
        result = runner.invoke(
            app,
            ["enrich", "tokyo", "--check-in", "bogus", "--format", "json"],
        )
        assert result.exit_code == 1
        assert _parse_stdout_json(result.stdout) == _load_json("cli_envelope_enrich_validation_error.json")

    def test_jsonl(self, runner, mock_enrich_two):
        result = runner.invoke(
            app,
            ["enrich", "tokyo", "--check-in", "bogus", "--format", "jsonl"],
        )
        assert result.exit_code == 1
        assert _parse_stdout_jsonl(result.stdout) == _load_jsonl("cli_envelope_enrich_validation_error.jsonl")

    def test_text(self, runner, mock_enrich_two):
        result = runner.invoke(app, ["enrich", "tokyo", "--check-in", "bogus"])
        assert result.exit_code == 1
        assert result.stdout == _load_text("cli_envelope_enrich_validation_error.txt")
