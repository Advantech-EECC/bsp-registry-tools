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
      includes:
        - test.yaml
  releases:
    - slug: test-release
      description: "Test Release"
      yocto_version: "5.0"
      includes:
        - test-base.yaml
  features: []
  bsp:
    - name: test-bsp
      description: "Test BSP"
      device: test-device
      release: test-release
      features: []
      build:
        container: "ubuntu-22.04"
        path: build/test
"""

REGISTRY_WITH_ENV_YAML = """
specification:
  version: "2.0"
environment:
  variables:
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
      includes:
        - kas/qemu/qemuarm64.yaml
    - slug: qemu-x86-64
      description: "QEMU x86-64"
      vendor: qemu
      soc_vendor: intel
      includes:
        - kas/qemu/qemux86-64.yaml
  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS (Scarthgap)"
      yocto_version: "5.0"
      includes:
        - kas/scarthgap.yaml
  features: []
  bsp:
    - name: qemu-arm64
      description: "QEMU ARM64 BSP"
      device: qemu-arm64
      release: scarthgap
      features: []
      build:
        container: "ubuntu-22.04"
        path: build/qemu-arm64
    - name: qemu-x86-64
      description: "QEMU x86-64 BSP"
      device: qemu-x86-64
      release: scarthgap
      features: []
      build:
        container: "ubuntu-22.04"
        path: build/qemu-x86-64
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
      includes:
        - kas/imx8.yaml
    - slug: qemu-arm64
      description: "QEMU ARM64"
      vendor: qemu
      soc_vendor: arm
      includes:
        - kas/qemuarm64.yaml
  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS"
      yocto_version: "5.0"
      includes:
        - kas/scarthgap.yaml
  features:
    - slug: ota
      description: "Over-the-Air Update support"
      includes:
        - kas/features/ota.yaml
      local_conf:
        - "DISTRO_FEATURES:append = ' swupdate'"
    - slug: secure-boot
      description: "Secure Boot support"
      compatibility:
        soc_vendor:
          - nxp
      includes:
        - kas/features/secure-boot.yaml
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
      build:
        container: "debian-bookworm"
        path: build/imx8-board
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
      includes:
        - kas/qemuarm64.yaml
    - slug: isar-board
      description: "Isar Board"
      vendor: acme
      soc_vendor: arm
      includes:
        - kas/isar/board.yaml
  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS"
      yocto_version: "5.0"
      includes:
        - kas/scarthgap.yaml
    - slug: isar-v0.11
      description: "Isar v0.11"
      environment: isar-env
      includes:
        - kas/isar/v0.11.yaml
  features: []
  bsp:
    - name: qemu-scarthgap
      description: "QEMU Scarthgap"
      device: qemu-arm64
      release: scarthgap
      features: []
      build:
        path: build/qemuarm64
    - name: isar-v0.11-build
      description: "Isar v0.11 build"
      device: isar-board
      release: isar-v0.11
      features: []
      build:
        path: build/isar-board
"""

REGISTRY_WITH_COPY_YAML = """
specification:
  version: "2.0"
containers:
  debian-bookworm:
    image: "test/debian:latest"
    file: null
    args: []
registry:
  devices:
    - slug: isar-qemu
      description: "QEMU Isar"
      vendor: qemu
      soc_vendor: arm
      includes:
        - kas/isar/qemu.yaml
      copy:
        - scripts/isar-runqemu.sh: build/isar-qemu/
  releases:
    - slug: isar-v0.11
      description: "Isar v0.11"
      includes:
        - kas/isar/v0.11.yaml
  features: []
  bsp:
    - name: isar-qemu-v0.11
      description: "Isar QEMU v0.11"
      device: isar-qemu
      release: isar-v0.11
      features: []
      build:
        container: "debian-bookworm"
        path: build/isar-qemu
"""

REGISTRY_WITH_NAMED_ENV_COPY_YAML = """
specification:
  version: "2.0"

