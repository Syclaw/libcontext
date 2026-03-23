"""Internal security primitives for libcontext.

Centralises input sanitisation, path validation, and output size guards
so that security invariants are enforced in one place rather than scattered
across modules.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Filename sanitisation (cache, output files)
# ---------------------------------------------------------------------------

_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]")

# Max length for a single path component (conservative for all OS)
_MAX_FILENAME_LEN = 200


def sanitize_filename(raw: str) -> str:
    """Replace characters unsafe for filenames with underscores.

    Prevents path traversal (``../``), null bytes, and special characters
    from reaching the filesystem.  The result is always a flat filename
    with no directory separators.

    Args:
        raw: Untrusted input (e.g. a package name or version string).

    Returns:
        A sanitised string safe for use as a filename component.
    """
    sanitized = _SAFE_FILENAME_RE.sub("_", raw)
    # Collapse consecutive underscores
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized:
        sanitized = "_unnamed"
    if len(sanitized) > _MAX_FILENAME_LEN:
        sanitized = sanitized[:_MAX_FILENAME_LEN]
    return sanitized


# ---------------------------------------------------------------------------
# HTML marker escaping
# ---------------------------------------------------------------------------


def escape_marker_name(name: str) -> str:
    """Escape a name for safe use inside HTML comments.

    HTML comments end at ``-->``, so we must neutralise ``--`` and ``>``
    sequences.  Also strips ``<`` to prevent tag injection if the
    surrounding context is parsed by a Markdown renderer.

    Args:
        name: Untrusted package/module name.

    Returns:
        Escaped string safe for embedding inside ``<!-- ... -->``.
    """
    # Order matters: replace -- before stripping individual chars
    escaped = name.replace("--", "__")
    escaped = escaped.replace(">", "_")
    escaped = escaped.replace("<", "_")
    return escaped


# ---------------------------------------------------------------------------
# Symlink / path boundary validation
# ---------------------------------------------------------------------------


def is_within_boundary(file_path: Path, root: Path) -> bool:
    """Check that *file_path* resolves to a location inside *root*.

    Catches symlink escapes: a symlink inside the package pointing to
    ``/etc/shadow`` would resolve outside *root* and be rejected.

    Both paths are resolved to eliminate ``..`` components and follow
    any intermediate symlinks before the comparison.

    Args:
        file_path: The path to validate (may be a symlink).
        root: The trusted boundary directory.

    Returns:
        True if the resolved *file_path* is inside (or equal to) *root*.
    """
    try:
        resolved = file_path.resolve()
        root_resolved = root.resolve()
        resolved.relative_to(root_resolved)
        return True
    except (ValueError, OSError):
        return False


# ---------------------------------------------------------------------------
# File size guard
# ---------------------------------------------------------------------------

# 10 MiB — larger Python source files are almost certainly generated code
# or data dumps, not useful API surface.
MAX_SOURCE_FILE_BYTES = 10 * 1024 * 1024


def check_file_size(file_path: Path, limit: int = MAX_SOURCE_FILE_BYTES) -> bool:
    """Return True if the file is within the size limit.

    Args:
        file_path: Path to check.
        limit: Maximum allowed size in bytes.

    Returns:
        True if the file size is at or below *limit*.
    """
    try:
        return file_path.stat().st_size <= limit
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Output size guard
# ---------------------------------------------------------------------------

# Conservative default: ~120k chars ≈ ~30k tokens.  Enough for the largest
# single-module renders while preventing multi-megabyte full-package dumps
# from saturating an LLM context window.
DEFAULT_MAX_OUTPUT_CHARS = 120_000

_TRUNCATION_NOTICE = (
    "\n\n---\n"
    "⚠ Output truncated ({chars:,} chars).  "
    "Use `--overview` then `--module <name>` for progressive discovery."
)


def truncate_output(text: str, limit: int = DEFAULT_MAX_OUTPUT_CHARS) -> str:
    """Truncate *text* to *limit* characters, appending a notice if cut.

    Cuts at the last newline before the limit so that Markdown blocks are
    not broken mid-line.

    Args:
        text: The rendered output.
        limit: Maximum character count (0 = unlimited).

    Returns:
        The original text if within limits, otherwise truncated with notice.
    """
    if limit <= 0 or len(text) <= limit:
        return text

    # Reserve room for the notice
    cut_point = limit - 200
    if cut_point < 0:
        cut_point = limit

    # Find last newline before cut_point for a clean break
    nl = text.rfind("\n", 0, cut_point)
    if nl > 0:
        cut_point = nl

    notice = _TRUNCATION_NOTICE.format(chars=len(text))
    return text[:cut_point] + notice


# ---------------------------------------------------------------------------
# Search result cap
# ---------------------------------------------------------------------------

DEFAULT_MAX_SEARCH_RESULTS = 100


# ---------------------------------------------------------------------------
# JSON input size guard
# ---------------------------------------------------------------------------

# 50 MiB — generous limit for API snapshot JSON files.
MAX_JSON_INPUT_BYTES = 50 * 1024 * 1024
