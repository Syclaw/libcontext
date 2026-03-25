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

from dataclasses import dataclass

from ._security import (
    DEFAULT_MAX_SEARCH_RESULTS,
    escape_marker_name,
    truncate_output,
)
from .inspector import is_public_member
from .models import (
    ClassInfo,
    DiffResult,
    FunctionInfo,
    ModuleInfo,
    PackageInfo,
    ParameterInfo,
    VariableInfo,
)

# ---------------------------------------------------------------------------
# Overload detection & grouping
# ---------------------------------------------------------------------------

_OVERLOAD_DECORATORS = frozenset(
    {
        "overload",
        "typing.overload",
        "typing_extensions.overload",
    }
)


def _is_overload(decorator: str) -> bool:
    """Check if a decorator string represents ``@typing.overload``."""
    return decorator in _OVERLOAD_DECORATORS


def _has_overload(func: FunctionInfo) -> bool:
    """Check if a function is decorated with ``@overload``."""
    return any(_is_overload(d) for d in func.decorators)


@dataclass
class _OverloadGroup:
    """A group of overloaded function signatures with a shared identity."""

    name: str
    qualname: str
    overloads: list[FunctionInfo]
    implementation: FunctionInfo | None


def _group_overloads(
    functions: list[FunctionInfo],
) -> list[FunctionInfo | _OverloadGroup]:
    """Group ``@overload``-decorated functions by name.

    Non-overloaded functions pass through unchanged. For each set of
    same-named functions where at least one has ``@overload``, produces
    an ``_OverloadGroup``.

    Args:
        functions: Functions from a single scope (module or class).

    Returns:
        Mixed list of standalone functions and overload groups,
        preserving the order of first appearance.
    """
    groups: dict[str, _OverloadGroup] = {}
    order: list[str | FunctionInfo] = []

    for func in functions:
        if _has_overload(func):
            if func.name not in groups:
                groups[func.name] = _OverloadGroup(
                    name=func.name,
                    qualname=func.qualname,
                    overloads=[],
                    implementation=None,
                )
                order.append(func.name)
            groups[func.name].overloads.append(func)
        else:
            if func.name in groups:
                groups[func.name].implementation = func
            else:
                order.append(func)

    result: list[FunctionInfo | _OverloadGroup] = []
    for entry in order:
        if isinstance(entry, str):
            result.append(groups[entry])
        else:
            result.append(entry)
    return result


def _resolve_overload_docstring(group: _OverloadGroup) -> str | None:
    """Select the best docstring for an overload group.

    Priority:
    1. Implementation docstring (most complete, matches Pylance/Sphinx)
    2. First overload with a non-None docstring
    3. None
    """
    if group.implementation and group.implementation.docstring:
        return _first_paragraph(group.implementation.docstring)

    for overload in group.overloads:
        doc = _first_paragraph(overload.docstring)
        if doc:
            return doc

    return None


_VALID_KINDS = frozenset({"class", "function", "variable", "alias"})
_DOCSTRING_MATCH_PREVIEW_LEN = 60


@dataclass
class _SearchHit:
    """A single search match found during package traversal."""

    kind: str  # "class", "method", "function", "variable", "alias"
    module: str
    name: str
    match_in: str  # "name" or "docstring"
    signature: str
    class_name: str | None = None
    docstring: str | None = None
    overload_signatures: list[str] | None = None


def _matches(name: str, docstring: str | None, query_lower: str) -> str | None:
    """Check if an entity matches the search query.

    Returns:
        ``"name"`` if matched on name, ``"docstring"`` if matched on
        first-paragraph docstring, ``None`` if no match.
    """
    if query_lower in name.lower():
        return "name"
    first_para = _first_paragraph(docstring)
    if first_para and query_lower in first_para.lower():
        return "docstring"
    return None


