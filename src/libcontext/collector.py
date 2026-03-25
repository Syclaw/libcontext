"""Package collector — discovers and inspects all modules in a Python package.

Walks the source tree of an installed (or local) package, applies filtering
rules from the optional ``[tool.libcontext]`` configuration, and returns a
complete :class:`~libcontext.models.PackageInfo` data structure.
"""

from __future__ import annotations

import copy
import difflib
import importlib.metadata
import importlib.util
import logging
import sys
from pathlib import Path

from . import cache as _cache
from .config import LibcontextConfig, find_config_for_package
from .exceptions import InspectionError, PackageNotFoundError
from .inspector import inspect_file
from .models import (
    ClassInfo,
    FunctionInfo,
    ModuleInfo,
    PackageInfo,
    VariableInfo,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Package name suggestions
# ---------------------------------------------------------------------------

_SUGGESTION_CUTOFF = 0.6
_SUGGESTION_MAX = 3


def _get_installed_package_names() -> list[str]:
    """Collect all known package names from the current environment.

    Gathers both distribution names and top-level import names so that
    suggestions cover both namespaces (e.g. ``scikit-learn`` and ``sklearn``).
    """
    names: set[str] = set()

    if sys.version_info >= (3, 11):
        try:
            for import_name in importlib.metadata.packages_distributions():
                names.add(import_name)
        except Exception:
            # Intentionally broad: packages_distributions() can fail
            # in unpredictable ways depending on Python version and
            # environment state (ImportError from broken stdlib
            # modules, RuntimeError from corrupted metadata, etc.).
            # The distributions()-based fallback below is more
            # resilient, so any failure here is non-critical.
            logger.debug(
                "packages_distributions() failed; falling back to distributions() only",
                exc_info=True,
            )

    seen_distributions: set[str] = set()
    for dist in importlib.metadata.distributions():
        dist_name = dist.metadata["Name"]
        if not dist_name or dist_name in seen_distributions:
            continue
        seen_distributions.add(dist_name)
        names.add(dist_name)
        # Normalized form (- → _, lowercased) so "scikit-learn" also
        # matches a typo like "scikit_lern"
        normalized = dist_name.replace("-", "_").lower()
        if normalized != dist_name:
            names.add(normalized)

        try:
            top_level = dist.read_text("top_level.txt")
        except OSError:
            top_level = None
        if top_level:
            for line in top_level.strip().splitlines():
                entry = line.strip()
                if entry and not entry.startswith("#"):
                    names.add(entry)

    return sorted(names)


def suggest_similar_packages(name: str) -> list[str]:
    """Find installed packages with names similar to *name*.

    Uses :func:`difflib.get_close_matches` (Ratcliff/Obershelp algorithm)
    which handles character transpositions better than raw Levenshtein
    distance for short identifier strings.

    Args:
        name: The (possibly misspelled) package name.

    Returns:
        Up to 3 similar names, sorted by descending similarity.
    """
    candidates = _get_installed_package_names()
    return difflib.get_close_matches(
        name,
        candidates,
        n=_SUGGESTION_MAX,
        cutoff=_SUGGESTION_CUTOFF,
    )


# ---------------------------------------------------------------------------
# Stub support
# ---------------------------------------------------------------------------

_COMPILED_SUFFIXES = frozenset({".so", ".pyd", ".dylib"})


def _is_compiled_extension(path: Path) -> bool:
    """Check if a path points to a compiled extension module.

    A directory is considered a compiled extension if it has neither
    ``__init__.py`` nor ``__init__.pyi``.
    """
    if path.is_file():
        return any(path.name.endswith(s) for s in _COMPILED_SUFFIXES)
    if path.is_dir():
        return not ((path / "__init__.py").exists() or (path / "__init__.pyi").exists())
    return False


def _find_stub_package(package_name: str) -> Path | None:
    """Locate a standalone stub package for *package_name*.

    Searches installed distributions for ``<name>-stubs`` and
    ``types-<name>`` patterns (PEP 561).

    Args:
        package_name: The importable package name (e.g. ``pandas``).

    Returns:
        Path to the stub package directory, or ``None`` if not found.
    """
    norm_name = package_name.replace("-", "_").lower()
    candidates: list[tuple[int, importlib.metadata.Distribution]] = []

    seen: set[str] = set()
    for dist in importlib.metadata.distributions():
        dist_name = dist.metadata["Name"]
        if not dist_name or dist_name in seen:
            continue
        seen.add(dist_name)
        dist_norm = dist_name.replace("-", "_").lower()
        if dist_norm == f"{norm_name}_stubs":
            candidates.append((0, dist))  # priority 0 = highest
        elif dist_norm == f"types_{norm_name}":
            candidates.append((1, dist))

    candidates.sort(key=lambda x: x[0])

    for _priority, dist in candidates:
        # Try to resolve via dist.files
        if dist.files:
            for f in dist.files:
                if str(f).endswith(".pyi"):
                    stub_root = Path(dist.locate_file(f.parts[0]))
                    if stub_root.is_dir():
                        return stub_root
        # Fallback: convention-based path
        site_packages = Path(dist.locate_file(""))
        for suffix in (f"{package_name}-stubs", f"{norm_name}-stubs"):
            candidate = site_packages / suffix
            if candidate.is_dir():
                return candidate

    return None


def _merge_functions(
    py_funcs: list[FunctionInfo],
    pyi_funcs: list[FunctionInfo],
) -> list[FunctionInfo]:
    """Merge function lists: signatures from .pyi, docstrings from .py."""
    py_index = {f.name: f for f in py_funcs}
    result: list[FunctionInfo] = []
    seen: set[str] = set()

    for pyi_f in pyi_funcs:
        seen.add(pyi_f.name)
        py_f = py_index.get(pyi_f.name)
        if py_f is not None:
            result.append(
                FunctionInfo(
                    name=pyi_f.name,
                    qualname=pyi_f.qualname,
                    parameters=pyi_f.parameters,
                    return_annotation=pyi_f.return_annotation,
                    docstring=py_f.docstring or pyi_f.docstring,
                    decorators=pyi_f.decorators,
                    is_async=pyi_f.is_async,
                    is_property=pyi_f.is_property,
                    is_classmethod=pyi_f.is_classmethod,
                    is_staticmethod=pyi_f.is_staticmethod,
                    line_number=py_f.line_number or pyi_f.line_number,
                )
            )
        else:
            result.append(pyi_f)

    for py_f in py_funcs:
        if py_f.name not in seen:
            result.append(py_f)

    return result


def _merge_variables(
    py_vars: list[VariableInfo],
    pyi_vars: list[VariableInfo],
) -> list[VariableInfo]:
    """Merge variable lists: annotations from .pyi, values from .py."""
    py_index = {v.name: v for v in py_vars}
    result: list[VariableInfo] = []
    seen: set[str] = set()

    for pyi_v in pyi_vars:
        seen.add(pyi_v.name)
        py_v = py_index.get(pyi_v.name)
        if py_v is not None:
            result.append(
                VariableInfo(
                    name=pyi_v.name,
                    annotation=pyi_v.annotation or py_v.annotation,
                    value=py_v.value or pyi_v.value,
                    line_number=py_v.line_number or pyi_v.line_number,
                    is_type_alias=pyi_v.is_type_alias or py_v.is_type_alias,
                )
            )
        else:
            result.append(pyi_v)

    for py_v in py_vars:
        if py_v.name not in seen:
            result.append(py_v)

    return result


def _merge_classes(
    py_classes: list[ClassInfo],
    pyi_classes: list[ClassInfo],
) -> list[ClassInfo]:
    """Merge class lists recursively."""
    py_index = {c.name: c for c in py_classes}
    result: list[ClassInfo] = []
    seen: set[str] = set()

    for pyi_c in pyi_classes:
        seen.add(pyi_c.name)
        py_c = py_index.get(pyi_c.name)
        if py_c is not None:
            result.append(
                ClassInfo(
                    name=pyi_c.name,
                    qualname=pyi_c.qualname,
                    bases=pyi_c.bases,
                    docstring=py_c.docstring or pyi_c.docstring,
                    methods=_merge_functions(py_c.methods, pyi_c.methods),
                    class_variables=_merge_variables(
                        py_c.class_variables, pyi_c.class_variables
                    ),
                    decorators=pyi_c.decorators,
                    inner_classes=_merge_classes(
                        py_c.inner_classes, pyi_c.inner_classes
                    ),
                    line_number=py_c.line_number or pyi_c.line_number,
                )
            )
        else:
            result.append(pyi_c)

    for py_c in py_classes:
        if py_c.name not in seen:
            result.append(py_c)

    return result


def _merge_module(py_mod: ModuleInfo, pyi_mod: ModuleInfo) -> ModuleInfo:
    """Merge a source module with its stub.

    Type signatures come from the stub, docstrings from the source.

    Args:
        py_mod: ModuleInfo from the ``.py`` source.
        pyi_mod: ModuleInfo from the ``.pyi`` stub.

    Returns:
        Merged ModuleInfo.
    """
    return ModuleInfo(
        name=py_mod.name,
        path=py_mod.path or pyi_mod.path,
        docstring=py_mod.docstring or pyi_mod.docstring,
        classes=_merge_classes(py_mod.classes, pyi_mod.classes),
        functions=_merge_functions(py_mod.functions, pyi_mod.functions),
        variables=_merge_variables(py_mod.variables, pyi_mod.variables),
        all_exports=(
            py_mod.all_exports
            if py_mod.all_exports is not None
            else pyi_mod.all_exports
        ),
    )


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


def _safe_rglob(root: Path, pattern: str) -> list[Path]:
    """Like ``sorted(root.rglob(pattern))`` but tolerant of permission errors.

    Collects as many matching files as possible before the first
    inaccessible directory terminates the generator.
    """
    results: list[Path] = []
    try:
        for path in root.rglob(pattern):
            results.append(path)
    except PermissionError:
        logger.warning(
            "Permission denied while traversing '%s'; "
            "some modules may be missing",
            root,
        )
    results.sort()
    return results


def _is_safe_source_file(file_path: Path, root: Path) -> bool:
    """Check that a source file is safe to read.

    Rejects files that escape the package boundary via symlinks and
    files larger than the configured limit (likely generated data, not API).
    """
    from ._security import check_file_size, is_within_boundary

    if not is_within_boundary(file_path, root):
        logger.warning(
            "Skipped %s: resolves outside package boundary %s",
            file_path,
            root,
        )
        return False
    if not check_file_size(file_path):
        logger.warning("Skipped %s: exceeds source file size limit", file_path)
        return False
    return True


def _should_skip_path(parts: tuple[str, ...], include_private: bool) -> bool:
    """Decide whether a file path should be skipped.

    Skips ``__pycache__``, ``.git``, and (optionally) private modules.
    """
    for part in parts:
        if part == "__pycache__" or part.startswith("."):
            return True
        if Path(part).stem == "__init__":
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

    if Path(parts[-1]).stem == "__init__":
        if len(parts) == 1:
            return package_name
        return f"{package_name}.{'.'.join(parts[:-1])}"

    parts[-1] = Path(parts[-1]).stem
    return f"{package_name}.{'.'.join(parts)}"


def _walk_package(
    package_path: Path,
    package_name: str,
    config: LibcontextConfig,
    *,
    stub_path: Path | None = None,
) -> list[ModuleInfo]:
    """Walk a package source tree and inspect every Python module.

    When *stub_path* is provided, ``.pyi`` files from the stub directory
    are merged with ``.py`` files from the primary package.

    Args:
        package_path: Root of the primary package.
        package_name: Fully-qualified package name.
        config: Collection configuration.
        stub_path: Root of the standalone stub package, if any.
    """
    modules: list[ModuleInfo] = []

    # Single-file module
    if package_path.is_file():
        pyi_sibling = package_path.with_suffix(".pyi")
        py_mod: ModuleInfo | None = None
        try:
            py_mod = inspect_file(package_path, module_name=package_name)
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            if pyi_sibling.is_file():
                logger.warning("Source %s failed, using stub: %s", package_path, exc)
            else:
                raise InspectionError(str(package_path), str(exc)) from exc

        if pyi_sibling.is_file():
            try:
                pyi_mod = inspect_file(pyi_sibling, module_name=package_name)
                if py_mod is not None:
                    mod = _merge_module(py_mod, pyi_mod)
                    mod.stub_source = "colocated"
                else:
                    mod = pyi_mod
                    mod.stub_source = "colocated"
                modules.append(mod)
            except (SyntaxError, UnicodeDecodeError, OSError) as exc:
                logger.warning("Stub %s failed: %s", pyi_sibling, exc)
                if py_mod is not None:
                    modules.append(py_mod)
        elif py_mod is not None:
            modules.append(py_mod)

        return modules

    include_set = set(config.include_modules) if config.include_modules else None
    exclude_set = set(config.exclude_modules) if config.exclude_modules else set()

    # Phase 1: collect all source files
    # key = relative path without extension -> (py_path, pyi_path, stub_source)
    file_map: dict[str, tuple[Path | None, Path | None, str]] = {}

    for py_file in _safe_rglob(package_path, "*.py"):
        if not _is_safe_source_file(py_file, package_path):
            continue
        relative = py_file.relative_to(package_path)
        parts = relative.parts
        if _should_skip_path(parts, include_private=config.include_private):
            continue
        key = str(relative.with_suffix(""))
        file_map[key] = (py_file, None, "")

    # Colocated .pyi files
    for pyi_file in _safe_rglob(package_path, "*.pyi"):
        if not _is_safe_source_file(pyi_file, package_path):
            continue
        relative = pyi_file.relative_to(package_path)
        parts = relative.parts
        if _should_skip_path(parts, include_private=config.include_private):
            continue
        key = str(relative.with_suffix(""))
        existing = file_map.get(key, (None, None, ""))
        file_map[key] = (existing[0], pyi_file, "colocated")

    # Standalone stub .pyi files
    if stub_path is not None:
        for pyi_file in _safe_rglob(stub_path, "*.pyi"):
            if not _is_safe_source_file(pyi_file, stub_path):
                continue
            relative = pyi_file.relative_to(stub_path)
            parts = relative.parts
            if _should_skip_path(parts, include_private=config.include_private):
                continue
            key = str(relative.with_suffix(""))
            existing = file_map.get(key, (None, None, ""))
            # Colocated stubs take priority over standalone
            if existing[1] is None:
                file_map[key] = (existing[0], pyi_file, "standalone")

    # Phase 2: inspect and merge
    for key in sorted(file_map):
        py_file_entry, pyi_file_entry, source_type = file_map[key]

        # Determine module name from whichever file is available
        ref_file = py_file_entry or pyi_file_entry
        if ref_file is None:
            continue
        ref_root = package_path if py_file_entry else (stub_path or package_path)
        try:
            module_name = _module_name_from_path(ref_file, ref_root, package_name)
        except ValueError:
            # File not relative to root (shouldn't happen)
            continue

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

        # Inspect available files
        py_mod_info: ModuleInfo | None = None
        pyi_mod_info: ModuleInfo | None = None

        if py_file_entry is not None:
            try:
                py_mod_info = inspect_file(py_file_entry, module_name=module_name)
            except (SyntaxError, UnicodeDecodeError, OSError) as exc:
                logger.warning("Skipped %s: %s", py_file_entry, exc)

        if pyi_file_entry is not None:
            try:
                pyi_mod_info = inspect_file(pyi_file_entry, module_name=module_name)
            except (SyntaxError, UnicodeDecodeError, OSError) as exc:
                logger.warning("Stub %s failed: %s", pyi_file_entry, exc)

        # Merge or use what's available
        if py_mod_info is not None and pyi_mod_info is not None:
            mod = _merge_module(py_mod_info, pyi_mod_info)
            mod.stub_source = source_type
            modules.append(mod)
        elif pyi_mod_info is not None:
            pyi_mod_info.stub_source = source_type or "colocated"
            modules.append(pyi_mod_info)
        elif py_mod_info is not None:
            modules.append(py_mod_info)

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
    no_cache: bool = False,
    env_tag: str | None = None,
) -> PackageInfo:
    """Collect complete API information for a Python package.

    Combines source inspection, metadata retrieval, README discovery, and
    optional ``[tool.libcontext]`` configuration.

    Args:
        package_name: Importable package name **or** filesystem path.
        include_private: Include private (``_``-prefixed) modules/members.
        include_readme: Attach the package README to the result.
        config_override: Explicit config; skips automatic discovery.
        no_cache: Skip the disk cache (force fresh AST collection).
        env_tag: Environment identifier for cache namespacing (from
            ``--python``).

    Returns:
        :class:`~libcontext.models.PackageInfo` with all collected data.

    Raises:
        PackageNotFoundError: If the package cannot be located.
        InspectionError: If a single-file module cannot be parsed or read.
    """
    # --- Resolve path --------------------------------------------------
    path = Path(package_name)
    stub_path: Path | None = None

    if path.exists():
        pkg_path = path.resolve()
        pkg_name = path.name if path.is_dir() else path.stem
        metadata: dict[str, str | None] = {}
        logger.debug("Resolved '%s' as local path: %s", package_name, pkg_path)
    else:
        pkg_path_resolved = find_package_path(package_name)

        if pkg_path_resolved is None or _is_compiled_extension(pkg_path_resolved):
            stub_path = _find_stub_package(package_name)
            if stub_path:
                pkg_path = stub_path
                stub_path = None
                logger.info(
                    "Package '%s' has no Python source; using stubs as primary",
                    package_name,
                )
            elif pkg_path_resolved is None:
                suggestions = suggest_similar_packages(package_name)
                raise PackageNotFoundError(package_name, suggestions=suggestions)
            else:
                pkg_path = pkg_path_resolved
        else:
            pkg_path = pkg_path_resolved
            stub_path = _find_stub_package(package_name)
            if stub_path:
                logger.info(
                    "Stub package discovered for '%s' at %s",
                    package_name,
                    stub_path,
                )

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

    # --- Cache lookup --------------------------------------------------
    is_local = path.exists()
    use_cache = not no_cache and not is_local and bool(metadata.get("version"))
    source_stats: _cache._SourceStats | None = None

    if use_cache:
        cached = _cache.load(pkg_name, metadata.get("version"), pkg_path, env_tag)
        if cached is not None:
            if include_readme:
                cached.readme = _find_readme(pkg_name, pkg_path)
            return cached
        source_stats = _cache._compute_source_stats(pkg_path)

    # --- Collect -------------------------------------------------------
    modules = _walk_package(pkg_path, pkg_name, config, stub_path=stub_path)
    readme = _find_readme(pkg_name, pkg_path) if include_readme else None

    logger.debug(
        "Collected %d modules for '%s'",
        len(modules),
        pkg_name,
    )

    pkg_info = PackageInfo(
        name=pkg_name,
        version=metadata.get("version"),
        summary=metadata.get("summary"),
        readme=readme,
        modules=modules,
    )

    # --- Cache save ----------------------------------------------------
    if use_cache:
        _cache.save(pkg_info, pkg_path, source_stats=source_stats, env_tag=env_tag)

    return pkg_info
