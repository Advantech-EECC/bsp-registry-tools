"""
Persistent management of named KAS repository overlays.

Overlays let users override the repository URL, branch, tag, commit, or
local checkout path of individual KAS repos without editing the shared
``bsp-registry`` YAML files.  They are stored in a YAML file at
``~/.config/bsp/overlays.yaml`` (overridable via the ``BSP_OVERLAYS_CONFIG``
environment variable) in the following format::

    overlays:
      - name: modular-bsp-dev
        description: Local work on modular BSP
        repos:
          meta-modular-bsp-nxp:
            branch: feature/ota-rework
          meta-imx:
            url: https://github.com/example/meta-imx.git
            branch: fix/display
          meta-local:
            path: /home/user/src/meta-local

The design mirrors ``git remote``:

- ``bsp overlay list``                      — list overlay names
- ``bsp overlay add``                       — create a new named overlay
- ``bsp overlay remove``                    — remove a named overlay
- ``bsp overlay show``                      — show details of an overlay
- ``bsp overlay set-repo <o> <repo>=<spec>``  — set a repo URL/ref override
- ``bsp overlay set-path <o> <repo>=<path>``  — point a repo at a local checkout
- ``bsp overlay unset-repo <o> <repo>``       — drop the override for a repo
- ``bsp --overlay <o> build ...``             — apply an overlay to a build

At build time the active overlay is rendered into a small KAS YAML fragment
that is appended *after* the registry-provided KAS files, so KAS's standard
configuration merging applies the overrides on top of the registry defaults.
"""

import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml


# ---------------------------------------------------------------------------
# Config file location
# ---------------------------------------------------------------------------

DEFAULT_OVERLAYS_CONFIG = Path.home() / ".config" / "bsp" / "overlays.yaml"

# KAS config format version used for the generated overlay fragment.  Kept in
# sync with V2Resolver.generate_kas_yaml.
KAS_OVERLAY_HEADER_VERSION = 14

_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _overlays_config_path() -> Path:
    """Return the active overlays config file path.

    Can be overridden via the ``BSP_OVERLAYS_CONFIG`` environment variable.
    """
    env = os.environ.get("BSP_OVERLAYS_CONFIG")
    return Path(env) if env else DEFAULT_OVERLAYS_CONFIG


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class RepoOverride:
    """Override values for a single KAS repository.

    All fields are optional; only the set fields are applied on top of the
    registry-provided repo definition.

    Attributes:
        url:    Replacement git repository URL.
        branch: Branch to check out.
        tag:    Tag to check out.
        commit: Full commit SHA to check out.
        path:   Local checkout directory; when set the repository is used
                in-place instead of being cloned.
    """

    url: Optional[str] = None
    branch: Optional[str] = None
    tag: Optional[str] = None
    commit: Optional[str] = None
    path: Optional[str] = None

    def to_dict(self) -> dict:
        result = {}
        for key in ("url", "branch", "tag", "commit", "path"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "RepoOverride":
        return cls(
            url=data.get("url"),
            branch=data.get("branch"),
            tag=data.get("tag"),
            commit=data.get("commit"),
            path=data.get("path"),
        )

    def describe(self) -> str:
        """Return a compact human-readable summary of the override."""
        if self.path:
            return f"path={self.path}"
        parts = []
        if self.url:
            parts.append(f"url={self.url}")
        if self.branch:
            parts.append(f"branch={self.branch}")
        if self.tag:
            parts.append(f"tag={self.tag}")
        if self.commit:
            parts.append(f"commit={self.commit}")
        return ", ".join(parts) or "(empty)"


@dataclass
class OverlayEntry:
    """A single named overlay: a set of per-repo overrides.

    Attributes:
        name:        Display name used to reference this overlay.
        description: Optional free-form description.
        repos:       Mapping of KAS repo name to its :class:`RepoOverride`.
    """

    name: str
    description: str = ""
    repos: Dict[str, RepoOverride] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "repos": {repo: ov.to_dict() for repo, ov in self.repos.items()},
        }


# ---------------------------------------------------------------------------
# Repo spec parsing
# ---------------------------------------------------------------------------


