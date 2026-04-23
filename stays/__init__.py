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
# succeed in normal installs. Guarded defensively against a corrupted
# install or a user who manually uninstalled a transitive MCP dep; catches
# both ModuleNotFoundError (module missing) and ImportError (name missing
# inside an existing module, e.g. when fastmcp's internal shape shifts).
try:
    from stays.mcp import (
        get_hotel_details,
        mcp,
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
        "mcp",
        "run_mcp",
        "run_mcp_http",
        "search_hotels",
        "search_hotels_with_details",
    ]
except ImportError:
    # Covers both ModuleNotFoundError (a dep is missing) and plain
    # ImportError (a name wasn't bound because an inner try/except
    # swallowed the failure). Library-only usage (`from stays import
    # HotelSearchFilters`) keeps working either way.
    pass
