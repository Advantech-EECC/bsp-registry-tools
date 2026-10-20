"""
Remote BSP registry fetcher for automatic cloning and updating of a git-hosted registry.
"""

import hashlib
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

DEFAULT_REMOTE_URL = "https://github.com/Advantech-EECC/bsp-registry.git"
DEFAULT_BRANCH = "main"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "bsp" / "registry"
REGISTRY_FILENAMES = ["bsp-registry.yaml", "bsp-registry.yml"]
REGISTRY_FILENAME = REGISTRY_FILENAMES[0]


@dataclass
class RemoteRegistrySpec:
    """Specification for a single remote BSP registry source.

    Attributes:
        url: Git repository URL.
        branch: Branch to clone / pull (default: ``"main"``).
        name: Human-readable registry name used in output.  When ``None`` the
              name is derived from the repository URL (last path component
              without ``.git``).
    """

    url: str
    branch: str = DEFAULT_BRANCH
    name: Optional[str] = field(default=None)

    def resolved_name(self) -> str:
        """Return the effective registry name (explicit or URL-derived)."""
        if self.name:
            return self.name
        # Derive from URL: strip trailing .git, take last path segment
        url_stripped = self.url.rstrip("/")
        if url_stripped.endswith(".git"):
            url_stripped = url_stripped[:-4]
        return url_stripped.rstrip("/").rsplit("/", 1)[-1] or "registry"

    def cache_subdir_name(self) -> str:
        """Return a filesystem-safe subdirectory name for caching this remote.

        The name combines the resolved name with a short hash of the URL so
        that two remotes with the same ``name`` but different URLs never share
        the same cache directory.
        """
        url_hash = hashlib.sha1(self.url.encode()).hexdigest()[:8]
        safe_name = self.resolved_name().replace("/", "_").replace(":", "_")
        return f"{safe_name}-{url_hash}"

    @classmethod
    def parse(cls, remote_str: str, default_branch: str = DEFAULT_BRANCH) -> "RemoteRegistrySpec":
        """Parse a remote specification string.

        Supported formats:

        * ``URL``
        * ``URL@BRANCH``
        * ``URL@BRANCH@name=NAME``

        The ``@name=NAME`` component may appear in any position after the URL.
        """
        name: Optional[str] = None
        branch = default_branch
        remaining = remote_str

        # Extract @name=NAME anywhere in the string
        import re
        name_match = re.search(r"@name=([^@]+)", remaining)
        if name_match:
            name = name_match.group(1)
            remaining = remaining[:name_match.start()] + remaining[name_match.end():]

        # Split remaining on the first @BRANCH
        parts = remaining.split("@", 1)
        url = parts[0].strip()
        if len(parts) == 2 and parts[1].strip():
            branch = parts[1].strip()

        return cls(url=url, branch=branch, name=name)


