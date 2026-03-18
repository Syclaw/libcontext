"""MCP server — exposes libcontext inspection as tools for LLM assistants.

Provides tools for progressive API discovery:

1. ``get_package_overview`` — compact structural map (module + class/func names)
2. ``get_module_api`` — full API reference for a single module
3. ``search_api`` — find classes/functions by name across the package

Run with::

    libctx-mcp            # stdio transport (default for IDE integration)
    python -m libcontext.mcp_server

Requires the ``mcp`` optional dependency::

    pip install libcontext[mcp]
"""

from __future__ import annotations

import logging
from functools import lru_cache

from mcp.server.fastmcp import FastMCP

from .collector import collect_package
from .exceptions import PackageNotFoundError
from .models import PackageInfo
from .renderer import (
    render_module,
    render_package_overview,
    search_package,
)

logger = logging.getLogger(__name__)

_TOOL_PREFIX = "libcontext"

mcp = FastMCP(
    _TOOL_PREFIX,
    instructions=(
        "Inspect any installed Python package's API via static analysis. "
        "No code execution — safe for any package."
    ),
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CACHE_SIZE = 32


@lru_cache(maxsize=_CACHE_SIZE)
def _collect_cached(package_name: str, include_private: bool = False) -> PackageInfo:
    """Cache collected packages within the server process lifetime."""
    return collect_package(
        package_name,
        include_private=include_private,
        include_readme=False,
    )


def _invalidate_cache() -> None:
    """Clear the collection cache."""
    _collect_cached.cache_clear()


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_package_overview(package_name: str) -> str:
    """Get a structural overview of a Python package's API.

    Returns module names with their class and function names listed
    (no full signatures).  Use this first to understand a package's
    shape, then call ``get_module_api`` for the modules you need.

    Args:
        package_name: Importable package name (e.g. ``requests``).
    """
    try:
        pkg = _collect_cached(package_name)
    except PackageNotFoundError as exc:
        return f"Error: {exc}"

    return render_package_overview(pkg)


@mcp.tool()
def get_module_api(package_name: str, module_name: str) -> str:
    """Get detailed API reference for a specific module.

    Returns full function signatures with type annotations, class
    definitions with methods, and first-paragraph docstrings.

    Call ``get_package_overview`` first to discover available module names.

    Args:
        package_name: Importable package name.
        module_name: Fully qualified module name (e.g. ``requests.api``).
    """
    try:
        pkg = _collect_cached(package_name)
    except PackageNotFoundError as exc:
        return f"Error: {exc}"

    for mod in pkg.non_empty_modules:
        if mod.name == module_name:
            return render_module(mod)

    available = [m.name for m in pkg.non_empty_modules]
    return (
        f"Module '{module_name}' not found in {package_name}.\n"
        f"Available modules: {', '.join(available)}"
    )


@mcp.tool()
def search_api(package_name: str, query: str) -> str:
    """Search for classes, functions, or methods matching a query.

    Performs a case-insensitive substring search across all public names
    in the package.  Returns matching items with their location and
    signature.

    Args:
        package_name: Importable package name.
        query: Search term (case-insensitive substring match).
    """
    try:
        pkg = _collect_cached(package_name)
    except PackageNotFoundError as exc:
        return f"Error: {exc}"

    return search_package(pkg, query)


@mcp.tool()
def refresh_cache() -> str:
    """Clear all cached package data so the next call re-inspects from disk.

    Use when a package has been updated (pip install --upgrade) and
    the cached API data may be stale.
    """
    _invalidate_cache()
    return "Cache cleared for all packages."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the libcontext MCP server (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
