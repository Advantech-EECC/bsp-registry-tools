"""
Tests for BspManager registry operations (v2.0 schema).
"""

import pytest
from unittest.mock import patch, MagicMock

from bsp import BspManager, BspPreset, Docker, V2Resolver
from .conftest import EMPTY_REGISTRY_YAML, REGISTRY_WITH_FEATURES_YAML, REGISTRY_WITH_FRAMEWORKS_YAML, REGISTRY_WITH_VENDOR_INCLUDES_YAML


class TestBspManagerInit:
    def test_init(self, tmp_dir):
        manager = BspManager(config_path=str(tmp_dir / "bsp-registry.yaml"))
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
        manager = BspManager(config_path=str(tmp_dir / "missing.yaml"))
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
        empty_file = tmp_dir / "empty.yaml"
        empty_file.write_text(EMPTY_REGISTRY_YAML)
        manager = BspManager(config_path=str(empty_file))
        manager.initialize()
        # Should NOT raise; just prints info
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
        registry_file = tmp_dir / "bsp-registry.yaml"
        registry_file.write_text(no_containers_yaml)
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        # Should not raise, just print info
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
        # release includes: ["test-base.yaml"]
        # device includes: ["test.yaml"]
        assert "test-base.yaml" in resolved.kas_files
        assert "test.yaml" in resolved.kas_files
        assert resolved.kas_files.index("test-base.yaml") < resolved.kas_files.index("test.yaml")

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


