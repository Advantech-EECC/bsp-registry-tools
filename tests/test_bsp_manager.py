"""
Tests for BspManager registry operations.
"""

import pytest

from bsp import BspManager, Docker
from .conftest import EMPTY_REGISTRY_YAML


class TestBspManager:
    def test_init(self, tmp_dir):
        manager = BspManager(config_path=str(tmp_dir / "bsp-registry.yml"))
        assert manager.model is None
        assert manager.env_manager is None
        assert manager.containers == {}

    def test_load_configuration_success(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.load_configuration()
        assert manager.model is not None
        assert len(manager.model.registry.bsp) == 1

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

    def test_initialize(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        assert manager.model is not None

    def test_list_bsp_outputs_names(self, registry_file, capsys):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        manager.list_bsp()
        captured = capsys.readouterr()
        assert "test-bsp" in captured.out

    def test_list_bsp_outputs_descriptions(self, registry_file, capsys):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        manager.list_bsp()
        captured = capsys.readouterr()
        assert "Test BSP" in captured.out

    def test_list_bsp_empty_registry_exits(self, tmp_dir):
        empty_file = tmp_dir / "empty.yml"
        empty_file.write_text(EMPTY_REGISTRY_YAML)
        manager = BspManager(config_path=str(empty_file))
        manager.initialize()
        with pytest.raises(SystemExit):
            manager.list_bsp()

    def test_list_containers_outputs_names(self, registry_file, capsys):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        manager.list_containers()
        captured = capsys.readouterr()
        assert "ubuntu-22.04" in captured.out

    def test_list_containers_empty(self, tmp_dir):
        no_containers_yaml = """
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
          - test.yml
"""
        registry_file = tmp_dir / "bsp-registry.yml"
        registry_file.write_text(no_containers_yaml)
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        # Should not raise, just log info
        manager.list_containers()

    def test_get_bsp_by_name_found(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        bsp_obj = manager.get_bsp_by_name("test-bsp")
        assert bsp_obj.name == "test-bsp"

    def test_get_bsp_by_name_not_found(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        with pytest.raises(SystemExit):
            manager.get_bsp_by_name("nonexistent-bsp")

    def test_get_container_config_for_bsp_with_container_ref(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        bsp_obj = manager.get_bsp_by_name("test-bsp")
        container = manager.get_container_config_for_bsp(bsp_obj)
        assert isinstance(container, Docker)
        assert container.image == "test/ubuntu-22.04:latest"

    def test_get_container_config_missing_container_ref(self, tmp_dir):
        yaml_content = """
specification:
  version: "1.0"
registry:
  bsp:
    - name: test-bsp
      description: "Test BSP"
      build:
        path: build/test
        environment:
          container: "nonexistent-container"
        configuration:
          - test.yml
containers: []
"""
        registry_file = tmp_dir / "bsp-registry.yml"
        registry_file.write_text(yaml_content)
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        bsp_obj = manager.get_bsp_by_name("test-bsp")
        with pytest.raises(SystemExit):
            manager.get_container_config_for_bsp(bsp_obj)

    def test_get_container_config_with_direct_docker(self, tmp_dir):
        yaml_content = """
specification:
  version: "1.0"
registry:
  bsp:
    - name: test-bsp
      description: "Test BSP"
      build:
        path: build/test
        environment:
          docker:
            image: "direct-image:latest"
        configuration:
          - test.yml
"""
        registry_file = tmp_dir / "bsp-registry.yml"
        registry_file.write_text(yaml_content)
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        bsp_obj = manager.get_bsp_by_name("test-bsp")
        container = manager.get_container_config_for_bsp(bsp_obj)
        assert container.image == "direct-image:latest"

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

    def test_multiple_bsps(self, registry_with_env_file):
        manager = BspManager(config_path=str(registry_with_env_file))
        manager.initialize()
        assert len(manager.model.registry.bsp) == 2
        names = [b.name for b in manager.model.registry.bsp]
        assert "qemu-arm64" in names
        assert "qemu-x86-64" in names

    def test_bsp_with_os_info(self, registry_with_env_file):
        manager = BspManager(config_path=str(registry_with_env_file))
        manager.initialize()
        bsp_obj = manager.get_bsp_by_name("qemu-arm64")
        assert bsp_obj.os is not None
        assert bsp_obj.os.name == "linux"
        assert bsp_obj.os.build_system == "yocto"
