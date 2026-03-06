"""
Tests for BspManager registry operations (v2.0 schema).
"""

import pytest
from unittest.mock import patch, MagicMock

from bsp import BspManager, BspPreset, Docker, V2Resolver
from .conftest import EMPTY_REGISTRY_YAML, REGISTRY_WITH_FEATURES_YAML


class TestBspManagerInit:
    def test_init(self, tmp_dir):
        manager = BspManager(config_path=str(tmp_dir / "bsp-registry.yml"))
        assert manager.model is None
        assert manager.env_manager is None
        assert manager.containers == {}
        assert manager.resolver is None

    def test_load_configuration_success(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.load_configuration()
        assert manager.model is not None
        assert len(manager.model.registry.devices) == 1

    def test_load_configuration_missing_file(self, tmp_dir):
        manager = BspManager(config_path=str(tmp_dir / "missing.yml"))
        with pytest.raises(SystemExit):
            manager.load_configuration()

    def test_load_configuration_containers_loaded(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.load_configuration()
        assert "ubuntu-22.04" in manager.containers

    def test_load_configuration_env_manager_initialized(self, registry_with_env_file):
        manager = BspManager(config_path=str(registry_with_env_file))
        manager.load_configuration()
        assert manager.env_manager is not None

    def test_initialize_creates_resolver(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        assert manager.resolver is not None
        assert isinstance(manager.resolver, V2Resolver)


class TestBspManagerList:
    def test_list_bsp_outputs_preset_name(self, registry_file, capsys):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        manager.list_bsp()
        captured = capsys.readouterr()
        assert "test-bsp" in captured.out

    def test_list_bsp_outputs_preset_description(self, registry_file, capsys):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        manager.list_bsp()
        captured = capsys.readouterr()
        assert "Test BSP" in captured.out

    def test_list_bsp_empty_registry_does_not_exit(self, tmp_dir):
        empty_file = tmp_dir / "empty.yml"
        empty_file.write_text(EMPTY_REGISTRY_YAML)
        manager = BspManager(config_path=str(empty_file))
        manager.initialize()
        # Should NOT raise; just logs info
        manager.list_bsp()

    def test_list_devices(self, registry_file, capsys):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        manager.list_devices()
        captured = capsys.readouterr()
        assert "test-device" in captured.out
        assert "test-vendor" in captured.out

    def test_list_releases(self, registry_file, capsys):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        manager.list_releases()
        captured = capsys.readouterr()
        assert "test-release" in captured.out

    def test_list_features_empty(self, registry_file, capsys):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        manager.list_features()  # Should not raise

    def test_list_features_with_features(self, registry_with_features_file, capsys):
        manager = BspManager(config_path=str(registry_with_features_file))
        manager.initialize()
        manager.list_features()
        captured = capsys.readouterr()
        assert "ota" in captured.out
        assert "secure-boot" in captured.out

    def test_list_containers_outputs_names(self, registry_file, capsys):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        manager.list_containers()
        captured = capsys.readouterr()
        assert "ubuntu-22.04" in captured.out

    def test_list_containers_empty(self, tmp_dir):
        no_containers_yaml = """
specification:
  version: "2.0"
registry:
  devices:
    - slug: test-device
      description: "Test Device"
      vendor: vendor
      soc_vendor: soc
      build:
        container: "no-container"
        path: build/test
  releases: []
  features: []
  bsp: []
"""
        registry_file = tmp_dir / "bsp-registry.yml"
        registry_file.write_text(no_containers_yaml)
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        # Should not raise, just log info
        manager.list_containers()

    def test_multiple_presets(self, registry_with_env_file):
        manager = BspManager(config_path=str(registry_with_env_file))
        manager.initialize()
        assert len(manager.model.registry.bsp) == 2
        names = [b.name for b in manager.model.registry.bsp]
        assert "qemu-arm64" in names
        assert "qemu-x86-64" in names

    def test_multiple_devices(self, registry_with_env_file):
        manager = BspManager(config_path=str(registry_with_env_file))
        manager.initialize()
        assert len(manager.model.registry.devices) == 2
        slugs = [d.slug for d in manager.model.registry.devices]
        assert "qemu-arm64" in slugs
        assert "qemu-x86-64" in slugs


class TestBspManagerPresetLookup:
    def test_get_bsp_by_name_found(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        preset = manager.get_bsp_by_name("test-bsp")
        assert isinstance(preset, BspPreset)
        assert preset.name == "test-bsp"
        assert preset.device == "test-device"
        assert preset.release == "test-release"

    def test_get_bsp_by_name_not_found(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        with pytest.raises(SystemExit):
            manager.get_bsp_by_name("nonexistent-bsp")


class TestBspManagerResolver:
    def test_resolver_resolves_preset(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        resolved, preset = manager.resolver.resolve_preset("test-bsp")
        assert resolved.device.slug == "test-device"
        assert resolved.release.slug == "test-release"
        assert resolved.container is not None
        assert resolved.container.image == "test/ubuntu-22.04:latest"

    def test_resolver_get_device(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        device = manager.resolver.get_device("test-device")
        assert device.slug == "test-device"
        assert device.vendor == "test-vendor"

    def test_resolver_get_device_not_found(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        with pytest.raises(SystemExit):
            manager.resolver.get_device("nonexistent")

    def test_resolver_get_release(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        release = manager.resolver.get_release("test-release")
        assert release.slug == "test-release"

    def test_resolver_get_feature(self, registry_with_features_file):
        manager = BspManager(config_path=str(registry_with_features_file))
        manager.initialize()
        feature = manager.resolver.get_feature("ota")
        assert feature.slug == "ota"

    def test_resolver_build_path_from_device(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        resolved, _ = manager.resolver.resolve_preset("test-bsp")
        assert resolved.build_path == "build/test"

    def test_resolver_kas_files_order(self, registry_file):
        """Release includes come before device includes."""
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        resolved, _ = manager.resolver.resolve_preset("test-bsp")
        # release includes: ["test-base.yml"]
        # device includes: ["test.yml"]
        assert "test-base.yml" in resolved.kas_files
        assert "test.yml" in resolved.kas_files
        assert resolved.kas_files.index("test-base.yml") < resolved.kas_files.index("test.yml")

    def test_resolver_feature_compatibility_ok(self, registry_with_features_file):
        manager = BspManager(config_path=str(registry_with_features_file))
        manager.initialize()
        # imx8-board has soc_vendor=nxp, secure-boot requires nxp -> compatible
        resolved = manager.resolver.resolve("imx8-board", "scarthgap", ["secure-boot"])
        assert len(resolved.features) == 1

    def test_resolver_feature_compatibility_fails(self, registry_with_features_file):
        """secure-boot requires soc_vendor=nxp; qemu-arm64 has soc_vendor=arm -> incompatible."""
        manager = BspManager(config_path=str(registry_with_features_file))
        manager.initialize()
        with pytest.raises(SystemExit):
            manager.resolver.resolve("qemu-arm64", "scarthgap", ["secure-boot"])

    def test_resolver_local_conf_from_feature(self, registry_with_features_file):
        manager = BspManager(config_path=str(registry_with_features_file))
        manager.initialize()
        resolved = manager.resolver.resolve("imx8-board", "scarthgap", ["ota"])
        assert any("swupdate" in lc for lc in resolved.local_conf)

    def test_resolver_env_from_feature(self, registry_with_features_file):
        manager = BspManager(config_path=str(registry_with_features_file))
        manager.initialize()
        resolved = manager.resolver.resolve("imx8-board", "scarthgap", ["secure-boot"])
        env_names = [e.name for e in resolved.env]
        assert "SIGNING_KEY" in env_names


class TestBspManagerBuildByComponents:
    def test_build_by_components_calls_kas(self, registry_with_features_file):
        manager = BspManager(config_path=str(registry_with_features_file))
        manager.initialize()
        with patch("bsp.bsp_manager.build_docker"), \
             patch("bsp.kas_manager.KasManager.build_project") as mock_build, \
             patch("bsp.kas_manager.KasManager.dump_config", return_value=None), \
             patch("bsp.kas_manager.KasManager.validate_kas_files", return_value=True), \
             patch("bsp.kas_manager.KasManager.check_kas_available", return_value=True):
            manager.build_by_components("imx8-board", "scarthgap")
        mock_build.assert_called_once()

    def test_build_bsp_preset_calls_kas(self, registry_with_features_file):
        manager = BspManager(config_path=str(registry_with_features_file))
        manager.initialize()
        with patch("bsp.bsp_manager.build_docker"), \
             patch("bsp.kas_manager.KasManager.build_project") as mock_build, \
             patch("bsp.kas_manager.KasManager.dump_config", return_value=None), \
             patch("bsp.kas_manager.KasManager.validate_kas_files", return_value=True), \
             patch("bsp.kas_manager.KasManager.check_kas_available", return_value=True):
            manager.build_bsp("imx8-scarthgap-ota")
        mock_build.assert_called_once()


class TestBspManagerMisc:
    def test_prepare_build_directory(self, tmp_dir, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        build_dir = tmp_dir / "test-build"
        manager.prepare_build_directory(str(build_dir))
        assert build_dir.is_dir()

    def test_cleanup_does_not_raise(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        manager.cleanup()  # Should not raise

    def test_initialize(self, registry_with_env_file):
        manager = BspManager(config_path=str(registry_with_env_file))
        manager.initialize()
        assert len(manager.model.registry.bsp) == 2
        names = [b.name for b in manager.model.registry.bsp]
        assert "qemu-arm64" in names
        assert "qemu-x86-64" in names

    def test_bsp_has_expected_fields(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        bsp_obj = manager.get_bsp_by_name("test-bsp")
        assert bsp_obj.name == "test-bsp"
        assert bsp_obj.description == "Test BSP"
        assert bsp_obj.device == "test-device"
        assert bsp_obj.release == "test-release"

    def test_build_bsp_uses_registry_dir_for_dockerfile(self, tmp_dir):
        """build_docker must be called with the registry file's directory, not CWD."""
        from unittest.mock import patch
        from bsp.kas_manager import KasManager

        # Create a Dockerfile next to the registry file in a subdirectory
        registry_dir = tmp_dir / "remote_cache"
        registry_dir.mkdir()
        dockerfile = registry_dir / "Dockerfile.ubuntu"
        dockerfile.write_text("FROM ubuntu:22.04\n")
        kas_file = registry_dir / "test.yml"
        kas_file.write_text("header:\n  version: 14\nmachine: qemuarm64\n")

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
          - {kas_file}
  releases:
    - slug: test-release
      description: "Test Release"
      includes: []
  features: []
  bsp:
    - name: test-bsp
      description: "Test BSP"
      device: test-device
      release: test-release
      features: []
"""
        registry_file = registry_dir / "bsp-registry.yml"
        registry_file.write_text(registry_content)

        manager = BspManager(config_path=str(registry_file))
        manager.initialize()

        with patch("bsp.bsp_manager.build_docker") as mock_build_docker:
            with patch.object(KasManager, "build_project"):
                with patch.object(manager, "prepare_build_directory"):
                    with patch.object(KasManager, "dump_config", return_value=None):
                        manager.build_bsp("test-bsp")

        # The first argument to build_docker must be the registry file's parent dir
        assert mock_build_docker.called
        called_dockerfile_dir = mock_build_docker.call_args[0][0]
        assert called_dockerfile_dir == str(registry_dir)

    def test_shell_into_bsp_uses_registry_dir_for_dockerfile(self, tmp_dir):
        """shell_into_bsp must resolve Dockerfile relative to the registry file, not CWD."""
        from unittest.mock import patch
        from bsp.kas_manager import KasManager

        registry_dir = tmp_dir / "remote_cache"
        registry_dir.mkdir()
        dockerfile = registry_dir / "Dockerfile.ubuntu"
        dockerfile.write_text("FROM ubuntu:22.04\n")
        kas_file = registry_dir / "test.yml"
        kas_file.write_text("header:\n  version: 14\nmachine: qemuarm64\n")

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
          - {kas_file}
  releases:
    - slug: test-release
      description: "Test Release"
      includes: []
  features: []
  bsp:
    - name: test-bsp
      description: "Test BSP"
      device: test-device
      release: test-release
      features: []
"""
        registry_file = registry_dir / "bsp-registry.yml"
        registry_file.write_text(registry_content)

        manager = BspManager(config_path=str(registry_file))
        manager.initialize()

        with patch("bsp.bsp_manager.build_docker") as mock_build_docker:
            with patch.object(KasManager, "shell_session"):
                with patch.object(manager, "prepare_build_directory"):
                    with patch.object(KasManager, "dump_config", return_value=None):
                        manager.shell_into_bsp("test-bsp")

        assert mock_build_docker.called
        called_dockerfile_dir = mock_build_docker.call_args[0][0]
        assert called_dockerfile_dir == str(registry_dir)

    def test_kas_manager_gets_registry_dir_as_search_path(self, tmp_dir):
        """KasManager must include the registry file's directory in its search paths."""
        registry_dir = tmp_dir / "remote_cache"
        registry_dir.mkdir()
        kas_file = registry_dir / "test.yml"
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
  bsp:
    - name: test-bsp
      description: "Test BSP"
      device: test-device
      release: test-release
      features: []
"""
        registry_file = registry_dir / "bsp-registry.yml"
        registry_file.write_text(registry_content)

        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        resolved = manager.resolver.resolve("test-device", "test-release")

        kas_mgr = manager._get_kas_manager_for_resolved(resolved, use_container=False)
        assert str(registry_dir) in kas_mgr.search_paths
        manager._cleanup_temp_kas_file()


# =============================================================================
# Tests for named environments in resolver
# =============================================================================

class TestNamedEnvironmentsInResolver:
    def test_default_env_container_used_when_device_has_no_container(
        self, registry_with_named_env_file
    ):
        """When device has no build.container, the default named env's container is used."""
        manager = BspManager(config_path=str(registry_with_named_env_file))
        manager.initialize()
        resolved = manager.resolver.resolve("qemu-arm64", "scarthgap")
        assert resolved.container is not None
        assert resolved.container.image == "test/debian:latest"

    def test_release_specific_env_container_used(
        self, registry_with_named_env_file
    ):
        """When release names 'isar-env', that environment's container is used."""
        manager = BspManager(config_path=str(registry_with_named_env_file))
        manager.initialize()
        resolved = manager.resolver.resolve("isar-board", "isar-v0.11")
        assert resolved.container is not None
        assert resolved.container.image == "test/debian-isar:latest"

    def test_named_env_variables_in_resolved_env(
        self, registry_with_named_env_file
    ):
        """Named environment variables appear in ResolvedConfig.env."""
        manager = BspManager(config_path=str(registry_with_named_env_file))
        manager.initialize()
        resolved = manager.resolver.resolve("qemu-arm64", "scarthgap")
        env_names = [e.name for e in resolved.env]
        assert "DL_DIR" in env_names
        assert "SSTATE_DIR" in env_names

    def test_isar_env_variables_in_resolved_env(
        self, registry_with_named_env_file
    ):
        """isar-env variables appear for the isar-v0.11 release."""
        manager = BspManager(config_path=str(registry_with_named_env_file))
        manager.initialize()
        resolved = manager.resolver.resolve("isar-board", "isar-v0.11")
        dl_var = next((e for e in resolved.env if e.name == "DL_DIR"), None)
        assert dl_var is not None
        assert dl_var.value == "/tmp/isar-downloads"

    def test_device_container_overrides_named_env_container(
        self, tmp_dir
    ):
        """If device explicitly sets build.container, it takes priority over env container."""
        import textwrap
        yaml_content = textwrap.dedent("""
            specification:
              version: "2.0"
            environments:
              default:
                container: "env-container"
                variables: []
            containers:
              device-container:
                image: "device-image:latest"
                file: null
                args: []
              env-container:
                image: "env-image:latest"
                file: null
                args: []
            registry:
              devices:
                - slug: my-device
                  description: "My Device"
                  vendor: acme
                  soc_vendor: arm
                  build:
                    container: "device-container"
                    path: build/my-device
                    includes: []
              releases:
                - slug: my-release
                  description: "My Release"
                  includes: []
              features: []
              bsp: []
        """)
        registry_path = tmp_dir / "bsp-registry.yml"
        registry_path.write_text(yaml_content)
        manager = BspManager(config_path=str(registry_path))
        manager.initialize()
        resolved = manager.resolver.resolve("my-device", "my-release")
        # Device's explicit container should win
        assert resolved.container.image == "device-image:latest"

    def test_unknown_named_env_raises(self, tmp_dir):
        """A release referencing a non-existent named environment should exit."""
        import textwrap
        yaml_content = textwrap.dedent("""
            specification:
              version: "2.0"
            containers:
              some-container:
                image: "some-image:latest"
                file: null
                args: []
            registry:
              devices:
                - slug: my-device
                  description: "My Device"
                  vendor: acme
                  soc_vendor: arm
                  build:
                    container: "some-container"
                    path: build/my-device
                    includes: []
              releases:
                - slug: bad-env-release
                  description: "Bad"
                  environment: "nonexistent-env"
                  includes: []
              features: []
              bsp: []
        """)
        registry_path = tmp_dir / "bsp-registry.yml"
        registry_path.write_text(yaml_content)
        manager = BspManager(config_path=str(registry_path))
        manager.initialize()
        with pytest.raises(SystemExit):
            manager.resolver.resolve("my-device", "bad-env-release")


# =============================================================================
# Tests for copy field support
# =============================================================================

class TestCopyFiles:
    def test_copy_field_parsed(self, registry_with_copy_file):
        """DeviceBuild.copy is parsed from YAML."""
        manager = BspManager(config_path=str(registry_with_copy_file))
        manager.initialize()
        device = manager.resolver.get_device("isar-qemu")
        assert len(device.build.copy) == 1
        assert device.build.copy[0] == {"scripts/isar-runqemu.sh": "build/isar-qemu/"}

    def test_copy_propagated_to_resolved(self, registry_with_copy_file):
        """ResolvedConfig.copy contains the device build copy entries."""
        manager = BspManager(config_path=str(registry_with_copy_file))
        manager.initialize()
        resolved = manager.resolver.resolve("isar-qemu", "isar-v0.11")
        assert resolved.copy == [{"scripts/isar-runqemu.sh": "build/isar-qemu/"}]

    def test_copy_empty_when_not_specified(self, registry_file):
        """ResolvedConfig.copy is empty when no copy entries are defined."""
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        resolved = manager.resolver.resolve("test-device", "test-release")
        assert resolved.copy == []

    def test_copy_files_creates_file_in_destination(self, registry_with_copy_file, tmp_dir):
        """_copy_files copies the source file to the destination directory."""
        manager = BspManager(config_path=str(registry_with_copy_file))
        manager.initialize()

        # Create the source file relative to registry dir
        scripts_dir = registry_with_copy_file.parent / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        src_file = scripts_dir / "isar-runqemu.sh"
        src_file.write_text("#!/bin/sh\necho hello\n")

        # Ensure destination directory exists
        dst_dir = registry_with_copy_file.parent / "build" / "isar-qemu"
        dst_dir.mkdir(parents=True, exist_ok=True)

        resolved = manager.resolver.resolve("isar-qemu", "isar-v0.11")
        manager._copy_files(resolved)

        dst_file = dst_dir / "isar-runqemu.sh"
        assert dst_file.exists()
        assert dst_file.read_text() == "#!/bin/sh\necho hello\n"

    def test_copy_files_missing_source_exits(self, registry_with_copy_file):
        """_copy_files exits with an error when the source file does not exist."""
        manager = BspManager(config_path=str(registry_with_copy_file))
        manager.initialize()
        resolved = manager.resolver.resolve("isar-qemu", "isar-v0.11")
        with pytest.raises(SystemExit):
            manager._copy_files(resolved)

    def test_copy_files_noop_when_empty(self, registry_file):
        """_copy_files does nothing when resolved.copy is empty."""
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        resolved = manager.resolver.resolve("test-device", "test-release")
        # Should not raise
        manager._copy_files(resolved)


# =============================================================================
# Tests for runtime_args support in KasManager creation
# =============================================================================

class TestRuntimeArgs:
    def test_runtime_args_parsed_from_container(self, registry_with_runtime_args_file):
        """Container definition with runtime_args is parsed correctly."""
        manager = BspManager(config_path=str(registry_with_runtime_args_file))
        manager.initialize()
        container = manager.containers["isar-qemu-container"]
        assert container.runtime_args == "-p 2222:2222 --device=/dev/net/tun --cap-add=NET_ADMIN"

    def test_runtime_args_propagated_to_kas_manager(self, registry_with_runtime_args_file):
        """runtime_args from container is forwarded to KasManager as KAS_CONTAINER_ARGS."""
        manager = BspManager(config_path=str(registry_with_runtime_args_file))
        manager.initialize()
        resolved = manager.resolver.resolve("isar-qemu", "isar-v0.11")
        kas_mgr = manager._get_kas_manager_for_resolved(resolved, use_container=True)
        env = kas_mgr._get_environment_with_container_vars()
        assert env.get("KAS_CONTAINER_ARGS") == "-p 2222:2222 --device=/dev/net/tun --cap-add=NET_ADMIN"
        manager._cleanup_temp_kas_file()

    def test_runtime_args_absent_for_container_without_them(
        self, registry_with_runtime_args_file
    ):
        """KAS_CONTAINER_ARGS is absent when container has no runtime_args."""
        manager = BspManager(config_path=str(registry_with_runtime_args_file))
        manager.initialize()
        resolved = manager.resolver.resolve("plain-device", "isar-v0.11")
        kas_mgr = manager._get_kas_manager_for_resolved(resolved, use_container=True)
        env = kas_mgr._get_environment_with_container_vars()
        assert "KAS_CONTAINER_ARGS" not in env
        manager._cleanup_temp_kas_file()
