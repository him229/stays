"""Hotel detail-page models: rooms, rate plans, reviews.

Populated by SearchHotels.get_details() which hits AtySUc with an
entity_key in request slot [2][5]. The response carries a richer version
of the same 48-slot hotel entry that the search-list response uses.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, PositiveInt

from stays.models.google_hotels.policy import CancellationPolicy
from stays.models.google_hotels.result import HotelResult


class RatePlan(BaseModel):
    """One bookable offer for a RoomType — specific provider + price."""

    provider: str = Field(..., description='e.g. "Booking.com", "Hotels.com", "Expedia", "Direct (Marriott)"')
    price: int
    currency: str
    cancellation: CancellationPolicy = Field(default_factory=CancellationPolicy)
    breakfast_included: bool = False
    includes_taxes_and_fees: bool = False
    deeplink_url: str | None = None


class RoomType(BaseModel):
    """One bookable room configuration at a hotel."""

    name: str
    description: str | None = None
    bed_config: str | None = Field(None, description='e.g. "1 King Bed", "2 Queen Beds"')
    max_occupancy: PositiveInt | None = None
    rates: list[RatePlan] = Field(
        default_factory=list,
        description="Rate plans for this room, sorted cheapest first.",
    )


class Review(BaseModel):
    """One user review surfaced in the detail response."""

    author_name: str | None = None
    rating: int = Field(..., ge=1, le=5)
    body: str
    review_date: date | None = None
    source: str | None = Field(None, description='e.g. "Google", "Booking.com"')


class HotelDetail(HotelResult):
    """Full per-property record returned by SearchHotels.get_details().

    Extends HotelResult with fields only the detail response exposes
    (description, street address, phone, rooms + rate plans, amenity
    details, nearby attractions, sample reviews).
    """

    description: str | None = None
    address: str | None = None
    phone: str | None = None

    rooms: list[RoomType] = Field(default_factory=list)

    amenity_details: list[str] = Field(
        default_factory=list,
        description="Human-readable amenity labels — supplements amenities_available bits.",
    )
    nearby_attractions: list[str] = Field(default_factory=list)
    recent_reviews: list[Review] = Field(
        default_factory=list,
        description="Small sample (target: top 3) of recent reviews.",
    )
