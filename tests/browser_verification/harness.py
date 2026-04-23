"""Browser-vs-programmatic harness for verification tests.

Drives Google Hotels via the pluggable ``BrowserDriver`` abstraction
(see ``drivers.py``) — agent-browser by default, with Playwright as the
CI-friendly fallback. Extracts list-view / detail-view fields via JS
``innerText``, and compares against ``SearchHotels`` programmatic
results.

These helpers are NOT used in ordinary unit tests. They exist only to
support the on-demand ``tests/browser_verification/`` suite, which is
gated behind the ``browser_verify`` pytest marker.

Design notes:
  * Google's wire prices jitter by a few dollars between back-to-back
    requests (dynamic pricing). We allow a small price tolerance in all
    comparisons.
  * Cancellation ``free_until`` dates are tied to check-in — so the
    tolerance is ±1 day when both sides say the policy is free-until-date.
  * Browser list view sometimes rounds or uses "nightly + taxes" while
    programmatic uses Google's own ``display_num``. Tolerance handles that.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from tests.browser_verification.drivers import (
    AgentBrowserDriver,
    BrowserDriver,
    any_driver_available,
    get_driver,
)

# =============================================================================
# Constants
# =============================================================================

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

# Tolerances for browser-vs-programmatic comparison.
#
# Prices come from Google's own rounded integer display slot
# (``entry[6][2][1][4]`` in the list view, ``price_info[4]`` in the detail
# room-rate block), so the same entity on the same dates should match
# almost exactly. We allow ±2% to absorb two real sources of noise:
#   1. Sub-minute dynamic pricing between the browser's initial XHR and
#      our back-to-back MCP call.
#   2. Integer rounding — ``$97.40`` displays as ``$97`` in one channel
#      and ``$98`` in the other depending on how Google snaps the float.
# Anything beyond 2% is treated as a real discrepancy worth investigating.
PRICE_ABS_TOL = 2  # $2 floor so a 2% rule isn't sub-dollar on cheap rooms
PRICE_PCT_TOL = 0.02  # 2% relative — tight enough to catch parser drift
RATING_ABS_TOL = 0.1  # Ratings show one decimal
REVIEW_PCT_TOL = 0.05  # Review counts only grow; 5% covers normal lag
CANCEL_DAYS_TOL = 0  # Free-until dates are deterministic per check-in

# Map ISO currency → (Google country hint, language hint). The ``gl`` param
# drives Google's geolocation; the ``hl`` param drives the UI language.
# Empirically, passing both together is what coaxes Google's detail page to
# actually honour ``curr=<non-USD>`` — without a matching ``gl``/``hl`` the
# headline price falls back to USD even when the URL carries the foreign
# currency code. Keep the English-speaking locales at ``hl=en`` (matches
# the Accept-Language our CLI sends) so anchor names stay readable for the
# token-overlap matcher; switch ja/fr only where Google's USD override is
# more aggressive.
CURRENCY_LOCALE: dict[str, tuple[str, str]] = {
    "USD": ("us", "en"),
    "EUR": ("fr", "fr"),  # FR is the canonical EUR locale; DE works equally
    "GBP": ("gb", "en"),
    "JPY": ("jp", "ja"),
    "AUD": ("au", "en"),
    "SGD": ("sg", "en"),
    "HKD": ("hk", "en"),
    "CAD": ("ca", "en"),
    "CHF": ("ch", "en"),
    "INR": ("in", "en"),
}

# Backwards-compat alias — some callers only need the country code. Prefer
# ``CURRENCY_LOCALE`` in new code.
CURRENCY_COUNTRY = {curr: pair[0] for curr, pair in CURRENCY_LOCALE.items()}

# Map currency symbols → ISO code. Used to detect what currency the browser
# is ACTUALLY displaying, which is not always what the URL requested.
SYMBOL_TO_ISO = {
    "$": "USD",  # Ambiguous (AUD/SGD/HKD etc. also use $) — USD default
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",  # Ambiguous with CNY, but JPY is the common Google display
}


# =============================================================================
# Driver-backed browser helpers
# =============================================================================


# Module-level driver instance. Chosen once per process at import time via
# ``get_driver()`` — which honours ``STAYS_BROWSER_DRIVER`` and falls back
# from agent-browser to Playwright when the former isn't on PATH.
_DRIVER: BrowserDriver = get_driver()


def browser_available() -> bool:
    """Return True iff at least one browser driver (agent-browser or Playwright) is installed."""
    return any_driver_available()


def set_target_locale(currency: str) -> None:
    """Force the driver's future page loads into the locale matching ``currency``.

    Google Hotels picks its display currency primarily from the browser's
    ``Accept-Language`` header + IP-inferred geolocation — URL params
    (``curr=`` / ``gl=`` / ``hl=``) alone are not enough on a US-locale dev
    box. This function plumbs the ``currency`` → ``(country, language)``
    mapping through the driver so the next ``open_url`` actually paints in
    the requested currency.

    Safe to call multiple times; both drivers are idempotent on repeated
    calls with the same locale. Callers should invoke this BEFORE every
    ``open_url``, since URL changes may reset state on some drivers.
    """
    country, lang = CURRENCY_LOCALE.get(currency, ("us", "en"))
    try:
        _DRIVER.set_locale(country, lang)
    except Exception:
        # Best-effort — a driver that can't honour the locale shouldn't
        # break the rest of the test. The caller will still detect any
        # currency mismatch downstream via ``detect_browser_currency``.
        pass


def open_url(url: str) -> None:
    _DRIVER.open_url(url, wait_ms=3500)


def screenshot(name: str, full_page: bool = True) -> Path:
    path = SCREENSHOT_DIR / name
    _DRIVER.screenshot(path, full_page=full_page)
    return path


def page_text() -> str:
    return _DRIVER.page_text()


def snapshot_interactive() -> str:
    return _DRIVER.snapshot_interactive()


def find_ref(snapshot: str, pattern: str) -> str | None:
    """Return the first ``@eNN`` ref whose accessibility label matches ``pattern``.

    Only meaningful for the agent-browser driver. Playwright's accessibility
    snapshot has no ``@eNN`` format, so this will always return ``None``
    there — callers (see ``set_dates``) fall back to DOM-level scripting.
    """
    regex = re.compile(rf"{pattern}.*?\[ref=(e\d+)\]", re.IGNORECASE)
    m = regex.search(snapshot)
    return f"@{m.group(1)}" if m else None


def _set_dates_via_dom(check_in: date, check_out: date) -> bool:
    """Driver-agnostic fallback: find Check-in / Check-out inputs by placeholder / aria-label.

    Google Hotels' date pickers vary by country / experiment, so the DOM
    query tries several shapes. Returns ``True`` only when both inputs
    were found + filled; caller treats ``False`` as "couldn't set dates —
    rely on whatever the URL params already carry".
    """
    js = f"""
    (() => {{
      const want = (el, label) => {{
        const al = (el.getAttribute('aria-label') || '').toLowerCase();
        const ph = (el.getAttribute('placeholder') || '').toLowerCase();
        const nm = (el.getAttribute('name') || '').toLowerCase();
        return al.includes(label) || ph.includes(label) || nm.includes(label);
      }};
      const inputs = Array.from(document.querySelectorAll('input'));
      const ci = inputs.find(e => want(e, 'check-in') || want(e, 'checkin'));
      const co = inputs.find(e => want(e, 'check-out') || want(e, 'checkout'));
      if (!ci || !co) return 'missing';
      const set = (el, v) => {{
        const proto = Object.getPrototypeOf(el);
        const desc = Object.getOwnPropertyDescriptor(proto, 'value');
        desc.set.call(el, v);
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
      }};
      set(ci, {check_in.isoformat()!r});
      set(co, {check_out.isoformat()!r});
      return 'ok';
    }})()
    """
    try:
        result = _DRIVER.eval_js(js)
    except Exception:
        return False
    return "ok" in result


def set_dates(check_in: date, check_out: date) -> bool:
    """Fill Check-in / Check-out textboxes and press Enter. Returns True on success.

    Prefers the agent-browser ``@eNN`` accessibility-ref path when available
    (fast, matches keyboard navigation exactly). Falls back to a
    driver-agnostic DOM script so the Playwright path can still set dates.
    """
    # Fast path: only AgentBrowserDriver produces ``@eNN`` refs. For
    # anything else, go straight to the DOM fallback.
    if isinstance(_DRIVER, AgentBrowserDriver):
        snap = snapshot_interactive()
        ci_ref = find_ref(snap, r'textbox "Check-in"')
        co_ref = find_ref(snap, r'textbox "Check-out"')
        if ci_ref and co_ref:
            _DRIVER.fill(ci_ref, check_in.isoformat())
            _DRIVER.press("Tab")
            _DRIVER.fill(co_ref, check_out.isoformat())
            _DRIVER.press("Enter")
            _DRIVER.wait(6000)
            return True
    # Fallback: direct DOM input — works for Playwright AND a degraded
    # agent-browser snapshot that didn't expose the textbox refs.
    return _set_dates_via_dom(check_in, check_out)


# =============================================================================
# URL builders
# =============================================================================


def list_url(
    query: str,
    currency: str = "USD",
    check_in: date | None = None,
    check_out: date | None = None,
) -> str:
    """Google Hotels list URL. Currency + ``gl``/``hl`` locale hints keep the UI consistent.

    ``gl`` and ``hl`` together tell Google which country + language to
    render for — empirically required to get the non-USD headline price to
    actually paint in the requested currency. Without them Google's
    locale-inference falls back to the caller's IP-derived locale (USA for
    most CI runs), which silently overrides ``curr=JPY``/``GBP``/... to USD.
    """
    country, lang = CURRENCY_LOCALE.get(currency, ("us", "en"))
    params: dict[str, str] = {
        "q": query,
        "curr": currency,
        "hl": lang,
        "gl": country,
    }
    if check_in:
        params["checkin"] = check_in.isoformat()
    if check_out:
        params["checkout"] = check_out.isoformat()
    return f"https://www.google.com/travel/search?{urlencode(params)}"


def detail_url(entity_key: str, currency: str = "USD") -> str:
    """Google Hotels detail URL with ``gl``/``hl`` locale hints matched to ``currency``.

    Same rationale as ``list_url``: the detail page's headline price is
    especially aggressive about falling back to USD when the URL lacks a
    country+language that matches the requested currency.
    """
    country, lang = CURRENCY_LOCALE.get(currency, ("us", "en"))
    params: dict[str, str] = {
        "curr": currency,
        "hl": lang,
        "gl": country,
    }
    return f"https://www.google.com/travel/hotels/entity/{entity_key}?{urlencode(params)}"


# =============================================================================
# Browser extractors
# =============================================================================


@dataclass
class BrowserListRow:
    name: str
    price_num: float | None
    rating: float | None
    star_class: int | None


@dataclass
class BrowserDetailView:
    name: str
    star_class: int | None
    rating: float | None
    review_count: int | None
    # List of (provider, price, cancel_text) tuples extracted from "All options"
    providers: list[tuple[str, float, str]]
    # The "headline" price — the big prominent $NN next to the hotel name +
    # date range, matching Google's own display_num slot. Use this for the
    # primary MCP-vs-browser comparison; per-provider prices are noisier.
    headline_price: float | None
    # Raw innerText blob — used for debugging + free-form search
    raw_text: str


# Accept both ``$100`` (en-US style, symbol prefix) and ``100 €`` (fr-FR
# style, symbol suffix). The ``€``/``£``/``¥`` symbols in particular
# swap sides based on the page's locale — fr-FR, it-IT, and es-ES all
# put the symbol after the number, while en-US and ja-JP put it before.
# Without both branches we silently miss every non-USD list price on a
# locale-forced page.
_PRICE_RE = re.compile(r"([\$€£¥])\s?([0-9][0-9,.]*)|([0-9][0-9,.]*)\s?([\$€£¥])")


def _parse_currency_num(text: str) -> tuple[str, float] | tuple[None, None]:
    """Return (iso_currency_symbol_guess, numeric_value) or (None, None).

    The symbol guess is best-effort since ``$`` is shared across many currencies.
    """
    m = _PRICE_RE.search(text)
    if not m:
        return None, None
    # Branch 1: ``$100`` (prefix symbol). Branch 2: ``100 €`` (suffix symbol).
    symbol = m.group(1) or m.group(4)
    pure = (m.group(2) or m.group(3) or "").replace(",", "")
    try:
        return symbol, float(pure)
    except ValueError:
        return symbol, None


def _parse_num_only(text: str) -> float | None:
    _, val = _parse_currency_num(text)
    return val


def detect_browser_currency(raw_text: str) -> str | None:
    """Detect the currency symbol actually used in the rendered page."""
    if "¥" in raw_text:
        return "JPY"
    if "€" in raw_text:
        return "EUR"
    if "£" in raw_text:
        return "GBP"
    if "$" in raw_text:
        return "USD"  # best-effort — browser may be showing AUD/SGD/HKD as $
    return None


def extract_list_view() -> list[BrowserListRow]:
    """Parse Google Hotels list-view innerText into rows.

    Heuristic — each row block starts with a hotel-name line and usually has
    ``$NNN`` (or equivalent) nearby. Uses eval() to pull node-level data so
    the number of anonymous-provider rows ("Sponsored", etc.) doesn't confuse us.
    """
    # NOTE: the price regex accepts BOTH orderings:
    #   - ``$100`` / ``€100`` / ``¥1,000`` (symbol-prefix, en-US/ja-JP style)
    #   - ``100 €`` / ``1 000 €`` (symbol-suffix with optional thin-space,
    #     fr-FR/it-IT/es-ES style).
    # Without both branches, every non-USD page on a locale-forced browser
    # returns 0 list rows because the regex can't find a match. The French
    # Google Hotels list renders ``78 €``, which would never match a pure
    # symbol-prefix regex.
    js = r"""
    (() => {
      const rows = [];
      const seen = new Set();
      const priceRe = /(?:[\$€£¥]\s?[0-9][0-9,]*)|(?:[0-9][0-9,]*\s?[\$€£¥])/;
      // Diagnostics — captured alongside rows so failures can inspect what
      // the extractor actually saw. Printed to the browser console so we
      // can cross-reference with agent-browser logs when an extractor
      // layout drift occurs (Sydney Apr-2026: h2/heading dropped entirely;
      // organic cards are price-only <a> overlays whose hotel name lives
      // on an ANCESTOR div, not a descendant).
      const diag = { scanned: 0, sponsored: 0, no_price: 0, no_name: 0, found: 0 };
      // Tokens that reliably identify non-name badge text (deal callouts,
      // sponsored/ad labels, and per-night/total tooltip phrases surfaced
      // by Google's hover overlay card). Kept as two regexes so each
      // candidate goes through a couple of cheap tests.
      const DEAL_WORDS = /^(great deal|deal|sponsored|ad)\b/i;
      const TOOLTIP_PHRASE = /\b(nightly|taxes \+ fees|less than usual|per night|total)\b/i;
      // Return true when ``s`` looks like a plausible hotel-name string:
      // reasonable length, some alphabetic content, doesn't open with a
      // currency sigil, isn't a deal/sponsor badge, and doesn't contain a
      // price or a tooltip-overlay phrase. All extractName branches share
      // this predicate so we don't drift between them.
      const isPlausibleName = (s) => {
        if (!s) return false;
        if (s.length < 4 || s.length > 90) return false;
        if (!/[A-Za-z]/.test(s)) return false;
        if (/^[\$€£¥]/.test(s)) return false;
        if (DEAL_WORDS.test(s)) return false;
        if (priceRe.test(s)) return false;
        if (TOOLTIP_PHRASE.test(s)) return false;
        return true;
      };
      // Extract a plausible hotel-name string from ``el``. Returns '' when
      // no plausible name is found. Order of preference:
      //   1. <h2> / [role="heading"] descendant — classic en-US organic
      //      layout used by most non-Apr-2026 US pages.
      //   2. aria-label on the link — Google sometimes puts the hotel
      //      name on the link's aria-label even when the heading element
      //      is absent.
      //   3. ANCESTOR-walk — for the Apr-2026 "overlay" layout where the
      //      iterated <a> is a pure-price tooltip card and the actual
      //      hotel name sits on a parent DIV (class ``jVsyI``). Walks up
      //      to 8 levels looking for an ancestor whose firstLine matches
      //      ``isPlausibleName``.
      //   4. Descendant <div>/<span> fallback — for layouts where the
      //      name is a sibling text node inside the link subtree.
      //   5. firstLine — last-ditch fallback, still gated to plausible
      //      names so we don't regress on pre-Apr 2026 USD cases that
      //      already pass (they have firstLine = hotel name).
      const extractName = (el, text) => {
        // 1. Heading descendant
        const heading = el.querySelector('h2, [role="heading"]');
        const headingText = heading ? (heading.innerText || '').trim() : '';
        if (isPlausibleName(headingText)) return headingText;
        // 2. aria-label on link
        const aria = ((el.getAttribute && el.getAttribute('aria-label')) || '').trim();
        if (isPlausibleName(aria)) return aria;
        // 3. Ancestor walk — the Apr-2026 overlay layout needs this. The
        //    link itself is just "$237"; the hotel name lives on the
        //    parent ``.jVsyI`` div's firstLine.
        let anc = el.parentElement;
        for (let i = 0; i < 8 && anc; i++) {
          const ancFirst = ((anc.innerText || '').split('\n')[0] || '').trim();
          if (isPlausibleName(ancFirst)) return ancFirst;
          anc = anc.parentElement;
        }
        // 4. Descendant <div>/<span> whose own text looks like a hotel
        //    name. Take the first match so we pick the tightest name
        //    rather than a summary blob.
        const descendants = el.querySelectorAll('div, span');
        for (const d of descendants) {
          const t = (d.innerText || '').trim();
          if (isPlausibleName(t)) return t;
        }
        // 5. firstLine fallback
        const firstLine = (text.split('\n')[0] || '').trim();
        if (isPlausibleName(firstLine)) return firstLine;
        return '';
      };
      document.querySelectorAll('a, [role="link"], [role="listitem"]').forEach(el => {
        diag.scanned += 1;
        const text = (el.innerText || '').trim();
        if (!text) return;
        // Reject sponsored / OTA-advertiser cards — their prices are the
        // sponsor rate (e.g. Booking.com featured bundle) and do NOT match
        // Google's organic display_num slot that the programmatic side
        // returns. Walk up a few ancestors checking aria-label / role /
        // class for "sponsor" or standalone "ad" markers. See
        // nyc-price-investigation.md: the NYC case was locking onto a
        // DoubleTree Fort Lee sponsor row at $159 instead of organic $128.
        let anc = el, sponsored = false;
        for (let i = 0; i < 8 && anc; i++) {
          const al = ((anc.getAttribute && anc.getAttribute('aria-label')) || '').toLowerCase();
          const role = ((anc.getAttribute && anc.getAttribute('role')) || '').toLowerCase();
          const cls = ((anc.className && typeof anc.className === 'string') ? anc.className : '').toLowerCase();
          if (/sponsor/i.test(al) || /\bad\b/i.test(al)
              || /sponsor/i.test(role) || /\bad\b/i.test(role)
              || /sponsor/i.test(cls) || /\bad\b/i.test(cls)) {
            sponsored = true; break;
          }
          const first = ((anc.innerText || '').split('\n')[0] || '').trim().toLowerCase();
          if (first === 'sponsored'
              || first.startsWith('sponsored·') || first.startsWith('sponsored ·')) {
            sponsored = true; break;
          }
          anc = anc.parentElement;
        }
        if (sponsored) { diag.sponsored += 1; return; }
        const priceMatch = text.match(priceRe);
        if (!priceMatch) { diag.no_price += 1; return; }
        const name = extractName(el, text);
        if (!name) { diag.no_name += 1; return; }
        if (seen.has(name)) return;
        seen.add(name);
        diag.found += 1;
        const ratingMatch = text.match(/\b([0-9](?:\.[0-9])?)\b\s*(?:\/5|\s*\()/);
        const starMatch = text.match(/([1-5])-star/);
        rows.push({
          name: name,
          price: priceMatch[0],
          rating: ratingMatch ? parseFloat(ratingMatch[1]) : null,
          stars: starMatch ? parseInt(starMatch[1]) : null,
        });
      });
      // Surface counters so a 0-row run can be diagnosed from the
      // browser's devtools console without re-probing the DOM.
      try { console.log('[extract_list_view] diag', JSON.stringify(diag)); } catch (_) {}
      return JSON.stringify(rows);
    })()
    """
    # eval_js handles per-driver quoting / unescaping — both drivers return
    # the inner string value ready to feed to json.loads.
    raw = _DRIVER.eval_js(js)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out = []
    for d in data:
        out.append(
            BrowserListRow(
                name=d["name"],
                price_num=_parse_num_only(d.get("price") or ""),
                rating=d.get("rating"),
                star_class=d.get("stars"),
            )
        )
    return out


def _extract_headline_price_dom() -> float | None:
    """Find the hotel's headline price by scoping to the ``<h1>`` ancestor.

    Mirrors the list-view sponsor-rejection discipline (see
    ``extract_list_view`` + ``nyc-price-investigation.md``) but for detail
    view. The detail page has a prominent ``<h1>`` with the hotel name and
    a sibling price pill showing the nightly rate (matching Google's own
    ``display_num`` slot). Sponsored / promotional / "starting from" /
    "avg rate" prices live in OTHER regions of the page (similar-hotels
    carousels, multi-night promos, all-options list). Walking up from
    ``<h1>`` to the first price-bearing ancestor — and rejecting any
    ancestor whose text is tagged sponsor/promo/starting/ad — keeps the
    extractor locked onto the organic headline price.

    The hero walk is explicitly gated: the chosen ancestor must contain
    both the ``<h1>``'s text AND a price, AND its innerText must be short
    enough (<=400 chars) that we haven't widened past the hero card into
    the booking-options section below. This prevents the classic leak
    where the smallest price-bearing ancestor of h1 is actually the
    page-wrapper, which also contains the OTA booking card's "$158 Book
    on Booking.com" row.

    Returns the price as a ``float`` on success, or ``None`` when the DOM
    isn't shaped like we expect (caller then falls back to the innerText
    scan).
    """
    js = r"""
    (() => {
      const h1 = document.querySelector('h1');
      if (!h1) return '';
      const h1Text = (h1.innerText || '').trim();
      if (!h1Text) return '';
      const priceRe = /(?:[\$€£¥]\s?[0-9][0-9,.]*)|(?:[0-9][0-9,.]*\s?[\$€£¥])/;
      // Diagnostics — helps future layout-drift investigations see what
      // the walk actually matched (printed via console.log at the end).
      const diag = { hero_level: -1, hero_len: -1, hero_tag: '', leaf_text: '' };
      // Walk up from h1 to the smallest ancestor that contains BOTH the
      // h1's text AND a price AND whose total innerText is short enough
      // (<=400 chars) to be a hero card rather than the page-wrapper.
      // The 400-char cap is the key guard: without it, the walk skips
      // past a price-less hotel-header div into the page-wrapper, whose
      // innerText also rolls up the OTA booking-options card below the
      // fold — leaking e.g. $158 Booking.com rate into the "headline"
      // when Google's display_num is $133.
      let anc = h1.parentElement;
      let hero = null;
      for (let i = 0; i < 10 && anc; i++) {
        const text = anc.innerText || '';
        if (text.includes(h1Text) && priceRe.test(text) && text.length <= 400) {
          hero = anc;
          diag.hero_level = i;
          diag.hero_len = text.length;
          diag.hero_tag = anc.tagName;
          break;
        }
        anc = anc.parentElement;
      }
      if (!hero) {
        try { console.log('[headline_price_dom] no hero', JSON.stringify(diag)); } catch (_) {}
        return '';
      }
      // Reject heroes that live inside a sponsored/promo/starting/ad region.
      // Same ancestor walk + keyword set as the list-view extractor, with
      // "promo" + "starting" added to catch detail-page-specific slots
      // (multi-night "avg rate" promos, "View more options from $N").
      let up = hero;
      for (let i = 0; i < 10 && up; i++) {
        const al = ((up.getAttribute && up.getAttribute('aria-label')) || '').toLowerCase();
        const role = ((up.getAttribute && up.getAttribute('role')) || '').toLowerCase();
        const cls = ((up.className && typeof up.className === 'string') ? up.className : '').toLowerCase();
        if (/sponsor|promo|starting/i.test(al) || /\bad\b/i.test(al)
            || /sponsor|promo|starting/i.test(role) || /\bad\b/i.test(role)
            || /sponsor|promo|starting/i.test(cls) || /\bad\b/i.test(cls)) {
          try { console.log('[headline_price_dom] rejected sponsor/promo hero', JSON.stringify(diag)); } catch (_) {}
          return '';
        }
        up = up.parentElement;
      }
      // Inside the hero, find the first leaf-ish element whose own text
      // matches the price regex. Prefer short text (<=30 chars) so we
      // skip ancestors whose ``innerText`` rolls up multiple lines like
      // "Stay 1 extra night for an avg nightly rate of $131". The avg-
      // rate promo is the classic detail-page decoy — same class of bug
      // as the list-view sponsor-card leak fixed in 05682b6.
      //
      // Reject booking-card / OTA-provider phrases so a hero that
      // accidentally widens to include the booking options still picks
      // the title pill, not the cheapest provider's row. Typical phrases
      // ("book on", "view site", "visit site", "booking.com", "expedia",
      // "hotels.com", "trip.com", "agoda", "priceline") are shared with
      // the provider extractor below.
      const PROVIDER_RX = /\b(book on|view site|visit site|booking\.?com|expedia|hotels\.?com|trip\.?com|agoda|priceline|orbitz|hotwire)\b/i;
      const PROMO_RX = /\b(avg|average|starting|from \$|per person|extra night|is typical)\b/i;
      const all = hero.querySelectorAll('*');
      for (const el of all) {
        const text = (el.innerText || '').trim();
        if (!text || text.length > 30) continue;
        if (!priceRe.test(text)) continue;
        const low = text.toLowerCase();
        if (PROMO_RX.test(low)) continue;
        if (PROVIDER_RX.test(low)) continue;
        const m = text.match(priceRe);
        if (!m) continue;
        diag.leaf_text = text;
        try { console.log('[headline_price_dom] match', JSON.stringify(diag)); } catch (_) {}
        return m[0];
      }
      try { console.log('[headline_price_dom] no leaf', JSON.stringify(diag)); } catch (_) {}
      return '';
    })()
    """
    try:
        raw = _DRIVER.eval_js(js)
    except Exception:
        return None
    if not raw:
        return None
    return _parse_num_only(raw)


def extract_detail_view() -> BrowserDetailView:
    """Parse Google Hotels detail-view innerText into a structured view.

    Extracts the *headline* price — the prominent price rendered near the
    hotel name + date range — since that's what maps cleanly to the MCP's
    ``display_price``. Per-provider prices are also extracted, but those
    belong in the rooms block and can legitimately differ from the
    headline when Google's featured slot carries a promotional rate that
    no single provider serves as their cheapest option.

    Headline-price extraction prefers the DOM-scoped ``_extract_headline_price_dom``
    (``<h1>`` → hero ancestor → first short price leaf, rejecting sponsor/
    promo/starting ancestors). Falls back to a locale-aware innerText scan
    for drivers that can't execute JS or pages whose DOM shape has drifted.
    """
    raw = page_text()
    lines = [ln.strip() for ln in raw.split("\n")]

    # Primary: DOM-scoped extraction scoped to the ``<h1>`` hero region.
    # This mirrors the sponsor-rejection hardening we did in ``extract_list_view``
    # (commit 05682b6) and prevents the extractor from locking onto an OTA
    # sponsor banner price or a "starting from"/"avg nightly" promo tag.
    headline_price: float | None = _extract_headline_price_dom()

    # Fallback: the original innerText-scan heuristic. Kept for driver /
    # page-shape edge cases where the DOM extractor returns no match (e.g.
    # Playwright running headless without an h1, or Google's detail-view
    # variant that delays h1 injection until after our 3.5s wait). The
    # innerText scan is looser — it can pick up promo-row prices when the
    # h1 pill is missing — but that's strictly better than no price at all.
    _HEADLINE_STOPS = (
        "check availability",
        "vérifier la disponibilité",
        "verifica disponibilità",
        "comprobar disponibilidad",
        "verfügbarkeit prüfen",
        "空室状況",
    )
    _PROMO_RX = re.compile(r"\b(avg|average|starting|per person|extra night)\b", re.IGNORECASE)
    if headline_price is None:
        for _idx, ln in enumerate(lines[:80]):
            low = ln.lower()
            if any(stop in low for stop in _HEADLINE_STOPS):
                break
            # Skip promo / avg-rate lines so the innerText fallback doesn't
            # redo the exact bug the DOM path was hardened against.
            if _PROMO_RX.search(ln):
                continue
            if _PRICE_RE.search(ln):
                headline_price = _parse_num_only(ln)
                if headline_price is not None:
                    break

    # Name — usually a prominent heading line matching the hotel. Skip the
    # obvious UI chrome in en + fr + it + es + ja. We don't try to skip
    # "hotel"-prefixed lines anymore — in French/Italian/Spanish the hotel
    # name itself often IS "Hôtel XYZ" / "Hotel XYZ". Rely on the explicit
    # skip set + the back-nav check instead.
    _UI_LINES = {
        "prices",
        "reviews",
        "location",
        "about",
        "photos",
        "overview",
        "view all photos",
        # fr
        "prix",
        "avis",
        "localisation",
        "à propos",
        "aperçu",
        # it
        "prezzi",
        "recensioni",
        "posizione",
        "panoramica",
        # es
        "precios",
        "opiniones",
        "ubicación",
    }
    _NAV_PREFIXES = ("back", "retour", "torna", "volver", "zurück")  # "back to hotels"
    name = ""
    for ln in lines[:40]:
        low = ln.lower()
        if not ln or not ln[0].isalpha():
            continue
        if len(ln) >= 90:
            continue
        if low in _UI_LINES:
            continue
        if any(low.startswith(p) for p in _NAV_PREFIXES):
            continue
        name = ln
        break

    # Star / rating / review count — regex-level locale drift. Review count
    # label varies ("reviews" en / "avis" fr / "recensioni" it / "opiniones"
    # es / "クチコミ" ja), but the bare "N.N" rating line is locale-agnostic.
    star_class: int | None = None
    rating: float | None = None
    review_count: int | None = None
    for ln in lines[:50]:
        m = re.match(r"([1-5])-star", ln)
        if m:
            star_class = int(m.group(1))
            break
    for ln in lines[:60]:
        m = re.match(r"^([0-5][.,][0-9])$", ln)
        if m:
            rating = float(m.group(1).replace(",", "."))
            break
    _REVIEW_RE = re.compile(
        r"([0-9][0-9,\. ]*)\s*(?:reviews?|avis|recensioni|opiniones|クチコミ|review)", re.IGNORECASE
    )
    for ln in lines[:80]:
        m = _REVIEW_RE.search(ln)
        if m:
            # Strip thin-spaces + commas + periods used as thousand separators.
            digits = re.sub(r"[,.\s]", "", m.group(1))
            if digits.isdigit():
                review_count = int(digits)
                break

    # Providers: look inside "All options" section. Each provider block is
    # usually "Provider\n[optional cancel text]\n$NNN\nVisit site".
    providers: list[tuple[str, float, str]] = []
    in_options = False
    i = 0
    while i < len(lines):
        ln = lines[i]
        if "All options" in ln:
            in_options = True
            i += 1
            continue
        if in_options and ln and ln[0].isalpha() and len(ln) < 40:
            # Maybe a provider name
            provider = ln
            cancel_text = ""
            price: float | None = None
            # Scan next few lines for price + cancel text
            for j in range(1, 6):
                if i + j >= len(lines):
                    break
                nxt = lines[i + j]
                pm = _PRICE_RE.search(nxt)
                if pm:
                    price = _parse_num_only(nxt)
                    break
                if "cancellation" in nxt.lower() or "non-refundable" in nxt.lower():
                    cancel_text = nxt
            if price is not None and len(provider) > 2:
                # Skip UI labels
                if provider.lower() in {
                    "view more options",
                    "view site",
                    "visit site",
                    "all options",
                    "nightly price with fees",
                    "nightly price with taxes + fees",
                    "sponsored",
                    "about this hotel",
                }:
                    i += 1
                    continue
                providers.append((provider, price, cancel_text))
        i += 1

    return BrowserDetailView(
        name=name,
        star_class=star_class,
        rating=rating,
        review_count=review_count,
        providers=providers,
        headline_price=headline_price,
        raw_text=raw,
    )


# =============================================================================
# Comparison helpers
# =============================================================================


def prices_match(browser: float | None, programmatic: float | None) -> bool:
    if browser is None or programmatic is None:
        return browser is None and programmatic is None
    abs_diff = abs(browser - programmatic)
    pct_diff = abs_diff / max(browser, programmatic, 1)
    return abs_diff <= PRICE_ABS_TOL or pct_diff <= PRICE_PCT_TOL


def dates_match(browser: date | None, programmatic: date | None, tol_days: int = CANCEL_DAYS_TOL) -> bool:
    if browser is None and programmatic is None:
        return True
    if browser is None or programmatic is None:
        return False
    return abs((browser - programmatic).days) <= tol_days


def rating_match(browser: float | None, programmatic: float | None) -> bool:
    if browser is None or programmatic is None:
        return True  # Missing is acceptable
    return abs(browser - programmatic) <= RATING_ABS_TOL


def review_count_match(browser: int | None, programmatic: int | None) -> bool:
    if browser is None or programmatic is None:
        return True  # Rating may not parse cleanly — don't hard-fail
    diff = abs(browser - programmatic)
    pct = diff / max(browser, programmatic, 1)
    return pct <= REVIEW_PCT_TOL


def normalize_provider(name: str) -> str:
    """Normalize provider names so Booking.com in browser matches 'Booking.com' programmatic."""
    n = name.lower().strip()
    n = n.replace(".com", "").replace(",", "").strip()
    return n


@dataclass
class FieldResult:
    name: str
    ok: bool
    browser: Any = None
    programmatic: Any = None
    note: str = ""


@dataclass
class CompareReport:
    case_label: str
    list_results: list[FieldResult] = field(default_factory=list)
    detail_results: list[FieldResult] = field(default_factory=list)

    def passed(self) -> bool:
        return all(r.ok for r in self.list_results + self.detail_results)

    def failures(self) -> list[FieldResult]:
        return [r for r in self.list_results + self.detail_results if not r.ok]

    def render(self) -> str:
        out = [f"=== {self.case_label} ==="]
        out.append("-- LIST --")
        for r in self.list_results:
            status = "OK" if r.ok else "FAIL"
            out.append(f"  [{status}] {r.name}: browser={r.browser!r} programmatic={r.programmatic!r}  {r.note}")
        out.append("-- DETAIL --")
        for r in self.detail_results:
            status = "OK" if r.ok else "FAIL"
            out.append(f"  [{status}] {r.name}: browser={r.browser!r} programmatic={r.programmatic!r}  {r.note}")
        return "\n".join(out)