def _format_docstring_match(docstring: str | None) -> str:
    """Format a docstring match annotation."""
    para = _first_paragraph(docstring) or ""
    preview = para[:_DOCSTRING_MATCH_PREVIEW_LEN]
    if len(para) > _DOCSTRING_MATCH_PREVIEW_LEN:
        preview += "..."
    preview = preview.replace('"', "'")
    return f'*(matched in docstring: "{preview}")*'


def _is_public_name(name: str, exports: set[str] | None) -> bool:
    """Check if a name is public, respecting __all__ when present."""
    if exports is not None:
        return name in exports
    return is_public_member(name)


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


def _render_type_alias(alias: VariableInfo) -> str:
    """Render a type alias as a Markdown list item.

    Uses the original source syntax (PEP 613 or PEP 695) to match
    what the developer will find in the code.
    """
    if alias.annotation is not None:
        # PEP 613: X: TypeAlias = Union[A, B]
        # Omit TypeAlias annotation — the section heading provides context
        val = alias.value or "..."
        return f"- `{alias.name} = {val}`"

    # PEP 695: value contains the full statement from ast.unparse(node)
    val = alias.value or "..."
    return f"- `{val}`"


def _render_overload_group(
    group: _OverloadGroup,
    *,
    heading: str = "-",
) -> str:
    """Render an overload group as a single Markdown block.

    Shows all overload signatures in one code block, hides the
    implementation signature, and uses the best available docstring.
    """
    lines: list[str] = []

    # Detect shared classmethod/staticmethod decorators
    first = group.overloads[0]
    shared_decs: list[str] = []
    if first.is_classmethod:
        shared_decs.append("`@classmethod`")
    elif first.is_staticmethod:
        shared_decs.append("`@staticmethod`")

    dec_prefix = " ".join(shared_decs) + " " if shared_decs else ""
    lines.append(f"{heading} {dec_prefix}`{group.name}` *(overloaded)*")

    # Code block with all overload signatures
    sig_lines: list[str] = []
    for overload in group.overloads:
        non_trivial = [
            d
            for d in overload.decorators
            if d not in ("property", "classmethod", "staticmethod")
            and not _is_overload(d)
        ]
        for dec in non_trivial:
            sig_lines.append(f"@{dec}")
        sig_lines.append(_format_signature(overload, compact=True))

    lines.append("")
    indent = "  " if heading == "-" else ""
    lines.append(f"{indent}```python")
    for sig_line in sig_lines:
        lines.append(f"{indent}{sig_line}")
    lines.append(f"{indent}```")

    doc = _resolve_overload_docstring(group)
    if doc:
        lines.append(f"{indent}{doc}")

    return "\n".join(lines)


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

    # Type aliases (public only)
    class_aliases = [
        v for v in cls.class_variables if is_public_member(v.name) and v.is_type_alias
    ]
    if class_aliases:
        lines.append("")
        lines.append("**Type Aliases:**")
        for alias in class_aliases:
            lines.append(_render_type_alias(alias))

    # Class variables (public only, excluding type aliases)
    public_vars = [
        v
        for v in cls.class_variables
        if is_public_member(v.name) and not v.is_type_alias
    ]
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
        for item in _group_overloads(visible_methods):
            if isinstance(item, _OverloadGroup):
                lines.append(_render_overload_group(item))
            else:
                lines.append(_render_function(item))

    # Inner classes
    public_inner = [c for c in cls.inner_classes if is_public_member(c.name)]
    for inner in public_inner:
        lines.append("")
        lines.append(_render_class(inner))

    return "\n".join(lines)


