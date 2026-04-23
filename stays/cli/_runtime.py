"""Shared CLI runtime helpers.

Encapsulates three patterns that each ``stays`` subcommand currently
duplicates:

- ``emit_result`` — the ``--format text/json/jsonl`` if-ladder that
  wraps (or renders) already-serialized results.
- ``emit_error`` — the envelope-vs-text error emission used by every
  command's validation / network-error handlers.
- ``build_filters_from_cli_args`` — the raw-CLI-args → validated values
  → ``(query_record, HotelSearchFilters)`` pipeline shared by
  ``search`` and ``enrich``.

Golden envelope tests (``tests/test_cli_envelope_golden.py``) pin the
byte-level stdout of every (command, format) tuple; anything routed
through here MUST keep those tests passing.
"""

from __future__ import annotations

import json as _json
from collections.abc import Callable
from datetime import date as _date
from typing import Any

import typer

from stays.cli import _serialize, _validate
from stays.cli._enums import OutputFormat
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
from stays.models.google_hotels.hotels import HotelSearchFilters


def emit_result(
    *,
    search_type: str,
    query: dict[str, Any],
    results_key: str,
    serialized_results: list[dict[str, Any]] | dict[str, Any],
    output_format: OutputFormat,
    render: Callable[[], None],
) -> None:
    """Emit a successful command result in the requested format.

    - ``OutputFormat.JSON`` → envelope from ``build_success``, pretty-printed
    - ``OutputFormat.JSONL`` → one JSON doc per result (one total for dict)
    - ``OutputFormat.TEXT`` → delegates to ``render`` (rich tables, etc.)

    ``serialized_results`` MUST already be plain dicts — domain objects
    belong on the caller side so this helper never touches pydantic or
    ``serialize_hotel_result`` / ``serialize_hotel_detail`` directly.
    """
    if output_format == OutputFormat.JSON:
        envelope = _serialize.build_success(
            search_type=search_type,
            query=query,
            results_key=results_key,
            results=serialized_results,
        )
        typer.echo(_json.dumps(envelope, indent=2))
        return
    if output_format == OutputFormat.JSONL:
        if isinstance(serialized_results, list):
            for item in serialized_results:
                typer.echo(_json.dumps(item))
        else:
            typer.echo(_json.dumps(serialized_results))
        return
    render()


def emit_error(
    *,
    search_type: str,
    message: str,
    error_type: str,
    query: dict[str, Any] | None,
    output_format: OutputFormat,
) -> None:
    """Emit an error in the requested format.

    Does NOT raise — callers follow up with ``raise typer.Exit(1)`` (or
    similar) so traceback chaining (``from exc``) remains explicit at
    the call site.

    - ``OutputFormat.TEXT`` → one-line ``Error: <message>`` on stdout
    - ``OutputFormat.JSON`` / ``JSONL`` → ``build_error`` envelope
      (pretty-printed for JSON, compact for JSONL)
    """
    if output_format == OutputFormat.TEXT:
        typer.echo(f"Error: {message}")
        return
    envelope = _serialize.build_error(
        search_type=search_type,
        message=message,
        error_type=error_type,
        query=query,
    )
    if output_format == OutputFormat.JSONL:
        typer.echo(_json.dumps(envelope))
    else:
        typer.echo(_json.dumps(envelope, indent=2))


def _serialize_query(
    *,
    query: str,
    check_in: _date | None,
    check_out: _date | None,
    adults: int,
    children: int,
    child_ages: list[int] | None,
    stars: list[int] | None,
    amenities: list[Amenity] | None,
    brands: list[Brand] | None,
    currency: Currency | None,
    property_type: PropertyType | None,
    sort_by: SortBy | None,
    min_rating: MinGuestRating | None,
    free_cancellation: bool,
    eco_certified: bool,
    special_offers: bool,
    price_range: tuple[int | None, int | None] | None,
    max_results: int | None,
) -> dict[str, Any]:
    """Build the JSON query-echo dict from (already-validated) CLI values.

    Mirrored from the pre-extraction ``search._serialize_query`` — every
    key, every ``None`` sentinel is preserved so the golden envelope
    fixtures stay byte-identical.
    """
    return {
        "query": query,
        "check_in": check_in.isoformat() if check_in else None,
        "check_out": check_out.isoformat() if check_out else None,
        "adults": adults,
        "children": children,
        "child_ages": list(child_ages) if child_ages else None,
        "currency": currency.value if currency else None,
        "property_type": property_type.name if property_type else None,
        "sort_by": sort_by.name if sort_by else None,
        "min_rating": min_rating.name if min_rating else None,
        "stars": stars,
        "amenities": [a.name for a in (amenities or [])] or None,
        "brands": [b.name for b in (brands or [])] or None,
        "free_cancellation": free_cancellation or None,
        "eco_certified": eco_certified or None,
        "special_offers": special_offers or None,
        "price_min": price_range[0] if price_range else None,
        "price_max": price_range[1] if price_range else None,
        "max_results": max_results,
    }