environments:
  default:
    container: "debian-bookworm"
    variables:
      - name: "DL_DIR"
        value: "/tmp/downloads"
    copy:
      - scripts/env-setup.sh: build/
  isar-env:
    container: "debian-bookworm-isar"
    variables:
      - name: "DL_DIR"
        value: "/tmp/isar-downloads"
    copy:
      - isar/scripts/isar-runqemu.sh: build/isar/

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
      includes:
        - kas/qemuarm64.yaml
    - slug: isar-board
      description: "Isar Board"
      vendor: acme
      soc_vendor: arm
      includes:
        - kas/isar/board.yaml
  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS"
      yocto_version: "5.0"
      includes:
        - kas/scarthgap.yaml
    - slug: isar-v0.11
      description: "Isar v0.11"
      environment: isar-env
      includes:
        - kas/isar/v0.11.yaml
  features: []
  bsp:
    - name: qemu-scarthgap
      description: "QEMU Scarthgap"
      device: qemu-arm64
      release: scarthgap
      features: []
      build:
        path: build/qemuarm64
    - name: isar-v0.11-build
      description: "Isar v0.11 build"
      device: isar-board
      release: isar-v0.11
      features: []
      build:
        path: build/isar-board
"""

REGISTRY_WITH_GLOBAL_COPY_YAML = """
specification:
  version: "2.0"

environment:
  copy:
    - global/setup.sh: build/

containers:
  debian-bookworm:
    image: "test/debian:latest"
    file: null
    args: []

registry:
  devices:
    - slug: qemu-arm64
      description: "QEMU ARM64"
      vendor: qemu
      soc_vendor: arm
      includes:
        - kas/qemuarm64.yaml
      copy:
        - device/config.sh: build/
  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS"
      yocto_version: "5.0"
      includes:
        - kas/scarthgap.yaml
  features: []
  bsp:
    - name: qemu-scarthgap
      description: "QEMU Scarthgap"
      device: qemu-arm64
      release: scarthgap
      features: []
      build:
        container: "debian-bookworm"
        path: build/qemuarm64
"""

REGISTRY_WITH_RUNTIME_ARGS_YAML = """
specification:
  version: "2.0"
containers:
  isar-qemu-container:
    image: "ghcr.io/ilbers/isar:latest"
    file: null
    args: []
    runtime_args: "-p 2222:2222 --device=/dev/net/tun --cap-add=NET_ADMIN"
  plain-container:
    image: "test/plain:latest"
    file: null
    args: []
registry:
  devices:
    - slug: isar-qemu
      description: "QEMU Isar"
      vendor: qemu
      soc_vendor: arm
      includes:
        - kas/isar/qemu.yaml
    - slug: plain-device
      description: "Plain device"
      vendor: test
      soc_vendor: arm
      includes:
        - kas/plain.yaml
  releases:
    - slug: isar-v0.11
      description: "Isar v0.11"
      includes:
        - kas/isar/v0.11.yaml
  features: []
  bsp:
    - name: isar-qemu-v0.11
      description: "Isar QEMU v0.11"
      device: isar-qemu
      release: isar-v0.11
      features: []
      build:
        container: "isar-qemu-container"
        path: build/isar-qemu
    - name: plain-build
      description: "Plain build"
      device: plain-device
      release: isar-v0.11
      features: []
      build:
        container: "plain-container"
        path: build/plain
"""

REGISTRY_WITH_DISTRO_YAML = """
specification:
  version: "2.0"
containers:
  debian-bookworm:
    image: "test/debian:bookworm"
    file: null
    args: []
registry:
  distro:
    - slug: poky
      description: "Poky (Yocto Project reference distro)"
      vendor: yocto
      includes:
        - kas/poky/distro/poky.yaml
    - slug: isar
      description: "Isar (Siemens build system)"
      vendor: siemens
      includes:
        - kas/isar/isar.yaml
  devices:
    - slug: qemu-arm64
      description: "QEMU ARM64"
      vendor: qemu
      soc_vendor: arm
      includes:
        - kas/qemu/qemuarm64.yaml
  releases:
    - slug: scarthgap
      distro: poky
      description: "Yocto 5.0 LTS"
      yocto_version: "5.0"
      includes:
        - kas/poky/scarthgap.yaml
  features: []
  bsp:
    - name: poky-qemuarm64-scarthgap
      description: "Poky QEMU ARM64 Scarthgap"
      device: qemu-arm64
      release: scarthgap
      features: []
      build:
        container: "debian-bookworm"
        path: build/poky-qemuarm64-scarthgap
"""

REGISTRY_WITH_FRAMEWORKS_YAML = """
specification:
  version: "2.0"
containers:
  debian-bookworm:
    image: "test/debian:bookworm"
    file: null
    args: []
  isar-container:
    image: "test/isar:latest"
    file: null
    args: []
