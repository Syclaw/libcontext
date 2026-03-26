"""CLI entry point for libcontext.

Provides the ``libctx`` command with subcommands:

``inspect``
    Generate LLM-optimised Markdown context from installed Python packages.

``install``
    Install libcontext integration files (skills, MCP) into the current project.

``diff``
    Compare two API snapshots and show what changed.

``cache``
    Manage the disk cache (``list``, ``clear``).

Usage examples::

    libctx inspect requests
    libctx inspect requests --overview -q
    libctx inspect requests --module requests.api -q
    libctx inspect requests --search Session -q

    libctx install --skills
    libctx install --mcp --target vscode
    libctx install --all --target all

    libctx diff old.json new.json

    libctx cache list
    libctx cache clear
    libctx cache clear requests
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sys
import textwrap
from pathlib import Path

import click

from . import cache as _cache
from .collector import collect_package
from .config import LibcontextConfig, read_config_from_pyproject
from .diff import diff_packages
from .exceptions import (
    ConfigError,
    EnvironmentSetupError,
    InspectionError,
    PackageNotFoundError,
)
from .models import PackageInfo, _deserialize_envelope, _serialize_envelope
from .renderer import (
    inject_into_file,
    render_diff,
    render_module,
    render_package,
    render_package_overview,
    search_package,
    search_package_structured,
)


@click.group()
@click.version_option(package_name="libcontext")
def main() -> None:
    """Generate LLM-optimised context from Python library APIs."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_stdout(text: str) -> None:
    """Write UTF-8 text to stdout, handling Windows encoding."""
    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")
        sys.stdout.buffer.flush()
    else:
        click.echo(text)


# ---------------------------------------------------------------------------
# inspect subcommand (default)
# ---------------------------------------------------------------------------


