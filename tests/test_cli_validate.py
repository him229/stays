"""Tests for stays.cli._validate callback helpers."""

from __future__ import annotations

from datetime import date

import pytest
import typer

from stays.cli import _validate
from stays.models.google_hotels.base import Amenity, Brand, Currency, SortBy


class TestDateParser:
    def test_accepts_iso_date(self) -> None:
        assert _validate.parse_date("2026-07-22") == date(2026, 7, 22)

    def test_accepts_none(self) -> None:
        assert _validate.parse_date(None) is None

    def test_rejects_malformed(self) -> None:
        with pytest.raises(typer.BadParameter, match="YYYY-MM-DD"):
            _validate.parse_date("07/22/2026")

    def test_rejects_impossible(self) -> None:
        with pytest.raises(typer.BadParameter):
            _validate.parse_date("2026-13-45")


class TestCurrency:
    def test_uppercases_valid_code(self) -> None:
        assert _validate.parse_currency("usd") == Currency.USD

    def test_accepts_enum_name_directly(self) -> None:
        assert _validate.parse_currency("EUR") == Currency.EUR

    def test_rejects_unknown(self) -> None:
        with pytest.raises(typer.BadParameter, match="Currency"):
            _validate.parse_currency("XYZ")

    def test_accepts_none(self) -> None:
        assert _validate.parse_currency(None) is None


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
    def test_both_set(self) -> None:
        assert _validate.parse_price_range(100, 300) == (100, 300)

    def test_only_min(self) -> None:
        assert _validate.parse_price_range(100, None) == (100, None)

    def test_only_max(self) -> None:
        assert _validate.parse_price_range(None, 250) == (None, 250)

    def test_both_none_is_none(self) -> None:
        assert _validate.parse_price_range(None, None) is None

    def test_min_ge_max_rejected(self) -> None:
        with pytest.raises(typer.BadParameter, match="price-min.*price-max"):
            _validate.parse_price_range(300, 100)
