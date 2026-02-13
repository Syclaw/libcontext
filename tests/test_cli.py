"""Tests for the CLI module."""

from __future__ import annotations

import io
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
    result = runner.invoke(main, [str(sample_package)])

    assert result.exit_code == 0
    assert "API Reference" in result.output


def test_output_to_file(sample_package: Path, tmp_path: Path) -> None:
    """``-o`` writes Markdown to a file with markers."""
    out_file = tmp_path / "out" / "copilot.md"
    runner = CliRunner()
    result = runner.invoke(main, [str(sample_package), "-o", str(out_file)])

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
    result = runner.invoke(main, [str(sample_package), "-o", str(out_file)])

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
    result = runner.invoke(main, [str(sample_package), "-q"])

    assert result.exit_code == 0
    # With -q, no "Inspecting" message in output
    assert "Inspecting" not in result.output


def test_no_readme_flag(sample_package: Path) -> None:
    """``--no-readme`` excludes readme section."""
    runner = CliRunner()
    result = runner.invoke(main, [str(sample_package), "--no-readme"])

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
    result_without = runner.invoke(main, [str(pkg)])
    # With flag — private included
    result_with = runner.invoke(main, [str(pkg), "--include-private"])

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
    result = runner.invoke(main, [str(pkg), "--max-readme-lines", "5"])

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
    result = runner.invoke(main, [str(pkg), "--config", str(pyproject)])

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
        main, [str(pkg), "--config", str(pyproject), "--include-private"]
    )

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_nonexistent_package() -> None:
    """Non-existent package exits with code 1 and error message."""
    runner = CliRunner()
    result = runner.invoke(main, ["this_package_does_not_exist_xyz"])

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
    result = runner.invoke(main, [str(tmp_path / "pkg_a"), str(tmp_path / "pkg_b")])

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
        [str(tmp_path / "pkg_x"), str(tmp_path / "pkg_y"), "-o", str(out_file)],
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
    result = runner.invoke(main, [str(sample_package)])

    assert result.exit_code == 0
    # Click mixes stderr into output by default in CliRunner
    assert "Inspecting" in result.output
    assert "modules" in result.output


def test_file_output_stderr_message(sample_package: Path, tmp_path: Path) -> None:
    """Writing to file prints 'Context written to ...' message."""
    out_file = tmp_path / "out.md"
    runner = CliRunner()
    result = runner.invoke(main, [str(sample_package), "-o", str(out_file)])

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
        result = runner.invoke(main, [str(pkg)])

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
    result = runner.invoke(main, [str(pkg)])

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
    result = runner.invoke(main, [str(sample_package), "-o", str(out_file)])

    assert result.exit_code == 1
    assert "not valid UTF-8" in result.output


def test_output_file_write_permission_error(
    sample_package: Path, tmp_path: Path
) -> None:
    """OSError when writing output file exits with error."""
    out_file = tmp_path / "output.md"

    runner = CliRunner()
    with patch.object(Path, "write_text", side_effect=OSError("Permission denied")):
        result = runner.invoke(main, [str(sample_package), "-o", str(out_file)])

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
    result = runner.invoke(main, [str(pkg), "--config", str(pyproject)])

    assert result.exit_code == 1
    assert "config" in result.output.lower()


def test_verbose_flag(sample_package: Path) -> None:
    """``--verbose`` enables debug logging without crashing."""
    runner = CliRunner()
    result = runner.invoke(main, [str(sample_package), "-v"])

    assert result.exit_code == 0
