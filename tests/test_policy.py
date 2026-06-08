"""Unit tests for CancellationPolicy."""

from datetime import date

import pytest

from stays import CancellationPolicy, CancellationPolicyKind
from stays.search.parse.policy_parser import _parse_cancellation
from stays.search.parse.provider_parser import _parse_cancellation_tuple


def test_default_kind_is_unknown():
    p = CancellationPolicy()
    assert p.kind == CancellationPolicyKind.UNKNOWN
    assert p.free_until is None
    assert p.description is None


def test_free_until_date_populated():
    p = CancellationPolicy(
        kind=CancellationPolicyKind.FREE_UNTIL_DATE,
        free_until=date(2026, 9, 1),
        description="Free cancellation until Sep 1, 2026",
    )
    assert p.free_until == date(2026, 9, 1)


def test_structured_cancellation_uses_reference_year_for_month_day():
    policy = _parse_cancellation_tuple([True, "Apr 24", "11:59 PM"], reference_year=2026)

    assert policy is not None
    assert policy.kind == CancellationPolicyKind.FREE_UNTIL_DATE
    assert policy.free_until == date(2026, 4, 24)


def test_text_cancellation_uses_reference_year_for_month_day():
    policy = _parse_cancellation("Free cancellation until Apr 24", reference_year=2026)

    assert policy is not None
    assert policy.kind == CancellationPolicyKind.FREE_UNTIL_DATE
    assert policy.free_until == date(2026, 4, 24)


@pytest.mark.parametrize("kind", list(CancellationPolicyKind))
def test_all_kinds_constructable(kind):
    p = CancellationPolicy(kind=kind)
    assert p.kind == kind
