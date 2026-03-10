"""
Tests for YAML parsing utilities and container list-to-dict conversion (v2.0).
"""

import subprocess
import pytest
from unittest.mock import patch, MagicMock

from bsp import (
    Docker,
    RegistryRoot,
    read_yaml_file,
    parse_yaml_file,
    get_registry_from_yaml_file,
    convert_containers_list_to_dict,
)
from bsp.utils import build_docker
from .conftest import INVALID_YAML, MINIMAL_REGISTRY_YAML, REGISTRY_WITH_ENV_YAML


# =============================================================================
# Tests for YAML Parsing Functions
# =============================================================================

class TestYamlParsing:
    def test_read_yaml_file_success(self, tmp_dir):
        test_file = tmp_dir / "test.yml"
        test_file.write_text("key: value")
        result = read_yaml_file(test_file)
        assert result == "key: value"

    def test_read_yaml_file_not_found(self, tmp_dir):
        non_existent = tmp_dir / "nonexistent.yml"
        with pytest.raises(SystemExit):
            read_yaml_file(non_existent)

    def test_parse_yaml_file_valid(self):
        yaml_str = "key: value\nlist:\n  - a\n  - b"
        result = parse_yaml_file(yaml_str)
        assert result["key"] == "value"
        assert result["list"] == ["a", "b"]

    def test_parse_yaml_file_invalid(self):
        with pytest.raises(SystemExit):
            parse_yaml_file("invalid: [yaml")

    def test_parse_yaml_file_empty(self):
        result = parse_yaml_file("")
        assert result is None

    def test_get_registry_from_yaml_file(self, registry_file):
        result = get_registry_from_yaml_file(registry_file)
        assert isinstance(result, RegistryRoot)
        assert result.specification.version == "2.0"
        assert len(result.registry.devices) == 1
        assert result.registry.devices[0].slug == "test-device"

    def test_get_registry_from_yaml_file_with_env(self, registry_with_env_file):
        result = get_registry_from_yaml_file(registry_with_env_file)
        assert len(result.environment) == 3
        env_names = [e.name for e in result.environment]
        assert "DL_DIR" in env_names
        assert "SSTATE_DIR" in env_names

    def test_get_registry_containers_converted(self, registry_file):
        result = get_registry_from_yaml_file(registry_file)
        assert "ubuntu-22.04" in result.containers
        container = result.containers["ubuntu-22.04"]
        assert isinstance(container, Docker)
        assert container.image == "test/ubuntu-22.04:latest"

    def test_get_registry_presets(self, registry_file):
        result = get_registry_from_yaml_file(registry_file)
        assert len(result.registry.bsp) == 1
        assert result.registry.bsp[0].name == "test-bsp"
        assert result.registry.bsp[0].description == "Test BSP"

    def test_get_registry_device_build_config(self, registry_file):
        result = get_registry_from_yaml_file(registry_file)
        device = result.registry.devices[0]
        assert "test.yaml" in device.includes
        # Build path and container are now in the BSP preset
        preset = result.registry.bsp[0]
        assert preset.build is not None
        assert preset.build.path == "build/test"
        assert preset.build.container == "ubuntu-22.04"

    def test_get_registry_missing_file(self, tmp_dir):
        with pytest.raises(SystemExit):
            get_registry_from_yaml_file(tmp_dir / "missing.yml")

    def test_get_registry_invalid_yaml(self, tmp_dir):
        invalid_file = tmp_dir / "invalid.yml"
        invalid_file.write_text(INVALID_YAML)
        with pytest.raises(SystemExit):
            get_registry_from_yaml_file(invalid_file)

    def test_get_registry_unsupported_version_exits(self, tmp_dir):
        """Registry files with unsupported version should exit immediately."""
        v1_yaml = """
specification:
  version: "1.0"
registry:
  bsp: []
"""
        v1_file = tmp_dir / "v1-registry.yaml"
        v1_file.write_text(v1_yaml)
        with pytest.raises(SystemExit):
            get_registry_from_yaml_file(v1_file)

    def test_get_registry_no_version_exits(self, tmp_dir):
        """Registry files without a version should exit immediately."""
        no_ver_yaml = """
registry:
  devices: []
"""
        no_ver_file = tmp_dir / "no-ver.yaml"
        no_ver_file.write_text(no_ver_yaml)
        with pytest.raises(SystemExit):
            get_registry_from_yaml_file(no_ver_file)


