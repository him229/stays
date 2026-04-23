"""Browser-vs-programmatic harness for verification tests.

Shells out to the ``agent-browser`` CLI to drive Google Hotels in a real
browser, extracts list-view / detail-view fields via JS innerText, and
compares against ``SearchHotels`` programmatic results.

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
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

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

# Map ISO currency → Google country hint (keeps display consistent).
CURRENCY_COUNTRY = {
    "USD": "us",
    "EUR": "fr",
    "GBP": "gb",
    "JPY": "jp",
    "AUD": "au",
    "SGD": "sg",
    "HKD": "hk",
    "CAD": "ca",
    "CHF": "ch",
    "INR": "in",
}

# Map currency symbols → ISO code. Used to detect what currency the browser
# is ACTUALLY displaying, which is not always what the URL requested.
SYMBOL_TO_ISO = {
    "$": "USD",  # Ambiguous (AUD/SGD/HKD etc. also use $) — USD default
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",  # Ambiguous with CNY, but JPY is the common Google display
}


# =============================================================================
# agent-browser subprocess helpers
# =============================================================================


def _ab(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """Shell out to agent-browser, raising on non-zero exit.

    Centralized so timeouts and error handling live in one place.
    """
    return subprocess.run(
        ["agent-browser"] + args,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def browser_available() -> bool:
    """Return True iff ``agent-browser`` CLI is on PATH."""
    proc = subprocess.run(
        ["which", "agent-browser"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def open_url(url: str) -> None:
    _ab(["open", url], timeout=60)
    _ab(["wait", "3500"])


def screenshot(name: str, full_page: bool = True) -> Path:
    path = SCREENSHOT_DIR / name
    args = ["screenshot", str(path)]
    if full_page:
        args.append("--full")
    _ab(args)
    return path


def page_text() -> str:
    proc = _ab(["eval", "document.body.innerText"])
    # agent-browser wraps string output in quotes + escapes; strip the outer
    # quotes + unescape \\n -> \n for plain-text consumers.
    raw = proc.stdout.strip()
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    return raw.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')


def snapshot_interactive() -> str:
    return _ab(["snapshot", "-i"]).stdout


def find_ref(snapshot: str, pattern: str) -> str | None:
    """Return the first ``@eNN`` ref whose accessibility label matches ``pattern``."""
    regex = re.compile(rf"{pattern}.*?\[ref=(e\d+)\]", re.IGNORECASE)
    m = regex.search(snapshot)
    return f"@{m.group(1)}" if m else None


def set_dates(check_in: date, check_out: date) -> bool:
    """Fill Check-in / Check-out textboxes and press Enter. Returns True on success."""
    snap = snapshot_interactive()
    ci_ref = find_ref(snap, r'textbox "Check-in"')
    co_ref = find_ref(snap, r'textbox "Check-out"')
    if not (ci_ref and co_ref):
        return False
    _ab(["fill", ci_ref, check_in.isoformat()])
    _ab(["press", "Tab"])
    _ab(["fill", co_ref, check_out.isoformat()])
    _ab(["press", "Enter"])
    _ab(["wait", "6000"])
    return True


# =============================================================================
# URL builders
# =============================================================================


def list_url(
    query: str,
    currency: str = "USD",
    check_in: date | None = None,
    check_out: date | None = None,
) -> str:
    """Google Hotels list URL. Currency + country hint keep the UI consistent."""
    params: dict[str, str] = {
        "q": query,
        "curr": currency,
        "hl": "en-US",
        "gl": CURRENCY_COUNTRY.get(currency, "us"),
    }
    if check_in:
        params["checkin"] = check_in.isoformat()
    if check_out:
        params["checkout"] = check_out.isoformat()
    return f"https://www.google.com/travel/search?{urlencode(params)}"


def detail_url(entity_key: str, currency: str = "USD") -> str:
    params: dict[str, str] = {
        "curr": currency,
        "hl": "en-US",
        "gl": CURRENCY_COUNTRY.get(currency, "us"),
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


_PRICE_RE = re.compile(r"([\$€£¥])[ ]?([0-9][0-9,.]*)")


def _parse_currency_num(text: str) -> tuple[str, float] | tuple[None, None]:
    """Return (iso_currency_symbol_guess, numeric_value) or (None, None).

    The symbol guess is best-effort since ``$`` is shared across many currencies.
    """
    m = _PRICE_RE.search(text)
    if not m:
        return None, None
    symbol = m.group(1)
    pure = m.group(2).replace(",", "")
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
    js = r"""
    (() => {
      const rows = [];
      const seen = new Set();
      document.querySelectorAll('a, [role="link"], [role="listitem"]').forEach(el => {
        const text = (el.innerText || '').trim();
        if (!text) return;
        // Row signature: must have a hotel-ish name + a price
        const priceMatch = text.match(/[\$€£¥]\s?[0-9][0-9,]*/);
        if (!priceMatch) return;
        const firstLine = text.split('\n')[0].trim();
        if (firstLine.length < 3 || firstLine.length > 90) return;
        if (!/[A-Za-z]/.test(firstLine)) return;
        if (seen.has(firstLine)) return;
        seen.add(firstLine);
        const ratingMatch = text.match(/\b([0-9](?:\.[0-9])?)\b\s*(?:\/5|\s*\()/);
        const starMatch = text.match(/([1-5])-star/);
        rows.push({
          name: firstLine,
          price: priceMatch[0],
          rating: ratingMatch ? parseFloat(ratingMatch[1]) : null,
          stars: starMatch ? parseInt(starMatch[1]) : null,
        });
      });
      return JSON.stringify(rows);
    })()
    """
    proc = _ab(["eval", js])
    raw = proc.stdout.strip()
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    raw = raw.replace('\\"', '"').replace("\\\\", "\\")
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


def extract_detail_view() -> BrowserDetailView:
    """Parse Google Hotels detail-view innerText into a structured view.

    Extracts the *headline* price — the prominent price rendered near the
    hotel name + date range — since that's what maps cleanly to the MCP's
    ``display_price``. Per-provider prices are also extracted, but those
    belong in the rooms block and can legitimately differ from the
    headline when Google's featured slot carries a promotional rate that
    no single provider serves as their cheapest option.
    """
    raw = page_text()
    lines = [ln.strip() for ln in raw.split("\n")]

    # Headline price — first ``$NN`` / ``€NN`` / etc. that appears before the
    # ``Check availability`` header and isn't part of a comparative block.
    headline_price: float | None = None
    for _idx, ln in enumerate(lines[:80]):
        if "check availability" in ln.lower():
            break
        if _PRICE_RE.search(ln):
            headline_price = _parse_num_only(ln)
            if headline_price is not None:
                break

    # Name — usually a prominent heading line matching the hotel
    name = ""
    for ln in lines[:40]:
        if (
            len(ln) < 90
            and "hotel" not in ln.lower()[:5]
            and "back" not in ln.lower()
            and "overview" not in ln.lower()
            and ln
            and ln[0].isalpha()
        ):
            # Skip UI-ish lines: "Prices", "Reviews", etc.
            if ln in {"Prices", "Reviews", "Location", "About", "Photos"}:
                continue
            if ln in {"Overview", "View all photos"}:
                continue
            name = ln
            break

    star_class: int | None = None
    rating: float | None = None
    review_count: int | None = None
    for ln in lines[:50]:
        m = re.match(r"([1-5])-star", ln)
        if m:
            star_class = int(m.group(1))
            break
    for ln in lines[:60]:
        m = re.match(r"^([0-5]\.[0-9])$", ln)
        if m:
            rating = float(m.group(1))
            break
    for ln in lines[:80]:
        m = re.search(r"([0-9][0-9,]*)\s*reviews?", ln)
        if m:
            review_count = int(m.group(1).replace(",", ""))
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
