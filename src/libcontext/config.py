"""Configuration reader for libcontext.

Reads optional ``[tool.libcontext]`` configuration from a package's
``pyproject.toml`` to allow library authors to customize which parts
of their API are exposed in the generated context.

Example configuration in pyproject.toml::

    [tool.libcontext]
    include_modules = ["mypackage.core", "mypackage.models"]
    exclude_modules = ["mypackage._internal", "mypackage.tests"]
    include_private = false
    extra_context = "This library uses the repository pattern for data access."
    max_readme_lines = 150
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class LibcontextConfig:
    """Configuration for context generation."""

    include_modules: list[str] = field(default_factory=list)
    exclude_modules: list[str] = field(default_factory=list)
    include_private: bool = False
    extra_context: str | None = None
    max_readme_lines: int = 100

    @classmethod
    def from_dict(cls, data: dict) -> LibcontextConfig:
        """Create config from a dictionary (e.g. parsed TOML section).

        Raises:
            TypeError: If a value has an unexpected type.
        """
        include_modules = data.get("include_modules", [])
        exclude_modules = data.get("exclude_modules", [])
        include_private = data.get("include_private", False)
        extra_context = data.get("extra_context")
        max_readme_lines = data.get("max_readme_lines", 100)

        # --- Type validation ---
        if not isinstance(include_modules, list):
            raise TypeError(
                f"include_modules must be a list, got {type(include_modules).__name__}"
            )
        if not isinstance(exclude_modules, list):
            raise TypeError(
                f"exclude_modules must be a list, got {type(exclude_modules).__name__}"
            )
        if not isinstance(include_private, bool):
            raise TypeError(
                f"include_private must be a bool, got {type(include_private).__name__}"
            )
        if extra_context is not None and not isinstance(extra_context, str):
            raise TypeError(
                "extra_context must be a string or null, "
                f"got {type(extra_context).__name__}"
            )
        if not isinstance(max_readme_lines, int) or isinstance(max_readme_lines, bool):
            raise TypeError(
                "max_readme_lines must be an integer, "
                f"got {type(max_readme_lines).__name__}"
            )

        return cls(
            include_modules=include_modules,
            exclude_modules=exclude_modules,
            include_private=include_private,
            extra_context=extra_context,
            max_readme_lines=max_readme_lines,
        )


def _load_toml(path: Path) -> dict:
    """Load a TOML file, using tomllib (3.11+) or tomli as fallback."""
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        try:
            import tomli as tomllib
        except ImportError:
            logger.warning(
                "tomli is not installed and Python < 3.11; "
                "TOML configuration will be ignored. "
                "Install tomli (`pip install tomli`) to enable config support."
            )
            return {}

    try:
        with path.open("rb") as f:
            return dict(tomllib.load(f))
    except OSError as exc:
        logger.debug("Cannot read TOML file %s: %s", path, exc)
        return {}
    except ValueError as exc:
        logger.warning("Invalid TOML in %s: %s", path, exc)
        return {}


def read_config_from_pyproject(pyproject_path: Path) -> LibcontextConfig:
    """Read libcontext config from a pyproject.toml file.

    Args:
        pyproject_path: Path to the pyproject.toml file.

    Returns:
        LibcontextConfig parsed from the file, or defaults if not found.
    """
    data = _load_toml(pyproject_path)
    tool_config = data.get("tool", {}).get("libcontext", {})
    return LibcontextConfig.from_dict(tool_config)


def find_config_for_package(package_path: Path) -> LibcontextConfig:
    """Search for libcontext configuration near a package directory.

    Looks for ``pyproject.toml`` in the package directory and up to two
    parent directories (to handle src layout: ``project/src/package/``).

    Args:
        package_path: Path to the package source directory.

    Returns:
        LibcontextConfig if found, otherwise default configuration.
    """
    search_dirs = [
        package_path,
        package_path.parent,
        package_path.parent.parent,
    ]

    for search_dir in search_dirs:
        pyproject = search_dir / "pyproject.toml"
        if pyproject.is_file():
            data = _load_toml(pyproject)
            if "libcontext" in data.get("tool", {}):
                logger.debug("Found [tool.libcontext] config in %s", pyproject)
                tool_config = data["tool"]["libcontext"]
                return LibcontextConfig.from_dict(tool_config)

    logger.debug("No [tool.libcontext] config found near %s", package_path)
    return LibcontextConfig()
