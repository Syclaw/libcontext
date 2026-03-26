"""Environment setup — resolve and activate a target Python environment.

When libcontext is installed globally (e.g. via ``uv tool install``), it
runs inside its own isolated venv and cannot see packages from a project's
``.venv``.  This module auto-detects a project venv in the current working
directory, or accepts an explicit ``--python`` override, and injects the
target environment's paths into ``sys.path`` so that :mod:`importlib`
discovery works against the target environment.

Detection priority:
1. Explicit ``--python`` argument → use that environment.
2. ``VIRTUAL_ENV`` env var → activated venv (any tool).
3. ``CONDA_PREFIX`` env var → activated conda environment.
4. ``UV_PROJECT_ENVIRONMENT`` env var → uv-specific override.
5. ``.venv/`` or ``venv/`` in CWD → use the detected venv.
6. ``uv`` fallback: if CWD has ``pyproject.toml``, query ``uv`` for the
   project interpreter.
7. Neither → use the current process's environment (no injection).
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from .exceptions import EnvironmentSetupError

logger = logging.getLogger(__name__)

_SUBPROCESS_TIMEOUT_SECONDS = 10


_VENV_DIR_NAMES = (".venv", "venv")

# Relative interpreter paths inside a venv, checked in order.
_INTERPRETER_CANDIDATES = (
    Path("Scripts") / "python.exe",  # Windows
    Path("bin") / "python",  # Unix
    Path("bin") / "python3",  # Unix alternative
)

# Script executed in the *target* interpreter to collect site-packages
# directories.  Kept as a module constant so it can be tested directly.
# Uses only stdlib modules guaranteed present in Python 3.9+.
_SITE_PACKAGES_SCRIPT = """\
import json, site, sys, os

paths = []

# site-packages directories (includes system site-packages when the
# venv was created with --system-site-packages)
try:
    paths.extend(site.getsitepackages())
except AttributeError:
    pass

# User site-packages (e.g. ~/.local/lib/python3.x/site-packages),
# honoured only when ENABLE_USER_SITE is not explicitly disabled.
if site.ENABLE_USER_SITE:
    try:
        user = site.getusersitepackages()
        if isinstance(user, str):
            paths.append(user)
    except AttributeError:
        pass

# .pth files in site-packages can inject arbitrary paths into sys.path
# (editable installs, namespace packages, etc.).  Collect them by
# diffing sys.path against site-packages — any path that is not a
# site-packages dir and not under sys.base_prefix is .pth-injected.
site_set = set(os.path.realpath(p) for p in paths)
base = os.path.realpath(sys.base_prefix)
for p in sys.path:
    if not p:
        continue
    rp = os.path.realpath(p)
    if rp in site_set:
        continue
    if rp == base or rp.startswith(base + os.sep):
        continue
    paths.append(p)

print(json.dumps(paths))
"""

# Script executed in the *target* interpreter to discover a package.
# Accepts the package name as sys.argv[1].  Returns a JSON object with
# path, version, summary, and installed package names for suggestions.
_PACKAGE_DISCOVERY_SCRIPT = """\
import importlib.metadata, importlib.util, json, sys
from pathlib import Path

name = sys.argv[1]
result = {"path": None, "version": None, "summary": None, "installed": []}

# Locate the package source via find_spec
try:
    spec = importlib.util.find_spec(name)
except (ModuleNotFoundError, ValueError, AttributeError):
    spec = None

if spec is not None:
    if spec.origin and spec.origin != "frozen":
        origin = Path(spec.origin)
        result["path"] = str(origin.parent if origin.name == "__init__.py" else origin)
    elif spec.submodule_search_locations:
        locs = list(spec.submodule_search_locations)
        if locs:
            result["path"] = locs[0]

# Retrieve metadata (version + summary)
try:
    meta = importlib.metadata.metadata(name)
    result["version"] = meta.get("Version")
    result["summary"] = meta.get("Summary")
except importlib.metadata.PackageNotFoundError:
    pass

# Collect installed package names for typo suggestions
installed = set()
for dist in importlib.metadata.distributions():
    dn = dist.metadata.get("Name")
    if dn:
        installed.add(dn)
        norm = dn.replace("-", "_").lower()
        if norm != dn:
            installed.add(norm)
