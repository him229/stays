"""Unit tests for CancellationPolicy."""

from datetime import date

import pytest

from stays import CancellationPolicy, CancellationPolicyKind


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


@pytest.mark.parametrize("kind", list(CancellationPolicyKind))
def test_all_kinds_constructable(kind):
    p = CancellationPolicy(kind=kind)
    assert p.kind == kind
