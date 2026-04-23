"""Unit tests for HotelSearchFilters serialization.

These verify that the nested-list output of ``.format()`` matches the
shape we observed from the live Google Hotels UI (``docs/reverse-engineering/slot-map.md``).
They exercise validation rules (bad dates, empty query, malformed KGMID/FID)
and the currency/guest/date/filter propagation.

Run from the repo root with::

    python3 -m pytest tests/test_hotel_serializer.py -v
"""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import unquote

import pytest

from stays.models.google_hotels import (
    Amenity,
    Brand,
    Currency,
    DateRange,
    GuestInfo,
    HotelSearchFilters,
    Location,
    MinGuestRating,
    PropertyType,
    SortBy,
)
from stays.models.google_hotels.hotels import RPC_ID

# ---------------------------------------------------------------------------
# Minimum shape
# ---------------------------------------------------------------------------


def test_absolute_minimum_payload():
    """With just a query, format() yields [query, SearchParams] with the
    UI-matching 4-element filters record at [1][4]."""
    f = HotelSearchFilters(location=Location(query="paris, france hotels"))
    out = f.format()
    assert out[0] == "paris, france hotels"
    params = out[1]
    # [1][0] is property type (defaults to HOTELS=1)
    assert params[0] == 1
    assert params[1] is None
    assert params[2] is None, "No location pin and no dates → loc_dates_block is None"
    assert params[3] is None
    # [1][4] is the 4-element filters record
    filters_record = params[4]
    assert len(filters_record) == 4
    # [1][4][0] = filter-details: [amenities, None, None, None, sort, None, currency, brands]
    assert filters_record[0] == [None, None, None, None, None, None, "USD", None]
    assert filters_record[1] is None
    assert filters_record[2] == []
    assert filters_record[3] == [None, None, 1]


def test_query_preserved_verbatim():
    f = HotelSearchFilters(location=Location(query="SAN MATEO HOTELS"))
    assert f.format()[0] == "SAN MATEO HOTELS"


def test_currency_default_is_usd_and_overrides():
    f = HotelSearchFilters(location=Location(query="x"), currency=Currency.EUR)
    assert f.format()[1][4][0][6] == "EUR"

    f2 = HotelSearchFilters(location=Location(query="x"))
    assert f2.format()[1][4][0][6] == "USD"


# ---------------------------------------------------------------------------
# Dates + guests
# ---------------------------------------------------------------------------


def test_dates_and_guests_slot_shape():
    f = HotelSearchFilters(
        location=Location(query="tokyo hotels"),
        dates=DateRange(check_in=date(2026, 11, 20), check_out=date(2026, 11, 25)),
        guests=GuestInfo(adults=3, children=1, child_ages=[7]),
    )
    params = f.format()[1]
    # property type default = 1
    assert params[0] == 1
    # loc_dates_block = [loc_slot, dates_slot]
    loc_slot, dates_slot = params[2]
    assert loc_slot is None, "no pin → loc slot stays None"
    # dates_slot = [None, [ci, co, nights], None, None, None, [None, child_count]]
    assert dates_slot[0] is None
    assert dates_slot[1] == [[2026, 11, 20], [2026, 11, 25], 5], "5 nights = 11/25 - 11/20"
    assert dates_slot[2] is None
    assert dates_slot[3] is None
    assert dates_slot[4] is None
    assert dates_slot[5] == [None, 1], "run-2 shape: [null, child_count]; adults encoded at [1][1]"


def test_dates_accept_string_shortcut():
    f = HotelSearchFilters(
        location=Location(query="london"),
        dates=DateRange(check_in="2026-09-01", check_out="2026-09-04"),
    )
    dates_slot = f.format()[1][2][1]
    assert dates_slot[1][0] == [2026, 9, 1]
    assert dates_slot[1][1] == [2026, 9, 4]


def test_dates_validator_rejects_non_positive_stay():
    with pytest.raises(ValueError, match="check_out must be after check_in"):
        DateRange(check_in=date(2026, 9, 4), check_out=date(2026, 9, 4))
    with pytest.raises(ValueError, match="check_out must be after check_in"):
        DateRange(check_in=date(2026, 9, 4), check_out=date(2026, 9, 1))


