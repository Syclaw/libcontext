"""Tests for the renderer module."""

from __future__ import annotations

import pytest

from libcontext.models import (
    ClassInfo,
    FunctionInfo,
    ModuleInfo,
    PackageInfo,
    ParameterInfo,
    VariableInfo,
)
from libcontext.renderer import (
    _format_docstring_match,
    _group_overloads,
    _has_overload,
    _is_overload,
    _matches,
    _OverloadGroup,
    _render_overload_group,
    _render_type_alias,
    _resolve_overload_docstring,
    inject_into_file,
    render_module,
    render_package,
    render_package_overview,
    search_package,
    search_package_structured,
)


def _make_simple_package() -> PackageInfo:
    """Build a minimal PackageInfo for testing."""
    return PackageInfo(
        name="mylib",
        version="1.2.3",
        summary="A test library",
        readme=(
            "# MyLib\n\nThis is a test library.\n\n## Installation\n\npip install mylib"
        ),
        modules=[
            ModuleInfo(
                name="mylib",
                docstring="Root module.",
                classes=[
                    ClassInfo(
                        name="Client",
                        bases=["BaseClient"],
                        docstring="HTTP client wrapper.",
                        methods=[
                            FunctionInfo(
                                name="__init__",
                                parameters=[
                                    ParameterInfo(name="self"),
                                    ParameterInfo(
                                        name="base_url",
                                        annotation="str",
                                    ),
                                    ParameterInfo(
                                        name="timeout",
                                        annotation="int",
                                        default="30",
                                    ),
                                ],
                                docstring="Initialize the client.",
                            ),
                            FunctionInfo(
                                name="get",
                                parameters=[
                                    ParameterInfo(name="self"),
                                    ParameterInfo(
                                        name="path",
                                        annotation="str",
                                    ),
                                ],
                                return_annotation="Response",
                                docstring="Send a GET request.",
                                is_async=True,
                            ),
                            FunctionInfo(
                                name="_internal",
                                parameters=[ParameterInfo(name="self")],
                                docstring="Internal helper.",
                            ),
                        ],
                        class_variables=[
                            VariableInfo(
                                name="DEFAULT_TIMEOUT",
                                annotation="int",
                                value="30",
                            ),
                        ],
                    ),
                ],
                functions=[
                    FunctionInfo(
                        name="create_client",
                        parameters=[
                            ParameterInfo(
                                name="url",
                                annotation="str",
                            ),
                        ],
                        return_annotation="Client",
                        docstring="Factory function to create a Client.",
                    ),
                ],
                variables=[
                    VariableInfo(
                        name="VERSION",
                        value="'1.2.3'",
                    ),
                ],
            ),
        ],
    )


def test_render_basic_structure():
    pkg = _make_simple_package()
    output = render_package(pkg)

    # Header
    assert "# mylib v1.2.3 — API Reference" in output
    assert "> A test library" in output

    # README
    assert "## Overview" in output
    assert "# MyLib" in output

    # API Reference
    assert "## API Reference" in output
    assert "### `mylib`" in output

    # Class
    assert "class Client(BaseClient)" in output
    assert "HTTP client wrapper." in output

    # Methods — __init__ should be shown, _internal should be hidden
    assert "__init__" in output
    assert "async def get" in output
    assert "_internal" not in output

    # Function
    assert "create_client" in output
    assert "Factory function" in output

    # Constant
    assert "VERSION" in output


def test_render_module_level_variables():
    """Non-UPPER_CASE public module variables are rendered."""
    pkg = PackageInfo(
        name="varlib",
        modules=[
            ModuleInfo(
                name="varlib",
                variables=[
                    VariableInfo(name="MAX_RETRIES", value="3"),
                    VariableInfo(name="default_timeout", annotation="int", value="30"),
                    VariableInfo(
                        name="base_url", annotation="str", value="'https://example.com'"
                    ),
                    VariableInfo(name="_private", value="True"),
                ],
                functions=[
                    FunctionInfo(name="noop", docstring="A no-op."),
                ],
            ),
        ],
    )
    output = render_package(pkg, include_readme=False)

    # UPPER_CASE under "Constants"
    assert "**Constants:**" in output
    assert "MAX_RETRIES" in output

    # Non-UPPER public vars under "Module Variables"
    assert "**Module Variables:**" in output
    assert "default_timeout" in output
    assert "base_url" in output

    # Private vars should not appear
    assert "_private" not in output


