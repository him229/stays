"""Detail-mode parser — turns a single-hotel AtySUc response into ``HotelDetail``.

The detail response surfaces exactly one enriched hotel entry. We reuse
the shared hotel-entry walker (``_parse_hotel_entry``) and then extend with
fields only present in detail mode: street address, phone, full description,
human-readable amenity labels, and room/rate plans per provider.
"""

from __future__ import annotations

from typing import Any

from stays.models.google_hotels.detail import (
    HotelDetail,
    RatePlan,
    Review,
    RoomType,
)
from stays.search.parse.provider_parser import _parse_provider_rate
from stays.search.parse.search_parser import _find_hotel_entries, _parse_hotel_entry
from stays.search.parse.slots import (
    SLOT_ADDRESS,
    SLOT_AMENITY_DETAILS,
    SLOT_DESCRIPTION,
    SLOT_PHONE,
    SLOT_PROVIDER_BLOCK,
    SLOT_PROVIDER_LIST,
    SLOT_REVIEWS_LIST,
    Tree,
    safe_get,
)

__all__ = ["parse_detail_response"]


def parse_detail_response(inner: Tree) -> HotelDetail:
    """Parse a single-hotel AtySUc detail response into a HotelDetail.

    The detail response surfaces exactly one enriched hotel entry. We
    reuse the shared hotel-entry walker and then extend with the fields
    only present in detail mode — street address, phone, full description,
    amenity group labels, and room/rate plans.

    The hotel entry is found via `_find_hotel_entries` (same heuristic as
    search). In detail mode there's typically only one matching entry; if
    multiple, take the first.
    """
    entries = _find_hotel_entries(inner)
    if not entries:
        raise ValueError("parse_detail_response: no hotel entry found in response")
    entry = entries[0]
    base = _parse_hotel_entry(entry)
    if base is None:
        raise ValueError("parse_detail_response: hotel entry failed to parse")

    # Address: SLOT_ADDRESS = entry[2][1][0][0][0]
    addr_node = safe_get(entry, *SLOT_ADDRESS)
    address: str | None = addr_node if isinstance(addr_node, str) else None

    # Phone: SLOT_PHONE = entry[2][2][0]
    phone_node = safe_get(entry, *SLOT_PHONE)
    phone: str | None = phone_node if isinstance(phone_node, str) else None

    # Description (short): SLOT_DESCRIPTION = entry[11][0]
    description_node = safe_get(entry, *SLOT_DESCRIPTION)
    description: str | None = description_node if isinstance(description_node, str) else None

    # Rate plans / rooms from SLOT_PROVIDER_BLOCK (entry[6][2]):
    #   [6][2][1] = [display_low_str, display_high_str, base_num, null, display_num]
    #   [6][2][2] = SLOT_PROVIDER_LIST, list of providers
    # For now, build a SINGLE synthetic RoomType whose rates are the
    # observed per-provider options. Google's entity-page "rooms" tab
    # would unpack into multiple RoomType objects if we'd captured that
    # modal; for this MVP we surface providers as rates.
    rooms: list[RoomType] = []
    providers_block = safe_get(entry, *SLOT_PROVIDER_BLOCK)
    if isinstance(providers_block, list):
        provider_list_entry = safe_get(entry, *SLOT_PROVIDER_LIST)
        rates: list[RatePlan] = []
        if isinstance(provider_list_entry, list):
            for provider_entry in provider_list_entry:
                rate = _parse_provider_rate(provider_entry, base.currency or "USD")
                if rate is not None:
                    rates.append(rate)
        if rates:
            rooms.append(RoomType(name="Standard Room", rates=rates))

    # Amenity details: SLOT_AMENITY_DETAILS subtree contains human-readable
    # text labels under the available-bit pairs. Walk it and collect any
    # string children that look like amenity labels.
    amenity_details: list[str] = []
    pos10 = safe_get(entry, *SLOT_AMENITY_DETAILS)
    if isinstance(pos10, list):

        def collect_labels(n: Any) -> None:
            if isinstance(n, str) and 2 <= len(n) <= 60 and n[0].isupper():
                amenity_details.append(n)
            elif isinstance(n, list):
                for child in n:
                    collect_labels(child)

        collect_labels(pos10)
    amenity_details = amenity_details[:40]

    # Reviews sample from SLOT_REVIEWS_LIST = entry[7][3]
    recent_reviews: list[Review] = []
    reviews_block = safe_get(entry, *SLOT_REVIEWS_LIST)
    if isinstance(reviews_block, list):
        for review_entry in reviews_block[:5]:
            rv = _parse_review_entry(review_entry)
            if rv is not None:
                recent_reviews.append(rv)

    return HotelDetail(
        **base.model_dump(),
        description=description,
        address=address,
        phone=phone,
        rooms=rooms,
        amenity_details=amenity_details,
        recent_reviews=recent_reviews,
    )


def _parse_review_entry(entry: Tree) -> Review | None:
    if not isinstance(entry, list):
        return None
    rating: int | None = None
    body: str | None = None
    author: str | None = None

    def walk(n: Any) -> None:
        nonlocal rating, body, author
        if isinstance(n, int) and 1 <= n <= 5 and rating is None:
            rating = n
        elif isinstance(n, str):
            if len(n) > 40 and body is None:
                body = n
            elif 2 <= len(n) <= 40 and author is None and n[0].isupper():
                author = n
        elif isinstance(n, list):
            for x in n:
                walk(x)

    walk(entry)

    if rating is None or body is None:
        return None
    return Review(author_name=author, rating=rating, body=body)
