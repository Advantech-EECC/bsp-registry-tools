"""
Tests for the RegistryFetcher class.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from bsp.registry_fetcher import (
    DEFAULT_BRANCH,
    DEFAULT_REMOTE_URL,
    REGISTRY_FILENAME,
    RegistryFetcher,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fetcher(tmp_dir: Path) -> RegistryFetcher:
    return RegistryFetcher(cache_dir=tmp_dir / "registry-cache")


# ---------------------------------------------------------------------------
# Tests for _is_cloned
# ---------------------------------------------------------------------------

class TestIsCloned:
    def test_returns_false_when_directory_missing(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        assert not fetcher._is_cloned()

    def test_returns_false_when_no_git_dir(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        fetcher.cache_dir.mkdir(parents=True)
        assert not fetcher._is_cloned()

    def test_returns_true_when_git_dir_present(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        (fetcher.cache_dir / ".git").mkdir(parents=True)
        assert fetcher._is_cloned()


# ---------------------------------------------------------------------------
# Tests for fetch_registry (clone path)
# ---------------------------------------------------------------------------

class TestFetchRegistryClone:
    def test_clones_when_not_already_cloned(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)

        def fake_clone(cmd, **kwargs):
            # Simulate the side-effect of git clone: create .git and registry file
            (fetcher.cache_dir / ".git").mkdir(parents=True, exist_ok=True)
            (fetcher.cache_dir / REGISTRY_FILENAME).write_text("registry:\n  bsp: []\n")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_clone) as mock_run:
            result = fetcher.fetch_registry(
                repo_url="https://example.com/repo.git",
                branch="main",
                update=True,
            )

        assert result == fetcher.cache_dir / REGISTRY_FILENAME
        assert mock_run.call_count == 1
        clone_cmd = mock_run.call_args[0][0]
        assert "clone" in clone_cmd
        assert "https://example.com/repo.git" in clone_cmd

    def test_clone_failure_exits(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        fetcher.cache_dir.mkdir(parents=True)

        error = subprocess.CalledProcessError(128, "git clone", stderr="fatal: repo not found")
        with patch("subprocess.run", side_effect=error):
            with pytest.raises(SystemExit):
                fetcher.fetch_registry()


# ---------------------------------------------------------------------------
# Tests for fetch_registry (pull path)
# ---------------------------------------------------------------------------

class TestFetchRegistryPull:
    def _setup_cloned(self, fetcher: RegistryFetcher) -> None:
        """Create a minimal fake cloned repository."""
        (fetcher.cache_dir / ".git").mkdir(parents=True)
        (fetcher.cache_dir / REGISTRY_FILENAME).write_text("registry:\n  bsp: []\n")

    def test_pulls_when_already_cloned_and_update_true(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        self._setup_cloned(fetcher)

        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            result = fetcher.fetch_registry(update=True)

        assert result == fetcher.cache_dir / REGISTRY_FILENAME
        # fetch + checkout + pull
        assert mock_run.call_count == 3
        cmds = [mock_run.call_args_list[i][0][0] for i in range(3)]
        assert "fetch" in cmds[0]
        assert "checkout" in cmds[1]
        assert "pull" in cmds[2]

    def test_pull_uses_requested_branch(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        self._setup_cloned(fetcher)

        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            fetcher.fetch_registry(branch="development", update=True)

        cmds = [mock_run.call_args_list[i][0][0] for i in range(3)]
        assert "development" in cmds[1]   # checkout development
        assert "development" in cmds[2]   # pull origin development

    def test_skips_pull_when_no_update(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        self._setup_cloned(fetcher)

        with patch("subprocess.run") as mock_run:
            result = fetcher.fetch_registry(update=False)

        mock_run.assert_not_called()
        assert result == fetcher.cache_dir / REGISTRY_FILENAME

    def test_pull_failure_exits(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        self._setup_cloned(fetcher)

        error = subprocess.CalledProcessError(1, "git pull", stderr="error: network")
        with patch("subprocess.run", side_effect=error):
            with pytest.raises(SystemExit):
                fetcher.fetch_registry(update=True)


# ---------------------------------------------------------------------------
# Tests for missing registry file after clone/pull
# ---------------------------------------------------------------------------

class TestFetchRegistryMissingFile:
    def test_exits_when_registry_file_missing_after_clone(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)

        def fake_clone(cmd, **kwargs):
            # Clone succeeds but does NOT create the registry file
            (fetcher.cache_dir / ".git").mkdir(parents=True, exist_ok=True)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_clone):
            with pytest.raises(SystemExit):
                fetcher.fetch_registry()


# ---------------------------------------------------------------------------
# Tests for CLI integration with remote registry
# ---------------------------------------------------------------------------

class TestCliRemoteRegistry:
    def test_cli_uses_remote_when_no_local_registry(self, tmp_dir, registry_file):
        """When no local bsp-registry.yml exists, CLI should invoke RegistryFetcher."""
        import bsp

        fetched_path = registry_file  # reuse existing minimal registry as the "fetched" file

        with patch("sys.argv", ["bsp", "list"]):
            with patch("pathlib.Path.is_file", return_value=False):
                with patch(
                    "bsp.registry_fetcher.RegistryFetcher.fetch_registry",
                    return_value=fetched_path,
                ):
                    exit_code = bsp.main()

        assert exit_code == 0

    def test_cli_explicit_registry_overrides_remote(self, registry_file):
        """--registry flag should use the given path, skipping remote fetch."""
        import bsp

        with patch("sys.argv", ["bsp", "--registry", str(registry_file), "list"]):
            with patch(
                "bsp.registry_fetcher.RegistryFetcher.fetch_registry"
            ) as mock_fetch:
                exit_code = bsp.main()

        mock_fetch.assert_not_called()
        assert exit_code == 0

    def test_cli_local_flag_skips_remote(self, tmp_dir):
        """--local flag should fall back to local bsp-registry.yml, not fetch remote."""
        import bsp
        from bsp import BspManager

        # No local registry file -> would normally trigger remote fetch
        with patch("sys.argv", ["bsp", "--local", "list"]):
            with patch(
                "bsp.registry_fetcher.RegistryFetcher.fetch_registry"
            ) as mock_fetch:
                with patch.object(BspManager, "initialize", side_effect=SystemExit(1)):
                    exit_code = bsp.main()

        mock_fetch.assert_not_called()
        assert exit_code != 0  # exits because the local file doesn't exist
