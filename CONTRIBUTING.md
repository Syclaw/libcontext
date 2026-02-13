# Contributing to libcontext

Thank you for your interest in contributing to **libcontext**! This guide will help you get started.

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment for everyone. Please be kind, constructive, and professional in all interactions.

## Getting Started

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (recommended installer: `pip install uv` or see [installation docs](https://docs.astral.sh/uv/getting-started/installation/))
- Python 3.9 or later
- Git

### Setting Up Your Development Environment

1. **Fork the repository** on GitHub.

2. **Clone your fork:**

   ```bash
   git clone https://github.com/<your-username>/libcontext.git
   cd libcontext
   ```

3. **Install dependencies and set up the project:**

   ```bash
   uv sync
   ```

4. **Verify tests pass:**

   ```bash
   uv run pytest
   ```

## Making Changes

### Branching Strategy

- Create a feature branch from `main`:
  ```bash
  git checkout -b feature/my-feature
  ```
- Use descriptive branch names: `feature/...`, `fix/...`, `docs/...`

### Code Style

- Follow [PEP 8](https://peps.python.org/pep-0008/) conventions.
- Use type hints for all public function signatures.
- Write docstrings in [Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings) for all public classes, methods, and functions.
- Keep lines under 88 characters (Black default).

### Writing Tests

- All new features and bug fixes must include tests.
- Tests are located in the `tests/` directory.
- Run the full test suite before submitting:
  ```bash
  uv run pytest -v
  ```
- Run tests with coverage to check for gaps:
  ```bash
  uv run pytest --cov=libcontext --cov-report=term-missing
  ```

### Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
type(scope): short description

Longer explanation if needed.
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`

**Examples:**
- `feat(inspector): add support for TypedDict extraction`
- `fix(renderer): handle empty module docstrings`
- `docs: update README with new CLI options`

## Submitting a Pull Request

1. **Ensure all tests pass** and your code follows the project style.
2. **Push your branch** to your fork:
   ```bash
   git push origin feature/my-feature
   ```
3. **Open a Pull Request** against `main` on the upstream repository.
4. **Fill out the PR template** with a description of your changes.
5. **Wait for review** — a maintainer will review your PR and may request changes.

### Pull Request Checklist

- [ ] Tests added/updated for the change
- [ ] All tests pass (`uv run pytest`)
- [ ] Docstrings added/updated for public API changes
- [ ] CHANGELOG.md updated (for user-facing changes)

## Reporting Issues

### Bug Reports

When filing a bug report, please include:

- Python version (`python --version`)
- libcontext version (`uv run python -c "import libcontext; print(libcontext.__version__)"`)
- Operating system
- Steps to reproduce
- Expected vs actual behaviour
- Full error traceback (if applicable)

### Feature Requests

Feature requests are welcome! Please describe:

- The problem you're trying to solve
- Your proposed solution (if any)
- Any alternatives you've considered

## Project Structure

```
libcontext/
├── src/libcontext/
│   ├── __init__.py      # Public API exports
│   ├── models.py        # Data models (dataclasses)
│   ├── inspector.py     # AST-based source code inspection
│   ├── collector.py     # Package discovery and module walking
│   ├── config.py        # [tool.libcontext] configuration reader
│   ├── renderer.py      # Markdown generation
│   └── cli.py           # CLI entry point (click)
├── tests/
│   ├── test_cli.py
│   ├── test_collector.py
│   ├── test_config.py
│   ├── test_inspector.py
│   └── test_renderer.py
├── pyproject.toml
├── README.md
├── CONTRIBUTING.md
├── CHANGELOG.md
├── DEPENDENCIES.md
└── LICENSE
```

## Release Process

Releases are managed by the project maintainers. The general process is:

1. Update version in `pyproject.toml` and `src/libcontext/__init__.py`
2. Update `CHANGELOG.md` with the new version
3. Create a git tag: `git tag v0.x.x`
4. Push tag: `git push origin v0.x.x`
5. Build and publish to PyPI: `uv build && uv publish`

## Questions?

If you have questions about contributing, feel free to [open a discussion](https://github.com/Syclaw/libcontext/discussions) or [create an issue](https://github.com/Syclaw/libcontext/issues).

Thank you for helping make libcontext better!