result["installed"] = sorted(installed)

print(json.dumps(result))
"""


def _has_python_interpreter(venv_dir: Path) -> bool:
    """Check whether a directory contains a recognisable Python interpreter."""
    return any((venv_dir / rel).is_file() for rel in _INTERPRETER_CANDIDATES)


def auto_detect_venv(cwd: Path | None = None) -> Path | None:
    """Detect a project venv in the current working directory.

    Detection order:

    1. ``VIRTUAL_ENV`` env var — set by any activated venv (virtualenv,
       ``python -m venv``, ``poetry shell``, etc.).
    2. ``CONDA_PREFIX`` env var — set by an activated conda environment.
    3. ``UV_PROJECT_ENVIRONMENT`` env var — used when ``uv`` is configured
       to place the venv outside the default ``.venv/`` location.
    4. ``.venv/`` then ``venv/`` in *cwd*.
    5. ``uv`` fallback — if *cwd* contains a ``pyproject.toml``, query
       ``uv python find`` to locate the project interpreter and derive
       the venv from its path.

    Only considers directories that contain a recognisable Python
    interpreter.

    Args:
        cwd: Directory to search in.  Defaults to the process CWD.

    Returns:
        Path to the venv directory, or *None* if no venv is found.
    """
    if cwd is None:
        cwd = Path.cwd()

    # 1. VIRTUAL_ENV — set by any venv activation script
    # 2. CONDA_PREFIX — set by conda activate
    # 3. UV_PROJECT_ENVIRONMENT — uv-specific override
    for var in ("VIRTUAL_ENV", "CONDA_PREFIX", "UV_PROJECT_ENVIRONMENT"):
        value = os.environ.get(var)
        if not value:
            continue
        candidate = Path(value)
        if candidate.is_dir() and _has_python_interpreter(candidate):
            logger.debug("Auto-detected venv from %s: '%s'", var, candidate)
            return candidate
        logger.debug("%s='%s' set but not a valid venv", var, value)

    # 4. Standard .venv/ and venv/ in CWD
    for name in _VENV_DIR_NAMES:
        candidate = cwd / name
        if candidate.is_dir() and _has_python_interpreter(candidate):
            logger.debug("Auto-detected venv at '%s'", candidate)
            return candidate

    # 5. uv fallback — ask uv for the project interpreter
    if (cwd / "pyproject.toml").is_file():
        venv = _detect_venv_via_uv(cwd)
        if venv is not None:
            return venv

    return None


def _detect_venv_via_uv(cwd: Path) -> Path | None:
    """Ask ``uv`` for the project interpreter and derive the venv path.

    Only called when a ``pyproject.toml`` exists in *cwd* but no
    standard venv directory was found.
    """
    try:
        result = subprocess.run(
            ["uv", "python", "find", "--project", str(cwd)],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            cwd=str(cwd),
        )
    except FileNotFoundError:
        logger.debug("uv not found on PATH; skipping uv-based detection")
        return None
    except subprocess.TimeoutExpired:
        logger.debug("uv python find timed out; skipping uv-based detection")
        return None

    if result.returncode != 0:
        logger.debug(
            "uv python find exited with code %d; skipping",
            result.returncode,
        )
        return None

    python_path = Path(result.stdout.strip())
    if not python_path.is_file():
        logger.debug("uv reported interpreter '%s' but file not found", python_path)
        return None

    # Derive venv from interpreter path:
    # .../venv/bin/python  → .../venv
    # .../venv/Scripts/python.exe → .../venv
    venv_dir = python_path.parent.parent
    if (venv_dir / "pyvenv.cfg").is_file():
        logger.debug("Auto-detected venv via uv at '%s'", venv_dir)
        return venv_dir

    logger.debug(
        "uv interpreter '%s' is not inside a venv (no pyvenv.cfg)",
        python_path,
    )
    return None


def setup_environment(
    python_arg: str | None = None,
    *,
    cwd: Path | None = None,
) -> tuple[str | None, Path | None]:
    """Resolve the target environment for package discovery.

    Implements the detection priority:
    1. Explicit *python_arg* → use that environment.
    2. Auto-detected venv in *cwd* → use it.
    3. Neither → use the current process environment.

    Returns the resolved interpreter path so that callers can delegate
    package discovery to the target interpreter via subprocess, avoiding
    cross-version ``importlib`` contamination when the tool and target
    run different Python versions.

    Args:
        python_arg: Explicit ``--python`` value, or *None*.
        cwd: Working directory for auto-detection (defaults to CWD).

    Returns:
        A ``(env_tag, target_python)`` tuple.  Both are *None* when no
        external environment was detected (i.e. the current process
        environment is used).

    Raises:
        EnvironmentSetupError: If an explicit *python_arg* is invalid.
    """
    target: str | None = python_arg

    if target is None:
        detected = auto_detect_venv(cwd)
        if detected is not None:
            target = str(detected)

    if target is None:
        return None, None

    python_exe = resolve_python_executable(target)

    logger.debug(
        "Resolved target environment '%s' → '%s'",
        target,
        python_exe,
    )

    return _env_tag_from_resolved(python_exe), python_exe


def query_target_package(
    python_exe: Path,
    package_name: str,
) -> dict[str, object]:
    """Discover a package by running the target interpreter.

    Delegates ``importlib.util.find_spec`` and
    ``importlib.metadata.metadata`` to *python_exe* via subprocess,
    keeping the tool process free from cross-version import
    contamination.

    Args:
        python_exe: Absolute path to the target Python executable.
        package_name: Package import name (e.g. ``openai``).

    Returns:
        Dict with keys ``path`` (str | None), ``version`` (str | None),
        ``summary`` (str | None), ``installed`` (list[str]).

    Raises:
        EnvironmentSetupError: If the subprocess fails or times out.
    """
    try:
        result = subprocess.run(
            [str(python_exe), "-c", _PACKAGE_DISCOVERY_SCRIPT, package_name],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError) as exc:
        raise EnvironmentSetupError(
            str(python_exe),
            f"cannot execute interpreter: {exc}",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise EnvironmentSetupError(
            str(python_exe),
            f"interpreter timed out after {_SUBPROCESS_TIMEOUT_SECONDS}s",
        ) from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()[:200]
        raise EnvironmentSetupError(
            str(python_exe),
            f"package discovery failed (exit {result.returncode}): {stderr}",
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise EnvironmentSetupError(
            str(python_exe),
            f"cannot parse discovery output: {exc}",
        ) from exc

    return data  # type: ignore[no-any-return]


def resolve_python_executable(python_arg: str) -> Path:
    """Resolve a user-supplied path to a Python executable.

    Accepts either a direct path to a Python interpreter or a venv
    directory.  When given a directory, probes for the interpreter
    in the standard locations (``Scripts/python.exe`` on Windows,
    ``bin/python`` on Unix).

    Args:
        python_arg: Path to a Python interpreter or venv directory.

    Returns:
        Resolved absolute path to the Python executable.

    Raises:
        EnvironmentSetupError: If the path does not exist or no
            interpreter can be found.
    """
    path = Path(python_arg)

    if not path.exists():
        raise EnvironmentSetupError(
            python_arg,
            f"path does not exist: {python_arg}",
        )

    # Direct path to an executable
    if path.is_file():
        return path.resolve()

    # Directory — probe for interpreter
    if path.is_dir():
        for candidate in (path / rel for rel in _INTERPRETER_CANDIDATES):
            if candidate.is_file():
                logger.debug(
                    "Resolved venv directory '%s' to interpreter '%s'",
                    python_arg,
                    candidate,
                )
                return candidate.resolve()

        raise EnvironmentSetupError(
            python_arg,
            f"no Python interpreter found in directory: {python_arg}. "
            f"Expected Scripts/python.exe (Windows) or bin/python (Unix).",
        )

    raise EnvironmentSetupError(
        python_arg,
        f"path is neither a file nor a directory: {python_arg}",
    )


def get_target_sys_path(python_exe: Path) -> list[str]:
    """Query a target interpreter for its package-discovery paths.

    Collects site-packages directories (including system site-packages
    for ``--system-site-packages`` venvs), user site-packages, and
    any paths injected by ``.pth`` files (editable installs, namespace
    packages).  Stdlib paths are **excluded** to prevent cross-version
    import contamination when tool and target run different Python
    versions.

    Args:
        python_exe: Absolute path to the target Python executable.

    Returns:
        List of path strings suitable for prepending to ``sys.path``
        in the tool process.

    Raises:
        EnvironmentSetupError: If the subprocess fails or times out.
    """
    script = _SITE_PACKAGES_SCRIPT
    try:
        result = subprocess.run(
            [str(python_exe), "-c", script],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError) as exc:
        raise EnvironmentSetupError(
            str(python_exe),
            f"cannot execute interpreter: {exc}",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise EnvironmentSetupError(
            str(python_exe),
            f"interpreter timed out after {_SUBPROCESS_TIMEOUT_SECONDS}s",
        ) from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()[:200]
        raise EnvironmentSetupError(
            str(python_exe),
            f"interpreter exited with code {result.returncode}: {stderr}",
        )

    try:
        paths = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise EnvironmentSetupError(
            str(python_exe),
            f"cannot parse sys.path output: {exc}",
        ) from exc

    if not isinstance(paths, list):
        raise EnvironmentSetupError(
            str(python_exe),
            "sys.path output is not a list",
        )

    return [str(p) for p in paths]


@contextmanager
def activate_environment(python_arg: str) -> Generator[Path, None, None]:
    """Temporarily inject a target environment's paths into the process.

    Resolves the Python executable, queries its ``sys.path``, prepends
    the target paths to the current ``sys.path``, and invalidates
    :mod:`importlib` caches so that :func:`importlib.util.find_spec`
    and :func:`importlib.metadata.distributions` pick up the target
    environment's packages.

    The original ``sys.path`` is restored on exit.

    Args:
        python_arg: Path to a Python interpreter or venv directory.

    Yields:
        The resolved Python executable path.

    Raises:
        EnvironmentSetupError: If the environment cannot be resolved
            or queried.
    """
    python_exe = resolve_python_executable(python_arg)
    target_paths = get_target_sys_path(python_exe)

    # Filter to paths that actually exist and aren't already present
    current_set = set(sys.path)
    new_paths = [p for p in target_paths if p and p not in current_set]

    saved_path = sys.path.copy()
    try:
        # Prepend target paths so they take priority
        sys.path[:0] = new_paths
        importlib.invalidate_caches()

        logger.debug(
            "Activated environment '%s': injected %d paths",
            python_arg,
            len(new_paths),
        )
        yield python_exe
    finally:
        sys.path[:] = saved_path
        importlib.invalidate_caches()
        logger.debug("Restored original sys.path")


def inject_target_environment(python_arg: str) -> None:
    """Inject a target environment's paths into the current process.

    Unlike :func:`activate_environment`, this does **not** restore
    ``sys.path`` afterward.  Suitable for CLI entry points where the
    process exits after the command completes.

    Args:
        python_arg: Path to a Python interpreter or venv directory.

    Raises:
        EnvironmentSetupError: If the environment cannot be resolved
            or queried.
    """
    python_exe = resolve_python_executable(python_arg)
    target_paths = get_target_sys_path(python_exe)

    current_set = set(sys.path)
    new_paths = [p for p in target_paths if p and p not in current_set]

    sys.path[:0] = new_paths
    importlib.invalidate_caches()

    logger.debug(
        "Injected environment '%s': added %d paths",
        python_arg,
        len(new_paths),
    )


def _env_tag_from_resolved(python_exe: Path) -> str:
    """Compute a short tag from an already-resolved interpreter path."""
    import hashlib

    digest = hashlib.sha256(str(python_exe).encode()).hexdigest()
    return digest[:8]


def env_tag_for_path(python_arg: str) -> str:
    """Compute a short tag identifying a target environment for cache keys.

    Args:
        python_arg: The original ``--python`` argument (before resolution).

    Returns:
        An 8-character hex string derived from the resolved path.

    Raises:
        EnvironmentSetupError: If *python_arg* cannot be resolved.
    """
    resolved = resolve_python_executable(python_arg)
    return _env_tag_from_resolved(resolved)
