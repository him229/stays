"""Browser driver backends for browser_verify tests.

Primary: agent-browser (https://github.com/vercel-labs/agent-browser) — fast,
MCP-friendly, preferred on local machines.
Fallback: Playwright — works in remote/CI environments that can't install
agent-browser but have Chromium available.

Select via env var:
    STAYS_BROWSER_DRIVER=agent-browser (default)
    STAYS_BROWSER_DRIVER=playwright

Both drivers implement the same operational surface (``open_url``,
``page_text``, ``snapshot_interactive``, ``screenshot``, ``eval_js``,
``close``, ``set_locale``). Higher-level extraction (``extract_list_view``
/ ``extract_detail_view``) lives in ``harness.py`` and works against either
driver because both expose page text + a minimal DOM eval.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Protocol


class BrowserDriver(Protocol):
    """Minimal surface needed by harness.py + test cases."""

    def available(self) -> bool: ...
    def open_url(self, url: str, wait_ms: int = 3500) -> None: ...
    def page_text(self) -> str: ...
    def eval_js(self, expr: str) -> str: ...
    def snapshot_interactive(self) -> str: ...
    def screenshot(self, out_path: Path, full_page: bool = True) -> Path: ...
    def set_locale(self, country: str, language: str) -> None:
        """Configure future page loads to request the given locale.

        ``country`` is a 2-letter ISO code (``"fr"``, ``"jp"``, ...), ``language``
        is a 2-letter language tag (``"fr"``, ``"ja"``, ...). May be a no-op on
        drivers that can't control locale at runtime, but implementations should
        at least try to set ``Accept-Language`` headers since Google Hotels uses
        that header to choose the display currency — without it, ``curr=EUR``
        in the URL gets silently overridden to USD on US-locale machines.
        """
        ...

    def close(self) -> None: ...


# Map ISO country → approximate capital-city coordinates. agent-browser's
# ``set geo <lat> <lng>`` pins the browser's geolocation, which (combined
# with ``Accept-Language``) is what Google Hotels uses to pick the display
# currency. These coordinates don't need to be exact — anywhere in the
# right country is enough to flip Google's locale inference.
COUNTRY_GEO: dict[str, tuple[float, float]] = {
    "us": (37.7749, -122.4194),  # San Francisco
    "fr": (48.8566, 2.3522),  # Paris
    "gb": (51.5074, -0.1278),  # London
    "jp": (35.6762, 139.6503),  # Tokyo
    "au": (-33.8688, 151.2093),  # Sydney
    "sg": (1.3521, 103.8198),  # Singapore
    "hk": (22.3193, 114.1694),  # Hong Kong
    "ca": (45.4215, -75.6972),  # Ottawa
    "ch": (47.3769, 8.5417),  # Zurich
    "in": (28.6139, 77.2090),  # Delhi
    "de": (52.5200, 13.4050),  # Berlin
    "it": (41.9028, 12.4964),  # Rome
    "es": (40.4168, -3.7038),  # Madrid
    "ae": (25.2048, 55.2708),  # Dubai
}


def _accept_language(country: str, language: str) -> str:
    """Build an Accept-Language header value honouring the target locale.

    Format is ``<lang>-<COUNTRY>,<lang>;q=0.9,en;q=0.8`` — matches what a
    real browser in that locale would send, with a small English fallback
    so any UI chrome that isn't localised still renders readably.
    """
    primary = f"{language}-{country.upper()}"
    # English-speaking locales (gb, au, ca, sg, hk, in) don't need the
    # "en" fallback weight — they're already English-primary.
    if language == "en":
        return f"{primary},en;q=0.9"
    return f"{primary},{language};q=0.9,en;q=0.8"


class AgentBrowserDriver:
    """agent-browser CLI subprocess driver. Default."""

    def available(self) -> bool:
        proc = subprocess.run(
            ["which", "agent-browser"],
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode == 0

    def _run(self, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["agent-browser"] + args,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    def open_url(self, url: str, wait_ms: int = 3500) -> None:
        self._run(["open", url], timeout=60)
        self._run(["wait", str(wait_ms)])

    def page_text(self) -> str:
        return self.eval_js("document.body.innerText")

    def eval_js(self, expr: str) -> str:
        # agent-browser ``eval`` wraps string output in quotes + escapes;
        # strip the outer quotes + unescape ``\\n`` -> ``\n`` etc. so plain-text
        # consumers don't have to.
        proc = self._run(["eval", expr])
        raw = proc.stdout.strip()
        if raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1]
        return raw.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')

    def snapshot_interactive(self) -> str:
        return self._run(["snapshot", "-i"]).stdout

    def screenshot(self, out_path: Path, full_page: bool = True) -> Path:
        args = ["screenshot", str(out_path)]
        if full_page:
            args.append("--full")
        self._run(args)
        return out_path

    def fill(self, ref: str, value: str) -> None:
        """agent-browser specific: fill a ``@eNN`` ref with ``value``."""
        self._run(["fill", ref, value])

    def press(self, key: str) -> None:
        """agent-browser specific: press a keyboard key."""
        self._run(["press", key])

    def wait(self, ms: int) -> None:
        self._run(["wait", str(ms)])

    def set_locale(self, country: str, language: str) -> None:
        """Force Google Hotels to render in the target locale's currency.

        Uses two levers:
          1. ``agent-browser set headers`` — sets ``Accept-Language`` on every
             subsequent request, which is Google's primary locale signal.
          2. ``agent-browser set geo`` — pins the browser's geolocation to a
             city in the target country, which reinforces the locale choice
             when Accept-Language alone isn't enough (Google sometimes cross-
             references the two).

        Both commands are idempotent and cheap; callers should invoke this
        before every ``open_url`` so URL changes don't reset the state.
        """
        headers = {"Accept-Language": _accept_language(country, language)}
        self._run(["set", "headers", json.dumps(headers)])
        geo = COUNTRY_GEO.get(country.lower())
        if geo is not None:
            self._run(["set", "geo", str(geo[0]), str(geo[1])])

    def close(self) -> None:
        self._run(["close"])


class PlaywrightDriver:
    """Playwright sync driver. Fallback when agent-browser isn't installed.

    Playwright has no equivalent of agent-browser's ``@eNN`` accessibility
    refs, so ``snapshot_interactive`` returns a best-effort plain
    accessibility tree dump for logging. Tests that rely on ``@eNN`` refs
    (see ``harness.find_ref`` / ``harness.set_dates``) transparently fall
    back to DOM-level ``eval_js`` when a ref isn't found.
    """

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        # Cached (country, language) tuple so ``set_locale`` is a no-op when
        # called repeatedly with the same target — avoids the context teardown
        # cost between back-to-back open_url calls with the same currency.
        self._current_locale: tuple[str, str] | None = None

    def available(self) -> bool:
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError:
            return False
        return True

    def _ensure(self) -> None:
        if self._page is not None:
            return
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context()
        self._page = self._context.new_page()

    def open_url(self, url: str, wait_ms: int = 3500) -> None:
        self._ensure()
        self._page.goto(url, wait_until="networkidle")
        self._page.wait_for_timeout(wait_ms)

    def page_text(self) -> str:
        self._ensure()
        return self._page.evaluate("document.body.innerText")

    def eval_js(self, expr: str) -> str:
        self._ensure()
        return str(self._page.evaluate(expr))

    def snapshot_interactive(self) -> str:
        # Playwright has no equivalent of agent-browser's ``@eNN`` accessibility
        # refs. Callers that need refs (``find_ref``) should prefer
        # agent-browser. This returns a best-effort plain accessibility
        # snapshot for logging / soft-skip fallbacks.
        self._ensure()
        try:
            return str(self._page.accessibility.snapshot())
        except Exception:
            return ""

    def screenshot(self, out_path: Path, full_page: bool = True) -> Path:
        self._ensure()
        self._page.screenshot(path=str(out_path), full_page=full_page)
        return out_path

    def set_locale(self, country: str, language: str) -> None:
        """Recreate the browser context with ``locale`` + ``geolocation`` matching the target.

        Playwright applies ``locale`` and ``geolocation`` only at context
        creation time, so changing the target currency means discarding the
        current context and spinning up a fresh one. The open_url that
        follows will paint in the new locale from the first byte, which is
        what Google Hotels needs to render non-USD prices correctly.

        Idempotent — if we're already in the requested locale, do nothing.
        """
        target = (country.lower(), language.lower())
        if self._current_locale == target:
            return
        from playwright.sync_api import sync_playwright

        # Bring up the Playwright runtime if this is the first call.
        if self._pw is None:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)

        # Tear down the old context (if any) so the next navigation uses
        # the fresh locale. Page + context teardown is cheap compared to
        # the full ``chromium.launch()`` above.
        if self._page is not None:
            self._page.close()
            self._page = None
        if self._context is not None:
            self._context.close()
            self._context = None

        locale = f"{language}-{country.upper()}"
        kwargs: dict[str, object] = {
            "locale": locale,
            "extra_http_headers": {"Accept-Language": _accept_language(country, language)},
        }
        geo = COUNTRY_GEO.get(country.lower())
        if geo is not None:
            kwargs["geolocation"] = {"latitude": geo[0], "longitude": geo[1]}
            kwargs["permissions"] = ["geolocation"]
        self._context = self._browser.new_context(**kwargs)
        self._page = self._context.new_page()
        self._current_locale = target

    def close(self) -> None:
        if self._page is not None:
            self._page.close()
            self._page = None
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None
        self._current_locale = None


def get_driver() -> BrowserDriver:
    """Return the configured browser driver.

    Honors ``STAYS_BROWSER_DRIVER`` env var; otherwise prefers agent-browser,
    falls back to Playwright.
    """
    choice = os.environ.get("STAYS_BROWSER_DRIVER", "").strip().lower()
    if choice == "playwright":
        return PlaywrightDriver()
    if choice == "agent-browser":
        return AgentBrowserDriver()
    # Default: prefer agent-browser, fall back to Playwright.
    ab = AgentBrowserDriver()
    if ab.available():
        return ab
    return PlaywrightDriver()


def any_driver_available() -> bool:
    """True if at least one driver (agent-browser or Playwright) is installed."""
    return AgentBrowserDriver().available() or PlaywrightDriver().available()
