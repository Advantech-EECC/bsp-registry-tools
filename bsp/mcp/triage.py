"""
Build-failure triage for the BSP MCP server.

Turns raw kas/bitbake output into a structured report an AI agent can act
on: per-failure category, a one-line fix hint, the failing recipe/task, the
bitbake task log path and the evidence lines the classification is based on.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

__all__ = ["analyze_log", "read_task_log", "CATEGORY_HINTS"]

# ---------------------------------------------------------------------------
# Category hints
# ---------------------------------------------------------------------------

CATEGORY_HINTS: Dict[str, str] = {
    "disk_space": "Free disk space on the build host (or raise BB_DISKMON_DIRS limits) and retry.",
    "network": "Transient network problem: check connectivity/proxy/DNS and retry the job.",
    "fetch": "Source fetch failed: verify the recipe SRC_URI / layer pin (commit, branch, url) is still valid.",
    "patch": "A patch no longer applies: refresh the patch against the pinned source revision.",
    "configure": "Configure step failed: check missing dependencies or configure flags in the task log.",
    "compile": "Compile/install error: inspect the task log for the first compiler error and fix the recipe or source.",
    "qa": "Package QA check failed: fix the packaging issue or add a documented INSANE_SKIP.",
    "license": "License checksum mismatch: update LIC_FILES_CHKSUM after reviewing the new license text.",
    "parse": "Recipe/metadata parse error: fix the recipe syntax or the missing provider in the layer set.",
    "kas_config": "kas configuration error: fix the kas YAML (includes, keys) in the registry.",
    "image": "Image/rootfs assembly failed: check package install conflicts in the task log.",
    "container": "Docker/container problem: ensure the Docker daemon is running and the user may access it.",
    "unknown": "Unclassified failure: read the evidence lines and the task log for the root cause.",
}

# ---------------------------------------------------------------------------
# Line parsers
# ---------------------------------------------------------------------------

# ERROR: busybox-1.36.1-r0 do_compile: oe_runmake failed
_TASK_FAIL_RE = re.compile(
    r"^ERROR:\s+(?P<recipe>\S+?)-(?P<version>[^-\s]+(?:-r\d+)?)\s+(?P<task>do_[A-Za-z0-9_]+):\s*(?P<msg>.*)$"
)
_LOGFILE_RE = re.compile(r"Logfile of failure stored in:\s*(?P<path>\S+)")
_TASK_FAILED_RE = re.compile(r"Task\s+\((?:[^)]*\.bb:)?(?P<task>do_[A-Za-z0-9_]+)\)\s+failed")
_SUMMARY_RE = re.compile(r"Summary:\s+(?P<count>\d+)\s+task(?:s)?\s+failed")

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

# 1. Environment causes override everything else.
_DISK_SPACE_RES = [
    re.compile(r"No space left on device", re.I),
    re.compile(r"disk monitor", re.I),
    re.compile(r"Immediately (?:halt|abort).*disk", re.I),
]
# NOTE: deliberately no bare "TLS"/"gnutls" pattern — it would catch failures
# in the gnutls *recipe*.  Only the explicit handshake error counts.
_NETWORK_RES = [
    re.compile(r"Could not resolve host", re.I),
    re.compile(r"Connection timed out", re.I),
    re.compile(r"Network is unreachable", re.I),
    re.compile(r"Temporary failure in name resolution", re.I),
    re.compile(r"SSL certificate problem", re.I),
    re.compile(r"gnutls_handshake\(\) failed"),
    re.compile(r"(?:HTTP|server)\s+(?:error\s+)?5\d\d", re.I),
    re.compile(r"error:?\s*5\d\d\b.*(?:http|server)", re.I),
]

# 2. Failing task → category.
_TASK_CATEGORY = {
    "do_fetch": "fetch",
    "do_unpack": "fetch",
    "do_patch": "patch",
    "do_configure": "configure",
    "do_compile": "compile",
    "do_install": "compile",
    "do_package_qa": "qa",
    "do_populate_lic": "license",
    "do_rootfs": "image",
}

# 3. Content regexes, in order.
_CONTENT_RES = [
    ("fetch", re.compile(r"Fetcher failure|Unable to fetch URL|fetch repos failed|do_fetch", re.I)),
    ("patch", re.compile(r"(?:Applying patch|patch).*(?:failed|does not apply)|Hunk #\d+ FAILED", re.I)),
    ("parse", re.compile(r"ParseError|Nothing (?:RPROVIDES|PROVIDES)", re.I)),
    ("kas_config", re.compile(r"KasUserError|kas\.config|include file .* not found|Missing include", re.I)),
    ("license", re.compile(r"LIC_FILES_CHKSUM|license.*(?:mismatch|checksum)", re.I)),
    ("qa", re.compile(r"QA Issue|do_package_qa", re.I)),
    ("compile", re.compile(r"(?:^|\s)(?:error:|undefined reference|oe_runmake failed|compilation terminated)", re.I)),
    ("image", re.compile(r"do_rootfs|do_image|Could not invoke dnf|opkg_install", re.I)),
    ("container", re.compile(r"Cannot connect to the Docker daemon|docker:\s+permission denied|Is the docker daemon running", re.I)),
]


def _classify(task: Optional[str], text: str) -> str:
    """Classify one failure's context window."""
    for rx in _DISK_SPACE_RES:
        if rx.search(text):
            return "disk_space"
    for rx in _NETWORK_RES:
        if rx.search(text):
            return "network"
    if task:
        if task in _TASK_CATEGORY:
            return _TASK_CATEGORY[task]
        if task.startswith("do_image"):
            return "image"
    for category, rx in _CONTENT_RES:
        if rx.search(text):
            return category
    return "unknown"


