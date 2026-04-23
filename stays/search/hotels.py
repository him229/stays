"""Public SearchHotels API.

Detail architecture: there is NO separate detail RPC — `AtySUc` handles
both search (entity_key absent) and detail (entity_key present at outer
slot [2][5]). get_details() builds the detail request by calling
filters.format() then overlaying the entity_key into slot [2][5].
"""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from stays.models.google_hotels.base import Currency, DateRange, Location
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


class MissingHotelIdError(ValueError):
    """Raised by get_details() when the caller passed an empty / None
    entity_key. Prevents no-op requests hitting the wire."""


@dataclass
class EnrichedResult:
    """Result of one hotel in a ``search_with_details`` call.

    Exactly one of ``detail`` or ``error`` is set:
      * ``detail`` is populated when the detail RPC succeeded for this hotel.
      * ``error`` carries a human-readable message when we skipped or
        failed this hotel. ``result`` is always the list-view record (so
        callers still get name / price / rating even when details fail).
    """

    result: HotelResult
    detail: HotelDetail | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.detail is not None


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
        return parse_search_response(inner_resp)

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
        )
        inner_req = filters.format()
        # Overlay entity_key into the outer request metadata at [2][5].
        inner_req = self._with_entity_key(inner_req, entity_key)
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

        def enrich_one(r: HotelResult) -> EnrichedResult:
            if not r.entity_key:
                return EnrichedResult(result=r, error="missing entity_key")
            try:
                detail = self.get_details(
                    entity_key=r.entity_key,
                    dates=filters.dates,
                    location=filters.location,
                    currency=filters.currency,
                )
                return EnrichedResult(result=r, detail=detail)
            except (BatchExecuteError, TransientBatchExecuteError, MissingHotelIdError) as e:
                return EnrichedResult(result=r, error=f"{type(e).__name__}: {e}")
            except Exception as e:  # noqa: BLE001 — unexpected is reported, not raised
                return EnrichedResult(result=r, error=f"unexpected: {type(e).__name__}: {e}")

        with ThreadPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(enrich_one, top))

    @staticmethod
    def _with_entity_key(inner_req: list, entity_key: str) -> list:
        """Return a deep-copied inner_req with entity_key set at outer [2][5].

        The outer payload is ``[query, SearchParams, RequestMeta, ...]``.
        Task 11 will instead plumb entity_key through HotelSearchFilters
        directly; until then we overlay it here.
        """
        payload = copy.deepcopy(inner_req)
        # Ensure outer[2] exists and is a list of length >= 6.
        while len(payload) < 3:
            payload.append(None)
        meta = payload[2]
        if not isinstance(meta, list):
            meta = [None] * 6
        while len(meta) < 6:
            meta.append(None)
        meta[5] = entity_key
        payload[2] = meta
        return payload
