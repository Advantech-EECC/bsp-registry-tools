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
from bsp.utils import build_docker, _deep_merge_yaml_dicts
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
        assert result.environment is not None
        assert len(result.environment.variables) == 3
        env_names = [e.name for e in result.environment.variables]
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


# =============================================================================
# Tests for _deep_merge_yaml_dicts
# =============================================================================

class TestDeepMergeYamlDicts:
    def test_merge_disjoint_keys(self):
        base = {"a": 1}
        override = {"b": 2}
        result = _deep_merge_yaml_dicts(base, override)
        assert result == {"a": 1, "b": 2}

    def test_override_wins_for_scalars(self):
        base = {"a": 1}
        override = {"a": 99}
        result = _deep_merge_yaml_dicts(base, override)
        assert result["a"] == 99

    def test_lists_are_concatenated_base_first(self):
        base = {"items": [1, 2]}
        override = {"items": [3, 4]}
        result = _deep_merge_yaml_dicts(base, override)
        assert result["items"] == [1, 2, 3, 4]

    def test_nested_dicts_merged_recursively(self):
        base = {"registry": {"devices": ["dev-a"], "releases": ["rel-x"]}}
        override = {"registry": {"devices": ["dev-b"]}}
        result = _deep_merge_yaml_dicts(base, override)
        assert result["registry"]["devices"] == ["dev-a", "dev-b"]
        assert result["registry"]["releases"] == ["rel-x"]

    def test_base_not_mutated(self):
        base = {"items": [1]}
        override = {"items": [2]}
        _deep_merge_yaml_dicts(base, override)
        assert base["items"] == [1]

    def test_override_not_mutated(self):
        base = {"items": [1]}
        override = {"items": [2]}
        _deep_merge_yaml_dicts(base, override)
        assert override["items"] == [2]

    def test_empty_base(self):
        result = _deep_merge_yaml_dicts({}, {"key": "val"})
        assert result == {"key": "val"}

    def test_empty_override(self):
        result = _deep_merge_yaml_dicts({"key": "val"}, {})
        assert result == {"key": "val"}


# =============================================================================
# Tests for include directive in get_registry_from_yaml_file
# =============================================================================

# Minimal included file (no specification block required)
INCLUDED_DEVICES_YAML = """
registry:
  devices:
    - slug: extra-device
      description: "Extra Device"
      vendor: extra-vendor
      soc_vendor: extra-soc
      includes:
        - extra.yaml
  releases: []
  features: []
"""

INCLUDED_RELEASES_YAML = """
registry:
  devices: []
  releases:
    - slug: extra-release
      description: "Extra Release"
      yocto_version: "5.0"
      includes:
        - extra-base.yaml
  features: []
"""


