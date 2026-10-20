"""
``bsp-mcp`` — an MCP (Model Context Protocol) server exposing the BSP
workflow to AI agents.

Design rules:

* Long work (build/scan/test) never blocks a tool call: it is started as a
  background job running the real ``bsp`` CLI and the agent polls
  ``job_status``.
* stdout is the MCP protocol on the stdio transport, so all logging goes to
  stderr and every in-process :class:`~bsp.bsp_manager.BspManager` call runs
  with stdout/stderr redirected and a temporary logging handler attached.
* Errors the agent can act on are raised as ``ToolError`` so the model sees
  the message; genuine crashes stay generic.
* Every agent-supplied name is validated so nothing can inject CLI flags.
* No arbitrary shell tool is exposed.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import io
import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# MCP SDK compatibility shim (2.x renamed FastMCP to MCPServer)
# ---------------------------------------------------------------------------

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _ServerClass
    from mcp.server.mcpserver.exceptions import ToolError
    _MCP_V2 = True
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _ServerClass  # type: ignore
    from mcp.server.fastmcp.exceptions import ToolError  # type: ignore
    _MCP_V2 = False

from mcp.types import ToolAnnotations

from bsp.mcp import jobs as jobs_mod
from bsp.mcp import pins as pins_mod
from bsp.mcp import triage as triage_mod
from bsp.mcp.jobs import JobError, JobManager

logger = logging.getLogger("bsp.mcp")

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+:-]{0,127}$")


def _server_types():
    """
    Import :mod:`bsp.server.types` (the pydantic converters) without pulling
    in the rest of ``bsp.server`` — its ``__init__`` imports FastAPI, which
    belongs to the separate ``server`` extra.
    """
    name = "bsp.server.types"
    if name in sys.modules:
        return sys.modules[name]
    try:
        import bsp.server.types as mod
        return mod
    except ImportError:
        import importlib.util

        import bsp
        path = Path(bsp.__file__).parent / "server" / "types.py"
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

SCAN_SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
SCAN_FAIL_ON = ["NONE"] + SCAN_SEVERITIES
SCAN_TOOLS = ["trivy", "syft+grype"]
TEST_BACKENDS = ["lava", "direct-local", "direct-ssh", "direct-serial"]
_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3,
                   "NEGLIGIBLE": 4, "UNKNOWN": 5}

INSTRUCTIONS = """\
This server drives the BSP (Board Support Package) build workflow.

* Builds, scans and HIL tests run as background jobs: start_build/start_scan/
  start_hil_test return a job id immediately — poll job_status (and job_log)
  until the job reaches a terminal state. Builds can take hours.
* When a build job fails, call analyze_build_failure(job_id) FIRST: it
  classifies the failure (network, fetch, compile, ...) and gives a fix hint
  and the bitbake task log path (readable via read_task_log).
* Use start_build(..., checkout_only=true) to validate a configuration
  cheaply before committing to a full build.
* Registry changes (bump_layer_pin) only edit the working tree: commit them
  on a branch and open a pull request — never push to main directly.
"""


def make_tool_annotations(
    read_only: bool = False,
    destructive: bool = False,
    idempotent: bool = False,
    open_world: bool = False,
) -> ToolAnnotations:
    """Build ToolAnnotations across SDK generations (snake_case vs camelCase)."""
    fields = getattr(ToolAnnotations, "model_fields", {})
    if "read_only_hint" in fields:  # mcp 2.x
        return ToolAnnotations(
            read_only_hint=read_only,
            destructive_hint=destructive,
            idempotent_hint=idempotent,
            open_world_hint=open_world,
        )
    try:  # mcp 1.x
        return ToolAnnotations(
            readOnlyHint=read_only,
            destructiveHint=destructive,
            idempotentHint=idempotent,
            openWorldHint=open_world,
        )
    except (TypeError, ValueError):
        return ToolAnnotations(
            read_only_hint=read_only,
            destructive_hint=destructive,
            idempotent_hint=idempotent,
            open_world_hint=open_world,
        )


def _tool_errors(func):
    """Convert actionable exceptions to ToolError so the model sees them."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ToolError:
            raise
        except (ValueError, LookupError, PermissionError, FileNotFoundError, JobError) as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_name(value: str, what: str) -> str:
    """Validate an agent-supplied identifier (preset, device, release, ...)."""
    if not isinstance(value, str) or not NAME_RE.match(value):
        raise ValueError(
            f"Invalid {what} '{value}': must match {NAME_RE.pattern} "
            "(letters, digits, '_.+:-'; must not start with '-')"
        )
    return value


