"""
Tests for YAML parsing utilities and v2.0 registry parsing.
"""

import pytest

from bsp import (
    Docker,
    RegistryRoot,
    Device,
    Release,
    Feature,
    BspPreset,
    read_yaml_file,
    parse_yaml_file,
    get_registry_from_yaml_file,
    convert_containers_list_to_dict,
)
from .conftest import INVALID_YAML


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

    def test_get_registry_has_device(self, registry_file):
        result = get_registry_from_yaml_file(registry_file)
        assert len(result.registry.devices) == 1
        assert isinstance(result.registry.devices[0], Device)
        assert result.registry.devices[0].slug == "test-device"

    def test_get_registry_has_release(self, registry_file):
        result = get_registry_from_yaml_file(registry_file)
        assert len(result.registry.releases) == 1
        assert isinstance(result.registry.releases[0], Release)
        assert result.registry.releases[0].slug == "test-release"

    def test_get_registry_has_preset(self, registry_file):
        result = get_registry_from_yaml_file(registry_file)
        assert len(result.registry.bsp) == 1
        preset = result.registry.bsp[0]
        assert isinstance(preset, BspPreset)
        assert preset.name == "test-bsp"
        assert preset.description == "Test BSP"
        assert preset.device == "test-device"
        assert preset.release == "test-release"

    def test_get_registry_from_yaml_file_with_env(self, registry_with_env_file):
        result = get_registry_from_yaml_file(registry_with_env_file)
        assert len(result.environment) == 3
        env_names = [e.name for e in result.environment]
        assert "DL_DIR" in env_names
        assert "SSTATE_DIR" in env_names

    def test_get_registry_containers_parsed(self, registry_file):
        result = get_registry_from_yaml_file(registry_file)
        assert "ubuntu-22.04" in result.containers
        container = result.containers["ubuntu-22.04"]
        assert isinstance(container, Docker)
        assert container.image == "test/ubuntu-22.04:latest"

    def test_get_registry_device_build_config(self, registry_file):
        result = get_registry_from_yaml_file(registry_file)
        device = result.registry.devices[0]
        assert device.build.path == "build/test"
        assert device.build.includes == ["test.yml"]
        assert device.build.container == "ubuntu-22.04"

    def test_get_registry_missing_file(self, tmp_dir):
        with pytest.raises(SystemExit):
            get_registry_from_yaml_file(tmp_dir / "missing.yml")

    def test_get_registry_invalid_yaml(self, tmp_dir):
        invalid_file = tmp_dir / "invalid.yml"
        invalid_file.write_text(INVALID_YAML)
        with pytest.raises(SystemExit):
            get_registry_from_yaml_file(invalid_file)

    def test_get_registry_version_check_fails_for_v1(self, tmp_dir):
        """Fail fast if specification.version is not '2.0'."""
        v1_yaml = """
specification:
  version: "1.0"
registry:
  bsp: []
"""
        v1_file = tmp_dir / "v1.yml"
        v1_file.write_text(v1_yaml)
        with pytest.raises(SystemExit):
            get_registry_from_yaml_file(v1_file)

    def test_get_registry_version_check_fails_for_missing(self, tmp_dir):
        no_ver_yaml = """
registry:
  devices: []
  releases: []
"""
        no_ver_file = tmp_dir / "no_ver.yml"
        no_ver_file.write_text(no_ver_yaml)
        with pytest.raises(SystemExit):
            get_registry_from_yaml_file(no_ver_file)

    def test_get_registry_with_features(self, registry_with_features_file):
        result = get_registry_from_yaml_file(registry_with_features_file)
        assert len(result.registry.features) == 2
        slugs = [f.slug for f in result.registry.features]
        assert "ota" in slugs
        assert "secure-boot" in slugs

    def test_get_registry_feature_compatibility(self, registry_with_features_file):
        result = get_registry_from_yaml_file(registry_with_features_file)
        secure_boot = next(
            f for f in result.registry.features if f.slug == "secure-boot"
        )
        assert secure_boot.compatibility is not None
        assert "nxp" in secure_boot.compatibility.soc_vendor


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


# =============================================================================
# Tests for named environments in registry parsing
# =============================================================================

class TestNamedEnvironmentParsing:
    def test_registry_with_named_environments_parsed(
        self, registry_with_named_env_file
    ):
        result = get_registry_from_yaml_file(registry_with_named_env_file)
        assert result.environments is not None
        assert "default" in result.environments
        assert "isar-env" in result.environments

    def test_default_env_has_container(self, registry_with_named_env_file):
        result = get_registry_from_yaml_file(registry_with_named_env_file)
        default_env = result.environments["default"]
        assert default_env.container == "debian-bookworm"

    def test_default_env_has_variables(self, registry_with_named_env_file):
        result = get_registry_from_yaml_file(registry_with_named_env_file)
        default_env = result.environments["default"]
        var_names = [v.name for v in default_env.variables]
        assert "DL_DIR" in var_names
        assert "SSTATE_DIR" in var_names

    def test_named_env_has_different_container(self, registry_with_named_env_file):
        result = get_registry_from_yaml_file(registry_with_named_env_file)
        isar_env = result.environments["isar-env"]
        assert isar_env.container == "debian-bookworm-isar"

    def test_release_with_environment_name_parsed(self, registry_with_named_env_file):
        result = get_registry_from_yaml_file(registry_with_named_env_file)
        isar_rel = next(
            r for r in result.registry.releases if r.slug == "isar-v0.11"
        )
        assert isar_rel.environment == "isar-env"

    def test_release_without_environment_name_is_none(
        self, registry_with_named_env_file
    ):
        result = get_registry_from_yaml_file(registry_with_named_env_file)
        scarthgap = next(
            r for r in result.registry.releases if r.slug == "scarthgap"
        )
        assert scarthgap.environment is None

    def test_registry_without_environments_key(self, registry_file):
        """Registries without an environments section should still parse fine."""
        result = get_registry_from_yaml_file(registry_file)
        # Default is an empty dict (not None)
        assert result.environments == {}


# =============================================================================
# Tests for copy field in device build configuration
# =============================================================================

class TestDeviceBuildCopy:
    def test_device_with_copy_parsed(self, registry_with_copy_file):
        result = get_registry_from_yaml_file(registry_with_copy_file)
        devices = {d.slug: d for d in result.registry.devices}
        assert "isar-qemu" in devices
        device = devices["isar-qemu"]
        assert len(device.build.copy) == 1
        assert device.build.copy[0] == {"scripts/isar-runqemu.sh": "build/isar-qemu/"}

    def test_device_without_copy_defaults_to_empty_list(self, registry_file):
        result = get_registry_from_yaml_file(registry_file)
        device = result.registry.devices[0]
        assert device.build.copy == []


# =============================================================================
# Tests for runtime_args in container definitions
# =============================================================================

class TestContainerRuntimeArgs:
    def test_container_with_runtime_args_parsed(self, registry_with_runtime_args_file):
        result = get_registry_from_yaml_file(registry_with_runtime_args_file)
        container = result.containers["isar-qemu-container"]
        assert container.runtime_args == "-p 2222:2222 --device=/dev/net/tun --cap-add=NET_ADMIN"

    def test_container_without_runtime_args_is_none(self, registry_with_runtime_args_file):
        result = get_registry_from_yaml_file(registry_with_runtime_args_file)
        container = result.containers["plain-container"]
        assert container.runtime_args is None

    def test_container_without_runtime_args_defaults_none(self, registry_file):
        result = get_registry_from_yaml_file(registry_file)
        container = result.containers["ubuntu-22.04"]
        assert container.runtime_args is None
