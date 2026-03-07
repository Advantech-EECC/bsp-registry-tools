# bsp-registry-tools

Python tools to build, fetch, and work with Yocto-based BSPs using the [KAS](https://kas.readthedocs.io/) build system.

## Overview

`bsp-registry-tools` provides a command-line interface and Python API for managing Advantech Board Support Packages (BSPs). It uses YAML-based registry files (schema **v2.0**) to define devices, releases, features, and Docker containers, making reproducible Yocto builds straightforward.

> **Schema version:** This release uses **registry schema v2.0**.
> The older v1.0 schema is no longer supported.
> See [docs/migration-v1-to-v2.md](docs/migration-v1-to-v2.md) to upgrade.

### Key Features

- 📋 **BSP registry management** via YAML configuration files (v2.0 schema)
- 🌐 **Automatic remote registry fetching** — clone/update a remote registry with no manual setup
- 🧩 **Device / release / feature decomposition** with compatibility checking
- 🐳 **Docker container support** for reproducible build environments
- 🔧 **KAS integration** for Yocto-based builds (`kas`, `kas-container`)
- 🖥️ **Interactive shell** access to build environments
- 🔄 **Environment variable expansion** (`$ENV{VAR}` syntax)
- 📤 **Configuration export** for sharing and archiving build configs
- ✅ **Comprehensive validation** of configurations before building

## Documentation

| Document | Description |
|----------|-------------|
| [docs/registry-v2.md](docs/registry-v2.md) | Full v2.0 schema reference with examples |
| [docs/registry-v1.md](docs/registry-v1.md) | Historical v1.0 schema reference |
| [docs/migration-v1-to-v2.md](docs/migration-v1-to-v2.md) | Migration guide: v1.0 → v2.0 |

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

### Zero-Config Usage (Remote Registry)

If you have no local registry file, `bsp` automatically clones the default
[Advantech BSP registry](https://github.com/Advantech-EECC/bsp-registry) into
`~/.cache/bsp/registry` and keeps it up-to-date on every run:

```bash
# First run: clones the registry, then lists BSPs
bsp list

# Subsequent runs: pulls latest changes, then lists BSPs
bsp list

# Skip the network update (useful offline or in CI)
bsp --no-update list

# Use a different remote or branch
bsp --remote https://github.com/my-org/bsp-registry.git --branch dev list
```

### Manual Registry Usage

### 1. Create a BSP Registry File

Create a `bsp-registry.yaml` file (see [examples/bsp-registry.yaml](examples/bsp-registry.yaml) and [docs/registry-v2.md](docs/registry-v2.md)):

```yaml
specification:
  version: "2.0"

environment:
  - name: "DL_DIR"
    value: "$ENV{HOME}/yocto-cache/downloads"
  - name: "SSTATE_DIR"
    value: "$ENV{HOME}/yocto-cache/sstate"

containers:
  debian-bookworm:
    image: "bsp/registry/debian/kas:5.1"
    file: Dockerfile
    args:
      - name: "DISTRO"
        value: "debian-bookworm"

registry:
  devices:
    - slug: qemuarm64
      description: "QEMU ARM64 (emulated)"
      vendor: qemu
      soc_vendor: arm
      build:
        container: "debian-bookworm"
        path: build/qemu-arm64
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
    - name: poky-qemuarm64-scarthgap
      description: "Poky QEMU ARM64 Scarthgap (Yocto 5.0 LTS)"
      device: qemuarm64
      release: scarthgap
      features: []
```

### 2. List Available BSPs and Components

```bash
# With an explicit registry file
bsp --registry bsp-registry.yaml list

# Or simply if bsp-registry.yaml is in the current directory

# List BSP presets
bsp list

# List all devices
bsp list devices

# List all releases
bsp list releases

# List all features
bsp list features
```

### 3. Build a BSP

```bash
# Build by preset name
bsp build poky-qemuarm64-scarthgap

# Build by specifying components directly (no preset required)
bsp build --device qemuarm64 --release scarthgap

# Build with an optional feature enabled
bsp build --device qemuarm64 --release scarthgap --feature ota
```

### 4. Enter Interactive Shell

```bash
bsp shell poky-qemuarm64-scarthgap

# Or by components
bsp shell --device qemuarm64 --release scarthgap
```

## CLI Reference

```
usage: bsp [-h] [--verbose] [--registry REGISTRY] [--no-color]
           [--remote REMOTE] [--branch BRANCH] [--update | --no-update]
           [--local]
           {build,list,containers,export,shell} ...

Advantech Board Support Package Registry

positional arguments:
  {build,list,containers,export,shell}
                        Command to execute
    build               Build an image for BSP
    list                List available BSPs and components
    containers          List available containers
    export              Export BSP configuration
    shell               Enter interactive shell for BSP

options:
  -h, --help            show this help message and exit
  --verbose, -v         Verbose output
  --registry REGISTRY, -r REGISTRY
                        BSP Registry file (local path; skips remote fetch)
  --no-color            Disable colored output
  --remote REMOTE       Remote registry git URL
                        (default: https://github.com/Advantech-EECC/bsp-registry.git)
  --branch BRANCH       Remote registry branch (default: main)
  --update              Update the cached registry clone before use (default)
  --no-update           Skip updating the cached registry clone
  --local               Force local registry lookup only (do not use remote)
```

### Registry Resolution Priority

The tool determines which registry file to use in the following order:

1. **`--registry <path>`** — explicit local file, remote fetch is skipped entirely.
2. **`--local`** — use `./bsp-registry.yaml` in the current directory; no network access.
3. **`bsp-registry.yaml` exists in the current directory** — backward-compatible auto-detect.
4. **Otherwise** — clone/update the remote registry into `~/.cache/bsp/registry` via `RegistryFetcher`.

### Global Options

| Option | Description |
|--------|-------------|
| `--verbose`, `-v` | Enable verbose/debug output |
| `--registry REGISTRY`, `-r REGISTRY` | Path to BSP registry file (local override) |
| `--no-color` | Disable colored output |
| `--remote REMOTE` | Remote registry git URL (default: Advantech BSP registry) |
| `--branch BRANCH` | Remote registry branch (default: `main`) |
| `--update` / `--no-update` | Update cached registry clone before use (default: update) |
| `--local` | Force local lookup; never contact remote |

### Commands

#### `list` — List available BSPs and components

```bash
bsp list                      # List BSP presets
bsp list devices              # List hardware devices
bsp list releases             # List Yocto/Isar releases
bsp list releases --device d  # Filter releases by device
bsp list features             # List optional features
```

#### `containers` — List available container definitions

```bash
bsp containers
```

#### `build` — Build a BSP image

```bash
# Build by preset name
bsp build <preset_name> [--clean] [--checkout]

# Build by components
bsp build --device <device> --release <release> [--feature <f> ...] [--checkout]
```

| Option | Description |
|--------|-------------|
| `--clean` | Clean build directory before building |
| `--checkout` | Validate configuration and checkout repos without building |
| `--device`, `-d` | Device slug |
| `--release` | Release slug |
| `--feature`, `-f` | Feature slug (repeatable) |

**Examples:**

```bash
# Build a named preset
bsp build poky-qemuarm64-scarthgap

# Build by components (no preset needed)
bsp build --device qemuarm64 --release scarthgap

# Build with features
bsp build --device imx8mp-adv --release scarthgap --feature ota --feature secure-boot

# Checkout/validate only (fast, no build)
bsp build poky-qemuarm64-scarthgap --checkout
```

#### `shell` — Interactive shell in build environment

```bash
bsp shell <preset_name> [--command COMMAND]
bsp shell --device <device> --release <release> [--feature <f> ...] [--command COMMAND]
```

| Option | Description |
|--------|-------------|
| `--command COMMAND`, `-c COMMAND` | Execute a specific command instead of starting interactive shell |

**Examples:**

```bash
# Interactive shell via preset
bsp shell poky-qemuarm64-scarthgap

# Interactive shell by components
bsp shell --device qemuarm64 --release scarthgap

# Execute single command
bsp shell poky-qemuarm64-scarthgap --command "bitbake core-image-minimal"
```

#### `export` — Export BSP configuration

```bash
bsp export <preset_name> [--output OUTPUT]
bsp export --device <device> --release <release> [--feature <f> ...] [--output OUTPUT]
```

| Option | Description |
|--------|-------------|
| `--output OUTPUT`, `-o OUTPUT` | Output file path (default: stdout) |

**Examples:**

```bash
# Print to stdout
bsp export poky-qemuarm64-scarthgap

# Save to file
bsp export poky-qemuarm64-scarthgap --output exported-config.yaml

# Export by components
bsp export --device qemuarm64 --release scarthgap --output /tmp/config.yaml
```

## Registry Configuration Reference

See **[docs/registry-v2.md](docs/registry-v2.md)** for the full schema reference.

The v2.0 registry has the following top-level sections:

### `specification`

```yaml
specification:
  version: "2.0"   # required; tool exits on any other value
```

### `environment`

Global environment variables applied to all builds.  Supports `$ENV{VAR_NAME}` expansion.

```yaml
environment:
  - name: "DL_DIR"
    value: "$ENV{HOME}/yocto-cache/downloads"
  - name: "SSTATE_DIR"
    value: "$ENV{HOME}/yocto-cache/sstate"
```

### `containers`

Docker container definitions (dict format in v2.0):

```yaml
containers:
  debian-bookworm:
    image: "my-registry/debian/kas:5.1"
    file: Dockerfile
    args:
      - name: "KAS_VERSION"
        value: "5.1"
```

### `registry.devices`

Hardware board definitions:

```yaml
registry:
  devices:
    - slug: my-board
      description: "My Board"
      vendor: acme
      soc_vendor: nxp
      soc_family: imx8          # optional
      build:
        container: "debian-bookworm"
        path: build/my-board
        includes:
          - kas/boards/my-board.yaml
        local_conf: []           # optional extra local.conf lines
```

### `registry.releases`

Yocto/Isar release definitions:

```yaml
registry:
  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS"
      yocto_version: "5.0"
      includes:
        - kas/scarthgap.yaml
      vendor_includes:           # optional vendor-specific overrides
        - vendor: acme
          includes:
            - kas/acme/scarthgap-vendor.yaml
```

### `registry.features`

Optional feature definitions with compatibility rules:

```yaml
registry:
  features:
    - slug: ota
      description: "OTA Update via SWUpdate"
      includes:
        - kas/features/ota.yaml
      local_conf:
        - "DISTRO_FEATURES:append = ' swupdate'"

    - slug: secure-boot
      description: "Secure Boot (NXP)"
      compatibility:
        soc_vendor: [nxp]        # empty list = all devices
      includes:
        - kas/features/secure-boot.yaml
      env:
        - name: "SIGNING_KEY"
          value: "$ENV{SIGNING_KEY}"
```

### `registry.bsp` (optional presets)

Named shortcuts for device + release + features:

```yaml
registry:
  bsp:
    - name: my-board-scarthgap
      description: "My Board Scarthgap"
      device: my-board
      release: scarthgap
      features: []
```

## KAS Configuration Files

KAS configuration files define Yocto layer repositories, machine settings, and build targets. See the [examples/kas/](examples/kas/) directory for reference configurations.

### QEMU Example Configurations

| File | Description |
|------|-------------|
| `examples/kas/scarthgap.yaml` | Yocto Scarthgap (5.0 LTS) base configuration |
| `examples/kas/styhead.yaml` | Yocto Styhead (5.1) base configuration |
| `examples/kas/qemu/qemuarm64.yaml` | QEMU ARM64 machine configuration |
| `examples/kas/qemu/qemux86-64.yaml` | QEMU x86-64 machine configuration |
| `examples/kas/qemu/qemuarm.yaml` | QEMU ARM (32-bit) machine configuration |

## Python API

You can also use `bsp-registry-tools` as a Python library:

```python
from bsp import BspManager, V2Resolver, EnvironmentManager, KasManager, RegistryFetcher

# Fetch registry from remote (clone on first call, pull on subsequent)
fetcher = RegistryFetcher()
registry_path = fetcher.fetch_registry(
    repo_url="https://github.com/Advantech-EECC/bsp-registry.git",
    branch="main",
    update=True,
)

# Load and manage BSP registry
manager = BspManager(str(registry_path))
manager.initialize()

# List devices programmatically
for device in manager.model.registry.devices:
    print(f"{device.slug}: {device.description}")

# Resolve a preset
resolved, preset = manager.resolver.resolve_preset("poky-qemuarm64-scarthgap")
print(f"Build path: {resolved.build_path}")
print(f"KAS files: {resolved.kas_files}")

# Resolve components directly (no preset needed)
resolved = manager.resolver.resolve(
    device_slug="qemuarm64",
    release_slug="scarthgap",
    feature_slugs=["ota"],
)

# Environment variable management with $ENV{} expansion
from bsp import EnvironmentVariable
env_vars = [
    EnvironmentVariable(name="DL_DIR", value="$ENV{HOME}/downloads"),
]
env_manager = EnvironmentManager(env_vars)
print(env_manager.get_value("DL_DIR"))  # Expanded path
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
```

### Project Structure

```
│   ├── bsp-registry.yaml      # Sample BSP registry for QEMU targets
│   └── kas/
│       ├── scarthgap.yaml     # Yocto Scarthgap base config
│       ├── styhead.yaml       # Yocto Styhead base config
│       └── qemu/
│           ├── qemuarm64.yaml  # QEMU ARM64 machine config
│           ├── qemux86-64.yaml # QEMU x86-64 machine config
│           └── qemuarm.yaml    # QEMU ARM machine config
└── .github/
    └── workflows/
        ├── tests.yaml         # CI: run tests on push/PR
        └── publish.yaml       # CD: publish to PyPI on release
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
=======
│   ├── bsp-registry.yaml  # Sample v2.0 registry for QEMU targets
│   └── kas/              # KAS configuration files
├── pyproject.toml
└── README.md
```

## Architecture

### Classes

| Class | Description |
|-------|-------------|
| `BspManager` | Main coordinator for BSP operations |
| `V2Resolver` | Resolves device + release + features into a build config |
| `KasManager` | Handles KAS build system operations |
| `EnvironmentManager` | Manages build environment variables with `$ENV{}` expansion |
| `PathResolver` | Utility for path resolution and validation |
| `RegistryFetcher` | Clones/updates a remote git-hosted BSP registry to a local cache |

### v2.0 Data Classes

| Class | Description |
|-------|-------------|
| `RegistryRoot` | Root registry container |
| `Registry` | Contains devices, releases, features, and presets |
| `Device` | Hardware board definition |
| `DeviceBuild` | Device build configuration (container, path, includes) |
| `Release` | Yocto/Isar release definition |
| `VendorIncludes` | Vendor-specific KAS includes for a release |
| `Feature` | Optional feature definition |
| `FeatureCompatibility` | Device compatibility constraints for a feature |
| `BspPreset` | Named preset (device + release + features shortcut) |
| `Docker` | Docker image and build arg configuration |
| `EnvironmentVariable` | Name/value pair with `$ENV{}` expansion support |
| `ResolvedConfig` | Result of resolving a device+release+features combination |

### Exceptions

| Exception | Description |
|-----------|-------------|
| `ScriptError` | Base exception for all script errors |
| `ConfigurationError` | Configuration file issues |
| `BuildError` | Build process failures |
| `DockerError` | Docker operation failures |
| `KasError` | KAS operation failures |

## License

This project is licensed under the Apache 2.0 License — see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request on [GitHub](https://github.com/Advantech-EECC/bsp-registry-tools).

