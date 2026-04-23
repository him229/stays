"""Google Hotels MCP Server.

Exposes ``stays.search.SearchHotels`` as an MCP server over stdio via
FastMCP: three tools (``search_hotels``, ``get_hotel_details``,
``search_hotels_with_details``), two prompts, one configuration resource.

Module layout:
- ``_config.py`` — pydantic-settings ``CONFIG`` + JSON schema + hard caps.
- ``_params.py`` — pydantic param models (one per tool) + shared validators.
- ``_executors.py`` — ``_execute_*_from_params`` functions + serializers.
- ``server.py`` (this file) — registration surface: ``FastMCP`` instance
  plus ``@mcp.tool`` / ``@mcp.prompt`` / ``@mcp.resource`` decorators.

Every name historically importable from ``stays.mcp.server`` is re-exported
here so existing tests continue to resolve.
"""

from __future__ import annotations

import json
import os
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from stays.mcp._config import (
    CONFIG,
    CONFIG_SCHEMA,
    HARD_MAX_HOTELS_WITH_DETAILS,
    HotelSearchConfig,
)
from stays.mcp._executors import (
    _MCP_DETAIL_DROP_KEYS,
    _MCP_RESULT_DROP_KEYS,
    _apply_mcp_coordinate_aliases,
    _build_filters_from_search_params,
    _execute_get_hotel_details_from_params,
    _execute_search_hotels_from_params,
    _execute_search_hotels_with_details_from_params,
    _parse_date,
    _serialize_hotel_detail,
    _serialize_hotel_result,
    _serialize_rate_plan,
    _serialize_room_type,
)
from stays.mcp._params import (
    GetHotelDetailsParams,
    PropertyTypeLiteral,
    SearchHotelsParams,
    SearchHotelsWithDetailsParams,
    SortByLiteral,
)
from stays.search.hotels import MissingHotelIdError, SearchHotels

# Re-exported for test compatibility — some tests ``patch("stays.mcp.server.SearchHotels")``.
__all__ = [
    "CONFIG",
    "CONFIG_SCHEMA",
    "GetHotelDetailsParams",
    "HARD_MAX_HOTELS_WITH_DETAILS",
    "HotelSearchConfig",
    "MissingHotelIdError",
    "PropertyTypeLiteral",
    "SearchHotels",
    "SearchHotelsParams",
    "SearchHotelsWithDetailsParams",
    "SortByLiteral",
    "_MCP_DETAIL_DROP_KEYS",
    "_MCP_RESULT_DROP_KEYS",
    "_apply_mcp_coordinate_aliases",
    "_build_filters_from_search_params",
    "_execute_get_hotel_details_from_params",
    "_execute_search_hotels_from_params",
    "_execute_search_hotels_with_details_from_params",
    "_parse_date",
    "_serialize_hotel_detail",
    "_serialize_hotel_result",
    "_serialize_rate_plan",
    "_serialize_room_type",
    "configuration_resource",
    "compare_hotels_in_city_prompt",
    "get_hotel_details",
    "mcp",
    "run",
    "run_http",
    "search_hotels",
    "search_hotels_with_details",
    "when_to_deep_search_prompt",
]

mcp = FastMCP("Google Hotels MCP Server")


# =============================================================================
# MCP Tools
# =============================================================================


