"""Search-list item model — everything the AtySUc response gives us for free.

Amendment history:
  * Added category_ratings, check_in_time, check_out_time, nearby,
    google_hotel_id, rate_dates, entity_key per enrichment requirements.
  * kgmid is optional (adversarial-review finding #3): no synthetic
    `fid:`-prefixed IDs. When KGMID extraction fails, kgmid is None and
    get_details() callers must supply entity_key instead.
  * entity_key is the base64-encoded protobuf from hotel-entry slot [20];
    it is Google's native identifier for the hotel-detail request.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from stays.models.google_hotels.base import Amenity


class RatingHistogram(BaseModel):
    """Per-star review count (key 1-5 -> count)."""

    bucket_counts: dict[int, int] = Field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.bucket_counts.values())


class CategoryRating(BaseModel):
    """Google's five sub-scores for a hotel (location, cleanliness, etc.).

    Known categories:
      1: location
      2: rooms
      3: service
      4: cleanliness
      5: value
    """

    category_id: int = Field(..., ge=1, le=5)
    category_label: str | None = None
    score: float = Field(..., ge=0.0, le=5.0)


class NearbyPlace(BaseModel):
    """A point-of-interest near the hotel with travel-time metadata."""

    name: str
    mode: str = Field(
        ...,
        description='"walk", "drive", "transit", "bike" — derived from Google\'s internal mode_id.',
    )
    duration_minutes: int | None = None
    distance_text: str | None = None


class HotelResult(BaseModel):
    """One hotel from a search-list response. All fields sourced from the
    ``AtySUc`` payload — no secondary fetch required.
    """

    name: str
    kgmid: str | None = Field(
        None,
        description=("Google Knowledge Graph id '/g/...'. Decoded from entry[20]. None when extraction fails."),
    )
    fid: str | None = Field(None, description="Google Maps feature id '0x...:0x...'. Not always present.")
    google_hotel_id: str | None = Field(None, description="Stable Google-internal numeric id (entry[25]).")
    entity_key: str | None = Field(
        None,
        description=(
            "Google's native hotel identifier (base64 protobuf). Read directly "
            "from hotel-entry slot [20] of the search response. Required for "
            "`SearchHotels.get_details(entity_key, dates)` — pass this value "
            "verbatim; no re-encoding."
        ),
    )

    latitude: float | None = None
    longitude: float | None = None

    display_price: int | None = Field(None, description="Cheapest rate Google surfaced for the selected date window.")
    currency: str | None = None
    rate_dates: tuple[date, date] | None = Field(
        None, description="(check_in, check_out) that display_price applies to."
    )

    star_class: int | None = Field(None, ge=1, le=5)
    star_class_label: str | None = None
    overall_rating: float | None = None
    review_count: int | None = None
    rating_histogram: RatingHistogram | None = None
    category_ratings: list[CategoryRating] = Field(default_factory=list)

    check_in_time: str | None = None
    check_out_time: str | None = None

    amenities_available: set[Amenity] = Field(default_factory=set)

    deal_pct: int | None = None

    nearby: list[NearbyPlace] = Field(default_factory=list, max_length=20)

    image_urls: list[str] = Field(default_factory=list, max_length=10)
