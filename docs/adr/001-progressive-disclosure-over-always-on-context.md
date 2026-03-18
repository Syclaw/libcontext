# ADR-001: Progressive Disclosure Over Always-On Context Injection

## Status

Accepted

## Context

The original design of libcontext generated a full API reference and injected it into always-on instruction files (`copilot-instructions.md`, `CLAUDE.md`). These files are loaded into the LLM context window at the start of every session, regardless of whether the user is working with the documented library.

This approach has several problems:

- **Context window pollution.** LLM context windows are finite. Loading API references for libraries that are not relevant to the current task wastes tokens that could carry more useful information (project conventions, task-specific context).
- **Diminishing returns from excessive context.** Research on LLM-optimized documentation (ReadMe.LLM, UC Berkeley, April 2025) demonstrates that excessive context degrades output quality and increases hallucination rates. Concise, targeted context outperforms exhaustive dumps.
- **Hard limits.** GitHub Copilot enforces a 4,096-character limit on `copilot-instructions.md` during code review. A single library's API reference can easily exceed this, crowding out other instructions.
- **Staleness.** A static dump captures the API at generation time. When the library is updated, the injected content becomes stale and can actively mislead the model into suggesting removed or renamed APIs.

## Decision

Adopt a **progressive disclosure** model: provide API context on demand, at the granularity the task requires, rather than injecting everything upfront.

The disclosure follows three levels of increasing detail:

1. **Overview** — module names with class and function names (no signatures). Enough to understand the package shape and decide where to drill down.
2. **Module** — full signatures, type annotations, docstrings, and decorators for a single module. Loaded only when the user or the LLM needs to work with that module.
3. **Search** — case-insensitive substring search across all public names. Retrieves specific items without loading entire modules.

This is delivered through two integration paths:

- A **CLI** (`libctx`) with `--overview`, `--module`, and `--search` flags, invoked by the LLM via tool calls (Bash or MCP).
- An **install command** (`libctx install`) that configures the user's project for skill-based or MCP-based integration, so the LLM knows how to use the CLI.

## Alternatives Considered

### Hybrid: inject overview, drill down on demand

A lighter variant: inject the compact `--overview` output for packages declared in `pyproject.toml` into always-on context (a few hundred tokens per package), then use progressive drill-down for module-level detail.

This would eliminate the first round-trip for known project dependencies. The cost is modest context consumption and re-introducing a staleness surface (the overview could drift when a dependency is updated without re-running injection).

Rejected for v1 because it re-introduces injection into always-on files (conflicting with this ADR's core premise) and the overview round-trip cost is low enough to accept.

**Revision criterion:** revisit this alternative if usage data shows that more than half of sessions begin with a `/lib` call for the same package (indicating a stable primary dependency whose overview could be safely inlined). The measurement can be qualitative (user feedback) or quantitative (session log analysis). The token cost to evaluate is not just the overview content but the round-trip overhead: request formulation + response interpretation, typically 200–400 tokens per call.

## Consequences

- **Positive.** Context window usage is proportional to actual need. A task touching one module loads only that module's API, not the entire package.
- **Positive.** No staleness risk — the CLI inspects the currently installed version at invocation time.
- **Positive.** Works for projects with many dependencies — each library's context is loaded independently, only when needed.
- **Positive.** No injection into always-on instruction files (`CLAUDE.md`, `copilot-instructions.md`). The skill file is the sole integration point, loaded only when the user invokes `/lib`. This avoids conflicting with user-maintained content and keeps the install command surface minimal (`--skills`, `--mcp`, `--all`).
- **Negative.** Requires extra round-trips compared to always-on injection. The LLM must first request an overview, then drill down. Each call adds latency (under one second), but the cumulative cost is primarily in token consumption: each tool call consumes tokens to formulate the request and interpret the response. For packages requiring exploration of many modules, this can add up to several thousand tokens of overhead across a session.
- **Negative.** The LLM must know how to use the progressive workflow. This is handled by the `/lib` skill (Claude Code) or MCP tools (VS Code), but requires initial project setup via `libctx install`.
- **Negative.** The LLM may not proactively think to use `/lib` when it encounters an unfamiliar library. The skill is discovered at session startup via directory scanning, so the LLM knows it exists — but associating "unfamiliar API" with "invoke `/lib`" depends on the skill description being clear enough. Mitigated by the skill's `description` field which explicitly mentions this use case.
