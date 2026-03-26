"""Functional parity tests between CLI and MCP integration paths.

Verifies that the CLI (--overview, --module, --search) and the MCP server
tools (get_package_overview, get_module_api, search_api) produce identical
output for the same input, as required by ADR-002.

The MCP-only tool ``refresh_cache`` is intentionally excluded — it is a
session-level concern with no CLI equivalent (the CLI is stateless).
"""

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


class TestJsonFormatParity:
    """CLI --format json and MCP get_api_json produce equivalent JSON envelopes."""

    def test_full_package_json(
        self, parity_package: Path, collected_package: PackageInfo
    ) -> None:
        import json

        cli_result = _cli_output(
            [str(parity_package), "--format", "json"],
        )

        with _mcp_with_package(collected_package):
            mcp_result = mcp_server.get_api_json(str(parity_package))

        cli_data = json.loads(cli_result)
        mcp_data = json.loads(mcp_result)
        assert cli_data == mcp_data

    def test_single_module_json(
        self, parity_package: Path, collected_package: PackageInfo
    ) -> None:
        import json

        module_name = "paritypkg.core"
        cli_result = _cli_output(
            [str(parity_package), "--format", "json", "--module", module_name],
        )

        with _mcp_with_package(collected_package):
            mcp_result = mcp_server.get_api_json(str(parity_package), module_name)

        cli_data = json.loads(cli_result)
        mcp_data = json.loads(mcp_result)
        assert cli_data == mcp_data


class TestTypeFilteredSearchParity:
    """CLI --search --type and MCP search_api(kind=) produce equivalent output."""

    def test_class_filter(
        self, parity_package: Path, collected_package: PackageInfo
    ) -> None:
        cli_result = _cli_output(
            [str(parity_package), "--search", "Engine", "--type", "class"],
        )

        with _mcp_with_package(collected_package):
            mcp_result = mcp_server.search_api(
                str(parity_package), "Engine", kind="class"
            )

        assert cli_result == mcp_result.strip()

    def test_function_filter(
        self, parity_package: Path, collected_package: PackageInfo
    ) -> None:
        cli_result = _cli_output(
            [str(parity_package), "--search", "create", "--type", "function"],
        )

        with _mcp_with_package(collected_package):
            mcp_result = mcp_server.search_api(
                str(parity_package), "create", kind="function"
            )

        assert cli_result == mcp_result.strip()

    def test_filter_excludes_non_matching_kind(
        self, parity_package: Path, collected_package: PackageInfo
    ) -> None:
        cli_result = _cli_output(
            [str(parity_package), "--search", "Engine", "--type", "function"],
        )

        with _mcp_with_package(collected_package):
            mcp_result = mcp_server.search_api(
                str(parity_package), "Engine", kind="function"
            )

        assert cli_result == mcp_result.strip()


class TestErrorParity:
    """CLI and MCP both handle nonexistent packages gracefully."""

    def test_cli_nonexistent_package_exits_nonzero(self, tmp_path: Path) -> None:
        fake_pkg = str(tmp_path / "no_such_pkg_xyz")
        runner = CliRunner()

        result = runner.invoke(main, ["inspect", fake_pkg, "-q"])

        assert result.exit_code != 0
        assert "Error" in (result.output + (result.stderr or ""))

    def test_mcp_nonexistent_package_returns_error_string(self) -> None:
        result = mcp_server.get_package_overview("no_such_pkg_xyz_999")

        assert result.startswith("Error:")

    def test_mcp_get_api_json_nonexistent_returns_error(self) -> None:
        result = mcp_server.get_api_json("no_such_pkg_xyz_999")

        assert result.startswith("Error:")

    def test_mcp_search_nonexistent_returns_error(self) -> None:
        result = mcp_server.search_api("no_such_pkg_xyz_999", "anything")

        assert result.startswith("Error:")

    def test_mcp_nonexistent_module_in_valid_package(
        self, parity_package: Path, collected_package: PackageInfo
    ) -> None:
        with _mcp_with_package(collected_package):
            result = mcp_server.get_module_api(
                str(parity_package), "paritypkg.nonexistent"
            )

        assert "not found" in result


class TestDiffParity:
    """CLI diff and MCP diff_api both report the same added symbols."""

    @pytest.fixture()
    def diff_packages_pair(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create two package versions: v1 with greet(), v2 adds farewell()."""
        v1 = tmp_path / "v1" / "diffpkg"
        v1.mkdir(parents=True)
        (v1 / "__init__.py").write_text(
            textwrap.dedent('''
            """Diff test package v1."""

            __version__ = "1.0.0"
            '''),
            encoding="utf-8",
        )
        (v1 / "core.py").write_text(
            textwrap.dedent('''
            """Core module."""

            def greet(name: str) -> str:
                """Say hello."""
                return f"Hello {name}"
            '''),
            encoding="utf-8",
        )

        v2 = tmp_path / "v2" / "diffpkg"
        v2.mkdir(parents=True)
        (v2 / "__init__.py").write_text(
            textwrap.dedent('''
            """Diff test package v2."""

            __version__ = "2.0.0"
            '''),
            encoding="utf-8",
        )
        (v2 / "core.py").write_text(
            textwrap.dedent('''
            """Core module."""

            def greet(name: str) -> str:
                """Say hello."""
                return f"Hello {name}"

            def farewell(name: str) -> str:
                """Say goodbye."""
                return f"Bye {name}"
            '''),
            encoding="utf-8",
        )
        return v1, v2

    def test_both_mention_added_function(
        self, tmp_path: Path, diff_packages_pair: tuple[Path, Path]
    ) -> None:
        import dataclasses
        import json as json_mod

        from libcontext.models import _serialize_envelope

        v1_path, v2_path = diff_packages_pair

        old_pkg = collect_package(str(v1_path), include_readme=False)
        new_pkg = collect_package(str(v2_path), include_readme=False)

        old_envelope = _serialize_envelope(dataclasses.asdict(old_pkg))
        new_envelope = _serialize_envelope(dataclasses.asdict(new_pkg))

        old_json_str = json_mod.dumps(old_envelope)
        new_json_str = json_mod.dumps(new_envelope)

        # Write JSON files for CLI diff
        old_file = tmp_path / "old.json"
        new_file = tmp_path / "new.json"
        old_file.write_text(old_json_str, encoding="utf-8")
        new_file.write_text(new_json_str, encoding="utf-8")

        # CLI diff
        runner = CliRunner()
        cli_result = runner.invoke(main, ["diff", str(old_file), str(new_file)])
        assert cli_result.exit_code == 0, f"CLI diff failed: {cli_result.output}"

        # MCP diff
        mcp_result = mcp_server.diff_api(old_json_str, new_json_str)

        assert "farewell" in cli_result.output
        assert "farewell" in mcp_result
