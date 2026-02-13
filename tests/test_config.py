"""Tests for the config module."""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path

import pytest

from libcontext.config import (
    LibcontextConfig,
    _load_toml,
    find_config_for_package,
    read_config_from_pyproject,
)

# ---------------------------------------------------------------------------
# LibcontextConfig.from_dict
# ---------------------------------------------------------------------------


def test_from_dict_full() -> None:
    """All fields are populated from a dictionary."""
    data = {
        "include_modules": ["pkg.core", "pkg.models"],
        "exclude_modules": ["pkg.tests"],
        "include_private": True,
        "extra_context": "Extra notes.",
        "max_readme_lines": 50,
    }
    cfg = LibcontextConfig.from_dict(data)

    assert cfg.include_modules == ["pkg.core", "pkg.models"]
    assert cfg.exclude_modules == ["pkg.tests"]
    assert cfg.include_private is True
    assert cfg.extra_context == "Extra notes."
    assert cfg.max_readme_lines == 50


def test_from_dict_empty() -> None:
    """Empty dict yields defaults."""
    cfg = LibcontextConfig.from_dict({})

    assert cfg.include_modules == []
    assert cfg.exclude_modules == []
    assert cfg.include_private is False
    assert cfg.extra_context is None
    assert cfg.max_readme_lines == 100


def test_from_dict_partial() -> None:
    """Partial dict fills only provided fields."""
    cfg = LibcontextConfig.from_dict({"include_private": True})

    assert cfg.include_private is True
    assert cfg.include_modules == []
    assert cfg.max_readme_lines == 100


# ---------------------------------------------------------------------------
# _load_toml
# ---------------------------------------------------------------------------


def test_load_toml_valid(tmp_path: Path) -> None:
    """Loads a well-formed TOML file."""
    toml_file = tmp_path / "test.toml"
    toml_file.write_text(
        textwrap.dedent("""\
        [tool.libcontext]
        include_private = true
        max_readme_lines = 42
        """),
        encoding="utf-8",
    )

    data = _load_toml(toml_file)

    assert "tool" in data
    assert data["tool"]["libcontext"]["include_private"] is True
    assert data["tool"]["libcontext"]["max_readme_lines"] == 42


def test_load_toml_invalid(tmp_path: Path) -> None:
    """Invalid TOML returns empty dict without crashing."""
    bad = tmp_path / "bad.toml"
    bad.write_text("this is not [valid toml =", encoding="utf-8")

    data = _load_toml(bad)
    assert data == {}


def test_load_toml_missing_file(tmp_path: Path) -> None:
    """Non-existent file returns empty dict."""
    data = _load_toml(tmp_path / "nonexistent.toml")
    assert data == {}


# ---------------------------------------------------------------------------
# read_config_from_pyproject
# ---------------------------------------------------------------------------


def test_read_config_with_section(tmp_path: Path) -> None:
    """Reads [tool.libcontext] from pyproject.toml."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        textwrap.dedent("""\
        [project]
        name = "mylib"

        [tool.libcontext]
        include_private = true
        exclude_modules = ["mylib.internal"]
        extra_context = "Use async."
        """),
        encoding="utf-8",
    )

    cfg = read_config_from_pyproject(pyproject)

    assert cfg.include_private is True
    assert cfg.exclude_modules == ["mylib.internal"]
    assert cfg.extra_context == "Use async."


def test_read_config_without_section(tmp_path: Path) -> None:
    """No [tool.libcontext] → default config."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        textwrap.dedent("""\
        [project]
        name = "mylib"
        """),
        encoding="utf-8",
    )

    cfg = read_config_from_pyproject(pyproject)

    assert cfg.include_private is False
    assert cfg.include_modules == []
    assert cfg.extra_context is None


def test_read_config_empty_file(tmp_path: Path) -> None:
    """Empty pyproject.toml → default config."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("", encoding="utf-8")

    cfg = read_config_from_pyproject(pyproject)
    assert cfg == LibcontextConfig()


# ---------------------------------------------------------------------------
# find_config_for_package
# ---------------------------------------------------------------------------


def test_find_config_in_package_dir(tmp_path: Path) -> None:
    """Config at the same level as the package directory."""
    pkg_dir = tmp_path / "mypkg"
    pkg_dir.mkdir()

    pyproject = pkg_dir / "pyproject.toml"
    pyproject.write_text(
        textwrap.dedent("""\
        [tool.libcontext]
        include_private = true
        """),
        encoding="utf-8",
    )

    cfg = find_config_for_package(pkg_dir)
    assert cfg.include_private is True


