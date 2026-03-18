# libcontext

[![CI](https://github.com/Syclaw/libcontext/actions/workflows/ci.yml/badge.svg)](https://github.com/Syclaw/libcontext/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/Syclaw/libcontext/graph/badge.svg)](https://codecov.io/gh/Syclaw/libcontext)
[![PyPI version](https://img.shields.io/pypi/v/libcontext)](https://pypi.org/project/libcontext/)
[![Python](https://img.shields.io/pypi/pyversions/libcontext)](https://pypi.org/project/libcontext/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Typed](https://img.shields.io/badge/typed-mypy-blue.svg)](https://mypy-lang.org/)

> Make your AI coding assistant aware of any Python library's API — on demand, not always-on.

**libcontext** inspects any installed Python package via static AST analysis (no code execution) and generates compact Markdown API references. It integrates with Claude Code (via a `/lib` skill) and VS Code Copilot (via an MCP server) to provide **progressive disclosure** — only loading API context when you actually need it, avoiding context window pollution.

## Why This Exists

When you ask an AI assistant how to use a library, the quality of the output depends entirely on what the model knows about that library's API. For many real-world scenarios, the model is working blind:

- **Internal / private libraries** — Zero training data exists. The model has never seen the API.
- **Niche open-source packages** — Sparse or outdated training data leads to hallucinated methods and wrong signatures.
- **New versions of any library** — Training data has a cutoff. The model knows v2, you're using v3.

Dumping entire API references into always-on instruction files (like `copilot-instructions.md` or `CLAUDE.md`) wastes context window on every interaction — even when you're not using that library. Research ([ReadMe.LLM, UC Berkeley 2025](https://arxiv.org/abs/2504.15870)) confirms that excessive context triggers hallucinations and degrades output quality.

libcontext solves this with **progressive disclosure**: overview first, then drill into specific modules only when needed.

## When libcontext makes the biggest difference

| Scenario | Impact | Why |
|---|---|---|
| **Internal / private libraries** | Critical | Zero training data exists for proprietary code |
| **Niche open-source packages** | High | Sparse training data leads to hallucinated methods |
| **New versions of any library** | High | Training cutoff — the LLM knows v2, you're using v3 |
| **Popular, stable libraries** | Low | The LLM already has good knowledge from training data |

## Quick Start

```bash
pip install libcontext

# Install the /lib skill into your Claude Code project
libctx install --skills

# Now in Claude Code, just type:
#   /lib requests
# Claude will progressively discover the API for you
```

For VS Code with MCP support:

```bash
pip install libcontext[mcp]
libctx install --mcp --target vscode
```

## How It Works

### Progressive Disclosure (Skill / MCP)

Instead of dumping everything upfront, libcontext follows a progressive workflow:

```
Step 1: Overview          Step 2: Drill down          Step 3: Search
libctx inspect requests   libctx inspect requests     libctx inspect requests
  --overview                --module requests.api       --search Session

  Module list with          Full signatures,            Find specific
  class/function names      docstrings, parameters      classes or methods
  (no signatures)           for one module              across all modules
```

The `/lib` skill (Claude Code) and MCP server (VS Code / Cursor) automate this workflow — the AI assistant decides what to inspect based on the task at hand.

### Direct CLI Usage

```bash
# Full API reference to stdout
libctx inspect requests

# Compact overview — module names with class/function names
libctx inspect requests --overview -q

# Detailed API for a single module
libctx inspect requests --module requests.api -q

# Search for a specific class or function
libctx inspect requests --search Session -q

# Write to a file with marker injection
libctx inspect requests -o .github/copilot-instructions.md

# Multiple libraries at once
libctx inspect requests httpx pydantic -o context.md
```

### AST Analysis

1. **Parsing** — Reads source files of installed packages using Python's `ast` module. No code is ever executed.
2. **Extraction** — Classes, functions, methods, parameters, type annotations, decorators, and docstrings.
3. **Compact rendering** — Structured Markdown optimised for LLM context windows.
4. **Marker injection** — `<!-- BEGIN/END LIBCONTEXT -->` markers for idempotent file updates.

## Installation

```bash
pip install libcontext
```

With MCP server support (requires Python 3.10+):

```bash
pip install libcontext[mcp]
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add libcontext           # basic
uv add libcontext[mcp]      # with MCP server
```

For development:

```bash
git clone https://github.com/Syclaw/libcontext.git
cd libcontext
uv sync --all-extras
```

## Integration Setup

The `install` command configures your project for AI-assisted library discovery:

```bash
# Claude Code — install the /lib skill
libctx install --skills

# Claude Code — install MCP server config
libctx install --mcp

# VS Code / Cursor — install MCP server config
libctx install --mcp --target vscode

# GitHub Copilot — install the skill
libctx install --skills --target github

# Everything at once
libctx install --all --target all
```

| Flag | What it installs |
|---|---|
| `--skills` | `/lib` skill for on-demand API discovery |
| `--mcp` | MCP server configuration for tool-based access |
| `--all` | Both skills and MCP |

| Target | Skills location | MCP location |
|---|---|---|
| `claude` (default) | `.claude/skills/lib/SKILL.md` | `.mcp.json` |
| `github` | `.github/skills/lib/SKILL.md` | — |
| `vscode` | — | `.vscode/mcp.json` |

### Using the `/lib` Skill (Claude Code)

After `libctx install --skills`, type `/lib <package>` in Claude Code:

```
/lib requests              → overview, then drill into modules
/lib requests requests.api → jump straight to a specific module
```

Claude will automatically run `libctx` commands to discover the API progressively.

### Using the MCP Server

After `libctx install --mcp`, the MCP server provides tools:

- `get_package_overview` — structural overview of a package
- `get_module_api` — detailed API for a single module
- `search_api` — search for classes, functions, or methods
- `refresh_cache` — clear the session cache

## Python API

```python
from libcontext import collect_package, render_package

# Full API reference
pkg = collect_package("requests")
print(render_package(pkg))
```

```python
from libcontext import collect_package, render_package_overview, render_module, search_package

pkg = collect_package("requests")

# Overview — module names with class/function names
print(render_package_overview(pkg))

# Single module — full signatures and docstrings
for mod in pkg.non_empty_modules:
    if mod.name == "requests.api":
        print(render_module(mod))

# Search — find specific classes or functions
print(search_package(pkg, "Session"))
```

## Configuration (Optional)

Library authors can customise what libcontext exposes by adding a `[tool.libcontext]` section to their `pyproject.toml`. The library does not need to depend on libcontext.

```toml
[tool.libcontext]
include_modules = ["mylib.core", "mylib.models"]
exclude_modules = ["mylib._internal", "mylib.tests"]
include_private = false
max_readme_lines = 150
extra_context = """
This library uses the Repository pattern for data access.
All async operations use httpx internally.
"""
```

## Architecture

| Module | Role |
|---|---|
| `models.py` | Dataclasses representing Python components |
| `inspector.py` | Static AST analysis — signatures, docstrings, decorators |
| `collector.py` | Package discovery and module collection |
| `config.py` | Reads `[tool.libcontext]` from pyproject.toml |
| `renderer.py` | LLM-optimised Markdown generation |
| `cli.py` | CLI entry point with `inspect` and `install` subcommands |
| `mcp_server.py` | MCP server for VS Code / Cursor integration (optional) |

## Development

```bash
uv sync --all-extras
uv run pytest --cov=libcontext
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run mypy src/libcontext
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed contribution guidelines.

## Dependencies

See [DEPENDENCIES.md](DEPENDENCIES.md) for the full list of dependencies and their licenses.

## License

MIT — see [LICENSE](LICENSE) for details.
