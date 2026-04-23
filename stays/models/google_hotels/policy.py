"""Cancellation policy models.

Lives separately from `detail.py` because policies are referenced by
`RatePlan` (which is in `detail.py`) AND may later be surfaced in
`HotelResult` if we discover cancellation hints in the search response.
Keeping it standalone avoids a circular import.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class CancellationPolicyKind(str, Enum):
    """Cancellation policy categories Google surfaces in the detail page."""

    FREE_CANCELLATION = "free"
    FREE_UNTIL_DATE = "free_until"
    PARTIALLY_REFUNDABLE = "partial"
    NON_REFUNDABLE = "non_refundable"
    UNKNOWN = "unknown"


class CancellationPolicy(BaseModel):
    kind: CancellationPolicyKind = CancellationPolicyKind.UNKNOWN
    free_until: date | None = Field(
        None,
        description="When kind == FREE_UNTIL_DATE, the last calendar date on which cancellation is free.",
    )
    description: str | None = Field(None, description="Raw label Google displayed, if captured.")
