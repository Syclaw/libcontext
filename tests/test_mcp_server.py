"""Tests for the MCP server tool functions.

These tests exercise the tool logic directly (not via MCP protocol),
using mock PackageInfo data to avoid depending on installed packages.
"""

from __future__ import annotations

import json
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

    def test_with_kind_filter(self):
        with _patch_collect():
            result = mcp_server.search_api("fakepkg", "Client", kind="class")

        assert "Client" in result
        assert "create_client" not in result

    def test_json_format(self):
        with _patch_collect():
            result = mcp_server.search_api("fakepkg", "Client", output_format="json")

        data = json.loads(result)
        assert data["schema_version"] == 1
        assert data["data"]["query"] == "Client"
        assert len(data["data"]["results"]) > 0
        assert data["data"]["results"][0]["name"] == "Client"

    def test_json_format_with_kind(self):
        with _patch_collect():
            result = mcp_server.search_api(
                "fakepkg", "Client", kind="class", output_format="json"
            )

        data = json.loads(result)
        assert all(r["kind"] == "class" for r in data["data"]["results"])


# ---------------------------------------------------------------------------
# get_api_json
# ---------------------------------------------------------------------------


class TestGetApiJson:
    def test_full_package(self):
        with _patch_collect():
            result = mcp_server.get_api_json("fakepkg")

        data = json.loads(result)
        assert data["schema_version"] == 1
        assert data["data"]["name"] == "fakepkg"
        assert len(data["data"]["modules"]) == 3

    def test_single_module(self):
        with _patch_collect():
            result = mcp_server.get_api_json("fakepkg", module_name="fakepkg.utils")

        data = json.loads(result)
        assert data["schema_version"] == 1
        assert data["data"]["name"] == "fakepkg.utils"

    def test_module_not_found(self):
        with _patch_collect():
            result = mcp_server.get_api_json("fakepkg", module_name="fakepkg.nope")

        assert "not found" in result
        assert "fakepkg.utils" in result

    def test_package_not_found(self):
        with patch.object(
            mcp_server,
            "_collect_cached",
            side_effect=PackageNotFoundError("nope"),
        ):
            result = mcp_server.get_api_json("nope")

        assert "Error:" in result


# ---------------------------------------------------------------------------
# diff_api
# ---------------------------------------------------------------------------


class TestDiffApi:
    def _make_old_new_json(self):
        """Create two JSON strings with a simulated API change."""
        import dataclasses

        from libcontext.models import _serialize_envelope

        old_pkg = _make_test_package()
        new_pkg = _make_test_package()
        # Remove 'retry' function from utils in new version
        for mod in new_pkg.modules:
            if mod.name == "fakepkg.utils":
                mod.functions = []
                break

        old_json = json.dumps(_serialize_envelope(dataclasses.asdict(old_pkg)))
        new_json = json.dumps(_serialize_envelope(dataclasses.asdict(new_pkg)))
        return old_json, new_json

    def test_markdown_output(self):
        old_json, new_json = self._make_old_new_json()
        result = mcp_server.diff_api(old_json, new_json)

        assert "Breaking Changes" in result
        assert "retry" in result

    def test_json_output(self):
        old_json, new_json = self._make_old_new_json()
        result = mcp_server.diff_api(old_json, new_json, output_format="json")

        data = json.loads(result)
        assert data["schema_version"] == 1
        assert len(data["data"]["modified_modules"]) > 0

    def test_no_changes(self):
        old_json, _ = self._make_old_new_json()
        result = mcp_server.diff_api(old_json, old_json)

        assert "No changes" in result

    def test_invalid_json(self):
        result = mcp_server.diff_api("{bad", "{}")
        assert "Error:" in result

    def test_invalid_envelope(self):
        result = mcp_server.diff_api("{}", "{}")
        assert "Error:" in result


# ---------------------------------------------------------------------------
# refresh_cache
# ---------------------------------------------------------------------------


class TestRefreshCache:
    def test_clears_all(self):
        result = mcp_server.refresh_cache()
        assert "Cache cleared" in result
