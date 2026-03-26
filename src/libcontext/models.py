"""Data models for representing Python code components."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParameterInfo:
    """Represents a function/method parameter."""

    name: str
    annotation: str | None = None
    default: str | None = None
    kind: str = "POSITIONAL_OR_KEYWORD"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParameterInfo":
        """Reconstruct from a dict produced by ``dataclasses.asdict()``."""
        return cls(
            name=data["name"],
            annotation=data.get("annotation"),
            default=data.get("default"),
            kind=data.get("kind", "POSITIONAL_OR_KEYWORD"),
        )


@dataclass
class FunctionInfo:
    """Represents a function or method."""

    name: str
    qualname: str = ""
    parameters: list[ParameterInfo] = field(default_factory=list)
    return_annotation: str | None = None
    docstring: str | None = None
    decorators: list[str] = field(default_factory=list)
    is_async: bool = False
    is_property: bool = False
    is_classmethod: bool = False
    is_staticmethod: bool = False
    line_number: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FunctionInfo":
        """Reconstruct from a dict produced by ``dataclasses.asdict()``."""
        return cls(
            name=data["name"],
            qualname=data.get("qualname", ""),
            parameters=[ParameterInfo.from_dict(p) for p in data.get("parameters", [])],
            return_annotation=data.get("return_annotation"),
            docstring=data.get("docstring"),
            decorators=data.get("decorators", []),
            is_async=data.get("is_async", False),
            is_property=data.get("is_property", False),
            is_classmethod=data.get("is_classmethod", False),
            is_staticmethod=data.get("is_staticmethod", False),
            line_number=data.get("line_number"),
        )


@dataclass
class VariableInfo:
    """Represents a module-level or class-level variable/constant."""

    name: str
    annotation: str | None = None
    value: str | None = None
    line_number: int | None = None
    is_type_alias: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VariableInfo":
        """Reconstruct from a dict produced by ``dataclasses.asdict()``."""
        return cls(
            name=data["name"],
            annotation=data.get("annotation"),
            value=data.get("value"),
            line_number=data.get("line_number"),
            is_type_alias=data.get("is_type_alias", False),
        )


@dataclass
class ClassInfo:
    """Represents a class."""

    name: str
    qualname: str = ""
    bases: list[str] = field(default_factory=list)
    docstring: str | None = None
    methods: list[FunctionInfo] = field(default_factory=list)
    class_variables: list[VariableInfo] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    inner_classes: "list[ClassInfo]" = field(default_factory=list)
    line_number: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClassInfo":
        """Reconstruct from a dict produced by ``dataclasses.asdict()``."""
        return cls(
            name=data["name"],
            qualname=data.get("qualname", ""),
            bases=data.get("bases", []),
            docstring=data.get("docstring"),
            methods=[FunctionInfo.from_dict(m) for m in data.get("methods", [])],
            class_variables=[
                VariableInfo.from_dict(v) for v in data.get("class_variables", [])
            ],
            decorators=data.get("decorators", []),
            inner_classes=[
                ClassInfo.from_dict(c) for c in data.get("inner_classes", [])
            ],
            line_number=data.get("line_number"),
        )


@dataclass
class ModuleInfo:
    """Represents a Python module."""

    name: str
    path: str = ""
    docstring: str | None = None
    classes: list[ClassInfo] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    variables: list[VariableInfo] = field(default_factory=list)
    all_exports: list[str] | None = None  # __all__ if defined
    submodules: list[str] = field(default_factory=list)
    stub_source: str = ""  # "" | "colocated" | "standalone"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModuleInfo":
        """Reconstruct from a dict produced by ``dataclasses.asdict()``."""
        return cls(
            name=data["name"],
            path=data.get("path", ""),
            docstring=data.get("docstring"),
            classes=[ClassInfo.from_dict(c) for c in data.get("classes", [])],
            functions=[FunctionInfo.from_dict(f) for f in data.get("functions", [])],
            variables=[VariableInfo.from_dict(v) for v in data.get("variables", [])],
            all_exports=data.get("all_exports"),
            submodules=data.get("submodules", []),
            stub_source=data.get("stub_source", ""),
        )

    @property
    def is_empty(self) -> bool:
        """Check if the module has no public content."""
        return not (self.classes or self.functions or self.variables or self.docstring)


@dataclass
class PackageInfo:
    """Represents a complete Python package."""

    name: str
    version: str | None = None
    summary: str | None = None
    readme: str | None = None
    modules: list[ModuleInfo] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PackageInfo":
        """Reconstruct from a dict produced by ``dataclasses.asdict()``."""
        return cls(
            name=data["name"],
            version=data.get("version"),
            summary=data.get("summary"),
            readme=data.get("readme"),
            modules=[ModuleInfo.from_dict(m) for m in data.get("modules", [])],
        )

    @property
    def non_empty_modules(self) -> list[ModuleInfo]:
        """Return only modules with content."""
        return [m for m in self.modules if not m.is_empty]


# ---------------------------------------------------------------------------
# Diff models
# ---------------------------------------------------------------------------


@dataclass
class VariableDiff:
    """Diff for a single variable."""

    name: str
    is_breaking: bool = False
    changes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VariableDiff":
        """Reconstruct from a dict produced by ``dataclasses.asdict()``."""
        return cls(
            name=data["name"],
            is_breaking=data.get("is_breaking", False),
            changes=data.get("changes", []),
        )


@dataclass
class FunctionDiff:
    """Diff for a single function."""

    name: str
    is_breaking: bool = False
    changes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FunctionDiff":
        """Reconstruct from a dict produced by ``dataclasses.asdict()``."""
        return cls(
            name=data["name"],
            is_breaking=data.get("is_breaking", False),
            changes=data.get("changes", []),
        )


@dataclass
class ClassDiff:
    """Diff for a single class."""

    name: str
    is_breaking: bool = False
    changes: list[str] = field(default_factory=list)
    added_methods: list[str] = field(default_factory=list)
    removed_methods: list[str] = field(default_factory=list)
    modified_methods: list[FunctionDiff] = field(default_factory=list)
    added_variables: list[str] = field(default_factory=list)
    removed_variables: list[str] = field(default_factory=list)
    modified_variables: list[VariableDiff] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClassDiff":
        """Reconstruct from a dict produced by ``dataclasses.asdict()``."""
        return cls(
            name=data["name"],
            is_breaking=data.get("is_breaking", False),
            changes=data.get("changes", []),
            added_methods=data.get("added_methods", []),
            removed_methods=data.get("removed_methods", []),
            modified_methods=[
                FunctionDiff.from_dict(m) for m in data.get("modified_methods", [])
            ],
            added_variables=data.get("added_variables", []),
            removed_variables=data.get("removed_variables", []),
            modified_variables=[
                VariableDiff.from_dict(v) for v in data.get("modified_variables", [])
            ],
        )


@dataclass
class ModuleDiff:
    """Diff for a single module."""

    module_name: str
    added_functions: list[str] = field(default_factory=list)
    removed_functions: list[str] = field(default_factory=list)
    modified_functions: list[FunctionDiff] = field(default_factory=list)
    added_classes: list[str] = field(default_factory=list)
    removed_classes: list[str] = field(default_factory=list)
    modified_classes: list[ClassDiff] = field(default_factory=list)
    added_variables: list[str] = field(default_factory=list)
    removed_variables: list[str] = field(default_factory=list)
    modified_variables: list[VariableDiff] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModuleDiff":
        """Reconstruct from a dict produced by ``dataclasses.asdict()``."""
        return cls(
            module_name=data["module_name"],
            added_functions=data.get("added_functions", []),
            removed_functions=data.get("removed_functions", []),
            modified_functions=[
                FunctionDiff.from_dict(f) for f in data.get("modified_functions", [])
            ],
            added_classes=data.get("added_classes", []),
            removed_classes=data.get("removed_classes", []),
            modified_classes=[
                ClassDiff.from_dict(c) for c in data.get("modified_classes", [])
            ],
            added_variables=data.get("added_variables", []),
            removed_variables=data.get("removed_variables", []),
            modified_variables=[
                VariableDiff.from_dict(v) for v in data.get("modified_variables", [])
            ],
        )


@dataclass
class DiffResult:
    """Complete diff between two package versions."""

    package_name: str
    old_version: str | None = None
    new_version: str | None = None
    added_modules: list[str] = field(default_factory=list)
    removed_modules: list[str] = field(default_factory=list)
    modified_modules: list[ModuleDiff] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DiffResult":
        """Reconstruct from a dict produced by ``dataclasses.asdict()``."""
        return cls(
            package_name=data["package_name"],
            old_version=data.get("old_version"),
            new_version=data.get("new_version"),
            added_modules=data.get("added_modules", []),
            removed_modules=data.get("removed_modules", []),
            modified_modules=[
                ModuleDiff.from_dict(m) for m in data.get("modified_modules", [])
            ],
        )

    @property
    def has_breaking_changes(self) -> bool:
        """Check if any change in the diff is breaking."""
        if self.removed_modules:
            return True
        for mod in self.modified_modules:
            if mod.removed_functions or mod.removed_classes:
                return True
            if any(fd.is_breaking for fd in mod.modified_functions):
                return True
            if any(cd.is_breaking for cd in mod.modified_classes):
                return True
        return False

    @property
    def is_empty(self) -> bool:
        """Check if there are no changes."""
        return not (self.added_modules or self.removed_modules or self.modified_modules)


# ---------------------------------------------------------------------------
# JSON envelope
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = 1


def _serialize_envelope(
    data: dict[str, Any],
    schema_version: int = _SCHEMA_VERSION,
) -> dict[str, Any]:
    """Wrap serialized data in a versioned envelope."""
    return {
        "schema_version": schema_version,
        "generator": "libcontext",
        "data": data,
    }


def _deserialize_envelope(raw: dict[str, Any]) -> dict[str, Any]:
    """Unwrap and validate a versioned JSON envelope.

    Args:
        raw: Parsed JSON dict.

    Returns:
        The ``data`` dict inside the envelope.

    Raises:
        ValueError: If the schema version is unsupported.
    """
    version = raw.get("schema_version")
    if version != _SCHEMA_VERSION:
        msg = (
            f"Unsupported schema version {version!r}. "
            f"Expected {_SCHEMA_VERSION}. Upgrade libcontext."
        )
        raise ValueError(msg)
    data: dict[str, Any] = raw["data"]
    return data
