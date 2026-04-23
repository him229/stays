"""`stays details` command."""

from __future__ import annotations

from typing import Annotated, Any

import typer

from stays.cli import _render, _runtime, _serialize, _validate
from stays.cli._console import console
from stays.cli._enums import OutputFormat
from stays.models.google_hotels.base import DateRange
from stays.search.client import BatchExecuteError, TransientBatchExecuteError
from stays.search.hotels import MissingHotelIdError, SearchHotels


def details(
    entity_key: Annotated[str, typer.Argument(help="Entity key from a prior `stays search` result.")],
    *,
    # Keyword-only + no default = required option. Avoids the `= ...`
    # (Ellipsis) sentinel pattern, which is ambiguous and could silently
    # pass Ellipsis as a real default in some typer versions.
    check_in: Annotated[str, typer.Option("--check-in", help="Check-in date YYYY-MM-DD.")],
    check_out: Annotated[str, typer.Option("--check-out", help="Check-out date YYYY-MM-DD.")],
    currency: Annotated[str | None, typer.Option("--currency")] = None,
    output_format: Annotated[OutputFormat, typer.Option("--format", case_sensitive=False)] = OutputFormat.TEXT,
) -> None:
    """Fetch detailed rooms + rate plans for a single hotel."""
    # --check-in / --check-out are required typer options (no default,
    # keyword-only), so typer exits with code 2 before this function runs
    # when either is missing. No need to re-check for None here.
    ci = _validate.parse_date(check_in)
    co = _validate.parse_date(check_out)
    dates = DateRange(check_in=ci, check_out=co)
    cur = _validate.parse_currency(currency)  # Currency | None

    query: dict[str, Any] = {
        "entity_key": entity_key,
        "check_in": ci.isoformat(),
        "check_out": co.isoformat(),
        "currency": cur.value if cur else None,
    }

    # get_details signature is `currency: Currency = Currency.USD` — passing
    # None would TypeError the pydantic validator. Only pass when set.
    get_details_kwargs: dict[str, Any] = {"entity_key": entity_key, "dates": dates}
    if cur is not None:
        get_details_kwargs["currency"] = cur

    try:
        detail = SearchHotels().get_details(**get_details_kwargs)
    except MissingHotelIdError as exc:
        _runtime.emit_error(
            search_type="details",
            message=str(exc),
            error_type="validation_error",
            query=query,
            output_format=output_format,
        )
        raise typer.Exit(1) from exc
    except (BatchExecuteError, TransientBatchExecuteError) as exc:
        _runtime.emit_error(
            search_type="details",
            message=str(exc),
            error_type="network_error",
            query=query,
            output_format=output_format,
        )
        raise typer.Exit(1) from exc

    _runtime.emit_result(
        search_type="details",
        query=query,
        results_key="hotel",
        serialized_results=_serialize.serialize_hotel_detail(detail),
        output_format=output_format,
        render=lambda: _render.render_detail(detail, console=console),
    )
