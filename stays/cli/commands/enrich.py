"""`stays enrich` command — search + parallel detail-fetch for top N."""

from __future__ import annotations

import json as _json
from typing import Annotated, Any

import pydantic
import typer

from stays.cli import _render, _serialize, _validate
from stays.cli._console import console
from stays.cli._enums import OutputFormat
from stays.cli.commands.search import _build_filters, _emit_error, _serialize_query
from stays.models.google_hotels.base import (
    Amenity,
    Brand,
    MinGuestRating,
    PropertyType,
    SortBy,
)
from stays.search.client import BatchExecuteError, TransientBatchExecuteError
from stays.search.hotels import SearchHotels


def enrich(
    query: Annotated[str, typer.Argument()],
    check_in: Annotated[str | None, typer.Option("--check-in")] = None,
    check_out: Annotated[str | None, typer.Option("--check-out")] = None,
    adults: Annotated[int, typer.Option("--adults", min=1, max=12)] = 2,
    children: Annotated[int, typer.Option("--children", min=0, max=8)] = 0,
    child_age: Annotated[list[int] | None, typer.Option("--child-age")] = None,
    currency: Annotated[str | None, typer.Option("--currency")] = None,
    property_type: Annotated[str | None, typer.Option("--property-type")] = None,
    sort_by: Annotated[str | None, typer.Option("--sort-by")] = None,
    stars: Annotated[list[int] | None, typer.Option("--stars")] = None,
    min_rating: Annotated[str | None, typer.Option("--min-rating")] = None,
    amenity: Annotated[list[str] | None, typer.Option("--amenity")] = None,
    brand: Annotated[list[str] | None, typer.Option("--brand")] = None,
    free_cancellation: Annotated[bool, typer.Option("--free-cancellation/--no-free-cancellation")] = False,
    eco_certified: Annotated[bool, typer.Option("--eco-certified/--no-eco-certified")] = False,
    special_offers: Annotated[bool, typer.Option("--special-offers/--no-special-offers")] = False,
    price_min: Annotated[int | None, typer.Option("--price-min", min=0)] = None,
    price_max: Annotated[int | None, typer.Option("--price-max", min=0)] = None,
    max_hotels: Annotated[int, typer.Option("--max-hotels", min=1, max=15)] = 5,
    output_format: Annotated[OutputFormat, typer.Option("--format", case_sensitive=False)] = OutputFormat.TEXT,
) -> None:
    """Search + parallel detail-fetch for the top N hotels."""
    query_record: dict[str, Any] | None = None
    try:
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
            max_results=None,  # enrich uses max_hotels, not max_results
        )
        query_record["max_hotels"] = max_hotels

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
    except (typer.BadParameter, pydantic.ValidationError, ValueError) as exc:
        _emit_error("enrich", str(exc), "validation_error", query_record, output_format)
        raise typer.Exit(1) from exc

    assert query_record is not None

    try:
        items = SearchHotels().search_with_details(filters, max_hotels=max_hotels)
    except (BatchExecuteError, TransientBatchExecuteError) as exc:
        _emit_error("enrich", str(exc), "network_error", query_record, output_format)
        raise typer.Exit(1) from exc

    if output_format == OutputFormat.JSON:
        envelope = _serialize.build_success(
            search_type="enrich",
            query=query_record,
            results_key="hotels",
            results=[_serialize_enriched(it) for it in items],
        )
        typer.echo(_json.dumps(envelope, indent=2))
        return
    if output_format == OutputFormat.JSONL:
        for it in items:
            typer.echo(_json.dumps(_serialize_enriched(it)))
        return
    _render.render_enriched(items, console=console)


def _serialize_enriched(item: Any) -> dict[str, Any]:
    return {
        "ok": bool(item.ok),
        "result": _serialize.serialize_hotel_result(item.result),
        "detail": _serialize.serialize_hotel_detail(item.detail) if item.detail else None,
        "error": item.error,
    }