class TestBspManagerFrameworks:
    def test_resolver_get_framework(self, registry_with_frameworks_file):
        manager = BspManager(config_path=str(registry_with_frameworks_file))
        manager.initialize()
        fw = manager.resolver.get_framework("yocto")
        assert fw.slug == "yocto"
        assert fw.vendor == "Yocto Project"

    def test_resolver_get_framework_not_found(self, registry_with_frameworks_file):
        manager = BspManager(config_path=str(registry_with_frameworks_file))
        manager.initialize()
        with pytest.raises(SystemExit):
            manager.resolver.get_framework("nonexistent-fw")

    def test_resolver_list_frameworks(self, registry_with_frameworks_file):
        manager = BspManager(config_path=str(registry_with_frameworks_file))
        manager.initialize()
        frameworks = manager.resolver.list_frameworks()
        slugs = [f.slug for f in frameworks]
        assert "yocto" in slugs
        assert "isar" in slugs

    def test_registry_frameworks_loaded(self, registry_with_frameworks_file):
        manager = BspManager(config_path=str(registry_with_frameworks_file))
        manager.initialize()
        assert len(manager.model.registry.frameworks) == 2

    def test_distro_framework_field_loaded(self, registry_with_frameworks_file):
        manager = BspManager(config_path=str(registry_with_frameworks_file))
        manager.initialize()
        poky = manager.resolver.get_distro("poky")
        assert poky.framework == "yocto"
        isar = manager.resolver.get_distro("isar")
        assert isar.framework == "isar"

    def test_framework_includes_in_kas_files(self, registry_with_frameworks_file):
        """framework.includes must appear before distro.includes in resolved kas_files."""
        manager = BspManager(config_path=str(registry_with_frameworks_file))
        manager.initialize()
        resolved = manager.resolver.resolve("qemu-arm64", "scarthgap")
        # framework includes: kas/yocto/yocto.yaml
        # distro includes:    kas/poky/distro/poky.yaml
        assert "kas/yocto/yocto.yaml" in resolved.kas_files
        assert "kas/poky/distro/poky.yaml" in resolved.kas_files
        assert resolved.kas_files.index("kas/yocto/yocto.yaml") < resolved.kas_files.index("kas/poky/distro/poky.yaml")

    def test_framework_includes_isar_in_kas_files(self, registry_with_frameworks_file):
        """isar framework.includes must appear in kas_files for isar release."""
        manager = BspManager(config_path=str(registry_with_frameworks_file))
        manager.initialize()
        resolved = manager.resolver.resolve("qemu-arm64", "isar-v0.11")
        # Both the isar framework and isar distro include kas/isar/isar.yaml in the
        # fixture, so the file appears twice (framework first, then distro).
        assert resolved.kas_files.count("kas/isar/isar.yaml") == 2
        assert resolved.kas_files[0] == "kas/isar/isar.yaml"

    def test_feature_compatible_with_framework_ok(self, registry_with_frameworks_file):
        """yocto-only feature is compatible with scarthgap (distro=poky, framework=yocto)."""
        manager = BspManager(config_path=str(registry_with_frameworks_file))
        manager.initialize()
        resolved = manager.resolver.resolve("qemu-arm64", "scarthgap", ["yocto-only"])
        assert len(resolved.features) == 1

    def test_feature_compatible_with_framework_fails(self, registry_with_frameworks_file):
        """isar-only feature is incompatible with scarthgap (framework=yocto)."""
        manager = BspManager(config_path=str(registry_with_frameworks_file))
        manager.initialize()
        with pytest.raises(SystemExit):
            manager.resolver.resolve("qemu-arm64", "scarthgap", ["isar-only"])

    def test_feature_compatible_with_isar_ok(self, registry_with_frameworks_file):
        """isar-only feature is compatible with isar-v0.11 (distro=isar, framework=isar)."""
        manager = BspManager(config_path=str(registry_with_frameworks_file))
        manager.initialize()
        resolved = manager.resolver.resolve("qemu-arm64", "isar-v0.11", ["isar-only"])
        assert len(resolved.features) == 1

    def test_feature_compatible_with_distro_slug_ok(self, registry_with_frameworks_file):
        """poky-distro-only feature matches via distro slug 'poky'."""
        manager = BspManager(config_path=str(registry_with_frameworks_file))
        manager.initialize()
        resolved = manager.resolver.resolve("qemu-arm64", "scarthgap", ["poky-distro-only"])
        assert len(resolved.features) == 1

    def test_feature_compatible_with_distro_slug_fails(self, registry_with_frameworks_file):
        """poky-distro-only feature is incompatible with isar-v0.11 (distro=isar)."""
        manager = BspManager(config_path=str(registry_with_frameworks_file))
        manager.initialize()
        with pytest.raises(SystemExit):
            manager.resolver.resolve("qemu-arm64", "isar-v0.11", ["poky-distro-only"])

    def test_feature_no_compatible_with_works_everywhere(self, registry_with_frameworks_file):
        """Feature without compatible_with works with any framework."""
        manager = BspManager(config_path=str(registry_with_frameworks_file))
        manager.initialize()
        # Should work for both yocto and isar releases
        r1 = manager.resolver.resolve("qemu-arm64", "scarthgap", ["all-frameworks"])
        r2 = manager.resolver.resolve("qemu-arm64", "isar-v0.11", ["all-frameworks"])
        assert len(r1.features) == 1
        assert len(r2.features) == 1

    def test_list_frameworks_output(self, registry_with_frameworks_file, capsys):
        manager = BspManager(config_path=str(registry_with_frameworks_file))
        manager.initialize()
        manager.list_frameworks()
        captured = capsys.readouterr()
        assert "yocto" in captured.out
        assert "isar" in captured.out

    def test_list_features_shows_compatible_with(self, registry_with_frameworks_file, capsys):
        manager = BspManager(config_path=str(registry_with_frameworks_file))
        manager.initialize()
        manager.list_features()
        captured = capsys.readouterr()
        assert "compatible_with" in captured.out
        assert "yocto" in captured.out

    def test_list_distros_shows_framework(self, registry_with_frameworks_file, capsys):
        manager = BspManager(config_path=str(registry_with_frameworks_file))
        manager.initialize()
        manager.list_distros()
        captured = capsys.readouterr()
        assert "framework" in captured.out
        assert "yocto" in captured.out


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
        kas_file = registry_dir / "test.yaml"
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
        registry_file = registry_dir / "bsp-registry.yaml"
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
        kas_file = registry_dir / "test.yaml"
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
        registry_file = registry_dir / "bsp-registry.yaml"
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
        from bsp.kas_manager import KasManager

        registry_dir = tmp_dir / "remote_cache"
        registry_dir.mkdir()
        kas_file = registry_dir / "test.yaml"
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
        registry_file = registry_dir / "bsp-registry.yaml"
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
        registry_path = tmp_dir / "bsp-registry.yaml"
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
        registry_path = tmp_dir / "bsp-registry.yaml"
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
        """Device.copy is parsed from YAML."""
        manager = BspManager(config_path=str(registry_with_copy_file))
        manager.initialize()
        device = manager.resolver.get_device("isar-qemu")
        assert len(device.copy) == 1
        assert device.copy[0] == {"scripts/isar-runqemu.sh": "build/isar-qemu/"}

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
        resolved, _ = manager.resolver.resolve_preset("isar-qemu-v0.11")
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