@main.command()
@click.argument("packages", nargs=-1, required=True)
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help=(
        "Output file path.  When targeting an existing file the generated "
        "context is injected between markers so that the rest of the file "
        "is preserved.  Defaults to stdout."
    ),
)
@click.option(
    "--overview",
    is_flag=True,
    default=False,
    help=(
        "Show a compact structural overview: module names with class "
        "and function names (no signatures)."
    ),
)
@click.option(
    "--module",
    "module_name",
    type=str,
    default=None,
    help=(
        "Render the detailed API for a single module only.  "
        "Use --overview first to discover available module names."
    ),
)
@click.option(
    "--search",
    "search_query",
    type=str,
    default=None,
    help="Search for classes, functions, or methods matching a query.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "json"], case_sensitive=False),
    default="markdown",
    help="Output format.",
)
@click.option(
    "--type",
    "type_filter",
    type=click.Choice(["class", "function", "variable", "alias"], case_sensitive=False),
    default=None,
    help="Filter search results by entity type (requires --search).",
)
@click.option(
    "--include-private",
    is_flag=True,
    default=False,
    help="Include private (_-prefixed) modules and members.",
)
@click.option(
    "--no-readme",
    is_flag=True,
    default=False,
    help="Do not include the package README in the output.",
)
@click.option(
    "--max-readme-lines",
    type=int,
    default=None,
    help="Maximum number of README lines to include (default: 100).",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to a pyproject.toml with [tool.libcontext] configuration.",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    default=False,
    help="Suppress informational messages on stderr.",
)
@click.option(
    "--no-cache",
    "no_cache",
    is_flag=True,
    default=False,
    help="Force fresh collection, bypass disk cache.",
)
@click.option(
    "--python",
    "python_env",
    type=str,
    default=None,
    help=(
        "Override environment for package discovery.  Accepts a venv "
        "directory or Python interpreter path.  By default, libcontext "
        "auto-detects .venv/ or venv/ in the current directory."
    ),
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    help="Enable debug logging (useful for troubleshooting).",
)
def inspect(
    packages: tuple[str, ...],
    output: Path | None,
    overview: bool,
    module_name: str | None,
    search_query: str | None,
    output_format: str,
    type_filter: str | None,
    include_private: bool,
    no_readme: bool,
    max_readme_lines: int | None,
    config_path: Path | None,
    no_cache: bool,
    python_env: str | None,
    quiet: bool,
    verbose: bool,
) -> None:
    """Generate LLM context for one or more Python packages."""
    # Configure logging
    if verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(name)s: %(message)s",
            stream=sys.stderr,
        )

    # Validate mutually exclusive flags
    mode_count = sum([overview, module_name is not None, search_query is not None])
    if mode_count > 1:
        click.echo(
            "Error: --overview, --module, and --search are mutually exclusive.",
            err=True,
        )
        sys.exit(1)

    if type_filter is not None and search_query is None:
        click.echo("Error: --type requires --search.", err=True)
        sys.exit(1)

    # Resolve configuration
    config: LibcontextConfig | None = None
    if config_path is not None:
        try:
            config = read_config_from_pyproject(config_path)
        except ConfigError as exc:
            click.echo(f"Error in config: {exc}", err=True)
            sys.exit(1)

    if include_private and config:
        config.include_private = True

    # --overview and --search don't need README
    skip_readme = no_readme or overview or search_query is not None

    # Resolve target environment (--python override, auto-detected venv, or current)
    from ._envsetup import setup_environment

    try:
        _env_tag, _target_python = setup_environment(python_env)
    except EnvironmentSetupError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    all_blocks: list[tuple[str, str]] = []

    for pkg_name in packages:
        if not quiet:
            click.echo(f"Inspecting {pkg_name}…", err=True)

        try:
            pkg_info = collect_package(
                pkg_name,
                include_private=include_private,
                include_readme=not skip_readme,
                config_override=config,
                no_cache=no_cache,
                env_tag=_env_tag,
                target_python=_target_python,
            )
        except PackageNotFoundError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        except InspectionError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        except ConfigError as exc:
            click.echo(f"Error in config: {exc}", err=True)
            sys.exit(1)

        # --- Mode dispatch ------------------------------------------------
        if output_format == "json":
            if overview or not (module_name or search_query):
                # Both default and --overview: full PackageInfo JSON
                json_data = _serialize_envelope(dataclasses.asdict(pkg_info))
                all_blocks.append((pkg_info.name, json.dumps(json_data)))

            elif module_name is not None:
                mod = None
                for m in pkg_info.non_empty_modules:
                    if m.name == module_name:
                        mod = m
                        break
                if mod is None:
                    available = [m.name for m in pkg_info.non_empty_modules]
                    click.echo(
                        f"Error: module '{module_name}' not found in "
                        f"{pkg_info.name}.\n"
                        f"Available: {', '.join(available)}",
                        err=True,
                    )
                    sys.exit(1)
                json_data = _serialize_envelope(dataclasses.asdict(mod))
                all_blocks.append((pkg_info.name, json.dumps(json_data)))

            else:
                # --search + --format json
                assert search_query is not None  # guarded by elif above
                search_data: dict[str, object] = {
                    "query": search_query,
                    "package": pkg_info.name,
                    "results": search_package_structured(
                        pkg_info,
                        search_query,
                        kind=type_filter,
                    ),
                }
                json_data = _serialize_envelope(search_data)
                all_blocks.append((pkg_info.name, json.dumps(json_data)))

        else:
            # Markdown format
            if overview:
                rendered = render_package_overview(pkg_info)

            elif module_name is not None:
                mod = None
                for m in pkg_info.non_empty_modules:
                    if m.name == module_name:
                        mod = m
                        break
                if mod is None:
                    available = [m.name for m in pkg_info.non_empty_modules]
                    click.echo(
                        f"Error: module '{module_name}' not found in "
                        f"{pkg_info.name}.\n"
                        f"Available: {', '.join(available)}",
                        err=True,
                    )
                    sys.exit(1)
                rendered = render_module(mod)

            elif search_query is not None:
                rendered = search_package(pkg_info, search_query, kind=type_filter)

            else:
                readme_lines = max_readme_lines
                if readme_lines is None and config:
                    readme_lines = config.max_readme_lines
                if readme_lines is None:
                    readme_lines = 100

                rendered = render_package(
                    pkg_info,
                    include_readme=not no_readme,
                    max_readme_lines=readme_lines,
                    extra_context=config.extra_context if config else None,
                )

            all_blocks.append((pkg_info.name, rendered))

        if (
            not quiet
            and output_format != "json"
            and not (overview or module_name or search_query)
        ):
            n_modules = len(pkg_info.non_empty_modules)
            n_classes = sum(len(m.classes) for m in pkg_info.modules)
            n_functions = sum(len(m.functions) for m in pkg_info.modules)
            click.echo(
                f"  Found {n_modules} modules, {n_classes} classes, "
                f"{n_functions} functions.",
                err=True,
            )

    # --- Output --------------------------------------------------------
    if output_format == "json":
        indent = 2 if (output or sys.stdout.isatty()) else None
        for _name, json_str in all_blocks:
            # Re-parse and re-serialize with proper indentation
            obj = json.loads(json_str)
            formatted = json.dumps(obj, indent=indent, ensure_ascii=False)
            if output is None:
                _write_stdout(formatted)
            else:
                try:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text(formatted + "\n", encoding="utf-8")
                except OSError as exc:
                    click.echo(
                        f"Error: cannot write to {output}: {exc}",
                        err=True,
                    )
                    sys.exit(1)
                if not quiet:
                    click.echo(f"Context written to {output}", err=True)
    elif output is None:
        for _name, md in all_blocks:
            _write_stdout(md)
    else:
        existing: str | None = None
        if output.is_file():
            try:
                existing = output.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                click.echo(
                    f"Error: cannot read {output} — file is not valid UTF-8.",
                    err=True,
                )
                sys.exit(1)
            except OSError as exc:
                click.echo(f"Error: cannot read {output}: {exc}", err=True)
                sys.exit(1)

        result = existing or ""
        for pkg_name, md in all_blocks:
            result = inject_into_file(md, pkg_name, existing=result)

        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(result, encoding="utf-8")
        except OSError as exc:
            click.echo(f"Error: cannot write to {output}: {exc}", err=True)
            sys.exit(1)

        if not quiet:
            click.echo(f"Context written to {output}", err=True)


