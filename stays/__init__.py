"""stays — Google Hotels/Travel search client.

Reverse-engineered ``batchexecute`` client with an MCP-compatible surface
(three tools, two prompts, one configuration resource). The public
package surface re-exports filters, result models, and the MCP entry
points so callers can write ``from stays import SearchHotels``.
"""

from stays.models.google_hotels import (
    Amenity,
    Brand,
    Currency,
    DateRange,
    GuestInfo,
    HotelSearchFilters,
    Location,
    MinGuestRating,
    PropertyType,
    SortBy,
)
from stays.models.google_hotels.detail import (
    HotelDetail,
    RatePlan,
    Review,
    RoomType,
)

# models
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

# search
from stays.search import (
    BatchExecuteError,
    Client,
    EnrichedResult,
    MissingHotelIdError,
    SearchHotels,
    TransientBatchExecuteError,
)

__all__ = [
    "Amenity",
    "BatchExecuteError",
    "Brand",
    "CancellationPolicy",
    "CancellationPolicyKind",
    "CategoryRating",
    "Client",
    "Currency",
    "DateRange",
    "EnrichedResult",
    "GuestInfo",
    "HotelDetail",
    "HotelResult",
    "HotelSearchFilters",
    "Location",
    "MinGuestRating",
    "MissingHotelIdError",
    "NearbyPlace",
    "PropertyType",
    "RatePlan",
    "RatingHistogram",
    "Review",
    "RoomType",
    "SearchHotels",
    "SortBy",
    "TransientBatchExecuteError",
]

# MCP surface — shipped in core since 0.1.0, so this import should always
# succeed in normal installs. The ONLY expected failure mode is a user
# who manually uninstalled the optional ``fastmcp`` runtime; everything
# else (broken stays.mcp module, ImportError for names we control, etc.)
# must surface loudly rather than be silently swallowed.
#
# We deliberately do NOT re-export the ``mcp`` FastMCP instance here: it
# would shadow the ``stays.mcp`` subpackage on the ``stays`` namespace,
# which breaks Python 3.10's ``unittest.mock.patch`` dotted-path lookup
# (3.11+ recovers; 3.10 does not). Callers that need the FastMCP object
# can still reach it at ``stays.mcp.mcp``.
_OPTIONAL_MCP_DEPS = frozenset({"fastmcp"})
try:
    from stays.mcp import (
        get_hotel_details,
        search_hotels,
        search_hotels_with_details,
    )
    from stays.mcp import (
        run as run_mcp,
    )
    from stays.mcp import (
        run_http as run_mcp_http,
    )

    __all__ += [
        "get_hotel_details",
        "run_mcp",
        "run_mcp_http",
        "search_hotels",
        "search_hotels_with_details",
    ]
except ModuleNotFoundError as exc:
    # Only swallow the failure when the missing module is a known-optional
    # MCP runtime dep (``fastmcp``). Any other missing module — including
    # one of our own ``stays.*`` submodules — means the install is broken
    # and should raise rather than leave callers with a silently-empty
    # public surface.
    if exc.name not in _OPTIONAL_MCP_DEPS:
        raise
