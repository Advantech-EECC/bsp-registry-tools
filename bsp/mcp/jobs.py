"""
Background job runner for the BSP MCP server.

Long-running work (builds, scans, HIL tests) must never block an MCP tool
call, so each job runs the real ``bsp`` CLI as a detached subprocess in its
own process group, supervised by a thread.  Job metadata is persisted as
``job.json`` inside a per-job directory so a restarted server still knows
about earlier jobs.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

__all__ = ["Job", "JobError", "JobManager", "DEFAULT_STATE_DIR"]

DEFAULT_STATE_DIR = Path.home() / ".cache" / "bsp" / "mcp" / "jobs"

#: States a job can be in.  ``lost`` means the job was found on disk in a
#: non-terminal state after a server restart — its process is gone.
TERMINAL_STATES = {"succeeded", "failed", "cancelled", "lost"}

JOB_KINDS = {"build", "checkout", "scan", "test"}


class JobError(Exception):
    """A user-actionable job error (bad id, limit reached, bad regex, ...)."""


@dataclass
class Job:
    """A single background job running the ``bsp`` CLI."""

    id: str
    kind: str
    target: str
    command: List[str]
    state: str = "queued"
    pid: Optional[int] = None
    return_code: Optional[int] = None
    created_at: Optional[float] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    job_dir: str = ""
    extra: Dict[str, str] = field(default_factory=dict)

    @property
    def log_path(self) -> Path:
        return Path(self.job_dir) / "output.log"

    def summary(self) -> Dict:
        """Return a JSON-friendly summary including log path and duration."""
        data = asdict(self)
        data["log_path"] = str(self.log_path)
        duration = None
        if self.started_at is not None:
            end = self.finished_at if self.finished_at is not None else time.time()
            duration = round(end - self.started_at, 3)
        data["duration"] = duration
        return data


class JobManager:
    """Starts, tracks, persists and cancels background ``bsp`` CLI jobs."""

    def __init__(self, state_dir: Optional[Path] = None, max_jobs: int = 1):
        self.state_dir = Path(state_dir) if state_dir else DEFAULT_STATE_DIR
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.max_jobs = max(1, int(max_jobs))
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._cancelled: set = set()
        self._load_existing()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_existing(self) -> None:
        """Load job.json files left by previous server processes."""
        for job_json in sorted(self.state_dir.glob("*/job.json")):
            try:
                data = json.loads(job_json.read_text())
                job = Job(**{k: data[k] for k in Job.__dataclass_fields__ if k in data})
            except (OSError, ValueError, TypeError, KeyError):
                continue
            if job.state not in TERMINAL_STATES:
                # The process that supervised this job is gone.
                job.state = "lost"
                self._persist(job)
            self._jobs[job.id] = job

    def _persist(self, job: Job) -> None:
        """Atomically write job.json (temp file + rename)."""
        job_dir = Path(job.job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        tmp = job_dir / "job.json.tmp"
        tmp.write_text(json.dumps(asdict(job), indent=2))
        os.replace(tmp, job_dir / "job.json")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        kind: str,
        target: str,
        command: List[str],
        extra: Optional[Dict[str, str]] = None,
    ) -> Job:
        """
        Start *command* as a background job and return immediately.

        ``{job_dir}`` placeholders in the command args and in *extra* values
        are substituted with the job's directory before launch.
        """
        if kind not in JOB_KINDS:
            raise JobError(f"Unknown job kind '{kind}' (expected one of {sorted(JOB_KINDS)})")

        with self._lock:
            active = [j.id for j in self._jobs.values() if j.state in ("queued", "running")]
            if len(active) >= self.max_jobs:
                raise JobError(
                    f"Concurrency limit reached ({self.max_jobs}): "
                    f"job(s) {', '.join(active)} still running. "
                    "Wait for them to finish or cancel them with cancel_job."
                )

            job_id = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
            job_dir = self.state_dir / job_id
            job_dir.mkdir(parents=True, exist_ok=True)

            # Substitute the {job_dir} placeholder *before* the job starts;
            # mutating the command after the thread launched would be a race.
            rendered = [arg.replace("{job_dir}", str(job_dir)) for arg in command]
            rendered_extra = {
                k: v.replace("{job_dir}", str(job_dir)) if isinstance(v, str) else v
                for k, v in (extra or {}).items()
            }

            job = Job(
                id=job_id,
                kind=kind,
                target=target,
                command=rendered,
                created_at=time.time(),
                job_dir=str(job_dir),
                extra=rendered_extra,
            )
            self._jobs[job_id] = job
            self._persist(job)

        thread = threading.Thread(target=self._run, args=(job,), daemon=True)
        thread.start()
        return job

    def _run(self, job: Job) -> None:
        env = {**os.environ, "NO_COLOR": "1", "PYTHONUNBUFFERED": "1"}
        log_path = job.log_path
        try:
            with open(log_path, "w") as log_fh:
                log_fh.write("$ " + " ".join(job.command) + "\n")
                log_fh.flush()
                proc = subprocess.Popen(
                    job.command,
                    stdin=subprocess.DEVNULL,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env=env,
                )
                with self._lock:
                    job.pid = proc.pid
                    job.state = "running"
                    job.started_at = time.time()
                    self._persist(job)
                rc = proc.wait()
        except OSError as exc:
            with self._lock:
                job.state = "failed"
                job.finished_at = time.time()
                self._persist(job)
            try:
                with open(log_path, "a") as log_fh:
                    log_fh.write(f"Failed to start job: {exc}\n")
            except OSError:
                pass
            return

        with self._lock:
            job.return_code = rc
            job.finished_at = time.time()
            if job.id in self._cancelled:
                # Cancellation must win over the exit status of the killed
                # process group — keep the state 'cancelled'.
                job.state = "cancelled"
            else:
                job.state = "succeeded" if rc == 0 else "failed"
            self._persist(job)

    def cancel(self, job_id: str) -> Job:
        """SIGTERM the job's whole process group (kas, docker, bitbake...)."""
        job = self.get(job_id)
        with self._lock:
            if job.state in TERMINAL_STATES:
                raise JobError(f"Job {job_id} is already {job.state}")
            if job.pid is None:
                raise JobError(f"Job {job_id} has not started yet")
            self._cancelled.add(job_id)
            job.state = "cancelled"
            self._persist(job)
        try:
            os.killpg(job.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        return job

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobError(f"Unknown job id '{job_id}'")
        return job

    def list(self) -> List[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at or 0)

    def read_log(self, job_id: str, tail: int = 200, grep: Optional[str] = None) -> str:
        """Return the last *tail* lines of the job log, optionally filtered."""
        job = self.get(job_id)
        tail = max(1, min(int(tail), 2000))
        try:
            lines = job.log_path.read_text(errors="replace").splitlines()
        except FileNotFoundError:
            raise JobError(f"Job {job_id} has no log yet")
        if grep:
            try:
                pattern = re.compile(grep)
            except re.error as exc:
                raise JobError(f"Invalid grep regex '{grep}': {exc}")
            lines = [ln for ln in lines if pattern.search(ln)]
        return "\n".join(lines[-tail:])
