"""Markdown renderer — converts PackageInfo into LLM-optimized context.

Produces a structured Markdown document designed to give GitHub Copilot
(or any LLM) the best possible understanding of a library's public API.

The output format prioritises:
- Complete function/method signatures with type hints
- Concise docstrings (first paragraph only by default)
- Clear module hierarchy for correct import generation
- Compact representation to maximise useful content within context limits
"""

from __future__ import annotations

from .inspector import is_public_member
from .models import (
    ClassInfo,
    FunctionInfo,
    ModuleInfo,
    PackageInfo,
    ParameterInfo,
    VariableInfo,
)

# ---------------------------------------------------------------------------
# Parameter & signature formatting
# ---------------------------------------------------------------------------


def _format_param(param: ParameterInfo) -> str:
    """Format a single parameter for display in a signature."""
    parts: list[str] = []

    parts.append(param.name)

    if param.annotation:
        parts.append(f": {param.annotation}")

    if param.default is not None:
        parts.append(f" = {param.default}")

    return "".join(parts)


def _format_signature(func: FunctionInfo, *, compact: bool = False) -> str:
    """Build a human-readable function signature string.

    Args:
        func: The function to format.
        compact: If True, omit ``self``/``cls`` and decorators.
    """
    # Filter implicit params
    params = func.parameters
    if compact:
        params = [p for p in params if p.name not in ("self", "cls")]

    # Detect positional-only / keyword-only boundaries
    formatted_parts: list[str] = []
    prev_kind: str | None = None

    for param in params:
        # Insert / separator after positional-only params
        if prev_kind == "POSITIONAL_ONLY" and param.kind != "POSITIONAL_ONLY":
            formatted_parts.append("/")

        # Insert * separator before keyword-only (when no *args)
        if param.kind == "KEYWORD_ONLY" and prev_kind not in (
            "VAR_POSITIONAL",
            "KEYWORD_ONLY",
        ):
            formatted_parts.append("*")

        formatted_parts.append(_format_param(param))
        prev_kind = param.kind

    # Trailing / if ALL params are positional-only
    if params and all(p.kind == "POSITIONAL_ONLY" for p in params):
        formatted_parts.append("/")

    params_str = ", ".join(formatted_parts)
    prefix = "async def" if func.is_async else "def"
    ret = f" -> {func.return_annotation}" if func.return_annotation else ""

    return f"{prefix} {func.name}({params_str}){ret}"


def _first_paragraph(text: str | None) -> str | None:
    """Extract the first paragraph of a docstring."""
    if not text:
        return None
    lines: list[str] = []
    for line in text.strip().splitlines():
        stripped = line.strip()
        if not stripped and lines:
            break
        if stripped:
            lines.append(stripped)
    return " ".join(lines) if lines else None


# ---------------------------------------------------------------------------
# Component renderers
# ---------------------------------------------------------------------------


def _render_variable(var: VariableInfo) -> str:
    """Render a variable/constant as a Markdown list item."""
    parts = [f"`{var.name}"]
    if var.annotation:
        parts.append(f": {var.annotation}")
    if var.value is not None:
        # Truncate very long values
        val = var.value if len(var.value) <= 80 else var.value[:77] + "..."
        parts.append(f" = {val}")
    parts.append("`")
    return f"- {''.join(parts)}"


def _render_function(func: FunctionInfo, *, heading: str = "-") -> str:
    """Render a function as a Markdown block."""
    lines: list[str] = []

    # Decorators (only non-trivial ones)
    notable_decorators = [
        d
        for d in func.decorators
        if d not in ("property", "classmethod", "staticmethod")
    ]
    for dec in notable_decorators:
        lines.append(f"{heading} `@{dec}`")

    sig = _format_signature(func, compact=True)
    lines.append(f"{heading} `{sig}`")

    doc = _first_paragraph(func.docstring)
    if doc:
        indent = "  " if heading == "-" else ""
        lines.append(f"{indent}{doc}")

    return "\n".join(lines)


def _render_class(cls: ClassInfo) -> str:
    """Render a class as a Markdown section."""
    lines: list[str] = []

    # Class header
    bases_str = f"({', '.join(cls.bases)})" if cls.bases else ""
    dec_str = ""
    for dec in cls.decorators:
        dec_str += f"`@{dec}` "
    lines.append(f"#### {dec_str}`class {cls.name}{bases_str}`")

    # Docstring
    doc = _first_paragraph(cls.docstring)
    if doc:
        lines.append("")
        lines.append(doc)

    # Class variables (public only)
    public_vars = [v for v in cls.class_variables if is_public_member(v.name)]
    if public_vars:
        lines.append("")
        lines.append("**Attributes:**")
        for var in public_vars:
            lines.append(_render_variable(var))

    # Methods — include public + useful dunders
    visible_methods = [
        m for m in cls.methods if is_public_member(m.name, is_method=True)
    ]
    if visible_methods:
        lines.append("")
        lines.append("**Methods:**")
        for method in visible_methods:
            lines.append(_render_function(method))

    # Inner classes
    public_inner = [c for c in cls.inner_classes if is_public_member(c.name)]
    for inner in public_inner:
        lines.append("")
        lines.append(_render_class(inner))

    return "\n".join(lines)


