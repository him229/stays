"""Search-mode response parser — turns an AtySUc search response into
a list of ``HotelResult`` (list-view results).

Also exports the shared ``_find_hotel_entries`` and ``_parse_hotel_entry``
helpers that the detail-mode parser reuses, and ``extract_kgmid_from_protobuf``
for decoding the base64-wrapped entity key.
"""

from __future__ import annotations

import base64
import logging
import re
from datetime import date as _date
from typing import Any

from stays.models.google_hotels.base import Amenity
from stays.models.google_hotels.result import (
    CategoryRating,
    HotelResult,
    NearbyPlace,
    RatingHistogram,
)
from stays.search.parse.slots import (
    SLOT_ENTRY_COORDS,
    SLOT_ENTRY_DISPLAY_PRICE_NUM,
    SLOT_ENTRY_PRICE_CURRENCY,
    SLOT_ENTRY_PRICE_DATES,
    SLOT_ENTRY_PRICE_PAIR,
    SLOT_NEARBY_DURATION,
    SLOT_NEARBY_MODE_ID,
    HotelEntryRaw,
    Tree,
    safe_get,
)

logger = logging.getLogger(__name__)

__all__ = [
    "extract_kgmid_from_protobuf",
    "parse_search_response",
    "_find_hotel_entries",
    "_parse_hotel_entry",
]


# ---------------------------------------------------------------------------
# KGMID extraction
# ---------------------------------------------------------------------------


def extract_kgmid_from_protobuf(b64_or_bytes: str | bytes) -> str | None:
    """Decode a ChgI-style base64 protobuf; return the embedded KGMID."""
    if isinstance(b64_or_bytes, str):
        try:
            raw = base64.urlsafe_b64decode(b64_or_bytes + "=" * (-len(b64_or_bytes) % 4))
        except Exception:
            return None
    else:
        raw = b64_or_bytes
    for marker in (b"/g/", b"/m/"):
        idx = raw.find(marker)
        if idx >= 0:
            end = idx
            while end < len(raw) and 32 <= raw[end] < 127:
                end += 1
            return raw[idx:end].decode("ascii")
    return None


# ---------------------------------------------------------------------------
# Search response walker
# ---------------------------------------------------------------------------


def _find_hotel_entries(tree: Tree) -> list[HotelEntryRaw]:
    """Return every nested list that looks like a hotel-entry tuple.

    Heuristic: a hotel entry is a list of length >= 20 whose [1] is a
    non-empty hotel name, whose [2][0] is a [lat, lng] float-pair
    (structural anchor), and which carries a stable identifier — FID
    at [9] or entity_key at [20].

    Star-class is NOT required: many real hotels (budget, boutique,
    hostels) return ``entry[3] = None`` and must still surface.
    """
    found: list[HotelEntryRaw] = []

    def looks_like_hotel(node: Any) -> bool:
        if not isinstance(node, list) or len(node) < 20:
            return False
        name = node[1] if len(node) > 1 else None
        if not isinstance(name, str) or not name:
            return False
        # Identifiers: FID at [9] or entity_key at [20]
        fid = node[9] if len(node) > 9 else None
        ek = node[20] if len(node) > 20 else None
        if not ((isinstance(fid, str) and fid) or (isinstance(ek, str) and ek)):
            return False
        # Structural anchor: coords pair at [2][0] = [lat, lng]
        pos2 = node[2] if len(node) > 2 else None
        coords = pos2[0] if isinstance(pos2, list) and pos2 else None
        if not (isinstance(coords, list) and len(coords) == 2 and all(isinstance(c, (int, float)) for c in coords)):
            logger.debug("skip hotel-like entry name=%r reason=%s", name, "missing_coords_anchor")
            return False
        return True

    def walk(node: Any) -> None:
        if looks_like_hotel(node):
            found.append(node)
            return
        if isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)

    walk(tree)
    return found


