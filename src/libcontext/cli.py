"""CLI entry point for libcontext.

Provides the ``libctx`` command with two subcommands:

``inspect``
    Generate LLM-optimised Markdown context from installed Python packages.

``install``
    Install libcontext integration files (skills, MCP) into the current project.

Usage examples::

    libctx inspect requests
    libctx inspect requests --overview -q
    libctx inspect requests --module requests.api -q
    libctx inspect requests --search Session -q

    libctx install --skills
    libctx install --mcp --target vscode
    libctx install --all --target all
"""

from __future__ import annotations

import json
import logging
import sys
import textwrap
from pathlib import Path

import click

from .collector import collect_package
from .config import LibcontextConfig, read_config_from_pyproject
from .exceptions import ConfigError, InspectionError, PackageNotFoundError
from .renderer import (
    inject_into_file,
    render_module,
    render_package,
    render_package_overview,
    search_package,
)


@click.group()
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
    include_private: bool,
    no_readme: bool,
    max_readme_lines: int | None,
    config_path: Path | None,
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
            rendered = search_package(pkg_info, search_query)

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

        if not quiet and not (overview or module_name or search_query):
            n_modules = len(pkg_info.non_empty_modules)
            n_classes = sum(len(m.classes) for m in pkg_info.modules)
            n_functions = sum(len(m.functions) for m in pkg_info.modules)
            click.echo(
                f"  Found {n_modules} modules, {n_classes} classes, "
                f"{n_functions} functions.",
                err=True,
            )

    # --- Output --------------------------------------------------------
    if output is None:
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
          Load API reference for any installed Python library.
          Use when working with an unfamiliar, niche, or recently
          updated Python package that may not be in training data.
        argument-hint: "<package> [module] [--search query]"
        ---

        # Progressive API Discovery

        Inspect an installed Python package's API to use it correctly.

        ## Workflow

        ### Step 1 — Verify installation

        Run `pip show $ARGUMENTS` (or `uv run pip show $ARGUMENTS`) to confirm
        the package is installed and note its version.

        If not installed, inform the user and stop.

        ### Step 2 — Get structural overview

        Run:
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

        This searches across all modules by name (case-insensitive).

        ## Rules

        - Always start with `--overview`. Never run bare `libctx inspect <pkg>`
          as the full output may be very large and saturate context.
        - Request at most 2-3 modules per invocation cycle. If more are needed,
          summarize what was learned so far, then request the next batch.
        - Use `-q` flag to suppress stderr noise.
        - If the user specifies a module directly (e.g., `/lib requests requests.auth`),
          skip the overview and go straight to `--module`.
        - If a signature from the overview doesn't match what the code expects,
          the package may have been updated. Re-run with `--module` for full detail.
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


if __name__ == "__main__":
    main()
