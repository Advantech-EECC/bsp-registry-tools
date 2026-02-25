"""
Tests for the bsp CLI entry point (main()).
"""

from unittest.mock import MagicMock, call, patch

import bsp
from bsp import BspManager, KasManager
from bsp.registry_fetcher import DEFAULT_BRANCH, DEFAULT_REMOTE_URL


class TestMainCli:
    def test_main_list_command(self, registry_file, capsys):
        with patch("sys.argv", ["bsp", "--registry", str(registry_file), "list"]):
            exit_code = bsp.main()
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "test-bsp" in captured.out

    def test_main_containers_command(self, registry_file, capsys):
        with patch("sys.argv", ["bsp", "--registry", str(registry_file), "containers"]):
            exit_code = bsp.main()
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "ubuntu-22.04" in captured.out

    def test_main_no_command_exits(self):
        with patch("sys.argv", ["bsp"]):
            exit_code = bsp.main()
        assert exit_code != 0

    def test_main_missing_registry_exits(self, tmp_dir):
        with patch("sys.argv", [
            "bsp", "--registry", str(tmp_dir / "missing.yml"), "list"
        ]):
            exit_code = bsp.main()
        assert exit_code != 0

    def test_main_keyboard_interrupt(self, registry_file):
        with patch("sys.argv", ["bsp", "--registry", str(registry_file), "list"]):
            with patch.object(BspManager, "initialize", side_effect=KeyboardInterrupt):
                exit_code = bsp.main()
        assert exit_code == 130

    def test_main_export_command_to_stdout(self, tmp_dir, capsys):
        kas_file = tmp_dir / "test.yml"
        kas_file.write_text("header:\n  version: 14\nmachine: qemuarm64\n")
        registry_content = f"""
specification:
  version: "1.0"
registry:
  bsp:
    - name: test-bsp
      description: "Test BSP"
      build:
        path: build/test
        environment:
          container: "ubuntu-22.04"
        configuration:
          - {kas_file}
containers:
  - ubuntu-22.04:
      image: "test/ubuntu-22.04:latest"
      file: Dockerfile.ubuntu
      args: []
"""
        registry_file = tmp_dir / "bsp-registry.yml"
        registry_file.write_text(registry_content)

        with patch("sys.argv", [
            "bsp", "--registry", str(registry_file), "export", "test-bsp"
        ]):
            with patch.object(KasManager, "export_kas_config", return_value="config: data"):
                exit_code = bsp.main()
        assert exit_code == 0


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
