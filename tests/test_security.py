"""Tests for the _security module."""

from __future__ import annotations

from pathlib import Path

from libcontext._security import (
    DEFAULT_MAX_OUTPUT_CHARS,
    DEFAULT_MAX_SEARCH_RESULTS,
    MAX_JSON_INPUT_BYTES,
    MAX_SOURCE_FILE_BYTES,
    check_file_size,
    escape_marker_name,
    is_within_boundary,
    sanitize_filename,
    truncate_output,
)

# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------


def test_sanitize_safe_name():
    assert sanitize_filename("requests") == "requests"


def test_sanitize_version_dots():
    assert sanitize_filename("2.31.0") == "2.31.0"


def test_sanitize_path_traversal():
    result = sanitize_filename("../../etc/passwd")
    assert "/" not in result
    # Directory separators are stripped; the result is a flat filename
    assert result == ".._.._etc_passwd"


def test_sanitize_null_bytes():
    result = sanitize_filename("pkg\x00name")
    assert "\x00" not in result


def test_sanitize_special_characters():
    result = sanitize_filename("pkg<>|:name")
    assert "<" not in result
    assert ">" not in result


def test_sanitize_empty_string():
    assert sanitize_filename("") == "_unnamed"


def test_sanitize_only_special_chars():
    assert sanitize_filename("///") == "_unnamed"


def test_sanitize_long_name():
    long_name = "a" * 300
    result = sanitize_filename(long_name)
    assert len(result) <= 200


def test_sanitize_consecutive_underscores():
    result = sanitize_filename("a!!!b")
    assert "__" not in result


# ---------------------------------------------------------------------------
# escape_marker_name
# ---------------------------------------------------------------------------


def test_escape_marker_double_dash():
    assert "--" not in escape_marker_name("pkg--name")


def test_escape_marker_gt():
    assert ">" not in escape_marker_name("pkg>name")


def test_escape_marker_lt():
    assert "<" not in escape_marker_name("pkg<name")


def test_escape_marker_safe_name():
    assert escape_marker_name("requests") == "requests"


# ---------------------------------------------------------------------------
# is_within_boundary
# ---------------------------------------------------------------------------


def test_within_boundary_child(tmp_path: Path):
    child = tmp_path / "sub" / "file.py"
    child.parent.mkdir(parents=True, exist_ok=True)
    child.touch()
    assert is_within_boundary(child, tmp_path) is True


def test_within_boundary_same(tmp_path: Path):
    assert is_within_boundary(tmp_path, tmp_path) is True


def test_within_boundary_outside(tmp_path: Path):
    other = tmp_path.parent / "other_dir"
    other.mkdir(exist_ok=True)
    assert is_within_boundary(other, tmp_path) is False


def test_within_boundary_nonexistent_path(tmp_path: Path):
    fake = tmp_path / "nonexistent" / "deep" / "file.py"
    assert is_within_boundary(fake, tmp_path) is True


def test_within_boundary_symlink_escape(tmp_path: Path):
    """Symlink pointing outside the boundary is rejected."""
    target = tmp_path.parent / "escape_target.txt"
    target.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        # Skip on systems where symlinks aren't supported
        return
    assert is_within_boundary(link, tmp_path) is False


# ---------------------------------------------------------------------------
# check_file_size
# ---------------------------------------------------------------------------


def test_check_file_size_small(tmp_path: Path):
    f = tmp_path / "small.py"
    f.write_text("x = 1")
    assert check_file_size(f) is True


def test_check_file_size_exceeds_limit(tmp_path: Path):
    f = tmp_path / "big.py"
    f.write_text("x = 1")
    assert check_file_size(f, limit=1) is False


def test_check_file_size_nonexistent(tmp_path: Path):
    f = tmp_path / "missing.py"
    assert check_file_size(f) is False


def test_check_file_size_at_limit(tmp_path: Path):
    f = tmp_path / "exact.py"
    f.write_bytes(b"x" * 100)
    assert check_file_size(f, limit=100) is True


# ---------------------------------------------------------------------------
# truncate_output
# ---------------------------------------------------------------------------


def test_truncate_short_text():
    text = "Hello, world!"
    assert truncate_output(text) == text


def test_truncate_unlimited():
    text = "x" * 200_000
    assert truncate_output(text, limit=0) == text


def test_truncate_long_text():
    text = "Line one\nLine two\n" * 10_000
    result = truncate_output(text, limit=500)
    assert len(result) < len(text)
    assert "truncated" in result.lower()


def test_truncate_cuts_at_newline():
    lines = "\n".join(f"Line {i}" for i in range(100))
    result = truncate_output(lines, limit=50)
    assert "truncated" in result.lower()
    # Should not break mid-line
    for line in result.split("\n"):
        if "truncated" in line.lower() or "---" in line or "⚠" in line:
            continue
        assert not line or line.startswith("Line")


def test_truncate_very_small_limit():
    text = "A" * 500
    result = truncate_output(text, limit=100)
    assert "truncated" in result.lower()


# ---------------------------------------------------------------------------
# Constants are sane
# ---------------------------------------------------------------------------


def test_max_source_file_bytes():
    assert MAX_SOURCE_FILE_BYTES == 10 * 1024 * 1024


def test_default_max_output_chars():
    assert DEFAULT_MAX_OUTPUT_CHARS == 120_000


def test_default_max_search_results():
    assert DEFAULT_MAX_SEARCH_RESULTS == 100


def test_max_json_input_bytes():
    assert MAX_JSON_INPUT_BYTES == 50 * 1024 * 1024
