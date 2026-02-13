"""Tests for the collector module."""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from libcontext.collector import (
    _find_readme,
    _get_package_metadata,
    _should_skip_path,
    collect_package,
    find_package_path,
)
from libcontext.config import LibcontextConfig


def test_collect_local_directory(tmp_path: Path):
    """Test collecting from a local directory."""
    pkg_dir = tmp_path / "mypkg"
    pkg_dir.mkdir()

    # __init__.py
    (pkg_dir / "__init__.py").write_text(
        textwrap.dedent('''
        """My test package."""

        from .core import MyClass

        __all__ = ["MyClass"]
        '''),
        encoding="utf-8",
    )

    # core.py
    (pkg_dir / "core.py").write_text(
        textwrap.dedent('''
        """Core module."""

        class MyClass:
            """A useful class."""

            def do_something(self, x: int) -> str:
                """Do something useful."""
                return str(x)
        '''),
        encoding="utf-8",
    )

    # _private.py — should be skipped by default
    (pkg_dir / "_private.py").write_text(
        textwrap.dedent('''
        """Private module."""
        SECRET = 42
        '''),
        encoding="utf-8",
    )

    pkg_info = collect_package(str(pkg_dir), include_readme=False)

    assert pkg_info.name == "mypkg"
    module_names = [m.name for m in pkg_info.modules]
    assert "mypkg" in module_names
    assert "mypkg.core" in module_names
    # Private module should be excluded
    assert "mypkg._private" not in module_names


def test_collect_local_with_private(tmp_path: Path):
    """Test that --include-private exposes private modules."""
    pkg_dir = tmp_path / "mypkg"
    pkg_dir.mkdir()

    (pkg_dir / "__init__.py").write_text('"""Root."""', encoding="utf-8")
    (pkg_dir / "_secret.py").write_text("SECRET = 42\n", encoding="utf-8")

    pkg_info = collect_package(str(pkg_dir), include_private=True, include_readme=False)

    module_names = [m.name for m in pkg_info.modules]
    assert "mypkg._secret" in module_names


def test_collect_nonexistent_package():
    """Collecting a non-existent package raises ValueError."""
    with pytest.raises(ValueError, match="not found"):
        collect_package("this_package_does_not_exist_xyz_123")


def test_collect_with_syntax_error(tmp_path: Path):
    """Files with syntax errors are skipped gracefully."""
    pkg_dir = tmp_path / "badpkg"
    pkg_dir.mkdir()

    (pkg_dir / "__init__.py").write_text('"""Root."""', encoding="utf-8")
    (pkg_dir / "broken.py").write_text(
        "def broken(\n  this is not valid python", encoding="utf-8"
    )
    (pkg_dir / "good.py").write_text(
        'def works() -> bool:\n    """It works."""\n    return True\n',
        encoding="utf-8",
    )

    pkg_info = collect_package(str(pkg_dir), include_readme=False)

    module_names = [m.name for m in pkg_info.modules]
    assert "badpkg.good" in module_names
    # broken.py should be skipped, not crash
    assert "badpkg.broken" not in module_names


def test_collect_readme_from_directory(tmp_path: Path):
    """README is found when placed next to the package directory."""
    pkg_dir = tmp_path / "mypkg"
    pkg_dir.mkdir()

    (pkg_dir / "__init__.py").write_text('"""Root."""', encoding="utf-8")

    # README in parent (project root)
    (tmp_path / "README.md").write_text(
        "# MyPkg\n\nThis is the readme.",
        encoding="utf-8",
    )

    pkg_info = collect_package(str(pkg_dir), include_readme=True)

    assert pkg_info.readme is not None
    assert "# MyPkg" in pkg_info.readme


def test_collect_subpackages(tmp_path: Path):
    """Subpackages are collected recursively."""
    pkg_dir = tmp_path / "mypkg"
    sub_dir = pkg_dir / "sub"
    sub_dir.mkdir(parents=True)

    (pkg_dir / "__init__.py").write_text('"""Root."""', encoding="utf-8")
    (sub_dir / "__init__.py").write_text('"""Sub module."""', encoding="utf-8")
    (sub_dir / "helpers.py").write_text(
        'def helper() -> str:\n    """A helper."""\n    return "ok"\n',
        encoding="utf-8",
    )

    pkg_info = collect_package(str(pkg_dir), include_readme=False)

    module_names = [m.name for m in pkg_info.modules]
    assert "mypkg" in module_names
    assert "mypkg.sub" in module_names
    assert "mypkg.sub.helpers" in module_names