class TestDistros:
    """Tests for registry.distro support."""

    def test_list_distros_output(self, registry_with_distro_file, capsys):
        manager = BspManager(config_path=str(registry_with_distro_file))
        manager.initialize()
        manager.list_distros()
        captured = capsys.readouterr()
        assert "poky" in captured.out
        assert "isar" in captured.out

    def test_list_distros_empty(self, registry_file, capsys):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        manager.list_distros()
        captured = capsys.readouterr()
        assert "No distros found" in captured.out

    def test_resolver_get_distro(self, registry_with_distro_file):
        manager = BspManager(config_path=str(registry_with_distro_file))
        manager.initialize()
        distro = manager.resolver.get_distro("poky")
        assert distro.slug == "poky"
        assert distro.vendor == "yocto"

    def test_resolver_get_distro_not_found(self, registry_with_distro_file):
        manager = BspManager(config_path=str(registry_with_distro_file))
        manager.initialize()
        import pytest
        with pytest.raises(SystemExit):
            manager.resolver.get_distro("nonexistent-distro")

    def test_resolver_list_distros(self, registry_with_distro_file):
        manager = BspManager(config_path=str(registry_with_distro_file))
        manager.initialize()
        distros = manager.resolver.list_distros()
        assert len(distros) == 2
        slugs = [d.slug for d in distros]
        assert "poky" in slugs
        assert "isar" in slugs

    def test_resolve_includes_distro_files(self, registry_with_distro_file):
        manager = BspManager(config_path=str(registry_with_distro_file))
        manager.initialize()
        resolved = manager.resolver.resolve("qemu-arm64", "scarthgap")
        # distro.includes should come before release.includes
        assert "kas/poky/distro/poky.yaml" in resolved.kas_files
        assert "kas/poky/scarthgap.yaml" in resolved.kas_files
        distro_idx = resolved.kas_files.index("kas/poky/distro/poky.yaml")
        release_idx = resolved.kas_files.index("kas/poky/scarthgap.yaml")
        assert distro_idx < release_idx


# =============================================================================
# Tests for copy field on named environments
# =============================================================================

