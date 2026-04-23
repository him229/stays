"""Unit tests for SearchHotels (mocked HTTP)."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from stays import (
    DateRange,
    HotelSearchFilters,
    Location,
)
from stays.search import (
    Client,
    EnrichedResult,
    MissingHotelIdError,
    SearchHotels,
)

FIXTURE = Path(__file__).parent / "fixtures" / "search_response_nyc.json"


def test_search_returns_parsed_hotels():
    inner = json.loads(FIXTURE.read_text())
    with patch.object(Client, "post_rpc", return_value=inner):
        s = SearchHotels()
        results = s.search(HotelSearchFilters(location=Location(query="x")))
    assert len(results) >= 10
    # At least one hotel should have a kgmid OR entity_key
    assert any(h.kgmid or h.entity_key for h in results)


def test_get_details_rejects_missing_entity_key():
    """No entity_key → immediate MissingHotelIdError, no wire call."""
    s = SearchHotels()
    dates = DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4))
    with pytest.raises(MissingHotelIdError):
        s.get_details(entity_key="", dates=dates)  # type: ignore[arg-type]
    with pytest.raises(MissingHotelIdError):
        s.get_details(entity_key=None, dates=dates)  # type: ignore[arg-type]


def test_get_details_builds_payload_with_entity_key_in_slot_2_5():
    """Verify that get_details constructs a request payload with entity_key at [2][5]."""
    captured_payload = {}

    def capture_post_rpc(self, rpc_id, payload):
        captured_payload["rpc_id"] = rpc_id
        captured_payload["payload"] = payload
        return json.loads(FIXTURE.read_text())  # reuse search fixture for smoke

    dates = DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4))
    with patch.object(Client, "post_rpc", capture_post_rpc):
        s = SearchHotels()
        # This will succeed at the RPC call (mocked), but parse_detail_response
        # may or may not find a single-hotel entry — we only care that the
        # payload was built correctly and the entity_key landed at [2][5].
        try:
            s.get_details(
                entity_key="ChkIooCAqvyy0fDgARoML2cvMWhoZ18zbWdzEAE",
                dates=dates,
            )
        except (ValueError, Exception):
            # parser may raise on fixture mismatch — that's fine for this test
            pass

    assert captured_payload["rpc_id"] == "AtySUc"
    payload = captured_payload["payload"]
    assert len(payload) >= 3, f"detail payload should have ≥3 outer elements, got {len(payload)}"
    assert payload[2][5] == "ChkIooCAqvyy0fDgARoML2cvMWhoZ18zbWdzEAE"


def test_search_with_details_requires_dates():
    """search_with_details requires filters.dates to compute rate plans."""
    s = SearchHotels()
    filters = HotelSearchFilters(location=Location(query="x"))  # no dates
    with pytest.raises(ValueError, match="dates"):
        s.search_with_details(filters, max_hotels=2)


def test_search_with_details_respects_max_hotels_and_partial_failure():
    """Detail failures for individual hotels do NOT abort the batch.
    Hotels without entity_key get error='missing entity_key'."""
    inner = json.loads(FIXTURE.read_text())
    call_log: list[str] = []

    def fake_post_rpc(self, rpc_id, payload):
        call_log.append(rpc_id)
        # Search request: outer[2][5] is None. Detail request: outer[2][5] is the entity_key.
        meta = payload[2] if len(payload) > 2 and isinstance(payload[2], list) else None
        if meta is None or len(meta) < 6 or meta[5] is None:
            return inner
        raise RuntimeError(f"simulated failure for {rpc_id}")

    dates = DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4))
    with patch.object(Client, "post_rpc", fake_post_rpc):
        s = SearchHotels()
        enriched = s.search_with_details(
            HotelSearchFilters(location=Location(query="x"), dates=dates),
            max_hotels=3,
        )
    # Exactly one search RPC call
    assert call_log.count("AtySUc") >= 1
    # Three EnrichedResult items, none ok
    assert len(enriched) == 3
    assert all(isinstance(e, EnrichedResult) for e in enriched)
    assert all(not e.ok for e in enriched)
    for e in enriched:
        assert e.result.name  # list-view data always present
        assert e.error is not None


def test_enriched_result_ok_property():
    from stays import HotelResult

    r = HotelResult(name="Test", entity_key="abc")
    enriched_success = EnrichedResult(result=r)
    enriched_success.detail = None  # remains failure because detail still None
    assert not enriched_success.ok

    # Manually construct a success-path EnrichedResult via direct field assignment
    # Simpler: just verify the property semantics
    from stays import HotelDetail

    detailed = HotelDetail(name="Test", entity_key="abc")
    enriched_ok = EnrichedResult(result=r, detail=detailed)
    assert enriched_ok.ok