@mcp.tool(
    annotations={
        "title": "Search Hotels",
        "readOnlyHint": True,
        "idempotentHint": True,
    }
)
def search_hotels(
    query: Annotated[str, Field(description="City or property query, e.g. 'hotels in Paris' or 'Hilton Tokyo'.")],
    check_in: Annotated[str | None, Field(description="Check-in date YYYY-MM-DD. Omit for flexible dates.")] = None,
    check_out: Annotated[
        str | None, Field(description="Check-out date YYYY-MM-DD. Required when check_in is set.")
    ] = None,
    adults: Annotated[int, Field(ge=1, description="Number of adult guests.")] = CONFIG.default_adults,
    children: Annotated[
        int, Field(ge=0, le=8, description="Number of children. Provide child_ages when > 0.")
    ] = CONFIG.default_children,
    child_ages: Annotated[list[int] | None, Field(description="One age (0-17) per child.")] = None,
    currency: Annotated[
        str,
        Field(
            min_length=3,
            max_length=3,
            description="ISO 4217 currency code, e.g. 'USD', 'EUR', 'GBP'.",
        ),
    ] = CONFIG.default_currency,
    sort_by: Annotated[
        SortByLiteral,
        Field(description="Sort order: RELEVANCE (default), LOWEST_PRICE, HIGHEST_RATING, MOST_REVIEWED."),
    ] = CONFIG.default_sort_by,
    hotel_class: Annotated[
        list[int] | None,
        Field(description="Star classes to include, e.g. [4, 5] for luxury. Each value 1-5."),
    ] = None,
    amenities: Annotated[
        list[str] | None,
        Field(
            description="Amenity filter names, e.g. ['WIFI', 'POOL', 'GYM', 'SPA', 'PARKING', 'BREAKFAST', 'PET_FRIENDLY']."
        ),
    ] = None,
    brands: Annotated[
        list[str] | None,
        Field(description="Brand family filters, e.g. ['HILTON', 'MARRIOTT', 'HYATT', 'IHG', 'ACCOR']."),
    ] = None,
    min_guest_rating: Annotated[
        float | None,
        Field(ge=3.5, le=4.5, description="Minimum guest rating. Use 3.5, 4.0, or 4.5."),
    ] = None,
    free_cancellation: Annotated[
        bool,
        Field(
            description="Only show hotels with free cancellation. Use when the user asks for 'refundable', 'flexible booking', 'cancel anytime', or 'free cancellation'."
        ),
    ] = False,
    eco_certified: Annotated[bool, Field(description="Filter to Google eco-certified properties only.")] = False,
    special_offers: Annotated[bool, Field(description="Only show hotels with current deals or member rates.")] = False,
    price_min: Annotated[
        int | None, Field(ge=0, description="Minimum per-night price in the selected currency.")
    ] = None,
    price_max: Annotated[
        int | None, Field(ge=0, description="Maximum per-night price in the selected currency.")
    ] = None,
    property_type: Annotated[
        PropertyTypeLiteral, Field(description="HOTELS (default) or VACATION_RENTALS.")
    ] = "HOTELS",
    max_results: Annotated[
        int | None,
        Field(
            ge=1,
            le=25,
            description="Cap the number of hotels returned. Omit to return all Google surfaces (typically 15-18).",
        ),
    ] = None,
) -> dict[str, Any]:
    """Fast list-view hotel search. USE THIS FIRST to discover hotels.

    Returns name, price, rating, star class, amenities, check-in/out times,
    and an entity_key for each hotel. Prefer this over
    search_hotels_with_details unless the user explicitly asks for
    room/rate/cancellation detail. One RPC. entity_key values here are
    inputs to get_hotel_details.

    Common filter triggers:
    - 'free cancellation' / 'refundable' → free_cancellation=True
    - 'budget' / 'cheap' → sort_by='LOWEST_PRICE' or price_max=N
    - 'luxury' / '5-star' → hotel_class=[5]
    - 'family' / 'kid-friendly' → amenities=['KID_FRIENDLY']
    - 'pet-friendly' / 'dogs allowed' → amenities=['PET_FRIENDLY']
    - 'pool' → amenities=['POOL'] or ['INDOOR_POOL'] or ['OUTDOOR_POOL']
    - 'wheelchair' / 'accessible' → amenities=['WHEELCHAIR_ACCESSIBLE']
    - 'eco' / 'sustainable' → eco_certified=True
    """
    params = SearchHotelsParams(
        query=query,
        check_in=check_in,
        check_out=check_out,
        adults=adults,
        children=children,
        child_ages=child_ages,
        currency=currency,
        sort_by=sort_by,
        hotel_class=hotel_class,
        amenities=amenities,
        brands=brands,
        min_guest_rating=min_guest_rating,
        free_cancellation=free_cancellation,
        eco_certified=eco_certified,
        special_offers=special_offers,
        price_min=price_min,
        price_max=price_max,
        property_type=property_type,
        max_results=max_results,
    )
    return _execute_search_hotels_from_params(params)


