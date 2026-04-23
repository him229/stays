"""Unit tests for the stays MCP server.

Three groups:
  1. Tool dispatch — call private _execute_*_from_params with mocked
     SearchHotels; assert envelope shape.
  2. Schema-level rejection — bad params must fail BEFORE _execute_* runs
     (pydantic validation, not {"success": False} envelopes).
  3. LLM-level introspection — list_tools / list_prompts / render_prompt
     / list_resources via fastmcp's async APIs.
"""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from stays.mcp.server import (
    HARD_MAX_HOTELS_WITH_DETAILS,
    GetHotelDetailsParams,
    SearchHotelsParams,
    SearchHotelsWithDetailsParams,
    _execute_get_hotel_details_from_params,
    _execute_search_hotels_from_params,
    _execute_search_hotels_with_details_from_params,
    _serialize_hotel_detail,
    _serialize_hotel_result,
    configuration_resource,
    mcp,
)
from stays.search.client import (
    TransientBatchExecuteError,
)

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


def _fake_result(name="Test Hotel", entity_key="ek123") -> MagicMock:
    r = MagicMock()
    r.name = name
    r.entity_key = entity_key
    r.kgmid = "/g/testing"
    r.fid = "0x111:0x222"
    r.display_price = 199
    r.currency = "USD"
    r.star_class = 4
    r.overall_rating = 4.3
    r.review_count = 500
    r.lat = 40.0
    r.lng = -74.0
    r.latitude = 40.0
    r.longitude = -74.0
    # Fields the canonical serializer reads but the MCP subset drops —
    # set to empty so the shared serializer pass-through doesn't choke
    # on MagicMock defaults (e.g. iterating/unpacking auto-mocks).
    r.rate_dates = None
    r.rating_histogram = None
    r.amenities_available = set()
    r.category_ratings = []
    r.nearby = []
    r.image_urls = []
    r.google_hotel_id = None
    r.star_class_label = None
    r.deal_pct = None
    return r


def _fake_detail(name="Test Hotel") -> MagicMock:
    d = _fake_result(name=name)
    d.description = "nice"
    d.address = "123 St"
    d.phone = "555"
    d.rooms = []
    d.amenity_details = []
    d.nearby_attractions = []
    d.recent_reviews = []
    return d


# ------------------------------------------------------------------
# 1. Tool dispatch — happy path with mocked SearchHotels
# ------------------------------------------------------------------


def test_execute_search_hotels_envelopes_success():
    params = SearchHotelsParams(query="nyc hotels")
    with patch("stays.mcp.server.SearchHotels") as M:
        M.return_value.search.return_value = [_fake_result(), _fake_result("H2", "ek2")]
        resp = _execute_search_hotels_from_params(params)
    assert resp["success"] is True
    assert resp["count"] == 2
    assert resp["hotels"][0]["name"] == "Test Hotel"


def test_execute_get_hotel_details_envelopes_success():
    params = GetHotelDetailsParams(
        entity_key="ek123",
        check_in="2026-09-01",
        check_out="2026-09-03",
    )
    with patch("stays.mcp.server.SearchHotels") as M:
        M.return_value.get_details.return_value = _fake_detail()
        resp = _execute_get_hotel_details_from_params(params)
    assert resp["success"] is True
    assert resp["hotel"]["name"] == "Test Hotel"


def test_execute_search_hotels_with_details_envelopes_success():
    params = SearchHotelsWithDetailsParams(
        query="paris hotels",
        check_in="2026-09-01",
        check_out="2026-09-03",
        max_hotels=3,
    )
    with patch("stays.mcp.server.SearchHotels") as M:
        er = MagicMock()
        er.ok = True
        er.result = _fake_result()
        er.detail = _fake_detail()
        er.error = None
        M.return_value.search_with_details.return_value = [er, er, er]
        resp = _execute_search_hotels_with_details_from_params(params)
    assert resp["success"] is True
    assert resp["count"] == 3
    assert resp["items"][0]["ok"] is True


# ------------------------------------------------------------------
# 2. Semantic failures — runtime exceptions surface as envelopes
# ------------------------------------------------------------------


def test_execute_search_hotels_transient_failure_envelopes():
    params = SearchHotelsParams(query="nyc hotels")
    with patch("stays.mcp.server.SearchHotels") as M:
        M.return_value.search.side_effect = TransientBatchExecuteError("boom")
        resp = _execute_search_hotels_from_params(params)
    assert resp["success"] is False
    assert "TransientBatchExecuteError" in resp["error"]


def test_execute_get_hotel_details_missing_id_envelopes():
    params = GetHotelDetailsParams(
        entity_key="whatever",
        check_in="2026-09-01",
        check_out="2026-09-03",
    )
    from stays.search.hotels import MissingHotelIdError

    with patch("stays.mcp.server.SearchHotels") as M:
        M.return_value.get_details.side_effect = MissingHotelIdError("nope")
        resp = _execute_get_hotel_details_from_params(params)
    assert resp["success"] is False
    assert "MissingHotelIdError" in resp["error"]


