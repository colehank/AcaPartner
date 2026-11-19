# Research Workbench for Codex

A portable Codex plugin connecting to an existing Research Partner HTTP service. It supplies 16 explicit MCP tools and a workflow skill. The graphical editor remains the Research Partner web application; this package does not claim to embed it inside Codex.

The directory is self-contained: `.codex-plugin/plugin.json`, `.mcp.json`, `skills/`, and the standard-library Python server under `scripts/`. No SDK installation, hosted model key, background model loop or direct database access is required. The service retains its current authentication, project permissions, version checks and finite task budgets.

## Connection

The default service is `http://127.0.0.1:8877`. Configure these environment variables for the MCP process when the existing service differs:

- `RP_WORKBENCH_URL`: exact service origin. Loopback HTTP and HTTPS are supported; URL credentials, extra paths and redirects are rejected.
- `RP_WORKBENCH_TOKEN_FILE`: path to an existing service access-token file when authentication is enabled. The adapter reads the file for each HTTP request. Do not paste tokens into tool arguments, plugin manifests, prompts or source control.

The plugin's `.mcp.json` starts `python3 ./scripts/mcp_workbench.py` from the plugin directory. It forwards those two variables and PATH. A copied package can also run directly with:

```sh
python3 /path/to/research-workbench/scripts/mcp_workbench.py --url http://127.0.0.1:8877 --token-file /path/to/existing-service-token
```

Omit `--token-file` only when the service already permits unauthenticated loopback access. This does not change service authentication. Stdout is reserved for MCP JSON-RPC; an interactive shell invocation waits for an MCP client, not a chat prompt.

## Tools

| Purpose | Tools |
|---|---|
| Find and inspect | `list_projects`, `list_outputs`, `read_object`, `read_task` |
| Comments | `add_annotation`, `update_annotation` |
| Actual source files | `list_source_files`, `export_source_files` |
| Organize and assemble | `organize_outputs`, `assemble_manuscript`, `refresh_manuscript_module`, `retain_manuscript_module` |
| Finite paragraph revision | `submit_manuscript_revision`, `view_manuscript_revision`, `decide_manuscript_revision` |
| User control | `stop_task` (pause/cancel) |

Read exact object revisions before writing. Organizing, assembly, export and revision decisions require stable request keys where the underlying service supports them. An uncertain connection does not trigger an automatic write retry. The existing annotation API has neither CAS nor idempotency: inspect comments before retrying an uncertain add/update. Its legacy actor labels remain unchanged; this adapter does not invent authenticated Codex executor identity.

Submitting a revision creates one actual service task and may consume the explicitly stated native-provider budget. It never loops, extends a budget, automatically adopts text or marks a comment resolved. Adoption requires exact proposal/candidate hashes and current target/decision versions. The authenticated operator can be a coordinator; a receipt does not claim human review or scientific approval.

The adapter exposes no arbitrary HTTP action, shell execution, fitting, global settings or credential-management tool. Source ZIP tools create actual registered assets and return authenticated URLs, without downloading/extracting files on the local host.

## Codex host setup boundary

This is the supported compatibility plugin layout. Codex supports local stdio MCP, while a plugin's optional custom web UI is a separate host capability. See [Codex MCP configuration](https://developers.openai.com/codex/mcp) and [plugin packaging](https://developers.openai.com/plugins/build/plugins).

This development unit did **not** install a global marketplace, load the plugin into a Codex task or publish it. A coordinator must add the package to an authorized local/repo marketplace and verify loaded tools in a new Codex task. The inspected local CLI was `codex-cli 0.156.1`; its plugin command is `codex plugin add`, not `codex plugin install`. Actual host installation and UI availability must be recorded separately from stdio tests. No marketplace-backed View/Share link is asserted here.

## Engineering checks

The public backend regression entry is:

```sh
python tools/check_backend.py test
```

The original private development environment also exercised a copied plugin through real stdio JSON-RPC and an isolated authenticated HTTP App/Store, including source ZIP bytes, version decisions, credential rotation and finite queue/cancel. Those historical integration fixtures are not included in this public repository, so the public regression command does not claim to repeat that full plugin acceptance or a Codex host/user trial. Host loading and end-to-end plugin verification remain explicit integration work.

`src/research_partner/integrations/mcp_workbench.py` is the development source; `scripts/mcp_workbench.py` is its byte-identical distributable copy. Do not update only one file.

Limits: 1 MiB per incoming MCP message, 32 MiB per HTTP response and a default 30-second timeout per HTTP request. A tool needing CSRF first reads `/api/state`, so its total may span two HTTP requests. Large workspaces can exceed that bounded state response and need service-side pagination; this adapter does not silently truncate it. MCP connection closure/notification cannot roll back an HTTP write already sent. Inspect the exact service state after an uncertain response.
