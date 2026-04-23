"""Response-tree walkers for the AtySUc RPC (search + detail mode).

Patterns:
  - `_find_hotel_entries(tree)` — returns the list of ~48-slot hotel-entry
    lists embedded in an AtySUc search response.
  - `parse_search_response(inner)` — top-level: extracts every HotelResult.
  - `parse_detail_response(inner)` — extracts the single enriched hotel
    from the detail-mode response (entity_key in slot [2][5]).
  - `extract_kgmid_from_protobuf(b64)` — decodes a `ChgI...`-style wrapper
    into a `/g/...` or `/m/...` KGMID string.
"""

from __future__ import annotations

import base64
import re
from datetime import date as _date
from typing import Any

from stays.models.google_hotels.base import Amenity
from stays.models.google_hotels.detail import (
    HotelDetail,
    RatePlan,
    Review,
    RoomType,
)
from stays.models.google_hotels.policy import (
    CancellationPolicy,
    CancellationPolicyKind,
)
from stays.models.google_hotels.result import (
    CategoryRating,
    HotelResult,
    NearbyPlace,
    RatingHistogram,
)

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


def _find_hotel_entries(tree: Any) -> list[list]:
    """Return every nested list that looks like a hotel-entry tuple.

    Heuristic: a hotel entry is a list of length >= 26 whose [1] is a
    non-empty string (hotel name) and whose [2] is a non-empty nested
    list whose first element is a [lat, lng] float-pair.
    """
    found: list[list] = []

    def looks_like_hotel(node: Any) -> bool:
        """Hotel entry anchor — works on both live (thin 27-slot) and captured
        (rich 48-slot) responses. Key signal is the star-class tuple at [3]
        plus at least one stable identifier at [9] (FID) or [20] (entity_key)."""
        if not isinstance(node, list) or len(node) < 20:
            return False
        name = node[1] if len(node) > 1 else None
        if not isinstance(name, str) or not name:
            return False
        # star-class tuple at [3]: ["<N>-star hotel", N]
        pos3 = node[3] if len(node) > 3 else None
        if not (
            isinstance(pos3, list)
            and len(pos3) >= 2
            and isinstance(pos3[0], str)
            and isinstance(pos3[1], int)
            and 1 <= pos3[1] <= 5
        ):
            return False
        # At least one identifier: FID at [9] or entity_key at [20]
        fid = node[9] if len(node) > 9 else None
        ek = node[20] if len(node) > 20 else None
        if not ((isinstance(fid, str) and fid) or (isinstance(ek, str) and ek)):
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


