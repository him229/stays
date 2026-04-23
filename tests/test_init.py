"""Tests for ``stays/__init__.py`` import narrowing (M4b).

The MCP-surface try/except MUST only swallow ``ModuleNotFoundError``
for the known-optional ``fastmcp`` runtime. Every other failure —
including a broken ``stays.mcp`` submodule — must propagate so a bad
install cannot silently produce an empty public surface.
"""

from __future__ import annotations

import builtins
import importlib

import pytest


def _reload_stays() -> None:
    """Re-import ``stays`` so monkey-patched ``__import__`` takes effect.

    Pops any cached ``stays`` + ``stays.mcp`` submodules so the next
    import actually re-evaluates ``stays/__init__.py``.
    """
    import sys

    for name in list(sys.modules):
        if name == "stays" or name.startswith("stays.mcp"):
            sys.modules.pop(name, None)
    importlib.import_module("stays")


def test_init_propagates_non_optional_module_not_found(monkeypatch):
    """A ``ModuleNotFoundError`` for a non-optional module inside
    ``stays.mcp`` must surface rather than be swallowed.
    """
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        # The narrow fallback should ONLY catch missing ``fastmcp`` — a
        # phantom missing submodule of our own package must propagate.
        if name == "stays.mcp" or (name == "stays" and "mcp" in (fromlist or ())):
            raise ModuleNotFoundError("No module named 'stays._internal_secret'", name="stays._internal_secret")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(ModuleNotFoundError) as excinfo:
        _reload_stays()
    # ``exc.name`` must be a NON-optional module — the narrow re-raise
    # at ``stays/__init__.py`` only swallows when ``exc.name == "fastmcp"``.
    assert excinfo.value.name == "stays._internal_secret"


def test_init_swallows_optional_fastmcp_module_not_found(monkeypatch):
    """The exact expected failure (``fastmcp`` missing) must be
    swallowed so library-only installs keep working.
    """
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "stays.mcp" or (name == "stays" and "mcp" in (fromlist or ())):
            raise ModuleNotFoundError("No module named 'fastmcp'", name="fastmcp")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    # Reload should NOT raise — the narrow block catches ``fastmcp``.
    _reload_stays()

    import stays

    # Core library surface must still be present.
    assert "HotelSearchFilters" in stays.__all__
    # MCP surface names should NOT be exported when the import failed.
    assert "mcp" not in stays.__all__


def test_init_reimport_restores_normal_surface():
    """Sanity: after test teardown the default ``stays`` reload brings
    back the full MCP surface. Belt-and-braces against other tests
    leaving ``sys.modules`` in a weird state.
    """
    _reload_stays()

    import stays

    assert "HotelSearchFilters" in stays.__all__
    assert "mcp" in stays.__all__
