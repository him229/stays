"""Detail-mode parser — turns a single-hotel AtySUc response into ``HotelDetail``.

The detail response surfaces exactly one enriched hotel entry. We reuse
the shared hotel-entry walker (``_parse_hotel_entry``) and then extend with
fields only present in detail mode: street address, phone, full description,
human-readable amenity labels, and room/rate plans per provider.
"""

from __future__ import annotations

import html
import re
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

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def parse_detail_response(inner: Tree, *, reference_year: int | None = None) -> HotelDetail:
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
                rate = _parse_provider_rate(
                    provider_entry,
                    base.currency or "USD",
                    reference_year=reference_year,
                )
                if rate is not None:
                    rates.append(rate)
        if rates:
            rooms.append(RoomType(name="Standard Room", rates=rates))

    # Amenity details: entry[10][0] contains grouped human-readable labels.
    # Other branches contain search-result snippets and business names, so
    # parse only the documented label records instead of recursively walking
    # every string in the subtree.
    pos10 = safe_get(entry, *SLOT_AMENITY_DETAILS)
    amenity_details = _parse_amenity_details(pos10)

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


def _parse_amenity_details(node: Any) -> list[str]:
    """Extract canonical amenity labels from the detail amenity subtree."""
    groups = safe_get(node, 0, default=[])
    if not isinstance(groups, list):
        return []

    labels: list[str] = []
    seen: set[str] = set()
    for group in groups:
        amenity_records = safe_get(group, 1, default=[])
        if not isinstance(amenity_records, list):
            continue
        for record in amenity_records:
            raw_label = safe_get(record, 0)
            if not isinstance(raw_label, str):
                continue
            label = _HTML_TAG_RE.sub("", html.unescape(raw_label))
            label = " ".join(label.split())
            key = label.casefold()
            if not label or key in seen:
                continue
            seen.add(key)
            labels.append(label)
            if len(labels) == 40:
                return labels

    return labels


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
