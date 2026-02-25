"""
Comprehensive pytest tests for bsp.py functionality.

Tests cover:
- Configuration data classes
- YAML parsing and validation
- EnvironmentManager with variable expansion
- PathResolver utility methods
- KasManager configuration and file resolution
- BspManager registry operations
- Exception hierarchy
- Container configuration handling
"""

import os
import sys
import pytest
import tempfile
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

# Add parent directory to path so we can import bsp module
sys.path.insert(0, str(Path(__file__).parent.parent))

import bsp
from bsp import (
    # Data classes
    EnvironmentVariable,
    DockerArg,
    Docker,
    ContainerDefinition,
    BuildEnvironment,
    BuildSetup,
    Specification,
    OperatingSystem,
    BSP,
    Registry,
    RegistryRoot,
    # Exceptions
    ScriptError,
    ConfigurationError,
    BuildError,
    DockerError,
    KasError,
    # Utility functions
    read_yaml_file,
    parse_yaml_file,
    get_registry_from_yaml_file,
    convert_containers_list_to_dict,
    # Classes
    PathResolver,
    EnvironmentManager,
    KasManager,
    BspManager,
    # Factory functions
    empty_list,
    empty_dict,
)


# =============================================================================
# Fixtures
# =============================================================================

MINIMAL_REGISTRY_YAML = """
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
containers:
  - ubuntu-22.04:
      image: "test/ubuntu-22.04:latest"
      file: Dockerfile.ubuntu
      args:
        - name: "DISTRO"
          value: "ubuntu:22.04"
"""

REGISTRY_WITH_ENV_YAML = """
specification:
  version: "1.0"
environment:
  - name: "DL_DIR"
    value: "/tmp/downloads"
  - name: "SSTATE_DIR"
    value: "/tmp/sstate"
  - name: "GITCONFIG_FILE"
    value: "$ENV{HOME}/.gitconfig"
registry:
  bsp:
    - name: qemu-arm64
      description: "QEMU ARM64 BSP"
      os:
        name: linux
        build_system: yocto
        version: "5.0"
      build:
        path: build/qemu-arm64
        environment:
          container: "ubuntu-22.04"
        configuration:
          - kas/qemu/qemuarm64.yml
    - name: qemu-x86-64
      description: "QEMU x86-64 BSP"
      build:
        path: build/qemu-x86-64
        environment:
          container: "ubuntu-22.04"
        configuration:
          - kas/qemu/qemux86-64.yml
containers:
  - ubuntu-22.04:
      image: "test/ubuntu-22.04:latest"
      file: Dockerfile.ubuntu
      args: []
"""

INVALID_YAML = """
specification:
  version: [invalid
"""

EMPTY_REGISTRY_YAML = """
specification:
  version: "1.0"
registry:
  bsp: []
"""


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def registry_file(tmp_dir):
    """Create a minimal registry YAML file in a temp directory."""
    registry_path = tmp_dir / "bsp-registry.yml"
    registry_path.write_text(MINIMAL_REGISTRY_YAML)
    return registry_path


@pytest.fixture
def registry_with_env_file(tmp_dir):
    """Create a registry YAML file with environment variables."""
    registry_path = tmp_dir / "bsp-registry.yml"
    registry_path.write_text(REGISTRY_WITH_ENV_YAML)
    return registry_path


@pytest.fixture
def kas_config_file(tmp_dir):
    """Create a simple KAS configuration YAML file."""
    kas_content = """
header:
  version: 14

distro: poky
machine: qemuarm64

target:
  - core-image-minimal
"""
    kas_path = tmp_dir / "test.yml"
    kas_path.write_text(kas_content)
    return kas_path


@pytest.fixture
def kas_config_with_includes(tmp_dir):
    """Create KAS configuration files with includes."""
    base_content = """
header:
  version: 14
  includes:
    - include.yml

machine: qemuarm64
"""
    include_content = """
header:
  version: 14

distro: poky
"""
    base_path = tmp_dir / "base.yml"
    include_path = tmp_dir / "include.yml"
    base_path.write_text(base_content)
    include_path.write_text(include_content)
    return base_path, include_path


# =============================================================================
# Tests for Exception Hierarchy
# =============================================================================

class TestExceptionHierarchy:
    def test_script_error_is_exception(self):
        assert issubclass(ScriptError, Exception)

    def test_configuration_error_inherits_script_error(self):
        assert issubclass(ConfigurationError, ScriptError)

    def test_build_error_inherits_script_error(self):
        assert issubclass(BuildError, ScriptError)

    def test_docker_error_inherits_script_error(self):
        assert issubclass(DockerError, ScriptError)

    def test_kas_error_inherits_script_error(self):
        assert issubclass(KasError, ScriptError)

    def test_raise_configuration_error(self):
        with pytest.raises(ConfigurationError):
            raise ConfigurationError("test error")

    def test_raise_build_error(self):
        with pytest.raises(BuildError):
            raise BuildError("build failed")