# ------------------------------------------------------------------
# 3. Schema-level rejection (pydantic raises BEFORE _execute_*)
# ------------------------------------------------------------------


def test_schema_rejects_max_hotels_over_15():
    with pytest.raises(ValidationError):
        SearchHotelsWithDetailsParams(
            query="x",
            check_in="2026-09-01",
            check_out="2026-09-03",
            max_hotels=16,
        )


def test_schema_rejects_short_currency():
    with pytest.raises(ValidationError):
        SearchHotelsParams(query="x", currency="US")


def test_schema_rejects_invalid_sort_literal():
    with pytest.raises(ValidationError):
        SearchHotelsParams(query="x", sort_by="PRICE_LOW_TO_HIGH")


def test_schema_rejects_child_ages_mismatch():
    with pytest.raises(ValidationError):
        SearchHotelsParams(
            query="x",
            children=2,
            child_ages=[5, 6, 7],
        )


def test_schema_rejects_children_without_ages():
    with pytest.raises(ValidationError):
        SearchHotelsParams(query="x", children=2)


# ------------------------------------------------------------------
# 4. Serialization helpers
# ------------------------------------------------------------------


def test_serialize_hotel_result_has_required_fields():
    out = _serialize_hotel_result(_fake_result())
    for field in ("name", "entity_key", "display_price", "star_class"):
        assert field in out


def test_serialize_hotel_detail_has_detail_fields():
    out = _serialize_hotel_detail(_fake_detail())
    for field in ("description", "address", "rooms"):
        assert field in out


# ------------------------------------------------------------------
# 5. Configuration resource
# ------------------------------------------------------------------


def test_configuration_resource_is_valid_json():
    import json as j

    payload = j.loads(configuration_resource())
    assert "defaults" in payload
    assert "schema" in payload
    assert "environment" in payload
    assert "STAYS_RPS" in payload["environment"]["variables"]


# ------------------------------------------------------------------
# 6. LLM-level introspection (fastmcp async APIs)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_returns_three_with_annotations():
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {"search_hotels", "get_hotel_details", "search_hotels_with_details"}
    for t in tools:
        assert t.annotations.readOnlyHint is True
        assert t.annotations.idempotentHint is True


@pytest.mark.asyncio
async def test_list_prompts_returns_two():
    prompts = await mcp.list_prompts()
    names = {p.name for p in prompts}
    assert names == {"when-to-deep-search", "compare-hotels-in-city"}


@pytest.mark.asyncio
async def test_render_prompt_when_to_deep_search():
    result = await mcp.render_prompt(
        "when-to-deep-search",
        {"user_intent": "compare 3 hotels in Paris"},
    )
    text = result.messages[0].content.text
    assert "search_hotels_with_details" in text
    assert "compare 3 hotels in Paris" in text


@pytest.mark.asyncio
async def test_when_to_deep_search_prompt_references_hard_max_constant():
    """S7: prompt must cite the canonical HARD_MAX_HOTELS_WITH_DETAILS cap.

    Before S7 the prompt said "10 is the hard maximum" while the code
    enforced 15. This test locks the prompt to the constant to prevent
    the text from drifting out of sync with enforcement again.
    """
    result = await mcp.render_prompt("when-to-deep-search", {"user_intent": ""})
    text = result.messages[0].content.text
    assert str(HARD_MAX_HOTELS_WITH_DETAILS) in text
    assert "10 is the hard maximum" not in text


@pytest.mark.asyncio
async def test_tool_docstring_matches_hard_max_constant():
    """S7 docstring guard: the ``search_hotels_with_details`` tool docstring
    (which FastMCP exposes as the tool description) must cite the same hard
    cap the code enforces. Python does not evaluate f-strings as docstrings,
    so the docstring uses the literal and this test checks they stay in sync.
    """
    from stays.mcp.server import search_hotels_with_details as tool

    # FastMCP may wrap the function; probe the underlying callable for __doc__.
    raw_doc = getattr(tool, "__doc__", None) or getattr(getattr(tool, "fn", None), "__doc__", None)
    assert raw_doc is not None
    assert f"HARD-CAPPED at {HARD_MAX_HOTELS_WITH_DETAILS}" in raw_doc


@pytest.mark.asyncio
async def test_when_to_deep_search_prompt_matches_fixture():
    """S7: snapshot the prompt body to a golden fixture.

    The fixture at ``tests/fixtures/prompt_when_to_deep_search.txt`` is the
    permanent prompt-text golden. Any prompt edit must be accompanied by a
    deliberate fixture update.
    """
    from pathlib import Path

    result = await mcp.render_prompt("when-to-deep-search", {"user_intent": ""})
    rendered = result.messages[0].content.text
    fixture_path = Path(__file__).parent / "fixtures" / "prompt_when_to_deep_search.txt"
    expected = fixture_path.read_text()
    assert rendered == expected


@pytest.mark.asyncio
async def test_list_resources_contains_configuration():
    resources = await mcp.list_resources()
    uris = {str(r.uri) for r in resources}
    assert "resource://stays-mcp/configuration" in uris