def _classify_refspec(refspec: str) -> Tuple[str, str]:
    """Classify a refspec string into a (kind, value) pair.

    Explicit prefixes ``branch:``, ``tag:`` and ``commit:`` are honored.
    Otherwise a 40-character hex string is treated as a commit and anything
    else as a branch name.
    """
    for prefix in ("branch", "tag", "commit"):
        if refspec.startswith(prefix + ":"):
            value = refspec[len(prefix) + 1:]
            if not value:
                logging.error("Empty %s in refspec '%s'", prefix, refspec)
                sys.exit(1)
            return prefix, value
    if _GIT_SHA_RE.match(refspec):
        return "commit", refspec
    return "branch", refspec


def _looks_like_url(value: str) -> bool:
    """Return True when *value* looks like a bare git URL rather than a
    ``<repo>=...`` or ``<repo>@...`` spec.

    Only the part before the first ``=`` is inspected so that specs like
    ``meta-x=https://host/repo.git`` are not mistaken for bare URLs.
    """
    head = value.split("=", 1)[0]
    return "://" in head or head.startswith("git@")


def _split_url_refspec(value: str) -> Tuple[str, Optional[str]]:
    """Split ``<url>[@<refspec>]`` into ``(url, refspec-or-None)``.

    Only an ``@`` that appears *after* the first ``/`` of the host/path part
    can separate a refspec: userinfo in URLs like ``https://user@host/path``
    or ``git@host:org/repo.git`` always occurs before the first slash, so it
    is never mistaken for a refspec separator.  The *last* such ``@`` is used.
    """
    scheme_end = value.find("://")
    path_search_start = scheme_end + 3 if scheme_end != -1 else 0
    first_slash = value.find("/", path_search_start)
    if first_slash == -1:
        # No path component (e.g. scp-style git@host:repo.git) — no refspec.
        return value, None
    at_pos = value.rfind("@")
    if at_pos <= first_slash:
        return value, None
    return value[:at_pos], value[at_pos + 1:]