def _parse_hotel_entry(entry: HotelEntryRaw) -> HotelResult | None:
    """Parse one 48-slot hotel entry into a HotelResult.

    Tolerates missing / None sub-slots. Returns None when the name slot
    (entry[1]) is missing or not a string.
    """

    def at(idx: int) -> Any:
        return entry[idx] if idx < len(entry) else None

    name = at(1)
    if not isinstance(name, str):
        return None

    # SLOT_ENTRY_COORDS = entry[2][0] = [lat, lng]
    lat = lng = None
    pos2 = at(2)
    coords_pair = safe_get(entry, *SLOT_ENTRY_COORDS)
    if isinstance(coords_pair, list) and len(coords_pair) == 2:
        lat, lng = coords_pair

    # [3] = ["N-star hotel", N]
    star_class = star_label = None
    pos3 = at(3)
    if isinstance(pos3, list) and len(pos3) >= 2:
        star_label = pos3[0] if isinstance(pos3[0], str) else None
        star_class = pos3[1] if isinstance(pos3[1], int) else None

    # images: [5] and/or [12]
    image_urls: list[str] = []
    for candidate in (at(12), at(5)):
        if isinstance(candidate, str) and candidate.startswith("http"):
            image_urls.append(candidate)
        elif isinstance(candidate, list):

            def walk_images(n: Any) -> None:
                if isinstance(n, str) and n.startswith("http"):
                    image_urls.append(n)
                elif isinstance(n, list):
                    for x in n:
                        walk_images(x)

            walk_images(candidate)
            if len(image_urls) >= 10:
                break
    image_urls = image_urls[:10]

    # [6] = pricing block — slots defined in slots.py:
    #   SLOT_ENTRY_PRICE_PAIR     entry[6][1][0] → [price, 0]
    #   SLOT_ENTRY_PRICE_CURRENCY entry[6][1][3] → currency
    #   SLOT_ENTRY_PRICE_DATES    entry[6][1][4] → [[Y,M,D], [Y,M,D]]
    #   SLOT_ENTRY_DISPLAY_PRICE_NUM entry[6][2][1][4] → display_num (list-view UI)
    #
    # Detail-mode responses have SLOT_ENTRY_PRICE_PAIR == None; that acts as
    # the list-view-only guard — currency / rate_dates / fallback price are
    # only populated when the pair exists (search mode).
    display_price = currency = None
    rate_dates: tuple[_date, _date] | None = None

    price_pair = safe_get(entry, *SLOT_ENTRY_PRICE_PAIR)
    if isinstance(price_pair, list):
        # Currency
        currency_val = safe_get(entry, *SLOT_ENTRY_PRICE_CURRENCY)
        if isinstance(currency_val, str):
            currency = currency_val

        # Rate-date window
        date_block = safe_get(entry, *SLOT_ENTRY_PRICE_DATES)
        if (
            isinstance(date_block, list)
            and len(date_block) >= 2
            and all(isinstance(d, list) and len(d) == 3 and all(isinstance(x, int) for x in d) for d in date_block[:2])
        ):
            try:
                ci_d = _date(*date_block[0])
                co_d = _date(*date_block[1])
                rate_dates = (ci_d, co_d)
            except (ValueError, TypeError):
                pass

        # Fallback price: SLOT_ENTRY_PRICE_PAIR[0] is the cheapest-rate integer
        if price_pair and isinstance(price_pair[0], int):
            display_price = price_pair[0]

    # Primary price: SLOT_ENTRY_DISPLAY_PRICE_NUM wins when present and >0
    display_num = safe_get(entry, *SLOT_ENTRY_DISPLAY_PRICE_NUM)
    if isinstance(display_num, (int, float)) and display_num > 0:
        display_price = int(display_num)

    # [7] review summary: [[overall, count], [[[star, pct, count], ...]], ...]
    overall_rating = review_count = None
    histogram = RatingHistogram()
    pos7 = at(7)
    if isinstance(pos7, list) and pos7:
        head = pos7[0]
        if isinstance(head, list) and len(head) >= 2:
            if isinstance(head[0], (int, float)):
                overall_rating = float(head[0])
            if isinstance(head[1], int):
                review_count = head[1]
        if len(pos7) >= 2 and isinstance(pos7[1], list):
            nested = pos7[1]
            if nested and isinstance(nested[0], list):
                for triple in nested[0]:
                    if (
                        isinstance(triple, list)
                        and len(triple) >= 3
                        and isinstance(triple[0], int)
                        and isinstance(triple[2], int)
                    ):
                        histogram.bucket_counts[triple[0]] = triple[2]

    # [9] = FID
    fid = at(9) if isinstance(at(9), str) else None

    # [10] = amenities as [[bool, id], ...]
    amenities: set[Amenity] = set()
    pos10 = at(10)
    if isinstance(pos10, list):

        def walk_amenities(n: Any) -> None:
            if isinstance(n, list):
                if len(n) >= 2 and isinstance(n[0], bool) and isinstance(n[1], int):
                    if n[0]:
                        try:
                            amenities.add(Amenity(n[1]))
                        except ValueError:
                            pass
                else:
                    for child in n:
                        walk_amenities(child)

        walk_amenities(pos10)

    # [20] = entity_key (protobuf base64). Same slot carries the KGMID
    # when decoded.
    entity_key = at(20) if isinstance(at(20), str) else None
    kgmid = extract_kgmid_from_protobuf(entity_key) if entity_key else None

    # [25] = google_hotel_id
    google_hotel_id = at(25) if isinstance(at(25), str) else None

    # Walk [2] for category ratings / check-in times / nearby places.
    category_ratings: list[CategoryRating] = []
    check_in_time = check_out_time = None
    nearby_entries: list[NearbyPlace] = []
    if isinstance(pos2, list):

        def visit(node: Any) -> None:
            nonlocal check_in_time, check_out_time
            if isinstance(node, list):
                # 5-category rating tuple: [[1-5, "N.N"], ...] with >=3 entries
                if (
                    len(node) >= 3
                    and all(
                        isinstance(e, list)
                        and len(e) == 2
                        and isinstance(e[0], int)
                        and 1 <= e[0] <= 5
                        and isinstance(e[1], str)
                        for e in node
                    )
                    and not category_ratings
                ):
                    for cat_id, score_str in node:
                        try:
                            category_ratings.append(CategoryRating(category_id=cat_id, score=float(score_str)))
                        except (ValueError, TypeError):
                            pass
                    return
                # Check-in/out pair: [<"HH:MM AM/PM">, <"HH:MM AM/PM">]
                if (
                    len(node) == 2
                    and all(isinstance(e, str) for e in node)
                    and any(tok in node[0] for tok in ("AM", "PM"))
                    and any(tok in node[1] for tok in ("AM", "PM"))
                    and check_in_time is None
                ):
                    check_in_time, check_out_time = node
                    return
                # Nearby place: [name, None, [[mode_id, "N min"]]]
                # SLOT_NEARBY_MODE_ID = node[2][0][0]; SLOT_NEARBY_DURATION = node[2][0][1]
                mode_id = safe_get(node, *SLOT_NEARBY_MODE_ID)
                dur_str = safe_get(node, *SLOT_NEARBY_DURATION)
                if (
                    len(node) >= 3
                    and isinstance(node[0], str)
                    and node[1] is None
                    and isinstance(mode_id, int)
                    and isinstance(dur_str, str)
                ):
                    mode_map = {0: "walk", 1: "drive", 2: "transit", 3: "bike"}
                    mode = mode_map.get(mode_id, f"mode_{mode_id}")
                    m = re.match(r"(\d+)", dur_str)
                    duration = int(m.group(1)) if m else None
                    nearby_entries.append(
                        NearbyPlace(
                            name=node[0],
                            mode=mode,
                            duration_minutes=duration,
                            distance_text=dur_str,
                        )
                    )
                    return
                for child in node:
                    visit(child)
            elif isinstance(node, dict):
                for v in node.values():
                    visit(v)

        visit(pos2)

    return HotelResult(
        name=name,
        kgmid=kgmid,
        fid=fid,
        google_hotel_id=google_hotel_id,
        entity_key=entity_key,
        latitude=lat,
        longitude=lng,
        display_price=display_price,
        currency=currency,
        rate_dates=rate_dates,
        star_class=star_class,
        star_class_label=star_label,
        overall_rating=overall_rating,
        review_count=review_count,
        rating_histogram=histogram if histogram.bucket_counts else None,
        category_ratings=category_ratings,
        check_in_time=check_in_time,
        check_out_time=check_out_time,
        amenities_available=amenities,
        nearby=nearby_entries[:20],
        image_urls=image_urls,
    )


def parse_search_response(inner: Tree) -> list[HotelResult]:
    """Top-level search-response parser.

    De-duplicates using the first available stable identifier per hotel
    (kgmid > fid > google_hotel_id). Hotels lacking ALL three are kept
    (losing a hotel silently because we couldn't hash it is worse than
    showing it twice).
    """
    results: list[HotelResult] = []
    for entry in _find_hotel_entries(inner):
        parsed = _parse_hotel_entry(entry)
        if parsed is not None:
            results.append(parsed)
    seen: set[str] = set()
    unique: list[HotelResult] = []
    for r in results:
        key = r.kgmid or r.fid or r.google_hotel_id
        if key is None:
            unique.append(r)
            continue
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return unique
