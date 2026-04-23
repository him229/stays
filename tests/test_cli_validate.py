"""Tests for stays.cli._validate callback helpers."""

from __future__ import annotations

from datetime import date

import pytest
import typer

from stays.cli import _validate
from stays.models.google_hotels.base import Amenity, Brand, Currency, SortBy


class TestDateParser:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("2026-07-22", date(2026, 7, 22)),
            (None, None),
        ],
        ids=["iso_date", "none_passthrough"],
    )
    def test_accepts_valid_input(self, value, expected) -> None:
        assert _validate.parse_date(value) == expected

    @pytest.mark.parametrize(
        "bad, match",
        [
            ("07/22/2026", "YYYY-MM-DD"),
            ("2026-13-45", None),
        ],
        ids=["malformed", "impossible"],
    )
    def test_rejects_invalid_input(self, bad, match) -> None:
        if match is None:
            with pytest.raises(typer.BadParameter):
                _validate.parse_date(bad)
        else:
            with pytest.raises(typer.BadParameter, match=match):
                _validate.parse_date(bad)


class TestCurrency:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("usd", Currency.USD),
            ("EUR", Currency.EUR),
            (None, None),
        ],
        ids=["lowercase_uppercased", "enum_name_direct", "none_passthrough"],
    )
    def test_accepts_valid_code(self, raw, expected) -> None:
        assert _validate.parse_currency(raw) == expected

    def test_rejects_unknown(self) -> None:
        with pytest.raises(typer.BadParameter, match="Currency"):
            _validate.parse_currency("XYZ")


class TestEnumByName:
    def test_maps_name_case_insensitive(self) -> None:
        result = _validate.parse_enum_name(SortBy, "lowest_price")
        assert result is SortBy.LOWEST_PRICE

    def test_raises_with_valid_names(self) -> None:
        with pytest.raises(typer.BadParameter, match="LOWEST_PRICE"):
            _validate.parse_enum_name(SortBy, "cheapest")

    def test_none_passthrough(self) -> None:
        assert _validate.parse_enum_name(SortBy, None) is None

    def test_list_of_enum_names(self) -> None:
        result = _validate.parse_enum_name_list(Amenity, ["POOL", "wifi"])
        assert result == [Amenity.POOL, Amenity.WIFI]

    def test_empty_list_returns_none(self) -> None:
        assert _validate.parse_enum_name_list(Brand, []) is None
        assert _validate.parse_enum_name_list(Brand, None) is None


class TestStars:
    def test_valid_range(self) -> None:
        assert _validate.parse_stars([4, 5]) == [4, 5]

    def test_rejects_out_of_range(self) -> None:
        with pytest.raises(typer.BadParameter, match="1.*5"):
            _validate.parse_stars([0, 6])

    def test_empty_is_none(self) -> None:
        assert _validate.parse_stars([]) is None
        assert _validate.parse_stars(None) is None

    def test_dedupes_and_sorts(self) -> None:
        assert _validate.parse_stars([5, 4, 4]) == [4, 5]


class TestPriceRange:
    @pytest.mark.parametrize(
        "lo, hi, expected",
        [
            (100, 300, (100, 300)),
            (100, None, (100, None)),
            (None, 250, (None, 250)),
            (None, None, None),
        ],
        ids=["both_set", "only_min", "only_max", "both_none"],
    )
    def test_valid_combinations(self, lo, hi, expected) -> None:
        assert _validate.parse_price_range(lo, hi) == expected

    def test_min_ge_max_rejected(self) -> None:
        with pytest.raises(typer.BadParameter, match="price-min.*price-max"):
            _validate.parse_price_range(300, 100)
