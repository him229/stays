"""Snapshot-style tests for rich renderers."""

from __future__ import annotations

from rich.console import Console

from stays.cli import _render
from tests.fixtures.cli_hotel_sample import make_detail, make_result


def _capture(width: int = 120) -> Console:
    return Console(record=True, width=width, force_terminal=False)


class TestRenderResults:
    def test_single_result_shows_name(self) -> None:
        console = _capture()
        _render.render_results([make_result()], console=console)
        out = console.export_text()
        assert "Tokyo Central Hotel" in out
        assert "180" in out
        assert "4.3" in out

    def test_empty_list_prints_message(self) -> None:
        console = _capture()
        _render.render_results([], console=console)
        out = console.export_text()
        assert "No hotels" in out

    def test_narrow_width_still_renders(self) -> None:
        console = _capture(width=80)
        _render.render_results([make_result()], console=console)
        # No crash, and the name appears (possibly truncated).
        assert "Tokyo" in console.export_text()


class TestRenderDetail:
    def test_detail_shows_room_and_rate(self) -> None:
        console = _capture()
        _render.render_detail(make_detail(), console=console)
        out = console.export_text()
        assert "Deluxe Double" in out
        assert "Booking.com" in out
        assert "185" in out
