"""Executor functions for the Google Hotels MCP server.

The MCP ``@mcp.tool`` wrappers in ``server.py`` are thin adapters — they
collect argument defaults, build a pydantic params object, and then delegate
to one of the three ``_execute_*_from_params`` functions here.

Every name is re-exported from ``stays.mcp.server`` so existing tests that do
``from stays.mcp.server import _execute_*`` keep resolving. Tests also do
``patch("stays.mcp.server.SearchHotels")`` to swap the client — so the
executors look up ``SearchHotels`` *through* the ``server`` module at call
time rather than holding a bound reference here.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from stays.mcp._config import CONFIG
from stays.mcp._params import (
    GetHotelDetailsParams,
    SearchHotelsParams,
    SearchHotelsWithDetailsParams,
)
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
from stays.search.hotels import MissingHotelIdError
from stays.serialize import _serialize_rate_plan as _serialize_rate_plan_full
from stays.serialize import _serialize_room as _serialize_room_full
from stays.serialize import serialize_hotel_detail as _serialize_hotel_detail_full
from stays.serialize import serialize_hotel_result as _serialize_hotel_result_full


def _get_search_hotels_cls():
    """Resolve ``SearchHotels`` via ``stays.mcp.server`` at call time.

    Tests ``patch("stays.mcp.server.SearchHotels")`` to inject a mock; this
    indirection makes that patch effective regardless of where the executor
    is called from.
    """
    # Late import to avoid a circular import at module load time.
    from stays.mcp import server as _server

    return _server.SearchHotels


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


# =============================================================================
# Serialization helpers — HotelResult / HotelDetail -> JSON-safe dicts
# =============================================================================

# MCP tool output is a compact subset of the canonical CLI shape:
#   - Result-level keys the CLI keeps but MCP omits (see _MCP_RESULT_DROP_KEYS)
#   - Detail-level extras the CLI adds but MCP omits (see _MCP_DETAIL_DROP_KEYS)
#   - Coordinates are surfaced as short aliases `lat`/`lng` instead of the
#     canonical `latitude`/`longitude` to keep tool payloads terse.
#   - Rate plans flatten the canonical nested ``cancellation`` object into
#     three top-level keys (``cancellation_kind``, ``cancellation_free_until``,
#     ``cancellation_description``).
#
# Goldens in tests/test_serialize_golden.py lock this shape.
_MCP_RESULT_DROP_KEYS: tuple[str, ...] = (
    "category_ratings",
    "deal_pct",
    "google_hotel_id",
    "image_urls",
    "nearby",
    "rate_dates",
    "rating_histogram",
    "star_class_label",
)
_MCP_DETAIL_DROP_KEYS: tuple[str, ...] = (
    *_MCP_RESULT_DROP_KEYS,
    "nearby_attractions",
    "recent_reviews",
)


def _apply_mcp_coordinate_aliases(data: dict[str, Any]) -> dict[str, Any]:
    """Rename canonical ``latitude``/``longitude`` to MCP's short ``lat``/``lng``."""
    data["lat"] = data.pop("latitude", None)
    data["lng"] = data.pop("longitude", None)
    return data


def _serialize_hotel_result(h: HotelResult) -> dict[str, Any]:
    """MCP subset of the canonical hotel-result serializer.

    Drops keys listed in ``_MCP_RESULT_DROP_KEYS`` and renames
    ``latitude``/``longitude`` to the compact ``lat``/``lng`` aliases.
    """
    full = _serialize_hotel_result_full(h)
    for key in _MCP_RESULT_DROP_KEYS:
        full.pop(key, None)
    return _apply_mcp_coordinate_aliases(full)


def _serialize_rate_plan(rp) -> dict[str, Any]:
    """MCP rate plan — flattens canonical ``cancellation`` nesting."""
    full = _serialize_rate_plan_full(rp)
    cancellation = full.pop("cancellation", None) or {}
    full["cancellation_kind"] = cancellation.get("kind")
    full["cancellation_free_until"] = cancellation.get("free_until")
    full["cancellation_description"] = cancellation.get("description")
    return full


def _serialize_room_type(r) -> dict[str, Any]:
    """MCP room — reuses canonical room shape but with MCP-flat rate plans."""
    full = _serialize_room_full(r)
    full["rates"] = [_serialize_rate_plan(rp) for rp in r.rates]
    return full


def _serialize_hotel_detail(d: HotelDetail) -> dict[str, Any]:
    """MCP subset of the canonical hotel-detail serializer."""
    full = _serialize_hotel_detail_full(d)
    for key in _MCP_DETAIL_DROP_KEYS:
        full.pop(key, None)
    _apply_mcp_coordinate_aliases(full)
    full["rooms"] = [_serialize_room_type(r) for r in d.rooms]
    return full


# =============================================================================
# Private execute entries (tests invoke these directly)
# =============================================================================


# Single canonical name — no aliases.
# Tests and tool wrappers both call *_from_params directly.


def _execute_search_hotels_from_params(params: SearchHotelsParams) -> dict[str, Any]:
    try:
        filters = _build_filters_from_search_params(params)
        hotels = _get_search_hotels_cls()().search(filters)
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
        detail = _get_search_hotels_cls()().get_details(
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
        enriched = _get_search_hotels_cls()().search_with_details(filters, max_hotels=params.max_hotels)
        items = []
        for er in enriched:
            items.append(
                {
                    "ok": er.ok,
                    "result": _serialize_hotel_result(er.result),
                    "detail": _serialize_hotel_detail(er.detail) if er.detail else None,
                    "error": er.error,
                    "error_kind": er.error_kind,
                    "is_retryable": er.is_retryable,
                }
            )
        return {"success": True, "count": len(items), "items": items}
    except (BatchExecuteError, TransientBatchExecuteError) as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}", "items": []}