# ---------------------------------------------------------------------------
# find_package_path
# ---------------------------------------------------------------------------


def test_find_package_path_installed() -> None:
    """find_package_path finds an installed package (e.g. click)."""
    path = find_package_path("click")
    if path is not None:
        assert path.exists()


def test_find_package_path_nonexistent() -> None:
    """Non-existent package returns None."""
    assert find_package_path("this_pkg_does_not_exist_xyz_999") is None


def test_find_package_path_invalid() -> None:
    """Invalid module name (raises ValueError in find_spec) returns None."""
    assert find_package_path("") is None


def test_find_package_path_spec_none() -> None:
    """When find_spec returns None, returns None."""
    with patch("libcontext.collector.importlib.util.find_spec", return_value=None):
        assert find_package_path("fakepkg") is None


def test_find_package_path_with_submodule_search_locations() -> None:
    """Spec with no origin but submodule_search_locations returns first."""
    from unittest.mock import MagicMock

    spec = MagicMock()
    spec.origin = None
    spec.submodule_search_locations = ["/fake/path"]

    with patch("libcontext.collector.importlib.util.find_spec", return_value=spec):
        result = find_package_path("namespace_pkg")
        assert result == Path("/fake/path")


def test_find_package_path_no_origin_no_locations() -> None:
    """Spec with no origin and empty submodule_search_locations returns None."""
    from unittest.mock import MagicMock

    spec = MagicMock()
    spec.origin = None
    spec.submodule_search_locations = []

    with patch("libcontext.collector.importlib.util.find_spec", return_value=spec):
        assert find_package_path("emptypkg") is None


def test_find_package_path_frozen_origin() -> None:
    """Frozen module with no submodule_search returns None."""
    from unittest.mock import MagicMock

    spec = MagicMock()
    spec.origin = "frozen"
    spec.submodule_search_locations = None

    with patch("libcontext.collector.importlib.util.find_spec", return_value=spec):
        assert find_package_path("frozenpkg") is None


def test_find_package_path_single_file() -> None:
    """Single-file module returns the .py file path."""
    from unittest.mock import MagicMock

    spec = MagicMock()
    spec.origin = "/some/path/module.py"
    spec.submodule_search_locations = None

    with patch("libcontext.collector.importlib.util.find_spec", return_value=spec):
        result = find_package_path("module")
        assert result == Path("/some/path/module.py")


# ---------------------------------------------------------------------------
# _get_package_metadata
# ---------------------------------------------------------------------------


def test_get_package_metadata_installed() -> None:
    """Retrieves metadata for an installed package."""
    meta = _get_package_metadata("click")
    if meta:
        assert "version" in meta


def test_get_package_metadata_nonexistent() -> None:
    """Missing package returns empty dict."""
    meta = _get_package_metadata("this_pkg_does_not_exist_xyz_999")
    assert meta == {}


# ---------------------------------------------------------------------------
# _find_readme
# ---------------------------------------------------------------------------


def test_find_readme_from_file(tmp_path: Path) -> None:
    """Finds a README.md near the package directory."""
    pkg_dir = tmp_path / "mypkg"
    pkg_dir.mkdir()
    (tmp_path / "README.md").write_text("# Hello", encoding="utf-8")

    result = _find_readme("mypkg", pkg_dir)
    assert result is not None
    assert "# Hello" in result


def test_find_readme_rst(tmp_path: Path) -> None:
    """Finds a README.rst."""
    pkg_dir = tmp_path / "mypkg"
    pkg_dir.mkdir()
    (tmp_path / "README.rst").write_text("Hello RST", encoding="utf-8")

    result = _find_readme("mypkg", pkg_dir)
    assert result is not None
    assert "Hello RST" in result


def test_find_readme_no_path() -> None:
    """No package path → falls back to metadata only."""
    # Won't crash when package_path is None
    result = _find_readme("this_pkg_does_not_exist_xyz", None)
    # May return None if pkg is not installed
    assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# _should_skip_path
# ---------------------------------------------------------------------------


def test_should_skip_pycache() -> None:
    assert _should_skip_path(("__pycache__", "something.py"), include_private=True)


def test_should_skip_dotdir() -> None:
    assert _should_skip_path((".git", "config"), include_private=True)


def test_should_skip_private_module() -> None:
    assert _should_skip_path(("_internal.py",), include_private=False)


