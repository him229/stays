"""Typer callback validators for CLI inputs."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import TypeVar

import typer

from stays.models.google_hotels.base import Currency

_E = TypeVar("_E", bound=Enum)


def parse_date(value: str | None) -> date | None:
    """Parse a YYYY-MM-DD string; raise typer.BadParameter on anything else."""
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"Date must be in YYYY-MM-DD format; got {value!r}") from exc


def parse_currency(value: str | None) -> Currency | None:
    """Normalize a currency string to a Currency enum member."""
    if value is None:
        return None
    candidate = value.strip().upper()
    try:
        return Currency[candidate]
    except KeyError as exc:
        valid = ", ".join(sorted(c.name for c in Currency))
        raise typer.BadParameter(f"Currency must be one of: {valid}. Got {value!r}.") from exc


def parse_enum_name(enum_cls: type[_E], value: str | None) -> _E | None:
    """Map a case-insensitive string to an enum member by NAME."""
    if value is None:
        return None
    candidate = value.strip().upper()
    try:
        return enum_cls[candidate]
    except KeyError as exc:
        valid = ", ".join(m.name for m in enum_cls)
        raise typer.BadParameter(f"{enum_cls.__name__} must be one of: {valid}. Got {value!r}.") from exc


def parse_enum_name_list(enum_cls: type[_E], values: list[str] | None) -> list[_E] | None:
    """Map a list of names to enum members. Empty/None returns None."""
    if not values:
        return None
    return [parse_enum_name(enum_cls, v) for v in values]  # type: ignore[misc]


def parse_stars(values: list[int] | None) -> list[int] | None:
    """Validate and normalize a hotel_class list."""
    if not values:
        return None
    out = sorted(set(values))
    for v in out:
        if v < 1 or v > 5:
            raise typer.BadParameter(f"Star values must be 1..5. Got {v}.")
    return out


def parse_price_range(price_min: int | None, price_max: int | None) -> tuple[int | None, int | None] | None:
    """Build the price_range tuple or None if both unset."""
    if price_min is None and price_max is None:
        return None
    if price_min is not None and price_max is not None and price_min >= price_max:
        raise typer.BadParameter("--price-min must be strictly less than --price-max.")
    return (price_min, price_max)
