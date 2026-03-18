# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in libcontext, please report it responsibly.

**Do NOT open a public issue for security vulnerabilities.**

Instead, please email the maintainer directly or use [GitHub's private vulnerability reporting](https://github.com/Syclaw/libcontext/security/advisories/new).

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Acknowledgement:** within 48 hours
- **Assessment:** within 1 week
- **Fix release:** as soon as possible after assessment

## Security Considerations

libcontext uses **AST-based static analysis only** — it never executes code from inspected packages. This is a deliberate design choice to minimise security risk. However, it does:

- Read files from disk (installed packages)
- Parse Python source code via `ast.parse()`
- Access package metadata via `importlib.metadata`

### MCP Server (`libctx-mcp`)

The optional MCP server adds a JSON-RPC interface over **stdio** (standard input/output). This means:

- **Local-only communication** — the server is launched by the IDE as a child process; it does not open network ports or accept remote connections.
- **Input validation** — package names and module names received via tool calls are passed to `collect_package()`, which resolves them through `importlib` and filesystem paths. Malformed names result in a `ValueError`, not arbitrary file access.
- **No code execution** — the same AST-only guarantee applies. The MCP server calls the same `collect_package` / `render_*` functions as the CLI.
- **Session cache** — an `lru_cache` stores collected packages for the lifetime of the server process. The `refresh_cache` tool allows clearing it. Cache is not persisted to disk and is isolated per server process.

If you identify any way these operations could be exploited, please report it.
