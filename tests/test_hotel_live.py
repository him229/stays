"""End-to-end smoke test — hits the real Google Hotels endpoint.

Skipped by default (marked ``live``) to keep unit runs network-free. Run with::

    python3 -m pytest tests/test_hotel_live.py -v -m live
"""

from __future__ import annotations

import json
import re
from datetime import date
from urllib.request import Request, urlopen

import pytest

from stays.models.google_hotels import (
    Currency,
    DateRange,
    GuestInfo,
    HotelSearchFilters,
    Location,
)

ENDPOINT = "https://www.google.com/_/TravelFrontendUi/data/batchexecute"
HEADERS = {"content-type": "application/x-www-form-urlencoded;charset=UTF-8"}


def _post(body: str) -> str:
    req = Request(ENDPOINT, data=body.encode(), method="POST", headers=HEADERS)
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def _extract_inner(raw: str) -> dict:
    m = re.search(r'"wrb\.fr","AtySUc","((?:\\.|[^"\\])*)"', raw)
    assert m, f"no AtySUc frame in response head: {raw[:200]!r}"
    payload_str = m.group(1).encode().decode("unicode_escape")
    assert payload_str, "AtySUc payload is empty (malformed request)"
    return json.loads(payload_str)


def _compact(obj) -> str:
    """Match Google's own compact JSON formatting so date/guest echoes are findable."""
    return json.dumps(obj, separators=(",", ":"))


@pytest.mark.live
def test_live_minimum_request_returns_nyc_hotels():
    f = HotelSearchFilters(location=Location(query="new york city hotels"))
    inner = _extract_inner(_post(f.to_request_body()))

    blob = json.dumps(inner)
    resolved_kgmid_slot = inner[1][5]
    # Google resolves "new york city" to '/m/02_286'
    assert resolved_kgmid_slot[0] == "/m/02_286", (
        f"expected resolved KGMID '/m/02_286' for NYC, got {resolved_kgmid_slot}"
    )
    assert any(
        name in blob
        for name in (
            "Times Square",
            "Manhattan",
            "New York Marriott Marquis",
        )
    ), "response missing NYC-specific hotels"


@pytest.mark.live
def test_live_disambiguates_paris_france_vs_paris_texas():
    france = _extract_inner(
        _post(HotelSearchFilters(location=Location(query="paris, france hotels")).to_request_body())
    )
    texas = _extract_inner(_post(HotelSearchFilters(location=Location(query="paris, texas hotels")).to_request_body()))
    assert france[1][5][0] == "/m/05qtj", f"Paris,FR should resolve to /m/05qtj, got {france[1][5]}"
    assert texas[1][5][0] == "/m/0gfgglz", f"Paris,TX should resolve to /m/0gfgglz, got {texas[1][5]}"
    # Sanity on content
    assert "Motel 6 Paris" in _compact(texas) or "Paris, TX" in _compact(texas)


@pytest.mark.live
def test_live_full_trip_respects_dates_guests_currency():
    f = HotelSearchFilters(
        location=Location(query="london hotels"),
        dates=DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4)),
        guests=GuestInfo(adults=4),
        currency=Currency.GBP,
    )
    inner = _extract_inner(_post(f.to_request_body()))
    blob = _compact(inner)
    # Currency propagated
    assert '"GBP"' in blob, "GBP should appear in the response"
    # Dates echoed back
    assert "[2026,9,1]" in blob, "check-in date should be echoed"
    assert "[2026,9,4]" in blob, "check-out date should be echoed"
    # London-specific sample
    assert any(
        name in blob
        for name in (
            "London",
            "Kensington",
            "Westminster",
            "Conrad London",
        )
    )


@pytest.mark.live
def test_live_pin_scopes_results_when_query_is_neutral():
    """Pin behavior: when the query text does NOT name a specific city, the
    pinned FID/KGMID scopes results. (If the query names a different city,
    text wins — Google's resolver prefers explicit text over the pin.)
    """
    f = HotelSearchFilters(
        location=Location(
            query="hotels in this area",  # neutral text
            fid="0x808f9e60efa95545:0xfd8efcf42dcc1ba7",
            display_name="San Mateo",
        ),
    )
    inner = _extract_inner(_post(f.to_request_body()))
    blob = _compact(inner)
    assert inner[1][5][6] == "San Mateo", f"response should resolve to San Mateo, got {inner[1][5]}"
    assert any(t in blob for t in ("San Mateo", "Burlingame", "Foster City")), (
        "pinned San Mateo should scope results when query is neutral"
    )


@pytest.mark.live
def test_live_pin_wins_over_mismatched_text_query():
    """When an explicit pin is supplied, Google's server resolves the
    request to that pin's KGMID even if the text query points elsewhere.

    This changed when we added the outer [2] request-meta element
    required for filter application (brands/hotel_class/amenities all
    silently drop without it). With that meta present, Google honours
    the pin as authoritative — so callers who don't want a pin to
    override their text query should omit the pin rather than pass a
    stale one.
    """
    f = HotelSearchFilters(
        location=Location(
            query="new york hotels",
            fid="0x808f9e60efa95545:0xfd8efcf42dcc1ba7",  # San Mateo
            display_name="San Mateo",
        ),
    )
    inner = _extract_inner(_post(f.to_request_body()))
    # Server resolves to the pin's KGMID (San Mateo), not the text's NYC.
    assert inner[1][5][0] == "/m/0r5y9", f"pin should win: expected San Mateo KGMID, got {inner[1][5]}"