def render_module(module: ModuleInfo) -> str:
    """Render a single module as a Markdown section.

    Produces a self-contained Markdown block with classes, functions,
    constants, and module-level variables.  Suitable for injecting a
    single module's API into an LLM conversation.

    Args:
        module: The module to render.

    Returns:
        Markdown string for this module.
    """
    lines: list[str] = []

    lines.append(f"### `{module.name}`")

    doc = _first_paragraph(module.docstring)
    if doc:
        lines.append("")
        lines.append(doc)

    # Determine public API boundary
    exports = set(module.all_exports) if module.all_exports is not None else None

    # Categorise public variables in a single pass
    type_aliases: list[VariableInfo] = []
    public_constants: list[VariableInfo] = []
    public_vars: list[VariableInfo] = []
    for v in module.variables:
        if not _is_public_name(v.name, exports):
            continue
        if v.is_type_alias:
            type_aliases.append(v)
        elif v.name.isupper():
            public_constants.append(v)
        else:
            public_vars.append(v)

    if type_aliases:
        lines.append("")
        lines.append("**Type Aliases:**")
        for alias in type_aliases:
            lines.append(_render_type_alias(alias))

    # Classes
    public_classes = [c for c in module.classes if _is_public_name(c.name, exports)]
    for cls in public_classes:
        lines.append("")
        lines.append(_render_class(cls))

    # Functions
    public_functions = [f for f in module.functions if _is_public_name(f.name, exports)]
    if public_functions:
        lines.append("")
        lines.append("**Functions:**")
        for item in _group_overloads(public_functions):
            lines.append("")
            if isinstance(item, _OverloadGroup):
                lines.append(_render_overload_group(item))
            else:
                lines.append(_render_function(item))

    if public_constants:
        lines.append("")
        lines.append("**Constants:**")
        for var in public_constants:
            lines.append(_render_variable(var))

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


