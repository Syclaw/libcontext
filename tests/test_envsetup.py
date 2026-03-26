"""Tests for the _envsetup module."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from libcontext._envsetup import (
    auto_detect_venv,
    env_tag_for_path,
    query_target_package,
    resolve_python_executable,
    setup_environment,
)
from libcontext.exceptions import EnvironmentSetupError

# ---------------------------------------------------------------------------
# resolve_python_executable
# ---------------------------------------------------------------------------


def test_resolve_direct_interpreter():
    """Passing the current interpreter returns an absolute path."""
    result = resolve_python_executable(sys.executable)
    assert result == Path(sys.executable).absolute()


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
    assert result == exe.absolute()


def test_resolve_preserves_symlink(tmp_path):
    """Symlinked interpreter must not be resolved to the target."""
    if sys.platform == "win32":
        scripts = tmp_path / "Scripts"
        scripts.mkdir()
        link = scripts / "python.exe"
    else:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        link = bin_dir / "python"

    real_exe = Path(sys.executable)
    try:
        link.symlink_to(real_exe)
    except OSError:
        pytest.skip("Cannot create symlink")

    result = resolve_python_executable(str(link))
    # Must return the symlink path, not the resolved target
    assert result == link.absolute()
    assert result != real_exe.resolve()


def test_resolve_nonexistent_raises():
    """A nonexistent path raises EnvironmentSetupError."""
    with pytest.raises(EnvironmentSetupError, match="does not exist"):
        resolve_python_executable("/no/such/path/python")


def test_resolve_empty_directory_raises(tmp_path):
    """A directory without a Python interpreter raises."""
    with pytest.raises(EnvironmentSetupError, match="no Python interpreter"):
        resolve_python_executable(str(tmp_path))


# ---------------------------------------------------------------------------
# query_target_package
# ---------------------------------------------------------------------------


def test_query_target_package_finds_installed():
    """Discovers a package known to be installed in the current interpreter."""
    data = query_target_package(Path(sys.executable), "pytest")
    assert data["path"] is not None
    assert data["version"] is not None
    assert isinstance(data["installed"], list)
    assert len(data["installed"]) > 0


def test_query_target_package_missing_returns_null_path():
    """Returns null path for a package that does not exist."""
    data = query_target_package(Path(sys.executable), "nonexistent_pkg_xyz")
    assert data["path"] is None


def test_query_target_package_returns_installed_names():
    """The installed list contains distribution names for suggestions."""
    data = query_target_package(Path(sys.executable), "pytest")
    assert "pytest" in data["installed"]


def test_query_target_package_bad_executable(tmp_path):
    """A non-Python executable raises EnvironmentSetupError."""
    fake = tmp_path / "not_python"
    fake.write_text("not a python interpreter", encoding="utf-8")
    if sys.platform != "win32":
        fake.chmod(0o755)

    with pytest.raises(EnvironmentSetupError):
        query_target_package(fake, "anything")


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

_VENV_ENV_VARS = ("VIRTUAL_ENV", "CONDA_PREFIX", "UV_PROJECT_ENVIRONMENT")


@pytest.fixture()
def _clean_venv_env(monkeypatch):
    """Remove venv-related env vars so auto_detect_venv tests are isolated."""
    for var in _VENV_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _make_fake_venv_at(path: Path) -> Path:
    """Create a fake venv at an arbitrary path."""
    path.mkdir(exist_ok=True)
    if sys.platform == "win32":
        scripts = path / "Scripts"
        scripts.mkdir(exist_ok=True)
        (scripts / "python.exe").write_text("fake", encoding="utf-8")
    else:
        bin_dir = path / "bin"
        bin_dir.mkdir(exist_ok=True)
        (bin_dir / "python").write_text("fake", encoding="utf-8")
    return path


def _make_fake_venv(parent: Path) -> Path:
    """Create a fake .venv/ directory with a recognisable interpreter."""
    return _make_fake_venv_at(parent / ".venv")


@pytest.mark.usefixtures("_clean_venv_env")
def test_auto_detect_venv_finds_dotvenv(tmp_path):
    """Detects .venv/ in the given directory."""
    _make_fake_venv(tmp_path)
    result = auto_detect_venv(tmp_path)
    assert result is not None
    assert result.name == ".venv"


@pytest.mark.usefixtures("_clean_venv_env")
def test_auto_detect_venv_finds_venv(tmp_path):
    """Detects venv/ when .venv/ is absent."""
    _make_fake_venv_at(tmp_path / "venv")
    result = auto_detect_venv(tmp_path)
    assert result is not None
    assert result.name == "venv"


@pytest.mark.usefixtures("_clean_venv_env")
def test_auto_detect_venv_prefers_dotvenv(tmp_path):
    """.venv/ takes priority over venv/."""
    _make_fake_venv(tmp_path)
    _make_fake_venv_at(tmp_path / "venv")
    result = auto_detect_venv(tmp_path)
    assert result is not None
    assert result.name == ".venv"


@pytest.mark.usefixtures("_clean_venv_env")
def test_auto_detect_venv_returns_none_when_absent(tmp_path):
    """Returns None when no venv directory exists."""
    assert auto_detect_venv(tmp_path) is None


@pytest.mark.usefixtures("_clean_venv_env")
@pytest.mark.parametrize("var", _VENV_ENV_VARS)
def test_auto_detect_venv_env_var(tmp_path, monkeypatch, var):
    """Detects venv from VIRTUAL_ENV, CONDA_PREFIX, or UV_PROJECT_ENVIRONMENT."""
    custom_venv = _make_fake_venv_at(tmp_path / "custom-env")
    monkeypatch.setenv(var, str(custom_venv))
    result = auto_detect_venv(tmp_path)
    assert result is not None
    assert result == custom_venv


@pytest.mark.usefixtures("_clean_venv_env")
def test_auto_detect_venv_virtual_env_takes_priority(tmp_path, monkeypatch):
    """VIRTUAL_ENV wins over CONDA_PREFIX and UV_PROJECT_ENVIRONMENT."""
    venv_a = _make_fake_venv_at(tmp_path / "venv-a")
    venv_b = _make_fake_venv_at(tmp_path / "venv-b")
    monkeypatch.setenv("VIRTUAL_ENV", str(venv_a))
    monkeypatch.setenv("CONDA_PREFIX", str(venv_b))
    result = auto_detect_venv(tmp_path)
    assert result == venv_a


@pytest.mark.usefixtures("_clean_venv_env")
def test_auto_detect_venv_env_var_invalid_falls_through(tmp_path, monkeypatch):
    """Falls through when env var points to an invalid dir."""
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "nonexistent"))
    _make_fake_venv(tmp_path)
    result = auto_detect_venv(tmp_path)
    # Should fall through to .venv detection
    assert result is not None
    assert result.name == ".venv"


@pytest.mark.usefixtures("_clean_venv_env")
def test_auto_detect_venv_ignores_dir_without_interpreter(tmp_path):
    """A .venv/ directory without an interpreter is ignored."""
    (tmp_path / ".venv").mkdir()
    assert auto_detect_venv(tmp_path) is None


# ---------------------------------------------------------------------------
# setup_environment
# ---------------------------------------------------------------------------


def test_setup_environment_explicit_python():
    """Explicit --python returns (env_tag, target_python)."""
    tag, target = setup_environment(sys.executable)
    assert tag is not None
    assert len(tag) == 8
    assert target is not None
    assert target.is_file()


@pytest.mark.usefixtures("_clean_venv_env")
def test_setup_environment_no_venv_returns_none(tmp_path):
    """No venv, no --python → returns (None, None)."""
    tag, target = setup_environment(None, cwd=tmp_path)
    assert tag is None
    assert target is None


@pytest.mark.usefixtures("_clean_venv_env")
def test_setup_environment_auto_detects(tmp_path, monkeypatch):
    """Auto-detects .venv/ and returns (env_tag, target_python)."""
    # Point the fake venv at the real interpreter so subprocess works
    venv = tmp_path / ".venv"
    venv.mkdir()
    real_exe = Path(sys.executable)
    if sys.platform == "win32":
        scripts = venv / "Scripts"
        scripts.mkdir()
        link = scripts / "python.exe"
    else:
        bin_dir = venv / "bin"
        bin_dir.mkdir()
        link = bin_dir / "python"

    # Create a symlink (or copy) so the interpreter actually works
    try:
        link.symlink_to(real_exe)
    except OSError:
        # Symlinks may require privileges on Windows; skip test
        pytest.skip("Cannot create symlink to Python interpreter")

    tag, target = setup_environment(None, cwd=tmp_path)
    assert tag is not None
    assert len(tag) == 8
    assert target is not None
    assert target.is_file()


# ---------------------------------------------------------------------------
# _detect_venv_via_uv (tested through auto_detect_venv)
# ---------------------------------------------------------------------------


def _setup_pyproject_only(tmp_path: Path) -> None:
    """Create a pyproject.toml but no .venv/ or venv/ directories."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n', encoding="utf-8"
    )


