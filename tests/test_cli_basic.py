"""
Tests for the basic bsp CLI entry point (main()) commands (v2.0).
"""

from unittest.mock import patch

import bsp
from bsp import BspManager, KasManager


class TestMainCli:
    def test_main_list_command(self, registry_file, capsys):
        with patch("sys.argv", ["bsp", "--registry", str(registry_file), "list"]):
            exit_code = bsp.main()
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "test-bsp" in captured.out

    def test_main_list_devices_command(self, registry_file, capsys):
        with patch("sys.argv", ["bsp", "--registry", str(registry_file), "list", "devices"]):
            exit_code = bsp.main()
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "test-device" in captured.out

    def test_main_list_releases_command(self, registry_file, capsys):
        with patch("sys.argv", ["bsp", "--registry", str(registry_file), "list", "releases"]):
            exit_code = bsp.main()
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "test-release" in captured.out

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
            "bsp", "--registry", str(tmp_dir / "missing.yaml"), "list"
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
  version: "2.0"
containers:
  - ubuntu-22.04:
      image: "test/ubuntu-22.04:latest"
      file: Dockerfile.ubuntu
      args: []
registry:
  devices:
    - slug: test-device
      description: "Test Device"
      vendor: test-vendor
      soc_vendor: arm
      build:
        path: build/test
        container: "ubuntu-22.04"
        includes:
          - {kas_file}
  releases:
    - slug: test-release
      description: "Test Release"
  bsp:
    - name: test-bsp
      description: "Test BSP"
      device: test-device
      release: test-release
"""
        registry_file = tmp_dir / "bsp-registry.yaml"
        registry_file.write_text(registry_content)

        with patch("sys.argv", [
            "bsp", "--registry", str(registry_file), "export", "test-bsp"
        ]):
            with patch.object(KasManager, "export_kas_config", return_value="config: data"):
                exit_code = bsp.main()
        assert exit_code == 0

    def test_main_tree_command(self, registry_file, capsys):
        with patch("sys.argv", ["bsp", "--registry", str(registry_file), "tree"]):
            exit_code = bsp.main()
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "BSP Registry" in captured.out
        assert "test-device" in captured.out
        assert "test-release" in captured.out

    def test_main_tree_no_color_flag(self, registry_file, capsys):
        with patch("sys.argv", ["bsp", "--registry", str(registry_file), "--no-color", "tree"]):
            exit_code = bsp.main()
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "BSP Registry" in captured.out
        assert "\x1b[" not in captured.out
