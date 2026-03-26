"""libcontext — Generate LLM-optimised context from Python library APIs.

This library inspects Python packages using AST-based static analysis
and produces structured Markdown documentation designed to give GitHub
Copilot (or any LLM) the best possible understanding of a library's
public API.

Quick start::

    from libcontext import collect_package, render_package

    pkg = collect_package("requests")
    print(render_package(pkg))

Or from the command line::

    libctx inspect requests -o .github/copilot-instructions.md
"""

import importlib.metadata
import logging

from .collector import collect_package, find_package_path, suggest_similar_packages
from .config import LibcontextConfig
from .diff import diff_packages
from .exceptions import (
    ConfigError,
    EnvironmentSetupError,
    InspectionError,
    LibcontextError,
    PackageNotFoundError,
)
from .inspector import inspect_file, inspect_source
from .models import (
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
)
from .renderer import (
    inject_into_file,
    render_diff,
    render_module,
    render_package,
    render_package_overview,
    search_package,
    search_package_structured,
)

# Library best practice: add NullHandler to prevent "No handlers could be found"
# warnings when libcontext is used as a library (not via CLI).
logging.getLogger(__name__).addHandler(logging.NullHandler())

try:
    __version__ = importlib.metadata.version("libcontext")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0-dev"

__all__ = [
    "ClassDiff",
    "ClassInfo",
    "ConfigError",
    "DiffResult",
    "EnvironmentSetupError",
    "FunctionDiff",
    "FunctionInfo",
    "InspectionError",
    "LibcontextConfig",
    "LibcontextError",
    "ModuleDiff",
    "ModuleInfo",
    "PackageInfo",
    "PackageNotFoundError",
    "ParameterInfo",
    "VariableDiff",
    "VariableInfo",
    "collect_package",
    "diff_packages",
    "find_package_path",
    "inject_into_file",
    "inspect_file",
    "inspect_source",
    "render_diff",
    "render_module",
    "render_package",
    "render_package_overview",
    "search_package",
    "search_package_structured",
    "suggest_similar_packages",
]
