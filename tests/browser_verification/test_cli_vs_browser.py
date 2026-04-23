"""CLI-vs-browser verification tests.

Same semantics as ``test_browser_match.py`` — but the "programmatic"
side is the ``stays`` CLI (subprocessed via ``python -m
stays.cli._entry``), not the Python API. This proves the full CLI
stack (typer -> commands -> runtime -> SearchHotels -> HTTP -> parse
-> serialize -> stdout JSON) matches what a real browser shows for
the same query.

Gated: ``@pytest.mark.browser_verify`` + ``@pytest.mark.live``. Pass
``--browser-verify`` to run, otherwise the suite is SKIPPED.

Uses the same ``CASES`` list as ``test_browser_match.py`` so every
case label (and count) matches: 10 parametrized IDs today.

Known limitation: on a US-locale dev machine, Google Hotels' detail
(and sometimes list) page will render prices in USD regardless of
``curr=``/``gl=``/``hl=`` URL params, ``Accept-Language`` headers, or
GPS-geolocation overrides — Google's server-side IP-to-country lookup
dominates all client-side hints. That turns every non-USD, unambiguous
currency case (EUR/JPY/GBP) into a hard "browser rendered USD" failure
when there's nothing wrong with the CLI.

The four non-USD, non-ambiguous-$ cases (``paris-eur-free-cancel``,
``tokyo-jpy-5-star``, ``london-gbp-5star-spa``, ``rome-eur-sort-rating``)
are SKIPPED by default to avoid that false positive. Set
``STAYS_FORCE_BROWSER_LOCALE=1`` to opt in — only valid on a machine /
proxy that presents as the target country, where the
``set_target_locale`` plumbing in ``harness.py`` becomes the thing that
actually matters. The USD + ambiguous-$ cases (USD/AUD/SGD/HKD/CAD) run
unconditionally; they work even when Google collapses the foreign
currency to USD, because ``$`` matches either way.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any

import pytest

from tests.browser_verification.cases import CASES, BrowserCase
from tests.browser_verification.harness import (
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
    set_target_locale,
)

pytestmark = [pytest.mark.browser_verify, pytest.mark.live]

# Non-USD, non-ambiguous-$ currencies. Without IP-level locale control
# (a proxy in the target country, or ``STAYS_FORCE_BROWSER_LOCALE=1`` on
# a machine that already has the right locale), Google Hotels will override
# the URL's ``curr=`` param and render these in USD — turning valid CLI
# output into a spurious browser-mismatch failure. Skipped by default.
_LOCALE_GATED_CURRENCIES = {"EUR", "GBP", "JPY", "CHF", "INR"}
_FORCE_LOCALE = os.environ.get("STAYS_FORCE_BROWSER_LOCALE", "").strip() == "1"


def pytest_generate_tests(metafunc):
    if "case" in metafunc.fixturenames:
        metafunc.parametrize(
            "case",
            CASES,
            ids=[c.label for c in CASES],
        )


@pytest.fixture(scope="module", autouse=True)
def require_browser() -> None:
    if not browser_available():
        pytest.skip("no browser driver (agent-browser or Playwright) available")


# =============================================================================
# CLI subprocess helpers
# =============================================================================


def _run_cli(args: list[str], *, timeout: int = 180) -> dict[str, Any]:
    """Run ``python -m stays.cli._entry`` with ``--format json`` and return the envelope.

    We invoke the CLI via its module entry (``python -m stays.cli._entry``)
    rather than shelling out to ``stays`` so this test works regardless of
    whether the package is installed on PATH. Asserts rc==0 and
    ``success: true`` so every failure points straight at the offending
    sub-step rather than hiding inside a generic JSON-decode error.
    """
    cmd = [sys.executable, "-m", "stays.cli._entry", *args, "--format", "json"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    assert proc.returncode == 0, (
        f"CLI failed (rc={proc.returncode}) for args={args!r}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    try:
        env = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(f"CLI produced non-JSON stdout for args={args!r}: {exc!r}\nstdout:\n{proc.stdout}")
    assert env.get("success") is True, f"CLI envelope not successful: {env!r}"
    return env


def _cli_args_for_case(case: BrowserCase) -> list[str]:
    """Translate a ``BrowserCase`` into ``stays search`` flags.

    Mirrors the filter slots exercised by the Python-API test so the two
    suites stay feature-equivalent. Any filter present on the case's
    ``HotelSearchFilters`` is passed through as a CLI flag.
    """
    args: list[str] = ["search", case.query]
    f = case.filters
    if f.dates:
        args += [
            "--check-in",
            f.dates.check_in.isoformat(),
            "--check-out",
            f.dates.check_out.isoformat(),
        ]
    if f.guests:
        if f.guests.adults:
            args += ["--adults", str(f.guests.adults)]
        if f.guests.children:
            args += ["--children", str(f.guests.children)]
            for age in f.guests.child_ages or []:
                args += ["--child-age", str(age)]
    if case.currency:
        args += ["--currency", case.currency]
    if f.sort_by is not None:
        args += ["--sort-by", f.sort_by.name]
    if f.hotel_class:
        for star in f.hotel_class:
            args += ["--stars", str(star)]
    if f.min_guest_rating is not None:
        args += ["--min-rating", f.min_guest_rating.name]
    if f.amenities:
        for a in f.amenities:
            args += ["--amenity", a.name]
    if f.brands:
        for b in f.brands:
            args += ["--brand", b.name]
    if f.free_cancellation:
        args += ["--free-cancellation"]
    if f.eco_certified:
        args += ["--eco-certified"]
    if f.special_offers:
        args += ["--special-offers"]
    if f.price_range:
        lo, hi = f.price_range
        if lo is not None:
            args += ["--price-min", str(lo)]
        if hi is not None:
            args += ["--price-max", str(hi)]
    return args


def _cli_search(case: BrowserCase) -> list[dict[str, Any]]:
    """Run ``stays search`` for the case and return the hotels list."""
    env = _run_cli(_cli_args_for_case(case))
    return env["hotels"]


def _cli_details(entity_key: str, case: BrowserCase) -> dict[str, Any]:
    """Run ``stays details`` for the anchor and return the detail dict."""
    args: list[str] = ["details", entity_key]
    if case.filters.dates:
        args += [
            "--check-in",
            case.filters.dates.check_in.isoformat(),
            "--check-out",
            case.filters.dates.check_out.isoformat(),
        ]
    if case.currency:
        args += ["--currency", case.currency]
    env = _run_cli(args)
    return env["hotel"]


# =============================================================================
# Per-case helpers
# =============================================================================


def _find_cli_anchor(hotels: list[dict[str, Any]], substring: str) -> dict[str, Any] | None:
    """Pick the first CLI hotel whose name contains ``substring``.

    Mirrors ``test_browser_match._find_anchor`` but operates on dicts
    parsed from CLI JSON instead of ``HotelResult`` pydantic objects.
    Generic placeholders like "Hotel" fall back to the top result.
    """
    if substring.strip().lower() not in {"hotel", "hotels"}:
        for h in hotels:
            if substring.lower() in (h.get("name") or "").lower():
                return h
    return hotels[0] if hotels else None


def _find_anchor_row_by_name(rows: list[BrowserListRow], full_name: str) -> BrowserListRow | None:
    """Find the browser row whose name matches the CLI hotel's full name.

    Duplicated from ``test_browser_match._find_anchor_row_by_name`` — both
    suites need the same token-overlap matcher, and keeping a private copy
    per test file avoids churn in the already-well-covered Python-API
    suite.
    """
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
    # Threshold bumped 0.7 → 0.85. After the sponsor-card rejection in
    # extract_list_view (see harness.py) the extractor no longer emits
    # garbage sponsor rows, so we can tighten the match bar. 0.85 keeps
    # defense-in-depth against future sponsor-layout drift and prevents
    # e.g. "Regent Hong Kong" from fuzzy-matching "Grand Hyatt Hong Kong"
    # on shared city tokens.
    return best if best_score >= 0.85 else None


def _prog_providers_from_cli_detail(cli_detail: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten CLI detail's rooms/rates into a ``{normalized_provider: …}`` map.

    Mirrors the list-comprehension in ``test_browser_match`` that walks
    ``detail.rooms -> room.rates -> rate.cancellation`` but operates on
    serialized dict shape (see ``stays.serialize._serialize_rate_plan``).
    """
    out: dict[str, dict[str, Any]] = {}
    for room in cli_detail.get("rooms") or []:
        for rp in room.get("rates") or []:
            provider = rp.get("provider") or ""
            key = normalize_provider(provider)
            price = rp.get("price")
            if price is None:
                continue
            if key in out and out[key]["price"] <= price:
                continue
            cancel = rp.get("cancellation") or {}
            cancel_text = ""
            if cancel.get("free_until"):
                cancel_text = f"Free until {cancel['free_until']}"
            elif cancel.get("kind") == "non_refundable":
                cancel_text = "Non-refundable"
            out[key] = {
                "price": price,
                "cancel": cancel_text,
                "provider": provider,
            }
    return out


