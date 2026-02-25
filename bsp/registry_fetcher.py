"""
Remote BSP registry fetcher for automatic cloning and updating of a git-hosted registry.
"""

import logging
import subprocess
import sys
from pathlib import Path

DEFAULT_REMOTE_URL = "https://github.com/Advantech-EECC/bsp-registry.git"
DEFAULT_BRANCH = "main"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "bsp" / "registry"
REGISTRY_FILENAME = "bsp-registry.yml"


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
            Path to the local ``bsp-registry.yml`` file inside the cache directory.

        Raises:
            SystemExit: If git operations fail or the registry file is not found.
        """
        if not self._is_cloned():
            self.logger.info("Cloning BSP registry from %s (branch: %s)", repo_url, branch)
            self._clone(repo_url, branch)
        elif update:
            self.logger.info("Updating BSP registry from remote")
            self._pull()
        else:
            self.logger.info("Using cached BSP registry (no-update requested)")

        registry_file = self.cache_dir / REGISTRY_FILENAME
        if not registry_file.is_file():
            self.logger.error(
                "BSP registry file not found in cloned repository: %s", registry_file
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

    def _pull(self) -> None:
        """Run ``git pull`` inside the cache directory."""
        cmd = ["git", "-C", str(self.cache_dir), "pull"]
        self.logger.debug("Running: %s", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            self.logger.error("git pull failed (return code %d): %s", e.returncode, e.stderr)
            sys.exit(1)
