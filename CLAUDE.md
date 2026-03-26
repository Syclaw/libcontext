# libcontext

Python CLI + skill + MCP server that generates context-efficient API references
from installed Python packages. Uses static AST analysis (no code execution) and
progressive disclosure to provide on-demand API context for LLM toolchains
(Claude Code, GitHub Copilot, VS Code). Most valuable for private, niche, or
recently updated libraries where LLM training data is absent or stale.

## Stack

- **Language**: Python 3.10+ (target compatibility: 3.10–3.13)
- **Dependencies**: click (CLI), tomli (TOML parsing on <3.11), mcp (optional, MCP server)
- **Build**: hatchling, src layout (`src/libcontext/`)
- **Toolchain**: ruff (lint + format), mypy (strict), pytest + pytest-cov
- **Package manager**: uv

## Architecture

| Module | Role |
|---|---|
| `models.py` | Dataclasses for packages, modules, classes, functions, diff results, and JSON envelope |
| `inspector.py` | Static AST analysis — signatures, docstrings, decorators, type aliases (PEP 613/695) |
| `collector.py` | Package discovery, module collection, stub `.pyi` merging, disk cache integration |
| `config.py` | Reads `[tool.libcontext]` from pyproject.toml |
| `renderer.py` | LLM-optimised Markdown generation (full, overview, module, search, diff) and structured JSON search |
| `diff.py` | API diff between two PackageInfo snapshots with breaking change detection |
| `cache.py` | Persistent disk cache with `(version, mtime, file_count)` invalidation and LRU eviction |
| `cli.py` | CLI entry point — `inspect`, `install`, `diff`, and `cache` subcommands |
| `mcp_server.py` | Optional MCP server for VS Code / Cursor (requires `[mcp]` extra) |
| `_security.py` | Input sanitisation, path boundary validation, output size guards, search caps |

## Key Commands

```bash
uv sync --all-extras          # install deps
uv run pytest --cov=libcontext # tests + coverage
uv run ruff check src/ tests/  # lint
uv run ruff format src/ tests/ # format
uv run mypy src/libcontext      # type check
```

## Design Decisions

- **No code execution**: all inspection is AST-based — safe for any package
- **Stub support**: merges `.pyi` stubs (colocated and standalone) with source files
- **Progressive disclosure**: overview → module → search to avoid context saturation
- **JSON output**: versioned envelope with `schema_version` for serialization/deserialization
- **API diff**: structured diff between versions with breaking change detection
- **Disk cache**: `(version, mtime, file_count)` invalidation avoids re-parsing unchanged packages
- **Marker injection**: `<!-- BEGIN/END LIBCONTEXT -->` allows idempotent updates
- **Library-friendly config**: packages can opt-in via `[tool.libcontext]` in their
  own pyproject.toml without depending on libcontext
- **Minimal dependencies**: only click + tomli (stdlib on 3.11+); MCP is optional

## Convention

- Google-style docstrings (enforced by ruff D rules)
- Type annotations on all public APIs (enforced by mypy strict + ruff ANN)
- Tests in `tests/`, one test file per source module
- Commits : ne jamais ajouter le trailer `Co-Authored-By` — le propriétaire du projet est seul auteur
- Ne jamais mentionner claude en tant que co auteur d'un commit, ni dans la description ou le nom de la branche.