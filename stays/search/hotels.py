"""Public SearchHotels API.

Detail architecture: there is NO separate detail RPC — `AtySUc` handles
both search (entity_key absent) and detail (entity_key present at outer
slot [2][5]). get_details() builds a HotelSearchFilters with entity_key
set; the filter's format() produces the final request shape with
entity_key at outer [2][5].
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal

from stays.models.google_hotels.base import Currency, DateRange, Location, SortBy
from stays.models.google_hotels.detail import HotelDetail
from stays.models.google_hotels.hotels import RPC_ID, HotelSearchFilters
from stays.models.google_hotels.result import HotelResult
from stays.search.client import (
    BatchExecuteError,
    Client,
    TransientBatchExecuteError,
    get_client,
)
from stays.search.parse import parse_detail_response, parse_search_response

logger = logging.getLogger(__name__)

ErrorKind = Literal["transient", "fatal"]


def _apply_post_sort(results: list[HotelResult], sort_by: SortBy | None) -> list[HotelResult]:
    """Stable-sort parsed results so explicit sort_by produces monotonic output.

    Google's own response order is usually mostly-sorted but has minor
    reorderings within same-price groups (likely pre-tax base rate vs.
    display-rounded USD). Post-sorting guarantees strict monotonicity
    on the requested key. RELEVANCE / None is a no-op.

    Missing values (``None``) always fall to the end so callers reading
    the top of the list still see well-ranked hotels. Ties preserve
    Google's order via Python's stable sort.
    """
    if sort_by is None or sort_by is SortBy.RELEVANCE:
        return results
    if sort_by is SortBy.LOWEST_PRICE:
        return sorted(
            results,
            key=lambda h: (h.display_price is None, h.display_price if h.display_price is not None else 0),
        )
    if sort_by is SortBy.HIGHEST_RATING:
        return sorted(
            results,
            key=lambda h: (h.overall_rating is None, -(h.overall_rating or 0.0)),
        )
    if sort_by is SortBy.MOST_REVIEWED:
        return sorted(
            results,
            key=lambda h: (h.review_count is None, -(h.review_count or 0)),
        )
    return results


class MissingHotelIdError(ValueError):
    """Raised by get_details() when the caller passed an empty / None
    entity_key. Prevents no-op requests hitting the wire."""


@dataclass
class EnrichedResult:
    """Result of one hotel in a ``search_with_details`` call.

    Exactly one of ``detail`` or ``error`` is set:
      * ``detail`` is populated when the detail RPC succeeded for this hotel.
      * ``error`` carries a human-readable message when we skipped or
        failed this hotel. ``error_kind`` classifies the failure so
        retry-aware callers can decide whether to re-issue the request.
        ``result`` is always the list-view record (so callers still
        get name / price / rating even when details fail).
    """

    result: HotelResult
    detail: HotelDetail | None = None
    error: str | None = None
    error_kind: ErrorKind | None = None

    @property
    def ok(self) -> bool:
        return self.detail is not None

    @property
    def is_retryable(self) -> bool:
        """True iff this hotel's failure was transient (retrying may
        succeed). Returns False for fatal errors and for successful
        items — only ``error_kind == "transient"`` is retryable."""
        return self.error_kind == "transient"


class SearchHotels:
    """High-level search API.

    Example::

        from datetime import date
        from stays import HotelSearchFilters, Location, DateRange, GuestInfo, Currency
        from stays.search import SearchHotels

        s = SearchHotels()
        results = s.search(HotelSearchFilters(
            location=Location(query="new york hotels"),
            dates=DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4)),
        ))

        if results[0].entity_key:
            details = s.get_details(
                entity_key=results[0].entity_key,
                dates=DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4)),
            )
            for room in details.rooms:
                print(room.name, [(rp.provider, rp.price) for rp in room.rates])
    """

    def __init__(
        self,
        client: Client | None = None,
        detail_concurrency: int = 4,
    ) -> None:
        self._client = client or get_client()
        self._detail_concurrency = max(1, detail_concurrency)

    def search(self, filters: HotelSearchFilters) -> list[HotelResult]:
        inner_req = filters.format()
        inner_resp = self._client.post_rpc(RPC_ID, inner_req)
        results = parse_search_response(inner_resp)
        return _apply_post_sort(results, filters.sort_by)

    def get_details(
        self,
        entity_key: str,
        dates: DateRange,
        *,
        location: Location | None = None,
        currency: Currency = Currency.USD,
    ) -> HotelDetail:
        """Fetch full detail for one hotel.

        ``entity_key`` is the base64 identifier from
        ``HotelResult.entity_key``. ``dates`` are required because the
        response-side rate plans are computed for the date window.

        ``location`` is optional; Google accepts the detail request
        without a pinned location. If omitted, a neutral query ("hotels")
        is used.

        Returns a ``HotelDetail`` with rooms, rate plans, cancellation
        policies (when resolvable), description, amenities, reviews.
        """
        if not entity_key or not isinstance(entity_key, str):
            raise MissingHotelIdError(f"get_details: entity_key must be a non-empty str; got {entity_key!r}")
        filters = HotelSearchFilters(
            location=location or Location(query="hotels"),
            dates=dates,
            currency=currency,
            entity_key=entity_key,
        )
        inner_req = filters.format()
        inner_resp = self._client.post_rpc(RPC_ID, inner_req)
        return parse_detail_response(inner_resp)

    def search_with_details(self, filters: HotelSearchFilters, max_hotels: int = 5) -> list[EnrichedResult]:
        """Run ``search()``, then fetch detail for the first
        ``max_hotels`` results in parallel. Partial failures are reported
        per-hotel via ``EnrichedResult.error``; the batch never aborts
        on a single transient."""
        if filters.dates is None:
            raise ValueError(
                "search_with_details requires filters.dates so that detail "
                "responses can carry rate plans. Set dates on your HotelSearchFilters."
            )
        results = self.search(filters)
        top = results[:max_hotels]
        workers = min(self._detail_concurrency, max(1, len(top)))
        logger.info("enrich count=%d concurrency=%d", len(top), workers)

        def enrich_one(r: HotelResult) -> EnrichedResult:
            if not r.entity_key:
                logger.warning(
                    "enrich error hotel=%s kind=%s msg=%s",
                    r.name,
                    "fatal",
                    "missing entity_key",
                )
                return EnrichedResult(
                    result=r,
                    error="missing entity_key",
                    error_kind="fatal",
                )
            try:
                detail = self.get_details(
                    entity_key=r.entity_key,
                    dates=filters.dates,
                    location=filters.location,
                    currency=filters.currency,
                )
                return EnrichedResult(result=r, detail=detail)
            except TransientBatchExecuteError as e:
                logger.warning(
                    "enrich error hotel=%s kind=%s msg=%s",
                    r.name,
                    "transient",
                    f"{type(e).__name__}: {e}",
                )
                return EnrichedResult(
                    result=r,
                    error=f"{type(e).__name__}: {e}",
                    error_kind="transient",
                )
            except (BatchExecuteError, MissingHotelIdError) as e:
                logger.warning(
                    "enrich error hotel=%s kind=%s msg=%s",
                    r.name,
                    "fatal",
                    f"{type(e).__name__}: {e}",
                )
                return EnrichedResult(
                    result=r,
                    error=f"{type(e).__name__}: {e}",
                    error_kind="fatal",
                )
            # Unknown exceptions intentionally NOT caught — they propagate
            # so parser bugs / programmer errors surface instead of being
            # silently stringified into per-hotel error fields.

        with ThreadPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(enrich_one, top))
