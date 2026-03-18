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
    """

    def __init__(self, package_name: str) -> None:
        self.package_name = package_name
        super().__init__(
            f"Package '{package_name}' not found. "
            "Make sure it is installed in the current environment."
        )


class ConfigError(LibcontextError):
    """Raised when ``[tool.libcontext]`` configuration is invalid.

    Attributes:
        detail: Human-readable description of the validation failure.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


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
