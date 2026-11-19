# Development conventions

## Reuse first

Before adding infrastructure or a general-purpose capability, inspect the existing implementation and evaluate maintained libraries against the required behavior. Prefer an existing module or a mature dependency; keep AcaPartner code focused on research objects, provenance, workflow, and integration.

For document editing/rendering, Office conversion, LaTeX, PDF, editors, trees, and icons, use the upstream engine through a small adapter. Verify its actual feature coverage, version compatibility, license, server requirements, and a representative real-file round trip before claiming support. A custom implementation needs a concrete unmet requirement and a documented reason existing solutions cannot satisfy it.

Use `docs/README.md` for the documentation map. Before changing document adapters or the manuscript workspace, read `docs/architecture/document-adapters.md`. Before domain changes, read `docs/product/glossary.md`; before system decomposition, read `docs/architecture/system-architecture-proposal.md` (a proposal, not a completion claim).

For product and design work, use the canonical context at `docs/product/README.md` and `docs/design-system.md`, including when a skill refers to PRODUCT.md or DESIGN.md. Update those files in place; keep documentation in `docs/` and this file as the agent entry point.

## Code Review Graph (CRG)

Before locating code, planning code changes, or reviewing a diff, use the `code-review-graph` MCP:

1. Start with `get_minimal_context_tool`, specifying this repository's absolute `repo_root` and the task. Use `base="HEAD"` when examining uncommitted changes.
2. Follow its suggestions: query or traverse symbols for code navigation, inspect affected flows for impact, and use `detect_changes_tool` / `get_review_context_tool` for reviews. Prefer `detail_level="minimal"` where supported; expand relevant results as needed.
3. Build an empty index with `build_or_update_graph_tool(full_rebuild=true)`. After code changes, incrementally update it before relying on affected symbols or review results. Shared exclusions live in `.code-review-graphignore`; `.code-review-graph/` is local generated state.

The installed CRG build/update commands can omit untracked files. Verify new source files are queryable. If missing, use CRG's Python `incremental_update` with `changed_files=get_staged_and_unstaged(repo_root)`, then rerun `run_postprocess_tool`; keep the user's Git staging unchanged.

Use graph results to locate current source and relevant tests; verify behavior through source inspection and appropriate checks. If MCP is unavailable, use the `code-review-graph` CLI (`build`, `update`, `status`); if CRG itself is unavailable, continue with direct source inspection and state that limitation.

## Browser verification

Run browser tests and screenshot capture headlessly by default. Do not open visible Chrome windows or use the user's browser for routine development verification. Use a visible browser only when the user explicitly requests it.