def test_render_no_readme():
    pkg = _make_simple_package()
    output = render_package(pkg, include_readme=False)

    assert "## Overview" not in output
    assert "## API Reference" in output


def test_render_readme_truncation():
    pkg = _make_simple_package()
    pkg.readme = "\n".join(f"Line {i}" for i in range(200))

    output = render_package(pkg, max_readme_lines=10)
    assert "Line 9" in output
    assert "Line 10" not in output
    assert "*(README truncated)*" in output


def test_render_extra_context():
    pkg = _make_simple_package()
    output = render_package(pkg, extra_context="Use async/await for all API calls.")

    assert "## Notes" in output
    assert "Use async/await for all API calls." in output


def test_render_empty_package():
    pkg = PackageInfo(name="empty", modules=[])
    output = render_package(pkg)

    assert "# empty — API Reference" in output
    # Should NOT have API Reference section if no modules
    assert "## API Reference" not in output


# ---------------------------------------------------------------------------
# inject_into_file
# ---------------------------------------------------------------------------


def test_inject_into_empty():
    content = "# My Package Context"
    result = inject_into_file(content, "mylib")

    assert "<!-- BEGIN LIBCONTEXT: mylib -->" in result
    assert "# My Package Context" in result
    assert "<!-- END LIBCONTEXT: mylib -->" in result


def test_inject_replace_existing():
    existing = (
        "# My Project Instructions\n\n"
        "Some custom instructions.\n\n"
        "<!-- BEGIN LIBCONTEXT: mylib -->\n"
        "OLD CONTENT\n"
        "<!-- END LIBCONTEXT: mylib -->\n\n"
        "More instructions."
    )

    result = inject_into_file("NEW CONTENT", "mylib", existing=existing)

    assert "NEW CONTENT" in result
    assert "OLD CONTENT" not in result
    assert "Some custom instructions." in result
    assert "More instructions." in result


def test_inject_append_to_existing():
    existing = "# Custom instructions\n\nDo this and that.\n"

    result = inject_into_file("APPENDED CONTEXT", "mylib", existing=existing)

    assert "# Custom instructions" in result
    assert "Do this and that." in result
    assert "<!-- BEGIN LIBCONTEXT: mylib -->" in result
    assert "APPENDED CONTEXT" in result


def test_inject_multiple_packages():
    result = inject_into_file("Context A", "pkg_a")
    result = inject_into_file("Context B", "pkg_b", existing=result)

    assert "<!-- BEGIN LIBCONTEXT: pkg_a -->" in result
    assert "Context A" in result
    assert "<!-- BEGIN LIBCONTEXT: pkg_b -->" in result
    assert "Context B" in result


# ---------------------------------------------------------------------------
# Regression: inject_into_file with partial / malformed markers
# ---------------------------------------------------------------------------


def test_inject_begin_without_end_does_not_duplicate():
    """If only BEGIN is present (corrupt file), the function should
    not silently create a duplicate block."""
    existing = (
        "# Instructions\n\n"
        "<!-- BEGIN LIBCONTEXT: mylib -->\n"
        "OLD CONTENT\n"
        "# no END marker\n"
    )

    result = inject_into_file("NEW CONTENT", "mylib", existing=existing)

    count_begin = result.count("<!-- BEGIN LIBCONTEXT: mylib -->")
    assert count_begin == 1, f"Expected exactly 1 BEGIN marker, got {count_begin}"


