"""Package collector — discovers and inspects all modules in a Python package.

Walks the source tree of an installed (or local) package, applies filtering
rules from the optional ``[tool.libcontext]`` configuration, and returns a
complete :class:`~libcontext.models.PackageInfo` data structure.
"""

from __future__ import annotations

import copy
import importlib.metadata
import importlib.util
import logging
from pathlib import Path

from .config import LibcontextConfig, find_config_for_package
from .inspector import inspect_file
from .models import ModuleInfo, PackageInfo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Package discovery
# ---------------------------------------------------------------------------


def find_package_path(package_name: str) -> Path | None:
    """Locate the source directory of an installed package.

    Uses :func:`importlib.util.find_spec` to resolve the package location.

    Args:
        package_name: The importable dotted name (e.g. ``requests``).

    Returns:
        Path to the package directory (or single-file module), or *None*.
    """
    try:
        spec = importlib.util.find_spec(package_name)
    except (ModuleNotFoundError, ValueError, AttributeError):
        return None

    if spec is None:
        return None

    if spec.origin and spec.origin != "frozen":
        origin = Path(spec.origin)
        if origin.name == "__init__.py":
            return origin.parent
        return origin

    if spec.submodule_search_locations:
        locations = list(spec.submodule_search_locations)
        if locations:
            return Path(locations[0])

    return None


def _get_package_metadata(package_name: str) -> dict[str, str | None]:
    """Retrieve version and summary from installed package metadata."""
    try:
        meta = importlib.metadata.metadata(package_name)
        return {
            "version": meta.get("Version"),
            "summary": meta.get("Summary"),
        }
    except importlib.metadata.PackageNotFoundError:
        logger.debug("No installed metadata for '%s'", package_name)
        return {}


# ---------------------------------------------------------------------------
# README discovery
# ---------------------------------------------------------------------------


def _find_readme(package_name: str, package_path: Path | None) -> str | None:
    """Try to locate and read a README for the package.

    Strategy:
    1. ``importlib.metadata`` long description (often contains the README).
    2. Search common README filenames near the package source directory.
    """
    # 1. Metadata long description
    try:
        meta = importlib.metadata.metadata(package_name)
        body = meta.get_payload()  # type: ignore[union-attr]
        if isinstance(body, str) and body.strip():
            logger.debug("README found via metadata for '%s'", package_name)
            return body.strip()
    except (importlib.metadata.PackageNotFoundError, AttributeError):
        pass

    # 2. Search near the source
    if package_path is None:
        return None

    readme_names = ("README.md", "README.rst", "README.txt", "README")
    for search_dir in (package_path, package_path.parent, package_path.parent.parent):
        for name in readme_names:
            readme = search_dir / name
            if readme.is_file():
                try:
                    content = readme.read_text(encoding="utf-8")
                    logger.debug("README found at %s", readme)
                    return content
                except (OSError, UnicodeDecodeError) as exc:
                    logger.debug("Cannot read README %s: %s", readme, exc)
                    continue

    return None


# ---------------------------------------------------------------------------
# Module walking
# ---------------------------------------------------------------------------


def _should_skip_path(parts: tuple[str, ...], include_private: bool) -> bool:
    """Decide whether a file path should be skipped.

    Skips ``__pycache__``, ``.git``, and (optionally) private modules.
    """
    for part in parts:
        if part == "__pycache__" or part.startswith("."):
            return True
        if part == "__init__.py":
            continue
        if not include_private and part.startswith("_"):
            return True
    return False


def _module_name_from_path(
    py_file: Path,
    package_root: Path,
    package_name: str,
) -> str:
    """Compute the fully-qualified module name from a file path."""
    relative = py_file.relative_to(package_root)
    parts = list(relative.parts)

    if parts[-1] == "__init__.py":
        if len(parts) == 1:
            return package_name
        return f"{package_name}.{'.'.join(parts[:-1])}"

    parts[-1] = parts[-1].removesuffix(".py")
    return f"{package_name}.{'.'.join(parts)}"