class RegistryFetcher:
    """
    Handles fetching a remote BSP registry via git clone / pull.

    The registry is cached locally under ``~/.cache/bsp/registry`` (by default)
    so that subsequent invocations only need a lightweight ``git pull``.
    """

    def __init__(self, cache_dir: Path = DEFAULT_CACHE_DIR):
        """
        Initialize RegistryFetcher.

        Args:
            cache_dir: Local directory used to cache the cloned registry.
        """
        self.cache_dir = cache_dir
        self.logger = logging.getLogger(self.__class__.__name__)

    def fetch_registry(self, repo_url: str = DEFAULT_REMOTE_URL,
                       branch: str = DEFAULT_BRANCH,
                       update: bool = True) -> Path:
        """
        Ensure a local copy of the registry exists and (optionally) is up-to-date.

        If the cache directory does not contain a valid git repository the repository
        is cloned. Otherwise a ``git pull`` is performed when *update* is ``True``.

        Args:
            repo_url: URL of the remote git repository.
            branch: Branch to clone / pull.
            update: When ``True`` (default) run ``git pull`` on an existing clone.

        Returns:
            Path to the local ``bsp-registry.yaml`` (or ``bsp-registry.yml``) file
            inside the cache directory.

        Raises:
            SystemExit: If git operations fail or the registry file is not found.
        """
        if not self._is_cloned():
            self.logger.info("Cloning BSP registry from %s (branch: %s)", repo_url, branch)
            self._clone(repo_url, branch)
        elif update:
            self.logger.info("Updating BSP registry from remote (branch: %s)", branch)
            self._pull(branch)
        else:
            self.logger.info("Using cached BSP registry (no-update requested)")

        registry_file = next(
            (p for name in REGISTRY_FILENAMES
             for p in [self.cache_dir / name] if p.is_file()),
            None,
        )
        if registry_file is None:
            self.logger.error(
                "BSP registry file not found in cloned repository: %s",
                " or ".join(str(self.cache_dir / name) for name in REGISTRY_FILENAMES),
            )
            sys.exit(1)

        return registry_file

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_cloned(self) -> bool:
        """Return True if the cache directory looks like a valid git repository."""
        return (self.cache_dir / ".git").is_dir()

    def _clone(self, repo_url: str, branch: str) -> None:
        """Clone *repo_url* into the cache directory."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "clone", "--branch", branch, repo_url, str(self.cache_dir)]
        self.logger.debug("Running: %s", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            self.logger.error("git clone failed (return code %d): %s", e.returncode, e.stderr)
            sys.exit(1)

    def _pull(self, branch: str) -> None:
        """Fetch from remote, switch to *branch*, and pull latest changes.

        If ``git pull`` fails, retries once with ``--rebase`` before giving up.
        """
        pre_cmds = [
            ["git", "-C", str(self.cache_dir), "fetch", "origin"],
            ["git", "-C", str(self.cache_dir), "checkout", branch],
        ]
        for cmd in pre_cmds:
            self.logger.debug("Running: %s", " ".join(cmd))
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as e:
                self.logger.error(
                    "git %s failed (return code %d): %s", cmd[3], e.returncode, e.stderr
                )
                sys.exit(1)

        pull_cmd = ["git", "-C", str(self.cache_dir), "pull", "origin", branch]
        self.logger.debug("Running: %s", " ".join(pull_cmd))
        try:
            subprocess.run(pull_cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as pull_err:
            self.logger.warning(
                "git pull failed (return code %d): %s – retrying with --rebase",
                pull_err.returncode,
                pull_err.stderr,
            )
            rebase_cmd = ["git", "-C", str(self.cache_dir), "pull", "--rebase", "origin", branch]
            self.logger.debug("Running: %s", " ".join(rebase_cmd))
            try:
                subprocess.run(rebase_cmd, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as rebase_err:
                self.logger.error(
                    "git pull --rebase failed (return code %d): %s",
                    rebase_err.returncode,
                    rebase_err.stderr,
                )
                sys.exit(1)

    # ------------------------------------------------------------------
    # Multi-registry support
    # ------------------------------------------------------------------

    def fetch_multiple(
        self,
        remotes: List["RemoteRegistrySpec"],
        update: bool = True,
    ) -> List[Tuple[str, Path]]:
        """Fetch (or update) multiple remote registries independently.

        Each registry is cached under its own subdirectory inside
        ``self.cache_dir`` so that registries never overwrite each other.
        A one-time migration is performed: if the legacy ``cache_dir/.git``
        exists (single-registry layout) it is renamed to a
        ``legacy-<hash>/`` sibling directory before fetching the new remotes.

        Args:
            remotes: Ordered list of :class:`RemoteRegistrySpec` instances.
            update: When ``True`` (default) pull updates for existing clones.

        Returns:
            Ordered list of ``(registry_name, yaml_path)`` pairs, one per
            remote.  The order matches *remotes*.

        Raises:
            SystemExit: If git operations fail or a registry file is not found
                        in any of the cloned repositories.
        """
        self._maybe_migrate_legacy_cache()

        results: List[Tuple[str, Path]] = []
        seen_names: dict = {}
        for spec in remotes:
            base_name = spec.resolved_name()
            # Deduplicate display names: append suffix when the same name appears
            if base_name in seen_names:
                seen_names[base_name] += 1
                display_name = f"{base_name}-{seen_names[base_name]}"
            else:
                seen_names[base_name] = 0
                display_name = base_name

            subdir = self.cache_dir / spec.cache_subdir_name()
            sub_fetcher = RegistryFetcher(cache_dir=subdir)
            yaml_path = sub_fetcher.fetch_registry(
                repo_url=spec.url,
                branch=spec.branch,
                update=update,
            )
            results.append((display_name, yaml_path))

        return results

    def _maybe_migrate_legacy_cache(self) -> None:
        """One-time migration: rename legacy single-registry cache to a sibling directory.

        If ``cache_dir/.git`` exists we are looking at the old single-registry
        layout.  Move the entire ``cache_dir`` tree to a sibling directory
        called ``legacy-<hash>`` and recreate ``cache_dir`` so that the
        multi-registry subdirectory layout can be used.
        """
        legacy_git = self.cache_dir / ".git"
        if not legacy_git.is_dir():
            return

        import shutil

        url_hash = hashlib.sha1(str(self.cache_dir).encode()).hexdigest()[:8]
        legacy_name = f"legacy-{url_hash}"
        legacy_dest = self.cache_dir.parent / legacy_name

        if legacy_dest.exists():
            # Already migrated (or name conflict) – nothing to do.
            return

        self.logger.info(
            "Migrating legacy single-registry cache from %s to %s",
            self.cache_dir,
            legacy_dest,
        )
        shutil.move(str(self.cache_dir), str(legacy_dest))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
