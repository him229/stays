"""Reusable LiveFilterCase abstraction for end-to-end filter round-trips.

Each case declares a HotelSearchFilters + assertions that will run against
the real Google endpoint. Use with pytest.mark.parametrize.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from stays import HotelSearchFilters
from stays.search import SearchHotels


@dataclass
class LiveFilterCase:
    label: str
    filters: HotelSearchFilters
    # Wire-level: list of (dot_path, expected_value). Dot path is e.g.
    # "[1].[4].[0].[4]" for the sort slot — resolved by _walk_path below.
    expected_slot_checks: list[tuple[str, Any]] = field(default_factory=list)
    # Response-level assertions
    expect_hotel_count_min: int = 1
    expect_substring_in_response: list[str] = field(default_factory=list)
    # Custom assertion hook — receives (case, parsed_hotels) and can raise.
    custom_assert: Callable[[Any, list], None] | None = None


def _walk_path(tree: Any, path: str) -> Any:
    """Resolve a dotted/bracketed path like '[1].[4].[0]' into `tree`."""
    cur = tree
    for token in re.findall(r"\[(-?\d+)\]", path):
        cur = cur[int(token)]
    return cur


def run_case(case: LiveFilterCase, search: SearchHotels | None = None) -> None:
    """Execute one LiveFilterCase end-to-end. Asserts pass/fail via raise."""
    client_search = search or SearchHotels()
    # Wire check (local — no HTTP)
    format_out = case.filters.format()
    for path, expected in case.expected_slot_checks:
        got = _walk_path(format_out, path)
        assert got == expected, f"[{case.label}] wire slot {path}: expected {expected!r}, got {got!r}"
    # Live round-trip
    results = client_search.search(case.filters)
    assert len(results) >= case.expect_hotel_count_min, (
        f"[{case.label}] got {len(results)} hotels, expected ≥ {case.expect_hotel_count_min}"
    )
    blob = json.dumps([h.model_dump() for h in results], default=str)
    for needle in case.expect_substring_in_response:
        assert needle in blob, f"[{case.label}] response missing {needle!r}"
    if case.custom_assert is not None:
        case.custom_assert(case, results)
    time.sleep(1.0)  # polite delay between live tests


def run_mcp_case(case, dispatcher):
    """Drive an MCP-tool dispatcher entry (e.g.
    `_execute_search_hotels_from_params`) with a `LiveFilterCase`-style
    dict and return the raw response envelope. Parallel to `run_case`
    for the SearchHotels layer, but at the MCP boundary.
    """
    params = case["params"]
    resp = dispatcher(params)
    return resp


__all__ = ["LiveFilterCase", "run_case", "run_mcp_case"]
