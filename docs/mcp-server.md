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
| `start_build` | job | Start a build (or `checkout_only` validation) and return a job id |
| `start_scan` | job | Start a CVE scan / SBOM generation (`trivy` or `syft+grype`) |
| `start_hil_test` | job | Start a HIL test run (`lava`, `direct-local`, `direct-ssh`, `direct-serial`) |
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

Long-running work never blocks a tool call: `start_build`, `start_scan` and
`start_hil_test` launch the real `bsp` CLI as a background job and return a
job id immediately; agents poll `job_status` / `job_log`.

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
| `--remote` | `BSP_MCP_REMOTE` | official registry | Remote registry git URL |
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