# =============================================================================
# Tests for Factory Functions and Data Classes
# =============================================================================

class TestFactoryFunctions:
    def test_empty_list_returns_list(self):
        result = empty_list()
        assert isinstance(result, list)
        assert result == []

    def test_empty_list_returns_new_instance(self):
        a = empty_list()
        b = empty_list()
        a.append(1)
        assert b == []

    def test_empty_dict_returns_dict(self):
        result = empty_dict()
        assert isinstance(result, dict)
        assert result == {}

    def test_empty_dict_returns_new_instance(self):
        a = empty_dict()
        b = empty_dict()
        a["key"] = "value"
        assert b == {}


class TestDataClasses:
    def test_environment_variable(self):
        ev = EnvironmentVariable(name="MY_VAR", value="my_value")
        assert ev.name == "MY_VAR"
        assert ev.value == "my_value"

    def test_docker_arg(self):
        arg = DockerArg(name="DISTRO", value="ubuntu:22.04")
        assert arg.name == "DISTRO"
        assert arg.value == "ubuntu:22.04"

    def test_docker_with_optional_fields(self):
        docker = Docker(image="my-image:latest", file=None)
        assert docker.image == "my-image:latest"
        assert docker.file is None
        assert docker.args == []

    def test_docker_with_args(self):
        args = [DockerArg(name="VERSION", value="22.04")]
        docker = Docker(image="my-image", file="Dockerfile", args=args)
        assert len(docker.args) == 1
        assert docker.args[0].name == "VERSION"

    def test_build_environment_defaults(self):
        env = BuildEnvironment()
        assert env.container is None
        assert env.docker is None

    def test_build_setup(self):
        env = BuildEnvironment(container="ubuntu-22.04")
        setup = BuildSetup(
            path="build/test",
            environment=env,
            docker=None,
            configuration=["test.yml"]
        )
        assert setup.path == "build/test"
        assert setup.configuration == ["test.yml"]

    def test_specification(self):
        spec = Specification(version="1.0")
        assert spec.version == "1.0"

    def test_operating_system(self):
        os_cfg = OperatingSystem(name="linux", build_system="yocto", version="5.0")
        assert os_cfg.name == "linux"
        assert os_cfg.build_system == "yocto"
        assert os_cfg.version == "5.0"

    def test_bsp_without_os(self):
        env = BuildEnvironment(container="ubuntu-22.04")
        setup = BuildSetup(
            path="build/test",
            environment=env,
            docker=None,
            configuration=["test.yml"]
        )
        bsp_obj = BSP(name="test-bsp", description="Test BSP", build=setup)
        assert bsp_obj.name == "test-bsp"
        assert bsp_obj.os is None

    def test_registry_defaults(self):
        reg = Registry()
        assert reg.bsp == []

    def test_registry_root_defaults(self):
        spec = Specification(version="1.0")
        reg = Registry()
        root = RegistryRoot(specification=spec, registry=reg)
        assert root.containers == {}
        assert root.environment == []


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
# Tests for PathResolver
# =============================================================================

class TestPathResolver:
    def test_resolve_returns_path(self, tmp_dir):
        result = PathResolver.resolve(str(tmp_dir))
        assert isinstance(result, Path)

    def test_resolve_str_returns_string(self, tmp_dir):
        result = PathResolver.resolve_str(str(tmp_dir))
        assert isinstance(result, str)

    def test_resolve_tilde_expansion(self):
        result = PathResolver.resolve("~")
        assert str(result) == str(Path.home())

    def test_exists_true_for_existing(self, tmp_dir):
        assert PathResolver.exists(str(tmp_dir)) is True

    def test_exists_false_for_nonexistent(self, tmp_dir):
        assert PathResolver.exists(str(tmp_dir / "nonexistent")) is False

    def test_is_file_true(self, tmp_dir):
        test_file = tmp_dir / "test.txt"
        test_file.write_text("content")
        assert PathResolver.is_file(str(test_file)) is True

    def test_is_file_false_for_dir(self, tmp_dir):
        assert PathResolver.is_file(str(tmp_dir)) is False

    def test_is_dir_true(self, tmp_dir):
        assert PathResolver.is_dir(str(tmp_dir)) is True

    def test_is_dir_false_for_file(self, tmp_dir):
        test_file = tmp_dir / "test.txt"
        test_file.write_text("content")
        assert PathResolver.is_dir(str(test_file)) is False

    def test_ensure_directory_creates_dir(self, tmp_dir):
        new_dir = tmp_dir / "new" / "nested" / "dir"
        PathResolver.ensure_directory(str(new_dir))
        assert new_dir.is_dir()

    def test_ensure_directory_existing_dir_ok(self, tmp_dir):
        # Should not raise for existing directories
        PathResolver.ensure_directory(str(tmp_dir))
        assert tmp_dir.is_dir()


