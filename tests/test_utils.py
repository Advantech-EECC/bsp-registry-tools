"""
Tests for YAML parsing utilities and container list-to-dict conversion.
"""

import pytest

from bsp import (
    Docker,
    RegistryRoot,
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
        assert result.specification.version == "1.0"
        assert len(result.registry.bsp) == 1
        assert result.registry.bsp[0].name == "test-bsp"

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

    def test_get_registry_bsp_has_description(self, registry_file):
        result = get_registry_from_yaml_file(registry_file)
        assert result.registry.bsp[0].description == "Test BSP"

    def test_get_registry_bsp_build_config(self, registry_file):
        result = get_registry_from_yaml_file(registry_file)
        bsp_obj = result.registry.bsp[0]
        assert bsp_obj.build.path == "build/test"
        assert bsp_obj.build.configuration == ["test.yml"]

    def test_get_registry_missing_file(self, tmp_dir):
        with pytest.raises(SystemExit):
            get_registry_from_yaml_file(tmp_dir / "missing.yml")

    def test_get_registry_invalid_yaml(self, tmp_dir):
        invalid_file = tmp_dir / "invalid.yml"
        invalid_file.write_text(INVALID_YAML)
        with pytest.raises(SystemExit):
            get_registry_from_yaml_file(invalid_file)


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