# ---------------------------------------------------------------------------
# install subcommand
# ---------------------------------------------------------------------------

# Where each artifact type is written per target.
_SKILL_DIRS = {
    "claude": Path(".claude/skills/lib"),
    "github": Path(".github/skills/lib"),
}

_MCP_FILES = {
    "claude": Path(".mcp.json"),
    "vscode": Path(".vscode/mcp.json"),
}

# Each artifact type has a set of valid targets.
_VALID_TARGETS = {
    "skills": {"claude", "github"},
    "mcp": {"claude", "vscode"},
}


# --- Content generators ---------------------------------------------------


def _get_skill_content() -> str:
    """Return the content of the /lib skill SKILL.md."""
    return textwrap.dedent("""\
        ---
        name: lib
        description: >-
          Inspect the API of an installed Python package with libcontext/libctx.
          Use when you need to understand how to use a library, dependency, SDK,
          client, framework, or package that is unfamiliar, niche, recently
          updated, poorly documented, or not reliable in model memory. Trigger
          for requests like: "check the package API", "inspect this dependency",
          "find the right class/function", or "look up how this library works".
        argument-hint: "<package> [module] [--search query]"
        ---

        # Progressive API Discovery

        Inspect an installed Python package's API to use it correctly.

        ## Scope

        This skill works **only with Python packages** (installed via pip/uv).
        It cannot inspect JavaScript (npm), Java (Maven/Gradle), Ruby (gem),
        or any non-Python library. If the requested package is not a Python
        package, inform the user and stop — do not attempt inspection.

        ## Workflow

        ### Step 1 — Verify installation

        Run `pip show $ARGUMENTS` (or `uv run pip show $ARGUMENTS`) to confirm
        the package is installed and note its version.

        If not installed, inform the user and stop.

        ### Step 2 — Get structural overview

        If the project has a `.venv/` or `venv/` directory, libctx auto-detects it.
        If auto-detection fails (e.g. non-standard venv location), pass `--python`:
        ```
        libctx inspect $ARGUMENTS --overview -q --python /path/to/.venv
        ```

        Standard case (auto-detection):
        ```
        libctx inspect $ARGUMENTS --overview -q
        ```

        This returns module names with class/function names (no signatures).
        Present this overview to understand the package shape.

        ### Step 3 — Drill into relevant modules

        Based on the task at hand, request detailed API for specific modules:
        ```
        libctx inspect <package> --module <module_name> -q
        ```

        Only request modules relevant to the current task. Do NOT dump the
        entire API — concise context produces better results than exhaustive dumps.

        ### Step 4 — Search when needed

        If looking for a specific class, function, or method:
        ```
        libctx inspect <package> --search <query> -q
        ```

        This searches across all modules by name and docstring (case-insensitive).

        To narrow results by type, add `--type`:
        ```
        libctx inspect <package> --search <query> --type class -q
        libctx inspect <package> --search <query> --type function -q
        ```

        Valid types: `class`, `function`, `variable`, `alias`.

        ### Step 5 — JSON and diff (advanced)

        For structured output suitable for comparison or programmatic use:
        ```
        libctx inspect <package> --format json -q
        libctx inspect <package> --module <module_name> --format json -q
        libctx inspect <package> --search <query> --format json -q
        ```

        To compare API versions after a package upgrade:
        ```
        libctx inspect <package> --format json -q > old.json
        # ... upgrade the package ...
        libctx inspect <package> --format json -q > new.json
        libctx diff old.json new.json
        ```

        ## Rules

        - Always start with `--overview`. Never run bare `libctx inspect <pkg>`
          as the full output may be very large and saturate context.
        - Request at most 2-3 modules per invocation cycle. If more are needed,
          summarize what was learned so far, then request the next batch.
        - Use `-q` flag to suppress stderr noise.
        - If the user specifies a module directly (e.g., `/lib requests requests.auth`),
          skip the overview and go straight to `--module`.
        - If a signature from the overview doesn't match what the code expects,
          the package may have been updated. Add `--no-cache` to force a fresh scan:
          `libctx inspect <package> --module <module_name> --no-cache -q`
        - Use `--type` with `--search` to reduce noise when you know what kind of
          symbol you need (e.g., `--type class` when looking for a class).

        ## Safety limits

        libcontext enforces built-in protections — no configuration needed:

        - **Output truncation**: MCP tool responses are capped at ~120k characters
          (~30k tokens). If output is truncated, a notice appears — use `--module`
          to request smaller slices.
        - **Search cap**: search results are limited to 100 matches. Use `--type`
          or a more specific query to narrow results if the cap is hit.
        - **No code execution**: all inspection is AST-based. Safe for any package,
          including untrusted ones.
    """)