# =============================================================================
# Tests for EnvironmentManager
# =============================================================================

class TestEnvironmentManager:
    def test_init_empty(self):
        manager = EnvironmentManager()
        assert manager.get_environment_dict() == {}

    def test_init_with_variables(self):
        vars_ = [
            EnvironmentVariable(name="VAR1", value="value1"),
            EnvironmentVariable(name="VAR2", value="value2"),
        ]
        manager = EnvironmentManager(vars_)
        env_dict = manager.get_environment_dict()
        assert env_dict["VAR1"] == "value1"
        assert env_dict["VAR2"] == "value2"

    def test_expand_env_var_pattern(self):
        with patch.dict(os.environ, {"MY_HOME": "/home/testuser"}):
            vars_ = [EnvironmentVariable(name="DL_DIR", value="$ENV{MY_HOME}/downloads")]
            manager = EnvironmentManager(vars_)
            assert manager.get_value("DL_DIR") == "/home/testuser/downloads"

    def test_expand_env_var_missing_warns(self, caplog):
        import logging
        vars_ = [EnvironmentVariable(name="TEST_VAR", value="$ENV{NONEXISTENT_VAR_12345}/path")]
        with caplog.at_level(logging.WARNING):
            manager = EnvironmentManager(vars_)
        assert manager.get_value("TEST_VAR") == "/path"

    def test_get_value_existing(self):
        vars_ = [EnvironmentVariable(name="MY_KEY", value="my_val")]
        manager = EnvironmentManager(vars_)
        assert manager.get_value("MY_KEY") == "my_val"

    def test_get_value_missing_returns_default(self):
        manager = EnvironmentManager()
        assert manager.get_value("MISSING_KEY", "default") == "default"

    def test_get_value_missing_returns_none(self):
        manager = EnvironmentManager()
        assert manager.get_value("MISSING_KEY") is None

    def test_get_environment_dict_returns_copy(self):
        vars_ = [EnvironmentVariable(name="KEY", value="value")]
        manager = EnvironmentManager(vars_)
        d1 = manager.get_environment_dict()
        d1["NEW_KEY"] = "new_value"
        d2 = manager.get_environment_dict()
        assert "NEW_KEY" not in d2

    def test_validate_environment_returns_true(self):
        manager = EnvironmentManager()
        assert manager.validate_environment() is True

    def test_setup_environment_merges(self):
        vars_ = [EnvironmentVariable(name="MY_VAR", value="configured")]
        manager = EnvironmentManager(vars_)
        base = {"EXISTING": "base_value", "MY_VAR": "original"}
        result = manager.setup_environment(base)
        assert result["EXISTING"] == "base_value"
        assert result["MY_VAR"] == "configured"

    def test_setup_environment_does_not_modify_base(self):
        vars_ = [EnvironmentVariable(name="NEW_VAR", value="new_value")]
        manager = EnvironmentManager(vars_)
        base = {"EXISTING": "base_value"}
        manager.setup_environment(base)
        assert "NEW_VAR" not in base

    def test_multiple_env_expansions(self):
        with patch.dict(os.environ, {"USER": "testuser", "HOST": "testhost"}):
            vars_ = [
                EnvironmentVariable(name="FULL_ADDR", value="$ENV{USER}@$ENV{HOST}")
            ]
            manager = EnvironmentManager(vars_)
            assert manager.get_value("FULL_ADDR") == "testuser@testhost"


# =============================================================================
# Tests for KasManager
# =============================================================================

