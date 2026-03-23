"""Persistent disk cache for collected package API data.

Caches ``PackageInfo`` as JSON to avoid repeated AST parsing for
unchanged packages.  Invalidation uses ``(version, max_mtime, file_count)``
to detect source changes.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .models import PackageInfo, _deserialize_envelope, _serialize_envelope

logger = logging.getLogger(__name__)

_CACHE_DIR_NAME = "libcontext"
_MAX_CACHE_ENTRIES = 50


# ---------------------------------------------------------------------------
# Cache directory
# ---------------------------------------------------------------------------


def _get_cache_dir() -> Path:
    """Return the platform-appropriate cache directory.

    - Linux/macOS: ``~/.cache/libcontext/``
    - Windows: ``%LOCALAPPDATA%/libcontext/cache/``

    Creates the directory if it does not exist.
    """
    if sys.platform == "win32":
        base = Path(
            os.environ.get(
                "LOCALAPPDATA",
                str(Path.home() / "AppData" / "Local"),
            )
        )
        cache_dir = base / _CACHE_DIR_NAME / "cache"
    else:
        base = Path(
            os.environ.get(
                "XDG_CACHE_HOME",
                str(Path.home() / ".cache"),
            )
        )
        cache_dir = base / _CACHE_DIR_NAME

    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


# ---------------------------------------------------------------------------
# Source stats for invalidation
# ---------------------------------------------------------------------------


@dataclass
class _SourceStats:
    """Aggregated stats for invalidation."""

    max_mtime: float
    file_count: int


def _compute_source_stats(package_path: Path) -> _SourceStats:
    """Compute mtime and file count across all source files in a package.

    Applies the same boundary and size guards as the collector to avoid
    following symlinks that escape the package directory.
    """
    from ._security import check_file_size, is_within_boundary

    max_mtime = 0.0
    file_count = 0
    for pattern in ("*.py", "*.pyi"):
        for f in package_path.rglob(pattern):
            if not is_within_boundary(f, package_path):
                continue
            if not check_file_size(f):
                continue
            try:
                mtime = f.stat().st_mtime
                if mtime > max_mtime:
                    max_mtime = mtime
                file_count += 1
            except OSError:
                continue
    return _SourceStats(max_mtime=max_mtime, file_count=file_count)


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------


def _safe_delete(path: Path) -> None:
    """Delete a file, ignoring errors."""
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def load(
    package_name: str,
    version: str | None,
    package_path: Path,
    env_tag: str | None = None,
) -> PackageInfo | None:
    """Load a cached PackageInfo if still valid.

    Args:
        package_name: Package name.
        version: Current installed version (from metadata).
        package_path: Path to the package source (for mtime check).
        env_tag: Environment identifier (from ``--python``).

    Returns:
        Cached PackageInfo if valid, None on miss or invalidation.
    """
    cache_file = _get_cache_dir() / _cache_filename(package_name, version, env_tag)

    if not cache_file.is_file():
        logger.debug("Cache miss for %r: file not found", package_name)
        return None

    try:
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
        data = _deserialize_envelope(raw)
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        logger.warning("Cache corrupted for %r: %s", package_name, exc)
        _safe_delete(cache_file)
        return None

    meta = data.get("_cache_meta")
    if not meta:
        logger.debug("Cache miss for %r: no metadata", package_name)
        _safe_delete(cache_file)
        return None

    current = _compute_source_stats(package_path)
    cached_mtime = meta.get("max_mtime", 0.0)
    cached_count = meta.get("file_count", -1)

    if current.max_mtime > cached_mtime:
        logger.debug(
            "Cache invalidated for %r: mtime changed (%.3f > %.3f)",
            package_name,
            current.max_mtime,
            cached_mtime,
        )
        _safe_delete(cache_file)
        return None

    if current.file_count != cached_count:
        logger.debug(
            "Cache invalidated for %r: file count changed (%d != %d)",
            package_name,
            current.file_count,
            cached_count,
        )
        _safe_delete(cache_file)
        return None

    logger.info("Cache hit for %r v%s", package_name, version)

    data.pop("_cache_meta", None)
    return PackageInfo.from_dict(data)


def save(
    package_info: PackageInfo,
    package_path: Path,
    source_stats: _SourceStats | None = None,
    env_tag: str | None = None,
) -> None:
    """Save a PackageInfo to the disk cache.

    Args:
        package_info: The collected package data.
        package_path: Path to the package source (for mtime computation).
        source_stats: Pre-computed stats. If None, stats are computed fresh.
        env_tag: Environment identifier (from ``--python``).
    """
    if source_stats is None:
        source_stats = _compute_source_stats(package_path)

    data = dataclasses.asdict(package_info)
    data["_cache_meta"] = {
        "max_mtime": source_stats.max_mtime,
        "file_count": source_stats.file_count,
        "cached_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
    }
    envelope = _serialize_envelope(data)

    cache_dir = _get_cache_dir()
    cache_file = cache_dir / _cache_filename(
        package_info.name, package_info.version, env_tag
    )

    try:
        cache_file.write_text(
            json.dumps(envelope, indent=2),
            encoding="utf-8",
        )
        logger.debug("Cached %r v%s", package_info.name, package_info.version)
    except OSError as exc:
        logger.warning("Cannot write cache for %r: %s", package_info.name, exc)
        return

    _evict_oldest(cache_dir)


# ---------------------------------------------------------------------------
# Eviction
# ---------------------------------------------------------------------------


def _evict_oldest(cache_dir: Path) -> None:
    """Remove oldest cache entries if the cache exceeds the size limit."""
    entries: list[tuple[Path, float]] = []
    for f in cache_dir.glob("*.json"):
        try:
            entries.append((f, f.stat().st_mtime))
        except OSError:
            continue
    entries.sort(key=lambda x: x[1])
    while len(entries) > _MAX_CACHE_ENTRIES:
        oldest_path, _ = entries.pop(0)
        logger.debug("Evicting cache entry: %s", oldest_path.name)
        _safe_delete(oldest_path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def clear_all() -> int:
    """Remove all cached API snapshots.

    Returns:
        Number of entries removed.
    """
    cache_dir = _get_cache_dir()
    count = 0
    for f in cache_dir.glob("*.json"):
        _safe_delete(f)
        count += 1
    return count


def clear_package(package_name: str) -> int:
    """Remove cached entries matching a package name.

    Matches entries whose embedded ``name`` field equals *package_name*
    (case-insensitive, normalised with hyphens → underscores).

    Args:
        package_name: Package name to clear.

    Returns:
        Number of entries removed.
    """
    target = package_name.lower().replace("-", "_")
    cache_dir = _get_cache_dir()
    count = 0
    for f in cache_dir.glob("*.json"):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            data = _deserialize_envelope(raw)
        except (json.JSONDecodeError, ValueError, OSError):
            continue
        name = data.get("name", "")
        if isinstance(name, str) and name.lower().replace("-", "_") == target:
            _safe_delete(f)
            count += 1
    return count


@dataclass
class CacheEntry:
    """Summary of a single cache entry for display."""

    package: str
    version: str
    cached_at: str
    size_bytes: int
    file_path: Path


def list_entries() -> list[CacheEntry]:
    """List all cached API snapshots with metadata.

    Returns:
        List of :class:`CacheEntry` sorted by package name then version.
    """
    cache_dir = _get_cache_dir()
    entries: list[CacheEntry] = []
    for f in cache_dir.glob("*.json"):
        try:
            size = f.stat().st_size
            raw = json.loads(f.read_text(encoding="utf-8"))
            data = _deserialize_envelope(raw)
        except (json.JSONDecodeError, ValueError, OSError):
            continue
        meta = data.get("_cache_meta", {})
        entries.append(
            CacheEntry(
                package=data.get("name", "unknown"),
                version=data.get("version", "unknown"),
                cached_at=meta.get("cached_at", "unknown"),
                size_bytes=size,
                file_path=f,
            )
        )
    entries.sort(key=lambda e: (e.package.lower(), e.version))
    return entries


def _cache_filename(
    package_name: str,
    version: str | None,
    env_tag: str | None = None,
) -> str:
    """Build the cache filename for a package.

    Sanitises both components to prevent path traversal via crafted
    package names (e.g. ``../../etc/cron.d/evil``).

    When *env_tag* is provided (from ``--python``), it is appended to
    the filename so that packages from different environments get
    separate cache entries.
    """
    from ._security import sanitize_filename

    safe_name = sanitize_filename(package_name)
    safe_version = sanitize_filename(version) if version else "unknown"
    if env_tag:
        safe_tag = sanitize_filename(env_tag)
        return f"{safe_name}-{safe_version}-{safe_tag}.json"
    return f"{safe_name}-{safe_version}.json"
