"""Golden-fixture regression tests for serializer output.

These lock the pre-M1 shape of CLI + MCP serializers. Any drift during
the M1 extraction fails these tests, which is the zero-regression guard.
Kept permanently as the canonical serializer contract.
"""

from __future__ import annotations

import json
import pathlib

from tests.fixtures.cli_hotel_sample import make_detail, make_result

FX = pathlib.Path(__file__).parent / "fixtures"


def _canon(obj):
    return json.loads(json.dumps(obj, sort_keys=True, default=str))


def test_serialize_hotel_result_is_byte_identical_to_golden():
    from stays.cli._serialize import serialize_hotel_result

    got = _canon(serialize_hotel_result(make_result()))
    expected = _canon(json.loads((FX / "serialize_golden_result.json").read_text()))
    assert got == expected


def test_serialize_hotel_detail_is_byte_identical_to_golden():
    from stays.cli._serialize import serialize_hotel_detail

    got = _canon(serialize_hotel_detail(make_detail()))
    expected = _canon(json.loads((FX / "serialize_golden_detail.json").read_text()))
    assert got == expected


def test_mcp_serialize_hotel_result_subset_is_byte_identical_to_golden():
    from stays.mcp.server import _serialize_hotel_result

    got = _canon(_serialize_hotel_result(make_result()))
    expected = _canon(json.loads((FX / "serialize_golden_mcp_result.json").read_text()))
    assert got == expected


def test_mcp_serialize_hotel_detail_subset_is_byte_identical_to_golden():
    from stays.mcp.server import _serialize_hotel_detail

    got = _canon(_serialize_hotel_detail(make_detail()))
    expected = _canon(json.loads((FX / "serialize_golden_mcp_detail.json").read_text()))
    assert got == expected
