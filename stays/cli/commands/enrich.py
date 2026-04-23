"""`stays enrich` command — search + parallel detail-fetch for top N."""

from __future__ import annotations

from typing import Annotated, Any

import pydantic
import typer

from stays.cli import _render, _runtime, _serialize
from stays.cli._console import console
from stays.cli._enums import OutputFormat
from stays.mcp._config import HARD_MAX_HOTELS_WITH_DETAILS
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
    max_hotels: Annotated[int, typer.Option("--max-hotels", min=1, max=HARD_MAX_HOTELS_WITH_DETAILS)] = 5,
    output_format: Annotated[OutputFormat, typer.Option("--format", case_sensitive=False)] = OutputFormat.TEXT,
) -> None:
    """Search + parallel detail-fetch for the top N hotels."""
    query_record: dict[str, Any] | None = None
    try:
        query_record, filters = _runtime.build_filters_from_cli_args(
            query=query,
            check_in=check_in,
            check_out=check_out,
            adults=adults,
            children=children,
            child_age=child_age,
            currency=currency,
            property_type=property_type,
            sort_by=sort_by,
            stars=stars,
            min_rating=min_rating,
            amenity=amenity,
            brand=brand,
            free_cancellation=free_cancellation,
            eco_certified=eco_certified,
            special_offers=special_offers,
            price_min=price_min,
            price_max=price_max,
            max_results=None,  # enrich uses max_hotels, not max_results
        )
        query_record["max_hotels"] = max_hotels
    except (typer.BadParameter, pydantic.ValidationError, ValueError) as exc:
        _runtime.emit_error(
            search_type="enrich",
            message=str(exc),
            error_type="validation_error",
            query=query_record,
            output_format=output_format,
        )
        raise typer.Exit(1) from exc

    assert query_record is not None

    try:
        items = SearchHotels().search_with_details(filters, max_hotels=max_hotels)
    except (BatchExecuteError, TransientBatchExecuteError) as exc:
        _runtime.emit_error(
            search_type="enrich",
            message=str(exc),
            error_type="network_error",
            query=query_record,
            output_format=output_format,
        )
        raise typer.Exit(1) from exc

    _runtime.emit_result(
        search_type="enrich",
        query=query_record,
        results_key="hotels",
        serialized_results=[_serialize_enriched(it) for it in items],
        output_format=output_format,
        render=lambda: _render.render_enriched(items, console=console),
    )


def _serialize_enriched(item: Any) -> dict[str, Any]:
    return {
        "ok": bool(item.ok),
        "result": _serialize.serialize_hotel_result(item.result),
        "detail": _serialize.serialize_hotel_detail(item.detail) if item.detail else None,
        "error": item.error,
        "error_kind": item.error_kind,
        "is_retryable": item.is_retryable,
    }