def test_inject_end_without_begin_does_not_duplicate():
    """If only END is present (corrupt file), the function should
    not silently create a duplicate block."""
    existing = "# Instructions\n\nOLD CONTENT\n<!-- END LIBCONTEXT: mylib -->\n"

    result = inject_into_file("NEW CONTENT", "mylib", existing=existing)

    count_end = result.count("<!-- END LIBCONTEXT: mylib -->")
    assert count_end == 1, f"Expected exactly 1 END marker, got {count_end}"


def test_inject_end_before_begin_does_not_cross():
    """If END appears before BEGIN (reversed), the result must be
    well-formed."""
    existing = (
        "<!-- END LIBCONTEXT: mylib -->\n"
        "MIDDLE\n"
        "<!-- BEGIN LIBCONTEXT: mylib -->\n"
        "OLD\n"
    )

    result = inject_into_file("NEW CONTENT", "mylib", existing=existing)

    # The result should have exactly one well-formed block
    count_begin = result.count("<!-- BEGIN LIBCONTEXT: mylib -->")
    count_end = result.count("<!-- END LIBCONTEXT: mylib -->")
    assert count_begin == 1
    assert count_end == 1
    # BEGIN must come before END
    assert result.index("<!-- BEGIN LIBCONTEXT: mylib -->") < result.index(
        "<!-- END LIBCONTEXT: mylib -->"
    )


# ---------------------------------------------------------------------------
# render_module (public API)
# ---------------------------------------------------------------------------


def test_render_module_standalone():
    """render_module produces a self-contained Markdown section."""
    module = ModuleInfo(
        name="mylib.api",
        docstring="Public API surface.",
        classes=[
            ClassInfo(
                name="Session",
                bases=["BaseSession"],
                docstring="Manages connections.",
                methods=[
                    FunctionInfo(
                        name="__init__",
                        parameters=[
                            ParameterInfo(name="self"),
                            ParameterInfo(name="url", annotation="str"),
                        ],
                        docstring="Create a session.",
                    ),
                    FunctionInfo(
                        name="close",
                        parameters=[ParameterInfo(name="self")],
                        return_annotation="None",
                        docstring="Close the session.",
                    ),
                ],
            ),
        ],
        functions=[
            FunctionInfo(
                name="get",
                parameters=[ParameterInfo(name="url", annotation="str")],
                return_annotation="Response",
                docstring="Send a GET request.",
            ),
        ],
    )

    output = render_module(module)

    assert "### `mylib.api`" in output
    assert "Public API surface." in output
    assert "class Session(BaseSession)" in output
    assert "Manages connections." in output
    assert "__init__" in output
    assert "close" in output
    assert "def get(url: str) -> Response" in output


def test_render_module_respects_all_exports():
    """render_module filters by __all__ when present."""
    module = ModuleInfo(
        name="mylib.core",
        all_exports=["public_func"],
        classes=[ClassInfo(name="Hidden")],
        functions=[
            FunctionInfo(name="public_func", docstring="Visible."),
            FunctionInfo(name="other_func", docstring="Not in __all__."),
        ],
    )

    output = render_module(module)

    assert "public_func" in output
    assert "other_func" not in output
    assert "Hidden" not in output


def test_render_module_empty():
    """render_module on an empty module produces only the heading."""
    module = ModuleInfo(name="mylib.empty")
    output = render_module(module)

    assert "### `mylib.empty`" in output
    assert "**Functions:**" not in output


# ---------------------------------------------------------------------------
# render_package_overview
# ---------------------------------------------------------------------------


def test_render_package_overview_structure():
    """Overview lists modules with class and function names."""
    pkg = _make_simple_package()
    output = render_package_overview(pkg)

    assert "# mylib v1.2.3" in output
    assert "> A test library" in output
    assert "## Modules" in output
    assert "**`mylib`**" in output
    assert "Client" in output
    assert "create_client()" in output


def test_render_package_overview_no_signatures():
    """Overview must NOT contain full signatures — just names."""
    pkg = _make_simple_package()
    output = render_package_overview(pkg)

    assert "base_url: str" not in output
    assert "-> Response" not in output


