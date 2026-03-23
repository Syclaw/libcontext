"""Environment setup — resolve and activate a target Python environment.

When libcontext is installed globally (e.g. via ``uv tool install``), it
runs inside its own isolated venv and cannot see packages from a project's
``.venv``.  This module auto-detects a project venv in the current working
directory, or accepts an explicit ``--python`` override, and injects the
target environment's paths into ``sys.path`` so that :mod:`importlib`
discovery works against the target environment.

Detection priority:
1. Explicit ``--python`` argument → use that environment.
2. ``.venv/`` or ``venv/`` in CWD → use the detected venv.
3. Neither → use the current process's environment (no injection).
"""

from __future__ import annotations

import importlib
import json
import logging
import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from .exceptions import EnvironmentSetupError

logger = logging.getLogger(__name__)

_SUBPROCESS_TIMEOUT_SECONDS = 10


_VENV_DIR_NAMES = (".venv", "venv")


def auto_detect_venv(cwd: Path | None = None) -> Path | None:
    """Detect a project venv in the current working directory.

    Checks for ``.venv/`` then ``venv/`` in *cwd* (defaults to
    ``Path.cwd()``).  Only considers directories that contain a
    recognisable Python interpreter.

    Args:
        cwd: Directory to search in.  Defaults to the process CWD.

    Returns:
        Path to the venv directory, or *None* if no venv is found.
    """
    if cwd is None:
        cwd = Path.cwd()

    for name in _VENV_DIR_NAMES:
        candidate = cwd / name
        if not candidate.is_dir():
            continue
        # Verify it actually contains an interpreter
        interpreters = [
            candidate / "Scripts" / "python.exe",
            candidate / "bin" / "python",
            candidate / "bin" / "python3",
        ]
        if any(exe.is_file() for exe in interpreters):
            logger.debug("Auto-detected venv at '%s'", candidate)
            return candidate

    return None


def setup_environment(
    python_arg: str | None = None,
    *,
    cwd: Path | None = None,
) -> str | None:
    """Set up the target environment for package discovery.

    Implements the detection priority:
    1. Explicit *python_arg* → inject that environment.
    2. Auto-detected venv in *cwd* → inject it.
    3. Neither → no injection (current process environment).

    Args:
        python_arg: Explicit ``--python`` value, or *None*.
        cwd: Working directory for auto-detection (defaults to CWD).

    Returns:
        The env_tag for cache namespacing, or *None* if no injection
        was performed.

    Raises:
        EnvironmentSetupError: If an explicit *python_arg* is invalid.
    """
    target: str | None = python_arg

    if target is None:
        detected = auto_detect_venv(cwd)
        if detected is not None:
            target = str(detected)

    if target is None:
        return None

    # Resolve once, reuse for both injection and tag computation
    python_exe = resolve_python_executable(target)
    target_paths = get_target_sys_path(python_exe)

    current_set = set(sys.path)
    new_paths = [p for p in target_paths if p and p not in current_set]

    sys.path[:0] = new_paths
    importlib.invalidate_caches()

    logger.debug(
        "Activated environment '%s': injected %d paths",
        target,
        len(new_paths),
    )

    return _env_tag_from_resolved(python_exe)


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
        candidates = [
            path / "Scripts" / "python.exe",  # Windows venv
            path / "bin" / "python",  # Unix venv
            path / "bin" / "python3",  # Unix alternative
        ]
        for candidate in candidates:
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
    """Query a Python interpreter for its ``sys.path``.

    Runs the interpreter in a subprocess with a short timeout to
    extract the full search path, including ``.pth`` expansions and
    site-packages.

    Args:
        python_exe: Absolute path to the target Python executable.

    Returns:
        List of path strings from the target interpreter's ``sys.path``.

    Raises:
        EnvironmentSetupError: If the subprocess fails or times out.
    """
    script = "import sys, json; print(json.dumps(sys.path))"
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
    """
    resolved = resolve_python_executable(python_arg)
    return _env_tag_from_resolved(resolved)
