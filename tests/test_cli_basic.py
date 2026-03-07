"""
Tests for the bsp CLI entry point (main()) – v2.0 schema.
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

    def test_main_list_features_command(self, registry_with_features_file, capsys):
        with patch("sys.argv", ["bsp", "--registry", str(registry_with_features_file), "list", "features"]):
            exit_code = bsp.main()
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "ota" in captured.out

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
        kas_file = tmp_dir / "test-base.yaml"
        kas_file.write_text("header:\n  version: 14\nmachine: qemuarm64\n")
        kas_file2 = tmp_dir / "test.yaml"
        kas_file2.write_text("header:\n  version: 14\nmachine: qemuarm64\n")
        registry_content = f"""
specification:
  version: "2.0"
containers:
  ubuntu-22.04:
    image: "test/ubuntu-22.04:latest"
    file: Dockerfile.ubuntu
    args: []
registry:
  devices:
    - slug: test-device
      description: "Test Device"
      vendor: test-vendor
      soc_vendor: test-soc
      build:
        container: "ubuntu-22.04"
        path: build/test
        includes:
          - {kas_file2}
  releases:
    - slug: test-release
      description: "Test Release"
      yocto_version: "5.0"
      includes:
        - {kas_file}
  features: []
  bsp:
    - name: test-bsp
      description: "Test BSP"
      device: test-device
      release: test-release
      features: []
"""
        registry_file = tmp_dir / "bsp-registry.yaml"
        registry_file.write_text(registry_content)

        with patch("sys.argv", [
            "bsp", "--registry", str(registry_file), "export", "test-bsp"
        ]):
            with patch.object(KasManager, "export_kas_config", return_value="config: data"):
                exit_code = bsp.main()
        assert exit_code == 0

    def test_main_build_by_components(self, tmp_dir):
        """bsp build --device <d> --release <r> should work."""
        kas_file = tmp_dir / "test-base.yaml"
        kas_file.write_text("header:\n  version: 14\nmachine: qemuarm64\n")
        registry_content = f"""
specification:
  version: "2.0"
containers:
  ubuntu-22.04:
    image: "test/ubuntu-22.04:latest"
    file: null
    args: []
registry:
  devices:
    - slug: test-device
      description: "Test Device"
      vendor: test-vendor
      soc_vendor: test-soc
      build:
        container: "ubuntu-22.04"
        path: build/test
        includes:
          - {kas_file}
  releases:
    - slug: test-release
      description: "Test Release"
      includes: []
  features: []
  bsp: []
"""
        registry_file = tmp_dir / "bsp-registry.yaml"
        registry_file.write_text(registry_content)

        with patch("sys.argv", [
            "bsp", "--registry", str(registry_file),
            "build", "--device", "test-device", "--release", "test-release"
        ]):
            with patch.object(KasManager, "build_project") as mock_build, \
                 patch.object(KasManager, "dump_config", return_value=None), \
                 patch.object(KasManager, "validate_kas_files", return_value=True), \
                 patch.object(KasManager, "check_kas_available", return_value=True):
                exit_code = bsp.main()
        assert exit_code == 0
        mock_build.assert_called_once()

    def test_main_build_ambiguous_args_fails(self, registry_file):
        """Mixing preset name with --device/--release should fail."""
        with patch("sys.argv", [
            "bsp", "--registry", str(registry_file),
            "build", "my-preset", "--device", "d", "--release", "r"
        ]):
            exit_code = bsp.main()
        assert exit_code != 0

    def test_main_build_missing_args_fails(self, registry_file):
        """bsp build with no name and no --device/--release should fail."""
        with patch("sys.argv", [
            "bsp", "--registry", str(registry_file), "build"
        ]):
            exit_code = bsp.main()
        assert exit_code != 0
