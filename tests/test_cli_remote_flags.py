"""
Tests for the --remote, --branch, --update/--no-update, and --local CLI flags.
"""

from unittest.mock import patch

import bsp
from bsp.registry_fetcher import DEFAULT_BRANCH, DEFAULT_REMOTE_URL


class TestMainCliRemoteFlags:
    """Tests covering the new --remote, --branch, --update/--no-update, and --local flags."""

    def test_default_remote_url_passed_to_fetcher(self, registry_file):
        """When no local registry exists, the default remote URL is forwarded to RegistryFetcher."""
        with patch("sys.argv", ["bsp", "list"]):
            with patch("pathlib.Path.is_file", return_value=False):
                with patch(
                    "bsp.registry_fetcher.RegistryFetcher.fetch_registry",
                    return_value=registry_file,
                ) as mock_fetch:
                    exit_code = bsp.main()

        mock_fetch.assert_called_once_with(
            repo_url=DEFAULT_REMOTE_URL,
            branch=DEFAULT_BRANCH,
            update=True,
        )
        assert exit_code == 0

    def test_custom_remote_url_passed_to_fetcher(self, registry_file):
        """--remote flag forwards a custom URL to RegistryFetcher."""
        custom_url = "https://github.com/my-org/bsp-registry.git"
        with patch("sys.argv", ["bsp", "--remote", custom_url, "list"]):
            with patch("pathlib.Path.is_file", return_value=False):
                with patch(
                    "bsp.registry_fetcher.RegistryFetcher.fetch_registry",
                    return_value=registry_file,
                ) as mock_fetch:
                    exit_code = bsp.main()

        mock_fetch.assert_called_once_with(
            repo_url=custom_url,
            branch=DEFAULT_BRANCH,
            update=True,
        )
        assert exit_code == 0

    def test_custom_branch_passed_to_fetcher(self, registry_file):
        """--branch flag forwards a custom branch name to RegistryFetcher."""
        with patch("sys.argv", ["bsp", "--branch", "dev", "list"]):
            with patch("pathlib.Path.is_file", return_value=False):
                with patch(
                    "bsp.registry_fetcher.RegistryFetcher.fetch_registry",
                    return_value=registry_file,
                ) as mock_fetch:
                    exit_code = bsp.main()

        mock_fetch.assert_called_once_with(
            repo_url=DEFAULT_REMOTE_URL,
            branch="dev",
            update=True,
        )
        assert exit_code == 0

    def test_no_update_flag_passes_update_false_to_fetcher(self, registry_file):
        """--no-update passes update=False to RegistryFetcher."""
        with patch("sys.argv", ["bsp", "--no-update", "list"]):
            with patch("pathlib.Path.is_file", return_value=False):
                with patch(
                    "bsp.registry_fetcher.RegistryFetcher.fetch_registry",
                    return_value=registry_file,
                ) as mock_fetch:
                    exit_code = bsp.main()

        mock_fetch.assert_called_once_with(
            repo_url=DEFAULT_REMOTE_URL,
            branch=DEFAULT_BRANCH,
            update=False,
        )
        assert exit_code == 0

    def test_update_flag_passes_update_true_to_fetcher(self, registry_file):
        """--update (explicit) passes update=True to RegistryFetcher."""
        with patch("sys.argv", ["bsp", "--update", "list"]):
            with patch("pathlib.Path.is_file", return_value=False):
                with patch(
                    "bsp.registry_fetcher.RegistryFetcher.fetch_registry",
                    return_value=registry_file,
                ) as mock_fetch:
                    exit_code = bsp.main()

        mock_fetch.assert_called_once_with(
            repo_url=DEFAULT_REMOTE_URL,
            branch=DEFAULT_BRANCH,
            update=True,
        )
        assert exit_code == 0

    def test_local_flag_skips_fetcher(self, registry_file):
        """--local skips RegistryFetcher and uses the local bsp-registry.yml path."""
        with patch("sys.argv", ["bsp", "--local", "--registry", str(registry_file), "list"]):
            with patch(
                "bsp.registry_fetcher.RegistryFetcher.fetch_registry"
            ) as mock_fetch:
                exit_code = bsp.main()

        mock_fetch.assert_not_called()
        assert exit_code == 0

    def test_explicit_registry_skips_fetcher(self, registry_file):
        """--registry <path> skips RegistryFetcher regardless of other flags."""
        with patch("sys.argv", ["bsp", "--registry", str(registry_file), "list"]):
            with patch(
                "bsp.registry_fetcher.RegistryFetcher.fetch_registry"
            ) as mock_fetch:
                exit_code = bsp.main()

        mock_fetch.assert_not_called()
        assert exit_code == 0

    def test_local_bsp_registry_in_cwd_skips_fetcher(self, registry_file, tmp_dir, monkeypatch):
        """When bsp-registry.yml exists in the CWD, remote fetch is skipped."""
        # Change working directory so the file is auto-detected
        monkeypatch.chdir(tmp_dir)
        with patch("sys.argv", ["bsp", "list"]):
            with patch(
                "bsp.registry_fetcher.RegistryFetcher.fetch_registry"
            ) as mock_fetch:
                exit_code = bsp.main()

        mock_fetch.assert_not_called()
        assert exit_code == 0

    def test_remote_and_branch_combined(self, registry_file):
        """--remote and --branch together are both forwarded to RegistryFetcher."""
        custom_url = "https://github.com/corp/registry.git"
        with patch("sys.argv", ["bsp", "--remote", custom_url, "--branch", "release", "list"]):
            with patch("pathlib.Path.is_file", return_value=False):
                with patch(
                    "bsp.registry_fetcher.RegistryFetcher.fetch_registry",
                    return_value=registry_file,
                ) as mock_fetch:
                    exit_code = bsp.main()

        mock_fetch.assert_called_once_with(
            repo_url=custom_url,
            branch="release",
            update=True,
        )
        assert exit_code == 0
