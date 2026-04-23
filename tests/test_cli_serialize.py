"""Tests for stays.cli._serialize."""

from __future__ import annotations

import json

from stays.cli import _serialize
from tests.fixtures.cli_hotel_sample import make_detail, make_result


class TestSerializeHotelResult:
    def test_basic_fields(self) -> None:
        result = make_result()
        payload = _serialize.serialize_hotel_result(result)
        assert payload["name"] == "Tokyo Central Hotel"
        assert payload["entity_key"] == "CgoI_TEST_KEY_0001"
        assert payload["star_class"] == 4
        assert payload["display_price"] == 180
        assert payload["currency"] == "USD"

    def test_amenities_sorted_list(self) -> None:
        payload = _serialize.serialize_hotel_result(make_result())
        assert isinstance(payload["amenities"], list)
        assert payload["amenities"] == sorted(payload["amenities"])

    def test_roundtrip_is_json_safe(self) -> None:
        payload = _serialize.serialize_hotel_result(make_result())
        json.dumps(payload)  # raises if non-serializable


class TestSerializeHotelDetail:
    def test_rooms_included(self) -> None:
        payload = _serialize.serialize_hotel_detail(make_detail())
        assert "rooms" in payload
        assert payload["rooms"][0]["name"] == "Deluxe Double"
        assert payload["rooms"][0]["rates"][0]["provider"] == "Booking.com"

    def test_detail_is_json_safe(self) -> None:
        """Regression guard: free_until (date) must serialize as ISO string."""
        payload = _serialize.serialize_hotel_detail(make_detail())
        # json.dumps raises TypeError if any date/datetime leaks through.
        dumped = json.dumps(payload)
        assert "2026-07-20" in dumped  # free_until is ISO, not repr

    def test_cancellation_free_until_is_isoformat(self) -> None:
        payload = _serialize.serialize_hotel_detail(make_detail())
        cancellation = payload["rooms"][0]["rates"][0]["cancellation"]
        assert cancellation["free_until"] == "2026-07-20"

    def test_address_and_phone(self) -> None:
        payload = _serialize.serialize_hotel_detail(make_detail())
        assert payload["address"].startswith("1-1-1")
        assert payload["phone"]


class TestSuccessEnvelope:
    def test_search_envelope_shape(self) -> None:
        env = _serialize.build_success(
            search_type="search",
            query={"query": "tokyo"},
            results_key="hotels",
            results=[{"name": "X"}],
        )
        assert env["success"] is True
        assert env["data_source"] == "google_hotels"
        assert env["search_type"] == "search"
        assert env["query"] == {"query": "tokyo"}
        assert env["count"] == 1
        assert env["hotels"] == [{"name": "X"}]


class TestErrorEnvelope:
    def test_validation_error(self) -> None:
        env = _serialize.build_error(
            search_type="search",
            message="bad date",
            error_type="validation_error",
            query={"query": "tokyo"},
        )
        assert env["success"] is False
        assert env["error"]["type"] == "validation_error"
        assert env["error"]["message"] == "bad date"
        assert env["query"] == {"query": "tokyo"}

    def test_no_query_optional(self) -> None:
        env = _serialize.build_error(
            search_type="details",
            message="network down",
            error_type="network_error",
        )
        assert "query" not in env
