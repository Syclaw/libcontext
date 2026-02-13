"""CLI entry point for libcontext.

Provides the ``libctx`` command that inspects an installed
Python package and generates a Markdown context file optimised for GitHub
Copilot.

Usage examples::

    # Generate context for the 'requests' library → stdout
    libctx requests

    # Write to .github/copilot-instructions.md (with markers)
    libctx requests -o .github/copilot-instructions.md

    # Append context for multiple libraries
    libctx requests httpx -o .github/copilot-instructions.md

    # Include private API
    libctx mypackage --include-private

    # Skip README
    libctx mypackage --no-readme
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from .collector import collect_package
from .config import LibcontextConfig, read_config_from_pyproject
from .renderer import inject_into_file, render_package


@click.command(
    name="libctx",
    help=(
        "Generate an LLM-optimised Markdown context file from one or more "
        "Python packages.  The output can be written to "
        ".github/copilot-instructions.md (recommended) or printed to stdout."
    ),
)
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
def main(
    packages: tuple[str, ...],
    output: Path | None,
    include_private: bool,
    no_readme: bool,
    max_readme_lines: int | None,
    config_path: Path | None,
    quiet: bool,
    verbose: bool,
) -> None:
    """Generate Copilot context for one or more Python packages."""
    # Configure logging
    if verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(name)s: %(message)s",
            stream=sys.stderr,
        )
    # Resolve configuration
    config: LibcontextConfig | None = None
    if config_path is not None:
        try:
            config = read_config_from_pyproject(config_path)
        except TypeError as exc:
            click.echo(f"Error in config: {exc}", err=True)
            sys.exit(1)

    if include_private and config:
        config.include_private = True

    all_blocks: list[tuple[str, str]] = []  # (package_name, rendered_md)

    for pkg_name in packages:
        if not quiet:
            click.echo(f"Inspecting {pkg_name}…", err=True)

        try:
            pkg_info = collect_package(
                pkg_name,
                include_private=include_private,
                include_readme=not no_readme,
                config_override=config,
            )
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        except TypeError as exc:
            click.echo(f"Error in config: {exc}", err=True)
            sys.exit(1)

        # Determine max_readme_lines
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

        n_modules = len(pkg_info.non_empty_modules)
        n_classes = sum(len(m.classes) for m in pkg_info.modules)
        n_functions = sum(len(m.functions) for m in pkg_info.modules)
        if not quiet:
            click.echo(
                f"  Found {n_modules} modules, {n_classes} classes, "
                f"{n_functions} functions.",
                err=True,
            )

    # --- Output --------------------------------------------------------
    if output is None:
        # stdout — force UTF-8 on Windows to avoid cp1252 issues
        if hasattr(sys.stdout, "buffer"):
            binary = sys.stdout.buffer
            for _name, md in all_blocks:
                binary.write(md.encode("utf-8", errors="replace"))
                binary.write(b"\n")
            binary.flush()
        else:
            # Test environments / non-standard stdout
            for _name, md in all_blocks:
                click.echo(md)
    else:
        # File output with marker injection
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


if __name__ == "__main__":
    main()
