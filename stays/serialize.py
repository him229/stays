"""Canonical serializers for stays public types.

This module is the single source of truth for turning pydantic domain
objects (HotelResult, HotelDetail, RatePlan, RoomType, CancellationPolicy)
into plain dicts suitable for CLI JSON output and MCP tool responses.

Pure functions — no I/O, no logging. Dict shape contracts are stable:
adding keys is safe; renaming or removing keys is a breaking change,
guarded by tests/test_serialize_golden.py.

CLI and MCP both import from here. The CLI module stays.cli._serialize
remains as a re-export shim for backwards compatibility.
"""

from __future__ import annotations

from typing import Any

from stays.models.google_hotels.base import Amenity
from stays.models.google_hotels.detail import HotelDetail, RatePlan, RoomType
from stays.models.google_hotels.policy import CancellationPolicy
from stays.models.google_hotels.result import HotelResult

_DATA_SOURCE = "google_hotels"


def _amenities_as_names(values: set[Amenity]) -> list[str]:
    return sorted(amenity.name for amenity in values)


def serialize_hotel_result(result: HotelResult) -> dict[str, Any]:
    rate_dates = None
    if result.rate_dates:
        ci, co = result.rate_dates
        rate_dates = {"check_in": ci.isoformat(), "check_out": co.isoformat()}
    return {
        "name": result.name,
        "entity_key": result.entity_key,
        "kgmid": result.kgmid,
        "fid": result.fid,
        "google_hotel_id": result.google_hotel_id or None,
        "latitude": result.latitude,
        "longitude": result.longitude,
        "display_price": result.display_price,
        "currency": result.currency,
        "rate_dates": rate_dates,
        "star_class": result.star_class,
        "star_class_label": result.star_class_label,
        "overall_rating": result.overall_rating,
        "review_count": result.review_count,
        "rating_histogram": (
            result.rating_histogram.model_dump(mode="json") if result.rating_histogram is not None else None
        ),
        "deal_pct": result.deal_pct,
        "check_in_time": result.check_in_time,
        "check_out_time": result.check_out_time,
        "amenities": _amenities_as_names(result.amenities_available or set()),
        "category_ratings": [cr.model_dump(mode="json") for cr in (result.category_ratings or [])],
        "nearby": [n.model_dump(mode="json") for n in (result.nearby or [])],
        "image_urls": list(result.image_urls or []),
    }


def _serialize_cancellation(policy: CancellationPolicy) -> dict[str, Any]:
    return {
        "kind": policy.kind.value,
        "free_until": policy.free_until.isoformat() if policy.free_until else None,
        "description": policy.description,
    }


def _serialize_rate_plan(rate: RatePlan) -> dict[str, Any]:
    return {
        "provider": rate.provider,
        "price": rate.price,
        "currency": rate.currency,
        "cancellation": _serialize_cancellation(rate.cancellation),
        "breakfast_included": rate.breakfast_included,
        "includes_taxes_and_fees": rate.includes_taxes_and_fees,
        "deeplink_url": rate.deeplink_url,
    }


def _serialize_room(room: RoomType) -> dict[str, Any]:
    return {
        "name": room.name,
        "description": room.description,
        "bed_config": room.bed_config,
        "max_occupancy": room.max_occupancy,
        "rates": [_serialize_rate_plan(r) for r in room.rates],
    }


def serialize_hotel_detail(detail: HotelDetail) -> dict[str, Any]:
    base = serialize_hotel_result(detail)
    base.update(
        {
            "description": detail.description,
            "address": detail.address,
            "phone": detail.phone,
            "rooms": [_serialize_room(r) for r in detail.rooms],
            "amenity_details": list(detail.amenity_details or []),
            "nearby_attractions": list(detail.nearby_attractions or []),
            "recent_reviews": [rev.model_dump(mode="json") for rev in (detail.recent_reviews or [])],
        }
    )
    return base


def build_success(
    *,
    search_type: str,
    query: dict[str, Any],
    results_key: str,
    results: list[Any] | Any,
) -> dict[str, Any]:
    count = len(results) if isinstance(results, list) else 1
    return {
        "success": True,
        "data_source": _DATA_SOURCE,
        "search_type": search_type,
        "query": query,
        "count": count,
        results_key: results,
    }


def build_error(
    *,
    search_type: str,
    message: str,
    error_type: str = "validation_error",
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": False,
        "data_source": _DATA_SOURCE,
        "search_type": search_type,
        "error": {"type": error_type, "message": message},
    }
    if query is not None:
        payload["query"] = query
    return payload
