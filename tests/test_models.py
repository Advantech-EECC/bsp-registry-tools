"""
Tests for configuration data classes and factory functions.
"""

from bsp import (
    EnvironmentVariable,
    DockerArg,
    Docker,
    BuildEnvironment,
    BuildSetup,
    Specification,
    OperatingSystem,
    BSP,
    Registry,
    RegistryRoot,
    empty_list,
    empty_dict,
)


# =============================================================================
# Tests for Factory Functions
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


# =============================================================================
# Tests for Data Classes
# =============================================================================

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