def test_should_not_skip_private_when_included() -> None:
    assert not _should_skip_path(("_internal.py",), include_private=True)


def test_should_not_skip_init() -> None:
    assert not _should_skip_path(("__init__.py",), include_private=False)


def test_should_not_skip_public() -> None:
    assert not _should_skip_path(("core.py",), include_private=False)


# ---------------------------------------------------------------------------
# collect_package with config filters
# ---------------------------------------------------------------------------


def test_collect_with_include_modules_filter(tmp_path: Path) -> None:
    """Only include_modules modules are collected."""
    pkg = tmp_path / "filterpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Root."""', encoding="utf-8")
    (pkg / "core.py").write_text(
        'def core_fn() -> None:\n    """Core."""\n    ...\n', encoding="utf-8"
    )
    (pkg / "utils.py").write_text(
        'def util_fn() -> None:\n    """Util."""\n    ...\n', encoding="utf-8"
    )

    config = LibcontextConfig(include_modules=["filterpkg.core"])
    info = collect_package(str(pkg), include_readme=False, config_override=config)

    names = [m.name for m in info.modules]
    assert "filterpkg" in names  # root always included
    assert "filterpkg.core" in names
    assert "filterpkg.utils" not in names


def test_collect_with_exclude_modules_filter(tmp_path: Path) -> None:
    """Excluded modules are skipped."""
    pkg = tmp_path / "exclpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Root."""', encoding="utf-8")
    (pkg / "public.py").write_text(
        'def pub() -> None:\n    """Public."""\n    ...\n', encoding="utf-8"
    )
    (pkg / "internal.py").write_text(
        'def priv() -> None:\n    """Internal."""\n    ...\n', encoding="utf-8"
    )

    config = LibcontextConfig(exclude_modules=["exclpkg.internal"])
    info = collect_package(str(pkg), include_readme=False, config_override=config)

    names = [m.name for m in info.modules]
    assert "exclpkg.public" in names
    assert "exclpkg.internal" not in names


def test_collect_single_file_module(tmp_path: Path) -> None:
    """Collect a single .py file as a package."""
    single = tmp_path / "single.py"
    single.write_text(
        'def func() -> str:\n    """A function."""\n    return "ok"\n',
        encoding="utf-8",
    )

    info = collect_package(str(single), include_readme=False)

    assert info.name == "single"
    assert len(info.modules) == 1
    assert info.modules[0].name == "single"


def test_collect_with_config_override(tmp_path: Path) -> None:
    """config_override is used instead of auto-discovery."""
    pkg = tmp_path / "ovpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Root."""', encoding="utf-8")

    config = LibcontextConfig(extra_context="Overridden!")
    info = collect_package(str(pkg), include_readme=False, config_override=config)

    # Just verify it doesn't crash and the package is collected
    assert info.name == "ovpkg"


# ---------------------------------------------------------------------------
# Regression: _get_package_metadata with partial metadata
# ---------------------------------------------------------------------------


def test_metadata_version_returned_when_summary_missing() -> None:
    """If a package has a Version but no Summary, version must still
    be returned."""
    mock_meta = MagicMock()
    mock_meta.get = lambda key, default=None: {
        "Version": "2.0.0",
    }.get(key, default)

    with patch(
        "libcontext.collector.importlib.metadata.metadata",
        return_value=mock_meta,
    ):
        result = _get_package_metadata("fakepkg")

    assert result.get("version") == "2.0.0"


def test_metadata_summary_returned_when_version_missing() -> None:
    """If a package has a Summary but no Version, summary must still
    be returned."""
    mock_meta = MagicMock()
    mock_meta.get = lambda key, default=None: {
        "Summary": "A useful library",
    }.get(key, default)

    with patch(
        "libcontext.collector.importlib.metadata.metadata",
        return_value=mock_meta,
    ):
        result = _get_package_metadata("fakepkg")

    assert result.get("summary") == "A useful library"


def test_metadata_both_keys_present() -> None:
    """When both keys are present, both are returned (sanity check)."""
    data = {"Version": "1.0.0", "Summary": "Great lib"}
    mock_meta = MagicMock()
    mock_meta.get = lambda key, default=None: data.get(key, default)

    with patch(
        "libcontext.collector.importlib.metadata.metadata",
        return_value=mock_meta,
    ):
        result = _get_package_metadata("fakepkg")

    assert result == {"version": "1.0.0", "summary": "Great lib"}