def _derive_repo_name_from_url(url: str) -> str:
    """Derive a repo name from a git URL (last path segment, sans ``.git``)."""
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    if ":" in tail:
        # scp-style URL without a slash after the colon: git@host:repo.git
        tail = tail.rsplit(":", 1)[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    if not tail:
        logging.error("Could not derive a repo name from URL '%s'. "
                      "Use the explicit '<repo>=<url>[@<refspec>]' form.", url)
        sys.exit(1)
    return tail


def parse_repo_spec(spec: str) -> Tuple[str, RepoOverride]:
    """Parse a repo override spec into ``(repo_name, RepoOverride)``.

    Supported formats::

        <repo>@<refspec>              # keep registry URL, override refspec
        <repo>=<url>                  # override URL only
        <repo>=<url>@<refspec>        # override URL and refspec
        <url>                         # override URL; repo name derived from URL
        <url>@<refspec>               # override URL and refspec; name derived

    When a bare URL is given, the repo name is derived from the last path
    segment of the URL (with any ``.git`` suffix removed).

    ``<refspec>`` may use the explicit prefixes ``branch:``, ``tag:`` or
    ``commit:``; a bare 40-character SHA is treated as a commit and any other
    bare value as a branch name.

    Raises:
        SystemExit: If the spec cannot be parsed.
    """
    spec = spec.strip()
    url: Optional[str] = None
    refspec: Optional[str] = None

    if _looks_like_url(spec):
        # Bare URL form: derive the repo name from the URL itself.  Split the
        # refspec at the last '@' so credentials in the URL are preserved
        # (e.g. https://user@host/org/repo@feature/foo).
        url, refspec = _split_url_refspec(spec)
        repo = _derive_repo_name_from_url(url)
    elif "=" in spec:
        repo, _, rest = spec.partition("=")
        url, refspec = _split_url_refspec(rest)
    elif "@" in spec:
        repo, _, refspec = spec.partition("@")
    else:
        logging.error(
            "Invalid repo spec '%s'. Use '<repo>@<refspec>', '<repo>=<url>', "
            "'<repo>=<url>@<refspec>' or '<url>[@<refspec>]'.",
            spec,
        )
        sys.exit(1)

    repo = repo.strip()
    if not repo:
        logging.error("Invalid repo spec '%s': missing repo name.", spec)
        sys.exit(1)
    if url is not None and not url.strip():
        logging.error("Invalid repo spec '%s': missing URL.", spec)
        sys.exit(1)

    override = RepoOverride(url=url.strip() if url else None)
    if refspec:
        kind, value = _classify_refspec(refspec.strip())
        setattr(override, kind, value)
    return repo, override


def parse_path_spec(spec: str) -> Tuple[str, str]:
    """Parse a ``<repo>=<local-path>`` spec into ``(repo_name, abs_path)``.

    ``~`` and environment variables in the path are expanded and the result
    is made absolute.

    Raises:
        SystemExit: If the spec cannot be parsed.
    """
    if "=" not in spec:
        logging.error("Invalid path spec '%s'. Use '<repo>=<local-path>'.", spec)
        sys.exit(1)
    repo, _, raw_path = spec.partition("=")
    repo = repo.strip()
    raw_path = raw_path.strip()
    if not repo or not raw_path:
        logging.error("Invalid path spec '%s'. Use '<repo>=<local-path>'.", spec)
        sys.exit(1)
    path = Path(os.path.expandvars(raw_path)).expanduser()
    return repo, str(path.resolve()) if path.exists() else str(path.absolute())


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class OverlayManager:
    """Read/write the persistent overlays configuration file.

    All mutating operations load the file, apply the change, and save
    immediately so that concurrent CLI invocations see a consistent view.

    Args:
        config_path: Path to the YAML config file.  Defaults to
                     ``~/.config/bsp/overlays.yaml`` (or ``BSP_OVERLAYS_CONFIG``).
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self.config_path = config_path or _overlays_config_path()
        self.logger = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> List[OverlayEntry]:
        """Load and return all configured overlays.

        Returns an empty list if the config file does not exist yet.
        """
        if not self.config_path.is_file():
            return []
        try:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except (OSError, yaml.YAMLError) as exc:
            self.logger.warning(
                "Could not read overlays config '%s': %s", self.config_path, exc
            )
            return []

        overlays_raw = data.get("overlays", []) or []
        result = []
        for item in overlays_raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            repos_raw = item.get("repos") or {}
            repos: Dict[str, RepoOverride] = {}
            if isinstance(repos_raw, dict):
                for repo_name, ov in repos_raw.items():
                    if isinstance(ov, dict):
                        repos[str(repo_name)] = RepoOverride.from_dict(ov)
            result.append(OverlayEntry(
                name=str(name),
                description=str(item.get("description") or ""),
                repos=repos,
            ))
        return result

    def save(self, overlays: List[OverlayEntry]) -> None:
        """Persist the given list of overlays to disk.

        Creates parent directories if they do not exist.
        """
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"overlays": [o.to_dict() for o in overlays]}
        with open(self.config_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, default_flow_style=False, sort_keys=False)
        self.logger.debug("Saved overlays config to '%s'", self.config_path)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(
        self,
        name: str,
        description: str = "",
        repo_specs: Optional[List[str]] = None,
    ) -> OverlayEntry:
        """Create a new overlay.

        Args:
            name:        Unique name for the overlay.
            description: Optional free-form description.
            repo_specs:  Optional list of ``<repo>@<refspec>`` /
                         ``<repo>=<url>[@<refspec>]`` specs applied initially.

        Returns:
            The newly created :class:`OverlayEntry`.

        Raises:
            SystemExit: If an overlay with *name* already exists.
        """
        overlays = self.load()
        if any(o.name == name for o in overlays):
            logging.error(
                "Overlay '%s' already exists. Use 'set-repo'/'set-path' to modify it.",
                name,
            )
            sys.exit(1)
        entry = OverlayEntry(name=name, description=description)
        for spec in repo_specs or []:
            repo, override = parse_repo_spec(spec)
            entry.repos[repo] = override
        overlays.append(entry)
        self.save(overlays)
        return entry

    def remove(self, name: str) -> None:
        """Remove an overlay by name.

        Raises:
            SystemExit: If no overlay with *name* exists.
        """
        overlays = self.load()
        new_overlays = [o for o in overlays if o.name != name]
        if len(new_overlays) == len(overlays):
            logging.error("Overlay '%s' not found.", name)
            self._print_available(overlays)
            sys.exit(1)
        self.save(new_overlays)

    def get(self, name: str) -> OverlayEntry:
        """Return an overlay by name.

        Raises:
            SystemExit: If no overlay with *name* exists.
        """
        overlays = self.load()
        for o in overlays:
            if o.name == name:
                return o
        logging.error("Overlay '%s' not found.", name)
        self._print_available(overlays)
        sys.exit(1)

    def set_repo(self, name: str, spec: str) -> OverlayEntry:
        """Set (or replace) a repository override on an overlay.

        Args:
            name: Overlay name.
            spec: ``<repo>@<refspec>`` or ``<repo>=<url>[@<refspec>]`` spec.

        Returns:
            The updated :class:`OverlayEntry`.

        Raises:
            SystemExit: If no overlay with *name* exists or the spec is invalid.
        """
        repo, override = parse_repo_spec(spec)
        return self._update(name, repo, override)

    def set_path(self, name: str, spec: str) -> OverlayEntry:
        """Point a repository at a local checkout directory.

        Args:
            name: Overlay name.
            spec: ``<repo>=<local-path>`` spec.

        Returns:
            The updated :class:`OverlayEntry`.

        Raises:
            SystemExit: If no overlay with *name* exists or the spec is invalid.
        """
        repo, path = parse_path_spec(spec)
        return self._update(name, repo, RepoOverride(path=path))

    def unset_repo(self, name: str, repo: str) -> OverlayEntry:
        """Remove the override for *repo* from an overlay.

        Raises:
            SystemExit: If the overlay or the repo override does not exist.
        """
        overlays = self.load()
        for o in overlays:
            if o.name == name:
                if repo not in o.repos:
                    logging.error(
                        "Overlay '%s' has no override for repo '%s'.", name, repo
                    )
                    available = ", ".join(sorted(o.repos)) or "(none)"
                    print(f"Overridden repos: {available}")
                    sys.exit(1)
                del o.repos[repo]
                self.save(overlays)
                return o
        logging.error("Overlay '%s' not found.", name)
        self._print_available(overlays)
        sys.exit(1)

    # ------------------------------------------------------------------
    # KAS YAML generation
    # ------------------------------------------------------------------

    @staticmethod
    def build_overlay_kas_config(entry: OverlayEntry) -> dict:
        """Return the KAS config dict representing *entry*'s overrides.

        The fragment relies on KAS's configuration merging: when appended
        after the registry KAS files, dictionary keys set here override the
        registry-provided values while unset keys are inherited.

        For URL/refspec overrides, stale refspec keys from the registry are
        explicitly cleared so that e.g. a ``commit`` pin in the registry does
        not defeat a ``branch`` override.  For local path overrides, ``url``
        and all refspec keys are cleared so KAS uses the checkout in-place.

        The KAS schema allows ``null`` for ``url``, ``branch`` and ``tag``
        (null removes a default value), but ``commit`` must be a string, so
        an empty string is used to clear it (KAS treats a falsy commit as
        unset).
        """
        repos: dict = {}
        for repo_name, ov in entry.repos.items():
            repo_cfg: dict = {}
            if ov.path:
                repo_cfg["path"] = ov.path
                # Clear url + refspecs so KAS treats it as a local repo.
                repo_cfg["url"] = None
                repo_cfg["branch"] = None
                repo_cfg["tag"] = None
                repo_cfg["commit"] = ""
            else:
                if ov.url:
                    repo_cfg["url"] = ov.url
                if ov.branch or ov.tag or ov.commit:
                    # Clear all refspec keys, then set the requested one, so
                    # registry-level pins do not conflict with the override.
                    repo_cfg["branch"] = ov.branch
                    repo_cfg["tag"] = ov.tag
                    repo_cfg["commit"] = ov.commit or ""
            repos[repo_name] = repo_cfg
        return {
            "header": {"version": KAS_OVERLAY_HEADER_VERSION},
            "repos": repos,
        }

    def generate_overlay_kas_yaml(self, entry: OverlayEntry, output_path: str) -> None:
        """Write the KAS YAML fragment for *entry* to *output_path*."""
        config = self.build_overlay_kas_config(entry)
        with open(output_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(config, fh, default_flow_style=False, sort_keys=False)
        self.logger.debug(
            "Generated overlay KAS YAML for '%s': %s", entry.name, output_path
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update(self, name: str, repo: str, override: RepoOverride) -> OverlayEntry:
        overlays = self.load()
        for o in overlays:
            if o.name == name:
                o.repos[repo] = override
                self.save(overlays)
                return o
        logging.error("Overlay '%s' not found.", name)
        self._print_available(overlays)
        sys.exit(1)

    def _print_available(self, overlays: List[OverlayEntry]) -> None:
        available = ", ".join(o.name for o in overlays) or "(none)"
        print(f"Available overlays: {available}")
