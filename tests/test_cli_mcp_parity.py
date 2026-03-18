"""Functional parity tests between CLI and MCP integration paths.

Verifies that the CLI (--overview, --module, --search) and the MCP server
tools (get_package_overview, get_module_api, search_api) produce identical
output for the same input, as required by ADR-002.

The MCP-only tool ``refresh_cache`` is intentionally excluded — it is a
session-level concern with no CLI equivalent (the CLI is stateless).
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from libcontext.cli import main
from libcontext.collector import collect_package
from libcontext.models import PackageInfo

mcp_server = pytest.importorskip(
    "libcontext.mcp_server",
    reason="mcp optional dependency not installed",
)


@pytest.fixture
def parity_package(tmp_path: Path) -> Path:
    """Create a package with enough structure to exercise all modes."""
    pkg = tmp_path / "paritypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        textwrap.dedent('''
        """Parity test package."""

        __version__ = "1.0.0"
        '''),
        encoding="utf-8",
    )
    (pkg / "core.py").write_text(
        textwrap.dedent('''
        """Core module with classes and functions."""


        class Engine:
            """Main engine class."""

            def run(self, task: str) -> bool:
                """Execute a task."""
                return True

            def stop(self) -> None:
                """Stop the engine."""


        def create_engine(name: str, *, debug: bool = False) -> Engine:
            """Factory for Engine instances."""
            return Engine()
        '''),
        encoding="utf-8",
    )
    (pkg / "utils.py").write_text(
        textwrap.dedent('''
        """Utility helpers."""


        def retry(func: "Callable", times: int = 3) -> "Callable":
            """Retry a callable on failure."""
            return func
        '''),
        encoding="utf-8",
    )
    return pkg


@pytest.fixture
def collected_package(parity_package: Path) -> PackageInfo:
    """Collect the parity package once for MCP tests."""
    return collect_package(
        str(parity_package),
        include_private=False,
        include_readme=False,
    )


@pytest.fixture(autouse=True)
def _clear_mcp_cache():
    """Ensure each test starts with a fresh MCP cache."""
    mcp_server._collect_cached.cache_clear()
    yield
    mcp_server._collect_cached.cache_clear()


def _cli_output(args: list[str]) -> str:
    """Run the CLI and return stripped stdout."""
    runner = CliRunner()
    result = runner.invoke(main, ["inspect", *args, "-q"])
    assert result.exit_code == 0, f"CLI failed: {result.output}"
    return result.output.strip()


def _mcp_with_package(collected: PackageInfo):
    """Context manager that patches MCP to use a pre-collected package."""
    return patch.object(
        mcp_server,
        "_collect_cached",
        return_value=collected,
    )


class TestOverviewParity:
    """CLI --overview and MCP get_package_overview produce equivalent output."""

    def test_same_content(
        self, parity_package: Path, collected_package: PackageInfo
    ) -> None:
        cli_result = _cli_output([str(parity_package), "--overview"])

        with _mcp_with_package(collected_package):
            mcp_result = mcp_server.get_package_overview(str(parity_package))

        assert cli_result == mcp_result.strip()


class TestModuleParity:
    """CLI --module and MCP get_module_api produce equivalent output."""

    def test_same_content_root(
        self, parity_package: Path, collected_package: PackageInfo
    ) -> None:
        module_name = "paritypkg"
        cli_result = _cli_output([str(parity_package), "--module", module_name])

        with _mcp_with_package(collected_package):
            mcp_result = mcp_server.get_module_api(str(parity_package), module_name)

        assert cli_result == mcp_result.strip()

    def test_same_content_submodule(
        self, parity_package: Path, collected_package: PackageInfo
    ) -> None:
        module_name = "paritypkg.core"
        cli_result = _cli_output([str(parity_package), "--module", module_name])

        with _mcp_with_package(collected_package):
            mcp_result = mcp_server.get_module_api(str(parity_package), module_name)

        assert cli_result == mcp_result.strip()


class TestSearchParity:
    """CLI --search and MCP search_api produce equivalent output."""

    def test_same_results_class(
        self, parity_package: Path, collected_package: PackageInfo
    ) -> None:
        cli_result = _cli_output([str(parity_package), "--search", "Engine"])

        with _mcp_with_package(collected_package):
            mcp_result = mcp_server.search_api(str(parity_package), "Engine")

        assert cli_result == mcp_result.strip()

    def test_same_results_function(
        self, parity_package: Path, collected_package: PackageInfo
    ) -> None:
        cli_result = _cli_output([str(parity_package), "--search", "retry"])

        with _mcp_with_package(collected_package):
            mcp_result = mcp_server.search_api(str(parity_package), "retry")

        assert cli_result == mcp_result.strip()

    def test_same_results_no_match(
        self, parity_package: Path, collected_package: PackageInfo
    ) -> None:
        cli_result = _cli_output([str(parity_package), "--search", "nonexistent"])

        with _mcp_with_package(collected_package):
            mcp_result = mcp_server.search_api(str(parity_package), "nonexistent")

        assert cli_result == mcp_result.strip()
