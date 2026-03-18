# ADR-002: Skill + CLI as Primary Integration Path

## Status

Accepted

## Context

Progressive disclosure (ADR-001) requires a mechanism for the LLM to invoke libcontext during a session. Three integration paths were evaluated:

### Option A: MCP Server

The Model Context Protocol (MCP) defines a JSON-RPC interface over stdio. The LLM calls typed tools (`get_package_overview`, `get_module_api`, etc.) and receives structured responses. MCP is supported by Claude Code, VS Code Copilot (via extensions), and Cursor.

**Advantages:**
- Typed tool interface with parameter validation.
- Cross-platform (works in any MCP-capable client).
- Session-level caching via `lru_cache` — avoids re-parsing on repeated calls.

**Disadvantages:**
- Many enterprise environments prohibit MCP servers for security policy reasons (arbitrary code execution surface, supply-chain risk from third-party servers).
- Requires Python 3.10+ (the `mcp` SDK uses `match` statements and modern typing).
- Adds an external dependency (`mcp[cli]`).

### Option B: Skill + CLI

A skill (`.claude/skills/lib/SKILL.md` or `.github/skills/lib/SKILL.md`) instructs the LLM to invoke `libctx` via Bash tool calls. The skill describes the progressive workflow and the CLI provides the `--overview`, `--module`, and `--search` flags.

**Advantages:**
- Zero external dependencies beyond the CLI itself.
- Works in any environment that allows shell commands — no MCP infrastructure needed.
- Skills are static Markdown files checked into the repository. No running process, no attack surface.
- Compatible with Python 3.9+.

**Disadvantages:**
- Bash tool calls have no typed interface — the LLM constructs command strings.
- No session-level caching (each invocation re-parses the package). In practice, AST parsing of typical packages takes under 200ms, making this negligible.
- Skill discovery requires the IDE to scan skill directories at session startup. Skills created mid-session are not discovered until the next session.

### Option C: Preprocessing (Static Generation)

Generate a skill file per library (e.g., `.claude/skills/requests/SKILL.md`) containing the full API reference. The LLM loads the skill when the user invokes it.

**Advantages:**
- No runtime dependency on libcontext being installed.
- Instant access — no CLI invocation during the session.

**Disadvantages:**
- Staleness — generated at a point in time, becomes outdated when the library is updated.
- Context saturation — a full API reference in a single skill file can be very large (thousands of lines for packages like `requests` or `pandas`), reproducing the always-on problem within the skill.
- Maintenance burden — users must regenerate and commit skill files when dependencies change.

### Option D: Hybrid B + C (CLI with pre-generated overview)

Rejected for the same reasons as the hybrid alternative in [ADR-001](001-progressive-disclosure-over-always-on-context.md#hybrid-inject-overview-drill-down-on-demand). See that ADR's revision criterion for when to revisit.

## Decision

Use **Skill + CLI (Option B) as the primary integration path**, with MCP (Option A) as an optional secondary path.

The `/lib` skill instructs the LLM to:
1. Verify the package is installed (`pip show`).
2. Get a structural overview (`libctx <pkg> --overview`).
3. Drill into specific modules (`libctx <pkg> --module <mod>`).
4. Search when needed (`libctx <pkg> --search <query>`).

The skill uses `allowed-tools` frontmatter to auto-approve `Bash(libctx *)` and `Bash(pip show *)` commands, avoiding permission prompts for routine operations.

MCP is offered as an optional extra (`pip install libcontext[mcp]`) for environments that support it and want typed tool interfaces with session caching.

## MCP as Optional Dependency

The MCP server (`libctx-mcp`) depends on `mcp[cli]`, which requires Python 3.10+ and pulls in transitive dependencies (HTTP server, JSON-RPC, Pydantic). Since the core library targets Python 3.9+, MCP is an optional extra:

- Installed via `pip install libcontext[mcp]`.
- `pyproject.toml` declares: `mcp = ["mcp[cli]>=1.0; python_version >= '3.10'"]`.
- `mcp_server.py` imports `mcp` at the top level — if not installed, only the `libctx-mcp` entry point is affected, not the core CLI.

Implementation details (test and type-checking accommodations) are documented in `CLAUDE.md` and `pyproject.toml`, not repeated here.

## Implementation Decisions

The following lower-level decisions support the install command. They were originally separate ADRs (003, 005, 007) but are implementation details of this ADR's integration path rather than standalone architectural choices.

### No injection into always-on instruction files

The `install` command does not write to `CLAUDE.md` or `copilot-instructions.md`. The skill file is the sole integration point, loaded only on explicit invocation. This follows directly from [ADR-001](001-progressive-disclosure-over-always-on-context.md).

### Non-destructive JSON merge for MCP configuration

When `install --mcp` writes to `.mcp.json` or `.vscode/mcp.json`, it performs a one-level-deep merge: existing entries in `mcpServers` (or `servers`) are preserved, and only the `libcontext` entry is added or updated. This avoids clobbering other MCP server configurations the user has already set up.

### Skill content embedded in source code

The `/lib` skill template is embedded as a string in `cli.py` (`_get_skill_content()`) rather than shipped as package data. This avoids `setuptools` package-data packaging complexity (path resolution at runtime, `MANIFEST.in` maintenance) and keeps a single source of truth for the skill content.

## Consequences

- **Positive.** Works in enterprise environments that block MCP.
- **Positive.** No additional runtime dependencies for the primary path. Core functionality works on Python 3.9.
- **Positive.** The skill file is a single Markdown file — easy to audit, version, and customize.
- **Positive.** MCP users are not excluded — they install the optional extra.
- **Negative.** The skill-based path relies on the LLM correctly constructing CLI commands. Mitigated by providing explicit command templates in the skill body.
- **Negative.** Two integration paths to maintain (skill + MCP). The CLI and MCP server expose the same capabilities through different interfaces (stdout vs JSON-RPC). If the core API evolves (new mode, changed signature), both must be updated. Mitigated by sharing the same core logic (`collect_package`, `render_*` functions) and a functional parity test (`tests/test_cli_mcp_parity.py`) that verifies both paths produce equivalent output for the same input. Note: the MCP server intentionally offers `refresh_cache` (a session-level concern) which has no CLI equivalent — this is not a parity gap since the CLI is stateless.