def test_render_package_overview_empty():
    """Overview on an empty package shows a placeholder."""
    pkg = PackageInfo(name="empty", modules=[])
    output = render_package_overview(pkg)

    assert "# empty" in output
    assert "*No public modules found.*" in output


def test_render_package_overview_respects_all_exports():
    """Overview filters by __all__ when defined."""
    pkg = PackageInfo(
        name="filtered",
        version="0.1.0",
        modules=[
            ModuleInfo(
                name="filtered.core",
                all_exports=["Visible"],
                classes=[
                    ClassInfo(name="Visible"),
                    ClassInfo(name="Internal"),
                ],
                functions=[
                    FunctionInfo(name="Visible"),
                    FunctionInfo(name="hidden_func"),
                ],
            ),
        ],
    )

    output = render_package_overview(pkg)

    assert "Visible" in output
    assert "Internal" not in output
    assert "hidden_func" not in output


# ---------------------------------------------------------------------------
# _render_type_alias
# ---------------------------------------------------------------------------


def test_render_type_alias_pep613():
    alias = VariableInfo(
        name="JsonDict",
        annotation="TypeAlias",
        value="Dict[str, Any]",
        is_type_alias=True,
    )
    assert _render_type_alias(alias) == "- `JsonDict = Dict[str, Any]`"


def test_render_type_alias_pep695():
    alias = VariableInfo(
        name="Point",
        annotation=None,
        value="type Point = tuple[int, int]",
        is_type_alias=True,
    )
    assert _render_type_alias(alias) == "- `type Point = tuple[int, int]`"


def test_render_type_alias_pep695_generic():
    alias = VariableInfo(
        name="Vec",
        annotation=None,
        value="type Vec[T] = list[T]",
        is_type_alias=True,
    )
    assert _render_type_alias(alias) == "- `type Vec[T] = list[T]`"


def test_render_type_alias_no_value():
    alias = VariableInfo(
        name="X",
        annotation="TypeAlias",
        value=None,
        is_type_alias=True,
    )
    assert _render_type_alias(alias) == "- `X = ...`"


# ---------------------------------------------------------------------------
# render_module with type aliases
# ---------------------------------------------------------------------------


def test_render_module_type_aliases_section():
    """Type aliases appear in their own section, not in Constants or Variables."""
    module = ModuleInfo(
        name="mylib.types",
        variables=[
            VariableInfo(
                name="JsonDict",
                annotation="TypeAlias",
                value="Dict[str, Any]",
                is_type_alias=True,
            ),
            VariableInfo(
                name="MAX_SIZE",
                value="100",
            ),
            VariableInfo(
                name="default_encoding",
                annotation="str",
                value="'utf-8'",
            ),
        ],
        functions=[
            FunctionInfo(name="noop", docstring="A no-op."),
        ],
    )

    output = render_module(module)

    assert "**Type Aliases:**" in output
    assert "- `JsonDict = Dict[str, Any]`" in output

    # Alias must NOT appear in Constants or Module Variables
    constants_idx = output.find("**Constants:**")
    vars_idx = output.find("**Module Variables:**")
    aliases_idx = output.find("**Type Aliases:**")

    assert aliases_idx < constants_idx, "Type Aliases should appear before Constants"
    assert "JsonDict" not in output[constants_idx:]
    assert "JsonDict" not in output[vars_idx:]


def test_render_module_no_aliases_unchanged():
    """Modules without aliases render identically to before."""
    module = ModuleInfo(
        name="mylib.core",
        variables=[
            VariableInfo(name="VERSION", value="'1.0'"),
        ],
        functions=[
            FunctionInfo(name="main", docstring="Entry point."),
        ],
    )

    output = render_module(module)

    assert "**Type Aliases:**" not in output
    assert "**Constants:**" in output


def test_render_module_upper_alias_not_in_constants():
    """An UPPER_CASE type alias should be in Type Aliases, not Constants."""
    module = ModuleInfo(
        name="mylib.types",
        variables=[
            VariableInfo(
                name="JSON_TYPE",
                annotation="TypeAlias",
                value="Dict[str, Any]",
                is_type_alias=True,
            ),
        ],
        functions=[
            FunctionInfo(name="noop", docstring="A no-op."),
        ],
    )

    output = render_module(module)

    assert "**Type Aliases:**" in output
    assert "**Constants:**" not in output


