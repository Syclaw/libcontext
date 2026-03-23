"""Tests for the collector module."""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from libcontext.collector import (
    _find_readme,
    _get_installed_package_names,
    _get_package_metadata,
    _is_compiled_extension,
    _is_safe_source_file,
    _merge_classes,
    _merge_module,
    _module_name_from_path,
    _should_skip_path,
    _walk_package,
    collect_package,
    find_package_path,
    suggest_similar_packages,
)
from libcontext.config import LibcontextConfig
from libcontext.exceptions import InspectionError, PackageNotFoundError
from libcontext.models import (
    ClassInfo,
    FunctionInfo,
    ModuleInfo,
    VariableInfo,
)


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
    """Collecting a non-existent package raises PackageNotFoundError."""
    with pytest.raises(PackageNotFoundError, match="not found"):
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
    spec = MagicMock()
    spec.origin = None
    spec.submodule_search_locations = ["/fake/path"]

    with patch("libcontext.collector.importlib.util.find_spec", return_value=spec):
        result = find_package_path("namespace_pkg")
        assert result == Path("/fake/path")


def test_find_package_path_no_origin_no_locations() -> None:
    """Spec with no origin and empty submodule_search_locations returns None."""
    spec = MagicMock()
    spec.origin = None
    spec.submodule_search_locations = []

    with patch("libcontext.collector.importlib.util.find_spec", return_value=spec):
        assert find_package_path("emptypkg") is None


def test_find_package_path_frozen_origin() -> None:
    """Frozen module with no submodule_search returns None."""
    spec = MagicMock()
    spec.origin = "frozen"
    spec.submodule_search_locations = None

    with patch("libcontext.collector.importlib.util.find_spec", return_value=spec):
        assert find_package_path("frozenpkg") is None


def test_find_package_path_single_file() -> None:
    """Single-file module returns the .py file path."""
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
    """No package path and no installed metadata → returns None."""
    result = _find_readme("this_pkg_does_not_exist_xyz", None)
    assert result is None


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
    """Single-file module with bad encoding raises InspectionError."""
    single = tmp_path / "bad.py"
    single.write_bytes(b'NAME = "caf\xe9"\n')

    with pytest.raises(InspectionError):
        collect_package(str(single), include_readme=False)


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

    assert any("Skipped" in r.message for r in caplog.records)


def test_encoding_error_is_logged(tmp_path: Path, caplog) -> None:
    """UnicodeDecodeError in a module emits a warning log."""
    pkg = tmp_path / "logpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Root."""', encoding="utf-8")
    (pkg / "bad.py").write_bytes(b'x = "caf\xe9"\n')

    with caplog.at_level(logging.WARNING, logger="libcontext.collector"):
        collect_package(str(pkg), include_readme=False)

    assert any("Skipped" in r.message for r in caplog.records)


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


# ---------------------------------------------------------------------------
# Package name suggestions
# ---------------------------------------------------------------------------

_DISTS_PATH = "libcontext.collector.importlib.metadata.distributions"


def _make_mock_dist(name: str, top_level: str | None = None) -> MagicMock:
    """Create a mock distribution object for testing."""
    dist = MagicMock()
    dist.metadata = {"Name": name}
    dist.read_text = MagicMock(return_value=top_level)
    return dist


def test_get_installed_package_names_collects_distributions() -> None:
    """Distribution names and normalized forms are collected."""
    dists = [
        _make_mock_dist("requests"),
        _make_mock_dist("scikit-learn", top_level="sklearn\n"),
    ]
    with patch(_DISTS_PATH, return_value=dists):
        names = _get_installed_package_names()

    assert "requests" in names
    assert "scikit-learn" in names
    assert "scikit_learn" in names
    assert "sklearn" in names


def test_get_installed_package_names_deduplicates() -> None:
    """Duplicate distributions are seen only once."""
    dists = [
        _make_mock_dist("requests"),
        _make_mock_dist("requests"),
    ]
    with patch(_DISTS_PATH, return_value=dists):
        names = _get_installed_package_names()

    assert names.count("requests") == 1


def test_suggest_similar_packages_finds_close_match() -> None:
    """A typo like 'reqeusts' matches 'requests'."""
    dists = [
        _make_mock_dist("requests"),
        _make_mock_dist("flask"),
        _make_mock_dist("numpy"),
    ]
    with patch(_DISTS_PATH, return_value=dists):
        suggestions = suggest_similar_packages("reqeusts")

    assert "requests" in suggestions


def test_suggest_similar_packages_no_match() -> None:
    """A completely unrelated name returns no suggestions."""
    dists = [
        _make_mock_dist("requests"),
        _make_mock_dist("flask"),
    ]
    with patch(_DISTS_PATH, return_value=dists):
        suggestions = suggest_similar_packages("xyzzy_not_a_package")

    assert suggestions == []


