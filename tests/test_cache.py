"""Tests for cache module."""

from __future__ import annotations

import json
import time

from libcontext.cache import (
    _MAX_CACHE_ENTRIES,
    _cache_filename,
    _compute_source_stats,
    _evict_oldest,
    _get_cache_dir,
    clear_all,
    load,
    save,
)
from libcontext.models import (
    FunctionInfo,
    ModuleInfo,
    PackageInfo,
    _serialize_envelope,
)

# ---------------------------------------------------------------------------
# _get_cache_dir
# ---------------------------------------------------------------------------


def test_get_cache_dir_creates_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("libcontext.cache.sys.platform", "linux")
    cache_dir = _get_cache_dir()
    assert cache_dir.is_dir()
    assert cache_dir == tmp_path / "libcontext"


def test_get_cache_dir_windows(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("libcontext.cache.sys.platform", "win32")
    cache_dir = _get_cache_dir()
    assert cache_dir.is_dir()
    assert cache_dir == tmp_path / "libcontext" / "cache"


# ---------------------------------------------------------------------------
# _compute_source_stats
# ---------------------------------------------------------------------------


def test_compute_source_stats_multiple_files(tmp_path):
    (tmp_path / "a.py").write_text("# a")
    time.sleep(0.01)
    (tmp_path / "b.py").write_text("# b")
    stats = _compute_source_stats(tmp_path)
    assert stats.file_count == 2
    assert stats.max_mtime > 0.0


def test_compute_source_stats_includes_pyi(tmp_path):
    (tmp_path / "a.py").write_text("# a")
    (tmp_path / "a.pyi").write_text("# stub")
    stats = _compute_source_stats(tmp_path)
    assert stats.file_count == 2


def test_compute_source_stats_empty_dir(tmp_path):
    stats = _compute_source_stats(tmp_path)
    assert stats.max_mtime == 0.0
    assert stats.file_count == 0


def test_compute_source_stats_file_count_detects_addition(tmp_path):
    (tmp_path / "a.py").write_text("# a")
    stats1 = _compute_source_stats(tmp_path)
    (tmp_path / "b.py").write_text("# b")
    stats2 = _compute_source_stats(tmp_path)
    assert stats2.file_count == stats1.file_count + 1


def test_compute_source_stats_file_count_detects_deletion(tmp_path):
    (tmp_path / "a.py").write_text("# a")
    (tmp_path / "b.py").write_text("# b")
    stats1 = _compute_source_stats(tmp_path)
    (tmp_path / "b.py").unlink()
    stats2 = _compute_source_stats(tmp_path)
    assert stats2.file_count == stats1.file_count - 1


# ---------------------------------------------------------------------------
# load / save roundtrip
# ---------------------------------------------------------------------------


def _make_pkg(version: str = "1.0.0") -> PackageInfo:
    return PackageInfo(
        name="testpkg",
        version=version,
        modules=[
            ModuleInfo(name="testpkg.core", functions=[FunctionInfo(name="f")]),
        ],
    )


def test_save_then_load(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("libcontext.cache.sys.platform", "linux")

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "mod.py").write_text("# code")

    pkg = _make_pkg()
    save(pkg, src_dir)

    result = load("testpkg", "1.0.0", src_dir)
    assert result is not None
    assert result.name == "testpkg"
    assert result.version == "1.0.0"
    assert len(result.modules) == 1
    assert result.modules[0].functions[0].name == "f"


def test_load_miss_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("libcontext.cache.sys.platform", "linux")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    assert load("nonexistent", "1.0.0", src_dir) is None


def test_load_version_mismatch(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("libcontext.cache.sys.platform", "linux")

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "mod.py").write_text("# code")

    pkg = _make_pkg("1.0.0")
    save(pkg, src_dir)

    # Query with different version — file won't exist
    result = load("testpkg", "2.0.0", src_dir)
    assert result is None


def test_load_mtime_changed(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("libcontext.cache.sys.platform", "linux")

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "mod.py").write_text("# code")

    pkg = _make_pkg()
    save(pkg, src_dir)

    # Modify source file after cache was saved
    time.sleep(0.05)
    (src_dir / "mod.py").write_text("# changed")

    result = load("testpkg", "1.0.0", src_dir)
    assert result is None


def test_load_file_count_changed(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("libcontext.cache.sys.platform", "linux")

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "mod.py").write_text("# code")

    pkg = _make_pkg()
    save(pkg, src_dir)

    # Add a new source file
    (src_dir / "new.py").write_text("# new")

    result = load("testpkg", "1.0.0", src_dir)
    assert result is None


def test_load_corrupted_json(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("libcontext.cache.sys.platform", "linux")

    cache_dir = _get_cache_dir()
    cache_file = cache_dir / _cache_filename("testpkg", "1.0.0")
    cache_file.write_text("not json", encoding="utf-8")

    src_dir = tmp_path / "src"
    src_dir.mkdir()

    result = load("testpkg", "1.0.0", src_dir)
    assert result is None
    assert not cache_file.exists()


def test_load_incompatible_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("libcontext.cache.sys.platform", "linux")

    cache_dir = _get_cache_dir()
    cache_file = cache_dir / _cache_filename("testpkg", "1.0.0")
    bad_envelope = {"schema_version": 999, "generator": "libcontext", "data": {}}
    cache_file.write_text(json.dumps(bad_envelope), encoding="utf-8")

    src_dir = tmp_path / "src"
    src_dir.mkdir()

    result = load("testpkg", "1.0.0", src_dir)
    assert result is None
    assert not cache_file.exists()


def test_load_no_cache_meta(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("libcontext.cache.sys.platform", "linux")

    cache_dir = _get_cache_dir()
    cache_file = cache_dir / _cache_filename("testpkg", "1.0.0")
    envelope = _serialize_envelope({"name": "testpkg", "version": "1.0.0"})
    cache_file.write_text(json.dumps(envelope), encoding="utf-8")

    src_dir = tmp_path / "src"
    src_dir.mkdir()

    result = load("testpkg", "1.0.0", src_dir)
    assert result is None


# ---------------------------------------------------------------------------
# _evict_oldest
# ---------------------------------------------------------------------------


def test_evict_oldest_removes_excess(tmp_path):
    for i in range(_MAX_CACHE_ENTRIES + 1):
        f = tmp_path / f"pkg{i:03d}.json"
        f.write_text("{}")
        # Slight mtime separation
        time.sleep(0.001)

    _evict_oldest(tmp_path)

    remaining = list(tmp_path.glob("*.json"))
    assert len(remaining) == _MAX_CACHE_ENTRIES


def test_evict_oldest_no_action_under_limit(tmp_path):
    for i in range(10):
        (tmp_path / f"pkg{i}.json").write_text("{}")

    _evict_oldest(tmp_path)

    remaining = list(tmp_path.glob("*.json"))
    assert len(remaining) == 10


# ---------------------------------------------------------------------------
# clear_all
# ---------------------------------------------------------------------------


def test_clear_all(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("libcontext.cache.sys.platform", "linux")

    cache_dir = _get_cache_dir()
    (cache_dir / "a.json").write_text("{}")
    (cache_dir / "b.json").write_text("{}")

    count = clear_all()
    assert count == 2
    assert not list(cache_dir.glob("*.json"))


def test_clear_all_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr("libcontext.cache.sys.platform", "linux")
    _get_cache_dir()

    count = clear_all()
    assert count == 0


# ---------------------------------------------------------------------------
# _cache_filename
# ---------------------------------------------------------------------------


def test_cache_filename():
    assert _cache_filename("requests", "2.31.0") == "requests-2.31.0.json"
    assert _cache_filename("mypkg", None) == "mypkg-unknown.json"