def _build_filters(
    *,
    query: str,
    check_in: _date | None,
    check_out: _date | None,
    adults: int,
    children: int,
    child_ages: list[int] | None,
    currency: Currency | None,
    property_type: PropertyType | None,
    sort_by: SortBy | None,
    stars: list[int] | None,
    min_rating: MinGuestRating | None,
    amenities: list[Amenity] | None,
    brands: list[Brand] | None,
    free_cancellation: bool,
    eco_certified: bool,
    special_offers: bool,
    price_range: tuple[int | None, int | None] | None,
) -> HotelSearchFilters:
    """Construct a ``HotelSearchFilters`` from already-validated values.

    Mirrored from the pre-extraction ``search._build_filters`` — the
    kwargs-omit-when-None pattern is deliberate: it keeps the resulting
    filter object identical to what the CLI built before.
    """
    dates = None
    if check_in and check_out:
        dates = DateRange(check_in=check_in, check_out=check_out)
    elif check_in or check_out:
        raise typer.BadParameter("Provide both --check-in and --check-out, or neither.")

    kwargs: dict[str, Any] = {
        "location": Location(query=query),
        "guests": GuestInfo(
            adults=adults,
            children=children,
            child_ages=child_ages or [],
        ),
    }
    if dates is not None:
        kwargs["dates"] = dates
    if currency is not None:
        kwargs["currency"] = currency
    if property_type is not None:
        kwargs["property_type"] = property_type
    if sort_by is not None:
        kwargs["sort_by"] = sort_by
    if stars:
        kwargs["hotel_class"] = stars
    if min_rating is not None:
        kwargs["min_guest_rating"] = min_rating
    if amenities:
        kwargs["amenities"] = amenities
    if brands:
        kwargs["brands"] = brands
    if free_cancellation:
        kwargs["free_cancellation"] = True
    if eco_certified:
        kwargs["eco_certified"] = True
    if special_offers:
        kwargs["special_offers"] = True
    if price_range is not None:
        kwargs["price_range"] = price_range
    return HotelSearchFilters(**kwargs)


def build_filters_from_cli_args(
    *,
    query: str,
    check_in: str | None,
    check_out: str | None,
    adults: int,
    children: int,
    child_age: list[int] | None,
    currency: str | None,
    property_type: str | None,
    sort_by: str | None,
    stars: list[int] | None,
    min_rating: str | None,
    amenity: list[str] | None,
    brand: list[str] | None,
    free_cancellation: bool,
    eco_certified: bool,
    special_offers: bool,
    price_min: int | None,
    price_max: int | None,
    max_results: int | None,
) -> tuple[dict[str, Any], HotelSearchFilters]:
    """Validate every raw CLI arg and build both the query echo and filters.

    Shared pre-network pipeline between ``stays search`` and ``stays
    enrich``. Returns ``(query_record, HotelSearchFilters)``.

    Raises ``typer.BadParameter`` / ``pydantic.ValidationError`` /
    ``ValueError`` — callers catch these to emit a ``validation_error``
    envelope with exit code 1.
    """
    check_in_d = _validate.parse_date(check_in)
    check_out_d = _validate.parse_date(check_out)
    stars_v = _validate.parse_stars(stars)
    amenities_v = _validate.parse_enum_name_list(Amenity, amenity)
    brands_v = _validate.parse_enum_name_list(Brand, brand)
    currency_v = _validate.parse_currency(currency)
    property_type_v = _validate.parse_enum_name(PropertyType, property_type)
    sort_by_v = _validate.parse_enum_name(SortBy, sort_by)
    min_rating_v = _validate.parse_enum_name(MinGuestRating, min_rating)
    price_range_v = _validate.parse_price_range(price_min, price_max)

    query_record = _serialize_query(
        query=query,
        check_in=check_in_d,
        check_out=check_out_d,
        adults=adults,
        children=children,
        child_ages=child_age,
        stars=stars_v,
        amenities=amenities_v,
        brands=brands_v,
        currency=currency_v,
        property_type=property_type_v,
        sort_by=sort_by_v,
        min_rating=min_rating_v,
        free_cancellation=free_cancellation,
        eco_certified=eco_certified,
        special_offers=special_offers,
        price_range=price_range_v,
        max_results=max_results,
    )

    filters = _build_filters(
        query=query,
        check_in=check_in_d,
        check_out=check_out_d,
        adults=adults,
        children=children,
        child_ages=child_age,
        currency=currency_v,
        property_type=property_type_v,
        sort_by=sort_by_v,
        stars=stars_v,
        min_rating=min_rating_v,
        amenities=amenities_v,
        brands=brands_v,
        free_cancellation=free_cancellation,
        eco_certified=eco_certified,
        special_offers=special_offers,
        price_range=price_range_v,
    )

    return query_record, filters
