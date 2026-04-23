"""Rate-limited HTTP client with Chrome TLS impersonation.

Wraps a single send with three decorators; note the ordering:
  * @retry (OUTERMOST) — tenacity exponential backoff. EVERY retry
     attempt re-enters the rate-limiter, so a single logical post_rpc()
     that retries three times costs three slots in the bucket. Only
     TransientBatchExecuteError triggers retry; retry_if_exception_type
     keeps fatals out of the loop.
  * @sleep_and_retry — catches RateLimitException and sleeps, then
     re-tries the inner call UNBOUNDEDLY. This is intentional — we
     have no higher-level deadline and Google's side eventually drains
     the queue. Callers who need a timeout should wrap their own
     asyncio.wait_for around post_rpc.
  * @limits (INNERMOST) — named module-level RateLimitDecorator with
     a fixed-window shared counter (calls_per_period, period_seconds).
     NOT a token bucket.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
from typing import Any

from curl_cffi import requests as cffi_requests
from ratelimit import limits, sleep_and_retry
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class BatchExecuteError(RuntimeError):
    """Fatal / request-shape errors (non-retryable)."""


class TransientBatchExecuteError(RuntimeError):
    """Retryable failures (429/5xx/network/empty/sorry)."""


_CALLS_PER_PERIOD = int(os.getenv("STAYS_RPS", "10"))
_PERIOD_S = 1
_POST_RPC_LIMITER = limits(calls=_CALLS_PER_PERIOD, period=_PERIOD_S)

# N2: surface rate-limit activity. `ratelimit.sleep_and_retry` sleeps INSIDE
# the third-party `ratelimit` package, so there is no clean hook we can
# instrument to log the actual wait duration. The compromise is two call
# sites: (1) a module-load INFO line so operators confirm the limiter is
# active and see the configured window, and (2) an INFO line at the top of
# `post_rpc` advertising the window per call. Tenacity retries still log
# their sleep via `before_sleep_log` above.
logger.info("post_rpc rate-limit window=%d/s (STAYS_RPS)", _CALLS_PER_PERIOD)


def _reset_rate_limit_state_for_tests() -> None:
    """Reset module-level bucket + singleton client. Tests call this in
    the body of any rate-limiter test to guarantee isolation — otherwise
    the enforcement test inherits bucket state from whatever test ran
    before it.
    """
    global _shared_client
    with _POST_RPC_LIMITER.lock:
        _POST_RPC_LIMITER.last_reset = _POST_RPC_LIMITER.clock()
        _POST_RPC_LIMITER.num_calls = 0
    _shared_client = None


class Client:
    ENDPOINT = "https://www.google.com/_/TravelFrontendUi/data/batchexecute"
    DEFAULT_HEADERS = {
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
    }
    _FRAME_RE_TEMPLATE = r'"wrb\.fr","{rpc}","((?:\\.|[^"\\])*)"'

    def __init__(self, timeout: float = 30.0, impersonate: str = "chrome") -> None:
        self._session = cffi_requests.Session()
        self._session.headers.update(self.DEFAULT_HEADERS)
        self._impersonate = impersonate
        self._timeout = timeout

    def __del__(self) -> None:
        if hasattr(self, "_session"):
            self._session.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type(TransientBatchExecuteError),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    @sleep_and_retry
    @_POST_RPC_LIMITER
    def post_rpc(self, rpc_id: str, inner_payload: list) -> Any:
        # N2: the @sleep_and_retry decorator (from the `ratelimit` package,
        # not ours) is what actually sleeps on the fixed-window bucket; we
        # can't hook that sleep directly. This INFO line is the nearest
        # in-code equivalent — it fires once per call AFTER the limiter has
        # admitted the request, so each logged line maps 1:1 to a slot used.
        logger.info("starting post_rpc id=%s with rate_limit=%d/s", rpc_id, _CALLS_PER_PERIOD)
        body = self._build_body(rpc_id, inner_payload)
        try:
            resp = self._session.post(
                self.ENDPOINT,
                data=body,
                timeout=self._timeout,
                impersonate=self._impersonate,
            )
            if resp.status_code in (429, 500, 502, 503, 504):
                raise TransientBatchExecuteError(f"HTTP {resp.status_code} from endpoint")
            if resp.status_code >= 400:
                logger.error("batchexecute failure rpc=%s status=%s", rpc_id, resp.status_code)
                raise BatchExecuteError(f"HTTP {resp.status_code} from endpoint")
            raw = resp.text
        except cffi_requests.errors.RequestsError as e:
            raise TransientBatchExecuteError(f"Network error: {e}") from e
        if not raw:
            raise TransientBatchExecuteError("Empty response body")
        return self._decode_frame(raw, rpc_id)

    def _build_body(self, rpc_id: str, inner_payload: list) -> bytes:
        inner_json = json.dumps(inner_payload, separators=(",", ":"))
        outer = [[[rpc_id, inner_json, None, "1"]]]
        encoded = urllib.parse.quote(json.dumps(outer, separators=(",", ":")), safe="")
        return f"f.req={encoded}".encode()

    @classmethod
    def _decode_frame(cls, raw: str, rpc_id: str) -> Any:
        pattern = re.compile(cls._FRAME_RE_TEMPLATE.format(rpc=re.escape(rpc_id)))
        match = pattern.search(raw)
        if not match:
            if "/sorry/" in raw or "unusual traffic" in raw.lower():
                raise TransientBatchExecuteError("Hit a rate-limit / anti-bot interstitial")
            logger.error("batchexecute failure rpc=%s err=frame_missing", rpc_id)
            raise BatchExecuteError(f"No {rpc_id} frame in response; head={raw[:200]!r}")
        payload_str = match.group(1)
        if not payload_str:
            logger.error("batchexecute failure rpc=%s err=null_payload", rpc_id)
            raise BatchExecuteError(f"{rpc_id} frame carries null payload — request likely malformed.")
        # The capture group is a valid JSON-string body (the regex only
        # allows escape pairs or non-quote/non-backslash chars). Wrapping
        # in quotes and passing to json.loads handles every JSON escape
        # (\", \\, \n, \uXXXX) while preserving literal UTF-8 bytes — the
        # older `encode('utf-8').decode('unicode_escape')` trick mojibaked
        # any non-ASCII character because `unicode_escape` treats its
        # input as Latin-1.
        inner = json.loads(f'"{payload_str}"')
        return json.loads(inner)


_shared_client: Client | None = None


def get_client() -> Client:
    """Return a process-wide shared Client (singleton)."""
    global _shared_client
    if _shared_client is None:
        _shared_client = Client()
    return _shared_client