def _parse_hotel_entry(entry: list) -> HotelResult | None:
    """Parse one 48-slot hotel entry into a HotelResult.

    Tolerates missing / None sub-slots. Returns None when the name slot
    (entry[1]) is missing or not a string.
    """

    def at(idx: int) -> Any:
        return entry[idx] if idx < len(entry) else None

    name = at(1)
    if not isinstance(name, str):
        return None

    # [2][0] = [lat, lng]
    lat = lng = None
    pos2 = at(2)
    if isinstance(pos2, list) and pos2 and isinstance(pos2[0], list) and len(pos2[0]) == 2:
        lat, lng = pos2[0]

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

    # [6] = pricing block:
    #   [6][1] inner: inner[0] = [price, 0], inner[3] = currency, inner[4] = dates
    #   [6][2][1] = [display_low_str, display_high_str, base_num, None, display_num]
    #              display_num (index [4]) is the price Google shows in list-view UI.
    display_price = currency = None
    rate_dates: tuple[_date, _date] | None = None
    pos6 = at(6)
    if isinstance(pos6, list) and len(pos6) >= 2:
        inner = pos6[1]
        if isinstance(inner, list) and inner and isinstance(inner[0], list):
            # Extract currency and dates from [6][1] (always present)
            if len(inner) > 3 and isinstance(inner[3], str):
                currency = inner[3]
            if len(inner) > 4 and isinstance(inner[4], list):
                date_block = inner[4]
                if len(date_block) >= 2 and all(
                    isinstance(d, list) and len(d) == 3 and all(isinstance(x, int) for x in d) for d in date_block[:2]
                ):
                    try:
                        ci_d = _date(*date_block[0])
                        co_d = _date(*date_block[1])
                        rate_dates = (ci_d, co_d)
                    except (ValueError, TypeError):
                        pass
            # Fallback price from [6][1][0][0] (cheapest provider rate)
            price_pair = inner[0]
            if price_pair and isinstance(price_pair[0], int):
                display_price = price_pair[0]

        # Primary price: [6][2][1][4] = display_num (matches Google list-view UI)
        if len(pos6) >= 3 and isinstance(pos6[2], list):
            pos6_2 = pos6[2]
            if len(pos6_2) > 1 and isinstance(pos6_2[1], list) and len(pos6_2[1]) >= 5:
                display_num = pos6_2[1][4]
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
                if (
                    len(node) >= 3
                    and isinstance(node[0], str)
                    and node[1] is None
                    and isinstance(node[2], list)
                    and node[2]
                    and isinstance(node[2][0], list)
                    and len(node[2][0]) == 2
                    and isinstance(node[2][0][0], int)
                    and isinstance(node[2][0][1], str)
                ):
                    mode_map = {0: "walk", 1: "drive", 2: "transit", 3: "bike"}
                    mode_id, dur_str = node[2][0]
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


def parse_search_response(inner: Any) -> list[HotelResult]:
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


# ---------------------------------------------------------------------------
# Detail response walker
# ---------------------------------------------------------------------------


def parse_detail_response(inner: Any) -> HotelDetail:
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

    def at(idx: int) -> Any:
        return entry[idx] if idx < len(entry) else None

    # Address: per DETAIL_SLOT_MAP, entry[2][1][0][0][0] is the street.
    address: str | None = None
    phone: str | None = None
    pos2 = at(2)
    if isinstance(pos2, list):
        # [1][0][0][0] address path
        try:
            addr_node = pos2[1][0][0][0]
            if isinstance(addr_node, str):
                address = addr_node
        except (IndexError, TypeError, KeyError):
            pass
        # [2][0] phone string (and [2][1] dial link)
        try:
            phone_node = pos2[2][0]
            if isinstance(phone_node, str):
                phone = phone_node
        except (IndexError, TypeError, KeyError):
            pass

    # Description (short, long) at entry[11]
    description: str | None = None
    pos11 = at(11)
    if isinstance(pos11, list) and pos11 and isinstance(pos11[0], str):
        description = pos11[0]

    # Rate plans / rooms from entry[6][2]:
    #   [6][2][1] = [display_low_str, display_high_str, base_num, null, display_num]
    #   [6][2][2] = list of providers (each provider: [provider_name, ..., price, ...])
    # For now, build a SINGLE synthetic RoomType whose rates are the
    # observed per-provider options. Google's entity-page "rooms" tab
    # would unpack into multiple RoomType objects if we'd captured that
    # modal; for this MVP we surface providers as rates.
    rooms: list[RoomType] = []
    pos6 = at(6)
    if isinstance(pos6, list) and len(pos6) >= 3 and isinstance(pos6[2], list):
        providers_block = pos6[2]
        provider_list_entry = providers_block[2] if len(providers_block) > 2 else None
        rates: list[RatePlan] = []
        if isinstance(provider_list_entry, list):
            for provider_entry in provider_list_entry:
                rate = _parse_provider_rate(provider_entry, base.currency or "USD")
                if rate is not None:
                    rates.append(rate)
        if rates:
            rooms.append(RoomType(name="Standard Room", rates=rates))

    # Amenity details: entry[10] sub-structure contains human-readable
    # text labels under the available-bit pairs. Walk it and collect any
    # string children that look like amenity labels.
    amenity_details: list[str] = []
    pos10 = at(10)
    if isinstance(pos10, list):

        def collect_labels(n: Any) -> None:
            if isinstance(n, str) and 2 <= len(n) <= 60 and n[0].isupper():
                amenity_details.append(n)
            elif isinstance(n, list):
                for child in n:
                    collect_labels(child)

        collect_labels(pos10)
    amenity_details = amenity_details[:40]

    # Reviews sample from entry[7][3]
    recent_reviews: list[Review] = []
    pos7 = at(7)
    if isinstance(pos7, list) and len(pos7) > 3 and isinstance(pos7[3], list):
        for review_entry in pos7[3][:5]:
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


