"""`stays search` command."""

from __future__ import annotations

import json as _json
from datetime import date as _date
from typing import Annotated, Any

import pydantic
import typer

from stays.cli import _render, _serialize, _validate
from stays.cli._console import console
from stays.cli._enums import OutputFormat
from stays.models.google_hotels.base import (
    Amenity,
    Brand,
    Currency,
    MinGuestRating,
    PropertyType,
    SortBy,
)
from stays.models.google_hotels.hotels import (
    DateRange,
    GuestInfo,
    HotelSearchFilters,
    Location,
)
from stays.search.client import BatchExecuteError, TransientBatchExecuteError
from stays.search.hotels import SearchHotels


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
    except (typer.BadParameter, pydantic.ValidationError, ValueError) as exc:
        _emit_error("search", str(exc), "validation_error", query_record, output_format)
        raise typer.Exit(1) from exc

    assert query_record is not None  # populated in the try block above

    try:
        results = SearchHotels().search(filters)
    except (BatchExecuteError, TransientBatchExecuteError) as exc:
        _emit_error("search", str(exc), "network_error", query_record, output_format)
        raise typer.Exit(1) from exc

    if max_results is not None:
        results = results[:max_results]

    if output_format == OutputFormat.JSON:
        envelope = _serialize.build_success(
            search_type="search",
            query=query_record,
            results_key="hotels",
            results=[_serialize.serialize_hotel_result(r) for r in results],
        )
        typer.echo(_json.dumps(envelope, indent=2))
        return

    if output_format == OutputFormat.JSONL:
        for r in results:
            typer.echo(_json.dumps(_serialize.serialize_hotel_result(r)))
        return

    _render.render_results(results, console=console)


def _emit_error(
    search_type: str,
    message: str,
    error_type: str,
    query: dict[str, Any] | None,
    output_format: OutputFormat,
) -> None:
    if output_format == OutputFormat.TEXT:
        typer.echo(f"Error: {message}", err=False)
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