class TestRegistryInclude:
    def test_include_merges_devices(self, tmp_dir):
        """Devices from an included file are added to the main registry."""
        included = tmp_dir / "devices.yaml"
        included.write_text(INCLUDED_DEVICES_YAML)

        main_yaml = f"""
specification:
  version: "2.0"
include:
  - devices.yaml
registry:
  devices: []
  releases: []
  features: []
"""
        main_file = tmp_dir / "registry.yaml"
        main_file.write_text(main_yaml)

        result = get_registry_from_yaml_file(main_file)
        device_slugs = [d.slug for d in result.registry.devices]
        assert "extra-device" in device_slugs

    def test_include_merges_releases(self, tmp_dir):
        """Releases from an included file are combined with main-file releases."""
        included = tmp_dir / "releases.yaml"
        included.write_text(INCLUDED_RELEASES_YAML)

        main_yaml = f"""
specification:
  version: "2.0"
include:
  - releases.yaml
registry:
  devices: []
  releases:
    - slug: main-release
      description: "Main Release"
      yocto_version: "4.0"
  features: []
"""
        main_file = tmp_dir / "registry.yaml"
        main_file.write_text(main_yaml)

        result = get_registry_from_yaml_file(main_file)
        slugs = [r.slug for r in result.registry.releases]
        assert "extra-release" in slugs
        assert "main-release" in slugs

    def test_include_order_included_before_main(self, tmp_dir):
        """Items from included files appear before items from the main file."""
        included = tmp_dir / "devices.yaml"
        included.write_text(INCLUDED_DEVICES_YAML)

        main_yaml = f"""
specification:
  version: "2.0"
include:
  - devices.yaml
registry:
  devices:
    - slug: main-device
      description: "Main Device"
      vendor: main-vendor
      soc_vendor: main-soc
  releases: []
  features: []
"""
        main_file = tmp_dir / "registry.yaml"
        main_file.write_text(main_yaml)

        result = get_registry_from_yaml_file(main_file)
        slugs = [d.slug for d in result.registry.devices]
        assert slugs.index("extra-device") < slugs.index("main-device")

    def test_include_multiple_files(self, tmp_dir):
        """Multiple includes are all processed and merged."""
        dev_file = tmp_dir / "devices.yaml"
        dev_file.write_text(INCLUDED_DEVICES_YAML)
        rel_file = tmp_dir / "releases.yaml"
        rel_file.write_text(INCLUDED_RELEASES_YAML)

        main_yaml = """
specification:
  version: "2.0"
include:
  - devices.yaml
  - releases.yaml
registry:
  devices: []
  releases: []
  features: []
"""
        main_file = tmp_dir / "registry.yaml"
        main_file.write_text(main_yaml)

        result = get_registry_from_yaml_file(main_file)
        assert any(d.slug == "extra-device" for d in result.registry.devices)
        assert any(r.slug == "extra-release" for r in result.registry.releases)

    def test_include_relative_to_including_file(self, tmp_dir):
        """Include paths are resolved relative to the file that contains them."""
        sub_dir = tmp_dir / "sub"
        sub_dir.mkdir()

        dev_file = sub_dir / "devices.yaml"
        dev_file.write_text(INCLUDED_DEVICES_YAML)

        main_yaml = """
specification:
  version: "2.0"
include:
  - sub/devices.yaml
registry:
  devices: []
  releases: []
  features: []
"""
        main_file = tmp_dir / "registry.yaml"
        main_file.write_text(main_yaml)

        result = get_registry_from_yaml_file(main_file)
        assert any(d.slug == "extra-device" for d in result.registry.devices)

    def test_include_nested(self, tmp_dir):
        """Includes can themselves contain further include directives."""
        inner_yaml = """
registry:
  devices:
    - slug: inner-device
      description: "Inner Device"
      vendor: inner-vendor
      soc_vendor: inner-soc
  releases: []
  features: []
"""
        inner_file = tmp_dir / "inner.yaml"
        inner_file.write_text(inner_yaml)

        outer_yaml = """
include:
  - inner.yaml
registry:
  devices: []
  releases: []
  features: []
"""
        outer_file = tmp_dir / "outer.yaml"
        outer_file.write_text(outer_yaml)

        main_yaml = """
specification:
  version: "2.0"
include:
  - outer.yaml
registry:
  devices: []
  releases: []
  features: []
"""
        main_file = tmp_dir / "registry.yaml"
        main_file.write_text(main_yaml)

        result = get_registry_from_yaml_file(main_file)
        assert any(d.slug == "inner-device" for d in result.registry.devices)

    def test_include_circular_detection(self, tmp_dir):
        """Circular includes are detected and cause SystemExit."""
        circular_a_yaml = """
include:
  - b.yaml
registry:
  devices: []
  releases: []
  features: []
"""
        circular_b_yaml = """
include:
  - a.yaml
registry:
  devices: []
  releases: []
  features: []
"""
        file_a = tmp_dir / "a.yaml"
        file_b = tmp_dir / "b.yaml"
        file_a.write_text(circular_a_yaml)
        file_b.write_text(circular_b_yaml)

        main_yaml = f"""
specification:
  version: "2.0"
include:
  - a.yaml
registry:
  devices: []
  releases: []
  features: []
"""
        main_file = tmp_dir / "registry.yaml"
        main_file.write_text(main_yaml)

        with pytest.raises(SystemExit):
            get_registry_from_yaml_file(main_file)

    def test_include_missing_file_exits(self, tmp_dir):
        """A missing include target causes SystemExit."""
        main_yaml = """
specification:
  version: "2.0"
include:
  - nonexistent.yaml
registry:
  devices: []
  releases: []
  features: []
"""
        main_file = tmp_dir / "registry.yaml"
        main_file.write_text(main_yaml)

        with pytest.raises(SystemExit):
            get_registry_from_yaml_file(main_file)

    def test_include_non_list_value_exits(self, tmp_dir):
        """A non-list 'include' value causes SystemExit."""
        main_yaml = """
specification:
  version: "2.0"
include: not-a-list
registry:
  devices: []
  releases: []
  features: []
"""
        main_file = tmp_dir / "registry.yaml"
        main_file.write_text(main_yaml)

        with pytest.raises(SystemExit):
            get_registry_from_yaml_file(main_file)

    def test_include_specification_ignored_in_included_file(self, tmp_dir):
        """A 'specification' block in an included file is silently ignored."""
        included_yaml = """
specification:
  version: "1.0"
registry:
  devices:
    - slug: included-device
      description: "Included Device"
      vendor: v
      soc_vendor: s
  releases: []
  features: []
"""
        included_file = tmp_dir / "partial.yaml"
        included_file.write_text(included_yaml)

        main_yaml = """
specification:
  version: "2.0"
include:
  - partial.yaml
registry:
  devices: []
  releases: []
  features: []
"""
        main_file = tmp_dir / "registry.yaml"
        main_file.write_text(main_yaml)

        # Should NOT raise even though included file has an old version
        result = get_registry_from_yaml_file(main_file)
        assert any(d.slug == "included-device" for d in result.registry.devices)

    def test_include_merges_containers(self, tmp_dir):
        """Containers defined in an included file are available in the merged registry."""
        included_yaml = """
containers:
  extra-container:
    image: "extra/image:latest"
    file: null
    args: []
registry:
  devices: []
  releases: []
  features: []
"""
        included_file = tmp_dir / "containers.yaml"
        included_file.write_text(included_yaml)

        main_yaml = """
specification:
  version: "2.0"
include:
  - containers.yaml
containers:
  main-container:
    image: "main/image:latest"
    file: null
    args: []
registry:
  devices: []
  releases: []
  features: []
"""
        main_file = tmp_dir / "registry.yaml"
        main_file.write_text(main_yaml)

        result = get_registry_from_yaml_file(main_file)
        assert "extra-container" in result.containers
        assert "main-container" in result.containers

    def test_no_include_key_still_works(self, tmp_dir):
        """Registry files without an 'include' key are parsed normally."""
        main_file = tmp_dir / "registry.yaml"
        main_file.write_text(MINIMAL_REGISTRY_YAML)

        result = get_registry_from_yaml_file(main_file)
        assert isinstance(result, RegistryRoot)