def test_render_class_type_aliases():
    """Type aliases in classes appear in a dedicated section before Attributes."""
    cls_info = ClassInfo(
        name="Container",
        class_variables=[
            VariableInfo(
                name="ItemType",
                annotation="TypeAlias",
                value="int",
                is_type_alias=True,
            ),
            VariableInfo(name="count", annotation="int", value="0"),
        ],
    )
    module = ModuleInfo(
        name="mylib.core",
        classes=[cls_info],
        functions=[FunctionInfo(name="noop", docstring="No-op.")],
    )

    output = render_module(module)

    assert "**Type Aliases:**" in output
    assert "**Attributes:**" in output
    # Type Aliases before Attributes
    assert output.index("**Type Aliases:**") < output.index("**Attributes:**")


# ---------------------------------------------------------------------------
# Overload helpers
# ---------------------------------------------------------------------------


def test_is_overload():
    assert _is_overload("overload") is True
    assert _is_overload("typing.overload") is True
    assert _is_overload("typing_extensions.overload") is True
    assert _is_overload("cache") is False
    assert _is_overload("my_overload") is False


def test_has_overload():
    assert _has_overload(FunctionInfo(name="f", decorators=["overload"])) is True
    assert _has_overload(FunctionInfo(name="f", decorators=["cache"])) is False
    assert _has_overload(FunctionInfo(name="f", decorators=[])) is False


def _make_overloaded_functions() -> list[FunctionInfo]:
    """Build a list of overloaded + normal functions for testing."""
    return [
        FunctionInfo(
            name="get",
            parameters=[ParameterInfo(name="url", annotation="str")],
            return_annotation="Response",
            decorators=["overload"],
        ),
        FunctionInfo(
            name="get",
            parameters=[
                ParameterInfo(name="url", annotation="str"),
                ParameterInfo(name="stream", annotation="Literal[True]"),
            ],
            return_annotation="StreamResponse",
            decorators=["overload"],
        ),
        FunctionInfo(
            name="get",
            parameters=[
                ParameterInfo(name="url", annotation="str"),
                ParameterInfo(name="stream", annotation="bool", default="False"),
            ],
            return_annotation="Response | StreamResponse",
            docstring="Send a GET request.",
        ),
        FunctionInfo(
            name="parse",
            parameters=[ParameterInfo(name="data", annotation="str")],
            return_annotation="dict",
            docstring="Parse data.",
        ),
    ]


def test_group_overloads_basic():
    funcs = _make_overloaded_functions()
    grouped = _group_overloads(funcs)

    assert len(grouped) == 2
    assert isinstance(grouped[0], _OverloadGroup)
    assert grouped[0].name == "get"
    assert len(grouped[0].overloads) == 2
    assert grouped[0].implementation is not None
    assert grouped[0].implementation.docstring == "Send a GET request."
    assert isinstance(grouped[1], FunctionInfo)
    assert grouped[1].name == "parse"


def test_group_overloads_no_overloads():
    funcs = [
        FunctionInfo(name="a"),
        FunctionInfo(name="b"),
    ]
    grouped = _group_overloads(funcs)
    assert len(grouped) == 2
    assert all(isinstance(g, FunctionInfo) for g in grouped)


def test_group_overloads_no_implementation():
    funcs = [
        FunctionInfo(name="f", decorators=["overload"]),
        FunctionInfo(name="f", decorators=["overload"]),
    ]
    grouped = _group_overloads(funcs)
    assert len(grouped) == 1
    group = grouped[0]
    assert isinstance(group, _OverloadGroup)
    assert group.implementation is None
    assert len(group.overloads) == 2


