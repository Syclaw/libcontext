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

    libctx requests -o .github/copilot-instructions.md
"""

from __future__ import annotations

import logging

from .collector import collect_package, find_package_path
from .config import LibcontextConfig
from .inspector import inspect_file, inspect_source
from .models import (
    ClassInfo,
    FunctionInfo,
    ModuleInfo,
    PackageInfo,
    ParameterInfo,
    VariableInfo,
)
from .renderer import inject_into_file, render_package

# Library best practice: add NullHandler to prevent "No handlers could be found"
# warnings when libcontext is used as a library (not via CLI).
logging.getLogger(__name__).addHandler(logging.NullHandler())

__version__ = "0.1.0"

__all__ = [
    "ClassInfo",
    "FunctionInfo",
    "LibcontextConfig",
    "ModuleInfo",
    "PackageInfo",
    "ParameterInfo",
    "VariableInfo",
    "collect_package",
    "find_package_path",
    "inject_into_file",
    "inspect_file",
    "inspect_source",
    "render_package",
]
