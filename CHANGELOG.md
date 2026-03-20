# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Stub file support**: `.pyi` stub files are discovered (colocated and standalone stub packages) and merged with `.py` sources — signatures from stubs, docstrings from sources.
- **Overload grouping**: `@typing.overload`-decorated functions are grouped into a single entry showing all signatures in one code block.
- **Type alias rendering**: PEP 613 (`TypeAlias`) and PEP 695 (`type X = T`) type aliases are detected via AST analysis and rendered in dedicated "Type Aliases" sections.
- **JSON output**: `--format json` flag for all CLI modes; versioned JSON envelope with `schema_version`; `from_dict()` classmethods on all model dataclasses; `search_package_structured()` for programmatic search results.
- **API diff**: `libctx diff old.json new.json` compares two API snapshots and reports added, removed, and modified symbols with breaking change detection; `render_diff()` Markdown output; `--format json` support.
- **Search enhancements**: `--type` filter (`class`, `function`, `variable`, `alias`); docstring search with preview annotations.
- **Persistent disk cache**: Caches collected `PackageInfo` as JSON on disk; invalidation by `(version, max_mtime, file_count)`; LRU eviction (max 50 entries); `--no-cache` flag; `libctx cache clear` subcommand.

### Changed

- `models.py` now includes diff dataclasses (`DiffResult`, `ModuleDiff`, `ClassDiff`, `FunctionDiff`, `VariableDiff`) and JSON envelope utilities.
- `renderer.py` now exports `search_package_structured()` and `render_diff()`.
- `collector.py` integrates the disk cache automatically for installed packages with version metadata.
- MCP server `search_api` tool now accepts `kind` and `format` parameters; supports JSON structured output.
- MCP server `get_api_json` tool now accepts an optional `module_name` for single-module extraction.
- MCP server `refresh_cache` tool now clears both in-memory (LRU) and disk caches.
- MCP server adds `diff_api` tool for comparing two API snapshots directly from the IDE.
- `/lib` skill now documents `--type` filter, `--no-cache`, `--format json`, and diff workflow.

## [0.2.0] - 2026-03-18

### Added

- Progressive disclosure CLI flags: `--overview`, `--module`, `--search` for on-demand API inspection.
- `libctx install` subcommand with `--skills`, `--mcp`, `--all`, and `--target` options.
- `/lib` skill for Claude Code and GitHub Copilot — on-demand library discovery via slash command.
- MCP server (`libctx-mcp`) for VS Code / Cursor integration with `get_package_overview`, `get_module_api`, `search_api`, and `refresh_cache` tools.
- `render_module()`, `render_package_overview()`, and `search_package()` public API functions.
- Optional `[mcp]` extra for MCP server dependencies (requires Python 3.10+).
- Non-destructive JSON merge for MCP config files (preserves existing entries).

### Changed

- CLI restructured as a click Group with `inspect` and `install` subcommands.

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

[Unreleased]: https://github.com/Syclaw/libcontext/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Syclaw/libcontext/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Syclaw/libcontext/releases/tag/v0.1.0
