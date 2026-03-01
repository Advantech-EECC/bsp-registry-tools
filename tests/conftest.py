"""
Shared pytest fixtures and YAML constants for bsp-registry-tools tests (v2.0 schema).
"""

import tempfile
import pytest
from pathlib import Path


# =============================================================================
# Shared YAML test data (v2.0 schema)
# =============================================================================

MINIMAL_REGISTRY_YAML = """
specification:
  version: "2.0"
containers:
  ubuntu-22.04:
    image: "test/ubuntu-22.04:latest"
    file: Dockerfile.ubuntu
    args:
      - name: "DISTRO"
        value: "ubuntu:22.04"
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
          - test.yml
  releases:
    - slug: test-release
      description: "Test Release"
      yocto_version: "5.0"
      includes:
        - test-base.yml
  features: []
  bsp:
    - name: test-bsp
      description: "Test BSP"
      device: test-device
      release: test-release
      features: []
"""

REGISTRY_WITH_ENV_YAML = """
specification:
  version: "2.0"
environment:
  - name: "DL_DIR"
    value: "/tmp/downloads"
  - name: "SSTATE_DIR"
    value: "/tmp/sstate"
  - name: "GITCONFIG_FILE"
    value: "$ENV{HOME}/.gitconfig"
containers:
  ubuntu-22.04:
    image: "test/ubuntu-22.04:latest"
    file: Dockerfile.ubuntu
    args: []
registry:
  devices:
    - slug: qemu-arm64
      description: "QEMU ARM64"
      vendor: qemu
      soc_vendor: arm
      build:
        container: "ubuntu-22.04"
        path: build/qemu-arm64
        includes:
          - kas/qemu/qemuarm64.yml
    - slug: qemu-x86-64
      description: "QEMU x86-64"
      vendor: qemu
      soc_vendor: intel
      build:
        container: "ubuntu-22.04"
        path: build/qemu-x86-64
        includes:
          - kas/qemu/qemux86-64.yml
  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS (Scarthgap)"
      yocto_version: "5.0"
      includes:
        - kas/scarthgap.yml
  features: []
  bsp:
    - name: qemu-arm64
      description: "QEMU ARM64 BSP"
      device: qemu-arm64
      release: scarthgap
      features: []
    - name: qemu-x86-64
      description: "QEMU x86-64 BSP"
      device: qemu-x86-64
      release: scarthgap
      features: []
"""

INVALID_YAML = """
specification:
  version: [invalid
"""

EMPTY_REGISTRY_YAML = """
specification:
  version: "2.0"
registry:
  devices: []
  releases: []
  features: []
  bsp: []
"""

REGISTRY_WITH_FEATURES_YAML = """
specification:
  version: "2.0"
containers:
  debian-bookworm:
    image: "test/debian:latest"
    file: Dockerfile
    args: []
registry:
  devices:
    - slug: imx8-board
      description: "i.MX8 Board"
      vendor: advantech
      soc_vendor: nxp
      soc_family: imx8
      build:
        container: "debian-bookworm"
        path: build/imx8-board
        includes:
          - kas/imx8.yml
    - slug: qemu-arm64
      description: "QEMU ARM64"
      vendor: qemu
      soc_vendor: arm
      build:
        container: "debian-bookworm"
        path: build/qemuarm64
        includes:
          - kas/qemuarm64.yml
  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS"
      yocto_version: "5.0"
      includes:
        - kas/scarthgap.yml
  features:
    - slug: ota
      description: "Over-the-Air Update support"
      includes:
        - kas/features/ota.yml
      local_conf:
        - "DISTRO_FEATURES:append = ' swupdate'"
    - slug: secure-boot
      description: "Secure Boot support"
      compatibility:
        soc_vendor:
          - nxp
      includes:
        - kas/features/secure-boot.yml
      env:
        - name: "SIGNING_KEY"
          value: "$ENV{SIGNING_KEY}"
  bsp:
    - name: imx8-scarthgap-ota
      description: "i.MX8 Scarthgap with OTA"
      device: imx8-board
      release: scarthgap
      features:
        - ota
"""

REGISTRY_WITH_NAMED_ENVIRONMENTS_YAML = """
specification:
  version: "2.0"

environments:
  default:
    container: "debian-bookworm"
    variables:
      - name: "DL_DIR"
        value: "/tmp/downloads"
      - name: "SSTATE_DIR"
        value: "/tmp/sstate"
  isar-env:
    container: "debian-bookworm-isar"
    variables:
      - name: "DL_DIR"
        value: "/tmp/isar-downloads"

containers:
  debian-bookworm:
    image: "test/debian:latest"
    file: null
    args: []
  debian-bookworm-isar:
    image: "test/debian-isar:latest"
    file: null
    args: []

registry:
  devices:
    - slug: qemu-arm64
      description: "QEMU ARM64"
      vendor: qemu
      soc_vendor: arm
      build:
        path: build/qemuarm64
        includes:
          - kas/qemuarm64.yml
    - slug: isar-board
      description: "Isar Board"
      vendor: acme
      soc_vendor: arm
      build:
        path: build/isar-board
        includes:
          - kas/isar/board.yml
  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS"
      yocto_version: "5.0"
      includes:
        - kas/scarthgap.yml
    - slug: isar-v0.11
      description: "Isar v0.11"
      environment: isar-env
      includes:
        - kas/isar/v0.11.yml
  features: []
  bsp:
    - name: qemu-scarthgap
      description: "QEMU Scarthgap"
      device: qemu-arm64
      release: scarthgap
      features: []
    - name: isar-v0.11-build
      description: "Isar v0.11 build"
      device: isar-board
      release: isar-v0.11
      features: []
"""


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def tmp_dir():
    """Provide a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def registry_file(tmp_dir):
    """Create a minimal registry YAML file in a temp directory."""
    registry_path = tmp_dir / "bsp-registry.yaml"
    registry_path.write_text(MINIMAL_REGISTRY_YAML)
    return registry_path


@pytest.fixture
def registry_with_env_file(tmp_dir):
    """Create a registry YAML file with environment variables."""
    registry_path = tmp_dir / "bsp-registry.yaml"
    registry_path.write_text(REGISTRY_WITH_ENV_YAML)
    return registry_path


@pytest.fixture
def registry_with_features_file(tmp_dir):
    """Create a registry YAML file with features and compatibility rules."""
    registry_path = tmp_dir / "bsp-registry.yml"
    registry_path.write_text(REGISTRY_WITH_FEATURES_YAML)
    return registry_path


@pytest.fixture
def registry_with_named_env_file(tmp_dir):
    """Create a registry YAML file with named environments."""
    registry_path = tmp_dir / "bsp-registry.yml"
    registry_path.write_text(REGISTRY_WITH_NAMED_ENVIRONMENTS_YAML)
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