def _render_module(module: ModuleInfo) -> str:
    """Render a module as a Markdown section."""
    lines: list[str] = []

    lines.append(f"### `{module.name}`")

    doc = _first_paragraph(module.docstring)
    if doc:
        lines.append("")
        lines.append(doc)

    # Determine public API boundary
    exports = set(module.all_exports) if module.all_exports is not None else None

    def _is_public(name: str) -> bool:
        if exports is not None:
            return name in exports
        return is_public_member(name)

    # Classes
    public_classes = [c for c in module.classes if _is_public(c.name)]
    for cls in public_classes:
        lines.append("")
        lines.append(_render_class(cls))

    # Functions
    public_functions = [f for f in module.functions if _is_public(f.name)]
    if public_functions:
        lines.append("")
        lines.append("**Functions:**")
        for func in public_functions:
            lines.append("")
            lines.append(_render_function(func))

    # Constants (UPPER_CASE variables)
    public_constants = [
        v for v in module.variables if _is_public(v.name) and v.name.isupper()
    ]
    if public_constants:
        lines.append("")
        lines.append("**Constants:**")
        for var in public_constants:
            lines.append(_render_variable(var))

    # Module-level variables (non-constant public variables)
    public_vars = [
        v for v in module.variables if _is_public(v.name) and not v.name.isupper()
    ]
    if public_vars:
        lines.append("")
        lines.append("**Module Variables:**")
        for var in public_vars:
            lines.append(_render_variable(var))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Markers used to delimit auto-generated sections in existing files
BEGIN_MARKER = "<!-- BEGIN LIBCONTEXT: {name} -->"
END_MARKER = "<!-- END LIBCONTEXT: {name} -->"


def render_package(
    package: PackageInfo,
    *,
    include_readme: bool = True,
    max_readme_lines: int = 100,
    extra_context: str | None = None,
) -> str:
    """Render a :class:`PackageInfo` as Markdown optimised for LLM context.

    Args:
        package: The collected package information.
        include_readme: Whether to include the README overview section.
        max_readme_lines: Truncate the README after this many lines.
        extra_context: Additional free-form context to append (e.g. from
            ``[tool.libcontext] extra_context``).

    Returns:
        A complete Markdown string ready to be written to a file or stdout.
    """
    lines: list[str] = []

    # --- Header --------------------------------------------------------
    version = f" v{package.version}" if package.version else ""
    lines.append(f"# {package.name}{version} — API Reference")
    lines.append("")

    if package.summary:
        lines.append(f"> {package.summary}")
        lines.append("")

    # --- README overview -----------------------------------------------
    if include_readme and package.readme:
        lines.append("## Overview")
        lines.append("")
        readme_lines = package.readme.strip().splitlines()
        if len(readme_lines) > max_readme_lines:
            readme_lines = readme_lines[:max_readme_lines]
            readme_lines.append("")
            readme_lines.append("*(README truncated)*")
        lines.extend(readme_lines)
        lines.append("")

    # --- Extra context -------------------------------------------------
    if extra_context:
        lines.append("## Notes")
        lines.append("")
        lines.append(extra_context.strip())
        lines.append("")

    # --- API Reference -------------------------------------------------
    modules = package.non_empty_modules
    if modules:
        lines.append("## API Reference")
        lines.append("")

        for module in modules:
            lines.append(_render_module(module))
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def inject_into_file(
    content: str,
    package_name: str,
    existing: str | None = None,
) -> str:
    """Inject generated context into an existing file using markers.

    If the file already contains a ``<!-- BEGIN LIBCONTEXT: {name} -->`` /
    ``<!-- END LIBCONTEXT: {name} -->`` block for this package, that block
    is replaced.  Otherwise, the content is appended at the end.

    Args:
        content: The generated Markdown context.
        package_name: Package name used in the markers.
        existing: Current file contents (if any).

    Returns:
        The updated file contents.
    """
    begin = BEGIN_MARKER.format(name=package_name)
    end = END_MARKER.format(name=package_name)
    block = f"{begin}\n{content}\n{end}"

    if existing is None:
        return block

    begin_idx = existing.find(begin)
    end_idx = existing.find(end)

    if begin_idx != -1 and end_idx != -1 and begin_idx < end_idx:
        # Well-formed existing section — replace it
        before = existing[:begin_idx]
        after = existing[end_idx + len(end) :]
        return f"{before}{block}{after}"

    if begin_idx != -1 or end_idx != -1:
        # Malformed markers (only one present, or reversed order).
        # Remove any stale markers before appending the clean block.
        cleaned = existing
        if begin_idx != -1:
            cleaned = cleaned[:begin_idx] + cleaned[begin_idx + len(begin) :]
        # Recalculate end_idx after potential removal
        end_idx_clean = cleaned.find(end)
        if end_idx_clean != -1:
            cleaned = cleaned[:end_idx_clean] + cleaned[end_idx_clean + len(end) :]
        existing = cleaned

    # Append
    separator = "\n\n" if existing.strip() else ""
    return f"{existing.rstrip()}{separator}{block}\n"
