"""
Tests for the BSP MCP server (bsp.mcp): triage, pins, jobs, validation and an
optional end-to-end stdio run.

The whole module is skipped when the optional ``mcp`` SDK is not installed
(``pip install bsp-registry-tools[mcp]``, Python 3.10+).
"""

import json
import os
import stat
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from bsp.mcp import triage
from bsp.mcp.jobs import JobError, JobManager
from bsp.mcp.pins import bump_pin, list_pins
from bsp.mcp.server import selection_args, validate_free_value

# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------

BITBAKE_TWO_FAILURES = textwrap.dedent("""\
    NOTE: Executing Tasks
    ERROR: busybox-1.36.1-r0 do_compile: oe_runmake failed
    ERROR: busybox-1.36.1-r0 do_compile: ExecutionError('/work/temp/run.do_compile.123', 1, None, None)
    ERROR: Logfile of failure stored in: /work/tmp/work/busybox/temp/log.do_compile.123
    coreutils.c:10:5: error: unknown type name 'foo'
    ERROR: Task (/layers/meta/recipes-core/busybox/busybox_1.36.1.bb:do_compile) failed with exit code '1'
    ERROR: linux-imx-6.1.55-r0 do_fetch: Fetcher failure: Unable to fetch URL from any source.
    ERROR: Logfile of failure stored in: /work/tmp/work/linux-imx/temp/log.do_fetch.456
    ERROR: Task (/layers/meta-freescale/recipes-kernel/linux/linux-imx_6.1.55.bb:do_fetch) failed with exit code '1'
    NOTE: Tasks Summary: Attempted 4000 tasks of which 3998 didn't need to be rerun and all succeeded.
    Summary: 2 tasks failed:
      /layers/meta/recipes-core/busybox/busybox_1.36.1.bb:do_compile
      /layers/meta-freescale/recipes-kernel/linux/linux-imx_6.1.55.bb:do_fetch
""")


class TestTriage:
    def test_two_failures_classified_independently(self):
        result = triage.analyze_log(BITBAKE_TWO_FAILURES)
        assert result["failed_task_count"] == 2
        failures = result["failures"]
        by_recipe = {f["recipe"]: f for f in failures}
        assert by_recipe["busybox"]["category"] == "compile"
        assert by_recipe["busybox"]["task"] == "do_compile"
        assert by_recipe["busybox"]["task_log"] == (
            "/work/tmp/work/busybox/temp/log.do_compile.123"
        )
        assert by_recipe["linux-imx"]["category"] == "fetch"
        assert by_recipe["linux-imx"]["task_log"] == (
            "/work/tmp/work/linux-imx/temp/log.do_fetch.456"
        )
        assert set(result["categories"]) == {"compile", "fetch"}

    def test_kas_user_error_is_kas_config(self):
        log = "ERROR: KasUserError: Error in configuration file: missing key\n"
        result = triage.analyze_log(log)
        assert result["failures"][0]["category"] == "kas_config"

    def test_disk_space_overrides_task(self):
        log = textwrap.dedent("""\
            ERROR: glibc-2.38-r0 do_compile: No space left on device
            ERROR: Task (/layers/meta/recipes-core/glibc/glibc_2.38.bb:do_compile) failed with exit code '1'
        """)
        result = triage.analyze_log(log)
        assert result["failures"][0]["category"] == "disk_space"

    def test_gnutls_recipe_compile_failure_is_not_network(self):
        log = textwrap.dedent("""\
            ERROR: gnutls-3.8.0-r0 do_compile: oe_runmake failed
            gnutls_cipher.c:55: error: implicit declaration of function
            ERROR: Task (/layers/meta/recipes-support/gnutls/gnutls_3.8.0.bb:do_compile) failed with exit code '1'
        """)
        result = triage.analyze_log(log)
        assert result["failures"][0]["category"] == "compile"

    def test_kas_clone_failure_fatal_line_network(self):
        log = textwrap.dedent("""\
            2024-01-01 10:00:00 - ERROR - Could not clone repository
            fatal: unable to access 'https://example.com/repo.git/': Could not resolve host: example.com
            2024-01-01 10:00:00 - ERROR - fetch repos failed
        """)
        result = triage.analyze_log(log)
        failure = result["failures"][0]
        assert failure["category"] == "network"
        assert any("Could not resolve host" in ln for ln in failure["evidence"])
        assert any(ln.startswith("fatal:") for ln in failure["evidence"])

    def test_read_task_log_refuses_outside_roots(self, tmp_path):
        with pytest.raises(PermissionError):
            triage.read_task_log("/etc/passwd", [tmp_path])

    def test_read_task_log_inside_root(self, tmp_path):
        log = tmp_path / "log.do_compile"
        log.write_text("line1\nline2\n")
        assert triage.read_task_log(str(log), [tmp_path]) == "line1\nline2"


# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------

BASE_YAML = textwrap.dedent("""\
    header:
      version: 14
    repos:
      meta-foo:
        url: https://example.com/meta-foo.git
        branch: kirkstone
      meta-bar:
        url: https://example.com/meta-bar.git
        branch: kirkstone
""")

PINNED_YAML = textwrap.dedent("""\
    header:
      version: 14
      includes:
        - base.yml
    repos:
      meta-foo:
        # pinned for release 1.2
        commit: 1111111111111111111111111111111111111111
      meta-bar:
        commit: "2222222222222222222222222222222222222222"  # keep in sync
""")


@pytest.fixture
def pin_tree(tmp_path):
    (tmp_path / "base.yml").write_text(BASE_YAML)
    (tmp_path / "pinned.yml").write_text(PINNED_YAML)
    return tmp_path


class TestPins:
    def test_inherited_url_is_resolved(self, pin_tree):
        pins = {p["repo"]: p for p in list_pins(pin_tree)}
        assert pins["meta-foo"]["url"] == "https://example.com/meta-foo.git"
        assert pins["meta-foo"]["branch"] == "kirkstone"
        assert pins["meta-foo"]["commit"] == "1" * 40
        assert pins["meta-bar"]["commit"] == "2" * 40

    def test_bump_preserves_comments_and_other_repos(self, pin_tree):
        new_sha = "a" * 40
        result = bump_pin(pin_tree, "pinned.yml", "meta-bar", new_sha)
        assert result == {"old_commit": "2" * 40, "new_commit": new_sha}
        text = (pin_tree / "pinned.yml").read_text()
        assert "# pinned for release 1.2" in text
        assert f'commit: "{new_sha}"  # keep in sync' in text
        assert "commit: " + "1" * 40 in text  # other repo untouched
        assert (pin_tree / "base.yml").read_text() == BASE_YAML

    def test_bump_rejects_bad_sha(self, pin_tree):
        with pytest.raises(ValueError):
            bump_pin(pin_tree, "pinned.yml", "meta-foo", "deadbeef")
        with pytest.raises(ValueError):
            bump_pin(pin_tree, "pinned.yml", "meta-foo", "A" * 40)

    def test_bump_rejects_missing_repo(self, pin_tree):
        with pytest.raises(LookupError):
            bump_pin(pin_tree, "pinned.yml", "meta-nope", "a" * 40)

    def test_bump_rejects_path_escape(self, pin_tree):
        with pytest.raises(ValueError):
            bump_pin(pin_tree, "../pinned.yml", "meta-foo", "a" * 40)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_bsp(tmp_path):
    """A fake 'bsp' script controlled by its first argument."""
    script = tmp_path / "fake-bsp"
    script.write_text(textwrap.dedent("""\
        #!/bin/sh
        case "$1" in
          ok) echo "build ok"; exit 0 ;;
          fail) echo "build failed" >&2; exit 3 ;;
          sleep) echo "sleeping"; sleep 60 ;;
          echodir) echo "DIR=$2"; exit 0 ;;
        esac
    """))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def _wait_terminal(manager, job_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        if job.state in ("succeeded", "failed", "cancelled", "lost"):
            return job
        time.sleep(0.05)
    pytest.fail(f"job {job_id} did not finish: {manager.get(job_id).state}")


class TestJobs:
    def test_success(self, tmp_path, fake_bsp):
        mgr = JobManager(state_dir=tmp_path / "state")
        job = mgr.start("build", "demo", [fake_bsp, "ok"])
        job = _wait_terminal(mgr, job.id)
        assert job.state == "succeeded"
        assert job.return_code == 0
        log = mgr.read_log(job.id)
        assert "build ok" in log
        assert log.splitlines()[0].startswith("$ ")  # command on first line
        assert job.summary()["duration"] is not None

    def test_failure(self, tmp_path, fake_bsp):
        mgr = JobManager(state_dir=tmp_path / "state")
        job = mgr.start("build", "demo", [fake_bsp, "fail"])
        job = _wait_terminal(mgr, job.id)
        assert job.state == "failed"
        assert job.return_code == 3
        assert "build failed" in mgr.read_log(job.id)

    def test_persistence_across_managers(self, tmp_path, fake_bsp):
        state = tmp_path / "state"
        mgr = JobManager(state_dir=state)
        job = mgr.start("build", "demo", [fake_bsp, "ok"])
        _wait_terminal(mgr, job.id)

        mgr2 = JobManager(state_dir=state)
        reloaded = mgr2.get(job.id)
        assert reloaded.state == "succeeded"

    def test_non_terminal_jobs_become_lost(self, tmp_path):
        state = tmp_path / "state"
        job_dir = state / "20240101-000000-deadbeef"
        job_dir.mkdir(parents=True)
        (job_dir / "job.json").write_text(json.dumps({
            "id": "20240101-000000-deadbeef",
            "kind": "build",
            "target": "demo",
            "command": ["bsp", "build"],
            "state": "running",
            "job_dir": str(job_dir),
        }))
        mgr = JobManager(state_dir=state)
        assert mgr.get("20240101-000000-deadbeef").state == "lost"

    def test_concurrency_limit(self, tmp_path, fake_bsp):
        mgr = JobManager(state_dir=tmp_path / "state", max_jobs=1)
        job = mgr.start("build", "demo", [fake_bsp, "sleep"])
        try:
            with pytest.raises(JobError) as exc:
                mgr.start("build", "demo2", [fake_bsp, "ok"])
            assert job.id in str(exc.value)
        finally:
            # Wait until pid is known, then cancel.
            deadline = time.time() + 10
            while mgr.get(job.id).pid is None and time.time() < deadline:
                time.sleep(0.05)
            mgr.cancel(job.id)
            _wait_terminal(mgr, job.id)

    def test_cancel_stays_cancelled(self, tmp_path, fake_bsp):
        mgr = JobManager(state_dir=tmp_path / "state")
        job = mgr.start("build", "demo", [fake_bsp, "sleep"])
        deadline = time.time() + 10
        while mgr.get(job.id).pid is None and time.time() < deadline:
            time.sleep(0.05)
        mgr.cancel(job.id)
        job = _wait_terminal(mgr, job.id)
        assert job.state == "cancelled"

    def test_job_dir_substitution(self, tmp_path, fake_bsp):
        mgr = JobManager(state_dir=tmp_path / "state")
        job = mgr.start("scan", "demo", [fake_bsp, "echodir", "{job_dir}/reports"],
                        extra={"reports_dir": "{job_dir}/reports"})
        assert "{job_dir}" not in " ".join(job.command)
        assert job.extra["reports_dir"] == f"{job.job_dir}/reports"
        job = _wait_terminal(mgr, job.id)
        assert f"DIR={job.job_dir}/reports" in mgr.read_log(job.id)

    def test_read_log_bad_regex(self, tmp_path, fake_bsp):
        mgr = JobManager(state_dir=tmp_path / "state")
        job = mgr.start("build", "demo", [fake_bsp, "ok"])
        _wait_terminal(mgr, job.id)
        with pytest.raises(JobError, match="Invalid grep regex"):
            mgr.read_log(job.id, grep="[unclosed")


# ---------------------------------------------------------------------------
# selection_args validation
# ---------------------------------------------------------------------------


class TestSelectionArgs:
    def test_rejects_flag_injection(self):
        with pytest.raises(ValueError, match="Invalid bsp_name"):
            selection_args(bsp_name="--clean")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError):
            selection_args(device="rsb 4810", release="scarthgap")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            selection_args(bsp_name="")

    def test_rejects_both_selections(self):
        with pytest.raises(ValueError, match="not both"):
            selection_args(bsp_name="demo", device="rsb-4810", release="scarthgap")

    def test_valid_selection(self):
        assert selection_args(bsp_name="demo-bsp") == ["demo-bsp"]
        assert selection_args(device="rsb-4810", release="scarthgap",
                              features=["docker"]) == [
            "--device", "rsb-4810", "--release", "scarthgap", "--feature", "docker",
        ]


