"""
Shared pytest fixtures and YAML constants for bsp-registry-tools tests.
"""

import tempfile
import pytest
from pathlib import Path


# =============================================================================
# Shared YAML test data
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