@mcp.tool(
    annotations={
        "title": "Get Hotel Details",
        "readOnlyHint": True,
        "idempotentHint": True,
    }
)
def get_hotel_details(
    entity_key: Annotated[str, Field()],
    check_in: Annotated[str, Field()],
    check_out: Annotated[str, Field()],
    currency: Annotated[str, Field(min_length=3, max_length=3)] = CONFIG.default_currency,
) -> dict[str, Any]:
    """Deep detail for ONE hotel. Requires entity_key from search_hotels.

    Returns rooms, per-OTA rate plans with prices, and cancellation
    policies. One RPC. For multi-hotel deep comparison use
    search_hotels_with_details instead.
    """
    params = GetHotelDetailsParams(
        entity_key=entity_key,
        check_in=check_in,
        check_out=check_out,
        currency=currency,
    )
    return _execute_get_hotel_details_from_params(params)


def _search_hotels_with_details_impl(
    query: Annotated[str, Field()],
    check_in: Annotated[str, Field()],
    check_out: Annotated[str, Field()],
    max_hotels: Annotated[
        int,
        Field(
            ge=1,
            le=HARD_MAX_HOTELS_WITH_DETAILS,
            description=(f"Top-N hotels to enrich with detail. Hard cap = {HARD_MAX_HOTELS_WITH_DETAILS}. Default 5."),
        ),
    ] = CONFIG.default_max_hotels_with_details,
    adults: Annotated[int, Field(ge=1)] = CONFIG.default_adults,
    children: Annotated[int, Field(ge=0, le=8)] = CONFIG.default_children,
    child_ages: Annotated[list[int] | None, Field()] = None,
    currency: Annotated[str, Field(min_length=3, max_length=3)] = CONFIG.default_currency,
    sort_by: Annotated[SortByLiteral, Field()] = CONFIG.default_sort_by,
    hotel_class: Annotated[list[int] | None, Field()] = None,
    amenities: Annotated[list[str] | None, Field()] = None,
    brands: Annotated[list[str] | None, Field()] = None,
    min_guest_rating: Annotated[float | None, Field(ge=3.5, le=4.5)] = None,
    free_cancellation: bool = False,
    eco_certified: bool = False,
    special_offers: bool = False,
    price_min: Annotated[int | None, Field(ge=0)] = None,
    price_max: Annotated[int | None, Field(ge=0)] = None,
    property_type: Annotated[PropertyTypeLiteral, Field()] = "HOTELS",
) -> dict[str, Any]:
    """placeholder — overwritten via __doc__ assignment below."""
    params = SearchHotelsWithDetailsParams(
        query=query,
        check_in=check_in,
        check_out=check_out,
        max_hotels=max_hotels,
        adults=adults,
        children=children,
        child_ages=child_ages,
        currency=currency,
        sort_by=sort_by,
        hotel_class=hotel_class,
        amenities=amenities,
        brands=brands,
        min_guest_rating=min_guest_rating,
        free_cancellation=free_cancellation,
        eco_certified=eco_certified,
        special_offers=special_offers,
        price_min=price_min,
        price_max=price_max,
        property_type=property_type,
    )
    return _execute_search_hotels_with_details_from_params(params)


# Assign the real docstring via f-string expansion so the HARD-CAPPED number
# stays in sync with HARD_MAX_HOTELS_WITH_DETAILS. Python does not evaluate a
# leading f-string as __doc__, so we set it explicitly BEFORE ``@mcp.tool``
# captures it at decoration time. test_tool_docstring_matches_hard_max_constant
# locks this invariant. We also rewrite __name__/__qualname__ so FastMCP's
# introspection sees the public tool name rather than the _impl helper.
_search_hotels_with_details_impl.__doc__ = f"""Search + parallel detail fetch for the top N hotels in one call.

Use when the user wants to COMPARE rooms, rates, or cancellation
policies across multiple hotels. Costs 1 + N RPCs. max_hotels is
HARD-CAPPED at {HARD_MAX_HOTELS_WITH_DETAILS}.
"""
_search_hotels_with_details_impl.__name__ = "search_hotels_with_details"
_search_hotels_with_details_impl.__qualname__ = "search_hotels_with_details"

