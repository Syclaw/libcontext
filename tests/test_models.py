"""Tests for models — from_dict roundtrip and JSON envelope."""

import dataclasses

import pytest

from libcontext.models import (
    _SCHEMA_VERSION,
    ClassDiff,
    ClassInfo,
    DiffResult,
    FunctionDiff,
    FunctionInfo,
    ModuleDiff,
    ModuleInfo,
    PackageInfo,
    ParameterInfo,
    VariableDiff,
    VariableInfo,
    _deserialize_envelope,
    _serialize_envelope,
)

# ---------------------------------------------------------------------------
# Roundtrip tests: asdict → from_dict
# ---------------------------------------------------------------------------


class TestParameterInfoRoundtrip:
    def test_full(self) -> None:
        p = ParameterInfo(name="x", annotation="int", default="0", kind="KEYWORD_ONLY")
        assert ParameterInfo.from_dict(dataclasses.asdict(p)) == p

    def test_minimal(self) -> None:
        p = ParameterInfo(name="args")
        assert ParameterInfo.from_dict(dataclasses.asdict(p)) == p


class TestFunctionInfoRoundtrip:
    def test_with_params(self) -> None:
        f = FunctionInfo(
            name="run",
            qualname="Runner.run",
            parameters=[
                ParameterInfo(name="self"),
                ParameterInfo(name="timeout", annotation="float", default="30"),
            ],
            return_annotation="bool",
            docstring="Run the task.",
            decorators=["classmethod"],
            is_async=True,
            is_classmethod=True,
            line_number=42,
        )
        assert FunctionInfo.from_dict(dataclasses.asdict(f)) == f

    def test_minimal(self) -> None:
        f = FunctionInfo(name="noop")
        assert FunctionInfo.from_dict(dataclasses.asdict(f)) == f


class TestVariableInfoRoundtrip:
    def test_type_alias(self) -> None:
        v = VariableInfo(
            name="Callback",
            annotation="TypeAlias",
            value="Callable[..., None]",
            is_type_alias=True,
        )
        assert VariableInfo.from_dict(dataclasses.asdict(v)) == v

    def test_plain(self) -> None:
        v = VariableInfo(name="VERSION", value="'1.0'")
        assert VariableInfo.from_dict(dataclasses.asdict(v)) == v


class TestClassInfoRoundtrip:
    def test_nested(self) -> None:
        inner = ClassInfo(name="Inner", bases=["Base"])
        c = ClassInfo(
            name="Outer",
            qualname="Outer",
            bases=["ABC"],
            docstring="Outer class.",
            methods=[FunctionInfo(name="run", return_annotation="None")],
            class_variables=[VariableInfo(name="x", annotation="int")],
            decorators=["dataclass"],
            inner_classes=[inner],
            line_number=10,
        )
        assert ClassInfo.from_dict(dataclasses.asdict(c)) == c


class TestModuleInfoRoundtrip:
    def test_full(self) -> None:
        m = ModuleInfo(
            name="pkg.core",
            path="/fake/path.py",
            docstring="Core module.",
            classes=[ClassInfo(name="Foo")],
            functions=[FunctionInfo(name="bar")],
            variables=[VariableInfo(name="X", value="1")],
            all_exports=["Foo", "bar"],
            submodules=["pkg.core.sub"],
            stub_source="colocated",
        )
        assert ModuleInfo.from_dict(dataclasses.asdict(m)) == m


class TestPackageInfoRoundtrip:
    def test_full(self) -> None:
        pkg = PackageInfo(
            name="mypkg",
            version="1.0.0",
            summary="A test package.",
            readme="# Hello",
            modules=[
                ModuleInfo(
                    name="mypkg",
                    functions=[FunctionInfo(name="main")],
                ),
            ],
        )
        assert PackageInfo.from_dict(dataclasses.asdict(pkg)) == pkg

    def test_empty(self) -> None:
        pkg = PackageInfo(name="empty")
        assert PackageInfo.from_dict(dataclasses.asdict(pkg)) == pkg

    def test_none_fields(self) -> None:
        pkg = PackageInfo(name="x", version=None, summary=None, readme=None)
        result = PackageInfo.from_dict(dataclasses.asdict(pkg))
        assert result.version is None
        assert result.summary is None
        assert result.readme is None

    def test_empty_lists(self) -> None:
        pkg = PackageInfo(name="x", modules=[])
        result = PackageInfo.from_dict(dataclasses.asdict(pkg))
        assert result.modules == []


# ---------------------------------------------------------------------------
# from_dict tolerance
# ---------------------------------------------------------------------------


class TestFromDictTolerance:
    def test_unknown_field_ignored(self) -> None:
        data = {"name": "x", "future_field": True, "another": [1, 2]}
        p = ParameterInfo.from_dict(data)
        assert p.name == "x"

    def test_optional_field_absent(self) -> None:
        data = {"name": "x"}
        p = ParameterInfo.from_dict(data)
        assert p.annotation is None
        assert p.default is None
        assert p.kind == "POSITIONAL_OR_KEYWORD"

    def test_required_field_absent(self) -> None:
        with pytest.raises(KeyError):
            ParameterInfo.from_dict({})

    def test_function_missing_optional(self) -> None:
        data = {"name": "f"}
        f = FunctionInfo.from_dict(data)
        assert f.parameters == []
        assert f.is_async is False

    def test_module_missing_stub_source(self) -> None:
        """Forward compatibility: older JSON without stub_source."""
        data = {"name": "mod"}
        m = ModuleInfo.from_dict(data)
        assert m.stub_source == ""

    def test_variable_missing_is_type_alias(self) -> None:
        """Forward compatibility: older JSON without is_type_alias."""
        data = {"name": "X"}
        v = VariableInfo.from_dict(data)
        assert v.is_type_alias is False