registry:
  frameworks:
    - slug: yocto
      description: "Yocto Project build system"
      vendor: "Yocto Project"
      includes:
        - kas/yocto/yocto.yaml
    - slug: isar
      description: "Isar build system"
      vendor: "Ilbers GmbH"
      includes:
        - kas/isar/isar.yaml
  distro:
    - slug: poky
      description: "Poky (Yocto Project reference distro)"
      vendor: yocto
      framework: yocto
      includes:
        - kas/poky/distro/poky.yaml
    - slug: isar
      description: "Isar (Siemens build system)"
      vendor: siemens
      framework: isar
      includes:
        - kas/isar/isar.yaml
  devices:
    - slug: qemu-arm64
      description: "QEMU ARM64"
      vendor: qemu
      soc_vendor: arm
      includes:
        - kas/qemu/qemuarm64.yaml
  releases:
    - slug: scarthgap
      distro: poky
      description: "Yocto 5.0 LTS"
      yocto_version: "5.0"
      includes:
        - kas/poky/scarthgap.yaml
    - slug: isar-v0.11
      distro: isar
      description: "Isar v0.11"
      includes:
        - kas/isar/v0.11.yaml
  features:
    - slug: yocto-only
      description: "Feature only for Yocto framework"
      compatible_with: [yocto]
      includes:
        - kas/features/yocto-only.yaml
    - slug: isar-only
      description: "Feature only for Isar framework"
      compatible_with: [isar]
      includes:
        - kas/features/isar-only.yaml
    - slug: poky-distro-only
      description: "Feature only for poky distro"
      compatible_with: [poky]
      includes:
        - kas/features/poky-only.yaml
    - slug: all-frameworks
      description: "Feature for all frameworks"
      includes:
        - kas/features/all.yaml
  bsp:
    - name: poky-qemuarm64-scarthgap
      description: "Poky QEMU ARM64 Scarthgap"
      device: qemu-arm64
      release: scarthgap
      features: []
      build:
        container: "debian-bookworm"
        path: build/poky-qemuarm64-scarthgap
    - name: isar-qemuarm64-v0.11
      description: "Isar QEMU ARM64 v0.11"
      device: qemu-arm64
      release: isar-v0.11
      features: []
      build:
        container: "isar-container"
        path: build/isar-qemuarm64-v0.11
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
    registry_path = tmp_dir / "bsp-registry.yaml"
    registry_path.write_text(REGISTRY_WITH_FEATURES_YAML)
    return registry_path


@pytest.fixture
def registry_with_named_env_file(tmp_dir):
    """Create a registry YAML file with named environments."""
    registry_path = tmp_dir / "bsp-registry.yaml"
    registry_path.write_text(REGISTRY_WITH_NAMED_ENVIRONMENTS_YAML)
    return registry_path


@pytest.fixture
def registry_with_copy_file(tmp_dir):
    """Create a registry YAML file with copy entries in device build config."""
    registry_path = tmp_dir / "bsp-registry.yaml"
    registry_path.write_text(REGISTRY_WITH_COPY_YAML)
    return registry_path


@pytest.fixture
def registry_with_named_env_copy_file(tmp_dir):
    """Create a registry YAML file with copy entries in named environments."""
    registry_path = tmp_dir / "bsp-registry.yaml"
    registry_path.write_text(REGISTRY_WITH_NAMED_ENV_COPY_YAML)
    return registry_path


@pytest.fixture
def registry_with_global_copy_file(tmp_dir):
    """Create a registry YAML file with a global (root-level) copy list."""
    registry_path = tmp_dir / "bsp-registry.yaml"
    registry_path.write_text(REGISTRY_WITH_GLOBAL_COPY_YAML)
    return registry_path


@pytest.fixture
def registry_with_runtime_args_file(tmp_dir):
    """Create a registry YAML file with runtime_args on a container definition."""
    registry_path = tmp_dir / "bsp-registry.yaml"
    registry_path.write_text(REGISTRY_WITH_RUNTIME_ARGS_YAML)
    return registry_path


@pytest.fixture
def registry_with_distro_file(tmp_dir):
    """Create a registry YAML file with distro definitions."""
    registry_path = tmp_dir / "bsp-registry.yaml"
    registry_path.write_text(REGISTRY_WITH_DISTRO_YAML)
    return registry_path


@pytest.fixture
def registry_with_frameworks_file(tmp_dir):
    """Create a registry YAML file with framework definitions and compatible_with features."""
    registry_path = tmp_dir / "bsp-registry.yaml"
    registry_path.write_text(REGISTRY_WITH_FRAMEWORKS_YAML)
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
    kas_path = tmp_dir / "test.yaml"
    kas_path.write_text(kas_content)
    return kas_path