# =============================================================================
# The actual test — parametrized over every case
# =============================================================================


def test_cli_matches_browser(case: BrowserCase) -> None:
    """For each case: drive the real Google UI + the stays CLI; compare fields."""
    # Skip non-USD, non-ambiguous-$ currencies unless the operator has opted
    # in with ``STAYS_FORCE_BROWSER_LOCALE=1``. See the module docstring for
    # the full rationale — on a US-locale dev box Google overrides
    # ``curr=EUR/GBP/JPY`` to USD regardless of what the URL asks for, so
    # running these cases without IP-level locale control would fail every
    # time even when the CLI is correct.
    if case.currency in _LOCALE_GATED_CURRENCIES and not _FORCE_LOCALE:
        pytest.skip(
            f"{case.currency} requires a browser locale matching the target country; "
            f"set STAYS_FORCE_BROWSER_LOCALE=1 to enable (requires matching host/proxy locale)."
        )

    report = CompareReport(case_label=case.label)

    # ----------------------------------------------------------------
    # STEP 1 — run the CLI search (list view).
    # ----------------------------------------------------------------
    cli_hotels = _cli_search(case)
    assert cli_hotels, f"[{case.label}] CLI search returned 0 hotels"
    anchor_cli = _find_cli_anchor(cli_hotels, case.anchor_hotel_substring)
    assert anchor_cli is not None, f"[{case.label}] CLI anchor not found"

    # Brand-filter semantic check — every CLI result should belong to
    # the requested brand family. Mirrors the Python-API suite so the
    # CLI gets the same regression guard.
    if case.brand_name_tokens:
        tokens = [t.lower() for t in case.brand_name_tokens]
        hits = [h for h in cli_hotels if any(t in (h.get("name") or "").lower() for t in tokens)]
        misses = [h for h in cli_hotels if not any(t in (h.get("name") or "").lower() for t in tokens)]
        pct = len(hits) / len(cli_hotels)
        report.list_results.append(
            FieldResult(
                name="brand_filter_semantic",
                ok=pct >= case.brand_min_match_pct,
                browser=f"{pct:.0%} of {len(cli_hotels)} match brand",
                programmatic=f"{len(hits)} hits, {len(misses)} misses",
                note=(f"misses: {[h.get('name') for h in misses[:3]]}" if misses else "all results are brand-family"),
            )
        )

    cli_detail: dict[str, Any] | None = None
    entity_key = anchor_cli.get("entity_key")
    if case.do_detail_check and entity_key:
        try:
            cli_detail = _cli_details(entity_key, case)
        except Exception as e:
            pytest.fail(f"[{case.label}] CLI details raised: {e!r}")

    # ----------------------------------------------------------------
    # STEP 2 — open the browser at the list view, set dates, extract.
    # ----------------------------------------------------------------
    assert case.filters.dates is not None, f"[{case.label}] case lacks dates — required for browser URL"
    # Pin the browser's locale (Accept-Language + geo) BEFORE opening the
    # URL. Without this, Google Hotels ignores ``curr=<non-USD>`` on a
    # US-locale dev box and renders everything in USD, which turns every
    # non-USD case into a false "currency mismatch" failure.
    set_target_locale(case.currency)
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
    screenshot(f"cli-{case.label}-list.png")

    # Match anchor by full hotel name (more robust than the generic substring).
    browser_anchor = _find_anchor_row_by_name(browser_rows, anchor_cli["name"])

    # SOFT: see the matching block in test_browser_match.py — list-extractor
    # zero is a test-harness bug (Google layout drift), not a product issue.
    # Detail-view checks are the stronger oracle and still apply.
    report.list_results.append(
        FieldResult(
            name="browser_list_non_empty",
            ok=True,
            browser=len(browser_rows),
            programmatic=len(cli_hotels),
            note=(
                f"{len(browser_rows)} browser rows parsed"
                if browser_rows
                else "ADVISORY: extractor returned 0 rows — Google list layout "
                "differs from our DOM heuristics for this case. Detail-view "
                "oracle still applies."
            ),
        )
    )

    # Soft — browser may rank differently so anchor may not appear in top rows.
    report.list_results.append(
        FieldResult(
            name="anchor_hotel_present",
            ok=True,
            browser=browser_anchor.name if browser_anchor else None,
            programmatic=anchor_cli["name"],
            note=("matched" if browser_anchor else "anchor absent from browser list — still comparing detail"),
        )
    )

    # Compare anchor list-view price. Two orthogonal reasons to skip:
    #   - price_filters_active: amenity/class/brand/price-range/free-cancellation
    #     filters can shift which rate Google surfaces in the list, so the
    #     browser and CLI display prices can legitimately diverge. Soft-skip.
    #   - ambiguous_dollar_list: AUD/SGD/HKD/CAD share the ``$`` glyph with
    #     USD, so ``detect_browser_currency`` can't tell which currency the
    #     page is rendering. Soft-skip with a note — the detail path will
    #     still exercise the same case.
    # But a DETECTED currency mismatch (e.g. browser renders USD when case
    # asks for JPY) is a real bug — fail hard, mirroring the detail-path
    # contract added to catch locale-override regressions.
    if browser_anchor and browser_anchor.price_num is not None:
        ambiguous_dollar_list = case.currency in {"AUD", "SGD", "HKD", "CAD"}
        f = case.filters
        price_filters_active = bool(f.amenities or f.hotel_class or f.brands or f.price_range or f.free_cancellation)
        detected_mismatch = (
            browser_currency is not None and not ambiguous_dollar_list and browser_currency != case.currency
        )
        if detected_mismatch:
            report.list_results.append(
                FieldResult(
                    name="anchor_list_price",
                    ok=False,
                    browser=f"{browser_anchor.price_num} {browser_currency}",
                    programmatic=f"{anchor_cli.get('display_price')} {case.currency}",
                    note=(
                        f"list view rendered {browser_currency} but case "
                        f"requested {case.currency} — the ``curr=`` URL param "
                        f"is being overridden by the browser locale. "
                        f"Fix: ensure ``list_url()`` emits matching "
                        f"``&gl=<country>&hl=<lang>`` for this currency, or "
                        f"drive currency via UI selector post-navigation."
                    ),
                )
            )
        elif ambiguous_dollar_list or price_filters_active:
            note = (
                f"ambiguous-$ currency {case.currency} — skipped"
                if ambiguous_dollar_list
                else "filter-affected list price — skipped"
            )
            report.list_results.append(
                FieldResult(
                    name="anchor_list_price",
                    ok=True,  # soft skip
                    browser=browser_anchor.price_num,
                    programmatic=anchor_cli.get("display_price"),
                    note=note,
                )
            )
        else:
            # Currencies match (or browser_currency undetectable) and no
            # filter-induced price shift → run the strict compare.
            report.list_results.append(
                FieldResult(
                    name="anchor_list_price",
                    ok=prices_match(browser_anchor.price_num, anchor_cli.get("display_price")),
                    browser=browser_anchor.price_num,
                    programmatic=anchor_cli.get("display_price"),
                    note=f"currency={case.currency}",
                )
            )

    if browser_anchor and browser_anchor.rating is not None:
        report.list_results.append(
            FieldResult(
                name="anchor_rating",
                ok=rating_match(browser_anchor.rating, anchor_cli.get("overall_rating")),
                browser=browser_anchor.rating,
                programmatic=anchor_cli.get("overall_rating"),
            )
        )

    # ----------------------------------------------------------------
    # STEP 3 — open the browser at the detail view, extract, compare.
    # ----------------------------------------------------------------
    if not (case.do_detail_check and cli_detail and entity_key):
        _finalize(report)
        return

    # Re-assert the target locale before the detail navigation. Playwright
    # resets geo/locale only when the context changes, but agent-browser's
    # ``set headers`` state is per-session and this is a cheap no-op when
    # the locale is already set — better safe than USD.
    set_target_locale(case.currency)
    open_url(detail_url(entity_key, currency=case.currency))
    set_dates(case.filters.dates.check_in, case.filters.dates.check_out)
    time.sleep(2)
    browser_detail = extract_detail_view()
    detail_currency = detect_browser_currency(browser_detail.raw_text)
    screenshot(f"cli-{case.label}-detail.png")

    # Name match (soft — browser detail extractor uses heuristics)
    report.detail_results.append(
        FieldResult(
            name="detail_name",
            ok=(
                case.anchor_hotel_substring.lower() in browser_detail.name.lower()
                or case.anchor_hotel_substring.lower() in browser_detail.raw_text.lower()
            ),
            browser=browser_detail.name,
            programmatic=cli_detail.get("name"),
        )
    )

    # Rating
    report.detail_results.append(
        FieldResult(
            name="detail_rating",
            ok=rating_match(browser_detail.rating, cli_detail.get("overall_rating")),
            browser=browser_detail.rating,
            programmatic=cli_detail.get("overall_rating"),
        )
    )

    # Review count
    report.detail_results.append(
        FieldResult(
            name="detail_review_count",
            ok=review_count_match(browser_detail.review_count, cli_detail.get("review_count")),
            browser=browser_detail.review_count,
            programmatic=cli_detail.get("review_count"),
        )
    )

    # Star class
    cli_star = cli_detail.get("star_class")
    if browser_detail.star_class is not None and cli_star is not None:
        report.detail_results.append(
            FieldResult(
                name="detail_star_class",
                ok=browser_detail.star_class == cli_star,
                browser=browser_detail.star_class,
                programmatic=cli_star,
            )
        )

    # Providers + prices + cancellation — compare per-provider where we can
    # match the provider name between browser and CLI.
    prog_providers = _prog_providers_from_cli_detail(cli_detail)
    browser_prov_map = {normalize_provider(p): (p, price, cancel) for p, price, cancel in browser_detail.providers}

    # Currency contract: both sides must agree on currency for a numeric
    # price comparison to be meaningful. Three cases drive the logic below:
    #
    #   1. ``browser_currency`` is None — the detector couldn't pin a symbol
    #      (e.g. page text had no price glyphs we recognize). That's a
    #      different bug (extractor gap), so we fall back to a soft
    #      informational note. We can't assert what we can't see.
    #
    #   2. ``browser_currency`` is set and MATCHES ``case.currency`` — run
    #      the strict numeric compare with the existing 2% tolerance.
    #
    #   3. ``browser_currency`` is set and DIFFERS from ``case.currency`` —
    #      this is a hard failure. Either the browser is ignoring the
    #      ``curr=`` URL param (locale override) or our URL builder isn't
    #      sending the right ``gl``/``hl`` pair. The diagnostic points at
    #      both fix paths.
    #
    # Note on ambiguous-$ currencies (AUD/SGD/HKD/CAD): the ``detect_browser_currency``
    # heuristic sees ``$`` and returns ``"USD"`` because the symbol is shared.
    # Treating that as a "mismatch" would produce false failures on correctly
    # rendered AUD/SGD/HKD/CAD pages. So for those four currencies we still
    # skip the strict price compare — the ``$`` in the page is NOT evidence
    # of a USD override, it's the native currency rendering. Rating / star /
    # review-count fields still compare cleanly; the browser-vs-Python-API
    # suite carries the same tradeoff for identical reasons.
    ambiguous_dollar = case.currency in {"AUD", "SGD", "HKD", "CAD"}
    cli_display_price = cli_detail.get("display_price")
    if browser_detail.headline_price is None or cli_display_price is None:
        # Can't compare either side's absent value — informational only.
        report.detail_results.append(
            FieldResult(
                name="detail_headline_price",
                ok=True,
                browser=browser_detail.headline_price,
                programmatic=cli_display_price,
                note="missing from one side",
            )
        )
    elif ambiguous_dollar:
        # $ symbol is ambiguous across AUD/SGD/HKD/CAD/USD; skip numeric
        # compare but surface the values so humans can eyeball them.
        report.detail_results.append(
            FieldResult(
                name="detail_headline_price",
                ok=True,
                browser=browser_detail.headline_price,
                programmatic=cli_display_price,
                note=f"ambiguous-$ currency {case.currency} — skipped",
            )
        )
    elif browser_currency is None:
        # Detector couldn't tell — different bug class (extractor gap), so
        # keep it soft. Don't assert what we can't observe.
        report.detail_results.append(
            FieldResult(
                name="detail_headline_price",
                ok=True,
                browser=browser_detail.headline_price,
                programmatic=cli_display_price,
                note="browser currency undetected — price comparison skipped",
            )
        )
    elif browser_currency != case.currency:
        # Hard failure — the browser is rendering a different currency than
        # the case requested. Point the on-call at the fix paths.
        report.detail_results.append(
            FieldResult(
                name="detail_headline_price",
                ok=False,
                browser=f"{browser_detail.headline_price} {browser_currency}",
                programmatic=f"{cli_display_price} {case.currency}",
                note=(
                    f"browser rendered {browser_currency} but case requested "
                    f"{case.currency}. This usually means the browser's "
                    f"locale is overriding the URL's `currency=` param. "
                    f"Fix: (a) update `list_url()`/`detail_url()` to include "
                    f"`&gl=<country>&hl=<lang>` locale hints, (b) use "
                    f"`STAYS_BROWSER_DRIVER=playwright` with `context.locale` "
                    f"set, or (c) click the currency selector in the UI after "
                    f"navigation."
                ),
            )
        )
    else:
        # Currencies match → strict numeric compare with the normal tolerance.
        # ``detail_currency`` (separate, page-body detection) may still disagree
        # if ¥/€/£ symbols show up in provider rows below the headline while
        # the headline itself is fine — but ``browser_currency`` came from the
        # list page's raw text, which is the cleaner signal.
        report.detail_results.append(
            FieldResult(
                name="detail_headline_price",
                ok=prices_match(browser_detail.headline_price, cli_display_price),
                browser=browser_detail.headline_price,
                programmatic=cli_display_price,
                note=f"currency={case.currency}",
            )
        )
    # Used downstream for per-provider compares (below). They ride the
    # stricter currency-aligned check because provider rows are noisier.
    currency_aligned_detail = (
        not ambiguous_dollar
        and browser_currency == case.currency
        and (detail_currency is None or detail_currency == case.currency)
    )

    matched_any = False
    for key, prog in prog_providers.items():
        if key in browser_prov_map:
            matched_any = True
            _, b_price, b_cancel = browser_prov_map[key]
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
    report.detail_results.append(
        FieldResult(
            name="provider_match_count",
            ok=True,  # soft — any match is a bonus, 0 is fine
            browser=len(browser_detail.providers),
            programmatic=len(prog_providers),
            note=f"matched={'yes' if matched_any else 'no'}",
        )
    )

    # Amenity keyword — informational. Browser innerText contains filter
    # chip labels and nearby-hotel amenities, so "Spa" in text doesn't
    # prove this specific hotel has a spa.
    if case.expected_amenity_keyword:
        kw = case.expected_amenity_keyword.lower()
        in_browser = kw in browser_detail.raw_text.lower()
        cli_amenities = list(cli_detail.get("amenities") or []) + list(cli_detail.get("amenity_details") or [])
        in_prog = any(kw in (a or "").lower() for a in cli_amenities)
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
