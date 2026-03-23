"""Tests for diff module."""

from __future__ import annotations

from libcontext.diff import diff_packages
from libcontext.models import (
    ClassInfo,
    FunctionInfo,
    ModuleInfo,
    PackageInfo,
    ParameterInfo,
    VariableInfo,
)
from libcontext.renderer import render_diff

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pkg(
    modules: list[ModuleInfo] | None = None,
    version: str | None = None,
) -> PackageInfo:
    return PackageInfo(
        name="mypkg",
        version=version,
        modules=modules or [],
    )


def _mod(
    name: str = "mypkg.core",
    functions: list[FunctionInfo] | None = None,
    classes: list[ClassInfo] | None = None,
    variables: list[VariableInfo] | None = None,
) -> ModuleInfo:
    return ModuleInfo(
        name=name,
        functions=functions or [],
        classes=classes or [],
        variables=variables or [],
    )


# ---------------------------------------------------------------------------
# Module-level diffs
# ---------------------------------------------------------------------------


class TestModuleDiffs:
    def test_module_added(self) -> None:
        old = _pkg([_mod("a")])
        new = _pkg([_mod("a"), _mod("b")])
        result = diff_packages(old, new)
        assert result.added_modules == ["b"]
        assert not result.removed_modules

    def test_module_removed(self) -> None:
        old = _pkg([_mod("a"), _mod("b")])
        new = _pkg([_mod("a")])
        result = diff_packages(old, new)
        assert result.removed_modules == ["b"]
        assert result.has_breaking_changes

    def test_identical_packages(self) -> None:
        pkg = _pkg([_mod("a", functions=[FunctionInfo(name="f")])])
        result = diff_packages(pkg, pkg)
        assert result.is_empty


# ---------------------------------------------------------------------------
# Function diffs
# ---------------------------------------------------------------------------


