# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-02-13

### Added

- Initial release of libcontext.
- AST-based static analysis of Python packages (no code execution).
- CLI command `libctx` to generate Markdown context files.
- Support for inspecting any installed Python package by name.
- Support for inspecting local package directories by path.
- Extraction of classes, methods, functions, parameters, type annotations, decorators, and docstrings.
- Automatic README discovery via `importlib.metadata` and filesystem search.
- Marker-based injection (`<!-- BEGIN/END LIBCONTEXT -->`) for updating existing files without overwriting.
- Optional `[tool.libcontext]` configuration in `pyproject.toml` for library authors.
- Module include/exclude filtering.
- Private member filtering with `--include-private` override.
- Multi-package support in a single CLI invocation.
- Intelligent dunder method filtering (includes useful ones like `__init__`, `__call__`, etc.).
- Respects `__all__` when defined in modules.
- Positional-only, keyword-only, `*args`, and `**kwargs` parameter handling.
- Inner class and decorated class support.
- README truncation with configurable line limit.
- Free-form `extra_context` field for library authors.
- Python API for programmatic usage (`collect_package`, `render_package`).

[Unreleased]: https://github.com/Syclaw/libcontext/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Syclaw/libcontext/releases/tag/v0.1.0