def _parse_cancellation(text: str) -> CancellationPolicy | None:
    """Extract a CancellationPolicy from a Google cancellation label string.

    Handles whitespace-padded strings like:
      "\n   Free cancellation until Apr 25\n "
      "Non-refundable"
      "Partially refundable"
    """
    from datetime import datetime as _dt_cls

    t = text.strip()
    if not t:
        return None

    # Free cancellation until <date>
    m = re.search(
        r"free cancellation until\s+([A-Za-z]+ \d{1,2}(?:,?\s*\d{4})?)",
        t,
        re.IGNORECASE,
    )
    if m:
        raw_date = m.group(1).strip().rstrip(",")
        free_until: _date | None = None
        for fmt in ("%b %d %Y", "%B %d %Y", "%b %d", "%B %d"):
            try:
                parsed = _dt_cls.strptime(raw_date, fmt)
                if parsed.year == 1900:
                    # No year in format — use current year, advance to next if past
                    today = _date.today()
                    parsed = parsed.replace(year=today.year)
                    if parsed.date() < today:
                        parsed = parsed.replace(year=today.year + 1)
                free_until = parsed.date()
                break
            except ValueError:
                continue
        return CancellationPolicy(
            kind=CancellationPolicyKind.FREE_UNTIL_DATE,
            free_until=free_until,
            description=t,
        )

    # Generic free cancellation (no date)
    if re.search(r"free cancellation", t, re.IGNORECASE):
        return CancellationPolicy(
            kind=CancellationPolicyKind.FREE_CANCELLATION,
            description=t,
        )

    # Partially refundable
    if re.search(r"partial(ly)? refund", t, re.IGNORECASE):
        return CancellationPolicy(
            kind=CancellationPolicyKind.PARTIALLY_REFUNDABLE,
            description=t,
        )

    # Non-refundable
    if re.search(r"non.?refundable|no cancel|fully refundable\b.*not", t, re.IGNORECASE):
        return CancellationPolicy(
            kind=CancellationPolicyKind.NON_REFUNDABLE,
            description=t,
        )

    return None


def _parse_cancellation_tuple(n: Any) -> CancellationPolicy | None:
    """Detect Google's structured cancellation tuple: [bool, date_str, time_str].

    Google encodes per-rate cancellation as a list where:
      [True, "Jul 20", "11:59 PM"]  → free cancellation until Jul 20
      [False]                        → no free cancellation
    Only fires when the first element is True with a valid month-day string.
    """
    from datetime import datetime as _dt_cls

    if not isinstance(n, list) or len(n) < 2:
        return None
    if n[0] is not True:
        return None
    date_str = n[1] if isinstance(n[1], str) else None
    if not date_str:
        return None
    # Month-name day pattern: "Jul 20", "December 5"
    date_str = date_str.strip()
    free_until: _date | None = None
    for fmt in ("%b %d", "%B %d", "%b %d %Y", "%B %d %Y"):
        try:
            parsed = _dt_cls.strptime(date_str, fmt)
            if parsed.year == 1900:
                today = _date.today()
                parsed = parsed.replace(year=today.year)
                if parsed.date() < today:
                    parsed = parsed.replace(year=today.year + 1)
            free_until = parsed.date()
            break
        except ValueError:
            continue
    if free_until is None:
        return None
    description = f"Free cancellation until {date_str}"
    if len(n) > 2 and isinstance(n[2], str):
        description += f" {n[2].strip()}"
    return CancellationPolicy(
        kind=CancellationPolicyKind.FREE_UNTIL_DATE,
        free_until=free_until,
        description=description,
    )


