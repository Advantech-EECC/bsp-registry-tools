"""
Layer-pin maintenance for the BSP MCP server.

Walks a bsp-registry checkout for kas-style YAML files, collects every
``repos.<name>`` entry that has a ``commit`` pin, checks those pins against
the remote branch head, and can bump a pin textually (preserving comments,
quoting and formatting) in the working tree.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

__all__ = ["list_pins", "check_pins", "bump_pin"]

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_LS_REMOTE_TIMEOUT = 60


def _yaml_files(root: Path) -> List[Path]:
    files = []
    for pattern in ("*.yml", "*.yaml"):
        for path in root.rglob(pattern):
            if ".git" in path.parts:
                continue
            files.append(path)
    return sorted(files)


def _load_repos(path: Path) -> Dict[str, dict]:
    """Return the top-level ``repos:`` mapping of a YAML file, or {}."""
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    repos = data.get("repos")
    if not isinstance(repos, dict):
        return {}
    return {
        name: value for name, value in repos.items() if isinstance(value, dict)
    }


def list_pins(registry_root: Path, repo_filter: Optional[str] = None) -> List[Dict]:
    """
    Collect every pinned repo (``repos.<name>`` with a ``commit``) across all
    YAML files under *registry_root*.

    The url/branch of a repo is often defined only in an included base file,
    so missing values are resolved from any file that defines that repo.
    """
    root = Path(registry_root).resolve()
    files = _yaml_files(root)

    # Index url/branch per repo name across *all* files first.
    url_index: Dict[str, str] = {}
    branch_index: Dict[str, str] = {}
    for path in files:
        for name, repo in _load_repos(path).items():
            if repo.get("url") and name not in url_index:
                url_index[name] = str(repo["url"])
            if repo.get("branch") and name not in branch_index:
                branch_index[name] = str(repo["branch"])

    pins: List[Dict] = []
    for path in files:
        for name, repo in _load_repos(path).items():
            if "commit" not in repo or repo.get("commit") in (None, ""):
                continue
            if repo_filter and repo_filter not in name:
                continue
            pins.append({
                "file": str(path.relative_to(root)),
                "repo": name,
                "commit": str(repo["commit"]),
                "branch": str(repo.get("branch") or branch_index.get(name) or "") or None,
                "url": str(repo.get("url") or url_index.get(name) or "") or None,
            })
    return pins


def _ls_remote(url: str, branch: str, cache: Dict[Tuple[str, str], Optional[str]]) -> Optional[str]:
    """Return the remote head SHA for url/branch, None if unreachable/absent."""
    key = (url, branch)
    if key in cache:
        return cache[key]
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--", url, f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
            timeout=_LS_REMOTE_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        cache[key] = None
        return None
    if result.returncode != 0:
        cache[key] = None
        return None
    head = None
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == f"refs/heads/{branch}":
            head = parts[0]
            break
    cache[key] = head if head else ""
    return cache[key]


def check_pins(registry_root: Path, repo_filter: Optional[str] = None) -> List[Dict]:
    """
    Check each pin against the remote branch head via ``git ls-remote``.

    Status is one of ``up_to_date | behind | unreachable | no_branch_or_url``.
    """
    pins = list_pins(registry_root, repo_filter)
    cache: Dict[Tuple[str, str], Optional[str]] = {}
    results: List[Dict] = []
    for pin in pins:
        url, branch = pin.get("url"), pin.get("branch")
        entry = dict(pin)
        if not url or not branch or url.startswith("-") or branch.startswith("-"):
            entry["status"] = "no_branch_or_url"
            entry["remote_head"] = None
        else:
            head = _ls_remote(url, branch, cache)
            if head is None:
                entry["status"] = "unreachable"
                entry["remote_head"] = None
            elif head == "":
                entry["status"] = "no_branch_or_url"
                entry["remote_head"] = None
            elif head == pin["commit"]:
                entry["status"] = "up_to_date"
                entry["remote_head"] = head
            else:
                entry["status"] = "behind"
                entry["remote_head"] = head
        results.append(entry)
    return results


def bump_pin(root: Path, file: str, repo: str, new_commit: str) -> Dict[str, str]:
    """
    Textually replace the ``commit:`` of *repo* in *file* with *new_commit*.

    Quotes, comments and every other line are preserved byte-for-byte.
    Only the working tree is edited — committing is the caller's job.

    Raises:
        ValueError: On a malformed SHA or a path escaping *root*.
        LookupError: If the file has no such pinned repo.
    """
    if not _SHA_RE.match(new_commit):
        raise ValueError(
            f"new_commit must be a full 40-character lowercase SHA, got '{new_commit}'"
        )
    root = Path(root).resolve()
    target = (root / file).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError(f"Path '{file}' is outside the registry root")
    if not target.is_file():
        raise LookupError(f"No such file: {file}")

    text = target.read_text()
    lines = text.splitlines(keepends=True)

    in_repos = False
    repos_indent = None
    in_repo = False
    repo_indent = None
    commit_re = re.compile(
        r"^(?P<prefix>\s*commit:\s*)(?P<quote>[\"']?)(?P<sha>[0-9a-fA-F]{4,40})(?P=quote)(?P<suffix>.*)$"
    )

    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())

        if not in_repos:
            if indent == 0 and re.match(r"^repos\s*:\s*(#.*)?$", stripped):
                in_repos = True
                repos_indent = indent
            continue

        if indent <= repos_indent:
            # Left the top-level repos: block.
            in_repos = False
            in_repo = False
            continue

        if not in_repo:
            if re.match(rf"^{re.escape(repo)}\s*:\s*(#.*)?$", stripped):
                in_repo = True
                repo_indent = indent
            continue

        if indent <= repo_indent:
            # Left this repo's block without finding commit:.
            in_repo = False
            if re.match(rf"^{re.escape(repo)}\s*:\s*(#.*)?$", stripped):
                in_repo = True
                repo_indent = indent
            continue

        m = commit_re.match(line)
        if m:
            old_commit = m.group("sha")
            newline = "\n" if raw.endswith("\n") else ""
            lines[i] = (
                m.group("prefix")
                + m.group("quote")
                + new_commit
                + m.group("quote")
                + m.group("suffix")
                + newline
            )
            target.write_text("".join(lines))
            return {"old_commit": old_commit, "new_commit": new_commit}

    raise LookupError(f"No pinned commit found for repo '{repo}' in {file}")