def test_dates_nights_property():
    assert DateRange(check_in="2026-09-01", check_out="2026-09-04").nights == 3


def test_guests_defaults():
    f = HotelSearchFilters(location=Location(query="x"), dates=DateRange(check_in="2026-09-01", check_out="2026-09-04"))
    dates_slot = f.format()[1][2][1]
    # Run-2 shape: [None, child_count]. Default GuestInfo is 2 adults / 0 children
    # → [None, 0]. Adults are conveyed via the [1][1] extras block (null when default).
    assert dates_slot[5] == [None, 0]


# ---------------------------------------------------------------------------
# Location pinning + validators
# ---------------------------------------------------------------------------


def test_pinned_location_emits_location_slot():
    loc = Location(
        query="paris, france hotels",
        kgmid="/m/05qtj",
        fid="0x47e66e1f06e2b70f:0x40b82c3688c9460",
        display_name="Paris",
    )
    f = HotelSearchFilters(location=loc)
    params = f.format()[1]
    loc_block = params[2]
    assert loc_block is not None, "pin means loc_dates_block exists even without dates"
    loc_slot, dates_slot = loc_block
    assert dates_slot is None
    # loc_slot = [None, [[kgmid, None, None, None, None, fid, name]], []]  (3-elem in real UI)
    assert len(loc_slot) == 3
    assert loc_slot[0] is None
    inner = loc_slot[1][0]
    assert inner[0] == "/m/05qtj"
    assert inner[1:5] == [None, None, None, None]
    assert inner[5] == "0x47e66e1f06e2b70f:0x40b82c3688c9460"
    assert inner[6] == "Paris"
    assert loc_slot[2] == []


def test_pinned_location_with_only_kgmid():
    f = HotelSearchFilters(location=Location(query="paris", kgmid="/m/05qtj"))
    loc_slot = f.format()[1][2][0]
    assert loc_slot[1][0] == ["/m/05qtj", None, None, None, None, None, None]
    assert loc_slot[2] == []


def test_empty_query_rejected():
    with pytest.raises(ValueError, match="must be non-empty"):
        Location(query="   ")


def test_malformed_kgmid_rejected():
    with pytest.raises(ValueError, match="must start with '/m/' or '/g/'"):
        Location(query="x", kgmid="m/05qtj")


def test_malformed_fid_rejected():
    with pytest.raises(ValueError, match="must look like"):
        Location(query="x", fid="deadbeef")


def test_has_pin():
    assert Location(query="x").has_pin is False
    assert Location(query="x", kgmid="/m/05qtj").has_pin is True
    assert Location(query="x", fid="0x1:0x2").has_pin is True
    assert Location(query="x", display_name="Nowhere").has_pin is True


# ---------------------------------------------------------------------------
# encode() / envelope
# ---------------------------------------------------------------------------


def test_encode_returns_urlencoded_batchexecute_envelope():
    f = HotelSearchFilters(location=Location(query="x"))
    encoded = f.encode()
    # URL-encoded, so un-quoting should give valid JSON
    decoded = unquote(encoded)
    outer = json.loads(decoded)
    assert outer[0][0][0] == RPC_ID
    inner = json.loads(outer[0][0][1])
    assert inner == f.format()
    assert outer[0][0][2] is None
    assert outer[0][0][3] == "1"


def test_to_request_body_has_freq_prefix():
    f = HotelSearchFilters(location=Location(query="x"))
    body = f.to_request_body()
    assert body.startswith("f.req=")


# ---------------------------------------------------------------------------
# Disambiguation smoke test — structure only, no network
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "paris, france hotels",
        "paris, texas hotels",
        "springfield, missouri hotels",
        "springfield, oregon hotels",
        "新宿 ホテル",
    ],
)
def test_disambiguation_strings_propagate(query):
    f = HotelSearchFilters(location=Location(query=query))
    assert f.format()[0] == query
    # Must round-trip through encoding without losing the string.
    decoded = unquote(f.encode())
    outer = json.loads(decoded)
    inner = json.loads(outer[0][0][1])
    assert inner[0] == query


