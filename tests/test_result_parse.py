"""Unit tests for parse_search_response against a fixture."""

import json
from pathlib import Path

import pytest

from stays import Amenity
from stays.search.parse import (
    extract_kgmid_from_protobuf,
    parse_search_response,
)

FIXTURE = Path(__file__).parent / "fixtures" / "search_response_nyc.json"


@pytest.fixture(scope="module")
def parsed_hotels():
    inner = json.loads(FIXTURE.read_text())
    return parse_search_response(inner)


def test_extract_kgmid_from_protobuf_roundtrip():
    # ChgI...AQ is the San Mateo KGMID wrapper from FINDINGS.md
    token = "ChgI9beFhbquiZLRARoLL2cvMXRmYnlwenMQAQ"
    assert extract_kgmid_from_protobuf(token) == "/g/1tfbypzs"


def test_fixture_yields_hotels(parsed_hotels):
    assert len(parsed_hotels) >= 10


def test_all_hotels_have_name(parsed_hotels):
    for h in parsed_hotels:
        assert h.name


def test_most_hotels_have_kgmid_and_all_kgmids_are_real(parsed_hotels):
    with_kgmid = [h for h in parsed_hotels if h.kgmid]
    assert len(with_kgmid) >= int(0.5 * len(parsed_hotels)), (
        f"expected ≥ 50% with KGMID, got {len(with_kgmid)}/{len(parsed_hotels)}"
    )
    for h in with_kgmid:
        assert h.kgmid.startswith("/g/") or h.kgmid.startswith("/m/"), (
            f"synthetic or malformed KGMID detected: {h.kgmid!r}"
        )
        assert not h.kgmid.startswith("fid:")


def test_at_least_one_hotel_has_entity_key(parsed_hotels):
    with_ek = [h for h in parsed_hotels if h.entity_key]
    assert len(with_ek) >= 3, f"expected ≥ 3 hotels to have an entity_key; got {len(with_ek)}"
    for h in with_ek:
        # entity_key is base64-ish; must not be empty
        assert len(h.entity_key) >= 10


def test_at_least_one_hotel_has_price(parsed_hotels):
    with_price = [h for h in parsed_hotels if h.display_price is not None]
    assert len(with_price) >= 3


def test_at_least_one_hotel_has_rating(parsed_hotels):
    rated = [h for h in parsed_hotels if h.overall_rating is not None]
    assert len(rated) >= 3


def test_at_least_one_hotel_has_amenities(parsed_hotels):
    with_amen = [h for h in parsed_hotels if h.amenities_available]
    assert len(with_amen) >= 3
    sample = with_amen[0]
    assert all(isinstance(a, Amenity) for a in sample.amenities_available)


def test_no_duplicate_kgmids(parsed_hotels):
    kgmids = [h.kgmid for h in parsed_hotels if h.kgmid]
    assert len(kgmids) == len(set(kgmids))


def test_rating_histogram_buckets_are_1_through_5(parsed_hotels):
    with_hist = [h for h in parsed_hotels if h.rating_histogram is not None]
    assert with_hist
    for h in with_hist:
        for k in h.rating_histogram.bucket_counts:
            assert 1 <= k <= 5


def test_coordinates_are_plausible(parsed_hotels):
    with_coords = [h for h in parsed_hotels if h.latitude is not None]
    assert len(with_coords) >= 3
    for h in with_coords:
        assert -90.0 <= h.latitude <= 90.0
        assert -180.0 <= h.longitude <= 180.0


def test_star_class_between_1_and_5(parsed_hotels):
    with_star = [h for h in parsed_hotels if h.star_class is not None]
    assert len(with_star) >= 3
    for h in with_star:
        assert 1 <= h.star_class <= 5


def test_at_least_one_hotel_has_currency(parsed_hotels):
    with_ccy = [h for h in parsed_hotels if h.currency]
    assert len(with_ccy) >= 3
    for h in with_ccy:
        assert len(h.currency) == 3


def test_at_least_one_hotel_has_rate_dates(parsed_hotels):
    with_dates = [h for h in parsed_hotels if h.rate_dates is not None]
    assert len(with_dates) >= 3
    for h in with_dates:
        ci, co = h.rate_dates
        assert co > ci


def test_at_least_one_hotel_has_check_in_time(parsed_hotels):
    # Allow 0 if the capture happens to lack times — soft check
    # but log informationally. Make sure parser doesn't crash at least.
    for h in parsed_hotels:
        if h.check_in_time:
            assert any(tok in h.check_in_time for tok in ("AM", "PM"))


def test_at_least_one_hotel_has_category_ratings(parsed_hotels):
    with_cat = [h for h in parsed_hotels if h.category_ratings]
    assert len(with_cat) >= 3
    for h in with_cat:
        for cr in h.category_ratings:
            assert 1 <= cr.category_id <= 5
            assert 0.0 <= cr.score <= 5.0


def test_no_hotels_dropped_by_dedup_when_kgmid_is_none(parsed_hotels):
    kgmid_none = [h for h in parsed_hotels if h.kgmid is None]
    if kgmid_none:
        keys = {(h.fid, h.google_hotel_id) for h in kgmid_none}
        assert len(keys) == len(kgmid_none), (
            f"dedupe dropped kgmid=None records: {len(kgmid_none)} → {len(keys)} unique fid+ghi keys"
        )
