"""Golden-file regression tests — the output of parse.* must remain
byte-identical throughout Phase 2. Kept permanently as the parser contract."""

import json
import pathlib

from stays.search.parse import parse_detail_response, parse_search_response

FX = pathlib.Path(__file__).parent / "fixtures"


def _deep_sort(obj):
    """Recursively sort dict keys and list contents for stable comparison.

    Lists that originate from ``set[...]`` fields (e.g. ``amenities_available``)
    are order-unstable across Python processes; deep-sorting normalizes them.
    """
    if isinstance(obj, dict):
        return {k: _deep_sort(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        sorted_children = [_deep_sort(x) for x in obj]
        try:
            return sorted(sorted_children, key=lambda x: json.dumps(x, sort_keys=True, default=str))
        except TypeError:
            return sorted_children
    return obj


def _canon(obj):
    return _deep_sort(json.loads(json.dumps(obj, sort_keys=True, default=str)))


def test_parse_search_output_is_stable():
    inp = json.loads((FX / "search_response_nyc.json").read_text())
    got = [r.model_dump(mode="json") for r in parse_search_response(inp)]
    expected = json.loads((FX / "parse_golden_search.json").read_text())
    assert _canon(got) == _canon(expected)


def test_parse_detail_output_is_stable():
    inp = json.loads((FX / "detail_response_sample.json").read_text())
    got = parse_detail_response(inp).model_dump(mode="json")
    expected = json.loads((FX / "parse_golden_detail.json").read_text())
    assert _canon(got) == _canon(expected)