search_hotels_with_details = mcp.tool(
    name="search_hotels_with_details",
    annotations={
        "title": "Search Hotels With Details",
        "readOnlyHint": True,
        "idempotentHint": True,
    },
)(_search_hotels_with_details_impl)


# =============================================================================
# Prompts
# =============================================================================


@mcp.prompt(
    name="when-to-deep-search",
    description="Guidance on choosing between search_hotels and search_hotels_with_details.",
)
def when_to_deep_search_prompt(user_intent: str = "") -> str:
    return (
        "Decide how to query Google Hotels:\n"
        "- Call `search_hotels` for browsing, filtering by price/stars, or any\n"
        "  question the user asks about a CITY or area.\n"
        "- Call `get_hotel_details` when the user has already chosen ONE hotel\n"
        "  and wants rooms / rates / cancellation info (you need an entity_key).\n"
        "- Call `search_hotels_with_details` ONLY when the user wants to COMPARE\n"
        "  rooms/rates/cancellation across SEVERAL hotels at once. Set\n"
        "  `max_hotels` to the smallest number that satisfies the ask (3-5\n"
        f"  is typical; {HARD_MAX_HOTELS_WITH_DETAILS} is the hard maximum).\n"
        f"User intent: {user_intent or '(unspecified)'}"
    )


@mcp.prompt(
    name="compare-hotels-in-city",
    description="Example workflow: find 5 top-rated hotels in a city and compare their rates.",
)
def compare_hotels_in_city_prompt(
    city: str,
    check_in: str,
    check_out: str,
    max_hotels: int = 5,
) -> str:
    max_hotels = min(max_hotels, HARD_MAX_HOTELS_WITH_DETAILS)
    return (
        f"Use `search_hotels_with_details` with query='{city} hotels', "
        f"check_in='{check_in}', check_out='{check_out}', max_hotels={max_hotels}. "
        "Present each result as a row: name, star class, price, cheapest rate, "
        "cancellation policy."
    )


# =============================================================================
# Resource
# =============================================================================


@mcp.resource(
    "resource://stays-mcp/configuration",
    name="Stays MCP Configuration",
    description="Defaults + env vars for the Google Hotels MCP server.",
    mime_type="application/json",
)
def configuration_resource() -> str:
    payload = {
        "defaults": CONFIG.model_dump(),
        "schema": CONFIG_SCHEMA,
        "environment": {
            "prefix": "STAYS_MCP_",
            "variables": {
                "STAYS_MCP_DEFAULT_ADULTS": "Adjust default adult count.",
                "STAYS_MCP_DEFAULT_CURRENCY": "Fallback currency code.",
                "STAYS_MCP_DEFAULT_MAX_HOTELS_WITH_DETAILS": (f"Default N (hard cap {HARD_MAX_HOTELS_WITH_DETAILS})."),
                "STAYS_MCP_DEFAULT_SORT_BY": "Default sort strategy.",
                "STAYS_MCP_MAX_RESULTS": "Cap returned result count.",
                "STAYS_RPS": "Override rate-limiter calls/sec (default 10).",
            },
        },
    }
    return json.dumps(payload, indent=2)


# =============================================================================
# Entry points
# =============================================================================


def run() -> None:
    """Run the MCP server on stdio."""
    mcp.run(transport="stdio")


def run_http(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the MCP server over HTTP — local dev only."""
    env_host = os.getenv("HOST")
    env_port = os.getenv("PORT")
    bind_host = env_host if env_host else host
    bind_port = int(env_port) if env_port else port
    mcp.run(transport="http", host=bind_host, port=bind_port)


if __name__ == "__main__":
    run()
