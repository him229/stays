"""Named constants for Google Hotels response slot indices.

Use `safe_get(tree, *path, default=None)` to walk named paths safely.
Populate constants progressively as each parser is extracted.
"""

from __future__ import annotations

from typing import Any, TypeAlias

__all__ = [
    "safe_get",
    "Tree",
    "HotelEntryRaw",
    "ProviderEntryRaw",
    # Provider / rate slots (detail RPC)
    "SLOT_PROVIDER_HEADER",
    "SLOT_HEADER_PROVIDER_NAME",
    "SLOT_HEADER_DEEPLINK",
    "SLOT_RATE_CANCEL",
    "SLOT_RATE_PRICE_INFO",
    "SLOT_RATE_PRICE_NIGHT",
    "SLOT_ROOM_RATES",
    # Hotel-entry slots used by the search walker (relative to entry root)
    "SLOT_ENTRY_COORDS",
    "SLOT_ENTRY_PRICE_PAIR",
    "SLOT_ENTRY_PRICE_CURRENCY",
    "SLOT_ENTRY_PRICE_DATES",
    "SLOT_ENTRY_DISPLAY_PRICE_NUM",
    # Nearby-place sub-tuple (relative to a visit() node)
    "SLOT_NEARBY_MODE_ID",
    "SLOT_NEARBY_DURATION",
    # Detail-mode slots (relative to entry root)
    "SLOT_ADDRESS",
    "SLOT_PHONE",
    "SLOT_PROVIDER_BLOCK",
    "SLOT_PROVIDER_LIST",
    "SLOT_REVIEWS_LIST",
    "SLOT_AMENITY_DETAILS",
    "SLOT_DESCRIPTION",
    # Price sanity range used as an int-detection heuristic
    "PRICE_RANGE_MIN",
    "PRICE_RANGE_MAX",
]

Tree: TypeAlias = list[Any] | dict[str, Any] | None
HotelEntryRaw: TypeAlias = list[Any]
ProviderEntryRaw: TypeAlias = list[Any]


def safe_get(tree: Any, *path: int, default: Any = None) -> Any:
    """Walk *path* indices through *tree*; return *default* if any step fails."""
    cur: Any = tree
    for idx in path:
        try:
            cur = cur[idx]
        except (IndexError, TypeError, KeyError):
            return default
    return cur


# ---------------------------------------------------------------------------
# Provider / rate slots — used by provider_parser.py
# ---------------------------------------------------------------------------

# Provider entry layout (entry): [header, ...rooms-blocks...]
#   entry[0]  → provider header row
#   entry[>=1] → room lists (first list-of-list-with-string-head wins)
SLOT_PROVIDER_HEADER = (0,)

# Header row layout (header): [provider_name, ?, deeplink_path, ... price ...]
SLOT_HEADER_PROVIDER_NAME = (0,)
SLOT_HEADER_DEEPLINK = (2,)

# Per-rate layout inside a room's rates list:
#   rate[2] → cancellation tuple (see policy_parser / _cancel_from_rate_slot)
#   rate[4] → price_info block; price_info[4] → per-night int
SLOT_RATE_CANCEL = (2,)
SLOT_RATE_PRICE_INFO = (4,)
SLOT_RATE_PRICE_NIGHT = (4, 4)

# Inside a room: room[2] is the list of rate options.
SLOT_ROOM_RATES = (2,)

# Integer heuristic for "looks like a price" — used when the slot layout is
# ambiguous (e.g. walking a header row for a fallback price).
PRICE_RANGE_MIN = 20
PRICE_RANGE_MAX = 100_000


# ---------------------------------------------------------------------------
# Hotel-entry (list-view + shared) slots — used by search_parser.py
# ---------------------------------------------------------------------------

# Inside a hotel entry (48-slot list):
#   entry[2][0]            → [lat, lng] float pair
#   entry[6][1][0]         → [price, 0] pair (fallback cheapest price)
#   entry[6][1][3]         → currency string
#   entry[6][1][4]         → [[Y,M,D], [Y,M,D]] rate-date window
#   entry[6][2][1][4]      → display_num (list-view UI price)
SLOT_ENTRY_COORDS = (2, 0)
SLOT_ENTRY_PRICE_PAIR = (6, 1, 0)
SLOT_ENTRY_PRICE_CURRENCY = (6, 1, 3)
SLOT_ENTRY_PRICE_DATES = (6, 1, 4)
SLOT_ENTRY_DISPLAY_PRICE_NUM = (6, 2, 1, 4)

# Nearby-place tuple path (relative to the candidate visit node):
#   node[2][0][0] → mode_id (int)
#   node[2][0][1] → duration string ("12 min")
SLOT_NEARBY_MODE_ID = (2, 0, 0)
SLOT_NEARBY_DURATION = (2, 0, 1)


# ---------------------------------------------------------------------------
# Detail-mode slots — used by detail_parser.py
# ---------------------------------------------------------------------------

# Inside a hotel entry (48-slot list):
#   entry[2][1][0][0][0] → street address string
#   entry[2][2][0]       → phone string
#   entry[6][2]          → provider-block (index [2] is the provider list)
#   entry[7][3]          → reviews sample
#   entry[10]            → amenity-detail subtree
#   entry[11][0]         → description (short)
SLOT_ADDRESS = (2, 1, 0, 0, 0)
SLOT_PHONE = (2, 2, 0)
SLOT_PROVIDER_BLOCK = (6, 2)
SLOT_PROVIDER_LIST = (6, 2, 2)
SLOT_REVIEWS_LIST = (7, 3)
SLOT_AMENITY_DETAILS = (10,)
SLOT_DESCRIPTION = (11, 0)
