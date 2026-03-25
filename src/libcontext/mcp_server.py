"""MCP server — exposes libcontext inspection as tools for LLM assistants.

Provides tools for progressive API discovery:

1. ``get_package_overview`` — compact structural map (module + class/func names)
2. ``get_module_api`` — full API reference for a single module
3. ``search_api`` — find classes/functions by name or docstring across the package
4. ``get_api_json`` — full or single-module API as structured JSON
5. ``diff_api`` — compare two API snapshots and report changes

Run with::

    libctx-mcp            # stdio transport (default for IDE integration)
    python -m libcontext.mcp_server

Requires the ``mcp`` optional dependency::

    pip install libcontext[mcp]
"""

from __future__ import annotations

import dataclasses
import json
import logging
from functools import lru_cache

from mcp.server.fastmcp import FastMCP

from . import cache as _cache
from ._security import truncate_output
from .collector import collect_package
from .diff import diff_packages
from .exceptions import PackageNotFoundError
from .models import PackageInfo, _deserialize_envelope, _serialize_envelope
from .renderer import (
    render_diff,
    render_module,
    render_package_overview,
    search_package,
    search_package_structured,
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

# Set by main() at startup; used by _collect_cached for cache namespacing.
_active_env_tag: str | None = None


@lru_cache(maxsize=_CACHE_SIZE)
def _collect_cached(package_name: str, include_private: bool = False) -> PackageInfo:
    """Cache collected packages within the server process lifetime."""
    return collect_package(
        package_name,
        include_private=include_private,
        include_readme=False,
        env_tag=_active_env_tag,
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

    return truncate_output(render_package_overview(pkg))


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
            return truncate_output(render_module(mod))

    available = [m.name for m in pkg.non_empty_modules]
    return (
        f"Module '{module_name}' not found in {package_name}.\n"
        f"Available modules: {', '.join(available)}"
    )


@mcp.tool()
def search_api(
    package_name: str,
    query: str,
    kind: str | None = None,
    output_format: str = "markdown",
) -> str:
    """Search for classes, functions, or methods matching a query.

    Performs a case-insensitive substring search across all public names
    and first-paragraph docstrings.

    Args:
        package_name: Importable package name.
        query: Search term (case-insensitive substring match).
        kind: Filter by entity type (``class``, ``function``,
            ``variable``, ``alias``). Omit to search all types.
        output_format: Output format — ``markdown`` (human-readable) or
            ``json`` (structured, easier for programmatic use).
    """
    try:
        pkg = _collect_cached(package_name)
    except PackageNotFoundError as exc:
        return f"Error: {exc}"

    try:
        if output_format == "json":
            results = search_package_structured(pkg, query, kind=kind)
            data = {"query": query, "package": package_name, "results": results}
            envelope = _serialize_envelope(data)
            return truncate_output(json.dumps(envelope, indent=2))
        return truncate_output(search_package(pkg, query, kind=kind))
    except ValueError as exc:
        return f"Error: {exc}"


@mcp.tool()
def get_api_json(
    package_name: str,
    module_name: str | None = None,
) -> str:
    """Get the API structure of a Python package (or a single module) as JSON.

    Returns a versioned JSON envelope suitable for programmatic consumption,
    caching, or diff operations.

    Args:
        package_name: The importable package name.
        module_name: Fully qualified module name to extract a single module.
            Omit to get the full package.
    """
    try:
        pkg = _collect_cached(package_name)
    except PackageNotFoundError as exc:
        return f"Error: {exc}"

    if module_name is not None:
        for mod in pkg.non_empty_modules:
            if mod.name == module_name:
                envelope = _serialize_envelope(dataclasses.asdict(mod))
                return truncate_output(json.dumps(envelope, indent=2))
        available = [m.name for m in pkg.non_empty_modules]
        return (
            f"Module '{module_name}' not found in {package_name}.\n"
            f"Available modules: {', '.join(available)}"
        )

    envelope = _serialize_envelope(dataclasses.asdict(pkg))
    return truncate_output(json.dumps(envelope, indent=2))


@mcp.tool()
def diff_api(old_json: str, new_json: str, output_format: str = "markdown") -> str:
    """Compare two API snapshots and report added, removed, and modified symbols.

    Accepts two JSON strings (as produced by ``get_api_json``) and returns
    a diff highlighting breaking changes, additions, and modifications.

    Args:
        old_json: JSON string of the old API snapshot.
        new_json: JSON string of the new API snapshot.
        output_format: Output format — ``markdown`` or ``json``.
    """
    from ._security import MAX_JSON_INPUT_BYTES

    for label, payload in (("old_json", old_json), ("new_json", new_json)):
        if len(payload) > MAX_JSON_INPUT_BYTES:
            limit_mib = MAX_JSON_INPUT_BYTES // (1024 * 1024)
            return (
                f"Error: {label} exceeds the {limit_mib} MiB "
                f"size limit ({len(payload):,} bytes)."
            )

    try:
        old_raw = json.loads(old_json)
        new_raw = json.loads(new_json)
    except json.JSONDecodeError as exc:
        return f"Error: invalid JSON — {exc}"

    try:
        old_data = _deserialize_envelope(old_raw)
        new_data = _deserialize_envelope(new_raw)
    except ValueError as exc:
        return f"Error: {exc}"

    old_pkg = PackageInfo.from_dict(old_data)
    new_pkg = PackageInfo.from_dict(new_data)
    result = diff_packages(old_pkg, new_pkg)

    if output_format == "json":
        envelope = _serialize_envelope(dataclasses.asdict(result))
        return truncate_output(json.dumps(envelope, indent=2))
    return truncate_output(render_diff(result))


@mcp.tool()
def refresh_cache() -> str:
    """Clear all cached package data (in-memory and on disk).

    Use when a package has been updated (pip install --upgrade) and
    the cached API data may be stale. Clears both the in-process
    LRU cache and the persistent disk cache.
    """
    _invalidate_cache()
    disk_count = _cache.clear_all()
    return f"Cache cleared: in-memory + {disk_count} disk entries."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the libcontext MCP server (stdio transport).

    Environment resolution (in priority order):

    1. ``--python <path>`` CLI argument → use that environment.
    2. ``LIBCONTEXT_PYTHON`` env var → use that environment.
    3. Auto-detect ``.venv/`` or ``venv/`` in CWD → use the detected venv.
    4. None of the above → use the current process's environment.

    Raises:
        EnvironmentSetupError: If an explicit ``--python`` path is invalid.
    """
    import os
    import sys as _sys

    python_env = None
    args = _sys.argv[1:]
    if args and args[0] == "--python" and len(args) >= 2:
        python_env = args[1]
    elif os.environ.get("LIBCONTEXT_PYTHON"):
        python_env = os.environ["LIBCONTEXT_PYTHON"]

    global _active_env_tag

    from ._envsetup import setup_environment

    _active_env_tag = setup_environment(python_env)

    mcp.run()


if __name__ == "__main__":
    main()
