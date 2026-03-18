"""Tests for the renderer module."""

from __future__ import annotations

from libcontext.models import (
    ClassInfo,
    FunctionInfo,
    ModuleInfo,
    PackageInfo,
    ParameterInfo,
    VariableInfo,
)
from libcontext.renderer import (
    inject_into_file,
    render_module,
    render_package,
    render_package_overview,
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
