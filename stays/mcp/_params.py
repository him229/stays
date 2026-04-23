"""Pydantic param models for the Google Hotels MCP server.

Each ``@mcp.tool`` in ``server.py`` builds one of these before dispatching to
an executor. They enforce validation *before* the network call and are
imported directly by tests that drive ``_execute_*_from_params`` with
pre-built param objects.

``server.py`` re-exports every class here so existing tests that import from
``stays.mcp.server`` continue to resolve.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from stays.mcp._config import CONFIG, HARD_MAX_HOTELS_WITH_DETAILS

# =============================================================================
# Typed enums — Literals give schema-level rejection in FastMCP
# =============================================================================

SortByLiteral = Literal["RELEVANCE", "LOWEST_PRICE", "HIGHEST_RATING", "MOST_REVIEWED"]
PropertyTypeLiteral = Literal["HOTELS", "VACATION_RENTALS"]


def _validate_child_ages(children: int, child_ages: list[int] | None) -> list[int] | None:
    """Shared validator for child age lists across params classes (S1).

    Preserves the exact error messages from the original inlined validators —
    tests assert against these strings verbatim.
    """
    if children > 0 and not child_ages:
        raise ValueError(f"child_ages is required when children > 0 (got children={children}, child_ages=None)")
    if child_ages is not None and len(child_ages) != children:
        raise ValueError(f"child_ages length ({len(child_ages)}) must equal children ({children})")
    return child_ages


class SearchHotelsParams(BaseModel):
    query: str = Field(description="City or property query.")
    check_in: str | None = Field(default=None, description="YYYY-MM-DD; omit for flexible dates.")
    check_out: str | None = Field(default=None, description="YYYY-MM-DD; required if check_in is set.")
    adults: int = Field(default=CONFIG.default_adults, ge=1)
    children: int = Field(default=CONFIG.default_children, ge=0, le=8)
    child_ages: list[int] | None = Field(default=None, description="Ages 0-17.")
    currency: str = Field(default=CONFIG.default_currency, min_length=3, max_length=3)
    sort_by: SortByLiteral = CONFIG.default_sort_by
    hotel_class: list[int] | None = None
    amenities: list[str] | None = None
    brands: list[str] | None = None
    min_guest_rating: float | None = Field(default=None, ge=3.5, le=4.5)
    free_cancellation: bool = False
    eco_certified: bool = False
    special_offers: bool = False
    price_min: int | None = Field(default=None, ge=0)
    price_max: int | None = Field(default=None, ge=0)
    property_type: PropertyTypeLiteral = "HOTELS"
    max_results: int | None = Field(default=None, ge=1, le=25, description="Cap on returned hotels count.")

    @model_validator(mode="after")
    def _child_ages_matches_children(self):
        _validate_child_ages(self.children, self.child_ages)
        return self


class GetHotelDetailsParams(BaseModel):
    entity_key: str = Field(description="entity_key from a prior search_hotels result.")
    check_in: str = Field(description="YYYY-MM-DD.")
    check_out: str = Field(description="YYYY-MM-DD after check_in.")
    currency: str = Field(default=CONFIG.default_currency, min_length=3, max_length=3)


class SearchHotelsWithDetailsParams(BaseModel):
    query: str = Field(description="City or property query.")
    check_in: str = Field(description="YYYY-MM-DD — REQUIRED.")
    check_out: str = Field(description="YYYY-MM-DD after check_in — REQUIRED.")
    max_hotels: int = Field(
        default=CONFIG.default_max_hotels_with_details,
        ge=1,
        le=HARD_MAX_HOTELS_WITH_DETAILS,
        description=f"Top-N to enrich. HARD CAP = {HARD_MAX_HOTELS_WITH_DETAILS}.",
    )
    adults: int = Field(default=CONFIG.default_adults, ge=1)
    children: int = Field(default=CONFIG.default_children, ge=0, le=8)
    child_ages: list[int] | None = Field(default=None)
    currency: str = Field(default=CONFIG.default_currency, min_length=3, max_length=3)
    sort_by: SortByLiteral = CONFIG.default_sort_by
    hotel_class: list[int] | None = None
    amenities: list[str] | None = None
    brands: list[str] | None = None
    min_guest_rating: float | None = Field(default=None, ge=3.5, le=4.5)
    free_cancellation: bool = False
    eco_certified: bool = False
    special_offers: bool = False
    price_min: int | None = Field(default=None, ge=0)
    price_max: int | None = Field(default=None, ge=0)
    property_type: PropertyTypeLiteral = "HOTELS"

    @model_validator(mode="after")
    def _child_ages_matches_children(self):
        _validate_child_ages(self.children, self.child_ages)
        return self
