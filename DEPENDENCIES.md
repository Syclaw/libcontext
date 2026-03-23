# Dependencies and Licenses

This document lists all dependencies used by **libcontext** and their respective licenses.

## Runtime Dependencies

| Package | Version | License | Description |
|---------|---------|---------|-------------|
| [click](https://pypi.org/project/click/) | >=8.0 | BSD-3-Clause | Composable command line interface toolkit. |
| [tomli](https://pypi.org/project/tomli/) | >=1.0 | MIT | A lil' TOML parser. Only required for Python < 3.11 (replaced by `tomllib` in the standard library). |

## Optional Dependencies (`[mcp]` extra)

| Package | Version | License | Description |
|---------|---------|---------|-------------|
| [mcp[cli]](https://pypi.org/project/mcp/) | >=1.0 | MIT | Model Context Protocol SDK with CLI extras. Requires Python >= 3.10. Enables the `libctx-mcp` server for VS Code / Cursor integration. |

## Development Dependencies

| Package | Version | License | Description |
|---------|---------|---------|-------------|
| [pytest](https://pypi.org/project/pytest/) | >=8.4.2 | MIT | Testing framework. |
| [pytest-cov](https://pypi.org/project/pytest-cov/) | >=7.0.0 | MIT | Coverage plugin for pytest. |
| [ruff](https://pypi.org/project/ruff/) | >=0.15.1 | MIT | Fast Python linter and formatter (replaces flake8, isort, black, pyupgrade). |
| [mypy](https://pypi.org/project/mypy/) | >=1.19.1 | MIT | Static type checker for Python. |

## Build Dependencies

| Package | Version | License | Description |
|---------|---------|---------|-------------|
| [hatchling](https://pypi.org/project/hatchling/) | * | MIT | Build backend (PEP 517). |

## Standard Library Modules Used

The following standard library modules are used and require **no additional installation**:

- `ast` — Abstract Syntax Trees (core of the inspection engine)
- `contextlib` — Context managers (cache file handling)
- `copy` — Deep copy of data structures (stub merging)
- `dataclasses` — Data model definitions
- `datetime` — Timestamp handling (cache metadata)
- `difflib` — Fuzzy matching (similar package name suggestions)
- `functools` — LRU cache (MCP server in-memory caching)
- `importlib.metadata` — Package metadata access
- `importlib.util` — Package location discovery
- `json` — JSON serialization (cache, MCP config, JSON output)
- `logging` — Diagnostic logging
- `os` — OS-level operations (cache directory, file stats)
- `pathlib` — Filesystem path handling
- `sys` — System-specific parameters
- `textwrap` — Text formatting (skill content generation)
- `tomllib` — TOML parsing (Python 3.11+, replaces `tomli`)
- `typing` — Type annotations (`Any`)

## License Compatibility

All dependencies use permissive open-source licenses (MIT, BSD-3-Clause) that are fully compatible with libcontext's MIT license. There are no copyleft or restrictive license requirements.

## Updating This Document

When adding new dependencies, please update this file accordingly. You can verify installed dependency licenses with:

```bash
pip install pip-licenses
pip-licenses --packages click tomli pytest pytest-cov hatchling
```