def _get_mcp_entry_claude() -> dict[str, object]:
    """Return the .mcp.json entry for Claude Code."""
    return {
        "mcpServers": {
            "libcontext": {
                "command": "libctx-mcp",
                "args": [],
                "env": {},
            }
        }
    }


def _get_mcp_entry_vscode() -> dict[str, object]:
    """Return the .vscode/mcp.json entry for VS Code."""
    return {
        "servers": {
            "libcontext": {
                "type": "stdio",
                "command": "libctx-mcp",
                "args": [],
            }
        }
    }


# --- Installers ------------------------------------------------------------


def _install_skill(target: str) -> list[str]:
    """Write the /lib skill SKILL.md for a single target.

    Args:
        target: One of the keys in ``_SKILL_DIRS`` (e.g. ``"claude"``).

    Returns:
        List of created file paths.
    """
    skill_dir = _SKILL_DIRS[target]
    skill_file = skill_dir / "SKILL.md"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(_get_skill_content(), encoding="utf-8")
    return [str(skill_file)]


def _merge_json(path: Path, new_data: dict[str, object]) -> None:
    """Merge new_data into an existing JSON file (or create it).

    Top-level keys are merged one level deep: if both the existing file
    and new_data have ``{"mcpServers": {...}}``, the inner dicts are merged
    so existing entries are preserved.
    """
    existing: dict[str, object] = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ConfigError(f"Cannot parse {path}: {exc}") from exc

    for key, value in new_data.items():
        if (
            key in existing
            and isinstance(existing[key], dict)
            and isinstance(value, dict)
        ):
            existing[key] = {**existing[key], **value}  # type: ignore[dict-item]
        else:
            existing[key] = value

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _install_mcp(target: str) -> list[str]:
    """Write MCP server configuration for a single target.

    Args:
        target: ``"claude"`` or ``"vscode"``.

    Returns:
        List of created file paths.
    """
    generators = {
        "claude": _get_mcp_entry_claude,
        "vscode": _get_mcp_entry_vscode,
    }
    path = _MCP_FILES[target]
    _merge_json(path, generators[target]())
    return [str(path)]


# --- Command ---------------------------------------------------------------


