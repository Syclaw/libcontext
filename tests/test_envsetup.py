"""Tests for the _envsetup module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from libcontext._envsetup import (
    activate_environment,
    auto_detect_venv,
    env_tag_for_path,
    get_target_sys_path,
    inject_target_environment,
    resolve_python_executable,
    setup_environment,
)
from libcontext.exceptions import EnvironmentSetupError

# ---------------------------------------------------------------------------
# resolve_python_executable
# ---------------------------------------------------------------------------


def test_resolve_direct_interpreter():
    """Passing the current interpreter returns its resolved path."""
    result = resolve_python_executable(sys.executable)
    assert result == Path(sys.executable).resolve()


def test_resolve_venv_directory(tmp_path):
    """Passing a venv-like directory finds the interpreter."""
    if sys.platform == "win32":
        scripts = tmp_path / "Scripts"
        scripts.mkdir()
        exe = scripts / "python.exe"
    else:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        exe = bin_dir / "python"

    exe.write_text("fake", encoding="utf-8")
    result = resolve_python_executable(str(tmp_path))
    assert result == exe.resolve()


def test_resolve_nonexistent_raises():
    """A nonexistent path raises EnvironmentSetupError."""
    with pytest.raises(EnvironmentSetupError, match="does not exist"):
        resolve_python_executable("/no/such/path/python")


def test_resolve_empty_directory_raises(tmp_path):
    """A directory without a Python interpreter raises."""
    with pytest.raises(EnvironmentSetupError, match="no Python interpreter"):
        resolve_python_executable(str(tmp_path))


# ---------------------------------------------------------------------------
# get_target_sys_path
# ---------------------------------------------------------------------------


def test_get_target_sys_path_current_interpreter():
    """Querying the current interpreter returns a non-empty path list."""
    paths = get_target_sys_path(Path(sys.executable))
    assert isinstance(paths, list)
    assert len(paths) > 0
    assert all(isinstance(p, str) for p in paths)


def test_get_target_sys_path_bad_executable(tmp_path):
    """A non-Python executable raises EnvironmentSetupError."""
    fake = tmp_path / "not_python"
    fake.write_text("not a python interpreter", encoding="utf-8")
    if sys.platform != "win32":
        fake.chmod(0o755)

    with pytest.raises(EnvironmentSetupError):
        get_target_sys_path(fake)


# ---------------------------------------------------------------------------
# inject_target_environment
# ---------------------------------------------------------------------------


def test_inject_target_environment_adds_paths():
    """Injecting the current interpreter adds its paths to sys.path."""
    original_len = len(sys.path)
    # Inject the current interpreter (should be mostly a no-op since
    # paths already overlap, but validates the mechanics)
    inject_target_environment(sys.executable)
    assert len(sys.path) >= original_len


# ---------------------------------------------------------------------------
# activate_environment (context manager)
# ---------------------------------------------------------------------------


def test_activate_environment_restores_path():
    """sys.path is restored after the context manager exits."""
    saved = sys.path.copy()
    with activate_environment(sys.executable):
        pass
    assert sys.path == saved


def test_activate_environment_restores_on_exception():
    """sys.path is restored even if an exception occurs."""
    saved = sys.path.copy()
    with pytest.raises(RuntimeError), activate_environment(sys.executable):
        raise RuntimeError("boom")
    assert sys.path == saved


def test_activate_environment_bad_path():
    """EnvironmentSetupError propagates from the context manager."""
    with pytest.raises(EnvironmentSetupError), activate_environment("/no/such/env"):
        pass


# ---------------------------------------------------------------------------
# env_tag_for_path
# ---------------------------------------------------------------------------


def test_env_tag_for_path_returns_hex_string():
    """env_tag returns an 8-char hex string."""
    tag = env_tag_for_path(sys.executable)
    assert len(tag) == 8
    int(tag, 16)  # validates hex


def test_env_tag_deterministic():
    """Same input produces the same tag."""
    tag1 = env_tag_for_path(sys.executable)
    tag2 = env_tag_for_path(sys.executable)
    assert tag1 == tag2


# ---------------------------------------------------------------------------
# Cache filename with env_tag
# ---------------------------------------------------------------------------


def test_cache_filename_with_env_tag():
    """Cache filename includes env_tag when provided."""
    from libcontext.cache import _cache_filename

    without = _cache_filename("requests", "2.31.0")
    with_tag = _cache_filename("requests", "2.31.0", env_tag="abcd1234")
    assert "abcd1234" in with_tag
    assert "abcd1234" not in without
    assert with_tag != without


# ---------------------------------------------------------------------------
# auto_detect_venv
# ---------------------------------------------------------------------------


def _make_fake_venv(parent: Path) -> Path:
    """Create a fake venv directory with a recognisable interpreter."""
    venv = parent / ".venv"
    venv.mkdir()
    if sys.platform == "win32":
        scripts = venv / "Scripts"
        scripts.mkdir()
        (scripts / "python.exe").write_text("fake", encoding="utf-8")
    else:
        bin_dir = venv / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").write_text("fake", encoding="utf-8")
    return venv


def test_auto_detect_venv_finds_dotvenv(tmp_path):
    """Detects .venv/ in the given directory."""
    _make_fake_venv(tmp_path)
    result = auto_detect_venv(tmp_path)
    assert result is not None
    assert result.name == ".venv"


def test_auto_detect_venv_finds_venv(tmp_path):
    """Detects venv/ when .venv/ is absent."""
    venv = tmp_path / "venv"
    venv.mkdir()
    if sys.platform == "win32":
        scripts = venv / "Scripts"
        scripts.mkdir()
        (scripts / "python.exe").write_text("fake", encoding="utf-8")
    else:
        bin_dir = venv / "bin"
        bin_dir.mkdir()
        (bin_dir / "python").write_text("fake", encoding="utf-8")

    result = auto_detect_venv(tmp_path)
    assert result is not None
    assert result.name == "venv"


def test_auto_detect_venv_prefers_dotvenv(tmp_path):
    """.venv/ takes priority over venv/."""
    _make_fake_venv(tmp_path)
    venv = tmp_path / "venv"
    venv.mkdir()
    if sys.platform == "win32":
        (venv / "Scripts").mkdir()
        (venv / "Scripts" / "python.exe").write_text("fake", encoding="utf-8")
    else:
        (venv / "bin").mkdir()
        (venv / "bin" / "python").write_text("fake", encoding="utf-8")

    result = auto_detect_venv(tmp_path)
    assert result is not None
    assert result.name == ".venv"


def test_auto_detect_venv_returns_none_when_absent(tmp_path):
    """Returns None when no venv directory exists."""
    assert auto_detect_venv(tmp_path) is None


def test_auto_detect_venv_ignores_dir_without_interpreter(tmp_path):
    """A .venv/ directory without an interpreter is ignored."""
    (tmp_path / ".venv").mkdir()
    assert auto_detect_venv(tmp_path) is None


# ---------------------------------------------------------------------------
# setup_environment
# ---------------------------------------------------------------------------


def test_setup_environment_explicit_python():
    """Explicit --python takes effect and returns an env_tag."""
    tag = setup_environment(sys.executable)
    assert tag is not None
    assert len(tag) == 8


def test_setup_environment_no_venv_returns_none(tmp_path):
    """No venv, no --python → returns None (no injection)."""
    tag = setup_environment(None, cwd=tmp_path)
    assert tag is None


def test_setup_environment_auto_detects(tmp_path, monkeypatch):
    """Auto-detects .venv/ and returns an env_tag when using real interpreter."""
    # Point the fake venv at the real interpreter so subprocess works
    venv = tmp_path / ".venv"
    venv.mkdir()
    real_exe = Path(sys.executable)
    if sys.platform == "win32":
        scripts = venv / "Scripts"
        scripts.mkdir()
        target = scripts / "python.exe"
    else:
        bin_dir = venv / "bin"
        bin_dir.mkdir()
        target = bin_dir / "python"

    # Create a symlink (or copy) so the interpreter actually works
    try:
        target.symlink_to(real_exe)
    except OSError:
        # Symlinks may require privileges on Windows; skip test
        pytest.skip("Cannot create symlink to Python interpreter")

    tag = setup_environment(None, cwd=tmp_path)
    assert tag is not None
    assert len(tag) == 8