# ---------------------------------------------------------------------------
# JSON envelope
# ---------------------------------------------------------------------------


class TestSerializeEnvelope:
    def test_structure(self) -> None:
        data = {"name": "pkg"}
        envelope = _serialize_envelope(data)
        assert envelope["schema_version"] == _SCHEMA_VERSION
        assert envelope["generator"] == "libcontext"
        assert envelope["data"] == data

    def test_custom_version(self) -> None:
        envelope = _serialize_envelope({"x": 1}, schema_version=99)
        assert envelope["schema_version"] == 99


class TestDeserializeEnvelope:
    def test_valid(self) -> None:
        raw = {
            "schema_version": _SCHEMA_VERSION,
            "generator": "libcontext",
            "data": {"name": "pkg"},
        }
        assert _deserialize_envelope(raw) == {"name": "pkg"}

    def test_wrong_version(self) -> None:
        raw = {"schema_version": 999, "data": {}}
        with pytest.raises(ValueError, match="Unsupported schema version"):
            _deserialize_envelope(raw)

    def test_missing_version(self) -> None:
        raw = {"data": {}}
        with pytest.raises(ValueError, match="Unsupported schema version"):
            _deserialize_envelope(raw)


# ---------------------------------------------------------------------------
# Diff model from_dict roundtrips
# ---------------------------------------------------------------------------


class TestVariableDiffRoundtrip:
    def test_full(self) -> None:
        vd = VariableDiff(name="X", is_breaking=True, changes=["type changed"])
        assert VariableDiff.from_dict(dataclasses.asdict(vd)) == vd

    def test_minimal(self) -> None:
        vd = VariableDiff(name="Y")
        assert VariableDiff.from_dict(dataclasses.asdict(vd)) == vd


class TestFunctionDiffRoundtrip:
    def test_full(self) -> None:
        fd = FunctionDiff(name="f", is_breaking=True, changes=["param removed"])
        assert FunctionDiff.from_dict(dataclasses.asdict(fd)) == fd

    def test_minimal(self) -> None:
        fd = FunctionDiff(name="g")
        assert FunctionDiff.from_dict(dataclasses.asdict(fd)) == fd


class TestClassDiffRoundtrip:
    def test_full(self) -> None:
        cd = ClassDiff(
            name="C",
            is_breaking=True,
            changes=["base removed"],
            added_methods=["new_m"],
            removed_methods=["old_m"],
            modified_methods=[FunctionDiff(name="m", changes=["return changed"])],
            added_variables=["new_v"],
            removed_variables=["old_v"],
            modified_variables=[VariableDiff(name="v", changes=["type changed"])],
        )
        assert ClassDiff.from_dict(dataclasses.asdict(cd)) == cd


class TestModuleDiffRoundtrip:
    def test_full(self) -> None:
        md = ModuleDiff(
            module_name="pkg.core",
            added_functions=["new_f"],
            removed_functions=["old_f"],
            modified_functions=[FunctionDiff(name="f")],
            added_classes=["NewC"],
            removed_classes=["OldC"],
            modified_classes=[ClassDiff(name="C")],
            added_variables=["new_v"],
            removed_variables=["old_v"],
            modified_variables=[VariableDiff(name="v")],
        )
        assert ModuleDiff.from_dict(dataclasses.asdict(md)) == md


class TestDiffResultRoundtrip:
    def test_full(self) -> None:
        dr = DiffResult(
            package_name="mypkg",
            old_version="1.0",
            new_version="2.0",
            added_modules=["new_mod"],
            removed_modules=["old_mod"],
            modified_modules=[ModuleDiff(module_name="mypkg.core")],
        )
        assert DiffResult.from_dict(dataclasses.asdict(dr)) == dr


# ---------------------------------------------------------------------------
# has_breaking_changes with modified functions/classes
# ---------------------------------------------------------------------------


class TestHasBreakingChanges:
    def test_breaking_via_modified_function(self) -> None:
        dr = DiffResult(
            package_name="mypkg",
            modified_modules=[
                ModuleDiff(
                    module_name="mypkg.core",
                    modified_functions=[FunctionDiff(name="f", is_breaking=True)],
                ),
            ],
        )
        assert dr.has_breaking_changes is True

    def test_breaking_via_modified_class(self) -> None:
        dr = DiffResult(
            package_name="mypkg",
            modified_modules=[
                ModuleDiff(
                    module_name="mypkg.core",
                    modified_classes=[ClassDiff(name="C", is_breaking=True)],
                ),
            ],
        )
        assert dr.has_breaking_changes is True

    def test_not_breaking_non_breaking_modifications(self) -> None:
        dr = DiffResult(
            package_name="mypkg",
            modified_modules=[
                ModuleDiff(
                    module_name="mypkg.core",
                    modified_functions=[FunctionDiff(name="f", is_breaking=False)],
                    modified_classes=[ClassDiff(name="C", is_breaking=False)],
                ),
            ],
        )
        assert dr.has_breaking_changes is False