@main.command()
@click.option(
    "--skills",
    is_flag=True,
    default=False,
    help="Install the /lib skill for AI-assisted library discovery.",
)
@click.option(
    "--mcp",
    is_flag=True,
    default=False,
    help="Install MCP server configuration (requires libcontext[mcp]).",
)
@click.option(
    "--all",
    "install_all",
    is_flag=True,
    default=False,
    help="Install everything (skills + mcp).",
)
@click.option(
    "--target",
    type=click.Choice(["claude", "github", "vscode", "all"]),
    default="claude",
    show_default=True,
    help="Target platform(s).",
)
def install(
    skills: bool,
    mcp: bool,
    install_all: bool,
    target: str,
) -> None:
    """Install libcontext integration files into the current project."""
    if install_all:
        skills = mcp = True

    if not (skills or mcp):
        click.echo(
            "Error: specify at least one of --skills, --mcp, or --all.",
            err=True,
        )
        sys.exit(1)

    created: list[str] = []

    try:
        if skills:
            targets = (
                sorted(_SKILL_DIRS)
                if target == "all"
                else [target]
                if target in _VALID_TARGETS["skills"]
                else []
            )
            for t in targets:
                created.extend(_install_skill(t))

        if mcp:
            targets = (
                sorted(_MCP_FILES)
                if target == "all"
                else [target]
                if target in _VALID_TARGETS["mcp"]
                else []
            )
            for t in targets:
                created.extend(_install_mcp(t))

    except (ConfigError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if created:
        for path in created:
            click.echo(f"  Installed: {path}")
    else:
        click.echo(
            f"Nothing to install: --target {target} has no matching "
            f"files for the selected options.",
            err=True,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# cache subcommand
# ---------------------------------------------------------------------------


@main.group()
def cache() -> None:
    """Manage the libcontext disk cache."""


@cache.command()
@click.argument("package", required=False, default=None)
def clear(package: str | None) -> None:
    """Remove cached API snapshots.

    When PACKAGE is given, only entries for that package are removed.
    Without arguments, all entries are cleared.
    """
    if package is not None:
        count = _cache.clear_package(package)
        label = f"for {package!r}" if count else f"no entries found for {package!r}"
    else:
        count = _cache.clear_all()
        label = "cache entries" if count else "cache entries (already empty)"
    click.echo(f"Cleared {count} {label}.")


@cache.command(name="list")
def list_() -> None:
    """Show cached API snapshots."""
    entries = _cache.list_entries()
    if not entries:
        click.echo("Cache is empty.")
        return
    total_bytes = 0
    for entry in entries:
        age = _format_age(entry.cached_at)
        size = _format_size(entry.size_bytes)
        click.echo(f"  {entry.package} {entry.version}  ({size}, {age})")
        total_bytes += entry.size_bytes
    click.echo(f"\n{len(entries)} entries, {_format_size(total_bytes)} total.")


def _format_size(size_bytes: int) -> str:
    """Format byte count as a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} kB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _format_age(iso_timestamp: str) -> str:
    """Format an ISO timestamp as a relative age string."""
    import datetime

    try:
        cached = datetime.datetime.fromisoformat(iso_timestamp)
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        delta = now - cached
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            m = seconds // 60
            return f"{m}m ago"
        if seconds < 86400:
            h = seconds // 3600
            return f"{h}h ago"
        d = seconds // 86400
        return f"{d}d ago"
    except (ValueError, TypeError):
        return "unknown age"


# ---------------------------------------------------------------------------
# diff subcommand
# ---------------------------------------------------------------------------


@main.command()
@click.argument("old_file", type=click.Path(exists=True, path_type=Path))
@click.argument("new_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "json"], case_sensitive=False),
    default="markdown",
    help="Output format.",
)
def diff(old_file: Path, new_file: Path, output_format: str) -> None:
    """Compare two API snapshots and show what changed."""
    from ._security import MAX_JSON_INPUT_BYTES

    for label, path in (("old_file", old_file), ("new_file", new_file)):
        try:
            size = path.stat().st_size
        except OSError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        if size > MAX_JSON_INPUT_BYTES:
            click.echo(
                f"Error: {label} exceeds the "
                f"{MAX_JSON_INPUT_BYTES // (1024 * 1024)} MiB size limit "
                f"({size:,} bytes).",
                err=True,
            )
            sys.exit(1)

    try:
        old_raw = json.loads(old_file.read_text(encoding="utf-8"))
        new_raw = json.loads(new_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        click.echo(f"Error: invalid JSON — {exc}", err=True)
        sys.exit(1)
    except OSError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    try:
        old_data = _deserialize_envelope(old_raw)
        new_data = _deserialize_envelope(new_raw)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    old_pkg = PackageInfo.from_dict(old_data)
    new_pkg = PackageInfo.from_dict(new_data)

    result = diff_packages(old_pkg, new_pkg)

    if output_format == "json":
        envelope = _serialize_envelope(dataclasses.asdict(result))
        indent = 2 if sys.stdout.isatty() else None
        _write_stdout(json.dumps(envelope, indent=indent, ensure_ascii=False))
    else:
        _write_stdout(render_diff(result))


if __name__ == "__main__":
    main()
