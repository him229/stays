"""Live MCP filter tests — hit real Google through the MCP tool
dispatch entries. 15 parametrized cases covering the major filter set.

Each case is marked `@pytest.mark.live` and `@pytest.mark.flaky(reruns=3)`
so transient Google failures auto-retry but assertion bugs fail fast.
"""

from datetime import date, timedelta

import pytest

from stays.mcp.server import (
    GetHotelDetailsParams,
    SearchHotelsParams,
    SearchHotelsWithDetailsParams,
    _execute_get_hotel_details_from_params,
    _execute_search_hotels_from_params,
    _execute_search_hotels_with_details_from_params,
)


def _iso(days_ahead: int) -> str:
    return (date.today() + timedelta(days=days_ahead)).isoformat()


pytestmark = [
    pytest.mark.live,
    pytest.mark.flaky(
        reruns=3,
        reruns_delay=5,
        only_rerun=["TransientBatchExecuteError"],
    ),
]


@pytest.mark.parametrize(
    "params, assertions",
    [
        # 1. query only
        (SearchHotelsParams(query="new york hotels"), lambda r: r["success"] and r["count"] >= 1),
        # 2. sort_by=LOWEST_PRICE
        (
            SearchHotelsParams(query="new york hotels", sort_by="LOWEST_PRICE"),
            lambda r: r["success"] and r["count"] >= 1,
        ),
        # 3. sort_by=HIGHEST_RATING
        (
            SearchHotelsParams(query="new york hotels", sort_by="HIGHEST_RATING"),
            lambda r: r["success"] and r["count"] >= 1,
        ),
        # 4. sort_by=MOST_REVIEWED
        (
            SearchHotelsParams(query="new york hotels", sort_by="MOST_REVIEWED"),
            lambda r: r["success"] and r["count"] >= 1,
        ),
        # 5. price range
        (
            SearchHotelsParams(query="new york hotels", price_min=100, price_max=300),
            lambda r: r["success"],
        ),
        # 6. hotel_class=[4,5]
        (
            SearchHotelsParams(query="chicago hotels", hotel_class=[4, 5]),
            lambda r: r["success"] and r["count"] >= 1,
        ),
        # 7. amenities=[WIFI, POOL]
        (
            SearchHotelsParams(query="las vegas hotels", amenities=["WIFI", "POOL"]),
            lambda r: r["success"],
        ),
        # 8. amenities=[GYM, SPA, BAR]
        (
            SearchHotelsParams(query="miami hotels", amenities=["GYM", "SPA", "BAR"]),
            lambda r: r["success"],
        ),
        # 9. brands=[MARRIOTT]
        (
            SearchHotelsParams(query="chicago hotels", brands=["MARRIOTT"]),
            lambda r: r["success"] and r["count"] >= 1,
        ),
        # 10. brands=[HILTON, IHG]
        (
            SearchHotelsParams(query="new york hotels", brands=["HILTON", "IHG"]),
            lambda r: r["success"],
        ),
        # 11. free_cancellation
        (SearchHotelsParams(query="denver hotels", free_cancellation=True), lambda r: r["success"]),
        # 12. special_offers
        (SearchHotelsParams(query="las vegas hotels", special_offers=True), lambda r: r["success"]),
        # 13. min_guest_rating=4.0
        (
            SearchHotelsParams(query="san francisco hotels", min_guest_rating=4.0),
            lambda r: r["success"],
        ),
    ],
    ids=[
        "query_only",
        "sort_lowest_price",
        "sort_highest_rating",
        "sort_most_reviewed",
        "price_range",
        "hotel_class_45",
        "amenities_wifi_pool",
        "amenities_gym_spa_bar",
        "brand_marriott",
        "brands_hilton_ihg",
        "free_cancellation",
        "special_offers",
        "min_rating_40",
    ],
)
def test_live_search_hotels(params, assertions):
    resp = _execute_search_hotels_from_params(params)
    assert assertions(resp), f"assertion failed for resp={resp}"


def test_live_get_hotel_details_after_search():
    """Run a live search first, pluck the first entity_key, fetch detail."""
    sp = SearchHotelsParams(
        query="new york hotels",
        check_in=_iso(30),
        check_out=_iso(33),
    )
    search = _execute_search_hotels_from_params(sp)
    assert search["success"]
    assert search["count"] >= 1
    ek = search["hotels"][0]["entity_key"]
    assert ek, f"no entity_key captured from: {search['hotels'][0]}"
    dp = GetHotelDetailsParams(
        entity_key=ek,
        check_in=_iso(30),
        check_out=_iso(33),
    )
    detail = _execute_get_hotel_details_from_params(dp)
    assert detail["success"]
    assert detail["hotel"]["name"]


def test_live_search_with_details_top3():
    params = SearchHotelsWithDetailsParams(
        query="seattle hotels",
        check_in=_iso(21),
        check_out=_iso(23),
        max_hotels=3,
    )
    resp = _execute_search_hotels_with_details_from_params(params)
    assert resp["success"]
    assert resp["count"] == 3
