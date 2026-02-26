"""
Tests for v2.0 configuration data classes and factory functions.
"""

from bsp import (
    EnvironmentVariable,
    DockerArg,
    Docker,
    Specification,
    DeviceBuild,
    Device,
    VendorIncludes,
    Release,
    FeatureCompatibility,
    Feature,
    BspPreset,
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
# Tests for Shared Data Classes
# =============================================================================

class TestSharedDataClasses:
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

    def test_specification(self):
        spec = Specification(version="2.0")
        assert spec.version == "2.0"


# =============================================================================
# Tests for v2.0 Data Classes
# =============================================================================

class TestV2DataClasses:
    def test_device_build_defaults(self):
        db = DeviceBuild(container="ubuntu-22.04", path="build/test")
        assert db.container == "ubuntu-22.04"
        assert db.path == "build/test"
        assert db.includes == []
        assert db.local_conf == []

    def test_device_build_with_includes(self):
        db = DeviceBuild(
            container="ubuntu-22.04",
            path="build/test",
            includes=["kas/board.yml"],
            local_conf=["MACHINE = 'myboard'"],
        )
        assert db.includes == ["kas/board.yml"]
        assert db.local_conf == ["MACHINE = 'myboard'"]

    def test_device_minimal(self):
        db = DeviceBuild(container="c", path="p")
        d = Device(
            slug="my-device",
            description="My Device",
            vendor="acme",
            soc_vendor="nxp",
            build=db,
        )
        assert d.slug == "my-device"
        assert d.vendor == "acme"
        assert d.soc_vendor == "nxp"
        assert d.soc_family is None

    def test_device_with_soc_family(self):
        db = DeviceBuild(container="c", path="p")
        d = Device(
            slug="imx8-board",
            description="i.MX8 Board",
            vendor="advantech",
            soc_vendor="nxp",
            build=db,
            soc_family="imx8",
        )
        assert d.soc_family == "imx8"

    def test_vendor_includes(self):
        vi = VendorIncludes(vendor="advantech", includes=["kas/adv.yml"])
        assert vi.vendor == "advantech"
        assert vi.includes == ["kas/adv.yml"]

    def test_vendor_includes_defaults(self):
        vi = VendorIncludes(vendor="myvendor")
        assert vi.includes == []

    def test_release_minimal(self):
        r = Release(slug="scarthgap", description="Yocto 5.0 LTS")
        assert r.slug == "scarthgap"
        assert r.yocto_version is None
        assert r.isar_version is None
        assert r.includes == []
        assert r.vendor_includes == []

    def test_release_full(self):
        vi = VendorIncludes(vendor="acme", includes=["kas/acme.yml"])
        r = Release(
            slug="scarthgap",
            description="Yocto 5.0 LTS",
            yocto_version="5.0",
            includes=["kas/scarthgap.yml"],
            vendor_includes=[vi],
        )
        assert r.yocto_version == "5.0"
        assert len(r.vendor_includes) == 1

    def test_feature_compatibility_defaults(self):
        fc = FeatureCompatibility()
        assert fc.vendor == []
        assert fc.soc_vendor == []
        assert fc.soc_family == []

    def test_feature_compatibility_with_values(self):
        fc = FeatureCompatibility(soc_vendor=["nxp", "ti"])
        assert fc.soc_vendor == ["nxp", "ti"]

    def test_feature_minimal(self):
        f = Feature(slug="ota", description="OTA Update")
        assert f.slug == "ota"
        assert f.compatibility is None
        assert f.includes == []
        assert f.local_conf == []
        assert f.env == []

    def test_feature_with_compatibility(self):
        fc = FeatureCompatibility(soc_vendor=["nxp"])
        f = Feature(
            slug="secure-boot",
            description="Secure Boot",
            compatibility=fc,
            includes=["kas/secure-boot.yml"],
            local_conf=["SECURE_BOOT = '1'"],
            env=[EnvironmentVariable(name="SIGN_KEY", value="/path/to/key")],
        )
        assert f.compatibility.soc_vendor == ["nxp"]
        assert len(f.includes) == 1
        assert len(f.local_conf) == 1
        assert len(f.env) == 1

    def test_bsp_preset_minimal(self):
        p = BspPreset(
            name="my-preset",
            description="My Preset",
            device="my-device",
            release="scarthgap",
        )
        assert p.name == "my-preset"
        assert p.device == "my-device"
        assert p.release == "scarthgap"
        assert p.features == []

    def test_bsp_preset_with_features(self):
        p = BspPreset(
            name="my-preset",
            description="My Preset",
            device="my-device",
            release="scarthgap",
            features=["ota", "secure-boot"],
        )
        assert p.features == ["ota", "secure-boot"]

    def test_registry_defaults(self):
        reg = Registry()
        assert reg.devices == []
        assert reg.releases == []
        assert reg.features == []
        assert reg.bsp == []

    def test_registry_root_defaults(self):
        spec = Specification(version="2.0")
        reg = Registry()
        root = RegistryRoot(specification=spec, registry=reg)
        assert root.specification.version == "2.0"
        assert root.containers == {}
        assert root.environment == []
