"""Tests for the MCP server tool functions.

These tests exercise the tool logic directly (not via MCP protocol),
using mock PackageInfo data to avoid depending on installed packages.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from libcontext.exceptions import PackageNotFoundError
from libcontext.models import (
    ClassInfo,
    FunctionInfo,
    ModuleInfo,
    PackageInfo,
    ParameterInfo,
)

mcp_server = pytest.importorskip(
    "libcontext.mcp_server",
    reason="mcp optional dependency not installed",
)


def _make_test_package() -> PackageInfo:
    return PackageInfo(
        name="fakepkg",
        version="2.0.0",
        summary="A fake package for testing",
        modules=[
            ModuleInfo(
                name="fakepkg",
                docstring="Root module.",
                classes=[
                    ClassInfo(
                        name="Client",
                        bases=["BaseClient"],
                        docstring="HTTP client.",
                        methods=[
                            FunctionInfo(
                                name="__init__",
                                parameters=[
                                    ParameterInfo(name="self"),
                                    ParameterInfo(name="url", annotation="str"),
                                ],
                                docstring="Init.",
                            ),
                            FunctionInfo(
                                name="fetch",
                                parameters=[
                                    ParameterInfo(name="self"),
                                    ParameterInfo(name="path", annotation="str"),
                                ],
                                return_annotation="Response",
                                docstring="Fetch a resource.",
                            ),
                        ],
                    ),
                ],
                functions=[
                    FunctionInfo(
                        name="create_client",
                        parameters=[
                            ParameterInfo(name="url", annotation="str"),
                        ],
                        return_annotation="Client",
                        docstring="Factory function.",
                    ),
                ],
            ),
            ModuleInfo(
                name="fakepkg.utils",
                docstring="Utility helpers.",
                functions=[
                    FunctionInfo(
                        name="retry",
                        parameters=[
                            ParameterInfo(name="func", annotation="Callable"),
                            ParameterInfo(name="times", annotation="int", default="3"),
                        ],
                        return_annotation="Callable",
                        docstring="Retry a function call.",
                    ),
                ],
            ),
            ModuleInfo(name="fakepkg.empty"),
        ],
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure each test starts with a fresh cache."""
    mcp_server._collect_cached.cache_clear()
    yield
    mcp_server._collect_cached.cache_clear()


def _patch_collect(pkg: PackageInfo | None = None):
    """Patch _collect_cached to return a test package."""
    target = _make_test_package() if pkg is None else pkg
    return patch.object(
        mcp_server,
        "_collect_cached",
        return_value=target,
    )


# ---------------------------------------------------------------------------
# get_package_overview
# ---------------------------------------------------------------------------


class TestGetPackageOverview:
    def test_returns_module_list(self):
        with _patch_collect():
            result = mcp_server.get_package_overview("fakepkg")

        assert "# fakepkg v2.0.0" in result
        assert "fakepkg" in result
        assert "fakepkg.utils" in result

    def test_shows_class_and_function_names(self):
        with _patch_collect():
            result = mcp_server.get_package_overview("fakepkg")

        assert "Client" in result
        assert "create_client()" in result
        assert "retry()" in result

    def test_excludes_empty_modules(self):
        with _patch_collect():
            result = mcp_server.get_package_overview("fakepkg")

        assert "fakepkg.empty" not in result

    def test_package_not_found(self):
        with patch.object(
            mcp_server,
            "_collect_cached",
            side_effect=PackageNotFoundError("nope"),
        ):
            result = mcp_server.get_package_overview("nope")

        assert "Error:" in result
        assert "not found" in result


# ---------------------------------------------------------------------------
# get_module_api
# ---------------------------------------------------------------------------


class TestGetModuleApi:
    def test_returns_full_api(self):
        with _patch_collect():
            result = mcp_server.get_module_api("fakepkg", "fakepkg")

        assert "### `fakepkg`" in result
        assert "class Client(BaseClient)" in result
        assert "def fetch(path: str) -> Response" in result
        assert "def create_client(url: str) -> Client" in result

    def test_specific_module(self):
        with _patch_collect():
            result = mcp_server.get_module_api("fakepkg", "fakepkg.utils")

        assert "### `fakepkg.utils`" in result
        assert "retry" in result
        assert "Client" not in result

    def test_module_not_found(self):
        with _patch_collect():
            result = mcp_server.get_module_api("fakepkg", "fakepkg.nope")

        assert "not found" in result
        assert "fakepkg" in result
        assert "fakepkg.utils" in result

    def test_package_not_found(self):
        with patch.object(
            mcp_server,
            "_collect_cached",
            side_effect=PackageNotFoundError("nope"),
        ):
            result = mcp_server.get_module_api("nope", "nope.core")

        assert "Error:" in result


# ---------------------------------------------------------------------------
# search_api
# ---------------------------------------------------------------------------


class TestSearchApi:
    def test_finds_class(self):
        with _patch_collect():
            result = mcp_server.search_api("fakepkg", "Client")

        assert "class" in result
        assert "Client" in result

    def test_finds_function(self):
        with _patch_collect():
            result = mcp_server.search_api("fakepkg", "retry")

        assert "function" in result
        assert "retry" in result

    def test_finds_method(self):
        with _patch_collect():
            result = mcp_server.search_api("fakepkg", "fetch")

        assert "method" in result
        assert "fetch" in result

    def test_case_insensitive(self):
        with _patch_collect():
            result = mcp_server.search_api("fakepkg", "CLIENT")

        assert "Client" in result

    def test_no_matches(self):
        with _patch_collect():
            result = mcp_server.search_api("fakepkg", "nonexistent")

        assert "No matches" in result

    def test_package_not_found(self):
        with patch.object(
            mcp_server,
            "_collect_cached",
            side_effect=PackageNotFoundError("nope"),
        ):
            result = mcp_server.search_api("nope", "anything")

        assert "Error:" in result


# ---------------------------------------------------------------------------
# refresh_cache
# ---------------------------------------------------------------------------


class TestRefreshCache:
    def test_clears_all(self):
        result = mcp_server.refresh_cache()
        assert "all packages" in result
