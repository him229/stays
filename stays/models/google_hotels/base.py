"""Shared data models for Google Hotels search.

Enums and pydantic ``BaseModel`` building blocks consumed by
``HotelSearchFilters``.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import (
    BaseModel,
    Field,
    NonNegativeInt,
    PositiveInt,
    field_validator,
    model_validator,
)


class Currency(str, Enum):
    """Currencies the Google Hotels endpoint accepts.

    The currency is embedded in the SearchParams filter record; the server
    echoes the code back in every price entry.
    """

    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    AUD = "AUD"
    CAD = "CAD"
    CHF = "CHF"
    CNY = "CNY"
    HKD = "HKD"
    INR = "INR"
    KRW = "KRW"
    MXN = "MXN"
    NZD = "NZD"
    SEK = "SEK"
    SGD = "SGD"
    ZAR = "ZAR"


class PropertyType(Enum):
    """Property type filter — confirmed from docs/reverse-engineering/slot-map.md section 1.

    Lives at ``[1][0]``. Defaults to HOTELS when unspecified; the UI always
    sends ``1`` even when no explicit filter is set.
    """

    HOTELS = 1
    VACATION_RENTALS = 2


class SortBy(Enum):
    """Sort ordering for hotel results.

    Lives at ``[1][4][0][4]``. LOWEST_PRICE, HIGHEST_RATING, and MOST_REVIEWED
    are confirmed from the Playwright capture runs (see docs/reverse-engineering/slot-map.md
    "Run 3 findings" section).

    RELEVANCE is the UI default ("Recommended" / "Relevance" — there is no
    explicit option in the UI, and run 3 confirmed that the absence of a sort
    value IS relevance). Our serializer emits ``null`` for ``SortBy.RELEVANCE``
    (and for ``sort_by=None``) — the sentinel ``-1`` is never written to the
    wire.
    """

    LOWEST_PRICE = 3
    HIGHEST_RATING = 8
    MOST_REVIEWED = 13
    # RELEVANCE has no explicit wire value — the slot stays null when selected.
    # Kept as a sentinel so callers can distinguish "relevance" from "unset".
    RELEVANCE = -1


class Amenity(Enum):
    """Amenity filter IDs.

    Lives at ``[1][4][0][0]`` as a list of int IDs. The IDs below are
    confirmed from Playwright capture runs (see docs/reverse-engineering/slot-map.md
    "Run 3 findings" and "Run 4 findings" sections).

    Confirmed (18 total):
      - Parking (free) = 1
      - Indoor pool = 4
      - Outdoor pool = 5
      - Pool = 6
      - Gym / Fitness centre = 7
      - Restaurant = 8
      - Breakfast (free) = 9
      - Spa = 10
      - Beach access = 11
      - Kid-friendly = 12
      - Bar = 15
      - Pet-friendly = 19
      - Room service = 22
      - Wi-Fi (free) = 35
      - Air-conditioned = 40
      - All-inclusive available = 52
      - Wheelchair accessible = 53
      - EV charger = 61
    """

    PARKING = 1
    INDOOR_POOL = 4
    OUTDOOR_POOL = 5
    POOL = 6
    GYM = 7
    RESTAURANT = 8
    BREAKFAST = 9
    SPA = 10
    BEACH_ACCESS = 11
    KID_FRIENDLY = 12
    BAR = 15
    PET_FRIENDLY = 19
    ROOM_SERVICE = 22
    WIFI = 35
    AIR_CONDITIONED = 40
    ALL_INCLUSIVE = 52
    WHEELCHAIR_ACCESSIBLE = 53
    EV_CHARGER = 61


class Brand(Enum):
    """Hotel brand/family IDs.

    Lives at ``[1][4][0][7]`` as a list of ``[brand_id, [sub_brand_ids]]``
    pairs. The sub-brand list is **required and must be populated** with
    every sub-brand ID in the family — an empty list is silently treated
    as "no-op" by Google and the filter does not apply (verified live
    against Xi'an, where ``[[28, []]]`` returned Hyatt/Marriott/Wyndham/IHG
    results unchanged).

    The per-brand sub-brand ID lists are the exact values captured in run
    4 via the Playwright filter chip (``captures/output_run4.json`` →
    ``brand_<name>`` entries). Use ``sub_brand_ids`` below to reach them.

    Four Seasons is the shape exception: run 4 captured ``[[289]]`` — a
    bare single-element pair with no sub-brand list. Our serializer emits
    that form when ``sub_brand_ids`` is empty, so Four Seasons works too.
    """

    IHG = 17
    BEST_WESTERN = 18
    CHOICE = 20
    HILTON = 28
    ACCOR = 33
    # Wire IDs for Hyatt / Marriott were swapped in the original capture —
    # live test (2026-04-22) confirmed:
    #   * ID 37 + 11 sub-brands  → Hyatt family
    #   * ID 46 + 23 sub-brands  → Marriott family
    # Matches brand scope: Marriott has ~23 sub-brands (Courtyard, Fairfield,
    # Sheraton, Westin, W, Ritz-Carlton, St. Regis, Renaissance, Aloft, Moxy,
    # Autograph, JW Marriott, AC, Delta, etc.); Hyatt has ~11 (Park/Grand/
    # Regency/Andaz/Alila/Thompson/Dream/JdV/Caption/Destination/Place/House).
    HYATT = 37
    MARRIOTT = 46
    WYNDHAM = 53
    FOUR_SEASONS = 289

    @property
    def sub_brand_ids(self) -> list[int]:
        """Sub-brand IDs that must accompany this brand in the filter slot.

        Values are the exact lists captured via Playwright in run 4. An
        empty list means "no sub-brand enumeration needed" (Four Seasons).
        """
        return _BRAND_SUB_IDS.get(self, [])


# Captured from ``captures/output_run4.json`` brand_<name>.request.inner_payload
# → ``[1][4][0][7]``. Populated via Playwright clicking each brand chip in
# isolation and intercepting the XHR. Count per brand matches SLOT_MAP.md.
_BRAND_SUB_IDS: dict[Brand, list[int]] = {
    Brand.IHG: [125, 52, 42, 282, 64, 56, 87, 2, 127, 298],
    Brand.BEST_WESTERN: [155, 104, 105, 254, 255, 107],
    Brand.CHOICE: [63, 112, 27, 113, 82, 78, 23, 293],
    Brand.HILTON: [114, 7, 151, 81, 88, 115, 71, 95, 54, 36, 77, 295, 285, 286, 41],
    Brand.ACCOR: [8, 84],
    # Hyatt = ID 37 with 11 sub-brands (confirmed live 2026-04-22)
    Brand.HYATT: [116, 412, 288, 119, 120, 121, 122, 349, 118, 346, 262],
    # Marriott = ID 46 with 23 sub-brands (confirmed live 2026-04-22)
    Brand.MARRIOTT: [
        128,
        60,
        59,
        86,
        153,
        256,
        134,
        58,
        135,
        26,
        72,
        61,
        129,
        131,
        75,
        3,
        12,
        83,
        136,
        143,
        40,
        137,
        39,
    ],
    Brand.WYNDHAM: [30, 19, 38, 11, 49, 50, 93, 284, 16, 65, 68, 150, 141],
    # Four Seasons: captured as bare [[289]] — no sub-brand list at all.
    Brand.FOUR_SEASONS: [],
}


class MinGuestRating(Enum):
    """Minimum guest rating filter.

    Lives at ``[1][4][4]`` as a single int. Encoding is ``round(rating * 2)``
    — so 4.5+ → 9, 4.0+ → 8, 3.5+ → 7.

    TODO: only 4.5+ (=9) is currently confirmed from the Playwright run.
    The 7 and 8 values are inferred by the ``*2`` pattern; rerun the 3.5+
    and 4.0+ captures to confirm.
    """

    THREE_FIVE_PLUS = 7
    FOUR_ZERO_PLUS = 8
    FOUR_FIVE_PLUS = 9


class Location(BaseModel):
    """Where to search for hotels.

    The simplest form is just `query`, e.g. ``"paris, france hotels"``. Google's
    server resolves it to a KGMID (Knowledge Graph ID) and scopes the results.
    Ambiguous names are disambiguated by including a region:
    ``"paris, texas hotels"`` vs ``"paris, france hotels"``.

    For pinning (e.g. once a prior response resolved a KGMID), supply
    ``kgmid`` and/or ``fid``. **The pin only takes effect when the query
    text is neutral** — if ``query`` names a specific city, Google uses
    that and ignores the pin. This is by design: it lets MCP callers send
    e.g. ``"paris, france hotels"`` without a stale pin sending them to
    Paris, Texas. ``display_name`` is echoed back in the response and is
    otherwise informational.
    """

    query: str = Field(
        ...,
        description="Free-text query sent verbatim to Google. Include region for ambiguous cities.",
    )
    kgmid: str | None = Field(
        None,
        description="Google Knowledge Graph ID, e.g. '/m/05qtj' (Paris, FR) or '/g/1tfbypzs' (San Mateo).",
    )
    fid: str | None = Field(
        None,
        description="Google Maps Feature ID in hex form, e.g. '0x808f9e60efa95545:0xfd8efcf42dcc1ba7'.",
    )
    display_name: str | None = Field(None, description="Human-readable place name echoed in the response.")

    @field_validator("query")
    @classmethod
    def _non_empty_query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Location.query must be non-empty")
        return v

    @field_validator("kgmid")
    @classmethod
    def _valid_kgmid(cls, v: str | None) -> str | None:
        if v is not None and not (v.startswith("/m/") or v.startswith("/g/")):
            raise ValueError("kgmid must start with '/m/' or '/g/'")
        return v

    @field_validator("fid")
    @classmethod
    def _valid_fid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if "0x" not in v or ":" not in v:
            raise ValueError("fid must look like '0xHHH...:0xHHH...'")
        return v

    @property
    def has_pin(self) -> bool:
        """True when a structural location (KGMID / FID / name) should be sent."""
        return bool(self.kgmid or self.fid or self.display_name)


class DateRange(BaseModel):
    """Check-in and check-out dates for the stay.

    Both dates are required if supplied; check_out must be strictly after
    check_in. Omitting the whole DateRange produces the 'flexible dates'
    style response where Google picks defaults.
    """

    check_in: date
    check_out: date

    @model_validator(mode="after")
    def _validate_order(self) -> DateRange:
        if self.check_out <= self.check_in:
            raise ValueError("check_out must be after check_in")
        return self

    @field_validator("check_in", "check_out", mode="before")
    @classmethod
    def _parse_date(cls, v):
        if isinstance(v, str):
            return datetime.strptime(v, "%Y-%m-%d").date()
        return v

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days


class GuestInfo(BaseModel):
    """Who is traveling.

    Google's accepted shape is a list at slot [1][2][1][5]. Our tests show
    the server accepts a single ``[N]`` (total occupants) and returns valid
    results; multi-element forms like ``[adults, children]`` are also
    accepted but their per-field semantics haven't been confirmed to alter
    pricing/availability. We send the total count as the conservative
    default and expose per-field inputs so future RE can wire them up.

    When ``children > 0``, ``child_ages`` must list one age per child
    (0-17). The extras block at ``[1][1]`` is then emitted using those
    ages; see ``age_to_bucket`` for the age → Google-bucket mapping.

    ``rooms`` is not yet confirmed to map to a specific slot; for now the
    serializer surfaces it as a stored preference but does not transmit it.
    """

    adults: PositiveInt = 2
    children: NonNegativeInt = 0
    rooms: PositiveInt = 1
    child_ages: list[NonNegativeInt] = Field(default_factory=list)

    @field_validator("child_ages")
    @classmethod
    def _valid_child_ages(cls, v: list[int]) -> list[int]:
        for age in v:
            if age < 0 or age > 17:
                raise ValueError("child_ages entries must be 0-17")
        return v

    @model_validator(mode="after")
    def _children_match_ages(self) -> GuestInfo:
        # Either no ages given (children count may still be set so the total
        # occupants math works) OR the ages list length must equal children.
        if self.child_ages and len(self.child_ages) != self.children:
            raise ValueError(f"child_ages length ({len(self.child_ages)}) must equal children ({self.children})")
        return self

    @property
    def total_occupants(self) -> int:
        return self.adults + self.children

    @staticmethod
    def age_to_bucket(age: int) -> list[int]:
        """Map a child age to Google's internal age-bucket pair.

        Buckets currently applied:
          - ages 2-12 → ``[2, 12]`` (CONFIRMED from captures, ages 5/7/10)
          - ages 0-1 → ``[0, 1]``  (UNCONFIRMED — inferred bucket boundary)
          - ages 13-17 → ``[13, 17]`` (UNCONFIRMED — inferred bucket boundary)

        TODO: confirm buckets once captures land for infant (0, 1) and teen
        (13-17) ages. The current 0-1 and 13-17 buckets are our best guess;
        if Google actually uses a different bucketing we'll find out.
        """
        if 2 <= age <= 12:
            return [2, 12]
        # TODO: confirm buckets once captures land
        if 0 <= age <= 1:
            return [0, 1]
        if 13 <= age <= 17:
            return [13, 17]
        return [age, age]
