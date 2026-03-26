"""Tests for the CLI module."""

import io
import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from libcontext.cli import main


@pytest.fixture
def sample_package(tmp_path: Path) -> Path:
    """Create a minimal package on disk for CLI testing."""
    pkg = tmp_path / "demopkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        textwrap.dedent('''
        """Demo package for CLI tests."""

        __version__ = "0.1.0"
        '''),
        encoding="utf-8",
    )
    (pkg / "core.py").write_text(
        textwrap.dedent('''
        """Core module."""

        def hello(name: str) -> str:
            """Greet someone."""
            return f"Hello, {name}!"
        '''),
        encoding="utf-8",
    )
    return pkg


# ---------------------------------------------------------------------------
# Basic invocations
# ---------------------------------------------------------------------------


def test_stdout_output(sample_package: Path) -> None:
    """CLI prints Markdown to stdout by default."""
    runner = CliRunner()
    result = runner.invoke(main, ["inspect", str(sample_package)])

    assert result.exit_code == 0
    assert "API Reference" in result.output


def test_output_to_file(sample_package: Path, tmp_path: Path) -> None:
    """``-o`` writes Markdown to a file with markers."""
    out_file = tmp_path / "out" / "copilot.md"
    runner = CliRunner()
    result = runner.invoke(main, ["inspect", str(sample_package), "-o", str(out_file)])

    assert result.exit_code == 0
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "<!-- BEGIN LIBCONTEXT:" in content
    assert "<!-- END LIBCONTEXT:" in content
    assert "API Reference" in content


def test_output_to_existing_file(sample_package: Path, tmp_path: Path) -> None:
    """Writing to an existing file preserves non-marker content."""
    out_file = tmp_path / "instructions.md"
    out_file.write_text("# My Custom Notes\n\nKeep this.\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["inspect", str(sample_package), "-o", str(out_file)])

    assert result.exit_code == 0
    content = out_file.read_text(encoding="utf-8")
    assert "# My Custom Notes" in content
    assert "Keep this." in content
    assert "<!-- BEGIN LIBCONTEXT:" in content


# ---------------------------------------------------------------------------
# Option flags
# ---------------------------------------------------------------------------


def test_quiet_flag(sample_package: Path) -> None:
    """``-q`` suppresses informational messages on stderr."""
    runner = CliRunner()
    result = runner.invoke(main, ["inspect", str(sample_package), "-q"])

    assert result.exit_code == 0
    # With -q, no "Inspecting" message in output
    assert "Inspecting" not in result.output


def test_no_readme_flag(sample_package: Path) -> None:
    """``--no-readme`` excludes readme section."""
    runner = CliRunner()
    result = runner.invoke(main, ["inspect", str(sample_package), "--no-readme"])

    assert result.exit_code == 0
    assert "## Overview" not in result.output


def test_include_private_flag(tmp_path: Path) -> None:
    """``--include-private`` includes private modules."""
    pkg = tmp_path / "privpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Root."""', encoding="utf-8")
    (pkg / "_internal.py").write_text(
        'def _secret() -> int:\n    """Hidden."""\n    return 42\n',
        encoding="utf-8",
    )

    runner = CliRunner()

    # Without flag — private skipped
    result_without = runner.invoke(main, ["inspect", str(pkg)])
    # With flag — private included
    result_with = runner.invoke(main, ["inspect", str(pkg), "--include-private"])

    assert result_without.exit_code == 0
    assert result_with.exit_code == 0
    assert "_internal" not in result_without.output
    assert "_internal" in result_with.output


def test_max_readme_lines(tmp_path: Path) -> None:
    """``--max-readme-lines`` truncates the readme."""
    pkg = tmp_path / "readmepkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Root."""', encoding="utf-8")

    # Put a long README next to the package
    long_readme = "\n".join(f"Line {i}" for i in range(200))
    (tmp_path / "README.md").write_text(long_readme, encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["inspect", str(pkg), "--max-readme-lines", "5"])

    assert result.exit_code == 0
    assert "Line 4" in result.output
    assert "Line 5" not in result.output
    assert "*(README truncated)*" in result.output


# ---------------------------------------------------------------------------
# Config file option
# ---------------------------------------------------------------------------


def test_config_flag(tmp_path: Path) -> None:
    """``--config`` reads [tool.libcontext] from a pyproject.toml."""
    pkg = tmp_path / "cfgpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Root."""', encoding="utf-8")
    (pkg / "core.py").write_text(
        'def func() -> None:\n    """A function."""\n    ...\n',
        encoding="utf-8",
    )
    (pkg / "_private.py").write_text(
        'def secret() -> None:\n    """Secret."""\n    ...\n',
        encoding="utf-8",
    )

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        textwrap.dedent("""\
        [tool.libcontext]
        include_private = true
        extra_context = "Use this library carefully."
        max_readme_lines = 10
        """),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["inspect", str(pkg), "--config", str(pyproject)])

    assert result.exit_code == 0
    assert "Use this library carefully." in result.output


def test_config_with_include_private_override(tmp_path: Path) -> None:
    """--include-private with --config updates config."""
    pkg = tmp_path / "cfgpkg2"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Root."""', encoding="utf-8")

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        textwrap.dedent("""\
        [tool.libcontext]
        include_private = false
        """),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["inspect", str(pkg), "--config", str(pyproject), "--include-private"],
    )

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_nonexistent_package() -> None:
    """Non-existent package exits with code 1 and error message."""
    runner = CliRunner()
    result = runner.invoke(main, ["inspect", "this_package_does_not_exist_xyz"])

    assert result.exit_code == 1
    assert "Error" in result.output or "not found" in result.output


# ---------------------------------------------------------------------------
# Multiple packages
# ---------------------------------------------------------------------------


def test_multiple_packages(tmp_path: Path) -> None:
    """CLI supports multiple package arguments."""
    for name in ("pkg_a", "pkg_b"):
        pkg = tmp_path / name
        pkg.mkdir()
        (pkg / "__init__.py").write_text(f'"""{name} root."""', encoding="utf-8")
        (pkg / "mod.py").write_text(
            f"def func_{name}() -> str:\n"
            f'    """Function in {name}."""\n'
            f'    return "ok"\n',
            encoding="utf-8",
        )

    runner = CliRunner()
    result = runner.invoke(
        main, ["inspect", str(tmp_path / "pkg_a"), str(tmp_path / "pkg_b")]
    )

    assert result.exit_code == 0
    assert "pkg_a" in result.output
    assert "pkg_b" in result.output


def test_multiple_packages_to_file(tmp_path: Path) -> None:
    """Multiple packages are injected with separate markers into a file."""
    for name in ("pkg_x", "pkg_y"):
        pkg = tmp_path / name
        pkg.mkdir()
        (pkg / "__init__.py").write_text(f'"""{name}."""', encoding="utf-8")

    out_file = tmp_path / "context.md"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "inspect",
            str(tmp_path / "pkg_x"),
            str(tmp_path / "pkg_y"),
            "-o",
            str(out_file),
        ],
    )

    assert result.exit_code == 0
    content = out_file.read_text(encoding="utf-8")
    assert "<!-- BEGIN LIBCONTEXT: pkg_x -->" in content
    assert "<!-- BEGIN LIBCONTEXT: pkg_y -->" in content


# ---------------------------------------------------------------------------
# Stderr messages (non-quiet mode)
# ---------------------------------------------------------------------------


def test_stderr_messages(sample_package: Path) -> None:
    """Non-quiet mode prints progress info (mixed into output by default)."""
    runner = CliRunner()
    result = runner.invoke(main, ["inspect", str(sample_package)])

    assert result.exit_code == 0
    # Click mixes stderr into output by default in CliRunner
    assert "Inspecting" in result.output
    assert "modules" in result.output


def test_file_output_stderr_message(sample_package: Path, tmp_path: Path) -> None:
    """Writing to file prints 'Context written to ...' message."""
    out_file = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(main, ["inspect", str(sample_package), "-o", str(out_file)])

    assert result.exit_code == 0
    assert "Context written to" in result.output


# ---------------------------------------------------------------------------
# Regression: stdout must not be corrupted after CLI invocation
# ---------------------------------------------------------------------------


def test_stdout_buffer_not_detached(tmp_path: Path) -> None:
    """Verify the CLI code path does not call detach() on stdout."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Root."""', encoding="utf-8")

    # Simulate a real stdout with a .buffer attribute
    binary_buffer = io.BytesIO()
    fake_stdout = io.TextIOWrapper(binary_buffer, encoding="utf-8")

    runner = CliRunner()
    with patch("sys.stdout", fake_stdout):
        result = runner.invoke(main, ["inspect", str(pkg)])

    assert result.exit_code == 0

    # After invocation, the buffer must NOT be detached
    try:
        fake_stdout.write("still works")
        fake_stdout.flush()
    except ValueError as exc:
        pytest.fail(f"stdout was corrupted (detached buffer): {exc}")


def test_cli_stdout_no_exception(tmp_path: Path) -> None:
    """CLI must not raise when writing to stdout."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        '"""Root."""\n\ndef hello() -> str:\n    """Hi."""\n    return "hi"\n',
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["inspect", str(pkg)])

    assert result.exit_code == 0
    assert result.exception is None


# ---------------------------------------------------------------------------
# I/O error handling
# ---------------------------------------------------------------------------


def test_output_file_read_non_utf8(sample_package: Path, tmp_path: Path) -> None:
    """Existing output file with non-UTF-8 bytes exits with error."""
    out_file = tmp_path / "bad.md"
    out_file.write_bytes(b"# Bad \xe9ncoding\n")

    runner = CliRunner()
    result = runner.invoke(main, ["inspect", str(sample_package), "-o", str(out_file)])

    assert result.exit_code == 1
    assert "not valid UTF-8" in result.output


def test_output_file_write_permission_error(
    sample_package: Path, tmp_path: Path
) -> None:
    """OSError when writing output file exits with error."""
    out_file = tmp_path / "output.md"

    runner = CliRunner()
    with patch.object(Path, "write_text", side_effect=OSError("Permission denied")):
        result = runner.invoke(
            main, ["inspect", str(sample_package), "-o", str(out_file)]
        )

    assert result.exit_code == 1
    assert "cannot write" in result.output


def test_bad_config_type_error(tmp_path: Path) -> None:
    """Config with wrong types exits with error."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Root."""', encoding="utf-8")

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        textwrap.dedent("""\
        [tool.libcontext]
        include_modules = "should_be_a_list"
        """),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["inspect", str(pkg), "--config", str(pyproject)])

    assert result.exit_code == 1
    assert "config" in result.output.lower()


def test_verbose_flag(sample_package: Path) -> None:
    """``--verbose`` enables debug logging without crashing."""
    runner = CliRunner()
    result = runner.invoke(main, ["inspect", str(sample_package), "-v"])

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# install subcommand
# ---------------------------------------------------------------------------


def test_install_skills_claude(tmp_path: Path) -> None:
    """``libctx install --skills`` creates .claude/skills/lib/SKILL.md."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["install", "--skills"])

        assert result.exit_code == 0
        skill = Path(".claude/skills/lib/SKILL.md")
        assert skill.exists()

        content = skill.read_text(encoding="utf-8")
        assert "name: lib" in content
        assert "libctx" in content
        assert "Progressive API Discovery" in content


def test_install_skills_github(tmp_path: Path) -> None:
    """``libctx install --skills --target github`` uses .github/skills/."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["install", "--skills", "--target", "github"])

        assert result.exit_code == 0
        skill = Path(".github/skills/lib/SKILL.md")
        assert skill.exists()

        content = skill.read_text(encoding="utf-8")
        assert "name: lib" in content


def test_install_skills_idempotent(tmp_path: Path) -> None:
    """Running install twice overwrites cleanly."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(main, ["install", "--skills"])
        result = runner.invoke(main, ["install", "--skills"])

        assert result.exit_code == 0
        skill = Path(".claude/skills/lib/SKILL.md")
        assert skill.exists()


def test_install_requires_flag() -> None:
    """``libctx install`` without any flag errors."""
    runner = CliRunner()
    result = runner.invoke(main, ["install"])

    assert result.exit_code != 0
    assert "specify at least one" in result.output


# ---------------------------------------------------------------------------
# install --mcp
# ---------------------------------------------------------------------------


def test_install_mcp_claude(tmp_path: Path) -> None:
    """``libctx install --mcp`` creates .mcp.json with mcpServers entry."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["install", "--mcp"])

        assert result.exit_code == 0
        mcp_file = Path(".mcp.json")
        assert mcp_file.exists()

        data = json.loads(mcp_file.read_text(encoding="utf-8"))
        assert "mcpServers" in data
        assert "libcontext" in data["mcpServers"]
        assert data["mcpServers"]["libcontext"]["command"] == "libctx-mcp"


def test_install_mcp_vscode(tmp_path: Path) -> None:
    """``libctx install --mcp --target vscode`` creates .vscode/mcp.json."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["install", "--mcp", "--target", "vscode"])

        assert result.exit_code == 0
        mcp_file = Path(".vscode/mcp.json")
        assert mcp_file.exists()

        data = json.loads(mcp_file.read_text(encoding="utf-8"))
        assert "servers" in data
        assert "libcontext" in data["servers"]
        assert data["servers"]["libcontext"]["type"] == "stdio"


def test_install_mcp_merges_existing(tmp_path: Path) -> None:
    """MCP install merges into existing .mcp.json without clobbering."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        existing = {"mcpServers": {"other-tool": {"command": "other"}}}
        Path(".mcp.json").write_text(json.dumps(existing, indent=2), encoding="utf-8")

        result = runner.invoke(main, ["install", "--mcp"])

        assert result.exit_code == 0
        data = json.loads(Path(".mcp.json").read_text(encoding="utf-8"))
        assert "other-tool" in data["mcpServers"]
        assert "libcontext" in data["mcpServers"]


def test_install_mcp_target_github_no_match(tmp_path: Path) -> None:
    """``--mcp --target github`` has no matching files — errors."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["install", "--mcp", "--target", "github"])

        assert result.exit_code != 0
        assert "Nothing to install" in result.output


def test_install_mcp_corrupt_json(tmp_path: Path) -> None:
    """``--mcp`` with corrupt existing .mcp.json exits with error."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path(".mcp.json").write_text("{invalid json", encoding="utf-8")

        result = runner.invoke(main, ["install", "--mcp"])

        assert result.exit_code != 0
        assert "Cannot parse" in result.output


# ---------------------------------------------------------------------------
# install --all
# ---------------------------------------------------------------------------


def test_install_all_claude(tmp_path: Path) -> None:
    """``libctx install --all`` installs skills + mcp for claude."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["install", "--all"])

        assert result.exit_code == 0
        assert Path(".claude/skills/lib/SKILL.md").exists()
        assert Path(".mcp.json").exists()


def test_install_all_target_all(tmp_path: Path) -> None:
    """``libctx install --all --target all`` installs for every platform."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["install", "--all", "--target", "all"])

        assert result.exit_code == 0
        # Skills
        assert Path(".claude/skills/lib/SKILL.md").exists()
        assert Path(".github/skills/lib/SKILL.md").exists()
        # MCP
        assert Path(".mcp.json").exists()
        assert Path(".vscode/mcp.json").exists()


# ---------------------------------------------------------------------------
# Combined flags
# ---------------------------------------------------------------------------


def test_install_skills_and_mcp(tmp_path: Path) -> None:
    """``--skills --mcp`` installs both without --all."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["install", "--skills", "--mcp"])

        assert result.exit_code == 0
        assert Path(".claude/skills/lib/SKILL.md").exists()
        assert Path(".mcp.json").exists()


def test_install_skills_target_vscode_no_match(tmp_path: Path) -> None:
    """``--skills --target vscode`` has no matching files — errors."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["install", "--skills", "--target", "vscode"])

        assert result.exit_code != 0
        assert "Nothing to install" in result.output


# ---------------------------------------------------------------------------
# Progressive disclosure flags
# ---------------------------------------------------------------------------


def test_overview_flag(sample_package: Path) -> None:
    """``--overview`` shows compact module list without signatures."""
    runner = CliRunner()
    result = runner.invoke(main, ["inspect", str(sample_package), "--overview", "-q"])

    assert result.exit_code == 0
    assert "## Modules" in result.output
    assert "hello()" in result.output
    # Overview should NOT contain full signatures
    assert "name: str" not in result.output


def test_module_flag(sample_package: Path) -> None:
    """``--module`` renders a single module's detailed API."""
    runner = CliRunner()
    result = runner.invoke(
        main, ["inspect", str(sample_package), "--module", "demopkg.core", "-q"]
    )

    assert result.exit_code == 0
    assert "### `demopkg.core`" in result.output
    assert "def hello(name: str) -> str" in result.output


def test_module_flag_not_found(sample_package: Path) -> None:
    """``--module`` with bad module name exits with error."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["inspect", str(sample_package), "--module", "demopkg.nonexistent", "-q"],
    )

    assert result.exit_code == 1
    assert "not found" in result.output


def test_search_flag(sample_package: Path) -> None:
    """``--search`` finds functions matching query."""
    runner = CliRunner()
    result = runner.invoke(
        main, ["inspect", str(sample_package), "--search", "hello", "-q"]
    )

    assert result.exit_code == 0
    assert "hello" in result.output
    assert "function" in result.output


def test_search_flag_no_matches(sample_package: Path) -> None:
    """``--search`` with no matches shows a message."""
    runner = CliRunner()
    result = runner.invoke(
        main, ["inspect", str(sample_package), "--search", "nonexistent", "-q"]
    )

    assert result.exit_code == 0
    assert "No matches" in result.output


def test_mutually_exclusive_flags(sample_package: Path) -> None:
    """--overview, --module, and --search are mutually exclusive."""
    runner = CliRunner()
    result = runner.invoke(
        main, ["inspect", str(sample_package), "--overview", "--search", "hello"]
    )

    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


def test_overview_and_module_exclusive(sample_package: Path) -> None:
    """--overview and --module cannot be combined."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["inspect", str(sample_package), "--overview", "--module", "demopkg.core"],
    )

    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


# ---------------------------------------------------------------------------
# --type requires --search
# ---------------------------------------------------------------------------


def test_type_without_search_error(sample_package: Path) -> None:
    """``--type`` without ``--search`` exits with error."""
    runner = CliRunner()
    result = runner.invoke(
        main, ["inspect", str(sample_package), "--type", "class", "-q"]
    )

    assert result.exit_code == 1
    assert "--type requires --search" in result.output


# ---------------------------------------------------------------------------
# JSON format output
# ---------------------------------------------------------------------------


def test_json_format_default(sample_package: Path) -> None:
    """``--format json`` outputs valid JSON envelope."""
    runner = CliRunner()
    result = runner.invoke(
        main, ["inspect", str(sample_package), "--format", "json", "-q"]
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["schema_version"] == 1
    assert data["data"]["name"] == "demopkg"


def test_json_format_overview(sample_package: Path) -> None:
    """``--overview --format json`` outputs full PackageInfo JSON."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["inspect", str(sample_package), "--overview", "--format", "json", "-q"],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["schema_version"] == 1


def test_json_format_module(sample_package: Path) -> None:
    """``--module --format json`` outputs module JSON."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "inspect",
            str(sample_package),
            "--module",
            "demopkg.core",
            "--format",
            "json",
            "-q",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["schema_version"] == 1
    assert data["data"]["name"] == "demopkg.core"


def test_json_format_module_not_found(sample_package: Path) -> None:
    """``--module --format json`` with bad module name exits with error."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "inspect",
            str(sample_package),
            "--module",
            "demopkg.nope",
            "--format",
            "json",
            "-q",
        ],
    )

    assert result.exit_code == 1
    assert "not found" in result.output


def test_json_format_search(sample_package: Path) -> None:
    """``--search --format json`` outputs structured search results."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "inspect",
            str(sample_package),
            "--search",
            "hello",
            "--format",
            "json",
            "-q",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["schema_version"] == 1
    assert data["data"]["query"] == "hello"


def test_json_format_to_file(sample_package: Path, tmp_path: Path) -> None:
    """``--format json -o`` writes JSON to file."""
    out_file = tmp_path / "out.json"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "inspect",
            str(sample_package),
            "--format",
            "json",
            "-o",
            str(out_file),
            "-q",
        ],
    )

    assert result.exit_code == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1


def test_json_format_search_with_type(sample_package: Path) -> None:
    """``--search --type --format json`` applies type filter."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "inspect",
            str(sample_package),
            "--search",
            "hello",
            "--type",
            "function",
            "--format",
            "json",
            "-q",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["schema_version"] == 1


# ---------------------------------------------------------------------------
# cache subcommand
# ---------------------------------------------------------------------------


def test_cache_clear(tmp_path: Path, monkeypatch) -> None:
    """``libctx cache clear`` runs without error."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("libcontext.cache.sys.platform", "linux")

    runner = CliRunner()
    result = runner.invoke(main, ["cache", "clear"])

    assert result.exit_code == 0
    assert "Cleared" in result.output


def test_cache_clear_specific_package(tmp_path: Path, monkeypatch) -> None:
    """``libctx cache clear <package>`` removes only that package."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("libcontext.cache.sys.platform", "linux")

    from libcontext import cache as _c
    from libcontext.models import FunctionInfo, ModuleInfo, PackageInfo

    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text("# code")

    for name in ("alpha", "beta"):
        pkg = PackageInfo(
            name=name,
            version="1.0.0",
            modules=[
                ModuleInfo(name=f"{name}.core", functions=[FunctionInfo(name="f")])
            ],
        )
        _c.save(pkg, src)

    runner = CliRunner()
    result = runner.invoke(main, ["cache", "clear", "alpha"])

    assert result.exit_code == 0
    assert "1" in result.output
    assert "alpha" in result.output

    remaining = _c.list_entries()
    assert len(remaining) == 1
    assert remaining[0].package == "beta"


def test_cache_list_empty(tmp_path: Path, monkeypatch) -> None:
    """``libctx cache list`` on empty cache shows message."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("libcontext.cache.sys.platform", "linux")

    runner = CliRunner()
    result = runner.invoke(main, ["cache", "list"])

    assert result.exit_code == 0
    assert "empty" in result.output.lower()


def test_cache_list_shows_entries(tmp_path: Path, monkeypatch) -> None:
    """``libctx cache list`` displays cached packages."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("libcontext.cache.sys.platform", "linux")

    from libcontext import cache as _c
    from libcontext.models import FunctionInfo, ModuleInfo, PackageInfo

    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text("# code")

    pkg = PackageInfo(
        name="mypkg",
        version="3.2.1",
        modules=[ModuleInfo(name="mypkg.core", functions=[FunctionInfo(name="f")])],
    )
    _c.save(pkg, src)

    runner = CliRunner()
    result = runner.invoke(main, ["cache", "list"])

    assert result.exit_code == 0
    assert "mypkg" in result.output
    assert "3.2.1" in result.output
    assert "1 entries" in result.output


# ---------------------------------------------------------------------------
# _format_size / _format_age helpers
# ---------------------------------------------------------------------------


def test_format_size_bytes() -> None:
    from libcontext.cli import _format_size

    assert _format_size(500) == "500 B"


def test_format_size_kilobytes() -> None:
    from libcontext.cli import _format_size

    assert _format_size(2048) == "2.0 kB"


def test_format_size_megabytes() -> None:
    from libcontext.cli import _format_size

    assert _format_size(5 * 1024 * 1024) == "5.0 MB"


def test_format_age_just_now() -> None:
    import datetime

    from libcontext.cli import _format_age

    now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    assert _format_age(now) == "just now"


def test_format_age_minutes() -> None:
    import datetime

    from libcontext.cli import _format_age

    ts = (
        datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(minutes=15)
    ).isoformat()
    assert _format_age(ts) == "15m ago"


def test_format_age_hours() -> None:
    import datetime

    from libcontext.cli import _format_age

    ts = (
        datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(hours=3)
    ).isoformat()
    assert _format_age(ts) == "3h ago"


def test_format_age_days() -> None:
    import datetime

    from libcontext.cli import _format_age

    ts = (
        datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(days=7)
    ).isoformat()
    assert _format_age(ts) == "7d ago"


def test_format_age_invalid() -> None:
    from libcontext.cli import _format_age

    assert _format_age("not-a-timestamp") == "unknown age"
    assert _format_age("") == "unknown age"


# ---------------------------------------------------------------------------
# diff subcommand
# ---------------------------------------------------------------------------


def _make_json_snapshot(tmp_path: Path, name: str, version: str) -> Path:
    """Create a minimal API snapshot JSON file."""
    from libcontext.models import _serialize_envelope

    data = _serialize_envelope(
        {
            "name": name,
            "version": version,
            "modules": [
                {
                    "name": f"{name}.core",
                    "functions": [
                        {
                            "name": "hello",
                            "return_annotation": "str",
                            "parameters": [],
                        }
                    ],
                    "classes": [],
                    "variables": [],
                }
            ],
        }
    )
    path = tmp_path / f"{name}-{version}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_diff_markdown(tmp_path: Path) -> None:
    """``libctx diff`` outputs Markdown by default."""
    old = _make_json_snapshot(tmp_path, "mypkg", "1.0")
    new = _make_json_snapshot(tmp_path, "mypkg", "2.0")

    runner = CliRunner()
    result = runner.invoke(main, ["diff", str(old), str(new)])

    assert result.exit_code == 0


def test_diff_json_format(tmp_path: Path) -> None:
    """``libctx diff --format json`` outputs JSON."""
    old = _make_json_snapshot(tmp_path, "mypkg", "1.0")
    new = _make_json_snapshot(tmp_path, "mypkg", "2.0")

    runner = CliRunner()
    result = runner.invoke(main, ["diff", str(old), str(new), "--format", "json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["schema_version"] == 1


def test_diff_invalid_json(tmp_path: Path) -> None:
    """``libctx diff`` with invalid JSON exits with error."""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    good = _make_json_snapshot(tmp_path, "mypkg", "1.0")

    runner = CliRunner()
    result = runner.invoke(main, ["diff", str(bad), str(good)])

    assert result.exit_code == 1
    assert "invalid JSON" in result.output


def test_diff_invalid_envelope(tmp_path: Path) -> None:
    """``libctx diff`` with wrong schema version exits with error."""
    bad = tmp_path / "bad_envelope.json"
    bad.write_text(
        json.dumps({"schema_version": 999, "data": {}}),
        encoding="utf-8",
    )
    good = _make_json_snapshot(tmp_path, "mypkg", "1.0")

    runner = CliRunner()
    result = runner.invoke(main, ["diff", str(good), str(bad)])

    assert result.exit_code == 1
    assert "Unsupported schema version" in result.output


def test_diff_with_changes(tmp_path: Path) -> None:
    """``libctx diff`` detects API changes between snapshots."""
    from libcontext.models import _serialize_envelope

    old_data = _serialize_envelope(
        {
            "name": "mypkg",
            "version": "1.0",
            "modules": [
                {
                    "name": "mypkg.core",
                    "functions": [
                        {"name": "old_func", "parameters": []},
                        {"name": "kept", "parameters": []},
                    ],
                    "classes": [],
                    "variables": [],
                }
            ],
        }
    )
    new_data = _serialize_envelope(
        {
            "name": "mypkg",
            "version": "2.0",
            "modules": [
                {
                    "name": "mypkg.core",
                    "functions": [
                        {"name": "kept", "parameters": []},
                        {"name": "new_func", "parameters": []},
                    ],
                    "classes": [],
                    "variables": [],
                }
            ],
        }
    )

    old_file = tmp_path / "old.json"
    new_file = tmp_path / "new.json"
    old_file.write_text(json.dumps(old_data), encoding="utf-8")
    new_file.write_text(json.dumps(new_data), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["diff", str(old_file), str(new_file)])

    assert result.exit_code == 0
    assert "old_func" in result.output or "new_func" in result.output


# ---------------------------------------------------------------------------
# _write_stdout fallback
# ---------------------------------------------------------------------------


def test_write_stdout_no_buffer(tmp_path: Path) -> None:
    """_write_stdout falls back to click.echo when no .buffer attribute."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Root."""', encoding="utf-8")

    class FakeStdout:
        def __init__(self):
            self.data = ""

        def write(self, s):
            self.data += s

        def flush(self):
            pass

    fake = FakeStdout()
    runner = CliRunner()
    with patch("sys.stdout", fake):
        result = runner.invoke(main, ["inspect", str(pkg)])

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# InspectionError during collect
# ---------------------------------------------------------------------------


def test_inspection_error_exits(tmp_path: Path) -> None:
    """InspectionError during collect_package exits with error."""
    from libcontext.exceptions import InspectionError

    runner = CliRunner()
    with patch(
        "libcontext.cli.collect_package",
        side_effect=InspectionError("/bad/file.py", "syntax error"),
    ):
        result = runner.invoke(main, ["inspect", "somepkg"])

    assert result.exit_code == 1
    assert "Error" in result.output


def test_config_error_during_collect(tmp_path: Path) -> None:
    """ConfigError during collect_package exits with error."""
    from libcontext.exceptions import ConfigError

    runner = CliRunner()
    with patch(
        "libcontext.cli.collect_package",
        side_effect=ConfigError("bad config"),
    ):
        result = runner.invoke(main, ["inspect", "somepkg"])

    assert result.exit_code == 1
    assert "config" in result.output.lower()


# ---------------------------------------------------------------------------
# Output file read OSError
# ---------------------------------------------------------------------------


def test_output_file_read_os_error(sample_package: Path, tmp_path: Path) -> None:
    """OSError when reading existing output file exits with error."""
    out_file = tmp_path / "out.md"
    out_file.write_text("existing", encoding="utf-8")

    runner = CliRunner()
    with patch.object(Path, "read_text", side_effect=OSError("disk error")):
        result = runner.invoke(
            main, ["inspect", str(sample_package), "-o", str(out_file)]
        )

    assert result.exit_code == 1