# =============================================================================
# Tests for convert_containers_list_to_dict
# =============================================================================

class TestConvertContainersListToDict:
    def test_basic_conversion(self):
        containers_list = [
            {"ubuntu-22.04": {"image": "ubuntu:22.04", "file": "Dockerfile", "args": []}},
        ]
        result = convert_containers_list_to_dict(containers_list)
        assert "ubuntu-22.04" in result
        assert isinstance(result["ubuntu-22.04"], Docker)
        assert result["ubuntu-22.04"].image == "ubuntu:22.04"

    def test_multiple_containers(self):
        containers_list = [
            {"ubuntu-20.04": {"image": "ubuntu:20.04", "file": "Dockerfile1", "args": []}},
            {"ubuntu-22.04": {"image": "ubuntu:22.04", "file": "Dockerfile2", "args": []}},
        ]
        result = convert_containers_list_to_dict(containers_list)
        assert len(result) == 2
        assert "ubuntu-20.04" in result
        assert "ubuntu-22.04" in result

    def test_container_with_args(self):
        containers_list = [
            {
                "my-container": {
                    "image": "my-image:latest",
                    "file": "Dockerfile",
                    "args": [
                        {"name": "DISTRO", "value": "ubuntu:22.04"},
                        {"name": "VERSION", "value": "1.0"},
                    ]
                }
            }
        ]
        result = convert_containers_list_to_dict(containers_list)
        container = result["my-container"]
        assert len(container.args) == 2
        assert container.args[0].name == "DISTRO"
        assert container.args[0].value == "ubuntu:22.04"

    def test_container_without_file(self):
        containers_list = [
            {"my-container": {"image": "my-image:latest", "args": []}},
        ]
        result = convert_containers_list_to_dict(containers_list)
        assert result["my-container"].file is None

    def test_invalid_container_config_skipped(self):
        containers_list = [
            {"valid-container": {"image": "valid:latest", "file": "Dockerfile", "args": []}},
            {"invalid-container": "not-a-dict"},
        ]
        result = convert_containers_list_to_dict(containers_list)
        assert "valid-container" in result
        assert "invalid-container" not in result

    def test_empty_list(self):
        result = convert_containers_list_to_dict([])
        assert result == {}

    def test_container_privileged_default_false(self):
        containers_list = [
            {"my-container": {"image": "my-image:latest", "file": "Dockerfile", "args": []}},
        ]
        result = convert_containers_list_to_dict(containers_list)
        assert result["my-container"].privileged is False

    def test_container_privileged_true(self):
        containers_list = [
            {"isar-container": {"image": "isar:latest", "file": "Dockerfile", "args": [], "privileged": True}},
        ]
        result = convert_containers_list_to_dict(containers_list)
        assert result["isar-container"].privileged is True

    def test_container_runtime_args_default_none(self):
        containers_list = [
            {"my-container": {"image": "my-image:latest", "file": "Dockerfile", "args": []}},
        ]
        result = convert_containers_list_to_dict(containers_list)
        assert result["my-container"].runtime_args is None

    def test_container_runtime_args_set(self):
        containers_list = [
            {
                "net-container": {
                    "image": "net:latest",
                    "file": "Dockerfile",
                    "args": [],
                    "runtime_args": "-p 2222:2222 --cap-add=NET_ADMIN",
                }
            },
        ]
        result = convert_containers_list_to_dict(containers_list)
        assert result["net-container"].runtime_args == "-p 2222:2222 --cap-add=NET_ADMIN"

    def test_get_registry_distro_section(self, registry_with_distro_file):
        result = get_registry_from_yaml_file(registry_with_distro_file)
        assert len(result.registry.distro) == 2
        distro_slugs = [d.slug for d in result.registry.distro]
        assert "poky" in distro_slugs
        assert "isar" in distro_slugs

    def test_get_registry_release_distro_field(self, registry_with_distro_file):
        result = get_registry_from_yaml_file(registry_with_distro_file)
        release = result.registry.releases[0]
        assert release.slug == "scarthgap"
        assert release.distro == "poky"

    def test_get_registry_distro_vendor(self, registry_with_distro_file):
        result = get_registry_from_yaml_file(registry_with_distro_file)
        poky = next(d for d in result.registry.distro if d.slug == "poky")
        assert poky.vendor == "yocto"
        assert "kas/poky/distro/poky.yaml" in poky.includes