class TestNamedEnvironmentCopy:
    def test_named_env_copy_field_parsed(self, registry_with_named_env_copy_file):
        """copy field on a named environment is parsed from YAML."""
        manager = BspManager(config_path=str(registry_with_named_env_copy_file))
        manager.initialize()
        env = manager.model.environments["isar-env"]
        assert len(env.copy) == 1
        assert env.copy[0] == {"isar/scripts/isar-runqemu.sh": "build/isar/"}

    def test_default_named_env_copy_field_parsed(self, registry_with_named_env_copy_file):
        """copy field on the default named environment is parsed from YAML."""
        manager = BspManager(config_path=str(registry_with_named_env_copy_file))
        manager.initialize()
        env = manager.model.environments["default"]
        assert len(env.copy) == 1
        assert env.copy[0] == {"scripts/env-setup.sh": "build/"}

    def test_named_env_copy_propagated_to_resolved(self, registry_with_named_env_copy_file):
        """Named environment copy entries appear in ResolvedConfig.copy."""
        manager = BspManager(config_path=str(registry_with_named_env_copy_file))
        manager.initialize()
        resolved = manager.resolver.resolve("isar-board", "isar-v0.11")
        copy_sources = [list(e.keys())[0] for e in resolved.copy]
        assert "isar/scripts/isar-runqemu.sh" in copy_sources

    def test_default_env_copy_propagated_to_resolved(self, registry_with_named_env_copy_file):
        """Default environment copy entries appear in resolved config for releases using default."""
        manager = BspManager(config_path=str(registry_with_named_env_copy_file))
        manager.initialize()
        resolved = manager.resolver.resolve("qemu-arm64", "scarthgap")
        copy_sources = [list(e.keys())[0] for e in resolved.copy]
        assert "scripts/env-setup.sh" in copy_sources

    def test_no_copy_in_named_env_gives_empty(self, registry_with_named_env_file):
        """When no copy is set on a named environment, resolved.copy is empty."""
        manager = BspManager(config_path=str(registry_with_named_env_file))
        manager.initialize()
        resolved = manager.resolver.resolve("qemu-arm64", "scarthgap")
        assert resolved.copy == []

    def test_named_env_copy_files_executed(self, registry_with_named_env_copy_file):
        """_copy_files executes copies coming from the named environment."""
        manager = BspManager(config_path=str(registry_with_named_env_copy_file))
        manager.initialize()

        base = registry_with_named_env_copy_file.parent
        # Create source files
        (base / "isar" / "scripts").mkdir(parents=True, exist_ok=True)
        src = base / "isar" / "scripts" / "isar-runqemu.sh"
        src.write_text("#!/bin/sh\n")
        (base / "build" / "isar").mkdir(parents=True, exist_ok=True)

        resolved = manager.resolver.resolve("isar-board", "isar-v0.11")
        manager._copy_files(resolved)

        assert (base / "build" / "isar" / "isar-runqemu.sh").exists()


# =============================================================================
# Tests for global (root-level) copy field
# =============================================================================

class TestGlobalCopy:
    def test_global_copy_field_parsed(self, registry_with_global_copy_file):
        """Global copy field inside environment section is parsed from YAML."""
        manager = BspManager(config_path=str(registry_with_global_copy_file))
        manager.initialize()
        assert manager.model.environment is not None
        assert len(manager.model.environment.copy) == 1
        assert manager.model.environment.copy[0] == {"global/setup.sh": "build/"}

    def test_global_copy_propagated_to_resolved(self, registry_with_global_copy_file):
        """Global copy entries appear in ResolvedConfig.copy."""
        manager = BspManager(config_path=str(registry_with_global_copy_file))
        manager.initialize()
        resolved = manager.resolver.resolve("qemu-arm64", "scarthgap")
        copy_sources = [list(e.keys())[0] for e in resolved.copy]
        assert "global/setup.sh" in copy_sources

    def test_global_copy_is_empty_by_default(self, registry_file):
        """RegistryRoot.environment is None (no global copy) when not specified."""
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        assert manager.model.environment is None

    def test_global_copy_order_before_device_copy(self, registry_with_global_copy_file):
        """Global copy entries come before device-level copy entries in resolved.copy."""
        manager = BspManager(config_path=str(registry_with_global_copy_file))
        manager.initialize()
        resolved = manager.resolver.resolve("qemu-arm64", "scarthgap")
        copy_sources = [list(e.keys())[0] for e in resolved.copy]
        assert copy_sources.index("global/setup.sh") < copy_sources.index("device/config.sh")

    def test_global_copy_files_executed(self, registry_with_global_copy_file):
        """_copy_files executes global copy entries."""
        manager = BspManager(config_path=str(registry_with_global_copy_file))
        manager.initialize()

        base = registry_with_global_copy_file.parent
        (base / "global").mkdir(parents=True, exist_ok=True)
        (base / "global" / "setup.sh").write_text("#!/bin/sh\n")
        (base / "device").mkdir(parents=True, exist_ok=True)
        (base / "device" / "config.sh").write_text("#!/bin/sh\n")
        (base / "build").mkdir(parents=True, exist_ok=True)

        resolved = manager.resolver.resolve("qemu-arm64", "scarthgap")
        manager._copy_files(resolved)

        assert (base / "build" / "setup.sh").exists()
        assert (base / "build" / "config.sh").exists()


