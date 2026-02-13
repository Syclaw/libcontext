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

If you identify any way these operations could be exploited, please report it.