class TestFunctionDiffs:
    def test_function_added(self) -> None:
        old = _pkg([_mod(functions=[FunctionInfo(name="a")])])
        new = _pkg([_mod(functions=[FunctionInfo(name="a"), FunctionInfo(name="b")])])
        result = diff_packages(old, new)
        assert result.modified_modules[0].added_functions == ["b"]

    def test_function_removed(self) -> None:
        old = _pkg([_mod(functions=[FunctionInfo(name="a"), FunctionInfo(name="b")])])
        new = _pkg([_mod(functions=[FunctionInfo(name="a")])])
        result = diff_packages(old, new)
        assert result.modified_modules[0].removed_functions == ["b"]

    def test_return_type_changed(self) -> None:
        old = _pkg([_mod(functions=[FunctionInfo(name="f", return_annotation="str")])])
        new = _pkg([_mod(functions=[FunctionInfo(name="f", return_annotation="int")])])
        result = diff_packages(old, new)
        fd = result.modified_modules[0].modified_functions[0]
        assert "return type changed: str → int" in fd.changes
        assert not fd.is_breaking

    def test_required_param_added(self) -> None:
        old = _pkg([_mod(functions=[FunctionInfo(name="f")])])
        new = _pkg(
            [
                _mod(
                    functions=[
                        FunctionInfo(
                            name="f",
                            parameters=[ParameterInfo(name="x", annotation="int")],
                        )
                    ]
                )
            ]
        )
        result = diff_packages(old, new)
        fd = result.modified_modules[0].modified_functions[0]
        assert fd.is_breaking
        assert any("required parameter 'x' added" in c for c in fd.changes)

    def test_optional_param_added(self) -> None:
        old = _pkg([_mod(functions=[FunctionInfo(name="f")])])
        new = _pkg(
            [
                _mod(
                    functions=[
                        FunctionInfo(
                            name="f",
                            parameters=[ParameterInfo(name="x", default="None")],
                        )
                    ]
                )
            ]
        )
        result = diff_packages(old, new)
        fd = result.modified_modules[0].modified_functions[0]
        assert not fd.is_breaking
        assert any("optional parameter 'x' added" in c for c in fd.changes)

    def test_param_removed(self) -> None:
        old = _pkg(
            [
                _mod(
                    functions=[
                        FunctionInfo(
                            name="f",
                            parameters=[ParameterInfo(name="x")],
                        )
                    ]
                )
            ]
        )
        new = _pkg([_mod(functions=[FunctionInfo(name="f")])])
        result = diff_packages(old, new)
        fd = result.modified_modules[0].modified_functions[0]
        assert fd.is_breaking
        assert any("parameter 'x' removed" in c for c in fd.changes)

    def test_param_now_required(self) -> None:
        old = _pkg(
            [
                _mod(
                    functions=[
                        FunctionInfo(
                            name="f",
                            parameters=[ParameterInfo(name="x", default="0")],
                        )
                    ]
                )
            ]
        )
        new = _pkg(
            [
                _mod(
                    functions=[
                        FunctionInfo(
                            name="f",
                            parameters=[ParameterInfo(name="x")],
                        )
                    ]
                )
            ]
        )
        result = diff_packages(old, new)
        fd = result.modified_modules[0].modified_functions[0]
        assert fd.is_breaking
        assert any("parameter 'x' now required" in c for c in fd.changes)

    def test_sync_to_async(self) -> None:
        old = _pkg([_mod(functions=[FunctionInfo(name="f")])])
        new = _pkg([_mod(functions=[FunctionInfo(name="f", is_async=True)])])
        result = diff_packages(old, new)
        fd = result.modified_modules[0].modified_functions[0]
        assert fd.is_breaking
        assert any("changed from sync to async" in c for c in fd.changes)

    def test_async_to_sync(self) -> None:
        old = _pkg([_mod(functions=[FunctionInfo(name="f", is_async=True)])])
        new = _pkg([_mod(functions=[FunctionInfo(name="f")])])
        result = diff_packages(old, new)
        fd = result.modified_modules[0].modified_functions[0]
        assert fd.is_breaking
        assert any("changed from async to sync" in c for c in fd.changes)

    def test_param_type_changed(self) -> None:
        old = _pkg(
            [
                _mod(
                    functions=[
                        FunctionInfo(
                            name="f",
                            parameters=[ParameterInfo(name="x", annotation="str")],
                        )
                    ]
                )
            ]
        )
        new = _pkg(
            [
                _mod(
                    functions=[
                        FunctionInfo(
                            name="f",
                            parameters=[ParameterInfo(name="x", annotation="bytes")],
                        )
                    ]
                )
            ]
        )
        result = diff_packages(old, new)
        fd = result.modified_modules[0].modified_functions[0]
        assert any("type changed: str → bytes" in c for c in fd.changes)
        assert not fd.is_breaking

    def test_decorators_changed(self) -> None:
        old = _pkg([_mod(functions=[FunctionInfo(name="f")])])
        new = _pkg([_mod(functions=[FunctionInfo(name="f", decorators=["cache"])])])
        result = diff_packages(old, new)
        fd = result.modified_modules[0].modified_functions[0]
        assert "decorators changed" in fd.changes


# ---------------------------------------------------------------------------
# Class diffs
# ---------------------------------------------------------------------------


