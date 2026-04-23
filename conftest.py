"""pytest config: register markers + CLI flags for on-demand test gating.

Two opt-in suites are auto-skipped by default so a bare ``pytest`` run is
always fast, offline, and deterministic:

  * ``@pytest.mark.live`` — tests that hit the real Google Hotels endpoint.
    Opt in with ``--live`` or ``-m live``.
  * ``@pytest.mark.browser_verify`` — tests that spawn a browser (Playwright
    or agent-browser) to compare against a live UI. Opt in with
    ``--browser-verify``.

Both suites are also sensitive to transient failures (rate limits, result
ranking drift) and depend on external tooling — keeping them opt-in is the
cleanest way to prevent accidental invocation from IDE test runners,
contributor-machine installs, or CI jobs that weren't meant to exercise
them.
"""


def pytest_addoption(parser):
    parser.addoption(
        "--browser-verify",
        action="store_true",
        default=False,
        help="Include the ``browser_verify`` suite (tests/browser_verification/).",
    )
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Include ``@pytest.mark.live`` tests (hit google.com; flaky + slow).",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: hits the real Google Hotels endpoint over the network",
    )
    config.addinivalue_line(
        "markers",
        "browser_verify: browser-vs-MCP verification tests; opt-in via --browser-verify",
    )
    config.addinivalue_line(
        "markers",
        "slow: marks tests that are slow (rate-limiter timing verification)",
    )


def pytest_collection_modifyitems(config, items):
    """Auto-skip the two opt-in suites unless the user explicitly asked for them.

    Live tests are also un-skipped when the user passes ``-m live`` (or any
    marker expression that mentions ``live``) — otherwise they'd pass
    ``-m live`` and get zero tests, which is surprising.
    """
    import pytest  # local import — pytest may not be loaded at module import time

    # Browser-verify gate
    if not config.getoption("--browser-verify"):
        skip_browser = pytest.mark.skip(reason="opt-in: pass --browser-verify to run")
        for item in items:
            if "browser_verify" in item.keywords:
                item.add_marker(skip_browser)

    # Live gate. Honor both the explicit ``--live`` flag and any ``-m``
    # expression that references the ``live`` marker (so ``pytest -m live``
    # works without also needing ``--live``).
    markexpr = config.option.markexpr or ""
    if not (config.getoption("--live") or "live" in markexpr):
        skip_live = pytest.mark.skip(reason="opt-in: pass --live or -m live to run")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip_live)