def test_group_overloads_preserves_order():
    funcs = [
        FunctionInfo(name="a"),
        FunctionInfo(name="f", decorators=["overload"]),
        FunctionInfo(name="f", decorators=["overload"]),
        FunctionInfo(name="f"),
        FunctionInfo(name="b"),
    ]
    grouped = _group_overloads(funcs)
    assert len(grouped) == 3
    assert isinstance(grouped[0], FunctionInfo)
    assert grouped[0].name == "a"
    assert isinstance(grouped[1], _OverloadGroup)
    assert grouped[1].name == "f"
    assert isinstance(grouped[2], FunctionInfo)
    assert grouped[2].name == "b"


def test_resolve_overload_docstring_impl_priority():
    group = _OverloadGroup(
        name="f",
        qualname="f",
        overloads=[FunctionInfo(name="f", docstring="Overload doc.")],
        implementation=FunctionInfo(name="f", docstring="Impl doc."),
    )
    assert _resolve_overload_docstring(group) == "Impl doc."


def test_resolve_overload_docstring_fallback_to_overload():
    group = _OverloadGroup(
        name="f",
        qualname="f",
        overloads=[
            FunctionInfo(name="f"),
            FunctionInfo(name="f", docstring="Second overload."),
        ],
        implementation=FunctionInfo(name="f"),
    )
    assert _resolve_overload_docstring(group) == "Second overload."


def test_resolve_overload_docstring_none():
    group = _OverloadGroup(
        name="f",
        qualname="f",
        overloads=[FunctionInfo(name="f")],
        implementation=None,
    )
    assert _resolve_overload_docstring(group) is None


def test_render_overload_group():
    group = _OverloadGroup(
        name="get",
        qualname="get",
        overloads=[
            FunctionInfo(
                name="get",
                parameters=[ParameterInfo(name="url", annotation="str")],
                return_annotation="Response",
                decorators=["overload"],
            ),
            FunctionInfo(
                name="get",
                parameters=[
                    ParameterInfo(name="url", annotation="str"),
                    ParameterInfo(name="stream", annotation="Literal[True]"),
                ],
                return_annotation="StreamResponse",
                decorators=["overload"],
            ),
        ],
        implementation=FunctionInfo(
            name="get",
            docstring="Send a GET request.",
        ),
    )

    output = _render_overload_group(group)
    assert "*(overloaded)*" in output
    assert "```python" in output
    assert "def get(url: str) -> Response" in output
    assert "def get(url: str, stream: Literal[True]) -> StreamResponse" in output
    assert "Send a GET request." in output


# ---------------------------------------------------------------------------
# Integration: render_module with overloads
# ---------------------------------------------------------------------------


def test_render_module_with_overloads():
    module = ModuleInfo(
        name="mylib.api",
        functions=_make_overloaded_functions(),
    )

    output = render_module(module)

    assert "*(overloaded)*" in output
    assert "```python" in output
    assert "def get(url: str) -> Response" in output
    assert "Parse data." in output


def test_render_module_no_overloads_unchanged():
    """Non-regression: module without overloads renders identically."""
    module = ModuleInfo(
        name="mylib.core",
        functions=[
            FunctionInfo(name="a", docstring="A."),
            FunctionInfo(name="b", docstring="B."),
        ],
    )

    output = render_module(module)

    assert "*(overloaded)*" not in output
    assert "a" in output
    assert "b" in output


def test_render_class_with_overloaded_methods():
    cls_info = ClassInfo(
        name="Client",
        methods=[
            FunctionInfo(
                name="__init__",
                parameters=[
                    ParameterInfo(name="self"),
                    ParameterInfo(name="url", annotation="str"),
                ],
                decorators=["overload"],
            ),
            FunctionInfo(
                name="__init__",
                parameters=[
                    ParameterInfo(name="self"),
                    ParameterInfo(name="config", annotation="Config"),
                ],
                decorators=["overload"],
            ),
            FunctionInfo(
                name="__init__",
                parameters=[ParameterInfo(name="self"), ParameterInfo(name="args")],
                docstring="Initialize client.",
            ),
        ],
    )
    module = ModuleInfo(name="mylib", classes=[cls_info])
    output = render_module(module)

    assert "*(overloaded)*" in output
    assert "Initialize client." in output


