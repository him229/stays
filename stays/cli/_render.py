"""Rich-table renderers for human-readable CLI output."""

from __future__ import annotations

from collections.abc import Iterable

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from stays.cli._console import console as _default_console
from stays.models.google_hotels.base import Amenity
from stays.models.google_hotels.detail import HotelDetail
from stays.models.google_hotels.result import HotelResult
from stays.search.hotels import EnrichedResult


def _amenity_short(values: set[Amenity] | None, limit: int = 4) -> str:
    if not values:
        return "—"
    # Amenities are Amenity enum members; sort by integer value for stability.
    sorted_amenities = sorted(values, key=lambda a: a.value)
    names = [a.name.lower().replace("_", " ") for a in sorted_amenities]
    head = names[:limit]
    suffix = f" +{len(names) - limit}" if len(names) > limit else ""
    return ", ".join(head) + suffix


def _fmt_price(hotel: HotelResult) -> str:
    if hotel.display_price is None:
        return "—"
    cur = hotel.currency or ""
    return f"{cur} {hotel.display_price}".strip()


def _fmt_rating(hotel: HotelResult) -> str:
    if hotel.overall_rating is None:
        return "—"
    return f"{hotel.overall_rating:.1f} ({hotel.review_count or 0})"


def render_results(results: list[HotelResult], *, console: Console | None = None) -> None:
    console = console or _default_console
    if not results:
        console.print(Panel("No hotels found matching your criteria.", border_style="red"))
        return

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("Name", overflow="fold", style="green")
    table.add_column("★", justify="center", width=3)
    table.add_column("Rating", justify="right", width=12)
    table.add_column("Price", justify="right", width=12)
    table.add_column("Amenities", overflow="fold")
    table.add_column("Entity Key", overflow="crop", width=14)

    for i, r in enumerate(results, 1):
        table.add_row(
            str(i),
            r.name or "—",
            str(r.star_class) if r.star_class else "—",
            _fmt_rating(r),
            _fmt_price(r),
            _amenity_short(r.amenities_available),
            (r.entity_key[:12] + "…") if r.entity_key else "—",
        )
    console.print(table)


def render_detail(detail: HotelDetail, *, console: Console | None = None) -> None:
    console = console or _default_console

    summary = Table(box=box.SIMPLE, show_header=False)
    summary.add_column(style="bold cyan")
    summary.add_column()
    summary.add_row("Name", detail.name or "—")
    summary.add_row("Address", detail.address or "—")
    summary.add_row("Phone", detail.phone or "—")
    summary.add_row("Stars", str(detail.star_class) if detail.star_class else "—")
    summary.add_row("Rating", _fmt_rating(detail))
    summary.add_row("Check-in / out", f"{detail.check_in_time or '—'} / {detail.check_out_time or '—'}")
    console.print(Panel(summary, title="Hotel", border_style="cyan"))

    if not detail.rooms:
        console.print(Panel("No rooms returned for these dates.", border_style="yellow"))
        return

    for room in detail.rooms:
        rt = Table(box=box.SIMPLE_HEAVY, show_header=True)
        rt.add_column("Provider", style="green")
        rt.add_column("Price", justify="right")
        rt.add_column("Cancellation")
        rt.add_column("Breakfast", justify="center")
        rt.add_column("Taxes", justify="center")
        for rate in room.rates:
            rt.add_row(
                rate.provider or "—",
                f"{rate.currency or ''} {rate.price}".strip(),
                rate.cancellation.kind.value.replace("_", " ").title(),
                "✓" if rate.breakfast_included else "",
                "✓" if rate.includes_taxes_and_fees else "",
            )
        subtitle = f"{room.bed_config or ''} · sleeps {room.max_occupancy or '?'}".strip(" ·")
        console.print(Panel(rt, title=room.name, subtitle=subtitle, border_style="green"))


def render_enriched(items: Iterable[EnrichedResult], *, console: Console | None = None) -> None:
    console = console or _default_console
    any_rendered = False
    for item in items:
        any_rendered = True
        if item.ok and item.detail is not None:
            render_detail(item.detail, console=console)
        else:
            console.print(
                Panel(
                    f"[red]Error: {item.error}[/red]\n[dim]{item.result.name}[/dim]",
                    border_style="red",
                )
            )
    if not any_rendered:
        console.print(Panel("No results.", border_style="red"))