# ---------------------------------------------------------------------------
# Property type
# ---------------------------------------------------------------------------


def test_property_type_default_is_hotels():
    f = HotelSearchFilters(location=Location(query="x"))
    assert f.format()[1][0] == 1


def test_property_type_vacation_rentals_emits_2():
    f = HotelSearchFilters(
        location=Location(query="x"),
        property_type=PropertyType.VACATION_RENTALS,
    )
    assert f.format()[1][0] == 2


# ---------------------------------------------------------------------------
# Sort mode
# ---------------------------------------------------------------------------


def test_sort_lowest_price_emits_3_at_filter_slot():
    f = HotelSearchFilters(location=Location(query="x"), sort_by=SortBy.LOWEST_PRICE)
    assert f.format()[1][4][0][4] == 3


def test_sort_highest_rating_emits_8_at_filter_slot():
    f = HotelSearchFilters(location=Location(query="x"), sort_by=SortBy.HIGHEST_RATING)
    assert f.format()[1][4][0][4] == 8


def test_sort_default_is_none():
    f = HotelSearchFilters(location=Location(query="x"))
    assert f.format()[1][4][0][4] is None


# ---------------------------------------------------------------------------
# Amenities
# ---------------------------------------------------------------------------


def test_amenities_pool_emits_list_with_6():
    f = HotelSearchFilters(location=Location(query="x"), amenities=[Amenity.POOL])
    assert f.format()[1][4][0][0] == [6]


def test_amenities_empty_emits_null():
    f = HotelSearchFilters(location=Location(query="x"))
    assert f.format()[1][4][0][0] is None


# ---------------------------------------------------------------------------
# Brands
# ---------------------------------------------------------------------------

_HILTON_SUBS = [114, 7, 151, 81, 88, 115, 71, 95, 54, 36, 77, 295, 285, 286, 41]


def test_brands_hilton_emits_28_with_all_sub_ids():
    """Hilton must carry its 15 sub-brand IDs — empty list is a silent no-op."""
    f = HotelSearchFilters(location=Location(query="x"), brands=[Brand.HILTON])
    assert f.format()[1][4][0][7] == [[28, _HILTON_SUBS]]


def test_brands_empty_emits_null():
    f = HotelSearchFilters(location=Location(query="x"))
    assert f.format()[1][4][0][7] is None


def test_brands_multi_emits_both_with_sub_ids():
    f = HotelSearchFilters(
        location=Location(query="x"),
        brands=[Brand.HILTON, Brand.MARRIOTT],
    )
    # Marriott is ID 46 (confirmed live 2026-04-22 — IDs were swapped vs the
    # initial capture labels).
    assert f.format()[1][4][0][7] == [
        [28, _HILTON_SUBS],
        [46, Brand.MARRIOTT.sub_brand_ids],
    ]


def test_every_brand_enum_has_non_empty_sub_ids_except_four_seasons():
    """Regression guard: every brand (except Four Seasons) must carry a
    non-empty sub-brand list. Google silently ignores ``[[brand_id, []]]``
    pairs — the filter applies only when the sub-brand list is populated
    with the IDs Playwright captured for that family in run 4.
    """
    for brand in Brand:
        if brand is Brand.FOUR_SEASONS:
            assert brand.sub_brand_ids == [], f"{brand.name}: Four Seasons is the shape exception — bare [[289]]"
            continue
        assert brand.sub_brand_ids, (
            f"{brand.name}: missing sub-brand IDs. Google silently ignores the brand filter when this list is empty."
        )


def test_brand_slot_populated_prevents_silent_filter_noop():
    """Guard against the bug that shipped in production: emitting
    ``[[brand_id, []]]`` (empty sub-brand list) makes Google return
    results as if no brand filter were set. The serializer must never
    emit an empty list for any brand that has sub-brands.
    """
    for brand in Brand:
        f = HotelSearchFilters(location=Location(query="x"), brands=[brand])
        emitted = f.format()[1][4][0][7]
        if brand is Brand.FOUR_SEASONS:
            assert emitted == [[289]], f"Four Seasons must emit bare [[289]], got {emitted!r}"
        else:
            assert len(emitted) == 1
            assert emitted[0][0] == brand.value
            assert len(emitted[0]) == 2, f"{brand.name}: expected [id, subs], got {emitted!r}"
            assert len(emitted[0][1]) > 0, f"{brand.name}: sub-brand list is empty — filter will silently no-op"