# =============================================================================
# Regression test: shell command must also execute copy entries
# =============================================================================

class TestShellCopyFiles:
    def test_shell_executes_named_env_copy(self, registry_with_named_env_copy_file):
        """_copy_files is called during shell_into_bsp so named-env copy entries are applied."""
        from unittest.mock import patch
        from bsp.kas_manager import KasManager

        manager = BspManager(config_path=str(registry_with_named_env_copy_file))
        manager.initialize()

        base = registry_with_named_env_copy_file.parent
        (base / "isar" / "scripts").mkdir(parents=True, exist_ok=True)
        (base / "isar" / "scripts" / "isar-runqemu.sh").write_text("#!/bin/sh\n")
        (base / "build" / "isar").mkdir(parents=True, exist_ok=True)

        with patch.object(KasManager, "shell_session"):
            with patch.object(manager, "prepare_build_directory"):
                manager.shell_by_components("isar-board", "isar-v0.11")

        assert (base / "build" / "isar" / "isar-runqemu.sh").exists()


# =============================================================================
# Tests for copy destination relative to BSP build path
# =============================================================================

class TestCopyDestinationRelativeToBuildPath:
    def test_copy_dst_relative_to_preset_build_path(self, registry_with_named_env_copy_file):
        """Files are copied into {build_path}/{dst}, not {registry_dir}/{dst}.

        When a BSP preset has an explicit build path the destination in the copy
        entry must be resolved relative to that BSP-specific build directory so
        the file lands in the correct workspace (e.g. build/my-bsp/build/).
        """
        manager = BspManager(config_path=str(registry_with_named_env_copy_file))
        manager.initialize()

        base = registry_with_named_env_copy_file.parent
        # Create source file expected by isar-env copy entry
        (base / "isar" / "scripts").mkdir(parents=True, exist_ok=True)
        (base / "isar" / "scripts" / "isar-runqemu.sh").write_text("#!/bin/sh\n")

        # resolve_preset fills in the real build path (build/isar-board)
        resolved, _ = manager.resolver.resolve_preset("isar-v0.11-build")
        assert resolved.build_path == "build/isar-board"

        manager._copy_files(resolved)

        # With build_path="build/isar-board" and copy dst="build/isar/",
        # the file must land at {registry_dir}/build/isar-board/build/isar/
        expected = base / "build" / "isar-board" / "build" / "isar" / "isar-runqemu.sh"
        assert expected.exists(), (
            f"Expected file at {expected} but it was not created. "
            "File should be placed relative to the BSP build path."
        )


# =============================================================================
# Tests for multi-release BSP presets (releases field)
# =============================================================================