@pytest.fixture
def kas_config_with_includes(tmp_dir):
    """Create KAS configuration files with includes."""
    base_content = """
header:
  version: 14
  includes:
    - include.yaml

machine: qemuarm64
"""
    include_content = """
header:
  version: 14

distro: poky
"""
    base_path = tmp_dir / "base.yaml"
    include_path = tmp_dir / "include.yaml"
    base_path.write_text(base_content)
    include_path.write_text(include_content)
    return base_path, include_path


REGISTRY_WITH_MULTI_RELEASE_BSP_YAML = """
specification:
  version: "2.0"
containers:
  debian-bookworm:
    image: "test/debian:bookworm"
    file: null
    args: []
registry:
  devices:
    - slug: qemu-arm64
      description: "QEMU ARM64"
      vendor: qemu
      soc_vendor: arm
      includes:
        - kas/qemu/qemuarm64.yaml
    - slug: qemu-x86-64
      description: "QEMU x86-64"
      vendor: qemu
      soc_vendor: intel
      includes:
        - kas/qemu/qemux86-64.yaml
  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS"
      yocto_version: "5.0"
      includes:
        - kas/scarthgap.yaml
    - slug: styhead
      description: "Yocto 5.1"
      yocto_version: "5.1"
      includes:
        - kas/styhead.yaml
    - slug: walnascar
      description: "Yocto 5.2"
      yocto_version: "5.2"
      includes:
        - kas/walnascar.yaml
  features: []
  bsp:
    # Multi-release preset: expands into qemu-arm64-scarthgap and qemu-arm64-styhead
    - name: qemu-arm64
      description: "QEMU ARM64 Yocto"
      device: qemu-arm64
      releases: [scarthgap, styhead]
      build:
        container: "debian-bookworm"
        path: build/should-be-ignored
    # Single-release preset (backward compat)
    - name: qemu-x86-64-walnascar
      description: "QEMU x86-64 Walnascar"
      device: qemu-x86-64
      release: walnascar
      build:
        container: "debian-bookworm"
        path: build/qemu-x86-64-walnascar
"""


@pytest.fixture
def registry_with_multi_release_bsp_file(tmp_dir):
    """Create a registry YAML file with a multi-release BSP preset."""
    registry_path = tmp_dir / "bsp-registry.yaml"
    registry_path.write_text(REGISTRY_WITH_MULTI_RELEASE_BSP_YAML)
    return registry_path


REGISTRY_WITH_VENDOR_OVERRIDES_YAML = """
specification:
  version: "2.0"
containers:
  debian-bookworm:
    image: "test/debian:bookworm"
    file: null
    args: []
registry:
  frameworks:
    - slug: yocto
      description: "Yocto Project build system"
      vendor: "Yocto Project"
      includes:
        - kas/yocto/yocto.yaml
  distro:
    - slug: poky
      description: "Poky (Yocto Project reference distro)"
      vendor: yocto
      framework: yocto
      includes:
        - kas/poky/distro/poky.yaml
    - slug: fsl-imx-xwayland
      description: "Freescale i.MX X Wayland (Yocto Project reference distro)"
      vendor: nxp
      framework: yocto
      includes:
        - vendors/nxp/distro/fsl-imx-xwayland.yaml
  devices:
    - slug: adv-imx8
      description: "Advantech i.MX8 Board"
      vendor: advantech
      soc_vendor: nxp
      includes:
        - kas/adv-imx8.yaml
    - slug: qemu-arm64
      description: "QEMU ARM64"
      vendor: qemu
      soc_vendor: arm
      includes:
        - kas/qemu/qemuarm64.yaml
  releases:
    - slug: scarthgap
      distro: poky
      description: "Yocto 5.0 LTS (Scarthgap)"
      yocto_version: "5.0"
      includes:
        - kas/poky/scarthgap.yaml
      vendor_overrides:
        - vendor: advantech
          distro: fsl-imx-xwayland
          includes:
            - kas/yocto/vendors/advantech/scarthgap.yaml
          releases:
            - slug: imx-6.6.53
              description: "Scarthgap for i.MX 6.6.53"
              includes:
                - kas/yocto/vendors/advantech/nxp/imx-6.6.53.yaml
            - slug: imx-6.12.0
              description: "Scarthgap for i.MX 6.12.0"
              includes:
                - kas/yocto/vendors/advantech/nxp/imx-6.12.0.yaml
    - slug: kirkstone
      distro: poky
      description: "Yocto 4.0 LTS (Kirkstone)"
      yocto_version: "4.0"
      includes:
        - kas/poky/kirkstone.yaml
      vendor_overrides:
        - vendor: advantech
          includes:
            - kas/yocto/vendors/advantech/kirkstone.yaml
          releases:
            - slug: imx-5.15.52
              description: "Kirkstone for i.MX 5.15.52"
              includes:
                - kas/yocto/vendors/advantech/nxp/imx-5.15.52.yaml
    - slug: generic-release
      distro: poky
      description: "Generic release without vendor overrides"
      yocto_version: "5.0"
      includes:
        - kas/poky/generic.yaml
  features: []
  bsp:
    - name: adv-imx8-scarthgap-imx6.6.53
      description: "Advantech i.MX8 Scarthgap (imx-6.6.53)"
      device: adv-imx8
      release: scarthgap
      vendor_release: imx-6.6.53
      features: []
      build:
        container: "debian-bookworm"
        path: build/adv-imx8-scarthgap-imx6.6.53
    - name: adv-imx8-scarthgap-imx6.12.0
      description: "Advantech i.MX8 Scarthgap (imx-6.12.0)"
      device: adv-imx8
      release: scarthgap
      vendor_release: imx-6.12.0
      features: []
      build:
        container: "debian-bookworm"
        path: build/adv-imx8-scarthgap-imx6.12.0
    - name: adv-imx8-scarthgap-imx-6.6.53-autopath
      description: "Advantech i.MX8 Scarthgap (imx-6.6.53) with auto-composed path"
      device: adv-imx8
      release: scarthgap
      vendor_release: imx-6.6.53
      features: []
      build:
        container: "debian-bookworm"
    - name: qemu-arm64-scarthgap
      description: "QEMU ARM64 Scarthgap BSP"
      device: qemu-arm64
      release: scarthgap
      features: []
      build:
        container: "debian-bookworm"
        path: build/qemu-arm64-scarthgap
"""