def test_suggest_similar_packages_max_results() -> None:
    """At most 3 suggestions are returned."""
    dists = [_make_mock_dist(f"aaa{i}") for i in range(10)]
    with patch(_DISTS_PATH, return_value=dists):
        suggestions = suggest_similar_packages("aaa0")

    assert len(suggestions) <= 3


def test_suggest_similar_packages_uses_top_level_names() -> None:
    """Import names from top_level.txt are included as candidates."""
    dists = [
        _make_mock_dist("Pillow", top_level="PIL\n"),
    ]
    with patch(_DISTS_PATH, return_value=dists):
        suggestions = suggest_similar_packages("PIl")

    assert "PIL" in suggestions


def test_collect_package_error_includes_suggestions() -> None:
    """PackageNotFoundError from collect_package includes suggestions."""
    dists = [
        _make_mock_dist("click"),
        _make_mock_dist("flask"),
    ]
    with (
        patch(_DISTS_PATH, return_value=dists),
        pytest.raises(PackageNotFoundError, match="Did you mean"),
    ):
        collect_package("clck")


def test_collect_package_error_no_suggestions() -> None:
    """PackageNotFoundError without suggestions shows install hint."""
    with (
        patch(_DISTS_PATH, return_value=[]),
        pytest.raises(PackageNotFoundError, match="Make sure it is installed"),
    ):
        collect_package("totally_nonexistent_pkg_xyz_999")


# ---------------------------------------------------------------------------
# Stub file .pyi support
# ---------------------------------------------------------------------------


def test_module_name_from_path_pyi(tmp_path: Path):
    """_module_name_from_path handles .pyi files."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    pyi = pkg / "core.pyi"
    pyi.touch()

    assert _module_name_from_path(pyi, pkg, "mypkg") == "mypkg.core"


def test_module_name_from_path_pyi_init(tmp_path: Path):
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    init = pkg / "__init__.pyi"
    init.touch()

    assert _module_name_from_path(init, pkg, "mypkg") == "mypkg"


def test_should_skip_path_init_pyi():
    assert _should_skip_path(("__init__.pyi",), include_private=False) is False


def test_should_skip_path_private_pyi():
    assert _should_skip_path(("_private.pyi",), include_private=False) is True
    assert _should_skip_path(("_private.pyi",), include_private=True) is False


def test_is_compiled_extension_so(tmp_path: Path):
    so = tmp_path / "module.cpython-312-x86_64-linux-gnu.so"
    so.touch()
    assert _is_compiled_extension(so) is True


def test_is_compiled_extension_py(tmp_path: Path):
    py = tmp_path / "module.py"
    py.touch()
    assert _is_compiled_extension(py) is False


def test_is_compiled_extension_dir_no_init(tmp_path: Path):
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    assert _is_compiled_extension(pkg) is True


def test_is_compiled_extension_dir_with_init(tmp_path: Path):
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").touch()
    assert _is_compiled_extension(pkg) is False


def test_is_compiled_extension_dir_with_pyi_init(tmp_path: Path):
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.pyi").touch()
    assert _is_compiled_extension(pkg) is False


def test_merge_module_basic():
    """Merge takes signatures from .pyi and docstrings from .py."""
    py_mod = ModuleInfo(
        name="pkg.core",
        path="/src/pkg/core.py",
        docstring="Module docstring.",
        functions=[
            FunctionInfo(
                name="greet",
                return_annotation=None,
                docstring="Say hello.",
                line_number=5,
            ),
        ],
        variables=[
            VariableInfo(name="X", value="42"),
        ],
    )

    pyi_mod = ModuleInfo(
        name="pkg.core",
        path="/src/pkg/core.pyi",
        functions=[
            FunctionInfo(
                name="greet",
                return_annotation="str",
                line_number=1,
            ),
        ],
        variables=[
            VariableInfo(name="X", annotation="int"),
        ],
    )

    merged = _merge_module(py_mod, pyi_mod)

    assert merged.docstring == "Module docstring."
    assert merged.path == "/src/pkg/core.py"

    func = merged.functions[0]
    assert func.return_annotation == "str"
    assert func.docstring == "Say hello."
    assert func.line_number == 5

    var = merged.variables[0]
    assert var.annotation == "int"
    assert var.value == "42"


def test_merge_module_pyi_only_member():
    """Members in .pyi but not .py are included."""
    py_mod = ModuleInfo(name="pkg.core", functions=[])
    pyi_mod = ModuleInfo(
        name="pkg.core",
        functions=[FunctionInfo(name="new_func", return_annotation="int")],
    )
    merged = _merge_module(py_mod, pyi_mod)
    assert len(merged.functions) == 1
    assert merged.functions[0].name == "new_func"


def test_merge_module_py_only_member():
    """Members in .py but not .pyi (partial stubs) are included."""
    py_mod = ModuleInfo(
        name="pkg.core",
        functions=[FunctionInfo(name="old_func", docstring="Old.")],
    )
    pyi_mod = ModuleInfo(name="pkg.core", functions=[])
    merged = _merge_module(py_mod, pyi_mod)
    assert len(merged.functions) == 1
    assert merged.functions[0].name == "old_func"


def test_merge_module_preserves_is_type_alias():
    """Merge preserves is_type_alias from .pyi."""
    py_mod = ModuleInfo(
        name="pkg.core",
        variables=[VariableInfo(name="T", value="int")],
    )
    pyi_mod = ModuleInfo(
        name="pkg.core",
        variables=[
            VariableInfo(name="T", annotation="TypeAlias", is_type_alias=True),
        ],
    )
    merged = _merge_module(py_mod, pyi_mod)
    assert merged.variables[0].is_type_alias is True


def test_merge_module_all_exports_from_py():
    """.py __all__ takes priority over .pyi."""
    py_mod = ModuleInfo(name="pkg", all_exports=["A"])
    pyi_mod = ModuleInfo(name="pkg", all_exports=["A", "B"])
    merged = _merge_module(py_mod, pyi_mod)
    assert merged.all_exports == ["A"]


def test_walk_package_py_only(tmp_path: Path):
    """Walk a package with .py files only — unchanged behavior."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Init."""\n', encoding="utf-8")
    (pkg / "core.py").write_text(
        'def hello() -> str:\n    """Hi."""\n    return "hi"\n',
        encoding="utf-8",
    )

    config = LibcontextConfig()
    modules = _walk_package(pkg, "mypkg", config)

    assert len(modules) == 2
    assert all(m.stub_source == "" for m in modules)