class TestKasManager:
    def test_init_basic(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build")
        )
        assert manager.kas_files == [str(kas_config_file)]
        assert manager.use_container is False

    def test_init_requires_non_empty_kas_files(self, tmp_dir):
        with pytest.raises(SystemExit):
            KasManager(kas_files=[], build_dir=str(tmp_dir / "build"))

    def test_init_requires_list_kas_files(self, tmp_dir):
        with pytest.raises(SystemExit):
            KasManager(kas_files="not-a-list", build_dir=str(tmp_dir / "build"))

    def test_get_kas_command_native(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build"),
            use_container=False
        )
        assert manager._get_kas_command() == ["kas"]

    def test_get_kas_command_container(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build"),
            use_container=True
        )
        assert manager._get_kas_command() == ["kas-container"]

    def test_resolve_kas_file_absolute(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build")
        )
        resolved = manager._resolve_kas_file(str(kas_config_file))
        assert resolved == str(kas_config_file)

    def test_resolve_kas_file_not_found_exits(self, tmp_dir):
        manager = KasManager(
            kas_files=[str(tmp_dir / "nonexistent.yml")],
            build_dir=str(tmp_dir / "build")
        )
        with pytest.raises(SystemExit):
            manager._resolve_kas_file("totally_missing_file.yml")

    def test_get_kas_files_string(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build")
        )
        result = manager._get_kas_files_string()
        assert str(kas_config_file) in result

    def test_get_kas_files_string_multiple(self, tmp_dir):
        file1 = tmp_dir / "file1.yml"
        file2 = tmp_dir / "file2.yml"
        file1.write_text("header:\n  version: 14\n")
        file2.write_text("header:\n  version: 14\n")
        manager = KasManager(
            kas_files=[str(file1), str(file2)],
            build_dir=str(tmp_dir / "build")
        )
        result = manager._get_kas_files_string()
        assert ":" in result

    def test_find_includes_in_yaml_top_level(self):
        content = {"includes": ["file1.yml", "file2.yml"]}
        manager = KasManager.__new__(KasManager)
        result = manager._find_includes_in_yaml(content)
        assert result == ["file1.yml", "file2.yml"]

    def test_find_includes_in_yaml_header(self):
        content = {"header": {"includes": ["file1.yml"]}}
        manager = KasManager.__new__(KasManager)
        result = manager._find_includes_in_yaml(content)
        assert result == ["file1.yml"]

    def test_find_includes_in_yaml_empty(self):
        content = {"machine": "qemuarm64"}
        manager = KasManager.__new__(KasManager)
        result = manager._find_includes_in_yaml(content)
        assert result == []

    def test_find_includes_both_sources(self):
        content = {
            "includes": ["top.yml"],
            "header": {"includes": ["header.yml"]}
        }
        manager = KasManager.__new__(KasManager)
        result = manager._find_includes_in_yaml(content)
        assert "top.yml" in result
        assert "header.yml" in result

    def test_validate_kas_files_success(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build")
        )
        assert manager.validate_kas_files(check_includes=False) is True

    def test_validate_kas_files_with_includes(self, kas_config_with_includes):
        base_path, include_path = kas_config_with_includes
        manager = KasManager(
            kas_files=[str(base_path)],
            build_dir=str(base_path.parent / "build")
        )
        assert manager.validate_kas_files(check_includes=True) is True

    def test_parse_yaml_file_with_cache(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build")
        )
        result1 = manager._parse_yaml_file(str(kas_config_file))
        result2 = manager._parse_yaml_file(str(kas_config_file))
        assert result1 == result2
        assert str(kas_config_file) in manager._yaml_cache

    def test_environment_variables_in_kas_env(self, kas_config_file):
        with patch.dict(os.environ, {"DL_DIR": "/custom/downloads"}):
            manager = KasManager(
                kas_files=[str(kas_config_file)],
                build_dir=str(kas_config_file.parent / "build"),
                download_dir="/custom/downloads"
            )
            env = manager._get_environment_with_container_vars()
            assert env.get("DL_DIR") == "/custom/downloads"

    def test_container_env_vars_set_when_using_container(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build"),
            use_container=True,
            container_engine="docker",
            container_image="custom-image:latest"
        )
        env = manager._get_environment_with_container_vars()
        assert env.get("KAS_CONTAINER_ENGINE") == "docker"
        assert env.get("KAS_CONTAINER_IMAGE") == "custom-image:latest"

    def test_check_kas_available_when_installed(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build"),
            use_container=False
        )
        # kas should be available in the test environment (installed via pip)
        result = manager.check_kas_available()
        assert isinstance(result, bool)


# =============================================================================
# Tests for BspManager
# =============================================================================

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


# =============================================================================
# Tests for main() CLI
# =============================================================================

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


# =============================================================================
# Tests for ColoramaFormatter
# =============================================================================

class TestColoramaFormatter:
    def test_formatter_is_logging_formatter(self):
        import logging
        formatter = bsp.ColoramaFormatter()
        assert isinstance(formatter, logging.Formatter)

    def test_format_record(self):
        import logging
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None
        )
        formatter = bsp.ColoramaFormatter()
        result = formatter.format(record)
        assert "Test message" in result