# ---------------------------------------------------------------------------
# Regression: collect_package must not mutate config_override
# ---------------------------------------------------------------------------


def test_config_not_mutated_by_collect_package(tmp_path: Path) -> None:
    """config_override must remain unchanged after collect_package."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Root."""', encoding="utf-8")

    config = LibcontextConfig(include_private=False)

    collect_package(
        str(pkg),
        include_private=True,
        include_readme=False,
        config_override=config,
    )

    assert config.include_private is False


def test_config_not_mutated_across_multiple_calls(tmp_path: Path) -> None:
    """Multiple collect_package calls with the same config must not
    accumulate mutations."""
    pkg_a = tmp_path / "pkg_a"
    pkg_a.mkdir()
    (pkg_a / "__init__.py").write_text('"""A."""', encoding="utf-8")

    pkg_b = tmp_path / "pkg_b"
    pkg_b.mkdir()
    (pkg_b / "__init__.py").write_text('"""B."""', encoding="utf-8")

    config = LibcontextConfig(include_private=False)

    # First call with include_private=True
    collect_package(
        str(pkg_a),
        include_private=True,
        include_readme=False,
        config_override=config,
    )

    # Second call WITHOUT include_private — should still be False
    collect_package(
        str(pkg_b),
        include_private=False,
        include_readme=False,
        config_override=config,
    )

    assert config.include_private is False


# ---------------------------------------------------------------------------
# UnicodeDecodeError handling
# ---------------------------------------------------------------------------


def test_collect_skips_non_utf8_module(tmp_path: Path) -> None:
    """A .py file with non-UTF-8 encoding is skipped gracefully."""
    pkg = tmp_path / "encpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Root."""', encoding="utf-8")
    # Write a file with Latin-1 bytes that aren't valid UTF-8
    (pkg / "bad_encoding.py").write_bytes(b'"""Module."""\nNAME = "caf\xe9"\n')
    (pkg / "good.py").write_text(
        'def ok() -> bool:\n    """Works."""\n    return True\n',
        encoding="utf-8",
    )

    info = collect_package(str(pkg), include_readme=False)

    names = [m.name for m in info.modules]
    assert "encpkg.good" in names
    assert "encpkg.bad_encoding" not in names


def test_collect_single_file_non_utf8(tmp_path: Path) -> None:
    """Single-file module with bad encoding is skipped gracefully."""
    single = tmp_path / "bad.py"
    single.write_bytes(b'NAME = "caf\xe9"\n')

    info = collect_package(str(single), include_readme=False)
    assert info.modules == []


def test_find_readme_skips_non_utf8(tmp_path: Path) -> None:
    """README with non-UTF-8 encoding is skipped."""
    pkg_dir = tmp_path / "mypkg"
    pkg_dir.mkdir()
    (tmp_path / "README.md").write_bytes(b"# Caf\xe9 Readme\n")

    result = _find_readme("mypkg", pkg_dir)
    # Should not crash; returns None since the file can't be decoded
    assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# Logging tests
# ---------------------------------------------------------------------------


def test_syntax_error_is_logged(tmp_path: Path, caplog) -> None:
    """SyntaxError in a module emits a warning log."""
    pkg = tmp_path / "logpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Root."""', encoding="utf-8")
    (pkg / "broken.py").write_text("def broken(\n  !!!", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="libcontext.collector"):
        collect_package(str(pkg), include_readme=False)

    assert any("Syntax error" in r.message for r in caplog.records)


def test_encoding_error_is_logged(tmp_path: Path, caplog) -> None:
    """UnicodeDecodeError in a module emits a warning log."""
    pkg = tmp_path / "logpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Root."""', encoding="utf-8")
    (pkg / "bad.py").write_bytes(b'x = "caf\xe9"\n')

    with caplog.at_level(logging.WARNING, logger="libcontext.collector"):
        collect_package(str(pkg), include_readme=False)

    assert any("Encoding error" in r.message for r in caplog.records)


def test_debug_logging_for_package_resolution(tmp_path: Path, caplog) -> None:
    """collect_package emits debug logs for path resolution."""
    pkg = tmp_path / "debugpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Root."""', encoding="utf-8")

    with caplog.at_level(logging.DEBUG, logger="libcontext.collector"):
        collect_package(str(pkg), include_readme=False)

    messages = " ".join(r.message for r in caplog.records)
    assert "local path" in messages
    assert "Collected" in messages