class TestFreeValue:
    def test_accepts_paths_urls_and_templates(self):
        assert validate_free_value("/dev/sdb", "target") == "/dev/sdb"
        assert validate_free_value("{device}/{release}", "prefix")
        assert validate_free_value("https://example.com/repo.git", "url")

    def test_rejects_flag_injection(self):
        with pytest.raises(ValueError, match="Invalid target"):
            validate_free_value("--force", "target")

    def test_rejects_empty_and_control_chars(self):
        with pytest.raises(ValueError):
            validate_free_value("", "prefix")
        with pytest.raises(ValueError):
            validate_free_value("a\nb", "prefix")


class TestNewJobKinds:
    @pytest.mark.parametrize(
        "kind", ["fetch", "deploy", "flash", "gather", "container_build"]
    )
    def test_new_kinds_accepted(self, tmp_path, fake_bsp, kind):
        mgr = JobManager(state_dir=tmp_path / "state")
        job = mgr.start(kind, "demo", [fake_bsp, "ok"])
        job = _wait_terminal(mgr, job.id)
        assert job.kind == kind
        assert job.state == "succeeded"


# ---------------------------------------------------------------------------
# End-to-end over stdio (needs a real registry)
# ---------------------------------------------------------------------------

REGISTRY_ENV = "BSP_TEST_REGISTRY"


