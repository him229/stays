"""`stays search` command."""

from __future__ import annotations

from typing import Annotated

import pydantic
import typer

from stays.cli import _render, _runtime, _serialize
from stays.cli._console import console
from stays.cli._enums import OutputFormat
from stays.search.client import BatchExecuteError, TransientBatchExecuteError
from stays.search.hotels import SearchHotels


def search(
    query: Annotated[str, typer.Argument(help="Free-text query (e.g. 'tokyo hotels', 'Hilton Paris').")],
    check_in: Annotated[str | None, typer.Option("--check-in", help="Check-in date YYYY-MM-DD.")] = None,
    check_out: Annotated[str | None, typer.Option("--check-out", help="Check-out date YYYY-MM-DD.")] = None,
    adults: Annotated[int, typer.Option("--adults", min=1, max=12)] = 2,
    children: Annotated[int, typer.Option("--children", min=0, max=8)] = 0,
    child_age: Annotated[
        list[int] | None,
        typer.Option("--child-age", help="Repeatable. e.g. --child-age 7 --child-age 10."),
    ] = None,
    currency: Annotated[
        str | None,
        typer.Option("--currency", help="ISO 4217 currency code (enum-backed)."),
    ] = None,
    property_type: Annotated[
        str | None,
        typer.Option("--property-type", help="HOTELS or VACATION_RENTALS"),
    ] = None,
    sort_by: Annotated[
        str | None,
        typer.Option(
            "--sort-by",
            help="RELEVANCE | LOWEST_PRICE | HIGHEST_RATING | MOST_REVIEWED",
        ),
    ] = None,
    stars: Annotated[
        list[int] | None,
        typer.Option("--stars", help="Repeatable, each 1..5."),
    ] = None,
    min_rating: Annotated[
        str | None,
        typer.Option(
            "--min-rating",
            help="THREE_FIVE_PLUS | FOUR_ZERO_PLUS | FOUR_FIVE_PLUS",
        ),
    ] = None,
    amenity: Annotated[
        list[str] | None,
        typer.Option("--amenity", help="Repeatable. POOL, WIFI, SPA, PET_FRIENDLY, …"),
    ] = None,
    brand: Annotated[
        list[str] | None,
        typer.Option("--brand", help="Repeatable. HILTON, MARRIOTT, HYATT, …"),
    ] = None,
    free_cancellation: Annotated[bool, typer.Option("--free-cancellation/--no-free-cancellation")] = False,
    eco_certified: Annotated[bool, typer.Option("--eco-certified/--no-eco-certified")] = False,
    special_offers: Annotated[bool, typer.Option("--special-offers/--no-special-offers")] = False,
    price_min: Annotated[int | None, typer.Option("--price-min", min=0)] = None,
    price_max: Annotated[int | None, typer.Option("--price-max", min=0)] = None,
    max_results: Annotated[int | None, typer.Option("--max-results", min=1, max=25)] = None,
    output_format: Annotated[OutputFormat, typer.Option("--format", case_sensitive=False)] = OutputFormat.TEXT,
) -> None:
    """Search Google Hotels list view."""
    # We deliberately catch typer.BadParameter INSIDE the body (not
    # letting typer handle it) so that JSON/JSONL users get a structured
    # error envelope instead of typer's default stderr-usage-error-exit-2.
    # Typer's native min/max/Enum parse-time validation still exits 2 —
    # that boundary is called out in the spec's "Exit codes" table.
    query_record: dict | None = None
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
            max_results=max_results,
        )
    except (typer.BadParameter, pydantic.ValidationError, ValueError) as exc:
        _runtime.emit_error(
            search_type="search",
            message=str(exc),
            error_type="validation_error",
            query=query_record,
            output_format=output_format,
        )
        raise typer.Exit(1) from exc

    assert query_record is not None  # populated in the try block above

    try:
        results = SearchHotels().search(filters)
    except (BatchExecuteError, TransientBatchExecuteError) as exc:
        _runtime.emit_error(
            search_type="search",
            message=str(exc),
            error_type="network_error",
            query=query_record,
            output_format=output_format,
        )
        raise typer.Exit(1) from exc

    if max_results is not None:
        results = results[:max_results]

    _runtime.emit_result(
        search_type="search",
        query=query_record,
        results_key="hotels",
        serialized_results=[_serialize.serialize_hotel_result(r) for r in results],
        output_format=output_format,
        render=lambda: _render.render_results(results, console=console),
    )