class TestMultiReleaseBspPreset:
    """Tests for BspPreset.releases (plural) feature."""

    def test_list_presets_expands_multi_release(self, registry_with_multi_release_bsp_file):
        """list_presets() expands a multi-release entry into one preset per release."""
        manager = BspManager(config_path=str(registry_with_multi_release_bsp_file))
        manager.initialize()
        preset_names = [p.name for p in manager.resolver.list_presets()]
        assert "qemu-arm64-scarthgap" in preset_names
        assert "qemu-arm64-styhead" in preset_names
        assert "qemu-x86-64-walnascar" in preset_names
        # The base name without a release suffix must NOT appear
        assert "qemu-arm64" not in preset_names

    def test_list_presets_count(self, registry_with_multi_release_bsp_file):
        """list_presets() returns two expanded + one single = three total presets."""
        manager = BspManager(config_path=str(registry_with_multi_release_bsp_file))
        manager.initialize()
        assert len(manager.resolver.list_presets()) == 3

    def test_expanded_preset_has_correct_release(self, registry_with_multi_release_bsp_file):
        """Each expanded preset carries its own release slug."""
        manager = BspManager(config_path=str(registry_with_multi_release_bsp_file))
        manager.initialize()
        presets = {p.name: p for p in manager.resolver.list_presets()}
        assert presets["qemu-arm64-scarthgap"].release == "scarthgap"
        assert presets["qemu-arm64-styhead"].release == "styhead"

    def test_expanded_preset_inherits_device(self, registry_with_multi_release_bsp_file):
        """Expanded presets inherit the device slug from the parent entry."""
        manager = BspManager(config_path=str(registry_with_multi_release_bsp_file))
        manager.initialize()
        presets = {p.name: p for p in manager.resolver.list_presets()}
        assert presets["qemu-arm64-scarthgap"].device == "qemu-arm64"
        assert presets["qemu-arm64-styhead"].device == "qemu-arm64"

    def test_expanded_preset_path_is_auto_composed(self, registry_with_multi_release_bsp_file):
        """Expanded presets ignore the explicit build.path and auto-compose instead."""
        manager = BspManager(config_path=str(registry_with_multi_release_bsp_file))
        manager.initialize()
        resolved, _ = manager.resolver.resolve_preset("qemu-arm64-scarthgap")
        # Auto-composed path: build/{device}-{release} (no distro prefix here)
        assert resolved.build_path == "build/qemu-arm64-scarthgap"

    def test_expanded_preset_container_is_preserved(self, registry_with_multi_release_bsp_file):
        """Expanded presets preserve the container override from build.container."""
        manager = BspManager(config_path=str(registry_with_multi_release_bsp_file))
        manager.initialize()
        resolved, _ = manager.resolver.resolve_preset("qemu-arm64-scarthgap")
        assert resolved.container is not None
        assert resolved.container.image == "test/debian:bookworm"

    def test_resolve_preset_expanded_name(self, registry_with_multi_release_bsp_file):
        """resolve_preset() resolves an expanded preset by its full name."""
        manager = BspManager(config_path=str(registry_with_multi_release_bsp_file))
        manager.initialize()
        resolved, preset = manager.resolver.resolve_preset("qemu-arm64-styhead")
        assert preset.name == "qemu-arm64-styhead"
        assert resolved.release.slug == "styhead"
        assert resolved.device.slug == "qemu-arm64"

    def test_resolve_preset_unknown_expanded_name_exits(self, registry_with_multi_release_bsp_file):
        """resolve_preset() exits when the base name (not expanded) is looked up."""
        manager = BspManager(config_path=str(registry_with_multi_release_bsp_file))
        manager.initialize()
        with pytest.raises(SystemExit):
            manager.resolver.resolve_preset("qemu-arm64")

    def test_list_bsp_shows_expanded_names(self, registry_with_multi_release_bsp_file, capsys):
        """list_bsp() prints the expanded preset names."""
        manager = BspManager(config_path=str(registry_with_multi_release_bsp_file))
        manager.initialize()
        manager.list_bsp()
        captured = capsys.readouterr()
        assert "qemu-arm64-scarthgap" in captured.out
        assert "qemu-arm64-styhead" in captured.out
        assert "qemu-x86-64-walnascar" in captured.out

    def test_get_bsp_by_name_expanded(self, registry_with_multi_release_bsp_file):
        """get_bsp_by_name() finds an expanded preset by its full name."""
        manager = BspManager(config_path=str(registry_with_multi_release_bsp_file))
        manager.initialize()
        preset = manager.get_bsp_by_name("qemu-arm64-scarthgap")
        assert isinstance(preset, BspPreset)
        assert preset.release == "scarthgap"

    def test_single_release_preset_unchanged(self, registry_with_multi_release_bsp_file):
        """Presets using the singular release field are returned as-is."""
        manager = BspManager(config_path=str(registry_with_multi_release_bsp_file))
        manager.initialize()
        preset = manager.get_bsp_by_name("qemu-x86-64-walnascar")
        assert preset.release == "walnascar"
        resolved, _ = manager.resolver.resolve_preset("qemu-x86-64-walnascar")
        assert resolved.build_path == "build/qemu-x86-64-walnascar"

    def test_expand_preset_both_fields_exits(self, tmp_dir):
        """expand_preset() exits when both release and releases are set."""
        bad_yaml = """
specification:
  version: "2.0"
containers:
  c:
    image: "test:latest"
    file: null
    args: []
registry:
  devices:
    - slug: dev
      description: "d"
      vendor: v
      soc_vendor: s
      includes: []
  releases:
    - slug: rel-a
      description: "r"
      includes: []
    - slug: rel-b
      description: "r"
      includes: []
  features: []
  bsp:
    - name: bad-preset
      description: "both fields set"
      device: dev
      release: rel-a
      releases: [rel-b]
"""
        p = tmp_dir / "bad.yaml"
        p.write_text(bad_yaml)
        manager = BspManager(config_path=str(p))
        manager.initialize()
        with pytest.raises(SystemExit):
            manager.resolver.list_presets()

    def test_expand_preset_neither_field_exits(self, tmp_dir):
        """expand_preset() exits when neither release nor releases is set."""
        bad_yaml = """
specification:
  version: "2.0"
containers:
  c:
    image: "test:latest"
    file: null
    args: []
registry:
  devices:
    - slug: dev
      description: "d"
      vendor: v
      soc_vendor: s
      includes: []
  releases:
    - slug: rel-a
      description: "r"
      includes: []
  features: []
  bsp:
    - name: bad-preset
      description: "no release field"
      device: dev
"""
        p = tmp_dir / "bad.yaml"
        p.write_text(bad_yaml)
        manager = BspManager(config_path=str(p))
        manager.initialize()
        with pytest.raises(SystemExit):
            manager.resolver.list_presets()


