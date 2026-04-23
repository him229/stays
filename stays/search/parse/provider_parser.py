"""Provider / rate parsers for the detail RPC response.

Each provider entry in the detail response carries a header row (provider
name + deeplink) followed by one or more room-rate blocks. We pick the
CHEAPEST rate across all rooms and surface its per-rate cancellation
policy.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime as _dt_cls

from stays.models.google_hotels.detail import RatePlan
from stays.models.google_hotels.policy import (
    CancellationPolicy,
    CancellationPolicyKind,
)
from stays.search.parse.slots import (
    PRICE_RANGE_MAX,
    PRICE_RANGE_MIN,
    SLOT_HEADER_DEEPLINK,
    SLOT_HEADER_PROVIDER_NAME,
    SLOT_PROVIDER_HEADER,
    SLOT_RATE_CANCEL,
    SLOT_RATE_PRICE_INFO,
    SLOT_RATE_PRICE_NIGHT,
    SLOT_ROOM_RATES,
    ProviderEntryRaw,
    Tree,
    safe_get,
)

__all__ = [
    "_parse_provider_rate",
    "_parse_cancellation_tuple",
    "_cancel_from_rate_slot",
]


def _parse_cancellation_tuple(n: Tree) -> CancellationPolicy | None:
    """Detect Google's structured cancellation tuple: [bool, date_str, time_str].

    Google encodes per-rate cancellation as a list where:
      [True, "Jul 20", "11:59 PM"]  → free cancellation until Jul 20
      [False]                        → no free cancellation
    Only fires when the first element is True with a valid month-day string.
    """
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


def _cancel_from_rate_slot(cancel_raw: Tree) -> CancellationPolicy:
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


def _parse_provider_rate(entry: ProviderEntryRaw, currency: str) -> RatePlan | None:
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

    # --- Header: provider name + deeplink at SLOT_PROVIDER_HEADER (entry[0]) ---
    header_raw = safe_get(entry, *SLOT_PROVIDER_HEADER)
    header: list = header_raw if isinstance(header_raw, list) else []
    provider_raw = safe_get(entry, *SLOT_PROVIDER_HEADER, *SLOT_HEADER_PROVIDER_NAME)
    provider: str | None = provider_raw if isinstance(provider_raw, str) else None
    deeplink_raw_val = safe_get(entry, *SLOT_PROVIDER_HEADER, *SLOT_HEADER_DEEPLINK)
    deeplink_raw: str | None = (
        deeplink_raw_val if isinstance(deeplink_raw_val, str) and deeplink_raw_val.startswith("/") else None
    )
    deeplink = ("https://www.google.com" + deeplink_raw) if deeplink_raw else None
    # Fallback header price (used only if room block parsing yields nothing)
    header_price: int | None = None
    for elem in header:
        if isinstance(elem, int) and PRICE_RANGE_MIN <= elem <= PRICE_RANGE_MAX:
            header_price = elem
            break

    if provider is None:
        return None

    # --- Rooms block: scan for first list element that contains room entries ---
    # Room entries are lists whose first element is a room-name string.
    # The deep guard uses safe_get to sniff a (candidate, 0, 0) -> str.
    rooms_block: list | None = None
    for idx in range(1, len(entry)):
        candidate = entry[idx]
        if not isinstance(candidate, list) or not candidate:
            continue
        first_name = safe_get(candidate, 0, 0)
        if isinstance(first_name, str):
            rooms_block = candidate
            break

    # --- Find cheapest rate across all rooms + rate tiers ---
    best_price: int | None = None
    best_cancellation: CancellationPolicy = CancellationPolicy()

    if rooms_block:
        for room in rooms_block:
            if not isinstance(room, list) or len(room) < 3:
                continue
            rates_list = safe_get(room, *SLOT_ROOM_RATES, default=[])
            if not isinstance(rates_list, list):
                rates_list = []
            for rate in rates_list:
                if not isinstance(rate, list) or len(rate) < 5:
                    continue
                price_info = safe_get(rate, *SLOT_RATE_PRICE_INFO)
                if not isinstance(price_info, list) or len(price_info) < 5:
                    continue
                per_night = safe_get(rate, *SLOT_RATE_PRICE_NIGHT)
                if not isinstance(per_night, int) or not (PRICE_RANGE_MIN <= per_night <= PRICE_RANGE_MAX):
                    continue
                if best_price is None or per_night < best_price:
                    best_price = per_night
                    best_cancellation = _cancel_from_rate_slot(safe_get(rate, *SLOT_RATE_CANCEL))

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
