"""Exception hierarchy for libcontext.

All exceptions raised by the public API inherit from :class:`LibcontextError`,
allowing callers to catch library errors selectively::

    try:
        pkg = collect_package("some-lib")
    except LibcontextError as exc:
        ...  # any libcontext error
"""

from __future__ import annotations


class LibcontextError(Exception):
    """Base exception for all libcontext errors."""


class PackageNotFoundError(LibcontextError):
    """Raised when a requested package cannot be located.

    Attributes:
        package_name: The name that was looked up.
        suggestions: Similar package names found in the environment.
    """

    def __init__(
        self,
        package_name: str,
        suggestions: list[str] | None = None,
    ) -> None:
        self.package_name = package_name
        self.suggestions = suggestions or []
        msg = f"Package '{package_name}' not found."
        if self.suggestions:
            joined = ", ".join(self.suggestions)
            msg += f" Did you mean: {joined}?"
        else:
            msg += (
                " Make sure it is installed in the current environment."
                " If installed in a project venv, run from the project"
                " directory or use --python <path-to-venv>."
            )
        super().__init__(msg)


class ConfigError(LibcontextError):
    """Raised when ``[tool.libcontext]`` configuration is invalid.

    Attributes:
        detail: Human-readable description of the validation failure.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class EnvironmentSetupError(LibcontextError):
    """Raised when a target Python environment cannot be resolved or queried.

    Attributes:
        python_path: The path that was supplied by the user.
    """

    def __init__(self, python_path: str, reason: str) -> None:
        self.python_path = python_path
        super().__init__(f"Cannot use environment '{python_path}': {reason}")


class InspectionError(LibcontextError):
    """Raised when a source file cannot be parsed or read.

    Wraps underlying :class:`SyntaxError`, :class:`OSError`, or
    :class:`UnicodeDecodeError` with the file path that caused the failure.

    Attributes:
        file_path: Path to the problematic file.
    """

    def __init__(self, file_path: str, reason: str) -> None:
        self.file_path = file_path
        super().__init__(f"Cannot inspect '{file_path}': {reason}")