def test_find_config_in_parent(tmp_path: Path) -> None:
    """Config in the parent directory (project root)."""
    pkg_dir = tmp_path / "mypkg"
    pkg_dir.mkdir()

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        textwrap.dedent("""\
        [tool.libcontext]
        exclude_modules = ["mypkg.tests"]
        """),
        encoding="utf-8",
    )

    cfg = find_config_for_package(pkg_dir)
    assert cfg.exclude_modules == ["mypkg.tests"]


def test_find_config_in_grandparent(tmp_path: Path) -> None:
    """Config in the grandparent (src layout: project/src/pkg)."""
    src = tmp_path / "src"
    pkg_dir = src / "mypkg"
    pkg_dir.mkdir(parents=True)

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        textwrap.dedent("""\
        [tool.libcontext]
        max_readme_lines = 200
        """),
        encoding="utf-8",
    )

    cfg = find_config_for_package(pkg_dir)
    assert cfg.max_readme_lines == 200


def test_find_config_no_section_returns_default(tmp_path: Path) -> None:
    """pyproject.toml exists but has no [tool.libcontext] → default."""
    pkg_dir = tmp_path / "mypkg"
    pkg_dir.mkdir()

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        textwrap.dedent("""\
        [project]
        name = "mypkg"
        """),
        encoding="utf-8",
    )

    cfg = find_config_for_package(pkg_dir)
    assert cfg == LibcontextConfig()


def test_find_config_no_file_returns_default(tmp_path: Path) -> None:
    """No pyproject.toml at all → default config."""
    pkg_dir = tmp_path / "mypkg"
    pkg_dir.mkdir()

    cfg = find_config_for_package(pkg_dir)
    assert cfg == LibcontextConfig()


# ---------------------------------------------------------------------------
# from_dict type validation
# ---------------------------------------------------------------------------


def test_from_dict_bad_include_modules_type() -> None:
    """include_modules as a string raises TypeError."""
    with pytest.raises(TypeError, match="include_modules must be a list"):
        LibcontextConfig.from_dict({"include_modules": "not_a_list"})


def test_from_dict_bad_exclude_modules_type() -> None:
    """exclude_modules as a string raises TypeError."""
    with pytest.raises(TypeError, match="exclude_modules must be a list"):
        LibcontextConfig.from_dict({"exclude_modules": "single"})


def test_from_dict_bad_include_private_type() -> None:
    """include_private as a string raises TypeError."""
    with pytest.raises(TypeError, match="include_private must be a bool"):
        LibcontextConfig.from_dict({"include_private": "yes"})


def test_from_dict_bad_extra_context_type() -> None:
    """extra_context as an int raises TypeError."""
    with pytest.raises(TypeError, match="extra_context must be a string"):
        LibcontextConfig.from_dict({"extra_context": 123})


def test_from_dict_bad_max_readme_lines_type() -> None:
    """max_readme_lines as a string raises TypeError."""
    with pytest.raises(TypeError, match="max_readme_lines must be an integer"):
        LibcontextConfig.from_dict({"max_readme_lines": "fifty"})


def test_from_dict_max_readme_lines_bool_rejected() -> None:
    """max_readme_lines as a bool is rejected (bool is subclass of int)."""
    with pytest.raises(TypeError, match="max_readme_lines must be an integer"):
        LibcontextConfig.from_dict({"max_readme_lines": True})


# ---------------------------------------------------------------------------
# Logging tests
# ---------------------------------------------------------------------------


def test_invalid_toml_logs_warning(tmp_path: Path, caplog) -> None:
    """Invalid TOML content emits a warning log."""
    bad = tmp_path / "bad.toml"
    bad.write_text("this is not [valid toml =", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="libcontext.config"):
        _load_toml(bad)

    assert any("Invalid TOML" in r.message for r in caplog.records)


def test_find_config_logs_debug_when_found(tmp_path: Path, caplog) -> None:
    """find_config_for_package logs debug when config is found."""
    pkg_dir = tmp_path / "mypkg"
    pkg_dir.mkdir()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        textwrap.dedent("""\
        [tool.libcontext]
        include_private = true
        """),
        encoding="utf-8",
    )

    with caplog.at_level(logging.DEBUG, logger="libcontext.config"):
        find_config_for_package(pkg_dir)

    assert any("[tool.libcontext] config" in r.message for r in caplog.records)


def test_find_config_logs_debug_when_not_found(tmp_path: Path, caplog) -> None:
    """find_config_for_package logs debug when no config is found."""
    pkg_dir = tmp_path / "mypkg"
    pkg_dir.mkdir()

    with caplog.at_level(logging.DEBUG, logger="libcontext.config"):
        find_config_for_package(pkg_dir)

    assert any("No [tool.libcontext] config" in r.message for r in caplog.records)