def test_request_meta_outer_2_always_present():
    """Filters (brands / hotel_class / amenities / free_cancel) are
    silently dropped unless outer[2] request-meta is present. This
    guards against regressions that remove it.
    """
    # No filters — still required
    f_plain = HotelSearchFilters(location=Location(query="x"))
    payload = f_plain.format()
    assert len(payload) >= 3, "outer[2] missing — filters will silently drop"
    assert payload[2] == [1, None, None, None, None, None, 13, None, 0]

    # With filters — still the same meta shape
    f_filtered = HotelSearchFilters(
        location=Location(query="x"),
        brands=[Brand.HILTON],
        free_cancellation=True,
    )
    payload_f = f_filtered.format()
    assert len(payload_f) >= 3
    assert payload_f[2][0] == 1
    assert payload_f[2][6] == 13


# ---------------------------------------------------------------------------
# Child ages
# ---------------------------------------------------------------------------


def test_child_ages_extras_block():
    """One child aged 7 → extras block = [[[3], [3], [2, 12]], 1]."""
    f = HotelSearchFilters(
        location=Location(query="x"),
        guests=GuestInfo(adults=2, children=1, child_ages=[7]),
    )
    assert f.format()[1][1] == [[[3], [3], [2, 12]], 1]


def test_child_ages_no_children_emits_null():
    f = HotelSearchFilters(
        location=Location(query="x"),
        guests=GuestInfo(adults=2, children=0),
    )
    assert f.format()[1][1] is None


def test_child_ages_validator():
    """children=0 but child_ages=[7] is inconsistent → should raise."""
    with pytest.raises(ValueError):
        GuestInfo(adults=2, children=0, child_ages=[7])


def test_child_ages_count_mismatch_rejected():
    """children=2 with only one age entry is inconsistent → raise."""
    with pytest.raises(ValueError):
        GuestInfo(adults=2, children=2, child_ages=[7])


def test_child_ages_bounds_validation():
    """Ages must be 0-17."""
    with pytest.raises(ValueError):
        GuestInfo(adults=2, children=1, child_ages=[18])


def test_age_to_bucket_helper():
    """Ages 2-12 map to Google's broad child bucket [2, 12]."""
    assert GuestInfo.age_to_bucket(2) == [2, 12]
    assert GuestInfo.age_to_bucket(7) == [2, 12]
    assert GuestInfo.age_to_bucket(12) == [2, 12]


# ---------------------------------------------------------------------------
# Hotel class (run-2)
# ---------------------------------------------------------------------------


def test_hotel_class_emits_list_at_filter_slot_1():
    f = HotelSearchFilters(location=Location(query="x"), hotel_class=[4, 5])
    params = f.format()[1]
    assert params[4][0][1] == [4, 5]


def test_hotel_class_single_star():
    f = HotelSearchFilters(location=Location(query="x"), hotel_class=[3])
    assert f.format()[1][4][0][1] == [3]


def test_hotel_class_unsorted_input_is_sorted():
    """Run-2 captures always emit stars ascending; we normalise."""
    f = HotelSearchFilters(location=Location(query="x"), hotel_class=[5, 3, 4])
    assert f.format()[1][4][0][1] == [3, 4, 5]


def test_hotel_class_empty_emits_null():
    f = HotelSearchFilters(location=Location(query="x"))
    assert f.format()[1][4][0][1] is None


def test_hotel_class_validator_rejects_out_of_range():
    with pytest.raises(ValueError, match="hotel_class entries must be 1-5"):
        HotelSearchFilters(location=Location(query="x"), hotel_class=[6])
    with pytest.raises(ValueError, match="hotel_class entries must be 1-5"):
        HotelSearchFilters(location=Location(query="x"), hotel_class=[0])


