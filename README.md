# bsp-registry-tools

[![Tests](https://github.com/Advantech-EECC/bsp-registry-tools/actions/workflows/tests.yml/badge.svg)](https://github.com/Advantech-EECC/bsp-registry-tools/actions/workflows/tests.yml)
[![PyPI version](https://badge.fury.io/py/bsp-registry-tools.svg)](https://badge.fury.io/py/bsp-registry-tools)
[![Python Versions](https://img.shields.io/pypi/pyversions/bsp-registry-tools.svg)](https://pypi.org/project/bsp-registry-tools/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Python tools to build, fetch, and work with Yocto-based BSPs using the [KAS](https://kas.readthedocs.io/) build system.

## Overview

`bsp-registry-tools` provides a command-line interface and Python API for managing Advantech Board Support Packages (BSPs). It uses YAML-based registry files to define BSP configurations, build environments, and Docker containers, making reproducible Yocto builds straightforward.

### Key Features

- 📋 **BSP registry management** via YAML configuration files
- 🐳 **Docker container support** for reproducible build environments
- 🔧 **KAS integration** for Yocto-based builds (`kas`, `kas-container`)
- 🖥️ **Interactive shell** access to build environments
- 🔄 **Environment variable expansion** (`$ENV{VAR}` syntax)
- 📤 **Configuration export** for sharing and archiving build configs
- ✅ **Comprehensive validation** of configurations before building

## Installation

### From PyPI

```bash
pip install bsp-registry-tools
```

### From Source

```bash
git clone https://github.com/Advantech-EECC/bsp-registry-tools.git
cd bsp-registry-tools
pip install .
```

### Dependencies

- Python 3.8+
- [PyYAML](https://pyyaml.org/) >= 6.0
- [dacite](https://github.com/konradhalas/dacite) >= 1.6.0
- [kas](https://kas.readthedocs.io/) >= 4.7
- [colorama](https://github.com/tartley/colorama) >= 0.4.6

## Quick Start

### 1. Create a BSP Registry File

Create a `bsp-registry.yml` file (see [examples/bsp-registry.yml](examples/bsp-registry.yml)):

```yaml
specification:
  version: "1.0"

environment:
  - name: "DL_DIR"
    value: "$ENV{HOME}/yocto-cache/downloads"
  - name: "SSTATE_DIR"
    value: "$ENV{HOME}/yocto-cache/sstate"

containers:
  - ubuntu-22.04:
      image: "ghcr.io/siemens/kas/kas:4.7"
      file: Dockerfile.ubuntu
      args:
        - name: "DISTRO"
          value: "ubuntu:22.04"

registry:
  bsp:
    - name: poky-qemuarm64-scarthgap
      description: "Poky QEMU ARM64 Scarthgap (Yocto 5.0 LTS)"
      build:
        path: build/qemu-arm64-scarthgap
        environment:
          container: "ubuntu-22.04"
        configuration:
          - kas/scarthgap.yml
          - kas/qemu/qemuarm64.yml
```

### 2. List Available BSPs

```bash
bsp list
```

```
- poky-qemuarm64-scarthgap: Poky QEMU ARM64 Scarthgap (Yocto 5.0 LTS)
```

### 3. Build a BSP

```bash
bsp build poky-qemuarm64-scarthgap
```

### 4. Enter Interactive Shell

```bash
bsp shell poky-qemuarm64-scarthgap
```

## CLI Reference

```
usage: bsp [-h] [--verbose] [--registry REGISTRY] [--no-color]
           {build,list,containers,export,shell} ...
```

### Global Options

| Option | Description |
|--------|-------------|
| `--verbose`, `-v` | Enable verbose/debug output |
| `--registry REGISTRY`, `-r REGISTRY` | Path to BSP registry file (default: `bsp-registry.yml`) |
| `--no-color` | Disable colored output |

### Commands

#### `list` — List available BSPs

```bash
bsp list
bsp --registry my-registry.yml list
```

#### `containers` — List available container definitions

```bash
bsp containers
```

#### `build` — Build a BSP image

```bash
bsp build <bsp_name> [--clean] [--checkout]
```

| Option | Description |
|--------|-------------|
| `--clean` | Clean build directory before building |
| `--checkout` | Validate configuration and checkout repos without building |

**Examples:**

```bash
# Full build
bsp build poky-qemuarm64-scarthgap

# Checkout/validate only (fast, no build)
bsp build poky-qemuarm64-scarthgap --checkout
```

#### `shell` — Interactive shell in build environment

```bash
bsp shell <bsp_name> [--command COMMAND]
```

| Option | Description |
|--------|-------------|
| `--command COMMAND`, `-c COMMAND` | Execute a specific command instead of starting interactive shell |

**Examples:**

```bash
# Interactive shell
bsp shell poky-qemuarm64-scarthgap

# Execute single command
bsp shell poky-qemuarm64-scarthgap --command "bitbake core-image-minimal"
```

#### `export` — Export BSP configuration

```bash
bsp export <bsp_name> [--output OUTPUT]
```

| Option | Description |
|--------|-------------|
| `--output OUTPUT`, `-o OUTPUT` | Output file path (default: stdout) |

**Examples:**

```bash
# Print to stdout
bsp export poky-qemuarm64-scarthgap

# Save to file
bsp export poky-qemuarm64-scarthgap --output exported-config.yml
```

## Registry Configuration Reference

The BSP registry is a YAML file with the following top-level sections:

### `specification`

```yaml
specification:
  version: "1.0"
```

### `environment`

Global environment variables applied to all builds. Supports `$ENV{VAR_NAME}` expansion to reference system environment variables.

```yaml
environment:
  - name: "GITCONFIG_FILE"
    value: "$ENV{HOME}/.gitconfig"
  - name: "DL_DIR"
    value: "$ENV{HOME}/yocto-cache/downloads"
  - name: "SSTATE_DIR"
    value: "$ENV{HOME}/yocto-cache/sstate"
```

**Supported variables:**

| Variable | Description |
|----------|-------------|
| `DL_DIR` | Yocto downloads cache directory |
| `SSTATE_DIR` | Yocto shared state cache directory |
| `GITCONFIG_FILE` | Git configuration file path |

### `containers`

Docker container definitions for build environments:

```yaml
containers:
  - ubuntu-22.04:
      image: "my-registry/ubuntu-22.04/kas:4.7"
      file: Dockerfile.ubuntu
      args:
        - name: "DISTRO"
          value: "ubuntu:22.04"
        - name: "KAS_VERSION"
          value: "4.7"
  - ubuntu-20.04:
      image: "my-registry/ubuntu-20.04/kas:4.7"
      file: Dockerfile.ubuntu
      args:
        - name: "DISTRO"
          value: "ubuntu:20.04"
```

### `registry.bsp`

List of BSP definitions:

```yaml
registry:
  bsp:
    - name: my-bsp-name           # Unique identifier
      description: "My BSP"       # Human-readable description
      os:                         # Optional OS information
        name: linux
        build_system: yocto
        version: "5.0"
      build:
        path: build/my-bsp        # Build output directory
        environment:
          container: "ubuntu-22.04"   # Reference to containers section
          # OR use direct Docker configuration:
          # docker:
          #   image: "my-image:latest"
        configuration:            # KAS configuration files (in order)
          - kas/scarthgap.yml
          - kas/qemu/qemuarm64.yml
```

## KAS Configuration Files

KAS configuration files define Yocto layer repositories, machine settings, and build targets. See the [examples/kas/](examples/kas/) directory for reference configurations.

### QEMU Example Configurations

The `examples/` directory contains ready-to-use KAS configurations for QEMU targets:

| File | Description |
|------|-------------|
| `examples/kas/scarthgap.yml` | Yocto Scarthgap (5.0 LTS) base configuration |
| `examples/kas/styhead.yml` | Yocto Styhead (5.1) base configuration |
| `examples/kas/qemu/qemuarm64.yml` | QEMU ARM64 machine configuration |
| `examples/kas/qemu/qemux86-64.yml` | QEMU x86-64 machine configuration |
| `examples/kas/qemu/qemuarm.yml` | QEMU ARM (32-bit) machine configuration |

### KAS File Structure

```yaml
header:
  version: 14
  includes:            # Optional: include other KAS files
    - base.yml

distro: poky
machine: qemuarm64

target:
  - core-image-minimal

repos:
  poky:
    url: "https://git.yoctoproject.org/poky"
    commit: "abc123..."
    path: "layers/poky"
    layers:
      meta:
      meta-poky:

local_conf_header:
  my_config: |
    DISTRO_FEATURES += "x11"
```

## Python API

You can also use `bsp-registry-tools` as a Python library:

```python
from bsp import BspManager, EnvironmentManager, KasManager

# Load and manage BSP registry
manager = BspManager("bsp-registry.yml")
manager.initialize()

# List BSPs programmatically
for bsp in manager.model.registry.bsp:
    print(f"{bsp.name}: {bsp.description}")

# Get a specific BSP
bsp = manager.get_bsp_by_name("poky-qemuarm64-scarthgap")

# Environment variable management with $ENV{} expansion
from bsp import EnvironmentVariable
env_vars = [
    EnvironmentVariable(name="DL_DIR", value="$ENV{HOME}/downloads"),
]
env_manager = EnvironmentManager(env_vars)
print(env_manager.get_value("DL_DIR"))  # Expanded path

# Use KasManager directly
kas = KasManager(
    kas_files=["kas/scarthgap.yml", "kas/qemu/qemuarm64.yml"],
    build_dir="build/my-bsp",
    use_container=False,
)
kas.validate_kas_files()
```

## Development

### Setup Development Environment

```bash
git clone https://github.com/Advantech-EECC/bsp-registry-tools.git
cd bsp-registry-tools
pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=bsp --cov-report=term-missing

# Run specific test class
pytest tests/test_bsp.py::TestEnvironmentManager -v
```

### Project Structure

```
bsp-registry-tools/
├── bsp.py                    # Main module
├── pyproject.toml            # Package configuration
├── README.md                 # This file
├── LICENSE                   # MIT License
├── tests/
│   └── test_bsp.py           # Comprehensive pytest tests
├── examples/
│   ├── bsp-registry.yml      # Sample BSP registry for QEMU targets
│   └── kas/
│       ├── scarthgap.yml     # Yocto Scarthgap base config
│       ├── styhead.yml       # Yocto Styhead base config
│       └── qemu/
│           ├── qemuarm64.yml  # QEMU ARM64 machine config
│           ├── qemux86-64.yml # QEMU x86-64 machine config
│           └── qemuarm.yml    # QEMU ARM machine config
└── .github/
    └── workflows/
        ├── tests.yml         # CI: run tests on push/PR
        └── publish.yml       # CD: publish to PyPI on release
```

## Publishing to PyPI

This repository uses GitHub Actions for automated publishing.

### Setup

1. Create PyPI and TestPyPI accounts and configure [Trusted Publishers](https://docs.pypi.org/trusted-publishers/):
   - **PyPI**: Add GitHub Actions publisher for `Advantech-EECC/bsp-registry-tools`
   - **TestPyPI**: Same configuration on test.pypi.org

2. Create GitHub Environments named `pypi` and `testpypi` in your repository settings.

### Publish Workflow

**Automatic (on GitHub Release):**
- Creating a non-prerelease GitHub Release automatically publishes to both TestPyPI and PyPI.
- Creating a prerelease publishes to TestPyPI only.

**Manual:**
```
GitHub → Actions → "Publish to PyPI" → Run workflow → Select environment
```

### Build Locally

```bash
pip install build
python -m build
# Artifacts are in dist/
```

## Architecture

### Classes

| Class | Description |
|-------|-------------|
| `BspManager` | Main coordinator for BSP operations |
| `KasManager` | Handles KAS build system operations |
| `EnvironmentManager` | Manages build environment variables with `$ENV{}` expansion |
| `PathResolver` | Utility for path resolution and validation |

### Data Classes

| Class | Description |
|-------|-------------|
| `RegistryRoot` | Root registry container |
| `Registry` | Contains list of BSP definitions |
| `BSP` | Single BSP definition |
| `BuildSetup` | Build configuration (path, environment, KAS files) |
| `BuildEnvironment` | Docker/container settings |
| `Docker` | Docker image and build arg configuration |
| `EnvironmentVariable` | Name/value pair with `$ENV{}` expansion support |

### Exceptions

| Exception | Description |
|-----------|-------------|
| `ScriptError` | Base exception for all script errors |
| `ConfigurationError` | Configuration file issues |
| `BuildError` | Build process failures |
| `DockerError` | Docker operation failures |
| `KasError` | KAS operation failures |

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request on [GitHub](https://github.com/Advantech-EECC/bsp-registry-tools).