def test_render_package_overview_overloads():
    pkg = PackageInfo(
        name="mylib",
        modules=[
            ModuleInfo(
                name="mylib.api",
                functions=_make_overloaded_functions(),
            ),
        ],
    )

    output = render_package_overview(pkg)

    assert "get() (overloaded)" in output
    assert "parse()" in output
    assert output.count("get()") == 1


def test_search_package_overloaded_function():
    pkg = PackageInfo(
        name="mylib",
        modules=[
            ModuleInfo(
                name="mylib.api",
                functions=_make_overloaded_functions(),
            ),
        ],
    )

    output = search_package(pkg, "get")

    assert "(overloaded)" in output
    assert "def get(url: str) -> Response" in output
    assert output.count("function") == 1


def test_search_package_normal_function():
    pkg = PackageInfo(
        name="mylib",
        modules=[
            ModuleInfo(
                name="mylib.api",
                functions=_make_overloaded_functions(),
            ),
        ],
    )

    output = search_package(pkg, "parse")

    assert "(overloaded)" not in output
    assert "def parse(data: str) -> dict" in output


# ---------------------------------------------------------------------------
# _matches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "docstring", "query", "expected"),
    [
        ("parse_url", "Parse a URL", "parse", "name"),
        ("fetch", "Parse and retrieve data", "parse", "docstring"),
        ("parse", "Parse data", "parse", "name"),
        ("fetch", "Retrieve data", "parse", None),
        ("fetch", None, "parse", None),
        ("Parse", None, "parse", "name"),
    ],
)
def test_matches(name: str, docstring: str | None, query: str, expected: str | None):
    assert _matches(name, docstring, query) == expected


def test_format_docstring_match_short():
    result = _format_docstring_match("Parse a URL")
    assert result == '*(matched in docstring: "Parse a URL")*'


def test_format_docstring_match_long():
    long_doc = "A" * 80
    result = _format_docstring_match(long_doc)
    assert "..." in result
    assert len(result) < 100


# ---------------------------------------------------------------------------
# search_package kind validation
# ---------------------------------------------------------------------------


def test_search_package_invalid_kind():
    pkg = PackageInfo(name="test", modules=[])
    with pytest.raises(ValueError, match="Invalid kind"):
        search_package(pkg, "query", kind="method")


@pytest.mark.parametrize("kind", ["class", "function", "variable", "alias", None])
def test_search_package_valid_kinds(kind: str | None):
    pkg = PackageInfo(name="test", modules=[])
    result = search_package(pkg, "query", kind=kind)
    assert "No matches" in result


# ---------------------------------------------------------------------------
# search_package with kind filter
# ---------------------------------------------------------------------------


def _make_search_package() -> PackageInfo:
    """Package with classes, functions, variables, and aliases for search tests."""
    return PackageInfo(
        name="testpkg",
        modules=[
            ModuleInfo(
                name="testpkg.core",
                classes=[
                    ClassInfo(
                        name="MyParser",
                        docstring="XML parser.",
                        methods=[
                            FunctionInfo(
                                name="run",
                                parameters=[ParameterInfo(name="self")],
                                docstring="Execute the parser.",
                            ),
                        ],
                    ),
                ],
                functions=[
                    FunctionInfo(
                        name="parse_data",
                        parameters=[ParameterInfo(name="data", annotation="str")],
                        return_annotation="dict",
                        docstring="Parse input data.",
                    ),
                ],
                variables=[
                    VariableInfo(name="MAX_SIZE", value="100"),
                    VariableInfo(
                        name="JsonDict",
                        annotation="TypeAlias",
                        value="Dict[str, Any]",
                        is_type_alias=True,
                    ),
                ],
            ),
        ],
    )


def test_search_kind_class():
    pkg = _make_search_package()
    output = search_package(pkg, "parser", kind="class")
    assert "class" in output
    assert "function" not in output
    assert "method" not in output


