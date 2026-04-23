"""One in-process FastMCP Client smoke test.

This is NOT the Phase 5 gate (which uses stdio subprocess). It only
proves the server's tool response plumbing is wire-compatible with
fastmcp.Client's call_tool contract.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import Client


@pytest.mark.asyncio
async def test_in_process_call_tool_roundtrip():
    from stays.mcp.server import mcp

    fake_result = MagicMock()
    fake_result.name = "Smoke Hotel"
    fake_result.entity_key = "ek1"
    fake_result.kgmid = "/g/x"
    fake_result.fid = "0x1:0x2"
    fake_result.display_price = 100
    fake_result.currency = "USD"
    fake_result.star_class = 3
    fake_result.overall_rating = 4.0
    fake_result.review_count = 10
    fake_result.lat = 0.0
    fake_result.lng = 0.0
    fake_result.latitude = 0.0
    fake_result.longitude = 0.0
    # Fields the canonical serializer reads but the MCP subset drops.
    fake_result.rate_dates = None
    fake_result.rating_histogram = None
    fake_result.amenities_available = set()
    fake_result.category_ratings = []
    fake_result.nearby = []
    fake_result.image_urls = []
    fake_result.google_hotel_id = None
    fake_result.star_class_label = None
    fake_result.deal_pct = None

    with patch("stays.mcp.server.SearchHotels") as M:
        M.return_value.search.return_value = [fake_result]
        async with Client(mcp) as client:
            result = await client.call_tool("search_hotels", {"query": "smoke test hotels"})
    resp = result.data if result.data is not None else result.structured_content
    assert resp["success"] is True
    assert resp["count"] == 1
    assert resp["hotels"][0]["name"] == "Smoke Hotel"