# ---------------------------------------------------------------------------
# Price range (run-4 preset-chip dollar shape)
# ---------------------------------------------------------------------------


def test_price_range_both_emits_bracket_shape():
    """(min, max) → [[None, min], [None, max], 1] — untested live but the
    natural extension of the preset-chip single-side forms."""
    f = HotelSearchFilters(location=Location(query="x"), price_range=(100, 300))
    assert f.format()[1][4][3] == [[None, 100], [None, 300], 1]


def test_price_range_min_only_emits_min_preset_shape():
    """(min, None) → [[None, min], None, 1] — parallel structure."""
    f = HotelSearchFilters(location=Location(query="x"), price_range=(150, None))
    assert f.format()[1][4][3] == [[None, 150], None, 1]


def test_price_range_max_only_emits_dollars_preset_shape():
    """(None, max) → [None, [None, max], 1] — matches price_under_75 live
    capture shape in run 4."""
    f = HotelSearchFilters(location=Location(query="x"), price_range=(None, 500))
    assert f.format()[1][4][3] == [None, [None, 500], 1]


def test_price_range_none_default():
    """Default (no price_range) emits [None, None, 1]."""
    f = HotelSearchFilters(location=Location(query="x"))
    assert f.format()[1][4][3] == [None, None, 1]


# ---------------------------------------------------------------------------
# Min guest rating (run-2)
# ---------------------------------------------------------------------------


def test_min_guest_rating_4_5_emits_9():
    f = HotelSearchFilters(
        location=Location(query="x"),
        min_guest_rating=MinGuestRating.FOUR_FIVE_PLUS,
    )
    assert f.format()[1][4][4] == 9


def test_min_guest_rating_4_0_emits_8():
    f = HotelSearchFilters(
        location=Location(query="x"),
        min_guest_rating=MinGuestRating.FOUR_ZERO_PLUS,
    )
    assert f.format()[1][4][4] == 8


def test_min_guest_rating_none_does_not_append():
    """No rating filter → filters_record stays 4-element."""
    f = HotelSearchFilters(location=Location(query="x"))
    params = f.format()[1]
    assert len(params[4]) == 4


# ---------------------------------------------------------------------------
# Free cancellation (run-2)
# ---------------------------------------------------------------------------


def test_free_cancellation_true_emits_1():
    f = HotelSearchFilters(location=Location(query="x"), free_cancellation=True)
    assert f.format()[1][4][0][3] == 1


def test_free_cancellation_false_emits_null():
    f = HotelSearchFilters(location=Location(query="x"))
    assert f.format()[1][4][0][3] is None


# ---------------------------------------------------------------------------
# Amenity IDs (run-2)
# ---------------------------------------------------------------------------


def test_amenity_wifi_has_correct_id():
    assert Amenity.WIFI.value == 35


def test_amenities_wifi_and_pool_emits_both_ids():
    f = HotelSearchFilters(
        location=Location(query="x"),
        amenities=[Amenity.WIFI, Amenity.POOL],
    )
    assert f.format()[1][4][0][0] == [35, 6]


# ---------------------------------------------------------------------------
# Guests breakdown at [1][1] (run-2)
# ---------------------------------------------------------------------------


def test_guests_2_adults_1_child_age_7_emits_expected_block():
    f = HotelSearchFilters(
        location=Location(query="x"),
        guests=GuestInfo(adults=2, children=1, child_ages=[7]),
    )
    assert f.format()[1][1] == [[[3], [3], [2, 12]], 1]


def test_guests_3_adults_no_children_emits_expected_block():
    f = HotelSearchFilters(
        location=Location(query="x"),
        guests=GuestInfo(adults=3),
    )
    assert f.format()[1][1] == [[[3], [3], [3]], 1]


def test_guests_4_adults_2_children_5_and_10_emits_expected_block():
    f = HotelSearchFilters(
        location=Location(query="x"),
        guests=GuestInfo(adults=4, children=2, child_ages=[5, 10]),
    )
    assert f.format()[1][1] == [[[3], [3], [3], [3], [2, 12], [2, 12]], 1]