@pytest.fixture
def registry_with_vendor_overrides_file(tmp_dir):
    """Create a registry YAML file with vendor_overrides (with sub-releases) on releases."""
    registry_path = tmp_dir / "bsp-registry.yaml"
    registry_path.write_text(REGISTRY_WITH_VENDOR_OVERRIDES_YAML)
    return registry_path


REGISTRY_WITH_VENDORS_YAML = """
specification:
  version: "2.0"
containers:
  debian-bookworm:
    image: "test/debian:bookworm"
    file: null
    args: []
registry:
  vendors:
    - slug: advantech
      name: "Advantech"
      description: "Advantech Corporation, a global leader in industrial computing and IoT solutions."
      website: "https://www.advantech.com/"
      includes:
        - vendors/advantech/nxp/advantech.yml
    - slug: myvendor
      name: "My Vendor"
      description: "Another vendor"
      website: "https://example.com/"
      includes:
        - vendors/myvendor/base.yml
  devices:
    - slug: adv-imx8
      description: "Advantech i.MX8 Board"
      vendor: advantech
      soc_vendor: nxp
      includes:
        - kas/adv-imx8.yaml
    - slug: qemu-arm64
      description: "QEMU ARM64"
      vendor: qemu
      soc_vendor: arm
      includes:
        - kas/qemu/qemuarm64.yaml
  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS (Scarthgap)"
      yocto_version: "5.0"
      includes:
        - kas/scarthgap.yaml
  features: []
  bsp:
    - name: adv-imx8-scarthgap
      description: "Advantech i.MX8 Scarthgap"
      device: adv-imx8
      release: scarthgap
      features: []
      build:
        container: "debian-bookworm"
        path: build/adv-imx8-scarthgap
    - name: qemu-arm64-scarthgap
      description: "QEMU ARM64 Scarthgap BSP"
      device: qemu-arm64
      release: scarthgap
      features: []
      build:
        container: "debian-bookworm"
        path: build/qemu-arm64-scarthgap
"""


@pytest.fixture
def registry_with_vendors_file(tmp_dir):
    """Create a registry YAML file with top-level vendor definitions."""
    registry_path = tmp_dir / "bsp-registry.yaml"
    registry_path.write_text(REGISTRY_WITH_VENDORS_YAML)
    return registry_path