class TestClassDiffs:
    def test_class_added(self) -> None:
        old = _pkg([_mod(classes=[ClassInfo(name="A")])])
        new = _pkg([_mod(classes=[ClassInfo(name="A"), ClassInfo(name="B")])])
        result = diff_packages(old, new)
        assert "B" in result.modified_modules[0].added_classes

    def test_class_removed(self) -> None:
        old = _pkg([_mod(classes=[ClassInfo(name="A"), ClassInfo(name="B")])])
        new = _pkg([_mod(classes=[ClassInfo(name="A")])])
        result = diff_packages(old, new)
        assert "B" in result.modified_modules[0].removed_classes

    def test_base_removed(self) -> None:
        old = _pkg([_mod(classes=[ClassInfo(name="C", bases=["Base"])])])
        new = _pkg([_mod(classes=[ClassInfo(name="C")])])
        result = diff_packages(old, new)
        cd = result.modified_modules[0].modified_classes[0]
        assert cd.is_breaking
        assert any("base class 'Base' removed" in c for c in cd.changes)

    def test_base_added(self) -> None:
        old = _pkg([_mod(classes=[ClassInfo(name="C")])])
        new = _pkg([_mod(classes=[ClassInfo(name="C", bases=["Base"])])])
        result = diff_packages(old, new)
        cd = result.modified_modules[0].modified_classes[0]
        assert not cd.is_breaking
        assert any("base class 'Base' added" in c for c in cd.changes)

    def test_method_removed_is_breaking(self) -> None:
        old = _pkg(
            [
                _mod(
                    classes=[
                        ClassInfo(
                            name="C",
                            methods=[FunctionInfo(name="m")],
                        )
                    ]
                )
            ]
        )
        new = _pkg([_mod(classes=[ClassInfo(name="C")])])
        result = diff_packages(old, new)
        cd = result.modified_modules[0].modified_classes[0]
        assert cd.is_breaking
        assert "m" in cd.removed_methods

    def test_method_modified(self) -> None:
        old = _pkg(
            [
                _mod(
                    classes=[
                        ClassInfo(
                            name="C",
                            methods=[FunctionInfo(name="m", return_annotation="str")],
                        )
                    ]
                )
            ]
        )
        new = _pkg(
            [
                _mod(
                    classes=[
                        ClassInfo(
                            name="C",
                            methods=[FunctionInfo(name="m", return_annotation="int")],
                        )
                    ]
                )
            ]
        )
        result = diff_packages(old, new)
        cd = result.modified_modules[0].modified_classes[0]
        assert len(cd.modified_methods) == 1

    def test_class_variable_added(self) -> None:
        old = _pkg([_mod(classes=[ClassInfo(name="C")])])
        new = _pkg(
            [
                _mod(
                    classes=[
                        ClassInfo(
                            name="C",
                            class_variables=[VariableInfo(name="x")],
                        )
                    ]
                )
            ]
        )
        result = diff_packages(old, new)
        cd = result.modified_modules[0].modified_classes[0]
        assert "x" in cd.added_variables

    def test_class_variable_removed(self) -> None:
        old = _pkg(
            [
                _mod(
                    classes=[
                        ClassInfo(
                            name="C",
                            class_variables=[VariableInfo(name="x")],
                        )
                    ]
                )
            ]
        )
        new = _pkg([_mod(classes=[ClassInfo(name="C")])])
        result = diff_packages(old, new)
        cd = result.modified_modules[0].modified_classes[0]
        assert "x" in cd.removed_variables

    def test_class_variable_modified(self) -> None:
        old = _pkg(
            [
                _mod(
                    classes=[
                        ClassInfo(
                            name="C",
                            class_variables=[VariableInfo(name="x", annotation="int")],
                        )
                    ]
                )
            ]
        )
        new = _pkg(
            [
                _mod(
                    classes=[
                        ClassInfo(
                            name="C",
                            class_variables=[VariableInfo(name="x", annotation="str")],
                        )
                    ]
                )
            ]
        )
        result = diff_packages(old, new)
        cd = result.modified_modules[0].modified_classes[0]
        assert len(cd.modified_variables) == 1

    def test_class_decorators_changed(self) -> None:
        old = _pkg([_mod(classes=[ClassInfo(name="C")])])
        new = _pkg([_mod(classes=[ClassInfo(name="C", decorators=["dataclass"])])])
        result = diff_packages(old, new)
        cd = result.modified_modules[0].modified_classes[0]
        assert "decorators changed" in cd.changes


# ---------------------------------------------------------------------------
# Variable diffs
# ---------------------------------------------------------------------------


class TestVariableDiffs:
    def test_annotation_changed(self) -> None:
        old = _pkg([_mod(variables=[VariableInfo(name="X", annotation="int")])])
        new = _pkg([_mod(variables=[VariableInfo(name="X", annotation="str")])])
        result = diff_packages(old, new)
        vd = result.modified_modules[0].modified_variables[0]
        assert "type changed: int → str" in vd.changes
        assert not vd.is_breaking

    def test_value_changed(self) -> None:
        old = _pkg([_mod(variables=[VariableInfo(name="X", value="1")])])
        new = _pkg([_mod(variables=[VariableInfo(name="X", value="2")])])
        result = diff_packages(old, new)
        vd = result.modified_modules[0].modified_variables[0]
        assert "value changed" in vd.changes


