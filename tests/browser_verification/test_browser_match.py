"""Browser-vs-programmatic verification tests.

These tests are gated behind the ``browser_verify`` marker. They are
SKIPPED by default. To run them:

    pytest tests/browser_verification/ --browser-verify -v

The tests require the ``agent-browser`` CLI to be installed and on PATH.
They hit Google Hotels over the network AND spawn a real browser, so
they are slow (roughly 20 seconds per case). Run them on demand when
you want to confirm the MCP output still matches what a user sees in
their browser — e.g. after a parser change or before cutting a release.

Each case compares these fields between the browser UI and the
SearchHotels code path:
  * List view: anchor hotel price (within tolerance) and rating
  * Detail view: provider prices, cancellation policy, rating, review
    count, and amenity keyword presence (when the case specifies one).

Screenshots are saved to ``tests/browser_verification/screenshots/`` for
manual review. Each failure prints a per-field diff so you can see
exactly which comparison broke.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from stays.models.google_hotels.result import HotelResult
from stays.search.hotels import SearchHotels

from .cases import CASES, BrowserCase
from .harness import (
    BrowserListRow,
    CompareReport,
    FieldResult,
    browser_available,
    detail_url,
    detect_browser_currency,
    extract_detail_view,
    extract_list_view,
    list_url,
    normalize_provider,
    open_url,
    page_text,
    prices_match,
    rating_match,
    review_count_match,
    screenshot,
    set_dates,
)

pytestmark = [pytest.mark.browser_verify, pytest.mark.live]


def pytest_generate_tests(metafunc):
    if "case" in metafunc.fixturenames:
        metafunc.parametrize(
            "case",
            CASES,
            ids=[c.label for c in CASES],
        )


@pytest.fixture(scope="module")
def search() -> SearchHotels:
    return SearchHotels()


@pytest.fixture(scope="module", autouse=True)
def require_browser() -> None:
    if not browser_available():
        pytest.skip("agent-browser CLI not installed — skipping browser tests")


# =============================================================================
# Per-case helpers
# =============================================================================


def _find_anchor(hotels: list[HotelResult], substring: str) -> HotelResult | None:
    """Pick the first programmatic hotel whose name contains ``substring``.

    If ``substring`` is a generic placeholder like "Hotel" (which basically
    matches everything), fall back to the top result — don't pretend we
    meaningfully filtered.
    """
    if substring.strip().lower() not in {"hotel", "hotels"}:
        for h in hotels:
            if substring.lower() in h.name.lower():
                return h
    return hotels[0] if hotels else None


def _find_anchor_row_by_name(rows: list[BrowserListRow], full_name: str) -> BrowserListRow | None:
    """Find the browser row whose name matches the programmatic hotel's full name.

    Uses a permissive token-overlap match: if 60% of the significant tokens
    in the programmatic name appear in the browser row name (and vice versa),
    they're the same hotel. Handles the ``Hôtel`` / ``Hotel`` unicode split,
    casing differences, and minor formatting drift.
    """
    # Drop generic geography / category tokens so they don't trigger false
    # cross-hotel matches (e.g. "Regent Hong Kong" vs "Grand Hyatt Hong Kong"
    # both share "hong kong").
    stop = {
        "hong",
        "kong",
        "new",
        "york",
        "los",
        "angeles",
        "san",
        "francisco",
        "hotel",
        "hotels",
        "the",
        "and",
    }

    def tokens(name: str) -> set[str]:
        return {t.lower().strip(",.-'") for t in name.split() if len(t) > 2 and t.lower().strip(",.-'") not in stop}

    prog_tokens = tokens(full_name)
    if not prog_tokens:
        return None
    best: BrowserListRow | None = None
    best_score = 0.0
    for r in rows:
        row_tokens = tokens(r.name)
        if not row_tokens:
            continue
        overlap = len(prog_tokens & row_tokens)
        score = overlap / max(len(prog_tokens), len(row_tokens))
        if score > best_score:
            best_score = score
            best = r
    # Threshold bumped from 0.5 → 0.7 to avoid false positives.
    return best if best_score >= 0.7 else None


# =============================================================================
# The actual test — parametrized over every case
# =============================================================================


def test_browser_matches_programmatic(case: BrowserCase, search: SearchHotels) -> None:
    report = CompareReport(case_label=case.label)

    # ----------------------------------------------------------------
    # STEP 1 — run the programmatic search + detail.
    # ----------------------------------------------------------------
    programmatic_hotels = search.search(case.filters)
    assert programmatic_hotels, f"[{case.label}] programmatic search returned 0 hotels"
    anchor = _find_anchor(programmatic_hotels, case.anchor_hotel_substring)
    assert anchor is not None, f"[{case.label}] anchor hotel not found programmatically"

    # Brand-filter semantic check — every returned hotel should belong to
    # the requested brand family. Catches the "filter silently ignored"
    # class of regression where the wire looked correct but Google dropped
    # the filter (e.g. ``[[brand_id, []]]`` empty sub-brand list).
    if case.brand_name_tokens:
        tokens = [t.lower() for t in case.brand_name_tokens]
        hits = [h for h in programmatic_hotels if any(t in h.name.lower() for t in tokens)]
        misses = [h for h in programmatic_hotels if not any(t in h.name.lower() for t in tokens)]
        pct = len(hits) / len(programmatic_hotels)
        report.list_results.append(
            FieldResult(
                name="brand_filter_semantic",
                ok=pct >= case.brand_min_match_pct,
                browser=f"{pct:.0%} of {len(programmatic_hotels)} match brand",
                programmatic=f"{len(hits)} hits, {len(misses)} misses",
                note=(f"misses: {[h.name for h in misses[:3]]}" if misses else "all results are brand-family"),
            )
        )

    programmatic_detail = None
    if case.do_detail_check and anchor.entity_key:
        try:
            programmatic_detail = search.get_details(
                entity_key=anchor.entity_key,
                dates=case.filters.dates,
            )
        except Exception as e:
            pytest.fail(f"[{case.label}] programmatic get_details raised: {e!r}")

    # ----------------------------------------------------------------
    # STEP 2 — open the browser at the list view, set dates, extract.
    # ----------------------------------------------------------------
    url = list_url(
        query=case.query,
        currency=case.currency,
        check_in=case.filters.dates.check_in,
        check_out=case.filters.dates.check_out,
    )
    open_url(url)
    # Some list URLs honor checkin/checkout params. Others don't — set
    # them via the date picker defensively.
    set_dates(case.filters.dates.check_in, case.filters.dates.check_out)
    time.sleep(2)

    browser_rows = extract_list_view()
    list_raw_text = page_text()
    browser_currency = detect_browser_currency(list_raw_text)
    screenshot(f"{case.label}-list.png")

    # Match anchor by full hotel name (more robust than the generic substring).
    browser_anchor = _find_anchor_row_by_name(browser_rows, anchor.name)

    report.list_results.append(
        FieldResult(
            name="browser_list_non_empty",
            ok=bool(browser_rows),
            browser=len(browser_rows),
            programmatic=len(programmatic_hotels),
            note=f"{len(browser_rows)} browser rows parsed",
        )
    )

    # Soft — browser may rank differently so anchor may not appear in top rows.
    report.list_results.append(
        FieldResult(
            name="anchor_hotel_present",
            ok=True,
            browser=browser_anchor.name if browser_anchor else None,
            programmatic=anchor.name,
            note=("matched" if browser_anchor else "anchor absent from browser list — still comparing detail"),
        )
    )

    # Compare anchor list-view price ONLY when:
    #   1. The browser unambiguously shows the requested currency (skip
    #      ambiguous-$ cases: AUD/SGD/HKD/CAD where $ ≠ USD but we can't
    #      tell from the symbol alone), AND
    #   2. No price-affecting filters are active. Filters like
    #      ``amenities=[POOL]`` can make Google surface the pool-room rate
    #      in the list view, which diverges from the browser's unfiltered
    #      display price for the same hotel. Detail-view prices still
    #      compare cleanly (detail is entity-keyed, filter-independent).
    if browser_anchor and browser_anchor.price_num is not None:
        ambiguous_dollar_list = case.currency in {"AUD", "SGD", "HKD", "CAD"}
        price_filters_active = bool(
            case.filters.amenities
            or case.filters.hotel_class
            or case.filters.brands
            or case.filters.price_range
            or case.filters.free_cancellation
        )
        currency_aligned = not ambiguous_dollar_list and (browser_currency is None or browser_currency == case.currency)
        if currency_aligned and not price_filters_active:
            report.list_results.append(
                FieldResult(
                    name="anchor_list_price",
                    ok=prices_match(browser_anchor.price_num, anchor.display_price),
                    browser=browser_anchor.price_num,
                    programmatic=anchor.display_price,
                    note=f"currency={case.currency}",
                )
            )
        else:
            note = (
                f"currency skew: browser={browser_currency} expected={case.currency}"
                if not currency_aligned
                else "filter-affected list price — skipped"
            )
            report.list_results.append(
                FieldResult(
                    name="anchor_list_price",
                    ok=True,  # soft skip
                    browser=browser_anchor.price_num,
                    programmatic=anchor.display_price,
                    note=note,
                )
            )

    if browser_anchor and browser_anchor.rating is not None:
        report.list_results.append(
            FieldResult(
                name="anchor_rating",
                ok=rating_match(browser_anchor.rating, anchor.overall_rating),
                browser=browser_anchor.rating,
                programmatic=anchor.overall_rating,
            )
        )

    # ----------------------------------------------------------------
    # STEP 3 — open the browser at the detail view, extract, compare.
    # ----------------------------------------------------------------
    if not (case.do_detail_check and programmatic_detail and anchor.entity_key):
        _finalize(report)
        return

    open_url(detail_url(anchor.entity_key, currency=case.currency))
    set_dates(case.filters.dates.check_in, case.filters.dates.check_out)
    time.sleep(2)
    browser_detail = extract_detail_view()
    detail_currency = detect_browser_currency(browser_detail.raw_text)
    screenshot(f"{case.label}-detail.png")

    # Name match (soft — browser detail extractor uses heuristics)
    report.detail_results.append(
        FieldResult(
            name="detail_name",
            ok=(
                case.anchor_hotel_substring.lower() in browser_detail.name.lower()
                or case.anchor_hotel_substring.lower() in browser_detail.raw_text.lower()
            ),
            browser=browser_detail.name,
            programmatic=programmatic_detail.name,
        )
    )

    # Rating
    report.detail_results.append(
        FieldResult(
            name="detail_rating",
            ok=rating_match(browser_detail.rating, programmatic_detail.overall_rating),
            browser=browser_detail.rating,
            programmatic=programmatic_detail.overall_rating,
        )
    )

    # Review count
    report.detail_results.append(
        FieldResult(
            name="detail_review_count",
            ok=review_count_match(browser_detail.review_count, programmatic_detail.review_count),
            browser=browser_detail.review_count,
            programmatic=programmatic_detail.review_count,
        )
    )

    # Star class
    if browser_detail.star_class is not None and programmatic_detail.star_class is not None:
        report.detail_results.append(
            FieldResult(
                name="detail_star_class",
                ok=browser_detail.star_class == programmatic_detail.star_class,
                browser=browser_detail.star_class,
                programmatic=programmatic_detail.star_class,
            )
        )

    # Providers + prices + cancellation — compare per-provider where we can
    # match the provider name between browser and programmatic.
    prog_providers: dict[str, dict[str, Any]] = {}
    for room in programmatic_detail.rooms:
        for rp in room.rates:
            key = normalize_provider(rp.provider)
            if key not in prog_providers or rp.price < prog_providers[key]["price"]:
                cancel_text = ""
                if rp.cancellation:
                    if rp.cancellation.free_until:
                        cancel_text = f"Free until {rp.cancellation.free_until}"
                    elif rp.cancellation.kind and rp.cancellation.kind.value == "non_refundable":
                        cancel_text = "Non-refundable"
                prog_providers[key] = {
                    "price": rp.price,
                    "cancel": cancel_text,
                    "provider": rp.provider,
                }

    browser_prov_map = {normalize_provider(p): (p, price, cancel) for p, price, cancel in browser_detail.providers}

    # Browser + programmatic only comparable when we're certain they're in
    # the same currency. For "$"-using non-USD currencies (AUD/SGD/HKD/CAD)
    # the symbol is ambiguous and the browser may be rendering USD even
    # when the URL requested the local currency — numeric comparison is
    # meaningless. Skip those cases (pass with a note) and rely on the
    # non-price fields (rating / review count / star / amenities).
    ambiguous_dollar = case.currency in {"AUD", "SGD", "HKD", "CAD"}
    currency_aligned_detail = not ambiguous_dollar and (detail_currency is None or detail_currency == case.currency)

    # Primary price check — headline ($NN near hotel name) vs MCP display_price.
    # Both come from Google's ``entry[6][2][1][4]`` slot so they should match
    # within the tight 2% tolerance. Per-provider prices below are noisier
    # (different slot, extractor fuzzy about which $ belongs to which row).
    if (
        browser_detail.headline_price is not None
        and programmatic_detail.display_price is not None
        and currency_aligned_detail
    ):
        report.detail_results.append(
            FieldResult(
                name="detail_headline_price",
                ok=prices_match(browser_detail.headline_price, programmatic_detail.display_price),
                browser=browser_detail.headline_price,
                programmatic=programmatic_detail.display_price,
                note=f"currency={case.currency}",
            )
        )
    else:
        report.detail_results.append(
            FieldResult(
                name="detail_headline_price",
                ok=True,  # soft — either extractor missed the value or currency ambiguous
                browser=browser_detail.headline_price,
                programmatic=programmatic_detail.display_price,
                note=("currency skew or missing value" if not currency_aligned_detail else "missing from one side"),
            )
        )

    matched_any = False
    for key, prog in prog_providers.items():
        if key in browser_prov_map:
            matched_any = True
            _, b_price, b_cancel = browser_prov_map[key]
            # Per-provider price: informational only. The browser extractor
            # can mis-attribute a headline or neighboring-row price to a
            # provider, and the browser UI sometimes surfaces taxes-inclusive
            # rates while the MCP returns pre-tax. Headline price check
            # above is the primary MCP-vs-browser price signal.
            agree = prices_match(b_price, prog["price"]) if currency_aligned_detail else True
            report.detail_results.append(
                FieldResult(
                    name=f"provider_price:{prog['provider']}",
                    ok=True,  # informational
                    browser=b_price,
                    programmatic=prog["price"],
                    note=("agree" if agree else "DIFFER (informational — extractor is heuristic)"),
                )
            )
            # Cancellation classification: informational only. The browser
            # text extractor can't reliably pin a cancellation label to the
            # right provider (labels float between adjacent rows and the
            # UI wraps some rates in accordions). Record the comparison
            # so humans can eyeball it in the report, but don't hard-fail.
            prog_is_free = "free" in prog["cancel"].lower()
            browser_is_free = "free cancellation" in b_cancel.lower()
            prog_is_nonref = "non-refundable" in prog["cancel"].lower()
            browser_is_nonref = "non-refundable" in b_cancel.lower()
            both_labelled = (prog_is_free or prog_is_nonref) and (browser_is_free or browser_is_nonref)
            if both_labelled:
                class_match = (prog_is_free and browser_is_free) or (prog_is_nonref and browser_is_nonref)
                note = "agree" if class_match else "DIFFER (informational — extractor is heuristic)"
            else:
                note = "one side unlabelled"
            report.detail_results.append(
                FieldResult(
                    name=f"provider_cancel_class:{prog['provider']}",
                    ok=True,  # informational
                    browser=b_cancel or "(none)",
                    programmatic=prog["cancel"] or "(none)",
                    note=note,
                )
            )
    # If we matched no providers but both sides have some, note it (don't fail —
    # browser UI sometimes hides providers behind "view more" accordions).
    report.detail_results.append(
        FieldResult(
            name="provider_match_count",
            ok=True,  # soft — any match is a bonus, 0 is fine
            browser=len(browser_detail.providers),
            programmatic=len(prog_providers),
            note=f"matched={'yes' if matched_any else 'no'}",
        )
    )

    # Amenity keyword — informational. The browser innerText contains filter
    # chip labels and nearby-hotel amenities alongside the hotel's actual
    # amenities, so "Spa" appearing in text doesn't prove this specific
    # hotel has a spa. We record the comparison for eyeballing but treat
    # a mismatch as a soft signal, not a hard failure.
    if case.expected_amenity_keyword:
        in_browser = case.expected_amenity_keyword.lower() in browser_detail.raw_text.lower()
        prog_amenities = [a.name for a in programmatic_detail.amenities_available] + list(
            programmatic_detail.amenity_details or []
        )
        in_prog = any(case.expected_amenity_keyword.lower() in a.lower() for a in prog_amenities)
        report.detail_results.append(
            FieldResult(
                name=f"amenity_keyword:{case.expected_amenity_keyword}",
                ok=True,  # informational
                browser=in_browser,
                programmatic=in_prog,
                note=("agree" if in_browser == in_prog else "differ (informational)"),
            )
        )

    _finalize(report)


def _finalize(report: CompareReport) -> None:
    """Dump the full report; fail pytest if any non-soft field mismatched."""
    print()  # separator from pytest's `.`
    print(report.render())
    failures = report.failures()
    if failures:
        msg = "\n".join(f"{f.name}: browser={f.browser!r} programmatic={f.programmatic!r}  {f.note}" for f in failures)
        pytest.fail(f"[{report.case_label}] {len(failures)} field(s) mismatched:\n{msg}")
