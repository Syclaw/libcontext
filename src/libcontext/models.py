"""Data models for representing Python code components."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParameterInfo:
    """Represents a function/method parameter."""

    name: str
    annotation: str | None = None
    default: str | None = None
    kind: str = "POSITIONAL_OR_KEYWORD"


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


@dataclass
class VariableInfo:
    """Represents a module-level or class-level variable/constant."""

    name: str
    annotation: str | None = None
    value: str | None = None
    line_number: int | None = None


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
    inner_classes: list[ClassInfo] = field(default_factory=list)
    line_number: int | None = None


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

    @property
    def non_empty_modules(self) -> list[ModuleInfo]:
        """Return only modules with content."""
        return [m for m in self.modules if not m.is_empty]
