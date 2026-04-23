"""Config surface for the Google Hotels MCP server.

Holds:
- ``HotelSearchConfig`` — ``pydantic-settings`` model driven by ``STAYS_MCP_*``
  env vars.
- ``CONFIG`` — module-level singleton instance.
- ``CONFIG_SCHEMA`` — JSON schema snapshot of ``HotelSearchConfig``.
- ``HARD_MAX_HOTELS_WITH_DETAILS`` — canonical hard cap for the
  ``max_hotels`` parameter on ``search_hotels_with_details`` (S7).

``server.py`` re-exports every name here so existing tests that import from
``stays.mcp.server`` continue to resolve.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Canonical hard cap for ``max_hotels`` on ``search_hotels_with_details``.
#: Every enforcement site (pydantic validators, CLI defaults, prompt copy)
#: must reference this constant rather than repeating the literal.
HARD_MAX_HOTELS_WITH_DETAILS = 15


class HotelSearchConfig(BaseSettings):
    """Optional env-driven defaults for the Google Hotels MCP server."""

    model_config = SettingsConfigDict(env_prefix="STAYS_MCP_")

    default_adults: int = Field(2, ge=1, description="Default adult guests.")
    default_children: int = Field(0, ge=0, le=8, description="Default children count.")
    default_currency: str = Field("USD", min_length=3, max_length=3, description="Fallback currency code (ISO 4217).")
    default_max_hotels_with_details: int = Field(
        5,
        ge=1,
        le=HARD_MAX_HOTELS_WITH_DETAILS,
        description=f"Default N for search_hotels_with_details. HARD CAP {HARD_MAX_HOTELS_WITH_DETAILS}.",
    )
    default_sort_by: str = Field(
        "RELEVANCE",
        description="RELEVANCE | LOWEST_PRICE | HIGHEST_RATING | MOST_REVIEWED.",
    )
    max_results: int | None = Field(
        None,
        gt=0,
        description="Optional cap on result count returned by search_hotels.",
    )


CONFIG = HotelSearchConfig()
CONFIG_SCHEMA = HotelSearchConfig.model_json_schema()
