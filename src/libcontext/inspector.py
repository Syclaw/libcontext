"""AST-based Python source code inspector.

Parses Python source files using the `ast` module to extract all public
components: classes, functions, variables, type hints, and docstrings.
This approach is safe (no code execution) and works with any valid Python source.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from .models import (
    ClassInfo,
    FunctionInfo,
    ModuleInfo,
    ParameterInfo,
    VariableInfo,
)

logger = logging.getLogger(__name__)

# Dunder methods that are useful to document
_USEFUL_DUNDERS = frozenset(
    {
        "__init__",
        "__call__",
        "__enter__",
        "__exit__",
        "__aenter__",
        "__aexit__",
        "__getitem__",
        "__setitem__",
        "__delitem__",
        "__len__",
        "__iter__",
        "__next__",
        "__aiter__",
        "__anext__",
        "__contains__",
        "__eq__",
        "__ne__",
        "__lt__",
        "__le__",
        "__gt__",
        "__ge__",
        "__hash__",
        "__repr__",
        "__str__",
        "__bool__",
        "__add__",
        "__sub__",
        "__mul__",
        "__truediv__",
        "__floordiv__",
        "__mod__",
        "__pow__",
        "__and__",
        "__or__",
        "__xor__",
        "__invert__",
        "__neg__",
        "__pos__",
        "__abs__",
        "__int__",
        "__float__",
        "__complex__",
        "__index__",
        "__await__",
        "__get__",
        "__set__",
        "__delete__",
        "__init_subclass__",
        "__class_getitem__",
        "__missing__",
        "__format__",
        "__sizeof__",
        "__reduce__",
        "__copy__",
        "__deepcopy__",
        "__fspath__",
    }
)


def _unparse(node: ast.AST | None) -> str | None:
    """Convert an AST node back to source code string."""
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except (ValueError, TypeError):
        logger.debug("Cannot unparse AST node %s", type(node).__name__)
        return None


def _extract_decorators(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> list[str]:
    """Extract decorator names from a decorated node."""
    return [ast.unparse(dec) for dec in node.decorator_list]


def _extract_parameters(args: ast.arguments) -> list[ParameterInfo]:
    """Extract parameters from function arguments AST node."""
    params: list[ParameterInfo] = []

    # --- Positional-only parameters ---
    num_posonly = len(args.posonlyargs)
    # defaults are shared: last N args get defaults
    # total positional = posonlyargs + args
    total_positional = num_posonly + len(args.args)
    num_no_default = total_positional - len(args.defaults)

    for i, arg in enumerate(args.posonlyargs):
        default_idx = i - num_no_default
        default = _unparse(args.defaults[default_idx]) if default_idx >= 0 else None
        params.append(
            ParameterInfo(
                name=arg.arg,
                annotation=_unparse(arg.annotation),
                default=default,
                kind="POSITIONAL_ONLY",
            )
        )

    # --- Regular positional/keyword parameters ---
    for i, arg in enumerate(args.args):
        default_idx = (num_posonly + i) - num_no_default
        default = _unparse(args.defaults[default_idx]) if default_idx >= 0 else None
        params.append(
            ParameterInfo(
                name=arg.arg,
                annotation=_unparse(arg.annotation),
                default=default,
                kind="POSITIONAL_OR_KEYWORD",
            )
        )

    # --- *args ---
    if args.vararg:
        params.append(
            ParameterInfo(
                name=f"*{args.vararg.arg}",
                annotation=_unparse(args.vararg.annotation),
                kind="VAR_POSITIONAL",
            )
        )

    # --- Keyword-only parameters ---
    for i, arg in enumerate(args.kwonlyargs):
        kw_default = args.kw_defaults[i] if i < len(args.kw_defaults) else None
        default = _unparse(kw_default) if kw_default is not None else None
        params.append(
            ParameterInfo(
                name=arg.arg,
                annotation=_unparse(arg.annotation),
                default=default,
                kind="KEYWORD_ONLY",
            )
        )

    # --- **kwargs ---
    if args.kwarg:
        params.append(
            ParameterInfo(
                name=f"**{args.kwarg.arg}",
                annotation=_unparse(args.kwarg.annotation),
                kind="VAR_KEYWORD",
            )
        )

    return params


def _extract_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    qualname_prefix: str = "",
) -> FunctionInfo:
    """Extract function/method information from an AST node."""
    decorators = _extract_decorators(node)
    qualname = f"{qualname_prefix}.{node.name}" if qualname_prefix else node.name

    return FunctionInfo(
        name=node.name,
        qualname=qualname,
        parameters=_extract_parameters(node.args),
        return_annotation=_unparse(node.returns),
        docstring=ast.get_docstring(node),
        decorators=decorators,
        is_async=isinstance(node, ast.AsyncFunctionDef),
        is_property="property" in decorators,
        is_classmethod="classmethod" in decorators,
        is_staticmethod="staticmethod" in decorators,
        line_number=node.lineno,
    )


def _extract_class(
    node: ast.ClassDef,
    qualname_prefix: str = "",
) -> ClassInfo:
    """Extract class information from an AST node."""
    qualname = f"{qualname_prefix}.{node.name}" if qualname_prefix else node.name
    bases = [ast.unparse(base) for base in node.bases]

    methods: list[FunctionInfo] = []
    class_variables: list[VariableInfo] = []
    inner_classes: list[ClassInfo] = []

    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(_extract_function(item, qualname_prefix=qualname))

        elif isinstance(item, ast.ClassDef):
            inner_classes.append(_extract_class(item, qualname_prefix=qualname))

        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            class_variables.append(
                VariableInfo(
                    name=item.target.id,
                    annotation=_unparse(item.annotation),
                    value=_unparse(item.value),
                    line_number=item.lineno,
                )
            )

        elif isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name):
                    class_variables.append(
                        VariableInfo(
                            name=target.id,
                            value=_unparse(item.value),
                            line_number=item.lineno,
                        )
                    )

    return ClassInfo(
        name=node.name,
        qualname=qualname,
        bases=bases,
        docstring=ast.get_docstring(node),
        methods=methods,
        class_variables=class_variables,
        decorators=_extract_decorators(node),
        inner_classes=inner_classes,
        line_number=node.lineno,
    )


def _extract_list_strings(node: ast.List | ast.Tuple) -> list[str]:
    """Extract string constants from a list/tuple AST node."""
    return [
        elt.value
        for elt in node.elts
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
    ]


def _extract_all_exports(tree: ast.Module) -> list[str] | None:
    """Extract the ``__all__`` list if defined at module level.

    Handles both simple assignment (``__all__ = [...]``) and augmented
    assignment (``__all__ += [...]``).
    """
    exports: list[str] | None = None

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "__all__"
                    and isinstance(node.value, (ast.List, ast.Tuple))
                ):
                    exports = _extract_list_strings(node.value)

        elif (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__all__"
            and isinstance(node.value, (ast.List, ast.Tuple))
        ):
            extra = _extract_list_strings(node.value)
            if exports is None:
                exports = extra
            else:
                exports.extend(extra)

    return exports


def inspect_source(
    source: str,
    module_name: str = "",
    file_path: str = "",
) -> ModuleInfo:
    """Inspect Python source code and extract all components.

    Uses AST parsing (no code execution) to safely extract classes,
    functions, variables, docstrings, and type annotations.

    Args:
        source: Python source code as a string.
        module_name: Fully qualified module name (e.g. ``mypackage.core``).
        file_path: Path to the source file (for reference only).

    Returns:
        ModuleInfo containing all extracted components.
    """
    tree = ast.parse(source)

    classes: list[ClassInfo] = []
    functions: list[FunctionInfo] = []
    variables: list[VariableInfo] = []

    all_exports = _extract_all_exports(tree)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            classes.append(_extract_class(node))

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(_extract_function(node))

        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            variables.append(
                VariableInfo(
                    name=node.target.id,
                    annotation=_unparse(node.annotation),
                    value=_unparse(node.value),
                    line_number=node.lineno,
                )
            )

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    variables.append(
                        VariableInfo(
                            name=target.id,
                            value=_unparse(node.value),
                            line_number=node.lineno,
                        )
                    )

    return ModuleInfo(
        name=module_name,
        path=file_path,
        docstring=ast.get_docstring(tree),
        classes=classes,
        functions=functions,
        variables=variables,
        all_exports=all_exports,
    )


def inspect_file(file_path: Path, module_name: str = "") -> ModuleInfo:
    """Inspect a Python file and extract all components.

    Args:
        file_path: Path to the Python file.
        module_name: Fully qualified module name. If empty, uses the file stem.

    Returns:
        ModuleInfo containing all extracted components.

    Raises:
        SyntaxError: If the file contains invalid Python syntax.
        OSError: If the file cannot be read.
        UnicodeDecodeError: If the file is not valid UTF-8.
    """
    logger.debug(
        "Inspecting file %s (module=%s)",
        file_path,
        module_name or file_path.stem,
    )
    source = file_path.read_text(encoding="utf-8")
    if not module_name:
        module_name = file_path.stem
    return inspect_source(source, module_name=module_name, file_path=str(file_path))


def is_public_member(name: str, is_method: bool = False) -> bool:
    """Determine if a name should be considered public.

    Args:
        name: The symbol name to check.
        is_method: Whether this is a method (allows useful dunder methods).

    Returns:
        True if the name should be included in public API documentation.
    """
    if name.startswith("__") and name.endswith("__"):
        # Dunder: only include if it's a useful one and it's a method
        return is_method and name in _USEFUL_DUNDERS
    return not name.startswith("_")
