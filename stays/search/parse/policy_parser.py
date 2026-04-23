"""Cancellation-policy parsers.

Secondary text parser (used when Google surfaces a human-readable
cancellation label instead of the structured tuple handled by
``provider_parser._parse_cancellation_tuple``).
"""

from __future__ import annotations

import re
from datetime import date as _date
from datetime import datetime as _dt_cls

from stays.models.google_hotels.policy import (
    CancellationPolicy,
    CancellationPolicyKind,
)

__all__ = ["_parse_cancellation"]


def _parse_cancellation(text: str) -> CancellationPolicy | None:
    """Extract a CancellationPolicy from a Google cancellation label string.

    Handles whitespace-padded strings like:
      "\n   Free cancellation until Apr 25\n "
      "Non-refundable"
      "Partially refundable"
    """
    t = text.strip()
    if not t:
        return None

    # Free cancellation until <date>
    m = re.search(
        r"free cancellation until\s+([A-Za-z]+ \d{1,2}(?:,?\s*\d{4})?)",
        t,
        re.IGNORECASE,
    )
    if m:
        raw_date = m.group(1).strip().rstrip(",")
        free_until: _date | None = None
        for fmt in ("%b %d %Y", "%B %d %Y", "%b %d", "%B %d"):
            try:
                parsed = _dt_cls.strptime(raw_date, fmt)
                if parsed.year == 1900:
                    # No year in format — use current year, advance to next if past
                    today = _date.today()
                    parsed = parsed.replace(year=today.year)
                    if parsed.date() < today:
                        parsed = parsed.replace(year=today.year + 1)
                free_until = parsed.date()
                break
            except ValueError:
                continue
        return CancellationPolicy(
            kind=CancellationPolicyKind.FREE_UNTIL_DATE,
            free_until=free_until,
            description=t,
        )

    # Generic free cancellation (no date)
    if re.search(r"free cancellation", t, re.IGNORECASE):
        return CancellationPolicy(
            kind=CancellationPolicyKind.FREE_CANCELLATION,
            description=t,
        )

    # Partially refundable
    if re.search(r"partial(ly)? refund", t, re.IGNORECASE):
        return CancellationPolicy(
            kind=CancellationPolicyKind.PARTIALLY_REFUNDABLE,
            description=t,
        )

    # Non-refundable
    if re.search(r"non.?refundable|no cancel|fully refundable\b.*not", t, re.IGNORECASE):
        return CancellationPolicy(
            kind=CancellationPolicyKind.NON_REFUNDABLE,
            description=t,
        )

    return None