# =============================================================================
# Tests for build_docker verbose/quiet behaviour
# =============================================================================

class TestBuildDocker:
    """Tests for the build_docker helper, focusing on verbose vs quiet output."""

    def _make_dockerfile_dir(self, tmp_path):
        """Create a minimal Dockerfile in tmp_path and return the dir path as str."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM scratch\n")
        return str(tmp_path)

    @patch("bsp.utils.subprocess.run")
    def test_quiet_mode_shows_status_message(self, mock_run, tmp_path, capsys):
        """In quiet mode (verbose=False) a 'Preparing docker environment' line is printed."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        dockerfile_dir = self._make_dockerfile_dir(tmp_path)

        build_docker(dockerfile_dir, "Dockerfile", "test-image:latest", verbose=False)

        captured = capsys.readouterr()
        assert "Preparing docker environment" in captured.out
        assert "test-image:latest" in captured.out

    @patch("bsp.utils.subprocess.run")
    def test_quiet_mode_captures_output(self, mock_run, tmp_path, capsys):
        """In quiet mode subprocess.run is called with capture_output=True."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        dockerfile_dir = self._make_dockerfile_dir(tmp_path)

        build_docker(dockerfile_dir, "Dockerfile", "test-image:latest", verbose=False)

        _, kwargs = mock_run.call_args
        assert kwargs.get("capture_output") is True

    @patch("bsp.utils.subprocess.run")
    def test_verbose_mode_no_capture(self, mock_run, tmp_path, capsys):
        """In verbose mode subprocess.run is called WITHOUT capture_output."""
        mock_run.return_value = MagicMock(returncode=0)
        dockerfile_dir = self._make_dockerfile_dir(tmp_path)

        build_docker(dockerfile_dir, "Dockerfile", "test-image:latest", verbose=True)

        _, kwargs = mock_run.call_args
        assert not kwargs.get("capture_output", False)

    @patch("bsp.utils.subprocess.run")
    def test_verbose_mode_no_status_message(self, mock_run, tmp_path, capsys):
        """In verbose mode the quiet status line is NOT printed."""
        mock_run.return_value = MagicMock(returncode=0)
        dockerfile_dir = self._make_dockerfile_dir(tmp_path)

        build_docker(dockerfile_dir, "Dockerfile", "test-image:latest", verbose=True)

        captured = capsys.readouterr()
        assert "Preparing docker environment" not in captured.out

    @patch("bsp.utils.subprocess.run")
    def test_default_is_quiet(self, mock_run, tmp_path, capsys):
        """Default call (no verbose arg) behaves the same as verbose=False."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        dockerfile_dir = self._make_dockerfile_dir(tmp_path)

        build_docker(dockerfile_dir, "Dockerfile", "test-image:latest")

        captured = capsys.readouterr()
        assert "Preparing docker environment" in captured.out

    @patch("bsp.utils.subprocess.run")
    def test_build_failure_exits(self, mock_run, tmp_path):
        """A non-zero return code from docker build causes SystemExit."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=["docker", "build"], stderr="some error"
        )
        dockerfile_dir = self._make_dockerfile_dir(tmp_path)

        with pytest.raises(SystemExit):
            build_docker(dockerfile_dir, "Dockerfile", "test-image:latest", verbose=False)

    def test_missing_dockerfile_dir_exits(self, tmp_path):
        """A missing Dockerfile directory causes SystemExit before docker is called."""
        with pytest.raises(SystemExit):
            build_docker(str(tmp_path / "nonexistent"), "Dockerfile", "test:latest")

    def test_missing_dockerfile_exits(self, tmp_path):
        """A missing Dockerfile inside an existing directory causes SystemExit."""
        with pytest.raises(SystemExit):
            build_docker(str(tmp_path), "Dockerfile", "test:latest")