def test_search_kind_function():
    pkg = _make_search_package()
    output = search_package(pkg, "parse", kind="function")
    assert "function" in output or "method" in output
    assert "class" not in output


def test_search_kind_variable():
    pkg = _make_search_package()
    output = search_package(pkg, "MAX", kind="variable")
    assert "MAX_SIZE" in output
    assert "JsonDict" not in output


def test_search_kind_alias():
    pkg = _make_search_package()
    output = search_package(pkg, "Json", kind="alias")
    assert "JsonDict" in output
    assert "MAX_SIZE" not in output


# ---------------------------------------------------------------------------
# Docstring search
# ---------------------------------------------------------------------------


def test_search_docstring_match_function():
    pkg = _make_search_package()
    output = search_package(pkg, "input data")
    assert "parse_data" in output
    assert "matched in docstring" in output


def test_search_docstring_match_class():
    pkg = _make_search_package()
    output = search_package(pkg, "xml")
    assert "MyParser" in output
    assert "matched in docstring" in output


def test_search_docstring_match_method():
    pkg = _make_search_package()
    output = search_package(pkg, "execute")
    assert "run" in output
    assert "matched in docstring" in output


def test_search_name_match_no_docstring_annotation():
    """Name match should NOT have docstring annotation."""
    pkg = _make_search_package()
    output = search_package(pkg, "parse_data")
    assert "parse_data" in output
    assert "matched in docstring" not in output


def test_search_no_kind_no_variables():
    """Without kind filter, variables should NOT appear in results."""
    pkg = _make_search_package()
    output = search_package(pkg, "MAX")
    assert "MAX_SIZE" not in output


# ---------------------------------------------------------------------------
# search_package_structured
# ---------------------------------------------------------------------------


def test_structured_search_class():
    pkg = _make_search_package()
    results = search_package_structured(pkg, "parser", kind="class")
    assert len(results) == 1
    assert results[0]["kind"] == "class"
    assert results[0]["name"] == "MyParser"
    assert results[0]["module"] == "testpkg.core"
    assert results[0]["match_in"] == "name"
    assert "signature" in results[0]


def test_structured_search_function():
    pkg = _make_search_package()
    results = search_package_structured(pkg, "parse", kind="function")
    names = [r["name"] for r in results]
    assert "parse_data" in names


def test_structured_search_method():
    pkg = _make_search_package()
    results = search_package_structured(pkg, "run")
    methods = [r for r in results if r["kind"] == "method"]
    assert len(methods) == 1
    assert methods[0]["class"] == "MyParser"


def test_structured_search_variable():
    pkg = _make_search_package()
    results = search_package_structured(pkg, "MAX", kind="variable")
    assert len(results) == 1
    assert results[0]["kind"] == "variable"
    assert results[0]["name"] == "MAX_SIZE"


def test_structured_search_alias():
    pkg = _make_search_package()
    results = search_package_structured(pkg, "Json", kind="alias")
    assert len(results) == 1
    assert results[0]["kind"] == "alias"
    assert results[0]["name"] == "JsonDict"


def test_structured_search_docstring_match():
    pkg = _make_search_package()
    results = search_package_structured(pkg, "xml")
    assert len(results) == 1
    assert results[0]["match_in"] == "docstring"
    assert "docstring_preview" in results[0]


def test_structured_search_no_results():
    pkg = _make_search_package()
    results = search_package_structured(pkg, "nonexistent")
    assert results == []


def test_structured_search_invalid_kind():
    pkg = PackageInfo(name="test", modules=[])
    with pytest.raises(ValueError, match="Invalid kind"):
        search_package_structured(pkg, "query", kind="method")


def test_structured_search_overloaded_function():
    pkg = PackageInfo(
        name="mylib",
        modules=[
            ModuleInfo(
                name="mylib.api",
                functions=_make_overloaded_functions(),
            ),
        ],
    )
    results = search_package_structured(pkg, "get")
    funcs = [r for r in results if r["kind"] == "function"]
    assert len(funcs) == 1
    assert funcs[0]["name"] == "get"
    assert "overload_count" in funcs[0]