REGISTRY_WITH_VENDOR_OVERRIDE_SLUG_YAML = """
specification:
  version: "2.0"
containers:
  debian-bookworm:
    image: "test/debian:bookworm"
    file: null
    args: []
registry:
  frameworks:
    - slug: yocto
      description: "Yocto Project build system"
      vendor: "Yocto Project"
      includes:
        - kas/yocto/yocto.yaml
  distro:
    - slug: poky
      description: "Poky (Yocto Project reference distro)"
      vendor: yocto
      framework: yocto
      includes:
        - kas/poky/distro/poky.yaml
    - slug: poky-imx
      description: "Poky with i.MX BSP layers"
      vendor: nxp
      framework: yocto
      includes:
        - kas/poky/distro/poky.yaml
        - kas/poky/distro/poky-imx.yaml
    - slug: fsl-imx-xwayland
      description: "Freescale i.MX X Wayland (Yocto Project reference distro)"
      vendor: nxp
      framework: yocto
      includes:
        - vendors/nxp/distro/fsl-imx-xwayland.yaml
  devices:
    - slug: adv-imx8
      description: "Advantech i.MX8 Board"
      vendor: advantech
      soc_vendor: nxp
      includes:
        - kas/adv-imx8.yaml
    - slug: adv-imx8-europe
      description: "Advantech Europe i.MX8 Board"
      vendor: advantech-europe
      soc_vendor: nxp
      includes:
        - kas/adv-imx8-europe.yaml
    - slug: qemu-arm64
      description: "QEMU ARM64"
      vendor: qemu
      soc_vendor: arm
      includes:
        - kas/qemu/qemuarm64.yaml
  releases:
    - slug: scarthgap
      distro: poky
      description: "Yocto 5.0 LTS (Scarthgap)"
      yocto_version: "5.0"
      includes:
        - kas/poky/scarthgap.yaml
      vendor_overrides:
        - slug: imx-6.6.23-2.0.0
          vendor: advantech-europe
          distro: poky-imx
          includes:
            - kas/yocto/vendors/advantech-europe/nxp/imx-6.6.23-2.0.0-scarthgap.yaml
        - slug: imx-6.6.36-2.1.0
          vendor: advantech-europe
          includes:
            - kas/yocto/vendors/advantech-europe/nxp/imx-6.6.36-2.1.0-scarthgap.yaml
        - slug: imx-xwayland-6.6.52
          vendor: advantech-europe
          distro: fsl-imx-xwayland
          includes:
            - kas/yocto/vendors/advantech-europe/nxp/imx-xwayland-6.6.52-scarthgap.yaml
        - vendor: advantech
          includes:
            - kas/yocto/vendors/advantech/nxp/scarthgap.yaml
  features:
    - slug: xwayland-only
      description: "Feature only for fsl-imx-xwayland distro"
      compatible_with: [fsl-imx-xwayland]
      includes:
        - kas/features/xwayland-only.yaml
    - slug: yocto-only
      description: "Feature compatible with any Yocto-based distro"
      compatible_with: [yocto]
      includes:
        - kas/features/yocto-only.yaml
  bsp:
    - name: adv-imx8-europe-scarthgap-imx-6.6.23
      description: "Advantech Europe i.MX8 Scarthgap (imx-6.6.23)"
      device: adv-imx8-europe
      release: scarthgap
      override: imx-6.6.23-2.0.0
      features: []
      build:
        container: "debian-bookworm"
        path: build/adv-imx8-europe-scarthgap-imx-6.6.23
    - name: adv-imx8-europe-scarthgap-imx-6.6.36
      description: "Advantech Europe i.MX8 Scarthgap (imx-6.6.36)"
      device: adv-imx8-europe
      release: scarthgap
      override: imx-6.6.36-2.1.0
      features: []
      build:
        container: "debian-bookworm"
        path: build/adv-imx8-europe-scarthgap-imx-6.6.36
    - name: adv-imx8-europe-scarthgap-xwayland
      description: "Advantech Europe i.MX8 Scarthgap (fsl-imx-xwayland distro)"
      device: adv-imx8-europe
      release: scarthgap
      override: imx-xwayland-6.6.52
      features: []
      build:
        container: "debian-bookworm"
    - name: adv-imx8-scarthgap
      description: "Advantech i.MX8 Scarthgap (no override)"
      device: adv-imx8
      release: scarthgap
      features: []
      build:
        container: "debian-bookworm"
        path: build/adv-imx8-scarthgap
"""


@pytest.fixture
def registry_with_vendor_override_slug_file(tmp_dir):
    """Create a registry YAML with vendor_overrides using slug and distro override."""
    registry_path = tmp_dir / "bsp-registry.yaml"
    registry_path.write_text(REGISTRY_WITH_VENDOR_OVERRIDE_SLUG_YAML)
    return registry_path
