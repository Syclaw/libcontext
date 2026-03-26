"""API diff — compare two PackageInfo snapshots and identify changes."""

import logging

from .models import (
    ClassDiff,
    ClassInfo,
    DiffResult,
    FunctionDiff,
    FunctionInfo,
    ModuleDiff,
    ModuleInfo,
    PackageInfo,
    VariableDiff,
    VariableInfo,
)

logger = logging.getLogger(__name__)


def diff_packages(old: PackageInfo, new: PackageInfo) -> DiffResult:
    """Compare two versions of a package and produce a structured diff.

    Compares at every level (modules, classes, functions, variables) and
    marks breaking changes.

    Args:
        old: The previous version's PackageInfo.
        new: The current version's PackageInfo.

    Returns:
        DiffResult describing all changes.
    """
    if old.name != new.name:
        logger.warning(
            "Comparing packages with different names: %s vs %s",
            old.name,
            new.name,
        )

    old_mods = {m.name: m for m in old.modules}
    new_mods = {m.name: m for m in new.modules}

    added = sorted(new_mods.keys() - old_mods.keys())
    removed = sorted(old_mods.keys() - new_mods.keys())

    modified: list[ModuleDiff] = []
    for name in sorted(old_mods.keys() & new_mods.keys()):
        mod_diff = _diff_module(old_mods[name], new_mods[name])
        if mod_diff is not None:
            modified.append(mod_diff)

    return DiffResult(
        package_name=new.name,
        old_version=old.version,
        new_version=new.version,
        added_modules=added,
        removed_modules=removed,
        modified_modules=modified,
    )


def _diff_module(old: ModuleInfo, new: ModuleInfo) -> ModuleDiff | None:
    """Compare two module snapshots."""
    old_funcs = {f.name: f for f in old.functions}
    new_funcs = {f.name: f for f in new.functions}

    old_classes = {c.name: c for c in old.classes}
    new_classes = {c.name: c for c in new.classes}

    old_vars = {v.name: v for v in old.variables}
    new_vars = {v.name: v for v in new.variables}

    added_funcs = sorted(new_funcs.keys() - old_funcs.keys())
    removed_funcs = sorted(old_funcs.keys() - new_funcs.keys())

    added_classes = sorted(new_classes.keys() - old_classes.keys())
    removed_classes = sorted(old_classes.keys() - new_classes.keys())

    added_vars = sorted(new_vars.keys() - old_vars.keys())
    removed_vars = sorted(old_vars.keys() - new_vars.keys())

    modified_funcs: list[FunctionDiff] = []
    for name in sorted(old_funcs.keys() & new_funcs.keys()):
        fd = _diff_function(old_funcs[name], new_funcs[name])
        if fd is not None:
            modified_funcs.append(fd)

    modified_classes: list[ClassDiff] = []
    for name in sorted(old_classes.keys() & new_classes.keys()):
        cd = _diff_class(old_classes[name], new_classes[name])
        if cd is not None:
            modified_classes.append(cd)

    modified_vars: list[VariableDiff] = []
    for name in sorted(old_vars.keys() & new_vars.keys()):
        vd = _diff_variable(old_vars[name], new_vars[name])
        if vd is not None:
            modified_vars.append(vd)

    if not any(
        [
            added_funcs,
            removed_funcs,
            modified_funcs,
            added_classes,
            removed_classes,
            modified_classes,
            added_vars,
            removed_vars,
            modified_vars,
        ]
    ):
        return None

    return ModuleDiff(
        module_name=old.name,
        added_functions=added_funcs,
        removed_functions=removed_funcs,
        modified_functions=modified_funcs,
        added_classes=added_classes,
        removed_classes=removed_classes,
        modified_classes=modified_classes,
        added_variables=added_vars,
        removed_variables=removed_vars,
        modified_variables=modified_vars,
    )