def test_walk_package_pyi_only(tmp_path: Path):
    """Walk a package with .pyi files only."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.pyi").write_text("", encoding="utf-8")
    (pkg / "core.pyi").write_text("def hello() -> str: ...\n", encoding="utf-8")

    config = LibcontextConfig()
    modules = _walk_package(pkg, "mypkg", config)

    names = [m.name for m in modules]
    assert "mypkg.core" in names


def test_walk_package_colocated_merge(tmp_path: Path):
    """Walk a package with colocated .py + .pyi."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(
        'def hello():\n    """Say hello."""\n    return "hi"\n',
        encoding="utf-8",
    )
    (pkg / "core.pyi").write_text("def hello() -> str: ...\n", encoding="utf-8")

    config = LibcontextConfig()
    modules = _walk_package(pkg, "mypkg", config)

    core = next(m for m in modules if m.name == "mypkg.core")
    assert core.stub_source == "colocated"
    func = core.functions[0]
    assert func.return_annotation == "str"
    assert func.docstring == "Say hello."


def test_walk_package_standalone_stubs(tmp_path: Path):
    """Walk a package with standalone stub directory."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(
        'def hello():\n    """Say hello."""\n    return "hi"\n',
        encoding="utf-8",
    )

    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "__init__.pyi").write_text("", encoding="utf-8")
    (stubs / "core.pyi").write_text("def hello() -> str: ...\n", encoding="utf-8")

    config = LibcontextConfig()
    modules = _walk_package(pkg, "mypkg", config, stub_path=stubs)

    core = next(m for m in modules if m.name == "mypkg.core")
    assert core.stub_source == "standalone"
    assert core.functions[0].return_annotation == "str"
    assert core.functions[0].docstring == "Say hello."


def test_walk_package_single_file_with_stub(tmp_path: Path):
    """Single-file module with colocated .pyi stub."""
    py_file = tmp_path / "mod.py"
    pyi_file = tmp_path / "mod.pyi"
    py_file.write_text('def f():\n    """Doc."""\n', encoding="utf-8")
    pyi_file.write_text("def f() -> int: ...\n", encoding="utf-8")

    config = LibcontextConfig()
    modules = _walk_package(py_file, "mod", config)

    assert len(modules) == 1
    assert modules[0].stub_source == "colocated"
    assert modules[0].functions[0].return_annotation == "int"
    assert modules[0].functions[0].docstring == "Doc."


def test_walk_package_pyi_syntax_error(tmp_path: Path):
    """Invalid .pyi is skipped gracefully, .py used alone."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text("def f(): pass\n", encoding="utf-8")
    (pkg / "core.pyi").write_text("def f( -> broken\n", encoding="utf-8")

    config = LibcontextConfig()
    modules = _walk_package(pkg, "mypkg", config)

    core = next(m for m in modules if m.name == "mypkg.core")
    assert core.stub_source == ""