def _cancel_from_rate_slot(cancel_raw: Any) -> CancellationPolicy:
    """Convert a rate-level cancel slot to a CancellationPolicy.

    Google encodes:
      [True, "Jul 20", "11:59 PM"] → free cancellation until that date
      [False] or [False, ...]       → no free cancellation (non-refundable)
    """
    if isinstance(cancel_raw, list) and cancel_raw:
        if cancel_raw[0] is True:
            result = _parse_cancellation_tuple(cancel_raw)
            if result is not None:
                return result
        # [False, ...] → explicitly no free cancellation
        return CancellationPolicy(kind=CancellationPolicyKind.NON_REFUNDABLE)
    return CancellationPolicy()


def _parse_provider_rate(entry: Any, currency: str) -> RatePlan | None:
    """Extract a RatePlan from a provider entry in the detail RPC response.

    Strategy (matches what Google shows in the list-view per provider):
    1. Provider name and deeplink come from the header element (entry[0]).
    2. Prices and cancellation come from room-rate entries in entry[7].
       Each rate option has (price, cancel_flag) paired together. We take
       the CHEAPEST rate and use THAT rate's own cancellation policy.
    3. Falls back to the header price integer if no room-rate block is found.
    """
    if not isinstance(entry, list) or not entry:
        return None

    # --- Header: provider name + deeplink at entry[0] ---
    header = entry[0] if isinstance(entry[0], list) else []
    provider: str | None = header[0] if header and isinstance(header[0], str) else None
    deeplink_raw: str | None = (
        header[2] if len(header) > 2 and isinstance(header[2], str) and header[2].startswith("/") else None
    )
    deeplink = ("https://www.google.com" + deeplink_raw) if deeplink_raw else None
    # Fallback header price (used only if room block parsing yields nothing)
    header_price: int | None = None
    for elem in header:
        if isinstance(elem, int) and 20 <= elem <= 100000:
            header_price = elem
            break

    if provider is None:
        return None

    # --- Rooms block: scan for first list element that contains room entries ---
    # Room entries are lists whose first element is a room-name string.
    rooms_block: list | None = None
    for idx in range(1, len(entry)):
        candidate = entry[idx]
        if (
            isinstance(candidate, list)
            and candidate
            and isinstance(candidate[0], list)
            and candidate[0]
            and isinstance(candidate[0][0], str)
        ):
            rooms_block = candidate
            break

    # --- Find cheapest rate across all rooms + rate tiers ---
    best_price: int | None = None
    best_cancellation: CancellationPolicy = CancellationPolicy()

    if rooms_block:
        for room in rooms_block:
            if not isinstance(room, list) or len(room) < 3:
                continue
            rates_list = room[2] if isinstance(room[2], list) else []
            for rate in rates_list:
                if not isinstance(rate, list) or len(rate) < 5:
                    continue
                price_info = rate[4]
                if not isinstance(price_info, list) or len(price_info) < 5:
                    continue
                per_night = price_info[4]
                if not isinstance(per_night, int) or not (20 <= per_night <= 100000):
                    continue
                if best_price is None or per_night < best_price:
                    best_price = per_night
                    best_cancellation = _cancel_from_rate_slot(rate[2] if len(rate) > 2 else None)

    price = best_price if best_price is not None else header_price
    if price is None:
        return None

    return RatePlan(
        provider=provider,
        price=price,
        currency=currency,
        cancellation=best_cancellation,
        deeplink_url=deeplink,
    )


def _parse_review_entry(entry: Any) -> Review | None:
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