def test_guests_default_2_adults_emits_null_extras():
    """Default party (2 adults, 0 children) → extras block stays null."""
    f = HotelSearchFilters(location=Location(query="x"))
    assert f.format()[1][1] is None


def test_guests_total_slot_is_null_children_count():
    """Run-2 shape at [1][2][1][5] is [None, child_count]."""
    f = HotelSearchFilters(
        location=Location(query="x"),
        dates=DateRange(check_in="2026-04-27", check_out="2026-04-28"),
        guests=GuestInfo(adults=2, children=1, child_ages=[7]),
    )
    assert f.format()[1][2][1][5] == [None, 1]


# ---------------------------------------------------------------------------
# Integration — combined filters against a run-2 capture shape
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Run-3 findings — newly decoded slot IDs
# ---------------------------------------------------------------------------


def test_amenity_ids_match_run3():
    """Run 3 decoded six amenity IDs from the Playwright captures."""
    assert Amenity.PARKING.value == 1
    assert Amenity.POOL.value == 6
    assert Amenity.RESTAURANT.value == 8
    assert Amenity.BREAKFAST.value == 9
    assert Amenity.SPA.value == 10
    assert Amenity.WIFI.value == 35


def test_sort_most_reviewed_emits_13():
    f = HotelSearchFilters(location=Location(query="x"), sort_by=SortBy.MOST_REVIEWED)
    assert f.format()[1][4][0][4] == 13


def test_brand_hyatt_emits_37_with_sub_ids():
    f = HotelSearchFilters(location=Location(query="x"), brands=[Brand.HYATT])
    assert f.format()[1][4][0][7] == [[37, Brand.HYATT.sub_brand_ids]]
    # Hyatt = 11 sub-brands (confirmed live)
    assert len(Brand.HYATT.sub_brand_ids) == 11


def test_brand_marriott_emits_46_with_sub_ids():
    f = HotelSearchFilters(location=Location(query="x"), brands=[Brand.MARRIOTT])
    assert f.format()[1][4][0][7] == [[46, Brand.MARRIOTT.sub_brand_ids]]
    # Marriott = 23 sub-brands (confirmed live)
    assert len(Brand.MARRIOTT.sub_brand_ids) == 23


def test_eco_certified_true_emits_at_position_9():
    """Setting eco_certified grows filter_details to 10 elements, [9]=1."""
    f = HotelSearchFilters(location=Location(query="x"), eco_certified=True)
    fd = f.format()[1][4][0]
    assert len(fd) == 10
    assert fd[8] is None
    assert fd[9] == 1


def test_eco_certified_false_omits_extension():
    """Default filter_details stays at length 8 when eco_certified is off."""
    f = HotelSearchFilters(location=Location(query="x"))
    assert len(f.format()[1][4][0]) == 8


def test_eco_certified_combines_with_amenities():
    """eco_certified=True alongside amenities both land at their slots."""
    f = HotelSearchFilters(
        location=Location(query="x"),
        amenities=[Amenity.POOL],
        eco_certified=True,
    )
    fd = f.format()[1][4][0]
    assert fd[0] == [6]
    assert fd[9] == 1


def test_combined_run2_example_has_expected_slot_values():
    """Sanity check: hotel_class + amenities + free_cancel + sort + rating + price
    all coexist and land at the right slots."""
    f = HotelSearchFilters(
        location=Location(query="new york hotels", kgmid="/m/02_286", display_name="New York"),
        dates=DateRange(check_in=date(2026, 4, 27), check_out=date(2026, 4, 28)),
        guests=GuestInfo(adults=2, children=1, child_ages=[7]),
        hotel_class=[4, 5],
        amenities=[Amenity.WIFI, Amenity.POOL],
        free_cancellation=True,
        sort_by=SortBy.LOWEST_PRICE,
        min_guest_rating=MinGuestRating.FOUR_FIVE_PLUS,
        price_range=(100, 300),
        currency=Currency.USD,
    )
    params = f.format()[1]
    # Guests breakdown
    assert params[1] == [[[3], [3], [2, 12]], 1]
    # Filter details
    fd = params[4][0]
    assert fd[0] == [35, 6]
    assert fd[1] == [4, 5]
    assert fd[3] == 1
    assert fd[4] == 3
    assert fd[6] == "USD"
    # Price + guest rating — price uses run-4 preset-chip dollar shape
    assert params[4][3] == [[None, 100], [None, 300], 1]
    assert params[4][4] == 9


