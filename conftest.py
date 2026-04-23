"""pytest config: register markers + CLI flags for on-demand test gating."""


def pytest_addoption(parser):
    parser.addoption(
        "--browser-verify",
        action="store_true",
        default=False,
        help="Include the ``browser_verify`` suite (tests/browser_verification/).",
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


def pytest_collection_modifyitems(config, items):
    """Skip ``browser_verify`` tests unless ``--browser-verify`` is passed.

    Keeps slow browser-driven tests alongside unit tests but opt-in only.
    """
    import pytest  # local import — pytest may not be loaded at module import time

    if config.getoption("--browser-verify"):
        return
    skip = pytest.mark.skip(reason="opt-in: pass --browser-verify to run")
    for item in items:
        if "browser_verify" in item.keywords:
            item.add_marker(skip)
