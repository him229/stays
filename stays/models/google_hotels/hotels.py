"""Hotel search filter model + serializer.

The ``format()`` method produces the nested list that goes into the
f.req batchexecute envelope, and ``encode()`` returns the ready-to-POST
URL-encoded string.

Slot commentary comes from:
- ``FINDINGS.md`` — original slot-by-slot probing.
- ``docs/reverse-engineering/slot-map.md`` — decoded slots from the Playwright capture run.
"""

from __future__ import annotations

import json
import urllib.parse

from pydantic import BaseModel, Field, field_validator

from stays.models.google_hotels.base import (
    Amenity,
    Brand,
    Currency,
    DateRange,
    GuestInfo,
    Location,
    MinGuestRating,
    PropertyType,
    SortBy,
)

#: The batchexecute RPC identifier for the hotel search function.
RPC_ID = "AtySUc"


class HotelSearchFilters(BaseModel):
    """Complete set of filters for a Google Hotels search.

    Example::

        HotelSearchFilters(
            location=Location(query="paris, france hotels"),
            dates=DateRange(check_in="2026-09-01", check_out="2026-09-04"),
            guests=GuestInfo(adults=2),
            currency=Currency.EUR,
            sort_by=SortBy.LOWEST_PRICE,
            amenities=[Amenity.POOL],
            brands=[Brand.HILTON],
        )

    The only required field is ``location``. Dates and guests are optional
    — leaving them unset produces Google's default "flexible dates" view.
    """

    location: Location
    dates: DateRange | None = Field(None, description="Check-in/out. Omit to get flexible-date defaults.")
    guests: GuestInfo = Field(default_factory=GuestInfo)
    currency: Currency = Currency.USD

    property_type: PropertyType = PropertyType.HOTELS
    sort_by: SortBy | None = None
    amenities: list[Amenity] = Field(default_factory=list)
    brands: list[Brand] = Field(default_factory=list)

    # Decoded run-2 slots (docs/reverse-engineering/slot-map.md):
    hotel_class: list[int] = Field(
        default_factory=list,
        description="Star-class filter at [1][4][0][1]. Each entry must be 1-5.",
    )
    price_range: tuple[int | None, int | None] | None = Field(
        None,
        description=(
            "Per-night price range in dollars via `(min, max)`. Either side "
            "can be None. Uses Google's preset-chip wire encoding (dollars "
            "sent directly), NOT the slider-drag percentile encoding."
        ),
    )
    min_guest_rating: MinGuestRating | None = Field(None, description="Minimum guest rating at [1][4][4].")
    free_cancellation: bool = Field(False, description="Free-cancellation toggle at [1][4][0][3].")
    eco_certified: bool = Field(
        False,
        description=(
            "Eco-certified chip at [1][4][0][9]. When True the filter-details "
            "array grows from 8 to 10 elements ([8]=null, [9]=1)."
        ),
    )
    special_offers: bool = Field(
        False,
        description=(
            "Special offers chip at [1][4][5]. When True the filters record "
            "extends to length 6, with position 5 set to 1. Parallels the "
            "guest_rating slot at position 4 — both are trailing toggles."
        ),
    )
    entity_key: str | None = Field(
        None,
        description=(
            "Optional hotel identifier (base64 protobuf). When set, the "
            "request is routed into AtySUc's 'hotel detail' mode and the "
            "response returns a single enriched hotel entry with rooms, "
            "rate plans, cancellation policies, full amenity list, "
            "description, address, phone, and recent reviews. Normal "
            "search leaves this None. Obtained from a prior search's "
            "HotelResult.entity_key field."
        ),
    )

    # TODO — filters still unwired (see docs/reverse-engineering/slot-map.md "Still unknown"):
    #   neighborhood pins
    #   map bounding box

    @field_validator("hotel_class")
    @classmethod
    def _valid_hotel_class(cls, v: list[int]) -> list[int]:
        for star in v:
            if star < 1 or star > 5:
                raise ValueError(f"hotel_class entries must be 1-5, got {star!r}")
        return v

    def format(self) -> list:
        """Return the RPC inner payload list (the thing JSON-stringified into the envelope).

        Matches the shape observed from the live Google Hotels UI
        (docs/reverse-engineering/slot-map.md). Structure:

            [query, SearchParams]

        where SearchParams is:

            [property_type, guests_extras, loc_dates, None, filters_record]

        and filters_record is:

            [filter_details, None, [], price_slot, (optional) guest_rating]
        """
        # --- [1][2][0] Location slot (3-elem, per docs/reverse-engineering/slot-map.md) ----
        # Shape: [None, [[kgmid, None, None, None, None, fid, display_name]], []]
        # The trailing empty list is a reserved slot observed in every
        # captured UI request; we mirror it for compatibility.
        loc_slot = None
        if self.location.has_pin:
            loc_slot = [
                None,
                [
                    [
                        self.location.kgmid,
                        None,
                        None,
                        None,
                        None,
                        self.location.fid,
                        self.location.display_name,
                    ]
                ],
                [],
            ]

        # --- [1][2][1] Dates + Guests slot ---------------------------------
        # Shape: [None, [[Y,M,D],[Y,M,D],nights], None, None, None, [None, child_count]]
        # Per run-2 captures, the trailing guests slot is [None, child_count] —
        # NOT [total_occupants]. Adults are now conveyed via [1][1].
        dates_slot = None
        if self.dates is not None:
            ci = [self.dates.check_in.year, self.dates.check_in.month, self.dates.check_in.day]
            co = [self.dates.check_out.year, self.dates.check_out.month, self.dates.check_out.day]
            dates_slot = [
                None,
                [ci, co, self.dates.nights],
                None,
                None,
                None,
                [None, len(self.guests.child_ages)],
            ]

        loc_dates_block = None
        if loc_slot is not None or dates_slot is not None:
            loc_dates_block = [loc_slot, dates_slot]

        # --- [1][1] Guests-extras block ------------------------------------
        # null when the default party (2 adults, 0 children) is used.
        # Otherwise emit one [3] per adult AND one [lo, hi] per child age:
        #   [[<party>], 1]  where <party> = [[3]]*adults + [age_bucket]*per child
        extras_block = None
        if self.guests.adults != 2 or self.guests.child_ages:
            party = [[3]] * self.guests.adults + [GuestInfo.age_to_bucket(a) for a in self.guests.child_ages]
            extras_block = [party, 1]

        # --- [1][4] Filters record (4- or 5-elem, per docs/reverse-engineering/slot-map.md) -
        # [0] filter-details:
        #     [amenities, hotel_class, None, free_cancel, sort_int, None, currency, brands]
        #     - amenities at [0]: list of int IDs, or None if empty
        #     - hotel_class at [1]: sorted list of 1-5 stars, or None if empty
        #     - [2]: reserved — stays None in every capture
        #     - free_cancel at [3]: 1 if refundable-only toggled, else None
        #     - sort_int at [4]: the SortBy.value or None
        #     - [5]: reserved — stays None in every capture
        #     - currency at [6]: always present
        #     - brands at [7]: list of [id, []] pairs, or None if empty
        # [1] None
        # [2] [] — seems to grow when additional filters are added
        # [3] price_slot = [[min_or_null, max_or_null], None, 1] — defaults to
        #     [None, None, 1] when no price filter set
        # [4] (optional) guest_rating int — only appended when min_guest_rating is set
        amenities_slot = [a.value for a in self.amenities] if self.amenities else None
        hotel_class_slot = sorted(self.hotel_class) if self.hotel_class else None
        free_cancel_slot = 1 if self.free_cancellation else None
        # Emit the int value when the SortBy has a confirmed wire ID
        # (positive ints). RELEVANCE uses a negative sentinel and stays null —
        # the absence of a sort value IS relevance (confirmed in run 3).
        sort_slot = None
        if self.sort_by is not None and self.sort_by.value > 0:
            sort_slot = self.sort_by.value
        # Brands emit as [brand_id, [sub_brand_ids...]] pairs. The sub-brand
        # list MUST be populated — an empty list is silently treated as
        # "no-op" by Google and the filter doesn't apply (regression found
        # live against Xi'an, where [[28, []]] returned non-Hilton results).
        # Four Seasons is the shape exception: run 4 captured [[289]] with
        # no sub-brand element at all, so we emit the bare one-element form
        # whenever ``sub_brand_ids`` is empty.
        brands_slot = None
        if self.brands:
            brands_slot = []
            for b in self.brands:
                subs = b.sub_brand_ids
                brands_slot.append([b.value, subs] if subs else [b.value])

        filter_details = [
            amenities_slot,
            hotel_class_slot,
            None,
            free_cancel_slot,
            sort_slot,
            None,
            self.currency.value,
            brands_slot,
        ]
        # Eco-certified extends filter_details to length 10 at positions 8/9.
        # [8] is reserved (null in every eco-certified capture) and [9] is
        # the eco flag itself. When eco_certified is False we keep the
        # 8-element form — the UI omits the trailing nulls.
        if self.eco_certified:
            filter_details += [None, 1]

        # Price range uses Google's preset-chip wire shape — dollars sent
        # directly. Run 4 decoded two distinct encodings: the preset-chip
        # form (dollars) vs. the slider-drag form (percentile indices).
        # We emit the preset-chip shape, which means arbitrary dollar
        # values are accepted without a pre-check lookup.
        #   - max-only: [None, [None, max_dollars], 1]     (captured live)
        #   - min-only: [[None, min_dollars], None, 1]     (untested — TODO)
        #   - both:     [[None, min_dollars], [None, max_dollars], 1]  (untested)
        if self.price_range is not None:
            lo, hi = self.price_range
            lo_slot = [None, lo] if lo is not None else None
            hi_slot = [None, hi] if hi is not None else None
            price_slot = [lo_slot, hi_slot, 1]
        else:
            price_slot = [None, None, 1]

        filters_record = [
            filter_details,
            None,
            [],
            price_slot,
        ]
        # Guest rating lives at position 4, special offers at position 5.
        # Both are trailing toggles (docs/reverse-engineering/slot-map.md run 4). When
        # special_offers is set without a rating filter, we still need a
        # placeholder at position 4 so position 5 lands correctly.
        if self.min_guest_rating is not None:
            filters_record.append(self.min_guest_rating.value)
        elif self.special_offers:
            filters_record.append(None)

        if self.special_offers:
            filters_record.append(1)

        # --- [1] SearchParams ---------------------------------------------
        search_params = [
            self.property_type.value,
            extras_block,
            loc_dates_block,
            None,
            filters_record,
        ]

        # --- [2] Request meta -----------------------------------------
        # Captured in every run 4 filter request as ``[1, null, ..., 13, null, 0]``.
        # Google silently IGNORES filters (brands, hotel_class, amenities,
        # free_cancellation) when this element is missing — the request
        # still returns hotels but the filter application is dropped.
        # Detail queries set ``entity_key`` into slot [2][5] directly on the
        # filter (see ``HotelSearchFilters.entity_key``); list queries leave
        # it null.
        request_meta: list = [1, None, None, None, None, None, 13, None, 0]
        if self.entity_key is not None:
            request_meta[5] = self.entity_key
        return [self.location.query, search_params, request_meta]

    def encode(self) -> str:
        """Produce the URL-encoded f.req form value ready for POST."""
        inner_json = json.dumps(self.format(), separators=(",", ":"))
        # Outer batchexecute envelope: [[[RPC_ID, <inner json str>, null, "1"]]]
        outer = [[[RPC_ID, inner_json, None, "1"]]]
        return urllib.parse.quote(
            json.dumps(outer, separators=(",", ":")),
            safe="",
        )

    def to_request_body(self) -> str:
        """Return the exact ``f.req=...`` form-body string for the POST."""
        return f"f.req={self.encode()}"