class TestVendorIncludes:
    """Tests for vendor_includes on Release and Distro."""

    def test_release_vendor_includes_applied_for_matching_vendor(
        self, registry_with_vendor_includes_file
    ):
        """Vendor includes from a release are added to KAS files for a matching device vendor."""
        manager = BspManager(config_path=str(registry_with_vendor_includes_file))
        manager.initialize()
        resolved = manager.resolver.resolve("adv-imx8", "scarthgap")
        assert "vendors/advantech/nxp/imx-6.6.52-2.2.0-scarthgap.yml" in resolved.kas_files

    def test_release_vendor_includes_not_applied_for_other_vendor(
        self, registry_with_vendor_includes_file
    ):
        """Vendor includes from a release are NOT added for a device with a different vendor."""
        manager = BspManager(config_path=str(registry_with_vendor_includes_file))
        manager.initialize()
        resolved = manager.resolver.resolve("qemu-arm64", "scarthgap")
        assert "vendors/advantech/nxp/imx-6.6.52-2.2.0-scarthgap.yml" not in resolved.kas_files

    def test_distro_vendor_includes_applied_for_matching_vendor(
        self, registry_with_vendor_includes_file
    ):
        """Vendor includes from a distro are added to KAS files for a matching device vendor."""
        manager = BspManager(config_path=str(registry_with_vendor_includes_file))
        manager.initialize()
        resolved = manager.resolver.resolve("adv-imx8", "scarthgap")
        assert "vendors/advantech/distro-common.yml" in resolved.kas_files

    def test_distro_vendor_includes_not_applied_for_other_vendor(
        self, registry_with_vendor_includes_file
    ):
        """Distro vendor includes are NOT added for a device with a different vendor."""
        manager = BspManager(config_path=str(registry_with_vendor_includes_file))
        manager.initialize()
        resolved = manager.resolver.resolve("qemu-arm64", "scarthgap")
        assert "vendors/advantech/distro-common.yml" not in resolved.kas_files

    def test_vendor_includes_maintain_correct_kas_file_order(self, registry_with_vendor_includes_file):
        """KAS file order: distro.includes -> distro.vendor_includes -> release.includes
        -> release.vendor_includes -> device.includes."""
        manager = BspManager(config_path=str(registry_with_vendor_includes_file))
        manager.initialize()
        resolved = manager.resolver.resolve("adv-imx8", "scarthgap")
        kas = resolved.kas_files
        idx_distro = kas.index("kas/poky/distro/poky.yaml")
        idx_distro_vendor = kas.index("vendors/advantech/distro-common.yml")
        idx_release = kas.index("kas/poky/scarthgap.yaml")
        idx_release_vendor = kas.index("vendors/advantech/nxp/imx-6.6.52-2.2.0-scarthgap.yml")
        idx_device = kas.index("kas/adv-imx8.yaml")
        assert idx_distro < idx_distro_vendor < idx_release < idx_release_vendor < idx_device

    def test_release_without_vendor_includes_unaffected(
        self, registry_with_vendor_includes_file
    ):
        """A release with no vendor_includes resolves normally for any device vendor."""
        manager = BspManager(config_path=str(registry_with_vendor_includes_file))
        manager.initialize()
        resolved = manager.resolver.resolve("adv-imx8", "generic-release")
        assert "kas/poky/generic.yaml" in resolved.kas_files
        # No vendor-specific files should appear
        assert "vendors/advantech/nxp/imx-6.6.52-2.2.0-scarthgap.yml" not in resolved.kas_files

    def test_list_releases_filters_by_device_vendor(
        self, registry_with_vendor_includes_file, capsys
    ):
        """list_releases with device_slug filters out releases that have no matching vendor."""
        manager = BspManager(config_path=str(registry_with_vendor_includes_file))
        manager.initialize()
        manager.list_releases(device_slug="adv-imx8")
        captured = capsys.readouterr()
        # scarthgap and kirkstone have advantech vendor_includes -> shown
        assert "scarthgap" in captured.out
        assert "kirkstone" in captured.out
        # generic-release has no vendor_includes -> also shown (generic = all vendors)
        assert "generic-release" in captured.out

    def test_list_releases_filters_out_non_matching_vendor(
        self, registry_with_vendor_includes_file, capsys
    ):
        """list_releases with qemu device_slug excludes releases that only have advantech includes."""
        manager = BspManager(config_path=str(registry_with_vendor_includes_file))
        manager.initialize()
        manager.list_releases(device_slug="qemu-arm64")
        captured = capsys.readouterr()
        # scarthgap and kirkstone only have advantech vendor_includes -> excluded for qemu
        assert "scarthgap" not in captured.out
        assert "kirkstone" not in captured.out
        # generic-release has no vendor_includes -> shown for all devices
        assert "generic-release" in captured.out

    def test_distro_vendor_includes_loaded_from_yaml(
        self, registry_with_vendor_includes_file
    ):
        """Distro vendor_includes field is correctly parsed from YAML."""
        manager = BspManager(config_path=str(registry_with_vendor_includes_file))
        manager.initialize()
        distro = manager.resolver.get_distro("poky")
        assert len(distro.vendor_includes) == 1
        assert distro.vendor_includes[0].vendor == "advantech"
        assert "vendors/advantech/distro-common.yml" in distro.vendor_includes[0].includes
