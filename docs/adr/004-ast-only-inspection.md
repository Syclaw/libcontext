# ADR-004: AST-Only Inspection (No Code Execution)

## Status

Accepted

## Context

Extracting API information from Python packages can be done in two ways:

### Runtime introspection

Import the package and use `inspect`, `dir()`, `getattr()`, etc. to enumerate classes, functions, and their signatures.

**Advantages:**
- Captures dynamically generated APIs (e.g., classes built by metaclasses, `__getattr__`-based module interfaces).
- Resolves re-exports and aliases automatically.

**Disadvantages:**
- **Executes arbitrary code.** Importing a package runs its `__init__.py` and any module-level code. This can trigger side effects: network requests, file writes, database connections, process spawning.
- **Environment coupling.** Some packages fail to import without specific system libraries, environment variables, or configuration files.
- **Security risk.** Running untrusted code from third-party packages is unacceptable in a tool designed to be used broadly across arbitrary dependencies.

### Static AST analysis

Parse source files with Python's `ast` module. Walk the syntax tree to extract class definitions, function signatures, type annotations, decorators, and docstrings.

**Advantages:**
- **No code execution.** Safe for any package, including malicious ones.
- **No import required.** Works without the package's own dependencies being installed (only the source files are needed).
- **Deterministic.** Produces the same output regardless of runtime state, environment variables, or system configuration.

**Disadvantages:**
- Cannot capture dynamically generated APIs.
- Cannot resolve re-exports that use `importlib` or `__getattr__`.
- May miss APIs defined in C extensions (`.so`/`.pyd` files).

## Decision

Use **static AST analysis exclusively**. Never import or execute code from inspected packages.

The `inspector.py` module uses `ast.parse()` to read source files and extracts:
- Class definitions with base classes, decorators, and docstrings.
- Method and function signatures with full parameter details (positional-only, keyword-only, defaults, `*args`, `**kwargs`).
- Type annotations (preserved as source text, not evaluated).
- Module-level variables and constants.
- `__all__` declarations (used to filter public API when defined).

## Consequences

- **Positive.** Safe to run against any installed package without risk.
- **Positive.** No environment dependencies — works in CI, sandboxed environments, and containers.
- **Positive.** Fast — AST parsing of a typical package (e.g., `requests`) completes in under 200ms.
- **Negative.** Misses dynamically generated APIs. This is a known limitation, documented in the project. For most well-structured Python libraries, the static API is the complete public API.
- **Negative.** Re-exports via `from module import *` or explicit `from module import Name` in `__init__.py` are not resolved. The inspector sees the `__all__` list in `__init__.py` (when defined) but does not follow imports to retrieve the actual signatures from the source module. For packages that define their public API primarily through re-exports (e.g., `requests`, `flask`), the overview lists the names correctly but module-level drill-down requires navigating to the internal module where the symbol is defined. This is a usability gap, not a correctness gap — the information is accessible, but not at the location the user would expect.
- **Negative.** C extensions (`.so`/`.pyd` files) are invisible to AST analysis. Packages that are primarily C extensions (e.g., `numpy` core) will have limited coverage. Many such packages ship Python stub files (`.pyi`) that could theoretically be parsed, but the current implementation does not inspect `.pyi` files — only `.py` source. Adding `.pyi` support is a future enhancement that would improve coverage for C-extension-heavy packages without compromising the no-execution guarantee.