# ---------------------------------------------------------------------------
# DiffResult properties
# ---------------------------------------------------------------------------


class TestDiffResultProperties:
    def test_has_breaking_removed_module(self) -> None:
        old = _pkg([_mod("a")])
        new = _pkg([])
        result = diff_packages(old, new)
        assert result.has_breaking_changes

    def test_no_breaking_added_only(self) -> None:
        old = _pkg([])
        new = _pkg([_mod("a")])
        result = diff_packages(old, new)
        assert not result.has_breaking_changes

    def test_is_empty(self) -> None:
        pkg = _pkg([_mod("a")])
        result = diff_packages(pkg, pkg)
        assert result.is_empty


# ---------------------------------------------------------------------------
# render_diff
# ---------------------------------------------------------------------------


class TestRenderDiff:
    def test_empty_diff(self) -> None:
        pkg = _pkg([_mod("a")])
        result = diff_packages(pkg, pkg)
        output = render_diff(result)
        assert "No changes detected" in output

    def test_breaking_section(self) -> None:
        old = _pkg([_mod("a", functions=[FunctionInfo(name="f")])], "1.0")
        new = _pkg([_mod("a")], "2.0")
        result = diff_packages(old, new)
        output = render_diff(result)
        assert "## Breaking Changes" in output
        assert "Removed function" in output

    def test_added_section(self) -> None:
        old = _pkg([], "1.0")
        new = _pkg([_mod("a")], "2.0")
        result = diff_packages(old, new)
        output = render_diff(result)
        assert "## Added" in output
        assert "Module" in output

    def test_modified_section(self) -> None:
        old = _pkg([_mod(functions=[FunctionInfo(name="f", return_annotation="str")])])
        new = _pkg([_mod(functions=[FunctionInfo(name="f", return_annotation="int")])])
        result = diff_packages(old, new)
        output = render_diff(result)
        assert "## Modified" in output
        assert "return type changed" in output

    def test_version_header(self) -> None:
        old = _pkg([], "1.0.0")
        new = _pkg([_mod("a")], "2.0.0")
        result = diff_packages(old, new)
        output = render_diff(result)
        assert "1.0.0 → 2.0.0" in output

    def test_no_breaking_section_when_clean(self) -> None:
        old = _pkg([])
        new = _pkg([_mod("a")])
        result = diff_packages(old, new)
        output = render_diff(result)
        assert "Breaking Changes" not in output

    def test_all_sections_present(self) -> None:
        old = _pkg(
            [
                _mod(
                    "a",
                    functions=[FunctionInfo(name="old_func")],
                    classes=[
                        ClassInfo(
                            name="OldClass",
                            methods=[FunctionInfo(name="m")],
                        )
                    ],
                ),
                _mod("removed_mod"),
            ],
            "1.0",
        )
        new = _pkg(
            [
                _mod(
                    "a",
                    functions=[
                        FunctionInfo(name="new_func"),
                    ],
                    classes=[
                        ClassInfo(
                            name="OldClass",
                            methods=[FunctionInfo(name="m", is_async=True)],
                        ),
                    ],
                ),
                _mod("new_mod"),
            ],
            "2.0",
        )
        result = diff_packages(old, new)
        output = render_diff(result)
        assert "## Breaking Changes" in output
        assert "## Added" in output
        assert "## Modified" in output


# ---------------------------------------------------------------------------
# Different package names warning
# ---------------------------------------------------------------------------


def test_diff_different_package_names_logs_warning(caplog) -> None:
    """Comparing packages with different names emits a warning."""
    import logging

    old = PackageInfo(name="pkg_a", modules=[])
    new = PackageInfo(name="pkg_b", modules=[])
    with caplog.at_level(logging.WARNING, logger="libcontext.diff"):
        result = diff_packages(old, new)
    assert any("different names" in r.message for r in caplog.records)
    assert result.package_name == "pkg_b"