def render_package_overview(package: PackageInfo) -> str:
    """Render a compact structural overview of a package.

    Lists each module with its public class and function names (no full
    signatures).  Designed for progressive disclosure: use this to
    understand a package's shape, then request per-module detail.

    Args:
        package: The collected package information.

    Returns:
        A compact Markdown overview.
    """
    lines: list[str] = []

    version = f" v{package.version}" if package.version else ""
    lines.append(f"# {package.name}{version}")
    lines.append("")

    if package.summary:
        lines.append(f"> {package.summary}")
        lines.append("")

    modules = package.non_empty_modules
    if not modules:
        lines.append("*No public modules found.*")
        return "\n".join(lines)

    lines.append("## Modules")
    lines.append("")

    for module in modules:
        exports = set(module.all_exports) if module.all_exports is not None else None

        class_names = [
            c.name for c in module.classes if _is_public_name(c.name, exports)
        ]
        public_functions = [
            f for f in module.functions if _is_public_name(f.name, exports)
        ]
        seen_names: set[str] = set()
        overloaded_names = {f.name for f in public_functions if _has_overload(f)}
        func_entries: list[str] = []
        for func in public_functions:
            if func.name in seen_names:
                continue
            seen_names.add(func.name)
            suffix = " (overloaded)" if func.name in overloaded_names else ""
            func_entries.append(f"{func.name}(){suffix}")

        parts: list[str] = []
        if class_names:
            parts.append(", ".join(class_names))
        if func_entries:
            parts.append(", ".join(func_entries))

        suffix = f" — {'; '.join(parts)}" if parts else ""
        lines.append(f"- **`{module.name}`**{suffix}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Search — shared traversal
# ---------------------------------------------------------------------------


def _collect_search_hits(
    package: PackageInfo,
    query: str,
    kind: str | None,
) -> list[_SearchHit]:
    """Traverse a package and collect all entities matching *query*.

    Shared implementation for both Markdown and structured search output.

    Args:
        package: The collected package information.
        query: Search term (case-insensitive substring match).
        kind: Filter by entity type, or ``None`` for all types.

    Returns:
        List of ``_SearchHit`` in traversal order.
    """
    query_lower = query.lower()
    hits: list[_SearchHit] = []

    for mod in package.non_empty_modules:
        exports = set(mod.all_exports) if mod.all_exports is not None else None

        if kind is None or kind in ("class", "function"):
            for cls in mod.classes:
                if not _is_public_name(cls.name, exports):
                    continue
                _collect_class_hits(mod, cls, query_lower, kind, hits)

        if kind is None or kind == "function":
            _collect_function_hits(mod, exports, query_lower, hits)

        if kind in ("variable", "alias"):
            _collect_variable_hits(mod, exports, query_lower, kind, hits)

    return hits


def _collect_class_hits(
    mod: ModuleInfo,
    cls: ClassInfo,
    query_lower: str,
    kind: str | None,
    hits: list[_SearchHit],
) -> None:
    """Collect class and method matches for a single class."""
    if kind is None or kind == "class":
        match_type = _matches(cls.name, cls.docstring, query_lower)
        if match_type:
            bases = f"({', '.join(cls.bases)})" if cls.bases else ""
            hits.append(
                _SearchHit(
                    kind="class",
                    module=mod.name,
                    name=cls.name,
                    match_in=match_type,
                    signature=f"class {cls.name}{bases}",
                    docstring=cls.docstring,
                )
            )

    if kind is None or kind == "function":
        visible = [m for m in cls.methods if is_public_member(m.name, is_method=True)]
        for item in _group_overloads(visible):
            if isinstance(item, _OverloadGroup):
                doc = _resolve_overload_docstring(item)
                match_type = _matches(item.name, doc, query_lower)
                if match_type:
                    hits.append(
                        _SearchHit(
                            kind="method",
                            module=mod.name,
                            name=item.name,
                            match_in=match_type,
                            signature=_format_signature(
                                item.overloads[0], compact=True
                            ),
                            class_name=cls.name,
                            docstring=doc,
                            overload_signatures=[
                                _format_signature(o, compact=True)
                                for o in item.overloads
                            ],
                        )
                    )
            else:
                match_type = _matches(item.name, item.docstring, query_lower)
                if match_type:
                    hits.append(
                        _SearchHit(
                            kind="method",
                            module=mod.name,
                            name=item.name,
                            match_in=match_type,
                            signature=_format_signature(item, compact=True),
                            class_name=cls.name,
                            docstring=item.docstring,
                        )
                    )


def _collect_function_hits(
    mod: ModuleInfo,
    exports: set[str] | None,
    query_lower: str,
    hits: list[_SearchHit],
) -> None:
    """Collect function matches for a module."""
    public_functions = [f for f in mod.functions if _is_public_name(f.name, exports)]
    for item in _group_overloads(public_functions):
        if isinstance(item, _OverloadGroup):
            doc = _resolve_overload_docstring(item)
            match_type = _matches(item.name, doc, query_lower)
            if match_type:
                hits.append(
                    _SearchHit(
                        kind="function",
                        module=mod.name,
                        name=item.name,
                        match_in=match_type,
                        signature=_format_signature(item.overloads[0], compact=False),
                        docstring=doc,
                        overload_signatures=[
                            _format_signature(o, compact=False) for o in item.overloads
                        ],
                    )
                )
        else:
            match_type = _matches(item.name, item.docstring, query_lower)
            if match_type:
                hits.append(
                    _SearchHit(
                        kind="function",
                        module=mod.name,
                        name=item.name,
                        match_in=match_type,
                        signature=_format_signature(item),
                        docstring=item.docstring,
                    )
                )


def _collect_variable_hits(
    mod: ModuleInfo,
    exports: set[str] | None,
    query_lower: str,
    kind: str | None,
    hits: list[_SearchHit],
) -> None:
    """Collect variable/alias matches for a module."""
    for var in mod.variables:
        if not _is_public_name(var.name, exports):
            continue
        is_alias = var.is_type_alias
        if kind == "alias" and not is_alias:
            continue
        if kind == "variable" and is_alias:
            continue
        if query_lower in var.name.lower():
            ann = f": {var.annotation}" if var.annotation else ""
            val = f" = {var.value}" if var.value else ""
            hits.append(
                _SearchHit(
                    kind="alias" if is_alias else "variable",
                    module=mod.name,
                    name=var.name,
                    match_in="name",
                    signature=f"{var.name}{ann}{val}",
                )
            )


# ---------------------------------------------------------------------------
# Search — Markdown output
# ---------------------------------------------------------------------------


def _hit_to_markdown(hit: _SearchHit) -> str:
    """Format a single search hit as a Markdown list item."""
    if hit.kind == "class":
        line = f"- class `{hit.module}.{hit.signature}`"
    elif hit.kind == "method":
        if hit.overload_signatures:
            sigs = "\n  ".join(f"`{s}`" for s in hit.overload_signatures)
            line = (
                f"- method `{hit.module}.{hit.class_name}.{hit.name}`"
                f" (overloaded)\n  {sigs}"
            )
        else:
            line = f"- method `{hit.module}.{hit.class_name}.{hit.signature}`"
    elif hit.kind == "function":
        if hit.overload_signatures:
            sigs = "\n  ".join(f"`{s}`" for s in hit.overload_signatures)
            line = f"- function `{hit.module}.{hit.name}` (overloaded)\n  {sigs}"
        else:
            line = f"- function `{hit.module}.{hit.signature}`"
    else:
        line = f"- variable `{hit.module}.{hit.signature}`"

    if hit.match_in == "docstring":
        line += f"\n  {_format_docstring_match(hit.docstring)}"
    return line


def search_package(
    package: PackageInfo,
    query: str,
    *,
    kind: str | None = None,
    max_results: int = 0,
) -> str:
    """Search for classes, functions, or methods matching a query.

    Performs a case-insensitive substring search across all public names
    and first-paragraph docstrings.

    Args:
        package: The collected package information.
        query: Search term (case-insensitive substring match).
        kind: Filter by entity type. Accepted values:
            ``"class"``, ``"function"``, ``"variable"``, ``"alias"``,
            or ``None`` (all types).
        max_results: Cap the number of results returned.  ``0`` uses the
            default from ``_security.DEFAULT_MAX_SEARCH_RESULTS``.

    Returns:
        Markdown-formatted search results, or a "no matches" message.

    Raises:
        ValueError: If *kind* is not a recognized value.
    """
    if kind is not None and kind not in _VALID_KINDS:
        valid = ", ".join(sorted(_VALID_KINDS))
        msg = f"Invalid kind {kind!r}. Accepted values: {valid}"
        raise ValueError(msg)

    hits = _collect_search_hits(package, query, kind)

    if not hits:
        return f"No matches for '{query}' in {package.name}."

    cap = max_results if max_results > 0 else DEFAULT_MAX_SEARCH_RESULTS
    results = [_hit_to_markdown(h) for h in hits[:cap]]
    if len(hits) > cap:
        omitted = len(hits) - cap
        results.append(
            f"\n*… {omitted} more results omitted. "
            f"Narrow your query or use `--kind` to filter.*"
        )

    return "\n".join(results)


# ---------------------------------------------------------------------------
# Search — structured (JSON) output
# ---------------------------------------------------------------------------


def _hit_to_dict(hit: _SearchHit) -> dict[str, str]:
    """Format a single search hit as a structured dict."""
    entry: dict[str, str] = {
        "kind": hit.kind,
        "module": hit.module,
        "name": hit.name,
        "signature": hit.signature,
        "match_in": hit.match_in,
    }
    if hit.class_name:
        entry["class"] = hit.class_name
    if hit.overload_signatures and len(hit.overload_signatures) > 1:
        entry["overload_count"] = str(len(hit.overload_signatures))
    if hit.match_in == "docstring":
        para = _first_paragraph(hit.docstring) or ""
        entry["docstring_preview"] = para[:_DOCSTRING_MATCH_PREVIEW_LEN]
    return entry


def search_package_structured(
    package: PackageInfo,
    query: str,
    *,
    kind: str | None = None,
    max_results: int = 0,
) -> list[dict[str, str]]:
    """Search and return structured results for JSON output.

    Same matching logic as ``search_package()`` but returns dicts
    instead of Markdown strings.

    Args:
        package: The collected package information.
        query: Search term (case-insensitive substring match).
        kind: Filter by entity type (same values as ``search_package``).
        max_results: Cap the number of results.  ``0`` uses the default.

    Returns:
        List of result dicts with keys: kind, module, name, signature,
        and optionally class, match_in, docstring_preview.

    Raises:
        ValueError: If *kind* is not a recognized value.
    """
    if kind is not None and kind not in _VALID_KINDS:
        valid = ", ".join(sorted(_VALID_KINDS))
        msg = f"Invalid kind {kind!r}. Accepted values: {valid}"
        raise ValueError(msg)

    hits = _collect_search_hits(package, query, kind)
    cap = max_results if max_results > 0 else DEFAULT_MAX_SEARCH_RESULTS
    return [_hit_to_dict(h) for h in hits[:cap]]


def render_package(
    package: PackageInfo,
    *,
    include_readme: bool = True,
    max_readme_lines: int = 100,
    extra_context: str | None = None,
    max_output_chars: int = 0,
) -> str:
    """Render a :class:`PackageInfo` as Markdown optimised for LLM context.

    Args:
        package: The collected package information.
        include_readme: Whether to include the README overview section.
        max_readme_lines: Truncate the README after this many lines.
        extra_context: Additional free-form context to append (e.g. from
            ``[tool.libcontext] extra_context``).
        max_output_chars: Truncate output beyond this many characters.
            ``0`` means unlimited (caller is responsible for size management).

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
            lines.append(render_module(module))
            lines.append("")
            lines.append("---")
            lines.append("")

    output = "\n".join(lines)

    if max_output_chars > 0:
        output = truncate_output(output, limit=max_output_chars)

    return output


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
    safe_name = escape_marker_name(package_name)
    begin = BEGIN_MARKER.format(name=safe_name)
    end = END_MARKER.format(name=safe_name)
    block = f"{begin}\n{content}\n{end}"

    if existing is None:
        return block

    # Search for escaped markers first, then fall back to legacy unescaped
    # markers for backward compatibility with files written before escaping
    # was introduced.
    begin_idx = existing.find(begin)
    end_idx = existing.find(end)

    if begin_idx == -1 or end_idx == -1 or begin_idx >= end_idx:
        legacy_begin = BEGIN_MARKER.format(name=package_name)
        legacy_end = END_MARKER.format(name=package_name)
        if legacy_begin != begin:
            lb_idx = existing.find(legacy_begin)
            le_idx = existing.find(legacy_end)
            if lb_idx != -1 and le_idx != -1 and lb_idx < le_idx:
                # Replace legacy block with new escaped markers
                before = existing[:lb_idx]
                after = existing[le_idx + len(legacy_end) :]
                return f"{before}{block}{after}"

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


# ---------------------------------------------------------------------------
# Diff rendering
# ---------------------------------------------------------------------------


def render_diff(result: DiffResult) -> str:
    """Render a DiffResult as human-readable Markdown.

    Sections appear in order: Breaking Changes, Added, Modified.
    Empty sections are omitted.

    Args:
        result: The diff to render.

    Returns:
        Markdown string, or a "no changes" message if the diff is empty.
    """
    if result.is_empty:
        return "No changes detected."

    lines: list[str] = []
    lines.append(f"# API Diff: {result.package_name}")
    lines.append("")

    if result.old_version or result.new_version:
        old_v = result.old_version or "unknown"
        new_v = result.new_version or "unknown"
        lines.append(f"**{old_v} → {new_v}**")
        lines.append("")

    # --- Breaking Changes ---
    breaking_lines: list[str] = []

    for mod_name in result.removed_modules:
        breaking_lines.append(f"- **Removed module** `{mod_name}`")

    for mod in result.modified_modules:
        for fname in mod.removed_functions:
            breaking_lines.append(f"- **Removed function** `{mod.module_name}.{fname}`")
        for cname in mod.removed_classes:
            breaking_lines.append(f"- **Removed class** `{mod.module_name}.{cname}`")
        for fd in mod.modified_functions:
            if fd.is_breaking:
                for change in fd.changes:
                    if _is_breaking_change_text(change):
                        breaking_lines.append(
                            f"- **{_capitalize(change)}** "
                            f"in `{mod.module_name}.{fd.name}`"
                        )
        for cd in mod.modified_classes:
            if cd.is_breaking:
                for change in cd.changes:
                    if _is_breaking_change_text(change):
                        breaking_lines.append(
                            f"- **{_capitalize(change)}** "
                            f"in `{mod.module_name}.{cd.name}`"
                        )
                for mname in cd.removed_methods:
                    breaking_lines.append(
                        f"- **Removed method** `{mod.module_name}.{cd.name}.{mname}`"
                    )
                for mfd in cd.modified_methods:
                    if mfd.is_breaking:
                        for change in mfd.changes:
                            if _is_breaking_change_text(change):
                                breaking_lines.append(
                                    f"- **{_capitalize(change)}** "
                                    f"in `{mod.module_name}.{cd.name}"
                                    f".{mfd.name}`"
                                )

    if breaking_lines:
        lines.append("## Breaking Changes")
        lines.append("")
        lines.extend(breaking_lines)
        lines.append("")

    # --- Added ---
    added_lines: list[str] = []

    for mod_name in result.added_modules:
        added_lines.append(f"- **Module** `{mod_name}`")

    for mod in result.modified_modules:
        for fname in mod.added_functions:
            added_lines.append(f"- **Function** `{mod.module_name}.{fname}`")
        for cname in mod.added_classes:
            added_lines.append(f"- **Class** `{mod.module_name}.{cname}`")
        for cd in mod.modified_classes:
            for mname in cd.added_methods:
                added_lines.append(
                    f"- **Method** `{mod.module_name}.{cd.name}.{mname}`"
                )

    if added_lines:
        lines.append("## Added")
        lines.append("")
        lines.extend(added_lines)
        lines.append("")

    # --- Modified ---
    modified_lines: list[str] = []

    for mod in result.modified_modules:
        for fd in mod.modified_functions:
            modified_lines.append(f"### `{mod.module_name}.{fd.name}`")
            for change in fd.changes:
                modified_lines.append(f"- {change}")
            modified_lines.append("")

        for cd in mod.modified_classes:
            modified_lines.append(f"### `{mod.module_name}.{cd.name}`")
            for change in cd.changes:
                modified_lines.append(f"- {change}")
            for mfd in cd.modified_methods:
                change_str = ", ".join(mfd.changes)
                modified_lines.append(f"- **method `{mfd.name}`**: {change_str}")
            for vname in cd.added_variables:
                modified_lines.append(f"- added attribute `{vname}`")
            for vname in cd.removed_variables:
                modified_lines.append(f"- removed attribute `{vname}`")
            for vd in cd.modified_variables:
                change_str = ", ".join(vd.changes)
                modified_lines.append(f"- **attribute `{vd.name}`**: {change_str}")
            modified_lines.append("")

        for vd in mod.modified_variables:
            modified_lines.append(f"### `{mod.module_name}.{vd.name}`")
            for change in vd.changes:
                modified_lines.append(f"- {change}")
            modified_lines.append("")

    if modified_lines:
        lines.append("## Modified")
        lines.append("")
        lines.extend(modified_lines)

    return "\n".join(lines).rstrip()


def _is_breaking_change_text(change: str) -> bool:
    """Check if a change description represents a breaking change."""
    breaking_keywords = (
        "removed",
        "now required",
        "changed from sync",
        "changed from async",
        "required parameter",
    )
    return any(kw in change.lower() for kw in breaking_keywords)


def _capitalize(text: str) -> str:
    """Capitalize the first letter without lowering the rest."""
    if not text:
        return text
    return text[0].upper() + text[1:]
