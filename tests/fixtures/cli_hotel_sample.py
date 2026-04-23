"""Factories for tiny fake HotelResult / HotelDetail used by CLI tests.

These avoid loading the real fixture JSON so CLI tests stay fast.
"""

from __future__ import annotations

from datetime import date

from stays.models.google_hotels.base import Amenity, Currency
from stays.models.google_hotels.detail import HotelDetail, RatePlan, RoomType
from stays.models.google_hotels.policy import CancellationPolicy, CancellationPolicyKind
from stays.models.google_hotels.result import HotelResult


def make_result(
    *,
    name: str = "Tokyo Central Hotel",
    entity_key: str = "CgoI_TEST_KEY_0001",
    display_price: int = 180,
    currency: Currency = Currency.USD,
    star_class: int = 4,
    overall_rating: float = 4.3,
    review_count: int = 1248,
) -> HotelResult:
    return HotelResult(
        name=name,
        kgmid="/g/1q2w3e4r5",
        fid="0x123:0x456",
        google_hotel_id="",
        entity_key=entity_key,
        latitude=35.6812,
        longitude=139.7671,
        display_price=display_price,
        currency=currency.value,
        rate_dates=(date(2026, 7, 22), date(2026, 7, 26)),
        star_class=star_class,
        star_class_label=f"{star_class}-star hotel",
        overall_rating=overall_rating,
        review_count=review_count,
        rating_histogram=None,
        category_ratings=[],
        check_in_time="15:00",
        check_out_time="11:00",
        amenities_available={Amenity.WIFI, Amenity.POOL},
        nearby=[],
        image_urls=[],
    )


def make_detail(*, result: HotelResult | None = None) -> HotelDetail:
    base = result or make_result()
    rate = RatePlan(
        provider="Booking.com",
        price=185,
        currency="USD",
        cancellation=CancellationPolicy(
            kind=CancellationPolicyKind.FREE_UNTIL_DATE,
            free_until="2026-07-20",
            description="Free cancellation until Jul 20",
        ),
        breakfast_included=True,
        includes_taxes_and_fees=False,
        deeplink_url="https://example.com/room",
    )
    room = RoomType(
        name="Deluxe Double",
        description="Non-smoking, city view",
        bed_config="1 queen bed",
        max_occupancy=2,
        rates=[rate],
    )
    return HotelDetail(
        **base.model_dump(),
        description="Sample description",
        address="1-1-1 Chiyoda, Tokyo",
        phone="+81-3-0000-0000",
        rooms=[room],
        amenity_details=[],
        nearby_attractions=[],
        recent_reviews=[],
    )