def _walk_package(
    package_path: Path,
    package_name: str,
    config: LibcontextConfig,
) -> list[ModuleInfo]:
    """Walk a package source tree and inspect every Python module."""
    modules: list[ModuleInfo] = []

    # Single-file module
    if package_path.is_file():
        try:
            mod = inspect_file(package_path, module_name=package_name)
            modules.append(mod)
        except SyntaxError as exc:
            logger.warning("Syntax error in %s: %s", package_path, exc)
        except UnicodeDecodeError as exc:
            logger.warning("Encoding error in %s: %s", package_path, exc)
        except OSError as exc:
            logger.warning("Cannot read %s: %s", package_path, exc)
        return modules

    include_set = set(config.include_modules) if config.include_modules else None
    exclude_set = set(config.exclude_modules) if config.exclude_modules else set()

    for py_file in sorted(package_path.rglob("*.py")):
        relative = py_file.relative_to(package_path)
        parts = relative.parts

        if _should_skip_path(parts, include_private=config.include_private):
            continue

        module_name = _module_name_from_path(py_file, package_path, package_name)

        # Apply include / exclude filters
        if (
            include_set
            and not any(
                module_name == inc or module_name.startswith(f"{inc}.")
                for inc in include_set
            )
            and module_name != package_name
        ):
            continue

        if any(
            module_name == exc or module_name.startswith(f"{exc}.")
            for exc in exclude_set
        ):
            continue

        try:
            mod = inspect_file(py_file, module_name=module_name)
            modules.append(mod)
        except SyntaxError as exc:
            logger.warning("Syntax error in %s: %s", py_file, exc)
        except UnicodeDecodeError as exc:
            logger.warning("Encoding error in %s: %s", py_file, exc)
        except OSError as exc:
            logger.warning("Cannot read %s: %s", py_file, exc)

    return modules


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_package(
    package_name: str,
    *,
    include_private: bool = False,
    include_readme: bool = True,
    config_override: LibcontextConfig | None = None,
) -> PackageInfo:
    """Collect complete API information for a Python package.

    Combines source inspection, metadata retrieval, README discovery, and
    optional ``[tool.libcontext]`` configuration.

    Args:
        package_name: Importable package name **or** filesystem path.
        include_private: Include private (``_``-prefixed) modules/members.
        include_readme: Attach the package README to the result.
        config_override: Explicit config; skips automatic discovery.

    Returns:
        :class:`~libcontext.models.PackageInfo` with all collected data.

    Raises:
        ValueError: If the package cannot be located.
    """
    # --- Resolve path --------------------------------------------------
    path = Path(package_name)
    if path.exists():
        pkg_path = path.resolve()
        pkg_name = path.name if path.is_dir() else path.stem
        metadata: dict[str, str | None] = {}
        logger.debug("Resolved '%s' as local path: %s", package_name, pkg_path)
    else:
        pkg_path_resolved = find_package_path(package_name)
        if pkg_path_resolved is None:
            raise ValueError(
                f"Package '{package_name}' not found. "
                "Make sure it is installed in the current environment."
            )
        pkg_path = pkg_path_resolved
        pkg_name = package_name
        metadata = _get_package_metadata(package_name)
        logger.debug("Resolved '%s' as installed package: %s", package_name, pkg_path)

    # --- Config --------------------------------------------------------
    if config_override is not None:
        config = copy.copy(config_override)
    else:
        config = find_config_for_package(pkg_path)

    if include_private:
        config.include_private = True

    # --- Collect -------------------------------------------------------
    modules = _walk_package(pkg_path, pkg_name, config)
    readme = _find_readme(pkg_name, pkg_path) if include_readme else None

    logger.debug(
        "Collected %d modules for '%s'",
        len(modules),
        pkg_name,
    )

    return PackageInfo(
        name=pkg_name,
        version=metadata.get("version"),
        summary=metadata.get("summary"),
        readme=readme,
        modules=modules,
    )
