"""Google Hotels MCP Server.

Exposes ``stays.search.SearchHotels`` as an MCP server over stdio via
FastMCP: three tools (``search_hotels``, ``get_hotel_details``,
``search_hotels_with_details``), two prompts, one configuration resource.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from stays.models.google_hotels.base import (
    Amenity,
    Brand,
    Currency,
    DateRange,
    GuestInfo,
    Location,
    MinGuestRating,
    PropertyType,
    SortBy,
)
from stays.models.google_hotels.detail import HotelDetail
from stays.models.google_hotels.hotels import HotelSearchFilters
from stays.models.google_hotels.result import HotelResult
from stays.search.client import (
    BatchExecuteError,
    TransientBatchExecuteError,
)
from stays.search.hotels import MissingHotelIdError, SearchHotels

# =============================================================================
# Configuration
# =============================================================================


class HotelSearchConfig(BaseSettings):
    """Optional env-driven defaults for the Google Hotels MCP server."""

    model_config = SettingsConfigDict(env_prefix="STAYS_MCP_")

    default_adults: int = Field(2, ge=1, description="Default adult guests.")
    default_children: int = Field(0, ge=0, le=8, description="Default children count.")
    default_currency: str = Field("USD", min_length=3, max_length=3, description="Fallback currency code (ISO 4217).")
    default_max_hotels_with_details: int = Field(
        5,
        ge=1,
        le=15,
        description="Default N for search_hotels_with_details. HARD CAP 15.",
    )
    default_sort_by: str = Field(
        "RELEVANCE",
        description="RELEVANCE | LOWEST_PRICE | HIGHEST_RATING | MOST_REVIEWED.",
    )
    max_results: int | None = Field(
        None,
        gt=0,
        description="Optional cap on result count returned by search_hotels.",
    )


CONFIG = HotelSearchConfig()
CONFIG_SCHEMA = HotelSearchConfig.model_json_schema()

mcp = FastMCP("Google Hotels MCP Server")


# =============================================================================
# Typed enums — Literals give schema-level rejection in FastMCP
# =============================================================================


SortByLiteral = Literal["RELEVANCE", "LOWEST_PRICE", "HIGHEST_RATING", "MOST_REVIEWED"]
PropertyTypeLiteral = Literal["HOTELS", "VACATION_RENTALS"]


# =============================================================================
# Params models (used by tests via _execute_*_from_params)
# =============================================================================


class SearchHotelsParams(BaseModel):
    query: str = Field(description="City or property query.")
    check_in: str | None = Field(default=None, description="YYYY-MM-DD; omit for flexible dates.")
    check_out: str | None = Field(default=None, description="YYYY-MM-DD; required if check_in is set.")
    adults: int = Field(default=CONFIG.default_adults, ge=1)
    children: int = Field(default=CONFIG.default_children, ge=0, le=8)
    child_ages: list[int] | None = Field(default=None, description="Ages 0-17.")
    currency: str = Field(default=CONFIG.default_currency, min_length=3, max_length=3)
    sort_by: SortByLiteral = CONFIG.default_sort_by
    hotel_class: list[int] | None = None
    amenities: list[str] | None = None
    brands: list[str] | None = None
    min_guest_rating: float | None = Field(default=None, ge=3.5, le=4.5)
    free_cancellation: bool = False
    eco_certified: bool = False
    special_offers: bool = False
    price_min: int | None = Field(default=None, ge=0)
    price_max: int | None = Field(default=None, ge=0)
    property_type: PropertyTypeLiteral = "HOTELS"
    max_results: int | None = Field(default=None, ge=1, le=25, description="Cap on returned hotels count.")

    @model_validator(mode="after")
    def _child_ages_matches_children(self):
        if self.children > 0 and not self.child_ages:
            raise ValueError(
                f"child_ages is required when children > 0 (got children={self.children}, child_ages=None)"
            )
        if self.child_ages is not None and len(self.child_ages) != self.children:
            raise ValueError(f"child_ages length ({len(self.child_ages)}) must equal children ({self.children})")
        return self


class GetHotelDetailsParams(BaseModel):
    entity_key: str = Field(description="entity_key from a prior search_hotels result.")
    check_in: str = Field(description="YYYY-MM-DD.")
    check_out: str = Field(description="YYYY-MM-DD after check_in.")
    currency: str = Field(default=CONFIG.default_currency, min_length=3, max_length=3)


class SearchHotelsWithDetailsParams(BaseModel):
    query: str = Field(description="City or property query.")
    check_in: str = Field(description="YYYY-MM-DD — REQUIRED.")
    check_out: str = Field(description="YYYY-MM-DD after check_in — REQUIRED.")
    max_hotels: int = Field(
        default=CONFIG.default_max_hotels_with_details,
        ge=1,
        le=15,
        description="Top-N to enrich. HARD CAP = 15.",
    )
    adults: int = Field(default=CONFIG.default_adults, ge=1)
    children: int = Field(default=CONFIG.default_children, ge=0, le=8)
    child_ages: list[int] | None = Field(default=None)
    currency: str = Field(default=CONFIG.default_currency, min_length=3, max_length=3)
    sort_by: SortByLiteral = CONFIG.default_sort_by
    hotel_class: list[int] | None = None
    amenities: list[str] | None = None
    brands: list[str] | None = None
    min_guest_rating: float | None = Field(default=None, ge=3.5, le=4.5)
    free_cancellation: bool = False
    eco_certified: bool = False
    special_offers: bool = False
    price_min: int | None = Field(default=None, ge=0)
    price_max: int | None = Field(default=None, ge=0)
    property_type: PropertyTypeLiteral = "HOTELS"

    @model_validator(mode="after")
    def _child_ages_matches_children(self):
        if self.children > 0 and not self.child_ages:
            raise ValueError(
                f"child_ages is required when children > 0 (got children={self.children}, child_ages=None)"
            )
        if self.child_ages is not None and len(self.child_ages) != self.children:
            raise ValueError(f"child_ages length ({len(self.child_ages)}) must equal children ({self.children})")
        return self


# =============================================================================
# Serialization helpers — HotelResult / HotelDetail -> JSON-safe dicts
# =============================================================================


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _build_filters_from_search_params(p: SearchHotelsParams) -> HotelSearchFilters:
    dates = None
    if p.check_in and p.check_out:
        dates = DateRange(
            check_in=_parse_date(p.check_in),
            check_out=_parse_date(p.check_out),
        )
    guests = GuestInfo(
        adults=p.adults,
        children=p.children,
        child_ages=p.child_ages or [],
    )
    loc = Location(query=p.query)
    sort = None if p.sort_by == "RELEVANCE" else SortBy[p.sort_by]
    amen = [Amenity[a] for a in (p.amenities or [])]
    brands = [Brand[b] for b in (p.brands or [])]
    price_range = None
    if p.price_min is not None or p.price_max is not None:
        price_range = (p.price_min, p.price_max)
    mgr = None
    if p.min_guest_rating is not None:
        mgr = MinGuestRating(round(p.min_guest_rating * 2))
    return HotelSearchFilters(
        location=loc,
        dates=dates,
        guests=guests,
        currency=Currency[p.currency],
        property_type=PropertyType[p.property_type],
        sort_by=sort,
        hotel_class=p.hotel_class or [],
        min_guest_rating=mgr,
        amenities=amen,
        brands=brands,
        free_cancellation=p.free_cancellation,
        eco_certified=p.eco_certified,
        special_offers=p.special_offers,
        price_range=price_range,
    )


def _serialize_hotel_result(h: HotelResult) -> dict[str, Any]:
    return {
        "name": h.name,
        "entity_key": h.entity_key,
        "kgmid": h.kgmid,
        "fid": h.fid,
        "display_price": h.display_price,
        "currency": h.currency,
        "star_class": h.star_class,
        "overall_rating": h.overall_rating,
        "review_count": h.review_count,
        "amenities": sorted(a.name for a in h.amenities_available),
        "check_in_time": h.check_in_time,
        "check_out_time": h.check_out_time,
        "lat": h.latitude,
        "lng": h.longitude,
    }


def _serialize_rate_plan(rp) -> dict[str, Any]:
    return {
        "provider": rp.provider,
        "price": rp.price,
        "currency": rp.currency,
        "cancellation_kind": rp.cancellation.kind.value if rp.cancellation else None,
        "cancellation_free_until": (
            rp.cancellation.free_until.isoformat() if rp.cancellation and rp.cancellation.free_until else None
        ),
        "cancellation_description": rp.cancellation.description if rp.cancellation else None,
        "breakfast_included": rp.breakfast_included,
        "includes_taxes_and_fees": rp.includes_taxes_and_fees,
        "deeplink_url": rp.deeplink_url,
    }


def _serialize_room_type(r) -> dict[str, Any]:
    return {
        "name": r.name,
        "description": r.description,
        "bed_config": r.bed_config,
        "max_occupancy": r.max_occupancy,
        "rates": [_serialize_rate_plan(rp) for rp in r.rates],
    }


def _serialize_hotel_detail(d: HotelDetail) -> dict[str, Any]:
    base = _serialize_hotel_result(d)
    base.update(
        {
            "description": d.description,
            "address": d.address,
            "phone": d.phone,
            "amenity_details": d.amenity_details,
            "rooms": [_serialize_room_type(r) for r in d.rooms],
        }
    )
    return base


# =============================================================================
# Private execute entries (tests invoke these directly)
# =============================================================================


# Single canonical name — no aliases.
# Tests and tool wrappers both call *_from_params directly.


def _execute_search_hotels_from_params(params: SearchHotelsParams) -> dict[str, Any]:
    try:
        filters = _build_filters_from_search_params(params)
        hotels = SearchHotels().search(filters)
        cap = params.max_results if params.max_results is not None else CONFIG.max_results
        if cap is not None:
            hotels = hotels[:cap]
        return {
            "success": True,
            "count": len(hotels),
            "hotels": [_serialize_hotel_result(h) for h in hotels],
        }
    except (BatchExecuteError, TransientBatchExecuteError) as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}", "hotels": []}


def _execute_get_hotel_details_from_params(params: GetHotelDetailsParams) -> dict[str, Any]:
    try:
        dates = DateRange(
            check_in=_parse_date(params.check_in),
            check_out=_parse_date(params.check_out),
        )
        detail = SearchHotels().get_details(
            entity_key=params.entity_key,
            dates=dates,
            currency=Currency[params.currency],
        )
        return {"success": True, "hotel": _serialize_hotel_detail(detail)}
    except MissingHotelIdError as e:
        return {"success": False, "error": f"MissingHotelIdError: {e}", "hotel": None}
    except (BatchExecuteError, TransientBatchExecuteError) as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}", "hotel": None}


def _execute_search_hotels_with_details_from_params(
    params: SearchHotelsWithDetailsParams,
) -> dict[str, Any]:
    try:
        shp = SearchHotelsParams(**params.model_dump(exclude={"max_hotels"}))
        filters = _build_filters_from_search_params(shp)
        enriched = SearchHotels().search_with_details(filters, max_hotels=params.max_hotels)
        items = []
        for er in enriched:
            items.append(
                {
                    "ok": er.ok,
                    "result": _serialize_hotel_result(er.result),
                    "detail": _serialize_hotel_detail(er.detail) if er.detail else None,
                    "error": er.error,
                }
            )
        return {"success": True, "count": len(items), "items": items}
    except (BatchExecuteError, TransientBatchExecuteError) as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}", "items": []}


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


@mcp.tool(
    annotations={
        "title": "Search Hotels With Details",
        "readOnlyHint": True,
        "idempotentHint": True,
    }
)
def search_hotels_with_details(
    query: Annotated[str, Field()],
    check_in: Annotated[str, Field()],
    check_out: Annotated[str, Field()],
    max_hotels: Annotated[
        int,
        Field(ge=1, le=15, description="Top-N hotels to enrich with detail. Hard cap = 15. Default 5."),
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
    """Search + parallel detail fetch for the top N hotels in one call.

    Use when the user wants to COMPARE rooms, rates, or cancellation
    policies across multiple hotels. Costs 1 + N RPCs. max_hotels is
    HARD-CAPPED at 15.
    """
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
        "  is typical; 10 is the hard maximum).\n"
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
    max_hotels = min(max_hotels, 15)
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
                "STAYS_MCP_DEFAULT_MAX_HOTELS_WITH_DETAILS": "Default N (hard cap 15).",
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
