"""MCP module for stays.

The server runtime (fastmcp / fastapi / uvicorn / pydantic-settings) is
shipped in the core package as of 0.1.0, so these names are normally
available after a plain ``pip install stays``. The try/except below
keeps imports from raising when a user has deliberately pruned the
runtime (unusual, but we don't want to break ``from stays.mcp import`` at
module load time).
"""

try:
    from stays.mcp.server import (
        GetHotelDetailsParams,
        HotelSearchConfig,
        SearchHotelsParams,
        SearchHotelsWithDetailsParams,
        get_hotel_details,
        mcp,
        run,
        run_http,
        search_hotels,
        search_hotels_with_details,
    )

    __all__ = [
        "GetHotelDetailsParams",
        "HotelSearchConfig",
        "SearchHotelsParams",
        "SearchHotelsWithDetailsParams",
        "get_hotel_details",
        "mcp",
        "run",
        "run_http",
        "search_hotels",
        "search_hotels_with_details",
    ]
except ModuleNotFoundError:
    __all__: list[str] = []