def analyze_log(text: str) -> Dict:
    """
    Analyse kas/bitbake output and return a structured failure report:
    ``{failed_task_count, categories, failures: [...]}``.
    """
    lines = text.splitlines()
    failures: List[Dict] = []
    failed_task_count = 0
    summary_count: Optional[int] = None

    # Collect per-recipe failures.  A failure's context window ends at the
    # next recipe failure so evidence never bleeds between failures.
    starts: List[int] = []
    for i, line in enumerate(lines):
        if _TASK_FAIL_RE.match(line):
            starts.append(i)
        m = _SUMMARY_RE.search(line)
        if m:
            summary_count = int(m.group("count"))
        if _TASK_FAILED_RE.search(line):
            failed_task_count += 1

    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        window = lines[start:end]
        m = _TASK_FAIL_RE.match(lines[start])
        task_log = None
        for ln in window:
            lm = _LOGFILE_RE.search(ln)
            if lm:
                task_log = lm.group("path")
                break
        window_text = "\n".join(window)
        task = m.group("task")
        category = _classify(task, window_text)
        evidence = [ln for ln in window if ln.strip()][:12]
        failures.append({
            "category": category,
            "hint": CATEGORY_HINTS[category],
            "recipe": m.group("recipe"),
            "task": task,
            "message": m.group("msg").strip(),
            "task_log": task_log,
            "evidence": evidence,
        })

    if summary_count is not None:
        failed_task_count = summary_count
    elif not failed_task_count:
        failed_task_count = len(failures)

    if not failures:
        # kas / git clone style failures with no bitbake task failure:
        # fall back to error lines, including git's 'fatal:' lines which
        # carry the real cause between kas ERROR lines.
        evidence = [
            ln for ln in lines
            if ln.lstrip().startswith("fatal:")
            or re.search(r"\bERROR\b|\berror\b:", ln)
        ][:20]
        if evidence:
            category = _classify(None, "\n".join(evidence))
            failures.append({
                "category": category,
                "hint": CATEGORY_HINTS[category],
                "recipe": None,
                "task": None,
                "message": evidence[0].strip(),
                "task_log": None,
                "evidence": evidence,
            })

    return {
        "failed_task_count": failed_task_count,
        "categories": sorted({f["category"] for f in failures}),
        "failures": failures,
    }


def read_task_log(path: str, allowed_roots: List[Path], tail: int = 200) -> str:
    """
    Read the tail of a bitbake task log, refusing paths outside *allowed_roots*.

    Raises:
        PermissionError: If the resolved path is not under an allowed root.
        FileNotFoundError: If the file does not exist.
    """
    resolved = Path(path).resolve()
    roots = [Path(r).resolve() for r in allowed_roots]
    for root in roots:
        try:
            resolved.relative_to(root)
            break
        except ValueError:
            continue
    else:
        raise PermissionError(
            f"Path '{resolved}' is outside the allowed roots: "
            + ", ".join(str(r) for r in roots)
        )
    tail = max(1, min(int(tail), 2000))
    lines = resolved.read_text(errors="replace").splitlines()
    return "\n".join(lines[-tail:])