@pytest.mark.usefixtures("_clean_venv_env")
def test_uv_fallback_skipped_when_uv_not_found(tmp_path):
    """auto_detect_venv returns None when uv is not installed."""
    _setup_pyproject_only(tmp_path)

    with patch("libcontext._envsetup.subprocess.run", side_effect=FileNotFoundError):
        result = auto_detect_venv(tmp_path)

    assert result is None


@pytest.mark.usefixtures("_clean_venv_env")
def test_uv_fallback_skipped_on_timeout(tmp_path):
    """auto_detect_venv returns None when uv times out."""
    _setup_pyproject_only(tmp_path)

    with patch(
        "libcontext._envsetup.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="uv", timeout=10),
    ):
        result = auto_detect_venv(tmp_path)

    assert result is None


@pytest.mark.usefixtures("_clean_venv_env")
def test_uv_fallback_skipped_on_nonzero_exit(tmp_path):
    """auto_detect_venv returns None when uv exits with an error."""
    _setup_pyproject_only(tmp_path)

    mock_result = MagicMock(returncode=1, stdout="", stderr="error")
    with patch("libcontext._envsetup.subprocess.run", return_value=mock_result):
        result = auto_detect_venv(tmp_path)

    assert result is None


@pytest.mark.usefixtures("_clean_venv_env")
def test_uv_fallback_skipped_when_interpreter_not_found(tmp_path):
    """auto_detect_venv returns None when uv reports a nonexistent interpreter."""
    _setup_pyproject_only(tmp_path)

    ghost_path = str(tmp_path / "nonexistent" / "bin" / "python")
    mock_result = MagicMock(returncode=0, stdout=ghost_path + "\n")
    with patch("libcontext._envsetup.subprocess.run", return_value=mock_result):
        result = auto_detect_venv(tmp_path)

    assert result is None


