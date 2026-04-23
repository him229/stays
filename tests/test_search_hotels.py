"""Unit tests for SearchHotels (mocked HTTP)."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stays import (
    DateRange,
    HotelSearchFilters,
    Location,
)
from stays.models.google_hotels.base import Currency
from stays.search import (
    BatchExecuteError,
    Client,
    EnrichedResult,
    MissingHotelIdError,
    SearchHotels,
    TransientBatchExecuteError,
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
        except ValueError:
            # parse_detail_response raises ValueError when the fixture
            # (a search response) has no single-hotel detail entry — we
            # only care that the payload was built correctly.
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
    BatchExecuteError from the detail RPC classifies as a fatal error
    (non-retryable) on the EnrichedResult — the search itself still
    succeeds for the other hotels in the batch."""
    inner = json.loads(FIXTURE.read_text())
    call_log: list[str] = []

    def fake_post_rpc(self, rpc_id, payload):
        call_log.append(rpc_id)
        # Search request: outer[2][5] is None. Detail request: outer[2][5] is the entity_key.
        meta = payload[2] if len(payload) > 2 and isinstance(payload[2], list) else None
        if meta is None or len(meta) < 6 or meta[5] is None:
            return inner
        raise BatchExecuteError(f"simulated fatal failure for {rpc_id}")

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
        # BatchExecuteError is a fatal (non-retryable) failure.
        assert e.error_kind == "fatal"
        assert e.is_retryable is False


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


def _call_get_details_and_capture_payload(
    entity_key: str,
    dates: DateRange,
    location: Location | None = None,
    currency: Currency = Currency.USD,
):
    client = MagicMock()
    client.post_rpc.return_value = [None]
    search = SearchHotels(client=client)
    try:
        search.get_details(entity_key=entity_key, dates=dates, location=location, currency=currency)
    except Exception:
        pass  # mock response fails the parser; we only care about the outbound call
    return client.post_rpc.call_args.args[1]


def test_get_details_full_payload_matches_filter_format():
    """M3 characterization: get_details payload == HotelSearchFilters(entity_key=...).format()"""
    entity_key = "ChkIxxx"
    dates = DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4))
    expected = HotelSearchFilters(
        location=Location(query="hotels"),  # default used by get_details when caller passes None
        dates=dates,
        currency=Currency.USD,
        entity_key=entity_key,
    ).format()
    got = _call_get_details_and_capture_payload(entity_key, dates)
    assert got == expected


def test_get_details_full_payload_equality_with_location_and_currency():
    entity_key = "ChkI_otherhotel"
    dates = DateRange(check_in=date(2026, 12, 20), check_out=date(2026, 12, 23))
    location = Location(query="paris hotels")
    currency = Currency.EUR
    expected = HotelSearchFilters(
        location=location,
        dates=dates,
        currency=currency,
        entity_key=entity_key,
    ).format()
    got = _call_get_details_and_capture_payload(entity_key, dates, location, currency)
    assert got == expected


# ---------------------------------------------------------------------------
# M4a — search_with_details error-classification contract
#
# Contract (new):
#   * TransientBatchExecuteError -> error_kind="transient", is_retryable=True
#   * BatchExecuteError / MissingHotelIdError -> error_kind="fatal",
#     is_retryable=False
#   * Unknown exceptions (KeyError, ValueError from a parser bug, etc.)
#     PROPAGATE out of search_with_details — we no longer stringify them
#     into per-hotel "unexpected: ..." errors.
# ---------------------------------------------------------------------------


def _make_search_hotels_with_mocked_details(side_effects_per_hotel):
    """Build a SearchHotels whose ``.search()`` returns N fake hotels and
    whose ``.get_details()`` either raises or returns according to
    ``side_effects_per_hotel``.

    ``side_effects_per_hotel`` is a list whose entries are either
    ``HotelDetail`` instances (returned by get_details) or exception
    instances (raised by get_details).
    """
    from stays.models.google_hotels.result import HotelResult

    client = MagicMock()
    search = SearchHotels(client=client, detail_concurrency=1)

    fake_results = [HotelResult(name=f"hotel-{i}", entity_key=f"key-{i}") for i in range(len(side_effects_per_hotel))]
    search.search = MagicMock(return_value=fake_results)

    effects = iter(side_effects_per_hotel)

    def fake_get_details(**_kwargs):
        effect = next(effects)
        if isinstance(effect, Exception):
            raise effect
        return effect

    search.get_details = MagicMock(side_effect=fake_get_details)
    return search, fake_results


def _enrich_filters() -> HotelSearchFilters:
    """Minimal valid filters for search_with_details (dates required)."""
    return HotelSearchFilters(
        location=Location(query="x"),
        dates=DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4)),
    )


def test_enrich_transient_error_is_retryable():
    """TransientBatchExecuteError for one hotel yields
    EnrichedResult(error_kind='transient', is_retryable=True) — and
    peers in the same batch still enrich successfully."""
    from stays import HotelDetail

    ok_detail = HotelDetail(name="hotel-1", entity_key="key-1")
    search, _ = _make_search_hotels_with_mocked_details([TransientBatchExecuteError("429 from Google"), ok_detail])

    results = search.search_with_details(_enrich_filters(), max_hotels=2)

    assert len(results) == 2
    assert results[0].ok is False
    assert results[0].error_kind == "transient"
    assert results[0].is_retryable is True
    assert "TransientBatchExecuteError" in (results[0].error or "")
    assert results[1].ok is True
    assert results[1].error_kind is None
    assert results[1].is_retryable is False


def test_enrich_fatal_error_is_not_retryable():
    """BatchExecuteError yields error_kind='fatal', is_retryable=False."""
    search, _ = _make_search_hotels_with_mocked_details([BatchExecuteError("malformed response")])

    results = search.search_with_details(_enrich_filters(), max_hotels=1)

    assert len(results) == 1
    assert results[0].ok is False
    assert results[0].error_kind == "fatal"
    assert results[0].is_retryable is False
    assert "BatchExecuteError" in (results[0].error or "")


def test_enrich_unexpected_exception_propagates():
    """Parser / programming bugs (e.g. KeyError) MUST propagate rather
    than being silently stringified into an "unexpected: ..." error on
    the EnrichedResult. This is the regression guard for the new
    M4a contract — the whole point of this task."""
    search, _ = _make_search_hotels_with_mocked_details([KeyError("missing slot")])

    with pytest.raises(KeyError):
        search.search_with_details(_enrich_filters(), max_hotels=1)


def test_enriched_result_ok_property_backward_compatible():
    """`.ok` keeps returning True iff ``detail`` is populated — the
    property semantics are unchanged by the error_kind / is_retryable
    additions."""
    from stays import HotelDetail, HotelResult

    r = HotelResult(name="x", entity_key="k")

    # No detail -> not ok
    failure = EnrichedResult(result=r, error="boom", error_kind="fatal")
    assert failure.ok is False
    # ... and a fatal failure is NOT retryable.
    assert failure.is_retryable is False

    # A transient failure IS retryable, but still not ok.
    transient = EnrichedResult(result=r, error="rl", error_kind="transient")
    assert transient.ok is False
    assert transient.is_retryable is True

    # Detail populated -> ok, and ok items are not retryable.
    success = EnrichedResult(result=r, detail=HotelDetail(name="x", entity_key="k"))
    assert success.ok is True
    assert success.is_retryable is False
    assert success.error_kind is None
