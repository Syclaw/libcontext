# libcontext

[![CI](https://github.com/Syclaw/libcontext/actions/workflows/ci.yml/badge.svg)](https://github.com/Syclaw/libcontext/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/Syclaw/libcontext/graph/badge.svg)](https://codecov.io/gh/Syclaw/libcontext)
[![PyPI version](https://img.shields.io/pypi/v/libcontext)](https://pypi.org/project/libcontext/)
[![Python](https://img.shields.io/pypi/pyversions/libcontext)](https://pypi.org/project/libcontext/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Typed](https://img.shields.io/badge/typed-mypy-blue.svg)](https://mypy-lang.org/)

> Make your AI coding assistant aware of any Python library's API — especially the ones it doesn't already know.

**libcontext** inspects any installed Python package via static AST analysis (no code execution) and generates a compact Markdown API reference. Add it to your [`.github/copilot-instructions.md`](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions) and GitHub Copilot will automatically include it as context in **Chat, Agent, and Code Review** interactions.

## Why This Exists

When you ask Copilot Chat how to use a library, or when Copilot Agent generates code that depends on one, the quality of the output depends entirely on what the model knows about that library's API.

For popular, well-established libraries, LLMs generally have good knowledge from training data. But for many real-world scenarios, the model is working blind:

- **Internal / private libraries** — Zero training data exists. The model has never seen the API.
- **Niche open-source packages** — Sparse or outdated training data leads to hallucinated methods and wrong signatures.
- **New versions of any library** — Training data has a cutoff. The model knows v2, you're using v3.

GitHub Copilot supports [repository custom instructions](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions) — a `.github/copilot-instructions.md` file that is automatically included as context. According to GitHub's [support matrix](https://docs.github.com/en/copilot/reference/custom-instructions-support), this file is loaded by:

| Copilot feature | Uses custom instructions |
|---|---|
| **Copilot Chat** (VS Code, JetBrains, Visual Studio, Eclipse, Xcode, github.com) | ✅ Yes |
| **Copilot coding agent** (PR generation, agent mode) | ✅ Yes |
| **Copilot code review** | ✅ Yes |
| **Inline code completion** (autocomplete as you type) | ❌ Not currently |

libcontext bridges the knowledge gap by pre-generating a structured API reference from installed packages and placing it where Copilot can find it.

## When libcontext makes the biggest difference

| Scenario | Impact | Why |
|---|---|---|
| **Internal / private libraries** | 🔴 Critical | Zero training data exists for proprietary code |
| **Niche open-source packages** | 🟠 High | Sparse training data → hallucinated methods and wrong signatures |
| **New versions of any library** | 🟠 High | Training data has a cutoff — the LLM knows v2, you're using v3 |
| **Popular, stable libraries** | ⚪ Low | The LLM already has good knowledge from training data |

> **If Copilot has ever suggested a function that doesn't exist** in one of your dependencies, or got the parameters wrong — libcontext can help prevent that.

## Quick Start

```bash
pip install libcontext

# Generate context for any installed package
libctx requests -o .github/copilot-instructions.md

# Done — Copilot Chat and Agent now know the complete requests API
# (15 modules, 44 classes, 70 functions → ~800 lines of compact reference)
```

## How It Works

1. **AST parsing** — Reads source files of installed packages using Python's `ast` module. No code is ever executed, making it safe for any package.
2. **Extraction** — Classes, functions, methods, parameters, type annotations, decorators, and docstrings are collected.
3. **Compact rendering** — Everything is rendered into structured Markdown optimised for LLM context windows (signatures and docstrings only, no implementation code).
4. **Marker injection** — Output is wrapped in `<!-- BEGIN/END LIBCONTEXT -->` markers, so re-running updates only its section without touching the rest of the file.

```
installed package         libcontext              .github/copilot-instructions.md
  (source files)    ──▶  (AST analysis)   ──▶   (compact API reference)
                                                        │
                                                        ▼
                                                 Copilot Chat, Agent &
                                                 Code Review now know
                                                 the full API
```

## Installation

```bash
pip install libcontext
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add libcontext
```

For development:

```bash
git clone https://github.com/Syclaw/libcontext.git
cd libcontext
uv sync --all-extras   # or: pip install -e ".[dev]"
```

## Usage

### Command Line

```bash
# Generate context for an installed library (stdout)
libctx requests

# Write to the Copilot instructions file
libctx requests -o .github/copilot-instructions.md

# Multiple libraries at once
libctx requests httpx pydantic -o .github/copilot-instructions.md

# Include private members
libctx mypackage --include-private

# Without the README
libctx mypackage --no-readme

# With an explicit configuration file
libctx mypackage --config path/to/pyproject.toml
```

### Python API

```python
from libcontext import collect_package, render_package

# Collect the API of an installed package
pkg = collect_package("requests")

# Generate the Markdown
context = render_package(pkg)
print(context)
```

### Injection into an Existing File

When using `-o`, libcontext injects content between markers:

```markdown
<!-- BEGIN LIBCONTEXT: requests -->
... generated content ...
<!-- END LIBCONTEXT: requests -->
```

Subsequent runs update only that section, preserving the rest of the file.

## Configuration (Optional)

Library authors can customise what libcontext exposes from their package by adding a `[tool.libcontext]` section to their `pyproject.toml`. **The library does not need to depend on libcontext** — this is purely opt-in metadata that libcontext reads at generation time.

```
┌──────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│  libcontext       │     │  Library B            │     │  Your project        │
│  (CLI tool)       │     │  (any Python pkg)     │     │  (end user)          │
│                   │     │                       │     │                       │
│  Reads            │     │  Can optionally add   │     │  Runs:               │
│  [tool.libcontext]│◀────│  [tool.libcontext]    │     │  libctx lib_b        │
│  from library B   │     │  to pyproject.toml    │     │                       │
└──────────────────┘     └──────────────────────┘     └──────────────────────┘
```

```toml
[tool.libcontext]
# Only include specific modules
include_modules = ["mylib.core", "mylib.models"]

# Exclude modules
exclude_modules = ["mylib._internal", "mylib.tests"]

# Include private members
include_private = false

# Free-form extra context
extra_context = """
This library uses the Repository pattern for data access.
All async operations use httpx internally.
"""

# Maximum README lines
max_readme_lines = 150
```

## Output Example

```markdown
# requests v2.31.0 — API Reference

> Python HTTP for Humans.

## Overview

# Requests
Requests is a simple HTTP library for Python...

## API Reference

### `requests`

#### `class Session()`
A Requests session. Provides cookie persistence, connection-pooling, and configuration.

**Methods:**
- `def get(url: str, **kwargs) -> Response`
  Sends a GET request.
- `def post(url: str, data: Any = None, json: Any = None, **kwargs) -> Response`
  Sends a POST request.

**Functions:**

- `def get(url: str, params: dict | None = None, **kwargs) -> Response`
  Sends a GET request.
- `def post(url: str, data: Any = None, **kwargs) -> Response`
  Sends a POST request.
```

## Architecture

| Module | Description |
|---|---|
| `models.py` | Dataclasses to represent Python components |
| `inspector.py` | Static AST analysis (no code execution) |
| `collector.py` | Discovery and collection of all modules in a package |
| `config.py` | Reads `[tool.libcontext]` from pyproject.toml |
| `renderer.py` | LLM-optimised Markdown generation |
| `cli.py` | CLI entry point (`libctx`) |

## Development

```bash
# Install in development mode
uv sync --all-extras

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=libcontext

# Lint & format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Type checking
uv run mypy src/libcontext
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed contribution guidelines.

## Dependencies

See [DEPENDENCIES.md](DEPENDENCIES.md) for the full list of dependencies and their licenses.

## License

MIT — see [LICENSE](LICENSE) for details.
