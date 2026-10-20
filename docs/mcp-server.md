# MCP Server (`bsp-mcp`)

`bsp-mcp` is an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/)
server that exposes the BSP workflow to AI agents (Claude, Copilot, and other
MCP-capable clients): preset discovery, builds, CVE scans, HIL tests,
build-failure triage and layer-pin maintenance.

Existing `bsp` CLI behaviour is unchanged — the MCP server is an optional
add-on.

## Install

The MCP SDK requires Python 3.10+ (the rest of the package keeps 3.8 support):

```bash
pip install "bsp-registry-tools[mcp]"
# or from a checkout:
pip install -e ".[mcp]"
```

## Run

```bash
# stdio transport (default — what most MCP clients expect)
bsp-mcp --registry /path/to/bsp-registry.yaml

# HTTP (streamable-http) transport
bsp-mcp --registry /path/to/bsp-registry.yaml --transport http --host 127.0.0.1 --port 8765
```

Without `--registry` the remote registry is fetched and cached automatically
(honouring `--remote` / `--branch`).

### Client configuration example

```json
{
  "mcpServers": {
    "bsp": {
      "command": "bsp-mcp",
      "args": ["--registry", "/path/to/bsp-registry.yaml"],
      "env": {
        "BSP_MCP_STATE_DIR": "/home/me/.cache/bsp/mcp/jobs"
      }
    }
  }
}
```

## Tools

| Tool | Kind | Description |
| --- | --- | --- |
| `list_presets` | read-only | Named BSP presets from the registry |
| `list_devices` | read-only | Hardware device definitions |
| `list_releases` | read-only | Releases, optionally filtered by device (vendor-aware) |
| `list_features` | read-only | Optional BSP features |
| `export_config` | read-only | Resolved KAS YAML for `bsp_name` or `device`+`release` |
| `list_containers` | read-only | Container image definitions from the registry |
| `registry_tree` | read-only | ASCII tree view of the registry (`default`, `full` or `compact`) |
| `start_build` | job | Start a build (or `checkout_only` validation) and return a job id |
| `start_fetch` | job | Fetch all sources without building (cache pre-warm / validation) |
| `start_scan` | job | Start a CVE scan / SBOM generation (`trivy` or `syft+grype`) |
| `start_hil_test` | job | Start a HIL test run (`lava`, `direct-local`, `direct-ssh`, `direct-serial`) |
| `start_deploy` | job | Upload built artifacts to Azure Blob / AWS S3 (`dry_run` supported) |
| `start_gather` | job | Download deployed artifacts from cloud storage (`dry_run` supported) |
| `start_flash` | destructive | Flash a built image to a block device (`dry_run` defaults to **true**) |
| `start_container_build` | job | Build one or all registry-defined container images |
| `job_status` | read-only | State, return code, duration and log path of a job |
| `list_jobs` | read-only | All known jobs, including finished and lost ones |
| `job_log` | read-only | Tail of a job's combined output (1..2000 lines, optional regex filter) |
| `cancel_job` | destructive | SIGTERM the job's whole process group (kills kas/docker/bitbake) |
| `analyze_build_failure` | read-only | Classify a failed job's log into actionable categories |
| `read_task_log` | read-only | Read a bitbake task log (restricted to allowed roots) |
| `scan_findings` | read-only | Parse Trivy/Grype JSON reports of a finished scan job |
| `list_layer_pins` | read-only | Every `repos.<name>` commit pin across the registry YAML files |
| `check_layer_pins` | read-only | Compare pins with remote branch heads via `git ls-remote` |
| `bump_layer_pin` | destructive | Textually bump a pin in the working tree (comments preserved) |
| `list_remotes` | read-only | Configured named remote registries (first = default, like `origin`) |
| `add_remote` | write | Add a named remote registry (URL + branch) |
| `remove_remote` | destructive | Remove a named remote registry |
| `rename_remote` | write | Rename a configured remote registry |
| `set_remote_url` | write | Change the git URL of a configured remote registry |

Long-running work never blocks a tool call: `start_build`, `start_fetch`,
`start_scan`, `start_hil_test`, `start_deploy`, `start_gather`, `start_flash`
and `start_container_build` launch the real `bsp` CLI as a background job and
return a job id immediately; agents poll `job_status` / `job_log`.

Remote management tools edit the shared remotes configuration used by new
`bsp` CLI runs; the running MCP server keeps using the registry it resolved
at startup.

## Prompts

The server ships ready-made MCP prompts — they appear as slash commands or in
the prompt picker of MCP clients (VS Code Copilot agent mode, Claude
Desktop/Code, MCP Inspector) and are the quickest way to test the server with
a real LLM:

| Prompt | Arguments | What it does |
| --- | --- | --- |
| `smoke_test` | — | Exercises every read-only tool (including a deliberate validation error) and reports a pass/fail table |
| `explore_registry` | — | Lists presets/devices/releases/features, renders a tree, recommends what to build |
| `validate_preset` | `preset` | `export_config` sanity check + `checkout_only` build, with triage on failure |
| `build_and_triage` | `preset` | Full build, polite polling, `analyze_build_failure` + task log on failure |
| `scan_image` | `preset` | CVE scan + `scan_findings` summary with update recommendations |
| `audit_layer_pins` | — | `check_layer_pins` report; proposes bumps but never applies them unconfirmed |

### Copy-paste test prompts

If your client has no prompt picker, paste these into the chat directly:

* *"Run a smoke test of the bsp MCP server: call every read-only tool, try
  `export_config` with bsp_name `--clean` to confirm validation works, and
  give me a table of what passed and failed."* — safe everywhere, touches no
  hardware and starts no jobs.
* *"What can I build from this registry? List presets, devices, releases and
  features and show me a compact tree."*
* *"Validate the preset `<name>` without building it: export its config,
  then run a checkout-only build and triage any failure."*
* *"Build `<name>`. Poll the job status; if it fails, analyze the failure,
  read the bitbake task log and tell me the root cause and fix."*
* *"Start a build of `<name>`, then immediately cancel it and confirm the
  job ends in the `cancelled` state."* — tests job control end to end.
* *"Check all layer pins against their remote branch heads and tell me which
  are behind. Don't bump anything yet."*
* *"Scan the built `<name>` image for CVEs and summarise the findings by
  severity, highlighting the fixable criticals."*
* *"Do a dry-run deploy of `<name>`'s artifacts and show me what would be
  uploaded."* / *"Do a dry-run flash of `<name>` and tell me which image and
  tool it would use."* — both default to or support `dry_run`, so nothing is
  written.

Negative tests worth trying: ask for a nonexistent preset or device (expect a
clear "unknown" error listing alternatives), pass a name starting with `-`
(expect a validation error, not a crash), and start two builds when
`--max-jobs` is 1 (expect a refusal naming the running job).

## Failure categories

`analyze_build_failure` classifies each failure and attaches a one-line hint:

| Category | Meaning |
| --- | --- |
| `disk_space` | No space left on device / bitbake disk monitor triggered |
| `network` | DNS, timeouts, unreachable network, TLS handshake, HTTP 5xx |
| `fetch` | Source fetch failed (bad SRC_URI, stale layer pin, kas fetch) |
| `patch` | A patch no longer applies |
| `configure` | `do_configure` failed |
| `compile` | `do_compile` / `do_install` failed |
| `qa` | Package QA check failed |
| `license` | License checksum mismatch |
| `parse` | Recipe/metadata parse error, missing provider |
| `kas_config` | kas configuration error (KasUserError, missing include) |
| `image` | Rootfs/image assembly failed |
| `container` | Docker daemon not running / permission denied |
| `unknown` | Unclassified — read the evidence and task log |

Environment causes (`disk_space`, `network`) override everything else, then
the failing task name, then content patterns.

## Options

| Flag | Env var | Default | Description |
| --- | --- | --- | --- |
| `--registry` | `BSP_MCP_REGISTRY` | fetch remote | Path to a local `bsp-registry.yaml` |
| `--remote` | `BSP_MCP_REMOTE` | first configured remote | Remote registry git URL (defaults to the first remote from `bsp remotes`, like git's `origin`) |
| `--branch` | `BSP_MCP_BRANCH` | `main` | Remote registry branch |
| `--state-dir` | `BSP_MCP_STATE_DIR` | `~/.cache/bsp/mcp/jobs` | Job state directory |
| `--max-jobs` | `BSP_MCP_MAX_JOBS` | `1` | Maximum concurrently running jobs |
| `--allow-root` | `BSP_MCP_ALLOW_ROOTS` | — | Extra dir readable via `read_task_log` (repeatable; env is `os.pathsep`-separated) |
| `--read-only` | `BSP_MCP_READ_ONLY=1` | off | Disable all job, cancel and bump tools |
| `--transport` | `BSP_MCP_TRANSPORT` | `stdio` | `stdio` or `http` (streamable-http) |
| `--host` | `BSP_MCP_HOST` | `127.0.0.1` | HTTP host |
| `--port` | `BSP_MCP_PORT` | `8765` | HTTP port |

## Safety notes

* **No arbitrary shell tool** is exposed.
* Every agent-supplied name (preset, device, release, feature) is validated
  against `^[A-Za-z0-9][A-Za-z0-9_.+:-]{0,127}$`, so nothing can start with
  `-` and inject CLI flags.
* Jobs run the real `bsp` CLI as a subprocess with `--no-color --registry
  <resolved path>`, so agent runs are reproducible by hand.
* `read_task_log` only reads files under the registry directory, the state
  directory and any `--allow-root` directories.
* `bump_layer_pin` edits the working tree only — the agent commits on a
  branch and opens a pull request; LAVA tokens never appear as command-line
  arguments (they stay in the registry as `$ENV{...}`).
* `--read-only` turns the server into a pure inspection endpoint.