def _is_error(result) -> bool:
    flag = getattr(result, "is_error", None)
    if flag is None:
        flag = getattr(result, "isError", False)
    return bool(flag)


def _text(result) -> str:
    return result.content[0].text


@pytest.mark.skipif(
    not os.environ.get(REGISTRY_ENV),
    reason=f"{REGISTRY_ENV} not set (must point at a bsp-registry.yml)",
)
class TestEndToEndStdio:
    async def test_tools_and_errors(self, tmp_path):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m", "bsp.mcp.server",
                "--registry", os.environ[REGISTRY_ENV],
                "--state-dir", str(tmp_path / "state"),
            ],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                assert "list_presets" in names
                assert "start_build" in names
                assert {"start_fetch", "start_deploy", "start_gather",
                        "start_flash", "start_container_build",
                        "list_containers", "registry_tree", "list_remotes",
                        "add_remote", "remove_remote", "rename_remote",
                        "set_remote_url"} <= names
                assert len(names) == 30

                prompts = await session.list_prompts()
                prompt_names = {p.name for p in prompts.prompts}
                assert {"smoke_test", "explore_registry", "validate_preset",
                        "build_and_triage", "scan_image",
                        "audit_layer_pins"} <= prompt_names
                prompt = await session.get_prompt(
                    "validate_preset", {"preset": "demo-bsp"}
                )
                text = prompt.messages[0].content.text
                assert "demo-bsp" in text
                assert "checkout_only" in text

                result = await session.call_tool("list_presets", {})
                assert not _is_error(result)

                bad = await session.call_tool("export_config", {"bsp_name": "--clean"})
                assert _is_error(bad)
                assert "Invalid bsp_name" in _text(bad)

                unknown = await session.call_tool(
                    "list_releases", {"device": "no-such-device-xyz"}
                )
                assert _is_error(unknown)
                assert "Unknown device" in _text(unknown)

                presets = json.loads(_text(result))
                if presets:
                    name = presets[0]["name"] if isinstance(presets, list) else presets["name"]
                    export = await session.call_tool("export_config", {"bsp_name": name})
                    if _is_error(export):
                        # Offline environments may not be able to resolve
                        # remote includes — the error must say why.
                        assert _text(export).strip()
                    else:
                        assert _text(export).strip()