def test_is_compiled_extension_nonexistent(tmp_path: Path):
    """Test _is_compiled_extension returns False for nonexistent path."""
    fake = tmp_path / "nonexistent"
    assert _is_compiled_extension(fake) is False


def test_merge_classes_basic():
    """Test _merge_classes merges docstrings from py and signatures from pyi."""
    py_classes = [
        ClassInfo(
            name="Foo",
            docstring="Py doc.",
            methods=[FunctionInfo(name="m", docstring="Method doc.")],
        ),
    ]
    pyi_classes = [
        ClassInfo(
            name="Foo",
            methods=[FunctionInfo(name="m", return_annotation="int")],
        ),
    ]
    merged = _merge_classes(py_classes, pyi_classes)
    assert len(merged) == 1
    assert merged[0].docstring == "Py doc."
    assert merged[0].methods[0].return_annotation == "int"
    assert merged[0].methods[0].docstring == "Method doc."


def test_merge_classes_pyi_only_class():
    """Test that a class only in pyi is included in merged result."""
    py_classes: list[ClassInfo] = []
    pyi_classes = [
        ClassInfo(name="OnlyPyi", docstring="Pyi only.", methods=[]),
    ]
    merged = _merge_classes(py_classes, pyi_classes)
    assert len(merged) == 1
    assert merged[0].name == "OnlyPyi"


def test_merge_classes_py_only_class():
    """Test that a class only in py is included in merged result."""
    py_classes = [
        ClassInfo(name="OnlyPy", docstring="Py only.", methods=[]),
    ]
    pyi_classes: list[ClassInfo] = []
    merged = _merge_classes(py_classes, pyi_classes)
    assert len(merged) == 1
    assert merged[0].name == "OnlyPy"
    assert merged[0].docstring == "Py only."


def test_is_safe_source_file_symlink_escape(tmp_path: Path):
    """Test _is_safe_source_file rejects symlinks escaping the package boundary."""
    target = tmp_path.parent / "escape_target.py"
    target.write_text("x = 1", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    link = pkg / "link.py"
    try:
        link.symlink_to(target)
    except OSError:
        return  # Skip if symlinks not supported
    assert _is_safe_source_file(link, pkg) is False


def test_is_safe_source_file_oversized(tmp_path: Path):
    """Test _is_safe_source_file rejects files exceeding size limit."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    big = pkg / "big.py"
    big.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    assert _is_safe_source_file(big, pkg) is False


def test_is_safe_source_file_normal(tmp_path: Path):
    """Test _is_safe_source_file accepts a normal file within boundary."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    normal = pkg / "normal.py"
    normal.write_text("x = 1", encoding="utf-8")
    assert _is_safe_source_file(normal, pkg) is True


def test_walk_package_single_file_py_fails_pyi_used(tmp_path: Path):
    """Test single-file module falls back to .pyi when .py has syntax error."""
    py_file = tmp_path / "mod.py"
    pyi_file = tmp_path / "mod.pyi"
    py_file.write_text("def f( -> broken\n", encoding="utf-8")
    pyi_file.write_text("def f() -> int: ...\n", encoding="utf-8")
    config = LibcontextConfig()
    modules = _walk_package(py_file, "mod", config)
    assert len(modules) == 1
    assert modules[0].stub_source == "colocated"
    assert modules[0].functions[0].return_annotation == "int"


def test_walk_package_single_file_py_fails_no_pyi_raises(tmp_path: Path):
    """Test single-file module with syntax error and no .pyi raises InspectionError."""
    py_file = tmp_path / "mod.py"
    py_file.write_text("def f( -> broken\n", encoding="utf-8")
    config = LibcontextConfig()
    with pytest.raises(InspectionError):
        _walk_package(py_file, "mod", config)


def test_walk_package_single_file_pyi_fails_py_used(tmp_path: Path):
    """Test single-file module uses .py when .pyi has syntax error."""
    py_file = tmp_path / "mod.py"
    pyi_file = tmp_path / "mod.pyi"
    py_file.write_text('def f():\n    """Doc."""\n', encoding="utf-8")
    pyi_file.write_text("def f( -> broken\n", encoding="utf-8")
    config = LibcontextConfig()
    modules = _walk_package(py_file, "mod", config)
    assert len(modules) == 1
    assert modules[0].stub_source == ""
    assert modules[0].functions[0].docstring == "Doc."