def _diff_function(
    old: FunctionInfo,
    new: FunctionInfo,
) -> FunctionDiff | None:
    """Compare two function snapshots."""
    changes: list[str] = []
    is_breaking = False

    # Return type
    if old.return_annotation != new.return_annotation:
        old_ret = old.return_annotation or "None"
        new_ret = new.return_annotation or "None"
        changes.append(f"return type changed: {old_ret} → {new_ret}")

    # Async
    if old.is_async != new.is_async:
        is_breaking = True
        if new.is_async:
            changes.append("changed from sync to async")
        else:
            changes.append("changed from async to sync")

    # Decorators
    if set(old.decorators) != set(new.decorators):
        changes.append("decorators changed")

    # Parameters
    old_params = {p.name: p for p in old.parameters}
    new_params = {p.name: p for p in new.parameters}

    for pname in sorted(new_params.keys() - old_params.keys()):
        p = new_params[pname]
        if p.default is None and p.name not in ("self", "cls"):
            is_breaking = True
            changes.append(f"required parameter '{pname}' added")
        else:
            changes.append(f"optional parameter '{pname}' added")

    for pname in sorted(old_params.keys() - new_params.keys()):
        if pname not in ("self", "cls"):
            is_breaking = True
            changes.append(f"parameter '{pname}' removed")

    for pname in sorted(old_params.keys() & new_params.keys()):
        op = old_params[pname]
        np = new_params[pname]

        if op.annotation != np.annotation:
            old_ann = op.annotation or "untyped"
            new_ann = np.annotation or "untyped"
            changes.append(f"parameter '{pname}' type changed: {old_ann} → {new_ann}")

        if (
            op.default is not None
            and np.default is None
            and pname not in ("self", "cls")
        ):
            is_breaking = True
            changes.append(f"parameter '{pname}' now required")

    if not changes:
        return None

    return FunctionDiff(
        name=old.name,
        is_breaking=is_breaking,
        changes=changes,
    )


def _diff_class(old: ClassInfo, new: ClassInfo) -> ClassDiff | None:
    """Compare two class snapshots."""
    changes: list[str] = []
    is_breaking = False

    # Bases
    old_bases = set(old.bases)
    new_bases = set(new.bases)
    for base in sorted(old_bases - new_bases):
        is_breaking = True
        changes.append(f"base class '{base}' removed")
    for base in sorted(new_bases - old_bases):
        changes.append(f"base class '{base}' added")

    # Decorators
    if set(old.decorators) != set(new.decorators):
        changes.append("decorators changed")

    # Methods
    old_methods = {m.name: m for m in old.methods}
    new_methods = {m.name: m for m in new.methods}

    added_methods = sorted(new_methods.keys() - old_methods.keys())
    removed_methods = sorted(old_methods.keys() - new_methods.keys())
    if removed_methods:
        is_breaking = True

    modified_methods: list[FunctionDiff] = []
    for name in sorted(old_methods.keys() & new_methods.keys()):
        fd = _diff_function(old_methods[name], new_methods[name])
        if fd is not None:
            modified_methods.append(fd)
            if fd.is_breaking:
                is_breaking = True

    # Class variables
    old_cvars = {v.name: v for v in old.class_variables}
    new_cvars = {v.name: v for v in new.class_variables}

    added_vars = sorted(new_cvars.keys() - old_cvars.keys())
    removed_vars = sorted(old_cvars.keys() - new_cvars.keys())

    modified_vars: list[VariableDiff] = []
    for name in sorted(old_cvars.keys() & new_cvars.keys()):
        vd = _diff_variable(old_cvars[name], new_cvars[name])
        if vd is not None:
            modified_vars.append(vd)

    if not any(
        [
            changes,
            added_methods,
            removed_methods,
            modified_methods,
            added_vars,
            removed_vars,
            modified_vars,
        ]
    ):
        return None

    return ClassDiff(
        name=old.name,
        is_breaking=is_breaking,
        changes=changes,
        added_methods=added_methods,
        removed_methods=removed_methods,
        modified_methods=modified_methods,
        added_variables=added_vars,
        removed_variables=removed_vars,
        modified_variables=modified_vars,
    )


def _diff_variable(
    old: VariableInfo,
    new: VariableInfo,
) -> VariableDiff | None:
    """Compare two variable snapshots."""
    changes: list[str] = []

    if old.annotation != new.annotation:
        old_ann = old.annotation or "untyped"
        new_ann = new.annotation or "untyped"
        changes.append(f"type changed: {old_ann} → {new_ann}")

    if old.value != new.value:
        changes.append("value changed")

    if not changes:
        return None

    return VariableDiff(name=old.name, changes=changes)