@pytest.mark.usefixtures("_clean_venv_env")
def test_uv_fallback_skipped_when_no_pyvenv_cfg(tmp_path):
    """auto_detect_venv returns None when the interpreter is not inside a venv."""
    _setup_pyproject_only(tmp_path)

    # Create a real interpreter file but no pyvenv.cfg in its grandparent
    fake_env = tmp_path / "some-env"
    if sys.platform == "win32":
        scripts = fake_env / "Scripts"
        scripts.mkdir(parents=True)
        interp = scripts / "python.exe"
    else:
        bin_dir = fake_env / "bin"
        bin_dir.mkdir(parents=True)
        interp = bin_dir / "python"
    interp.write_text("fake", encoding="utf-8")

    mock_result = MagicMock(returncode=0, stdout=str(interp) + "\n")
    with patch("libcontext._envsetup.subprocess.run", return_value=mock_result):
        result = auto_detect_venv(tmp_path)

    assert result is None


@pytest.mark.usefixtures("_clean_venv_env")
def test_uv_fallback_returns_venv_when_valid(tmp_path):
    """auto_detect_venv returns the venv path when uv reports a valid interpreter."""
    _setup_pyproject_only(tmp_path)

    fake_env = tmp_path / "uv-managed-env"
    if sys.platform == "win32":
        scripts = fake_env / "Scripts"
        scripts.mkdir(parents=True)
        interp = scripts / "python.exe"
    else:
        bin_dir = fake_env / "bin"
        bin_dir.mkdir(parents=True)
        interp = bin_dir / "python"
    interp.write_text("fake", encoding="utf-8")
    (fake_env / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")

    mock_result = MagicMock(returncode=0, stdout=str(interp) + "\n")
    with patch("libcontext._envsetup.subprocess.run", return_value=mock_result):
        result = auto_detect_venv(tmp_path)

    assert result == fake_env


# ---------------------------------------------------------------------------
# query_target_package — error paths
# ---------------------------------------------------------------------------


def test_query_target_package_raises_on_timeout():
    """Timeout during package discovery raises EnvironmentSetupError."""
    fake_exe = Path("/usr/bin/python3")

    with (
        patch(
            "libcontext._envsetup.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="python", timeout=10),
        ),
        pytest.raises(EnvironmentSetupError, match="timed out"),
    ):
        query_target_package(fake_exe, "some-pkg")


def test_query_target_package_raises_on_nonzero_returncode():
    """Non-zero exit from the subprocess raises EnvironmentSetupError."""
    fake_exe = Path("/usr/bin/python3")

    mock_result = MagicMock(returncode=1, stderr="ImportError: no module", stdout="")
    with (
        patch("libcontext._envsetup.subprocess.run", return_value=mock_result),
        pytest.raises(EnvironmentSetupError, match="exit 1"),
    ):
        query_target_package(fake_exe, "some-pkg")


def test_query_target_package_raises_on_invalid_json():
    """Malformed JSON output raises EnvironmentSetupError."""
    fake_exe = Path("/usr/bin/python3")

    mock_result = MagicMock(returncode=0, stdout="not valid json{{{")
    with (
        patch("libcontext._envsetup.subprocess.run", return_value=mock_result),
        pytest.raises(EnvironmentSetupError, match="cannot parse"),
    ):
        query_target_package(fake_exe, "some-pkg")


def test_query_target_package_custom_timeout_is_forwarded():
    """The timeout kwarg is forwarded to subprocess.run."""
    fake_exe = Path("/usr/bin/python3")
    custom_timeout = 5

    discovery_json = '{"path": null, "version": null, "installed": []}'
    mock_result = MagicMock(returncode=0, stdout=discovery_json)
    with patch(
        "libcontext._envsetup.subprocess.run", return_value=mock_result
    ) as mock_run:
        query_target_package(fake_exe, "some-pkg", timeout=custom_timeout)

    _, kwargs = mock_run.call_args
    assert kwargs["timeout"] == custom_timeout