def selection_args(
    bsp_name: Optional[str] = None,
    device: Optional[str] = None,
    release: Optional[str] = None,
    features: Optional[List[str]] = None,
) -> List[str]:
    """Build the CLI selection arguments, validating every name."""
    if bsp_name and (device or release):
        raise ValueError("Provide either 'bsp_name' or 'device'/'release', not both.")
    args: List[str] = []
    if bsp_name:
        args.append(validate_name(bsp_name, "bsp_name"))
    else:
        if not device or not release:
            raise ValueError("Provide 'bsp_name' or both 'device' and 'release'.")
        args += ["--device", validate_name(device, "device")]
        args += ["--release", validate_name(release, "release")]
    for feature in features or []:
        args += ["--feature", validate_name(feature, "feature")]
    return args


# ---------------------------------------------------------------------------
# Output capture for in-process BspManager calls
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _capture():
    """
    Redirect stdout/stderr AND capture logging while a BspManager call runs.

    BspManager reports kas/registry errors through ``logging``, so without
    the temporary handler the agent would only see "Export failed: 1".
    stdout must stay clean because it carries the MCP stdio protocol.
    """
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.INFO)
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            yield buf
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


# ---------------------------------------------------------------------------
# Server context
# ---------------------------------------------------------------------------


class ServerContext:
    """Holds resolved options, the lazy BspManager and the JobManager."""

    def __init__(
        self,
        registry: Optional[str] = None,
        remote: Optional[str] = None,
        branch: Optional[str] = None,
        state_dir: Optional[str] = None,
        max_jobs: int = 1,
        allow_roots: Optional[List[str]] = None,
        read_only: bool = False,
    ):
        self._registry_opt = registry
        self._remote = remote
        self._branch = branch
        self.read_only = read_only
        self.state_dir = Path(state_dir) if state_dir else jobs_mod.DEFAULT_STATE_DIR
        self.jobs = JobManager(state_dir=self.state_dir, max_jobs=max_jobs)
        self._extra_roots = [Path(r) for r in (allow_roots or [])]
        self._registry_path: Optional[Path] = None
        self._manager = None

    # -- registry ------------------------------------------------------

    @property
    def registry_path(self) -> Path:
        if self._registry_path is None:
            if self._registry_opt:
                path = Path(self._registry_opt).expanduser().resolve()
                if not path.exists():
                    raise FileNotFoundError(f"Registry file not found: {path}")
                self._registry_path = path
            else:
                from bsp.registry_fetcher import (
                    DEFAULT_BRANCH,
                    DEFAULT_REMOTE_URL,
                    RegistryFetcher,
                )
                fetcher = RegistryFetcher()
                with _capture() as buf:
                    try:
                        self._registry_path = fetcher.fetch_registry(
                            repo_url=self._remote or DEFAULT_REMOTE_URL,
                            branch=self._branch or DEFAULT_BRANCH,
                        )
                    except SystemExit as exc:
                        raise ValueError(
                            "Failed to fetch the remote registry: "
                            + (buf.getvalue().strip() or str(exc))
                        ) from exc
        return self._registry_path

    @property
    def manager(self):
        """Lazy in-process BspManager for the read-only registry tools."""
        if self._manager is None:
            from bsp.bsp_manager import BspManager
            registry = self.registry_path
            with _capture() as buf:
                try:
                    mgr = BspManager(config_path=str(registry))
                    mgr.initialize()
                except SystemExit as exc:
                    raise ValueError(
                        "Failed to load the registry: "
                        + (buf.getvalue().strip() or str(exc))
                    ) from exc
            self._manager = mgr
        return self._manager

    @property
    def allowed_roots(self) -> List[Path]:
        return [self.registry_path.parent, self.state_dir] + self._extra_roots

    # -- jobs ----------------------------------------------------------

    def require_writable(self, action: str) -> None:
        if self.read_only:
            raise PermissionError(
                f"Server is running in read-only mode: '{action}' is disabled."
            )

    def cli_command(self) -> List[str]:
        """Locate the ``bsp`` CLI for job subprocesses."""
        candidate = Path(sys.executable).parent / "bsp"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            base = [str(candidate)]
        else:
            which = shutil.which("bsp")
            if which:
                base = [which]
            else:
                base = [sys.executable, "-m", "bsp.cli_runner"]
        return base + ["--no-color", "--registry", str(self.registry_path)]


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def build_server(ctx: ServerContext):
    server = _ServerClass(name="bsp-registry-tools", instructions=INSTRUCTIONS)

    read_only_ann = make_tool_annotations(read_only=True, idempotent=True)
    job_ann = make_tool_annotations()
    destructive_ann = make_tool_annotations(destructive=True)

    def tool(annotations, description):
        def decorate(func):
            wrapped = _tool_errors(func)
            server.tool(name=func.__name__, description=description,
                        annotations=annotations)(wrapped)
            return wrapped
        return decorate

    # -- Registry (read-only) ------------------------------------------

    @tool(read_only_ann, "List all named BSP presets defined in the registry.")
    def list_presets() -> List[Dict]:
        preset_to_response = _server_types().preset_to_response
        mgr = ctx.manager
        presets = mgr.resolver.list_presets() if mgr.resolver else []
        return [preset_to_response(p).model_dump() for p in presets]

    @tool(read_only_ann, "List all hardware device definitions.")
    def list_devices() -> List[Dict]:
        device_to_response = _server_types().device_to_response
        mgr = ctx.manager
        devices = mgr.model.registry.devices if mgr.model else []
        return [device_to_response(d).model_dump() for d in devices]

    @tool(read_only_ann,
          "List release definitions, optionally filtered by device slug "
          "(only releases applicable to that device's vendor).")
    def list_releases(device: Optional[str] = None) -> List[Dict]:
        release_to_response = _server_types().release_to_response
        mgr = ctx.manager
        releases = mgr.model.registry.releases if mgr.model else []
        if device:
            validate_name(device, "device")
            with _capture():
                try:
                    dev = mgr.resolver.get_device(device)
                except SystemExit:
                    raise ValueError(f"Unknown device '{device}'. Use list_devices.")
            releases = [
                r for r in releases
                if not r.vendor_overrides
                or any(vo.vendor == dev.vendor for vo in r.vendor_overrides)
            ]
        return [release_to_response(r).model_dump() for r in releases]

    @tool(read_only_ann, "List all optional BSP feature definitions.")
    def list_features() -> List[Dict]:
        feature_to_response = _server_types().feature_to_response
        mgr = ctx.manager
        features = mgr.model.registry.features if mgr.model else []
        return [feature_to_response(f).model_dump() for f in features]

    @tool(read_only_ann,
          "Export the resolved BSP configuration as KAS-compatible YAML. "
          "Supply either bsp_name OR both device and release.")
    def export_config(
        bsp_name: Optional[str] = None,
        device: Optional[str] = None,
        release: Optional[str] = None,
        features: Optional[List[str]] = None,
    ) -> str:
        # Validates names and bsp_name/device exclusivity.
        selection_args(bsp_name, device, release, features)
        mgr = ctx.manager
        with _capture() as buf:
            try:
                if bsp_name:
                    mgr.export_bsp_config(bsp_name=bsp_name, output_file=None)
                else:
                    mgr.export_by_components(device, release, features or [],
                                             output_file=None)
            except SystemExit as exc:
                raise ValueError(
                    "Export failed: " + (buf.getvalue().strip() or str(exc))
                ) from exc
        return buf.getvalue()

    # -- Jobs -----------------------------------------------------------

    @tool(job_ann,
          "Start a BSP build as a background job and return its job id "
          "immediately (poll job_status). checkout_only validates the "
          "configuration without building; clean forces a clean build.")
    def start_build(
        bsp_name: Optional[str] = None,
        device: Optional[str] = None,
        release: Optional[str] = None,
        features: Optional[List[str]] = None,
        checkout_only: bool = False,
        clean: bool = False,
    ) -> Dict:
        ctx.require_writable("start_build")
        sel = selection_args(bsp_name, device, release, features)
        cmd = ctx.cli_command() + ["build"] + sel
        if checkout_only:
            cmd.append("--checkout")
        if clean:
            cmd.append("--clean")
        kind = "checkout" if checkout_only else "build"
        job = ctx.jobs.start(kind, bsp_name or f"{device}/{release}", cmd)
        return job.summary()

    @tool(job_ann,
          "Start a CVE scan (and SBOM generation) of previously built "
          "artifacts as a background job. Reports land in the job's "
          "reports directory; use scan_findings when it finishes.")
    def start_scan(
        bsp_name: Optional[str] = None,
        device: Optional[str] = None,
        release: Optional[str] = None,
        features: Optional[List[str]] = None,
        severity: str = "HIGH",
        fail_on: str = "CRITICAL",
        tool: str = "trivy",
    ) -> Dict:
        ctx.require_writable("start_scan")
        if severity not in SCAN_SEVERITIES:
            raise ValueError(f"severity must be one of {SCAN_SEVERITIES}")
        if fail_on not in SCAN_FAIL_ON:
            raise ValueError(f"fail_on must be one of {SCAN_FAIL_ON}")
        if tool not in SCAN_TOOLS:
            raise ValueError(f"tool must be one of {SCAN_TOOLS}")
        sel = selection_args(bsp_name, device, release, features)
        cmd = ctx.cli_command() + ["scan"] + sel + [
            "--tool", tool,
            "--severity", severity,
            "--fail-on", fail_on,
            "--output-dir", "{job_dir}/reports",
        ]
        job = ctx.jobs.start("scan", bsp_name or f"{device}/{release}", cmd,
                             extra={"reports_dir": "{job_dir}/reports"})
        return job.summary()

    @tool(job_ann,
          "Start a hardware-in-the-loop test run as a background job "
          "(always waits for the result inside the job). Tokens are never "
          "passed as arguments; they stay in the registry as $ENV{...}.")
    def start_hil_test(
        bsp_name: Optional[str] = None,
        device: Optional[str] = None,
        release: Optional[str] = None,
        features: Optional[List[str]] = None,
        backend: str = "lava",
    ) -> Dict:
        ctx.require_writable("start_hil_test")
        if backend not in TEST_BACKENDS:
            raise ValueError(f"backend must be one of {TEST_BACKENDS}")
        sel = selection_args(bsp_name, device, release, features)
        cmd = ctx.cli_command() + ["test"] + sel + ["--backend", backend, "--wait"]
        lava_server = os.environ.get("BSP_MCP_LAVA_SERVER")
        if backend == "lava" and lava_server:
            cmd += ["--lava-server", lava_server]
        job = ctx.jobs.start("test", bsp_name or f"{device}/{release}", cmd)
        return job.summary()

    @tool(read_only_ann, "Get the current status and summary of a job.")
    def job_status(job_id: str) -> Dict:
        return ctx.jobs.get(job_id).summary()

    @tool(read_only_ann, "List all known jobs (including finished and lost ones).")
    def list_jobs() -> List[Dict]:
        return [j.summary() for j in ctx.jobs.list()]

    @tool(read_only_ann,
          "Read the tail of a job's combined output log. tail is clamped to "
          "1..2000 lines; grep filters lines with a regex.")
    def job_log(job_id: str, tail: int = 200, grep: Optional[str] = None) -> str:
        return ctx.jobs.read_log(job_id, tail=tail, grep=grep)

    @tool(destructive_ann,
          "Cancel a running job: SIGTERMs the whole process group so kas, "
          "docker and bitbake children terminate too.")
    def cancel_job(job_id: str) -> Dict:
        ctx.require_writable("cancel_job")
        return ctx.jobs.cancel(job_id).summary()

    # -- Triage ----------------------------------------------------------

    @tool(read_only_ann,
          "Analyze a failed build/checkout job's log: classifies each "
          "failure (network, fetch, compile, ...), gives a fix hint, the "
          "failing recipe/task and the bitbake task log path.")
    def analyze_build_failure(job_id: str) -> Dict:
        job = ctx.jobs.get(job_id)
        try:
            text = job.log_path.read_text(errors="replace")
        except FileNotFoundError:
            raise JobError(f"Job {job_id} has no log yet")
        result = triage_mod.analyze_log(text)
        result["job_id"] = job_id
        result["job_state"] = job.state
        return result

    @tool(read_only_ann,
          "Read the tail of a bitbake task log (path from "
          "analyze_build_failure). Only paths under the allowed roots are "
          "readable.")
    def read_task_log(path: str, tail: int = 200) -> str:
        return triage_mod.read_task_log(path, ctx.allowed_roots, tail=tail)

    @tool(read_only_ann,
          "Parse a finished scan job's Trivy/Grype JSON reports: returns "
          "counts by severity, the fixable count, findings sorted by "
          "severity and the SBOM file names.")
    def scan_findings(job_id: str) -> Dict:
        job = ctx.jobs.get(job_id)
        reports_dir = Path(job.extra.get("reports_dir") or (Path(job.job_dir) / "reports"))
        if not reports_dir.is_dir():
            raise JobError(
                f"Job {job_id} has no reports directory yet ({reports_dir}). "
                "Wait for the scan job to finish."
            )
        findings: List[Dict] = []
        sboms: List[str] = []
        for path in sorted(reports_dir.glob("*.json")):
            name = path.name
            if name.endswith(".cdx.json") or name.endswith(".spdx.json"):
                sboms.append(name)
                continue
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and "Results" in data:  # Trivy
                for result in data.get("Results") or []:
                    for vuln in result.get("Vulnerabilities") or []:
                        findings.append({
                            "id": vuln.get("VulnerabilityID"),
                            "package": vuln.get("PkgName"),
                            "installed": vuln.get("InstalledVersion"),
                            "fixed": vuln.get("FixedVersion") or None,
                            "severity": (vuln.get("Severity") or "UNKNOWN").upper(),
                            "title": vuln.get("Title"),
                            "source": name,
                        })
            elif isinstance(data, dict) and "matches" in data:  # Grype
                for match in data.get("matches") or []:
                    vuln = match.get("vulnerability") or {}
                    artifact = match.get("artifact") or {}
                    fix = (vuln.get("fix") or {})
                    versions = fix.get("versions") or []
                    findings.append({
                        "id": vuln.get("id"),
                        "package": artifact.get("name"),
                        "installed": artifact.get("version"),
                        "fixed": versions[0] if versions else None,
                        "severity": (vuln.get("severity") or "UNKNOWN").upper(),
                        "title": vuln.get("description"),
                        "source": name,
                    })
        findings.sort(key=lambda f: _SEVERITY_ORDER.get(f["severity"], 99))
        counts: Dict[str, int] = {}
        for f in findings:
            counts[f["severity"]] = counts.get(f["severity"], 0) + 1
        return {
            "job_id": job_id,
            "total": len(findings),
            "counts_by_severity": counts,
            "fixable": sum(1 for f in findings if f["fixed"]),
            "findings": findings,
            "sbom_files": sorted(sboms),
        }

    # -- Maintenance ------------------------------------------------------

    @tool(read_only_ann,
          "List every pinned layer repo (repos.<name> with a commit) across "
          "all YAML files in the registry, with its branch and url (resolved "
          "from included base files when needed).")
    def list_layer_pins(repo_filter: Optional[str] = None) -> List[Dict]:
        if repo_filter:
            validate_name(repo_filter, "repo_filter")
        return pins_mod.list_pins(ctx.registry_path.parent, repo_filter)

    @tool(read_only_ann,
          "Check every layer pin against the remote branch head via "
          "git ls-remote. Status: up_to_date | behind | unreachable | "
          "no_branch_or_url.")
    def check_layer_pins(repo_filter: Optional[str] = None) -> List[Dict]:
        if repo_filter:
            validate_name(repo_filter, "repo_filter")
        return pins_mod.check_pins(ctx.registry_path.parent, repo_filter)

    @tool(destructive_ann,
          "Bump a layer pin to a new full 40-char commit SHA. Edits the file "
          "textually in the working tree only (comments and formatting are "
          "preserved); commit the change on a branch and open a PR.")
    def bump_layer_pin(file: str, repo: str, new_commit: str) -> Dict:
        ctx.require_writable("bump_layer_pin")
        validate_name(repo, "repo")
        return pins_mod.bump_pin(ctx.registry_path.parent, file, repo, new_commit)

    return server


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _env_roots() -> List[str]:
    raw = os.environ.get("BSP_MCP_ALLOW_ROOTS", "")
    return [r for r in raw.split(os.pathsep) if r]


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bsp-mcp",
        description="MCP server exposing bsp-registry-tools to AI agents",
    )
    parser.add_argument("--registry", default=os.environ.get("BSP_MCP_REGISTRY"),
                        help="Path to a local bsp-registry.yaml (env: BSP_MCP_REGISTRY). "
                             "Default: fetch the remote registry.")
    parser.add_argument("--remote", default=os.environ.get("BSP_MCP_REMOTE"),
                        help="Remote registry git URL (env: BSP_MCP_REMOTE)")
    parser.add_argument("--branch", default=os.environ.get("BSP_MCP_BRANCH"),
                        help="Remote registry branch (env: BSP_MCP_BRANCH)")
    parser.add_argument("--state-dir", default=os.environ.get("BSP_MCP_STATE_DIR"),
                        help="Job state directory (env: BSP_MCP_STATE_DIR, "
                             "default: ~/.cache/bsp/mcp/jobs)")
    parser.add_argument("--max-jobs", type=int,
                        default=int(os.environ.get("BSP_MCP_MAX_JOBS", "1")),
                        help="Maximum concurrently running jobs (env: BSP_MCP_MAX_JOBS, default: 1)")
    parser.add_argument("--allow-root", action="append", dest="allow_roots",
                        default=_env_roots(),
                        help="Extra directory readable via read_task_log; repeatable "
                             "(env: BSP_MCP_ALLOW_ROOTS, os.pathsep-separated)")
    parser.add_argument("--read-only", action="store_true",
                        default=os.environ.get("BSP_MCP_READ_ONLY") == "1",
                        help="Disable all job, cancel and bump tools (env: BSP_MCP_READ_ONLY=1)")
    parser.add_argument("--transport", choices=["stdio", "http"],
                        default=os.environ.get("BSP_MCP_TRANSPORT", "stdio"),
                        help="Transport: stdio (default) or http (streamable-http)")
    parser.add_argument("--host", default=os.environ.get("BSP_MCP_HOST", "127.0.0.1"),
                        help="HTTP host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("BSP_MCP_PORT", "8765")),
                        help="HTTP port (default: 8765)")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    # stdout carries the MCP stdio protocol — send all logging to stderr.
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = parse_args(argv)

    ctx = ServerContext(
        registry=args.registry,
        remote=args.remote,
        branch=args.branch,
        state_dir=args.state_dir,
        max_jobs=args.max_jobs,
        allow_roots=args.allow_roots,
        read_only=args.read_only,
    )
    server = build_server(ctx)

    if args.transport == "http":
        if _MCP_V2:
            server.run(transport="streamable-http", host=args.host, port=args.port)
        else:
            server.settings.host = args.host
            server.settings.port = args.port
            server.run(transport="streamable-http")
    else:
        server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