# ---------------------------------------------------------------------------
# Run-4 findings — new amenity IDs, brand IDs, special offers, price shape
# ---------------------------------------------------------------------------


def test_amenity_enum_has_18_values():
    """Run 4 expanded the Amenity enum from 6 IDs to 18 (confirmed live)."""
    ids = {a.value for a in Amenity}
    assert ids == {
        1,  # PARKING
        4,  # INDOOR_POOL
        5,  # OUTDOOR_POOL
        6,  # POOL
        7,  # GYM
        8,  # RESTAURANT
        9,  # BREAKFAST
        10,  # SPA
        11,  # BEACH_ACCESS
        12,  # KID_FRIENDLY
        15,  # BAR
        19,  # PET_FRIENDLY
        22,  # ROOM_SERVICE
        35,  # WIFI
        40,  # AIR_CONDITIONED
        52,  # ALL_INCLUSIVE
        53,  # WHEELCHAIR_ACCESSIBLE
        61,  # EV_CHARGER
    }
    assert len(ids) == 18


def test_amenity_gym_is_7():
    assert Amenity.GYM.value == 7


def test_amenity_pet_friendly_is_19():
    assert Amenity.PET_FRIENDLY.value == 19


def test_amenity_indoor_pool_is_4():
    assert Amenity.INDOOR_POOL.value == 4


def test_amenity_air_conditioned_is_40():
    assert Amenity.AIR_CONDITIONED.value == 40


def test_amenity_ev_charger_is_61():
    assert Amenity.EV_CHARGER.value == 61


def test_amenity_wheelchair_accessible_is_53():
    assert Amenity.WHEELCHAIR_ACCESSIBLE.value == 53


def test_brand_enum_has_9_values():
    """Run 4 expanded the Brand enum from 3 IDs to 9 (confirmed live)."""
    ids = {b.value for b in Brand}
    assert ids == {17, 18, 20, 28, 33, 37, 46, 53, 289}
    assert len(ids) == 9


def test_brand_four_seasons_id_289():
    assert Brand.FOUR_SEASONS.value == 289


def test_brand_ihg_id_17():
    assert Brand.IHG.value == 17


def test_brand_accor_id_33():
    assert Brand.ACCOR.value == 33


def test_special_offers_true_emits_at_position_5():
    """With special_offers=True and no guest rating, filters record has
    length 6, position 4 is None (placeholder), position 5 is 1. This
    exactly matches the run-4 `special_offers` capture shape."""
    f = HotelSearchFilters(location=Location(query="x"), special_offers=True)
    params = f.format()[1]
    assert len(params[4]) == 6
    assert params[4][4] is None
    assert params[4][5] == 1


def test_special_offers_false_omits_extension():
    """Default special_offers=False → filters record keeps its 4-element
    form (unless another trailing toggle is set)."""
    f = HotelSearchFilters(location=Location(query="x"))
    assert len(f.format()[1][4]) == 4


def test_special_offers_combines_with_min_guest_rating():
    """Both toggles set → position 4 holds the rating value, position 5
    holds the special_offers flag."""
    f = HotelSearchFilters(
        location=Location(query="x"),
        min_guest_rating=MinGuestRating.FOUR_FIVE_PLUS,
        special_offers=True,
    )
    params = f.format()[1]
    assert len(params[4]) == 6
    assert params[4][4] == 9
    assert params[4][5] == 1


def test_brand_four_seasons_emits_bare_single_element():
    """Four Seasons is the shape exception: run 4 captured [[289]] with
    no sub-brand list at all. The serializer drops the sub-brand slot
    entirely when ``sub_brand_ids`` is empty (FS is the only such brand)."""
    f = HotelSearchFilters(location=Location(query="x"), brands=[Brand.FOUR_SEASONS])
    assert f.format()[1][4][0][7] == [[289]]
