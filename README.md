# bsp-registry-tools

Python tools to build, fetch, and work with Yocto-based BSPs using the [KAS](https://kas.readthedocs.io/) build system.

## Overview

`bsp-registry-tools` provides a command-line interface, an interactive GUI launcher, and a Python API for managing Advantech Board Support Packages (BSPs). It uses YAML-based registry files to define BSP configurations, build environments, and Docker containers, making reproducible Yocto builds straightforward.

## ⚡ Quick Start

The four commands you need to start building BSPs:

```bash
bsp tree                   # visual overview of the BSP registry
bsp list                   # list all available BSP presets
bsp build <bsp_name>       # build a BSP image
bsp shell <bsp_name>       # enter an interactive build-environment shell
```

👉 See the [**Cheat Sheet**](docs/cheatsheet.md) for a quick reference of all commands, or read on for the full documentation.

### Key Features

- 📋 **BSP registry management** via YAML configuration files
- 🌐 **Automatic remote registry fetching** — clone/update a remote registry with no manual setup
- 🔗 **Named remote management** — `bsp remotes add/remove/rename/set-url/show` for persistent, git-style remote configuration
- 🐳 **Docker container support** for reproducible build environments
- 🔧 **KAS integration** for Yocto-based builds (`kas`, `kas-container`)
- 🖥️ **Interactive shell** access to build environments
- 🔄 **Environment variable expansion** (`$ENV{VAR}` syntax)
- 📤 **Configuration export** for sharing and archiving build configs
- ✅ **Comprehensive validation** of configurations before building
- 📂 **Registry splitting** — compose a registry from multiple files using the `include` directive
- 🌍 **HTTP server mode** — expose the full BSP registry via REST and GraphQL APIs
- ☁️ **Cloud artifact deployment** — upload Yocto build artifacts to Azure Blob Storage or AWS S3 with `bsp deploy`
- 🚀 **Interactive TUI launcher** (`bsp-explorer`) — visual alternative to the CLI
- ⬇️ **Cloud artifact gathering** — download previously uploaded artifacts from Azure Blob Storage or AWS S3 with `bsp gather`
- 🧪 **HIL test triggering** — submit [LAVA](https://lava.readthedocs.io/) test jobs with Robot Framework suites after a build
- 🔒 **CRA vulnerability scanning** — scan built images for CVEs and generate SBOMs (CycloneDX/SPDX) with `bsp scan` ([Trivy](https://trivy.dev/) / Syft+Grype)
- 💾 **SD card / block device flashing** — write Yocto WIC images to an SD card or USB drive with `bsp flash` ([bmap-tools](https://github.com/intel/bmap-tools) for fast, verified flashing)
- 🔤 **Shell tab completions** — Bash/Zsh/Fish/tcsh completions for commands, presets, devices, releases, and features
- 🤖 **MCP server for AI agents** — expose builds, scans, HIL tests, failure triage and layer-pin maintenance over the [Model Context Protocol](https://modelcontextprotocol.io/) with `bsp-mcp` (see [docs/mcp-server.md](docs/mcp-server.md))

## Installation

### From PyPI

```bash
pip install bsp-registry-tools
```

To also install the optional HTTP server dependencies:

```bash
pip install "bsp-registry-tools[server]"
```

### With GUI support

```bash
pip install 'bsp-registry-tools[gui]
```

### From Source

```bash
git clone https://github.com/Advantech-EECC/bsp-registry-tools.git
cd bsp-registry-tools
pip install .

# With server extras:
pip install ".[server]"
```

### Dependencies

- Python 3.8+
- [PyYAML](https://pyyaml.org/) >= 6.0
- [dacite](https://github.com/konradhalas/dacite) >= 1.6.0
- [kas](https://kas.readthedocs.io/) >= 4.7
- [colorama](https://github.com/tartley/colorama) >= 0.4.6
- *(optional)* [textual](https://textual.textualize.io/) >= 8.0.0 — required for `bsp-explorer` GUI
- *(optional)* [textual-serve](https://pypi.org/project/textual-serve/) >= 1.1.0 — required for `bsp-explorer-web` (installed by the `gui` extra)
- [requests](https://requests.readthedocs.io/) >= 2.28.0 *(for LAVA HIL test integration)*
- [Jinja2](https://jinja.palletsprojects.com/) >= 3.1.0 *(for LAVA job template rendering)*

**Optional — server mode** (`pip install bsp-registry-tools[server]`):

- [FastAPI](https://fastapi.tiangolo.com/) >= 0.100.0
- [uvicorn](https://www.uvicorn.org/) >= 0.23.0
- [strawberry-graphql](https://strawberry.rocks/) >= 0.200.0
#### Optional extras for cloud deployment

Cloud SDK dependencies are optional and only needed if you use `bsp deploy`:

```bash
# Azure Blob Storage support
pip install "bsp-registry-tools[azure]"

# AWS S3 support
pip install "bsp-registry-tools[aws]"

# Both providers
pip install "bsp-registry-tools[deploy]"
```

#### Optional extras for shell completions

Tab-completion support is optional and requires [argcomplete](https://kislyuk.github.io/argcomplete/):

```bash
pip install "bsp-registry-tools[completions]"
```

See the [Shell Completions](#shell-completions) section below for activation instructions.

#### Optional extras for SD card flashing

`bsp flash` requires `bmaptool` which is a **system package**, not a Python
package.  Install it with your system package manager:

```bash
# Debian / Ubuntu
sudo apt install bmap-tools

# Arch Linux
sudo pacman -S bmap-tools

# From PyPI
pip install bmaptool
```

The `flash` optional extra is documentation-only and installs no Python
dependencies:

```bash
pip install "bsp-registry-tools[flash]"
```

See [docs/sd-card-flashing.md](docs/sd-card-flashing.md) for full details.

## Shell Completions

`bsp` supports tab completions for Bash, Zsh, Fish, and tcsh via
[argcomplete](https://kislyuk.github.io/argcomplete/).  Completions
dynamically query the active registry so that preset names, device slugs,
release slugs, feature slugs, and remote names are all available.

### 1. Install the completions extra

```bash
pip install "bsp-registry-tools[completions]"
```

### 2. Activate completions for your shell

Use the `bsp completions` sub-command to print the shell-specific activation
snippet, then source it:

```bash
# Bash — add to ~/.bashrc
eval "$(bsp completions bash)"

# Zsh — add to ~/.zshrc
eval "$(bsp completions zsh)"

# Fish — add to ~/.config/fish/config.fish
bsp completions fish | source

# tcsh — add to ~/.tcshrc
eval `bsp completions tcsh`
```

`bsp completions` without an argument auto-detects the shell from `$SHELL`.

### 3. (Alternative) Global activation

If you want completions for all argcomplete-enabled tools at once, use the
helper provided by argcomplete itself:

```bash
activate-global-python-argcomplete
```

This installs a single shell hook that covers every tool that calls
`argcomplete.autocomplete()`.

## Quick Start

### Zero-Config Usage (Remote Registry)

If you have no local registry file, `bsp` automatically clones the default
[Advantech BSP registry](https://github.com/Advantech-EECC/bsp-registry) into
the cache root `~/.cache/bsp/registry` (under a remote-specific subdirectory)
and keeps it up-to-date on every run:

```bash
# First run: clones the registry, then lists BSPs
bsp list

# Subsequent runs: pulls latest changes, then lists BSPs
bsp list

# Skip the network update (useful offline or in CI)
bsp --no-update list

# Use a different remote or branch (one-off override)
bsp --remote https://github.com/my-org/bsp-registry.git --branch dev list
```

### Persistent Named Remotes

For a more permanent setup, register one or more named remotes (similar to
`git remote`).  Once added, these are used automatically whenever `bsp` falls
back to remote registry fetching — no `--remote` flag required:

```bash
# Register a named remote
bsp remotes add myorg https://github.com/my-org/bsp-registry.git --branch dev

# List configured remotes
bsp remotes

# Show full details
bsp remotes show myorg

# Now use it — the stored remote is picked up automatically
bsp list
bsp build my-preset

# With multiple remotes configured, list/tree show all remotes annotated with [remote-name]
bsp list
bsp tree

# Scope listing to a single named remote
bsp list --remote myorg
bsp tree --remote myorg
```

When **multiple remotes** are registered, `bsp list` and `bsp tree` display
entries from all of them, each annotated with `[remote-name]`.  Registries are
kept strictly separate — definitions from different remotes are never merged.
Use `--remote NAME` with `list` or `tree` to restrict output to a single named
remote.

### Manual Registry Usage

### 1. Create a BSP Registry File

Create a `bsp-registry.yaml` or `bsp-registry.yml` file (see [examples/bsp-registry.yaml](examples/bsp-registry.yaml)):

```yaml
specification:
  version: "2.2"

environment:
  variables:
    - name: "GITCONFIG_FILE"
      value: "$ENV{HOME}/.gitconfig"

# Named environment: container + variables used for all builds by default
environments:
  default:
    container: "debian-bookworm"
    variables:
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
      - name: "KAS_VERSION"
        value: "5.1"

registry:
  # frameworks and distro define the build system hierarchy (optional but recommended)
  frameworks:
    - slug: yocto
      description: "Yocto Project build system"
      vendor: "Yocto Project"
      includes:
        - kas/yocto/yocto.yaml

  distro:
    - slug: poky
      description: "Poky (Yocto Project reference distro)"
      framework: yocto     # links distro to a framework for feature compatibility checks
      includes:
        - kas/yocto/distro/poky.yaml

  # devices define hardware targets (KAS includes listed flat, no nested build: block)
  devices:
    - slug: qemuarm64
      description: "QEMU ARM64 (emulated)"
      vendor: qemu
      soc_vendor: arm
      includes:
        - kas/qemu/qemuarm64.yaml

  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS (Scarthgap)"
      distro: poky
      yocto_version: "5.0"
      includes:
        - kas/scarthgap.yaml

  # bsp presets name a device + release + features combination.
  # Use "releases" (plural) to target multiple releases without repetition:
  bsp:
    - name: poky-qemuarm64
      description: "Poky QEMU ARM64"
      device: qemuarm64
      releases: [scarthgap, styhead]   # expands to poky-qemuarm64-scarthgap / poky-qemuarm64-styhead
      features: []
      build:
        container: "debian-bookworm"
    # Single-release entry (backward compatible):
    - name: poky-qemuarm64-scarthgap-ota
      description: "Poky QEMU ARM64 Scarthgap with OTA"
      device: qemuarm64
      release: scarthgap
      features: [ota]
      build:
        container: "debian-bookworm"
        path: build/poky-qemuarm64-scarthgap-ota
```

### 2. List Available BSPs

```bash
# With an explicit registry file
bsp --registry bsp-registry.yaml list

# Or simply if bsp-registry.yaml (or bsp-registry.yml) is in the current directory
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

### 5. Launch the Interactive GUI

```bash
# Install the GUI extra first
pip install 'bsp-registry-tools[gui]'

# Then launch the TUI launcher
bsp-explorer

# Or via the main CLI
bsp gui
bsp --gui

# Serve the TUI in a browser (Textual web server)
bsp-explorer-web

# Load multiple remote registries in one GUI session
bsp-explorer \
  --remote https://github.com/my-org/bsp-registry.git@main@name=myorg \
  --remote https://github.com/vendor/partner-registry.git@release@name=partner
```

**Terminal** (`bsp-explorer`):

![BSP Registry Explorer TUI](docs/screenshots/bsp-launcher-tui.svg)

**Browser** (`bsp-explorer-web`):

![BSP Registry Explorer Web](docs/screenshots/bsp-explorer-web.svg)

### 6. Submit a HIL Test Job

```bash
# Submit a LAVA test job for a pre-built image and wait for results
bsp test poky-qemuarm64-scarthgap --wait

# Build and immediately trigger a LAVA test after the build succeeds
bsp build poky-qemuarm64-scarthgap --test --wait
```

## GUI Launcher (`bsp-explorer`)

`bsp-explorer` is a Terminal User Interface (TUI) that provides a visual, interactive
alternative to the CLI — similar in spirit to the
[Advantech BSP Launcher](https://docs.aim-linux.advantech.com/docs/utility/bsplauncher/).

![BSP Registry Explorer TUI](docs/screenshots/bsp-launcher-tui.svg)

### Features

| Feature | Description |
|---------|-------------|
| **BSP tree** | Vendor → Device → Release → BSP preset hierarchy with filter/search support |
| **BSP details** | Select a BSP to view its description, device, release, features, and build path |
| **Build environment** | Shows the Docker container, named environment, and resolved variables |
| **Build artifacts** | Automatically scans the Yocto deploy directory for `.wic` images and kernel images (`uImage`, `zImage`, `Image`, `fitImage`) — updated after each successful build |
| **Build** | Opens a dialog to choose build options (clean, checkout-only), then streams output to the log (`b`). Output is saved to a timestamped log file (`bsp-build-YYYYMMDD-HHMMSS.log`) in the build folder |
| **Shell** | Exits the TUI and launches an interactive `bsp shell` session in the restored terminal (`s`) |
| **Flash** | Auto-discovers removable drives (USB, SD card, eMMC), selects a flash image, then writes it to the target device using `bmaptool` or `dd` (`f`) |
| **Deploy** | Uploads build artifacts to cloud storage (Azure/AWS) when artifacts are available (`d`) |
| **Export** | Export KAS configuration and stream output to the log panel (`e`) |
| **Cancel** | Terminates a running build (kills the entire process group) (`x`) |
| **Refresh** | Reload the registry (pull latest from remote if applicable) (`r`) |
| **Output log** | Real-time streaming of command output in a scrollable panel |
| **Keyboard-first** | Full keyboard navigation; footer shows all available shortcuts |
| **Registry info** | Top bar displays the active registry URL and branch |

### Launching options

```bash
# Use the default (remote) registry
bsp-explorer

# Use a local registry file
bsp-explorer --registry ./bsp-registry.yaml

# Use a custom remote registry
bsp-explorer --remote https://github.com/my-org/bsp-registry.git --branch dev

# Use multiple remotes (same format as the main CLI)
bsp-explorer \
  --remote https://github.com/my-org/bsp-registry.git@dev@name=myorg \
  --remote https://github.com/vendor/partner-registry.git@main@name=partner

# Skip the remote update (faster, offline)
bsp-explorer --no-update

# Serve the TUI in a web browser (included in the 'gui' extra)
bsp-explorer-web

# Web mode supports multiple remotes too
bsp-explorer-web \
  --remote https://github.com/my-org/bsp-registry.git@dev@name=myorg \
  --remote https://github.com/vendor/partner-registry.git@main@name=partner
```

**TUI in terminal** (`bsp-explorer`):

![BSP Registry Explorer TUI](docs/screenshots/bsp-launcher-tui.svg)

**TUI in browser** (`bsp-explorer-web`):

![BSP Registry Explorer Web](docs/screenshots/bsp-explorer-web.svg)

### CLI vs GUI comparison

| Capability | CLI (`bsp`) | GUI (`bsp-explorer`) |
|-----------|-------------|----------------------|
| List BSPs | `bsp list` | Visual table, keyboard-navigable |
| Build BSP | `bsp build <name>` | Select row → press `b` |
| Shell access | `bsp shell <name>` | Shows equivalent CLI command |
| Export config | `bsp export <name>` | Select row → press `e` |
| List containers | `bsp containers` | Press `c` |
| Real-time output | stdout/stderr | Integrated scrollable log panel |
| Scriptable / CI | ✅ Yes | ❌ Requires a terminal |
## CLI Reference

```
usage: bsp [-h] [--verbose] [--registry REGISTRY] [--no-color]
           [--remote REMOTE] [--branch BRANCH] [--update | --no-update]
           [--local] [--gui]
           {gui,build,list,containers,tree,export,shell,server,deploy,gather,test,flash,remotes} ...

Advantech Board Support Package Registry

positional arguments:
  {gui,build,list,containers,tree,export,shell,server,deploy,gather,test,flash,remotes}
                        Command to execute
    gui                 Launch the interactive GUI launcher
    build               Build an image for BSP
    list                List available BSPs and components
    containers          List available containers
    tree                Display a tree view of the BSP registry
    export              Export BSP configuration
    shell               Enter interactive shell for BSP
    server              Start a GraphQL / REST HTTP server
    deploy              Deploy build artifacts to cloud storage
    gather              Download BSP build artifacts from cloud storage
    test                Submit a LAVA HIL test job for a BSP
    flash               Flash a build image to a block device (SD card / eMMC)
    remotes             Manage named remote BSP registry sources

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
  --gui                 Launch the interactive GUI (requires the [gui] extra)
```

### Registry Resolution Priority

The tool determines which registry file to use in the following order:

1. **`--registry <path>`** — explicit local file, remote fetch is skipped entirely.
2. **`--local`** — use `./bsp-registry.yaml` or `./bsp-registry.yml` in the current directory; no network access.
3. **`bsp-registry.yaml` exists in the current directory** — auto-detect (preferred extension).
4. **`bsp-registry.yml` exists in the current directory** — auto-detect (alternate extension).
5. **`--remote URL` flag(s) provided** — fetch the specified remote(s) on-the-fly (no persistence).
6. **Named remotes configured** — if `bsp remotes add` has registered remotes in `~/.config/bsp/remotes.yaml`, those are fetched automatically.
7. **Otherwise** — bootstrap/use the default named remote (`advantech-europe`) and fetch it from the cache root `~/.cache/bsp/registry` using the same remote-specific subdirectory layout as additional remotes.

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

#### `list` — List available BSPs

```bash
bsp list
bsp --registry my-registry.yaml list

# Filter by component type
bsp list devices
bsp list releases
bsp list features
bsp list distros

# Filter releases to those compatible with a specific device
bsp list releases --device imx8qm

# When multiple remotes are configured, scope output to a single named remote
bsp list --remote myorg
bsp list devices --remote myorg
bsp list releases --remote myorg
```

When multiple remotes are loaded, every entry is annotated with `[registry-name]`
so the source is always visible.  Registries from different remotes are kept
separate — their definitions are never merged together.

| Option | Description |
|--------|-------------|
| `--remote NAME` | Show only entries from the named remote registry |
| `--device DEVICE`, `-d DEVICE` | Filter releases by device slug (only used with `releases`) |

#### `containers` — List container definitions or build container images

```bash
# List all container definitions (default action)
bsp containers
bsp containers list

# Build all containers that have a Dockerfile
bsp containers build
bsp containers build --docker-no-cache   # force clean Docker rebuild

# Build a single named container
bsp containers build debian-bookworm
bsp containers build debian-bookworm --docker-no-cache

# Multi-registry: target a specific registry
bsp containers build upstream:debian-bookworm
```

The `build` action iterates every container in the registry that has both an
`image` and a `file` (Dockerfile) and builds each one. Containers with only an
`image` (pre-built images pulled from a registry) are skipped with a warning.
Pass a name to build only that single container.

`--docker-no-cache` passes Docker’s `--no-cache` flag to the build invocation,
bypassing the layer cache.

The `build_options` field in the registry and the `--docker-build-options` CLI
flag both support **environment variable expansion** using the ``$ENV{VAR}``
syntax (consistent with the rest of the registry) at build time:

```yaml
containers:
  my-image:
    image: "my-org/my-image:latest"
    file: Dockerfile
    build_options: "$ENV{BSP_REGISTRY_DOCKER_BUILD_OPTIONS}"
```

If the variable is unset the reference is passed through unchanged.

#### `tree` — Display a tree view of the BSP registry

```bash
bsp tree
bsp tree --full
bsp tree --compact
bsp --no-color tree
bsp --registry my-registry.yaml tree

# When multiple remotes are configured, scope the tree to a single named remote
bsp tree --remote myorg
bsp tree --full --remote myorg
```

Renders the full registry as a colored ASCII tree, grouped into sections:
**Frameworks**, **Distros**, **Releases** (with vendor overrides), **Devices**,
**Features** (with release and vendor overrides in full mode), and **BSP Presets** (with device, release, and feature details).
Use `--no-color` to disable colors (e.g. for scripts or log files).

When multiple remotes are loaded, items are grouped under `[registry-name]`
sub-nodes.  Registries from different remotes are kept separate — their
definitions are never merged together.  Use `--remote NAME` to restrict the
tree to a single named remote.

| Option | Description |
|--------|-------------|
| `--full` | Show full details including includes lists, release overrides and vendor overrides for features, vendor overrides for releases, and override slugs for presets |
| `--compact` | Show compact output with names/slugs only (no sub-items) |
| `--remote NAME` | Show only entries from the named remote registry |

**Example output (`bsp tree`):**

```
BSP Registry
├── Frameworks (1)
│   └── yocto: Yocto Project (vendor: yocto)
├── Distros (1)
│   └── poky: Poky (vendor: yocto, framework: yocto)
├── Releases (1)
│   └── scarthgap: Yocto 5.0 LTS [Yocto 5.0]
│       ├── distro: poky
│       └── vendor override: advantech (sub-releases: imx-6.6.53)
├── Devices (2)
│   ├── qemu-arm64: QEMU ARM64 (vendor: qemu, soc_vendor: arm)
│   └── imx8qm: i.MX8 QM (vendor: advantech, soc_vendor: nxp, soc_family: imx8)
├── Features (2)
│   ├── ota: OTA Update
│   └── secure-boot: Secure Boot [requires vendor: ['advantech']]
└── BSP Presets (2)
    ├── qemu-arm64-scarthgap: QEMU ARM64 Scarthgap
    │   └── device: qemu-arm64  release: scarthgap
    └── imx8qm-scarthgap: i.MX8 QM Scarthgap
        ├── device: imx8qm  release: scarthgap
        ├── vendor release: imx-6.6.53
        └── features: ota, secure-boot
```

**Example output (`bsp tree --full`):**

In `--full` mode all includes lists are expanded, release overrides and vendor overrides for features are shown as nested sub-trees, and vendor overrides for releases are also expanded:

```
BSP Registry
├── Releases (1)
│   └── scarthgap: Yocto 5.0 LTS [Yocto 5.0]
│       ├── distro: poky
│       ├── includes: kas/poky/scarthgap.yaml
│       └── vendor override: advantech (distro: fsl-imx-xwayland)
│           ├── includes: kas/yocto/vendors/advantech/scarthgap.yaml
│           └── vendor release: imx-6.6.53: Scarthgap for i.MX 6.6.53
│               └── includes:
│                   └── kas/yocto/vendors/advantech/nxp/imx-6.6.53.yaml
└── Features (1)
    └── ostree: Enable OSTree support in the Yocto image [requires compatible_with: yocto]
        ├── includes:
        │   └── features/ota/ostree/ostree.yml
        ├── release override: scarthgap
        │   └── includes:
        │       └── features/ota/ostree/ostree-scarthgap.yml
        ├── release override: styhead
        │   └── includes:
        │       └── features/ota/ostree/ostree-styhead.yml
        └── vendor override: advantech
            └── soc vendor: nxp
                └── includes: features/ota/ostree/modular-bsp-ota-nxp.yml
```

#### `build` — Build a BSP image

```bash
bsp build <bsp_name> [--feature FEATURE...] [--vendor-release SLUG] [--override SLUG] [--checkout] [--target TARGET] [--task TASK] [--path PATH]
bsp build <bsp_name> [--feature FEATURE...] [--deploy] [--deploy-provider PROVIDER] [--deploy-container CONTAINER] [--deploy-prefix PREFIX]
bsp build <bsp_name> [--feature FEATURE...] [--test [--wait] [--lava-server URL] [--lava-token TOKEN] [--artifact-url URL]]
bsp build --device <device> --release <release> [--feature FEATURE...] [--vendor-release SLUG] [--override SLUG] [--checkout] [--target TARGET] [--task TASK] [--path PATH] [--test ...]
```

| Option | Description |
|--------|-------------|
| `--feature FEATURE`, `-f FEATURE` | Feature slug to enable (can be repeated). When used with a preset name, extra features are merged with those already declared in the preset. |
| `--vendor-release SLUG` | Vendor sub-release slug to resolve (maps to `vendor_release`). Useful for selecting a specific vendor BSP release variant at runtime. |
| `--override SLUG` | Vendor override slug to resolve (maps to `override`). Useful when a release has multiple vendor override entries with different slugs. |
| `--checkout` | Validate configuration and checkout repos without building |
| `--path PATH` | Override the output build directory path defined in the registry |
| `--target TARGET` | Bitbake build target (image or recipe) to pass to KAS, overriding any targets defined in the registry preset |
| `--task TASK` | Bitbake task to run (e.g. `compile`, `configure`) to pass to KAS |
| `--deploy` | Deploy artifacts to cloud storage after a successful build |
| `--deploy-provider PROVIDER` | Cloud storage provider: `azure` (default) or `aws` |
| `--deploy-container CONTAINER` | Azure container or AWS bucket name (overrides registry config) |
| `--deploy-prefix PREFIX` | Remote path prefix template (overrides registry config) |
| `--deploy-archive-name NAME` | Bundle artifacts into a single archive with this name before uploading (supports `{device}`, `{release}`, `{distro}`, `{vendor}`, `{date}`, `{datetime}`) |
| `--deploy-archive-format FORMAT` | Archive format: `tar.gz` (default), `tar.bz2`, `tar.xz`, `zip` |
| `--test` | Submit a LAVA HIL test job after a successful build |
| `--wait` | Wait for the LAVA job to complete and print results (requires `--test`) |
| `--lava-server URL` | LAVA server base URL override (overrides registry `lava.server`) |
| `--lava-token TOKEN` | LAVA API token override (overrides registry `lava.token`) |
| `--artifact-url URL` | Base URL where build artifacts are served to the LAVA lab |
| `--docker-no-cache` | Disable Docker layer cache when building the BSP container image |
| `--docker-build-options OPTIONS` | Extra flags passed verbatim to `docker build` (e.g. `--network host`). Overrides `build_options` from the registry container definition and uses the same environment-variable syntax (e.g. `$ENV{MY_FLAGS}`). |

Each `bsp build` run writes `build-manifest.json` into the selected build directory (`--path` or resolved preset path). The manifest records the resolved device/release/features/container and build inputs used for that run, plus a `provenance` section with the tool name/version, the CLI invocation (`argv` and shell command), Python version, and registry git metadata (`commit_sha` / `is_dirty` when available).  `bsp deploy` uploads this file
to `<prefix>/build-manifest.json` by default; pass `--no-build-manifest` to
skip it.

The manifest (`schema_version: "2"`) never contains absolute host paths, so it
stays meaningful on any machine that consumes it.  All paths are emitted
relative to the anchors listed in the `roots` section — the registry root
(`.`, the directory holding the registry YAML) and the build root
(`roots.build`, relative to the registry root).  Paths outside both anchors are
replaced with placeholders: `${HOME}/<relative>` for paths under the user's
home directory and `<external>/<name>` for anything else.  Free-form values
that embed paths (`local_conf` lines, container `runtime_args`, environment
variable values, build options and the CLI command line) are scrubbed the same
way, and `argv[0]` is reduced to the bare program name.

**Examples:**

```bash
# Full build
bsp build poky-qemuarm64-scarthgap

# Checkout/validate only (fast, no build)
bsp build poky-qemuarm64-scarthgap --checkout

# Build a preset with an extra feature enabled on top of the preset's defaults
bsp build poky-qemuarm64-scarthgap --feature secure-boot

# Build with multiple extra features
bsp build poky-qemuarm64-scarthgap --feature secure-boot --feature ota

# Build using a specific vendor sub-release override
bsp build adv-imx8-scarthgap-imx6.6.53 --vendor-release imx-6.12.0

# Build using a specific vendor override slug
bsp build adv-imx8-scarthgap --override imx-xwayland-6.6.52

# Override the output build directory
bsp build poky-qemuarm64-scarthgap --path /mnt/fast-ssd/build

# Build a specific Bitbake image (overrides registry-configured targets)
bsp build poky-qemuarm64-scarthgap --target core-image-minimal

# Build a specific image and run only the compile task
bsp build poky-qemuarm64-scarthgap --target core-image-minimal --task compile

# Build and deploy artifacts to Azure automatically
bsp build poky-qemuarm64-scarthgap --deploy

# Build and deploy to a specific AWS bucket
bsp build poky-qemuarm64-scarthgap --deploy --deploy-provider aws --deploy-container my-s3-bucket

# Build and trigger LAVA test, wait for result
bsp build poky-qemuarm64-scarthgap --test --wait

# Force a clean Docker build (no layer cache)
bsp build poky-qemuarm64-scarthgap --docker-no-cache

# Pass extra Docker build flags (e.g. use host network during build)
bsp build poky-qemuarm64-scarthgap --docker-build-options "--network host"

# Build with LAVA credential overrides
bsp build poky-qemuarm64-scarthgap --test --wait \
  --lava-server https://lava.ci.example.com \
  --lava-token $LAVA_TOKEN \
  --artifact-url http://files.example.com/builds
```

When a build is triggered via the `bsp-explorer` GUI, the full output is saved to a timestamped log file inside the BSP's build directory (e.g. `build/poky-qemuarm64-scarthgap/bsp-build-20260406-205840.log`). Each build creates a new log file, so previous build logs are preserved.

#### `fetch` — Fetch all sources for a BSP

```bash
bsp fetch <bsp_name> [--feature FEATURE...] [--vendor-release SLUG] [--override SLUG] [--target TARGET] [--path PATH]
bsp fetch --device <device> --release <release> [--feature FEATURE...] [--vendor-release SLUG] [--override SLUG] [--target TARGET] [--path PATH]
```

| Option | Description |
|--------|-------------|
| `--feature FEATURE`, `-f FEATURE` | Feature slug to enable (can be repeated). When used with a preset name, extra features are merged with those already declared in the preset. |
| `--vendor-release SLUG` | Vendor sub-release slug to resolve (maps to `vendor_release`). |
| `--override SLUG` | Vendor override slug to resolve (maps to `override`). |
| `--target TARGET` | BitBake target to fetch. If omitted, `bsp fetch` uses targets resolved from the KAS configuration or preset. |
| `--path PATH` | Override the output build directory path defined in the registry |

`bsp fetch` runs BitBake with `--runall=fetch`, which downloads the full source dependency set without starting a full image build.

**Examples:**

```bash
# Fetch sources for a preset using its configured target(s)
bsp fetch poky-qemuarm64-scarthgap

# Fetch sources for a specific image target
bsp fetch poky-qemuarm64-scarthgap --target core-image-minimal

# Fetch sources using a specific vendor sub-release override
bsp fetch adv-imx8-scarthgap-imx6.6.53 --vendor-release imx-6.12.0

# Fetch sources using a specific vendor override slug
bsp fetch adv-imx8-scarthgap --override imx-xwayland-6.6.52

# Fetch sources for a component-based selection into a custom build directory
bsp fetch --device qemuarm64 --release scarthgap --target core-image-minimal --path /mnt/fast-ssd/build
```

#### `shell` — Interactive shell in build environment

```bash
bsp shell <bsp_name> [--command COMMAND] [--path PATH]
bsp shell --device <device> --release <release> [--feature FEATURE...] [--command COMMAND] [--path PATH]
```

| Option | Description |
|--------|-------------|
| `--command COMMAND`, `-c COMMAND` | Execute a specific command instead of starting interactive shell |
| `--path PATH` | Override the output build directory path defined in the registry |

**Examples:**

```bash
# Interactive shell
bsp shell poky-qemuarm64-scarthgap

# Execute single command
bsp shell poky-qemuarm64-scarthgap --command "bitbake core-image-minimal"

# Interactive shell with a custom build directory
bsp shell poky-qemuarm64-scarthgap --path /mnt/fast-ssd/build

# Component-based shell with a custom build directory
bsp shell --device qemuarm64 --release scarthgap --path /mnt/fast-ssd/build
```

#### `export` — Export BSP configuration

```bash
bsp export <bsp_name> [--output OUTPUT]
bsp export --device <device> --release <release> [--feature FEATURE...] [--output OUTPUT]
bsp export <bsp_name> --repo-manifest [--output OUTPUT]
bsp export --device <device> --release <release> [--feature FEATURE...] --repo-manifest [--output OUTPUT]
```

| Option | Description |
|--------|-------------|
| `--output OUTPUT`, `-o OUTPUT` | Output file path (default: stdout) |
| `--repo-manifest` | Export Android repo manifest XML from KAS lock/unlocked dumps (CLI only) |

**Examples:**

```bash
# Print to stdout
bsp export poky-qemuarm64-scarthgap

# Save to file
bsp export poky-qemuarm64-scarthgap --output exported-config.yaml

# Export Android repo manifest XML
bsp export poky-qemuarm64-scarthgap --repo-manifest --output repo-manifest.xml

# Export Android repo manifest XML using component mode
bsp export --device qemuarm64 --release scarthgap --repo-manifest --output qemuarm64-scarthgap.xml
```

When `--repo-manifest` is used, `bsp export` writes an Android `repo` XML
manifest generated from `kas dump --lock --sort` plus an unlocked
`kas dump --sort`. Commit revisions from lock output are preferred when
available; otherwise revision may come from unlocked config or be omitted.
This makes it suitable for release capture and later replay in CI or
production source checkout flows.

**Typical production workflow:**

1. Resolve and export the manifest at release cut time.
2. Store the XML next to the build outputs, `build-manifest.json`, and release
   metadata.
3. Commit the exported XML into a dedicated manifest repository (or release
   branch) so it can be selected later with `repo init -m ...`.
4. Reuse the same manifest in CI, factory, or field-reproduction workflows to
   sync the recorded source revisions.

**Recommended release capture example:**

```bash
# 1) Export the locked manifest
bsp export poky-qemuarm64-scarthgap --repo-manifest --output release-manifests/poky-qemuarm64-scarthgap-2026-05-25.xml

# 2) Archive it together with other release metadata
# (assumes build artifacts/build-manifest.json were generated previously via bsp build)
cp build/poky-qemuarm64-scarthgap/build-manifest.json release-manifests/
```

**Later use in production with a manifest repository:**

Commit the exported XML into your manifest Git repository, then initialize a
workspace from that repository and select the locked manifest file:

```bash
repo init -u ssh://git.example.com/manifests.git -m release-manifests/poky-qemuarm64-scarthgap-2026-05-25.xml
repo sync -c --no-tags --optimized-fetch --prune
```

This is the preferred production pattern because the exported XML becomes an
immutable release input that can be reviewed, tagged, mirrored, and reused by
automation.

**Later use in an existing `repo` workspace via local manifests:**

If you already have an initialized `repo` workspace, add the exported XML under
`.repo/local_manifests/` and resync:

```bash
mkdir -p .repo/local_manifests
cp /path/to/poky-qemuarm64-scarthgap-2026-05-25.xml .repo/local_manifests/bsp-locked.xml
repo sync -c --no-tags --optimized-fetch --prune
```

**Notes and limitations:**

- The exported Android repo manifest is currently available from the **CLI
  only**.
- Reproducibility depends on the repositories being accessible at the recorded
  URLs and revisions.
- The manifest captures recorded Git revisions, but it does **not** capture local
  environment state, credentials, downloaded artifacts, or non-Git external
  inputs.

#### `server` — Start an HTTP server (REST + GraphQL)

Starts a FastAPI-based HTTP server that exposes the full BSP registry via both a REST API and a GraphQL API.  Requires the `server` optional extras (`pip install "bsp-registry-tools[server]"`).

```bash
bsp server [--host HOST] [--port PORT] [--reload]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--host HOST` | `127.0.0.1` | Host address to bind to |
| `--port PORT` | `8080` | Port to listen on |
| `--reload` | — | Enable auto-reload on code changes (development mode) |

Once started, the following interfaces are available:

| URL | Description |
|-----|-------------|
| `http://localhost:8080/docs` | Swagger / OpenAPI UI (REST) |
| `http://localhost:8080/redoc` | ReDoc UI (REST) |
| `http://localhost:8080/graphql` | GraphiQL interactive editor (GraphQL) |
| `http://localhost:8080/api/v1/…` | REST API endpoints |

---

#### `deploy` — Upload build artifacts to cloud storage

Deploy Yocto build artifacts (images, SDKs) that were produced by `bsp build`
to Azure Blob Storage or AWS S3.  Optionally also upload Yocto build caches
(`DL_DIR` / `SSTATE_DIR`) with `--deploy-cache`.

```bash
bsp deploy <bsp_name> [OPTIONS]
bsp deploy --device <d> --release <r> [--feature <f>] [OPTIONS]
#### `flash` — Flash a build image to a block device

Writes the most recently built `.wic` (or `.img`) image from the BSP's deploy directory to an SD card or eMMC target. Uses `bmaptool` for efficient sparse writes when a `.bmap` sidecar is present, or falls back to `dd`.

```bash
bsp flash <bsp_name> --target <device> [--image <path>]
```

| Option | Description |
|--------|-------------|
| `--provider PROVIDER` | Storage provider: `azure` (default) or `aws` |
| `--container CONTAINER`, `--bucket CONTAINER` | Azure container or AWS S3 bucket name |
| `--prefix PREFIX` | Remote path prefix template (supports `{device}`, `{release}`, `{distro}`, `{vendor}`, `{date}`, `{datetime}`) |
| `--pattern PATTERN` | Glob pattern for artifacts to upload (repeatable; overrides registry config) |
| `--archive-name NAME` | Bundle artifacts into a single archive with this name before uploading (supports `{device}`, `{release}`, `{distro}`, `{vendor}`, `{date}`, `{datetime}`) |
| `--archive-format FORMAT` | Archive format: `tar.gz` (default), `tar.bz2`, `tar.xz`, `zip` |
| `--update-index` | Regenerate and upload a browsable, SAS-signed `index.html` after a successful deploy |
| `--no-update-index` | Never generate an `index.html`, even when enabled in the registry |
| `--no-build-manifest` | Do not upload the `build-manifest.json` produced by `bsp build` |
| `--deploy-cache` | Also upload Yocto DL_DIR / SSTATE_DIR caches to cloud storage |
| `--no-deploy-cache-downloads` | Skip the DL_DIR upload (use with `--deploy-cache`) |
| `--no-deploy-cache-sstate` | Skip the SSTATE_DIR upload (use with `--deploy-cache`) |
| `--dry-run` | List what would be uploaded without uploading (no credentials required) |
| `--target TARGET`, `-t TARGET` | Target block device (e.g. `/dev/sda`, `/dev/mmcblk0`) |
| `--image IMAGE`, `-i IMAGE` | Path to the image file to flash (auto-selected from deploy dir if omitted) |

---

#### `gather` — Download build artifacts from cloud storage

Downloads Yocto build artifacts that were previously uploaded by `bsp deploy`
from Azure Blob Storage or AWS S3 to a local directory.  With `--gather-cache`
it also restores Yocto build caches (`DL_DIR` / `SSTATE_DIR`) from cloud
storage — a missing cache is skipped silently, so the command always succeeds.

```bash
bsp gather <bsp_name> [OPTIONS]
bsp gather --device <d> --release <r> [--feature <f>] [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--provider PROVIDER` | Storage provider: `azure` (default) or `aws` |
| `--container CONTAINER`, `--bucket CONTAINER` | Azure container or AWS S3 bucket name |
| `--prefix PREFIX` | Remote path prefix template (supports `{device}`, `{release}`, `{distro}`, `{vendor}`, `{date}`) |
| `--dest-dir PATH` | Local directory to write downloaded artifacts into (default: `<build_path>/build/tmp/deploy/images` under the registry build path) |
| `--date DATE` | Override the `{date}` placeholder in the prefix template (`YYYY-MM-DD`); defaults to today |
| `--gather-cache` | Also download and restore Yocto cache archives (DL_DIR / SSTATE_DIR) if available |
| `--cache-downloads-dir PATH` | Local path to restore the DL_DIR cache into (default: `DL_DIR` env var or `<topdir>/downloads`, where TOPDIR is inferred from `artifact_dirs`) |
| `--cache-sstate-dir PATH` | Local path to restore the SSTATE_DIR cache into (default: `SSTATE_DIR` env var or `<topdir>/sstate-cache`, where TOPDIR is inferred from `artifact_dirs`) |
| `--dry-run` | List what would be downloaded without downloading (no credentials required) |

**Examples:**

```bash
# Download artifacts for a preset build (uses today's date)
bsp gather poky-qemuarm64-scarthgap

# Download artifacts into a specific local directory
bsp gather poky-qemuarm64-scarthgap --dest-dir /mnt/artifacts

# Download artifacts produced on a specific date
bsp gather poky-qemuarm64-scarthgap --date 2025-03-15

# Preview what would be downloaded (dry-run)
bsp gather poky-qemuarm64-scarthgap --dry-run

# Component-based gather
bsp gather --device qemuarm64 --release scarthgap --dest-dir /mnt/artifacts

# Restore artifacts + Yocto caches
bsp gather poky-qemuarm64-scarthgap \
    --gather-cache \
    --cache-downloads-dir /mnt/yocto/downloads \
    --cache-sstate-dir /mnt/yocto/sstate
```

---

#### `scan` — CRA vulnerability scanning and SBOM generation

Scans built Yocto image artifacts for CVEs and generates a Software Bill of
Materials (SBOM).  Supports [**Trivy**](https://trivy.dev/) (default) and
**Syft + Grype** as scanner backends.  See
[docs/cra-scanning.md](docs/cra-scanning.md) for full details and
prerequisites.

```bash
bsp scan <bsp_name> [OPTIONS]
bsp scan --device <d> --release <r> [--feature <f>] [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--tool trivy\|syft+grype\|emba` | Scanner backend (default: `trivy`) |
| `--severity LEVEL` | Minimum CVE severity to report: `LOW`, `MEDIUM`, `HIGH` (default), `CRITICAL` |
| `--fail-on LEVEL` | Exit non-zero at this severity: `NONE`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` (default) |
| `--sbom-format FORMAT` | SBOM format: `cyclonedx` (default), `spdx-json`, `spdx-tag-value` |
| `--output-dir PATH` | Directory for reports and SBOMs (default: `<build_path>/reports/`) |
| `--image-path PATH` | Explicit artifact to scan (repeatable; overrides auto-discovery) |
| `--dry-run` | List what would be scanned without running the scanner |

**Examples:**

```bash
# Scan a preset's built artifacts
bsp scan poky-qemuarm64-scarthgap

# Fail on HIGH or above, generate SPDX-JSON SBOM
bsp scan poky-qemuarm64-scarthgap --fail-on HIGH --sbom-format spdx-json

# Dry run: show which artifacts would be scanned
bsp scan poky-qemuarm64-scarthgap --dry-run

# Scan a specific image file explicitly
bsp scan poky-qemuarm64-scarthgap \
  --image-path build/poky/tmp/deploy/images/qemuarm64/core-image-minimal.wic

# Scan immediately after a build (--scan flag on bsp build)
bsp build poky-qemuarm64-scarthgap --scan --scan-fail-on CRITICAL
```

**Prerequisites:** Install [Trivy](https://trivy.dev/latest/getting-started/installation/) before using `bsp scan`.

---

#### `flash` — Flash a Yocto image to an SD card or block device

Discovers the Yocto WIC image produced by `bsp build` and writes it to a block
device using [bmap-tools](https://github.com/intel/bmap-tools) (`bmaptool
copy`) for fast, verified flashing.  See
[docs/sd-card-flashing.md](docs/sd-card-flashing.md) for full details and
prerequisites.

```bash
bsp flash <bsp_name> --target /dev/sdX [OPTIONS]
bsp flash --device <d> --release <r> [--feature <f>] --target /dev/sdX [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--target DEVICE`, `-t DEVICE` | Destination block device (e.g. `/dev/sdb`). Required unless `--dry-run` is used or `--tool uuu` is selected. |
| `--image-path PATH` | Explicit image file to flash (overrides auto-discovery) |
| `--image-pattern PATTERN` | Override default glob patterns for image discovery (repeatable) |
| `--tool bmaptool\|dd\|uuu` | Flash tool override (default: `bmaptool`) |
| `--extra-args ARGS` | Extra arguments forwarded verbatim to the flash tool (e.g. `--nobmap`) |
| `--build-path PATH` | Override the build output directory used for image discovery |
| `--dry-run` | Show what would be flashed without writing anything to the device |

For non-dry-run flashes, `bsp` runs the final flashing command with superuser
rights (via `sudo` when not already root).

**Examples:**

```bash
# Flash a preset's built image to /dev/sdb
bsp flash imx8mp-adv-scarthgap --target /dev/sdb

# Preview what would be flashed without writing
bsp flash imx8mp-adv-scarthgap --dry-run

# Flash a specific image file explicitly
bsp flash imx8mp-adv-scarthgap \
  --target /dev/sdb \
  --image-path build/imx8mp-adv/scarthgap/tmp/deploy/images/core-image-minimal.wic.bz2

# Use dd instead of bmaptool
bsp flash imx8mp-adv-scarthgap --target /dev/sdb --tool dd

# Use uuu (mfgtools) for NXP USB flashing (no --target required;
# "-b emmc_all" is used by default unless --extra-args supplies a burn script)
bsp flash imx8mp-adv-scarthgap --tool uuu

# Flash immediately after a build
bsp build imx8mp-adv-scarthgap --flash /dev/sdb
```

**Prerequisites:** Install [bmap-tools](https://github.com/intel/bmap-tools) (`sudo apt install bmap-tools`) for `bmaptool` mode, or [uuu/mfgtools](https://github.com/nxp-imx/mfgtools) for `--tool uuu`.

---

#### `test` — Run test suites via LAVA or direct execution

Runs BSP tests with one of four backends:

- `lava` (existing/default behavior)
- `direct-local` (run Lava-Test definitions on the local host)
- `direct-ssh` (run Lava-Test definitions on a remote target via SSH)
- `direct-serial` (run Lava-Test definitions over a serial-backed SSH ProxyCommand transport)

```bash
bsp test <bsp_name> [--backend BACKEND] [OPTIONS]
bsp test --device <device> --release <release> [--feature FEATURE...] [--backend BACKEND] [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--backend {lava,direct-local,direct-ssh,direct-serial}` | Backend override (`testing.backend` / `lava` by default) |
| `--wait` | LAVA only: block until the submitted job completes |
| `--lava-server URL` / `--lava-token TOKEN` / `--artifact-url URL` | LAVA backend overrides |
| `--test-repo-url URL` / `--test-repo-ref REF` | Direct backend test-definition Git source override |
| `--test-definition-path PATH` | Direct backend definition file/dir/glob (repeatable). LAVA job YAML files are also accepted; suites are read from `actions[].test.definitions[].path`. |
| `--test-job-path PATH` | Local LAVA job YAML file (repeatable). For entries with `from: git` and `repository`, the referenced Git repository is cloned and the test definition is run from there. Entries without a `repository` are resolved relative to the job file's directory. No `--test-repo-url` is required. |
| `--test-suite NAME` | Direct backends only: run only the named test suite(s) (repeatable). Matches `actions[].test.definitions[].name` in the LAVA job YAML, falling back to the definition's `metadata.name` / file stem for plain test definitions. |
| `--test-param KEY=VALUE` | Direct backend parameter override (repeatable) |
| `--test-requirements PATH_OR_URL` | Direct backends only: requirement catalogue YAML providing test case descriptions, specifications, versions and categories for the report (repeatable). Accepts a local path or an `http(s)` URL, so a catalogue maintained in another repository can be reused |
| `--show-cases` | Direct backends only: list every test case with its description in the console summary (implied by `--verbose`) |
| `--direct-timeout SECONDS` / `--direct-output-dir PATH` | Direct execution timeout and output controls |
| `--ssh-host/--ssh-user/--ssh-port/--ssh-key/--ssh-password` | SSH transport overrides for `direct-ssh` / `direct-serial` |
| `--ssh-known-hosts-file` / `--ssh-no-strict-host-key-checking` | SSH host key verification controls |
| `--ssh-remote-workdir PATH` | Remote staging directory for `direct-ssh` / `direct-serial` runs |
| `--ssh-serial-device /dev/ttyUSBX` / `--ssh-serial-baudrate BAUD` | Serial transport settings (required for `direct-serial`, optional for `direct-ssh`) |
| `-v` / `--verbose` | Emit detailed per-suite and per-case test execution logs |

**Examples:**

```bash
# LAVA backend (default)
bsp test poky-qemuarm64-scarthgap --wait

# Direct local run from GitHub test definitions
bsp test poky-qemuarm64-scarthgap \
  --backend direct-local \
  --test-repo-url https://github.com/Linaro/test-definitions.git \
  --test-repo-ref main \
  --test-definition-path automated/linux \
  --test-param BOARD_IP=192.168.1.10

# Direct local run from a remote LAVA job YAML (uses actions[].test.definitions paths)
bsp test poky-qemuarm64-scarthgap \
  --backend direct-local \
  --test-repo-url https://github.com/Linaro/test-definitions.git \
  --test-definition-path automated/linux/modular-bsp/jobs/rsb3720-modbsp.yaml

# Direct local run from a local LAVA job YAML (repositories in the YAML are cloned automatically)
bsp test poky-qemuarm64-scarthgap \
  --backend direct-local \
  --test-job-path /path/to/local/jobs/rsb3720-modbsp.yaml

# Run a single suite from a local LAVA job YAML over SSH
bsp test modular-bsp-rsb3720-6g-wrynose \
  --backend direct-ssh \
  --test-job-path vendors/advantech-europe/nxp/test/jobs/rsb3720-6g-modbsp.yaml \
  --ssh-host 192.168.3.195 \
  --ssh-user root \
  --ssh-no-strict-host-key-checking \
  --test-suite adv-context

# Direct SSH run on DUT
bsp test poky-qemuarm64-scarthgap \
  --backend direct-ssh \
  --test-repo-url https://github.com/Linaro/test-definitions.git \
  --test-definition-path smoke.yaml \
  --ssh-host 10.0.0.42 \
  --ssh-user root \
  --ssh-key ~/.ssh/id_ed25519

# Direct SSH run with an explicit requirement catalogue for the report
bsp test modular-bsp-rsb3720-6g-wrynose \
  --backend direct-ssh \
  --test-job-path vendors/advantech-europe/nxp/test/jobs/rsb3720-6g-modbsp.yaml \
  --test-requirements requirements.yaml \
  --ssh-host 192.168.3.195 \
  --ssh-user root

# Direct serial run
bsp test poky-qemuarm64-scarthgap \
  --backend direct-serial \
  --test-repo-url https://github.com/Linaro/test-definitions.git \
  --test-definition-path smoke.yaml \
  --ssh-serial-device /dev/ttyUSB0 \
  --ssh-serial-baudrate 115200
```

When `--verbose` is enabled, test execution logs include per-suite and per-case outcomes:

- **LAVA backend**: logs each suite and case result after `--wait` completes.
- **Direct backends**: logs each suite/case status, execution duration, command, and generated per-step log file path.

Direct backends also persist collected artifacts under `<build-path>/test-results` (or `--direct-output-dir` when set), including:

- `direct-test-report.html` with aggregate KPIs, a category roll-up, a cross-suite requirements matrix, suite quick navigation and per-suite test case tables
- `direct-test-report.pdf` (when the `report` extra is installed) — a condensed
  executive summary rendered from a dedicated A4 portrait template: verdict,
  aggregate KPIs, preset info, category roll-up, one row per suite and the list
  of failures. It carries no logs and no per-test detail, and the suite,
  category and failure tables are capped, so the document stays within a few
  pages regardless of the size of the run; the HTML report remains the complete
  record. WeasyPrint needs the system Pango/cairo libraries; on Debian/Ubuntu
  install them with
  `sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi-dev`.
- `direct-test-summary.json` for machine-readable summary data
- per-step log files linked from the HTML report

#### Test report contents

Each test case row of the report can show a requirement id, test case,
specification, version, category and verification status:

| Column | Source |
| --- | --- |
| Requirement Id | requirement catalogue (linked from the signal) |
| Test Case | `TEST_CASE_ID` of the LAVA signal, expandable to reveal the description (`DESCRIPTION` signal attribute › requirement catalogue › humanized test case id) |
| Parameters | requirement catalogue `specification` (falls back to the step parameters) |
| Version | requirement catalogue |
| Category | requirement catalogue |
| State | `RESULT` of the LAVA signal, with the measurement in parentheses |

Optional columns are omitted entirely when no test case in the run supplies the
corresponding metadata, so plain test definitions keep a compact table.

**Every test case always carries a description.** It is resolved in this order:

1. the `DESCRIPTION=` attribute of the LAVA signal,
2. the definition's inline `metadata.test_cases` entry (which overrides the
   shared catalogue for that suite),
3. the matching requirement catalogue entry (local or downloaded; when several
   catalogues are given, the last one carrying the requirement wins),
4. a humanized test case id (`ping-gateway` → "Ping gateway").

Descriptions are shown by expanding the *Test Case* cell; there is no separate
description column.  Descriptions derived from the test case id are rendered in
a muted, italic style so a generated fallback can be told apart from authored text, and the
*Described tests* KPI reports how many cases carry an authored description. Test
case ids that fall back to the derived description are also listed in a single
warning after the run, which makes a missing or mistyped requirement id visible
without ever failing the run.

The expanded test case cell also shows the catalogue's `verifies` text (what the
case actually asserts) and `remarks` when present. Suites list their described steps
under *Executed steps*, which covers steps that emit no LAVA signal at all.

Failed test cases (and failed steps) additionally carry a *Log* fold with the tail of the
step log — command, return code, stdout and stderr — embedded in the report so the HTML
stays self-contained. The log is collapsed by default and only the last 200 lines are kept;
when the log is longer, the fold points at the full per-step log file.

Add `--show-cases` (implied by `--verbose`) to also print every test case with
its description in the console summary.

#### LAVA signal attributes

Test scripts report results with the standard LAVA signal line and may add any
number of `KEY=VALUE` attributes (values may be quoted to carry spaces):

```
<LAVA_SIGNAL_TESTCASE TEST_CASE_ID=L-CPU-FREQ-SCALING-MAX-cpu0 RESULT=pass MEASUREMENT=1600000>
```

`RESULT` accepts `pass`, `fail`, `skip`, `unknown` and `manual`; `skip` and
`unknown` are reported as "not run" and `manual` as a manual test — neither
counts as a failure. Recognised attributes are `MEASUREMENT`, `UNITS`,
`REQUIREMENT_ID`, `DESCRIPTION`, `VERIFIES`, `REMARKS`, `SPECIFICATION`,
`VERSION` and `CATEGORY`;
any other attribute is preserved in the JSON summary. Attributes always take
precedence over catalogue values, but are normally only used for runtime data
(the measured value) — static text belongs in the requirement catalogue.

#### Requirement catalogue

The catalogue holds the static metadata of each requirement and lives in the
test-definition repository. It is discovered automatically from a
`requirements.yaml` file at the definition root, can be pointed at explicitly
with `--test-requirements PATH_OR_URL` (repeatable), or be declared per source
in the registry:

```yaml
testing:
  backend: direct-ssh
  direct:
    definitions:
      - repo_url: https://github.com/example/test-definitions.git
        paths: [automated/linux]
        requirement_catalogs: [requirements.yaml]
```

A catalogue reference may also be an `http(s)` URL, which makes the
descriptions maintained in another repository reusable for definitions that
carry no catalogue of their own. GitHub `blob` (and `raw`) web URLs are
downloaded as raw content automatically:

```bash
bsp test <bsp_name> --backend direct-ssh \
  --test-job-path jobs/rsb3720-modbsp.yaml \
  --test-requirements https://github.com/miketsukerman/modular-bsp-test-definitions/blob/main/requirements.yaml \
  --ssh-host 192.168.3.195 --ssh-user root
```

The catalogue is downloaded once per run and a failing download only logs a
warning: descriptions then fall back to the catalogue shipped with the
definitions, or to the humanized test case id.

A catalogue is a mapping of requirement id to entry (a top-level
`requirements:` key and a list of entries carrying `id` are also accepted):

```yaml
L-CPU-FREQ-SCALING-MAX:
  description: The CPU should match the specified maximum scaling frequency
  verifies: scaling_max_freq of every CPU equals the configured specification
  remarks: Requires the cpufreq driver to be loaded
  version: 1
  category: CPU
  specification:
    cpu0: 1600000
    cpu1: 1600000
"L-AUDIO-PLAYBACK:F":
  description: A sample WAV file shall be played back through the specified ALSA device
  category: AUDIO
  manual: true
```

| Field | Meaning |
| --- | --- |
| `description` (alias `desc`, `purpose`) | What the test case means and why it exists |
| `verifies` (alias `verification`) | What is actually asserted and how |
| `remarks` | Preconditions or caveats worth showing next to the result |
| `specification` (alias `spec`) | Expected value, optionally a mapping keyed by instance |
| `version`, `category`, `manual` | Requirement version, roll-up category, manual test flag |

An entry may also be a plain string, which is taken as its description
(`L-CPU-MODEL: The kernel shall enumerate the specified CPU model`).

A test case is linked to its requirement through an explicit `REQUIREMENT_ID`
signal attribute, or — when absent — by matching the test case id against
catalogue ids using the longest matching prefix. The remainder is used as the
instance key, so `L-CPU-FREQ-SCALING-MAX-cpu0` and `L-CPU-FREQ-SCALING-MAX-cpu1`
share one description while each picking its own `specification` value.

Individual definitions can declare or override entries inline, which takes
precedence over the shared catalogue for that suite only:

```yaml
metadata:
  name: cpu-suite
  test_cases:
    L-CPU-MODEL:
      description: The Linux Kernel shall enumerate the specified CPU Model
      category: CPU
```

Catalogues are always optional: a missing or malformed catalogue logs a warning
and never fails a test run.

#### Step descriptions

A `run.steps` entry may carry a `description` explaining what the step does,
which is shown in the report's per-suite *Executed steps* table. This is useful
for steps that emit no LAVA signal:

```yaml
metadata:
  name: net-suite
run:
  steps:
    - command: ./setup-network.sh
      description: Bring the network interface up before the checks run
```

Descriptions may equally be declared in a `metadata.steps` mapping keyed by the
generated step name (`step-1`, `step-2`, …) or by the raw command; an inline
`description` on the step wins. Steps without a description are not listed.

When `--test-definition-path` points to a LAVA job YAML, direct backends execute only entries under `actions[].test.definitions[].path`. If both the source and a job entry define parameters, entry `parameters` override source-level values with the same key.

`--test-job-path` accepts a local LAVA job YAML and automatically resolves each `actions[].test.definitions[]` entry:

- Entries with `from: git` and a `repository` URL are cloned (or updated from cache) and the definition at `path` is executed from that cloned repository. The optional `branch` / `revision` fields select the checkout ref.
- Entries without a `repository` (local-path style) are resolved relative to the job file's parent directory.

This means the job YAML fully drives which repositories are used and no separate `--test-repo-url` is required.

Use `--test-suite NAME` to run only some of the entries in a job YAML. The value is matched exactly against the entry's `name` field, so a job containing:

```yaml
  - test:
      definitions:
        - repository: https://github.com/miketsukerman/modular-bsp-test-definitions.git
          from: git
          branch: main
          path: automated/linux/context/context.yaml
          name: adv-context
```

can be narrowed with `--test-suite adv-context`. The flag is repeatable, only the repositories of the selected entries are cloned/staged, and when nothing matches the error message lists the available suite names. `--test-suite` applies to direct backends only and is ignored (with a warning) for the LAVA backend.

#### `remotes` — Manage named remote registries

`bsp remotes` manages a persistent list of named remote BSP registry sources,
stored in `~/.config/bsp/remotes.yaml` (overridable via the
`BSP_REMOTES_CONFIG` environment variable).  This is modelled after
`git remote` and integrates with the registry resolution fallback: when no
`--remote` flag is passed and no local registry file exists, configured remotes
are used automatically.

If no remotes are configured yet, `bsp` bootstraps a default remote named
`advantech-europe` pointing to
`https://github.com/Advantech-EECC/bsp-registry.git`.

**List remotes**

```bash
# Short listing — one name per line
bsp remotes

# Verbose — include URL and branch
bsp remotes -v
```

Example output:

```
advantech-europe
myorg
```

```
advantech-europe  https://github.com/Advantech-EECC/bsp-registry.git (branch: main)
myorg      https://github.com/my-org/bsp-registry.git (branch: develop)
```

**Add a remote**

```bash
bsp remotes add <name> <url> [--branch BRANCH]
```

```bash
# Add the default Advantech registry under a friendly name
bsp remotes add advantech-europe https://github.com/Advantech-EECC/bsp-registry.git

# Add a private registry on a non-default branch
bsp remotes add myorg https://github.com/my-org/bsp-registry.git --branch develop
```

**Remove a remote**

```bash
bsp remotes remove <name>
# or: bsp remotes rm <name>
```

**Rename a remote**

```bash
bsp remotes rename <old-name> <new-name>
```

**Change a remote's URL**

```bash
bsp remotes set-url <name> <new-url>

# Also update the branch at the same time
bsp remotes set-url <name> <new-url> --branch <branch>
```

**Show details of a remote**

```bash
bsp remotes show <name>
```

Example output:

```
name:   myorg
url:    https://github.com/my-org/bsp-registry.git
branch: develop
```

**`remotes` options summary**

| Sub-command | Arguments | Description |
|-------------|-----------|-------------|
| *(none)* | | List configured remote names |
| `-v` / `--verbose-list` | | Show URL and branch alongside each name |
| `add` | `<name> <url> [--branch BRANCH]` | Register a new named remote |
| `remove` / `rm` | `<name>` | Remove a named remote |
| `rename` | `<old-name> <new-name>` | Rename a remote |
| `set-url` | `<name> <url> [--branch BRANCH]` | Update URL (and optionally branch) |
| `show` | `<name>` | Print name, URL and branch for a remote |

> **Config file location** — `~/.config/bsp/remotes.yaml`  (override with
> `BSP_REMOTES_CONFIG=/path/to/remotes.yaml bsp remotes ...`)



## HTTP Server (REST + GraphQL)

The `bsp server` command exposes the entire BSP registry over HTTP.  Both a REST API and a GraphQL API are available simultaneously on the same port.

### Installation

```bash
pip install "bsp-registry-tools[server]"
```

### Starting the server

```bash
# Default: http://127.0.0.1:8080
bsp server

# Custom host/port
bsp server --host 0.0.0.0 --port 9000

# Using a specific registry file
bsp --registry /path/to/bsp-registry.yaml server --host 0.0.0.0 --port 8080
```

### REST API (`/api/v1/`)

#### Query endpoints (GET)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/bsp` | List all BSP presets |
| GET | `/api/v1/devices` | List all hardware devices |
| GET | `/api/v1/releases` | List all releases |
| GET | `/api/v1/releases?device=<slug>` | List releases compatible with a device |
| GET | `/api/v1/features` | List all optional features |
| GET | `/api/v1/distros` | List all distribution definitions |
| GET | `/api/v1/frameworks` | List all framework definitions |
| GET | `/api/v1/containers` | List all Docker container definitions |

**Example:**

```bash
curl http://localhost:8080/api/v1/devices
```

```json
[
  {
    "slug": "qemuarm64",
    "description": "QEMU ARM64 (emulated)",
    "vendor": "qemu",
    "soc_vendor": "arm",
    "soc_family": null,
    "includes": ["kas/qemu/qemuarm64.yaml"],
    "local_conf": []
  }
]
```

#### Action endpoints (POST)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/export` | Resolve and return a BSP config as YAML |
| POST | `/api/v1/build` | Trigger a BSP build (blocking) |
| POST | `/api/v1/shell` | Run a command inside the build container |

All action endpoints accept a JSON body with either `bsp_name` **or** both `device` + `release`:

```bash
# Export by preset name
curl -X POST http://localhost:8080/api/v1/export \
     -H "Content-Type: application/json" \
     -d '{"bsp_name": "poky-qemuarm64-scarthgap"}'

# Export by components
curl -X POST http://localhost:8080/api/v1/export \
     -H "Content-Type: application/json" \
     -d '{"device": "qemuarm64", "release": "scarthgap", "features": []}'

# Validate (checkout only) without building
curl -X POST http://localhost:8080/api/v1/build \
     -H "Content-Type: application/json" \
     -d '{"bsp_name": "poky-qemuarm64-scarthgap", "checkout_only": true}'
```

#### Interactive REST documentation

Navigate to **`http://localhost:8080/docs`** for the full Swagger / OpenAPI UI or **`http://localhost:8080/redoc`** for ReDoc.

### GraphQL API (`/graphql`)

Navigate to **`http://localhost:8080/graphql`** for the interactive GraphiQL editor.

#### Queries

```graphql
# List all devices
{ devices { slug description vendor socVendor } }

# List all BSP presets
{ bsp { name description device release features } }

# List releases compatible with a specific device
{ releases(device: "qemuarm64") { slug description yoctoVersion } }

# List features, distros, frameworks, and containers
{ features { slug description compatibleWith }
  distros { slug description framework }
  frameworks { slug vendor }
  containers { name image } }
```

#### Mutations

```graphql
# Export BSP config by preset name
mutation {
  exportBsp(bspName: "poky-qemuarm64-scarthgap") {
    yamlContent
  }
}

# Export by components
mutation {
  exportBsp(device: "qemuarm64", release: "scarthgap") {
    yamlContent
  }
}

# Validate (checkout only) without building
mutation {
  buildBsp(bspName: "poky-qemuarm64-scarthgap", checkoutOnly: true) {
    status
    message
  }
}

# Run a command in the build container
mutation {
  shellCommand(bspName: "poky-qemuarm64-scarthgap", command: "bitbake -e") {
    returnCode
    output
  }
}
```

### Python API — embedding the server

You can also embed the server directly in Python code:

```python
import uvicorn
from bsp.server import create_app

app = create_app(registry_path="/path/to/bsp-registry.yaml")
uvicorn.run(app, host="0.0.0.0", port=8080)
```

Or reuse an already-initialised `BspManager`:

```python
from bsp import BspManager
from bsp.server import create_app
import uvicorn

manager = BspManager("bsp-registry.yaml")
manager.initialize()

app = create_app(manager=manager)
uvicorn.run(app, host="0.0.0.0", port=8080)
```

## HIL Testing with LAVA and Robot Framework

`bsp-registry-tools` can submit Hardware-in-the-Loop (HIL) test jobs to a
[LAVA](https://lava.readthedocs.io/) server after or independently of a build.
Test jobs are rendered from a Jinja2 template and can run
[Robot Framework](https://robotframework.org/) suites inside the LAVA pipeline.

### Configuration overview

LAVA settings live in two places:

1. **Registry-level `lava:` block** — shared server settings (URL, token, timeouts).
   All values support `$ENV{}` expansion so credentials are never hardcoded.
2. **Per-preset `testing.lava:` block** — device type, artifact URL, LAVA tags,
   custom job template, and Robot Framework suites.

CLI flags (`--lava-server`, `--lava-token`, `--artifact-url`) override both.

### Minimal example

```yaml
# bsp-registry.yaml

specification:
  version: "2.2"

# Registry-level LAVA connection settings
lava:
  server: "$ENV{LAVA_SERVER}"      # e.g. https://lava.example.com
  token: "$ENV{LAVA_TOKEN}"        # LAVA API authentication token
  username: "$ENV{LAVA_USER}"      # LAVA username (optional)
  wait_timeout: 3600               # max seconds to wait for a job (default: 1 h)
  poll_interval: 30                # polling interval in seconds

registry:
  devices:
    - slug: qemuarm64
      description: "QEMU ARM64"
      vendor: qemu
      soc_vendor: arm
      includes:
        - kas/qemu/qemuarm64.yaml

  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS"
      distro: poky
      includes:
        - kas/scarthgap.yaml

  bsp:
    - name: poky-qemuarm64-scarthgap
      description: "Poky QEMU ARM64 Scarthgap"
      device: qemuarm64
      release: scarthgap
      build:
        container: debian-bookworm
        path: build/poky/qemuarm64/scarthgap
      # HIL test configuration
      testing:
        lava:
          device_type: "qemu-aarch64"          # LAVA device type label
          artifact_url: "http://files.ci/builds" # where the image is served
          tags: ["hil", "qemu"]                # optional LAVA scheduler tags
          job_template: "kas/lava/qemu.yaml.j2" # optional; builtin used if omitted
          robot:
            suites:
              - tests/robot/smoke.robot
              - tests/robot/boot.robot
            variables:
              BOARD_IP: "10.0.0.5"
              SSH_PORT: "22"
```

### LAVA job templates

When `job_template` is omitted a built-in minimal template is used (QEMU boot +
optional Robot Framework test action).  For real devices, create a Jinja2
template and point `job_template` at it.

A fully annotated example is provided at
[`examples/lava/job-template.yaml.j2`](examples/lava/job-template.yaml.j2).

**Available Jinja2 context variables:**

| Variable | Description |
|----------|-------------|
| `device_type` | LAVA device type label |
| `job_name` | Auto-composed from device/release/feature slugs |
| `image_url` | Full artifact URL (`artifact_url` + `build_path`) |
| `artifact_url` | Base artifact URL |
| `build_path` | Relative build output directory |
| `device_slug` | Device slug (e.g. `qemuarm64`) |
| `release_slug` | Release slug (e.g. `scarthgap`) |
| `feature_slugs` | List of active feature slugs |
| `lava_tags` | List of LAVA scheduler tags |
| `robot_suites` | List of Robot Framework `.robot` file paths |
| `robot_variables` | Dict of Robot Framework `--variable` pairs |
| `timeout_minutes` | Overall job timeout in minutes |

### Workflow examples

```bash
# Submit a LAVA job after a successful build and wait for results
bsp build poky-qemuarm64-scarthgap --test --wait

# Submit a LAVA test job for an already-built image
bsp test poky-qemuarm64-scarthgap --wait

# Override LAVA settings at the command line (useful in CI)
export LAVA_SERVER=https://lava.ci.example.com
export LAVA_TOKEN=mytoken
bsp test poky-qemuarm64-scarthgap \
  --artifact-url http://minio.example.com/builds \
  --wait

# Component-based test (no preset required)
bsp test --device qemuarm64 --release scarthgap \
  --lava-server https://lava.ci.example.com \
  --lava-token $LAVA_TOKEN \
  --wait
```

### Python API

```python
from bsp import BspManager, LavaClient, LavaTestSuite, build_lava_job

manager = BspManager("bsp-registry.yaml")
manager.initialize()

# Submit LAVA test and wait for results
passed = manager.test_bsp(
    "poky-qemuarm64-scarthgap",
    lava_server="https://lava.example.com",
    lava_token="mytoken",
    artifact_url="http://files.example.com/builds",
    wait=True,
)

# Use LavaClient directly
client = LavaClient(server="https://lava.example.com", token="mytoken")
job_id = client.submit_job(job_yaml_string)
health = client.wait_for_job(job_id, timeout=3600, poll_interval=30)
suites: list[LavaTestSuite] = client.get_job_results(job_id)
```


# Flash to USB drive (auto-selects the latest .wic image)
bsp flash poky-qemuarm64-scarthgap --target /dev/sda

# Flash a specific image file
bsp flash poky-qemuarm64-scarthgap --target /dev/mmcblk0 --image path/to/image.wic
```

## Registry Configuration Reference

The BSP registry is a YAML file following **schema v2.2**.  See [docs/registry-v2.md](docs/registry-v2.md) for the full reference.  For the HTTP server reference, see [docs/server.md](docs/server.md).  Key top-level sections:

### `specification`

```yaml
specification:
  version: "2.2"
```

### `include` (optional)

Split a large registry across multiple files using the `include` directive.
Paths are relative to the file that contains the directive.

```yaml
include:
  - devices/boards.yaml
  - releases/scarthgap.yaml
```

Each included file is merged before the root file's own content.  Lists
(e.g. `devices`, `releases`, `features`, `environment`) are concatenated; dicts
(e.g. `containers`, `environments`) are merged recursively; scalars use the root
file's value.
Included files can themselves contain further `include` directives, and
circular references are detected at load time.

See [docs/registry-v2.md](docs/registry-v2.md#include-optional) for full details.

### `environment`

Global build environment applied to all builds.  Groups `variables` (supports `$ENV{VAR_NAME}` expansion) and `copy` (file-copy entries executed inside the build environment before every build) under a single key.

```yaml
environment:
  variables:
    - name: "GITCONFIG_FILE"
      value: "$ENV{HOME}/.gitconfig"
    - name: "DL_DIR"
      value: "$ENV{HOME}/yocto-cache/downloads"
    - name: "SSTATE_DIR"
      value: "$ENV{HOME}/yocto-cache/sstate"
  copy:
    - scripts/global-setup.sh: build/
    - config/global.conf: build/conf/
```

Both `variables` and `copy` are optional.  Global copies are merged first, before named-environment and device copies.

### `environments`

Named environments bundle a container reference, environment variables, and optional file-copy entries together.  The special name `"default"` is used by any release that does not explicitly name an environment.

```yaml
environments:
  default:
    container: "debian-bookworm"
    variables:
      - name: "DL_DIR"
        value: "$ENV{HOME}/yocto-cache/downloads"
  isar-build:
    container: "isar-debian-trixie"
    variables:
      - name: "DL_DIR"
        value: "$ENV{HOME}/isar-cache/downloads"
    # Copy the QEMU run script into every Isar build directory
    copy:
      - isar/scripts/isar-runqemu.sh: build/
```

### `containers`

Docker container definitions for build environments:

```yaml
containers:
  debian-bookworm:
    image: "my-registry/debian/kas:5.1"
    file: Dockerfile
    args:
      - name: "DISTRO"
        value: "debian-bookworm"
      - name: "KAS_VERSION"
        value: "5.1"
  isar-container:
    image: "my-registry/isar/kas:5.1"
    file: Dockerfile.isar
    args: []
    privileged: true    # Run container in privileged mode (required for ISAR builds)
    runtime_args: "-p 2222:2222"  # Extra flags passed to the container engine
```

**Container fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `image` | string | — | Docker image name/tag |
| `file` | string | — | Path to Dockerfile for building the image |
| `args` | list | `[]` | Docker build arguments (`name`/`value` pairs) |
| `privileged` | boolean | `false` | Run container with elevated privileges. Required for ISAR builds. |
| `runtime_args` | string | — | Extra flags appended to the container engine `run` invocation (e.g. port-forwarding, `--device` access). Forwarded via `--runtime-args`. |

### `registry.devices`

Hardware device/board definitions:

```yaml
registry:
  devices:
    - slug: qemuarm64
      description: "QEMU ARM64 (emulated)"
      vendor: qemu
      soc_vendor: arm
      includes:
        - kas/qemu/qemuarm64.yaml
```

### `registry.releases`

Yocto/Isar release definitions referencing a distro:

```yaml
registry:
  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS (Scarthgap)"
      distro: poky
      yocto_version: "5.0"
      includes:
        - kas/scarthgap.yaml
```

### `registry.features`

Optional feature definitions that can be enabled per-build.  Features declare
their own KAS includes and can restrict themselves to specific frameworks/distros
(`compatible_with`), board vendors (`compatibility`), and/or releases
(`release_overrides`).

```yaml
registry:
  features:
    - slug: ostree
      description: "Enable OSTree support in the Yocto image"
      compatible_with: [yocto]   # restrict to Yocto framework
      includes:
        - features/ota/ostree/ostree.yml   # always included when feature is enabled
      release_overrides:
        - release: scarthgap
          includes:
            - features/ota/ostree/ostree-scarthgap.yml  # only for Scarthgap
        - release: styhead
          includes:
            - features/ota/ostree/ostree-styhead.yml    # only for Styhead
      vendor_overrides:
        - vendor: advantech
          soc_vendors:
            - vendor: nxp
              includes:
                - features/ota/ostree/modular-bsp-ota-nxp.yml  # only for Advantech NXP boards
```

See [docs/registry-v2.md](docs/registry-v2.md#registryfeatures) for the full
reference including `compatibility`, `local_conf`, `env`, and all override fields.

### `registry.bsp`

Named presets — device + release(s) + optional features:

```yaml
registry:
  bsp:
    # Single-release preset (backward compatible)
    - name: poky-qemuarm64-scarthgap
      description: "Poky QEMU ARM64 Scarthgap (Yocto 5.0 LTS)"
      device: qemuarm64
      release: scarthgap
      features: []
      build:              # optional: override container and/or output path
        container: "debian-bookworm"
        path: build/poky-qemuarm64-scarthgap
      testing:            # optional: LAVA HIL test configuration
        lava:
          device_type: "qemu-aarch64"
          artifact_url: "http://files.ci/builds"
          tags: ["hil"]
          job_template: "kas/lava/qemu.yaml.j2"   # optional; builtin used if absent
          robot:
            suites:
              - tests/robot/smoke.robot
            variables:
              BOARD_IP: "10.0.0.5"

    # Multi-release preset: use "releases" (plural) to avoid repeating the
    # same entry for every Yocto release.  The resolver expands this into one
    # preset per release, named "{name}-{release_slug}":
    #   poky-qemuarm64-scarthgap  (auto-composed path: build/poky-qemuarm64-scarthgap)
    #   poky-qemuarm64-styhead    (auto-composed path: build/poky-qemuarm64-styhead)
    # The "testing" block (and "deploy", "local_conf", "targets") is inherited
    # by every expanded preset, so a single testing block covers all releases.
    - name: poky-qemuarm64
      description: "Poky QEMU ARM64"
      device: qemuarm64
      releases: [scarthgap, styhead]
      features: [systemd, debug]
      build:              # optional: container override (path is always auto-composed)
        container: "debian-bookworm"
      testing:            # inherited by poky-qemuarm64-scarthgap AND poky-qemuarm64-styhead
        lava:
          device_type: "qemu-aarch64"
          artifact_url: "http://files.ci/builds"
          tags: ["hil", "qemu"]
          robot:
            suites:
              - tests/robot/smoke.robot
            variables:
              BOARD_IP: "10.0.0.5"
```

> **Note**: `release` (singular) and `releases` (plural) are mutually exclusive.
> Exactly one must be specified per preset entry.  When `releases` is used, all
> non-build fields (`features`, `local_conf`, `targets`, `deploy`, `testing`) are
> inherited unchanged by every expanded preset.  Build paths are computed per
> release as `{build.path or "build/{name}"}-{release_slug}`.  You can therefore
> test every release in the list with a single `testing` block:
>
> ```bash
> bsp test poky-qemuarm64-scarthgap --wait
> bsp test poky-qemuarm64-styhead --wait
> ```

### `deploy` (optional)

Global cloud deployment configuration applied to all builds.  An individual
`BspPreset` can also include a `deploy:` block that overrides specific settings
for that preset (see [Per-preset override](#per-preset-deploy-override) below).

```yaml
deploy:
  provider: azure                                   # "azure" (default) or "aws"
  account_url: $ENV{AZURE_STORAGE_ACCOUNT_URL}      # Azure only; supports $ENV{} expansion
  container: bsp-artifacts                          # Azure container name
  # bucket: my-s3-bucket                           # AWS alternative to container
  prefix: "{vendor}/{device}/{release}/{date}"      # remote path prefix template
  patterns:                                         # glob patterns for files to upload
    - "**/*.wic.gz"
    - "**/*.wic.bz2"
    - "**/*.tar.bz2"
    - "**/*.ext4"
    - "**/*.sdimg"
  artifact_dirs:                                    # subdirs under build_path to search
    - tmp/deploy/images
    - tmp/deploy/sdk
  include_manifest: true                            # upload a JSON manifest of all artifacts
  include_build_manifest: true                      # upload build-manifest.json from the build dir
```

**Prefix template variables:**

| Variable | Value |
|----------|-------|
| `{device}` | Device slug |
| `{release}` | Release slug |
| `{distro}` | Effective distro slug |
| `{vendor}` | Device vendor slug |
| `{date}` | Build date in `YYYY-MM-DD` format |
| `{datetime}` | Build datetime in `YYYYMMDD-HHMMSS` format |

#### Per-preset deploy override

Add a `deploy:` block directly on a `BspPreset` to override specific global
deploy settings for that preset.  Only fields that differ from their default
values override the global config; other fields keep the global value.
CLI flags (`--provider`, `--container`, …) are applied last.

```yaml
deploy:                               # global: Azure, shared container
  provider: azure
  account_url: $ENV{AZURE_STORAGE_ACCOUNT_URL}
  container: bsp-artifacts

registry:
  bsp:
    # Uses global settings unchanged.
    - name: qemuarm64-scarthgap
      device: qemuarm64
      release: scarthgap
      features: []

    # Overrides only container and prefix; provider/account_url come from global.
    - name: imx8mp-adv-scarthgap-release
      device: imx8mp-adv
      release: scarthgap
      features: []
      deploy:
        container: imx8mp-release-artifacts         # ← override
        prefix: "release/{device}/{release}/{date}" # ← override
        patterns:
          - "**/*.wic.gz"                           # ← override

    # Switches to AWS entirely for this preset.
    - name: aws-build-scarthgap
      device: qemuarm64
      release: scarthgap
      features: []
      deploy:
        provider: aws                 # ← override: switch provider
        container: my-s3-bucket       # ← override: bucket name
```

See [docs/artifact-deployment.md](docs/artifact-deployment.md) for full details.

### `flash` (optional)

Global SD-card / block-device flashing configuration applied to all presets.  A
`BspPreset` can also include a `flash:` block to override specific settings for
that preset.  All fields have sensible defaults; the `flash:` block is not
required to use `bsp flash`.

```yaml
flash:
  tool: bmaptool                  # "bmaptool" (default) | "dd" | "uuu"
  image_patterns:                 # glob patterns, tried in order (first match wins)
    - "**/{build_target}-*.wic.*" # expanded at runtime when --target is given (first priority)
    - "**/*.wic.bz2"
    - "**/*.wic.gz"
    - "**/*.wic.xz"
    - "**/*.wic"
    - "**/*.sdimg"
    - "**/*.rpi-sdimg"
  artifact_dirs:                  # subdirs under build_path to search
    - "tmp/deploy/images"
  extra_args: null                # extra CLI args forwarded verbatim to the flash tool
```

**`flash` fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `tool` | string | `"bmaptool"` | Flash tool: `"bmaptool"` (uses block-map for fast, verified flashing), `"dd"` (raw copy), or `"uuu"` (NXP mfgtools) |
| `image_patterns` | list[str] | See above | Glob patterns for flashable image discovery, evaluated in order. Patterns may contain `{build_target}` which is expanded to the BitBake target name when `bsp build --target <name> --flash ...` or `bsp flash --build-target <name>` is used; the exact target pattern `**/<target>.wic.*` is also prepended automatically as the highest-priority entry. |
| `artifact_dirs` | list[str] | `["tmp/deploy/images"]` | Subdirectories under the build output path to search |
| `extra_args` | string (opt.) | `null` | Extra arguments forwarded verbatim to the flash tool (e.g. `"--nobmap"`) |

#### Per-preset flash override

```yaml
flash:                            # global: bmaptool
  tool: bmaptool

registry:
  bsp:
    # Uses global settings unchanged.
    - name: imx8mp-adv-scarthgap
      device: imx8mp-adv
      release: scarthgap

    # Overrides extra_args for this preset (e.g. skip block-map verification).
    - name: rpi4-scarthgap
      device: rpi4
      release: scarthgap
      flash:
        extra_args: "--nobmap"
```

See [docs/sd-card-flashing.md](docs/sd-card-flashing.md) for full details.

### `lava` (optional)

Top-level LAVA server settings shared across all presets.  All values support
`$ENV{}` expansion.

```yaml
lava:
  server: "$ENV{LAVA_SERVER}"   # LAVA server base URL (required for bsp test)
  token: "$ENV{LAVA_TOKEN}"     # API authentication token
  username: "$ENV{LAVA_USER}"   # Username (optional)
  wait_timeout: 3600            # Maximum seconds to wait for a job (default: 3600)
  poll_interval: 30             # Polling interval in seconds (default: 30)
```

**`lava` fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `server` | string | — | LAVA server base URL (e.g. `https://lava.example.com`) |
| `token` | string | `""` | LAVA API authentication token |
| `username` | string | `""` | LAVA username |
| `wait_timeout` | integer | `3600` | Maximum wait time in seconds when `--wait` is used |
| `poll_interval` | integer | `30` | Job status polling interval in seconds |


## KAS Configuration Files

KAS configuration files define Yocto layer repositories, machine settings, and build targets. See the [examples/kas/](examples/kas/) directory for reference configurations.

### QEMU Example Configurations

The `examples/` directory contains ready-to-use KAS configurations for QEMU targets:

| File | Description |
|------|-------------|
| `examples/kas/yocto/releases/scarthgap.yaml` | Yocto Scarthgap (5.0 LTS) base configuration |
| `examples/kas/yocto/releases/styhead.yaml` | Yocto Styhead (5.1) base configuration |
| `examples/kas/yocto/releases/walnascar.yaml` | Yocto Walnascar (5.2) base configuration |
| `examples/kas/devices/qemu/qemuarm64.yaml` | QEMU ARM64 machine configuration |
| `examples/kas/devices/qemu/qemuarm.yaml` | QEMU ARM (32-bit) machine configuration |
| `examples/kas/devices/qemu/qemux86-64.yaml` | QEMU x86-64 machine configuration |
| `examples/kas/isar/` | Isar build-system example configurations |

### KAS File Structure

```yaml
header:
  version: 14
  includes:            # Optional: include other KAS files
    - base.yaml

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
from bsp import BspManager, EnvironmentManager, KasManager, RegistryFetcher

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
    kas_files=["kas/scarthgap.yaml", "kas/qemu/qemuarm64.yaml"],
    build_dir="build/my-bsp",
    use_container=False,
)
kas.validate_kas_files()
```

### Starting the HTTP server programmatically

```python
import uvicorn
from bsp.server import create_app

# Create and run the server (requires bsp-registry-tools[server])
app = create_app(registry_path="bsp-registry.yaml")
uvicorn.run(app, host="0.0.0.0", port=8080)
```

### Cloud Deployment API

```python
from bsp import BspManager

manager = BspManager("bsp-registry.yaml")
manager.initialize()

# Deploy artifacts from a preset build (dry-run)
result = manager.deploy_bsp("poky-qemuarm64-scarthgap", dry_run=True)
print(f"Would upload {result.success_count} artifact(s)")

# Deploy with overrides
result = manager.deploy_bsp(
    "poky-qemuarm64-scarthgap",
    deploy_overrides={
        "provider": "aws",
        "container": "my-s3-bucket",
        "prefix": "builds/{device}/{release}/{date}",
    },
)
for artifact in result.artifacts:
    print(f"  {artifact.local_path.name} → {artifact.remote_url}")

# Deploy by components
result = manager.deploy_by_components(
    device_slug="qemuarm64",
    release_slug="scarthgap",
)

# Use the storage backend and deployer directly
from bsp.storage import create_backend
from bsp.deployer import ArtifactDeployer
from bsp.models import DeployConfig

config = DeployConfig(
    provider="azure",
    container="bsp-artifacts",
    prefix="{device}/{release}/{date}",
    patterns=["**/*.wic.gz"],
)
backend = create_backend("azure", container_name="bsp-artifacts", dry_run=True)
deployer = ArtifactDeployer(config, backend)
result = deployer.deploy("build/poky-qemuarm64-scarthgap", device="qemuarm64", release="scarthgap")
```

## Development

### Setup Development Environment

```bash
git clone https://github.com/Advantech-EECC/bsp-registry-tools.git
cd bsp-registry-tools
pip install -e .
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
├── bsp/
│   ├── __init__.py           # Public API exports
│   ├── cli.py                # CLI entry point (bsp command)
│   ├── cli_runner.py         # Module runner shim for GUI subprocesses
│   ├── gui.py                # Interactive TUI launcher (bsp-explorer / bsp-explorer-web commands)
│   ├── bsp_manager.py        # Main BSP coordinator (build, shell, flash, export)
│   ├── registry_fetcher.py   # Remote registry clone/update
│   ├── remotes_manager.py    # Persistent named-remote CRUD (bsp remotes)
│   ├── kas_manager.py        # KAS build system integration
│   ├── environment.py        # Environment variable management
│   ├── path_resolver.py      # Path utilities
│   ├── models.py             # Dataclass models (v2.2 schema)
│   ├── resolver.py           # V2 resolver: device + release + features → ResolvedConfig
│   ├── registry_writer.py    # RegistryWriter: CRUD + validation for registry entities
│   ├── lava_client.py        # LAVA REST API wrapper (submit, poll, results)
│   ├── lava_job_builder.py   # Jinja2 LAVA job YAML renderer
│   ├── gatherer.py           # ArtifactGatherer: download build artifacts from cloud
│   ├── deployer.py           # ArtifactDeployer: collect & upload build artifacts
│   ├── utils.py              # YAML / Docker utilities
│   ├── exceptions.py         # Custom exceptions
│   ├── server/               # Optional HTTP server (requires [server] extras)
│   │   ├── __init__.py       # Exports create_app
│   │   ├── app.py            # FastAPI application factory
│   │   ├── rest.py           # REST router (/api/v1/*)
│   │   ├── graphql_schema.py # Strawberry GraphQL schema
│   │   └── types.py          # Pydantic response models
│   └── storage/              # Cloud storage backends
│       ├── __init__.py       # Exports CloudStorageBackend and create_backend()
│       ├── base.py           # Abstract CloudStorageBackend base class
│       ├── azure.py          # AzureStorageBackend (azure-storage-blob)
│       ├── aws.py            # AwsStorageBackend (boto3)
│       └── factory.py        # create_backend() factory function
├── pyproject.toml            # Package configuration
├── README.md                 # This file
├── LICENSE                   # Apache 2.0 License
├── docs/
│   ├── registry-v2.md        # Full v2.2 schema reference
│   ├── registry-v1.md        # Legacy v1.0 schema reference
│   ├── migration-v1-to-v2.md # Migration guide from v1 to v2
│   ├── server.md             # HTTP server (REST + GraphQL) reference
│   └── artifact-deployment.md # Cloud deployment guide (Azure / AWS)
│   └── screenshots/          # TUI screenshots
│   └── screenshots/          # TUI and web screenshots (bsp-launcher-tui.svg, bsp-explorer-web.svg)
├── tests/
│   ├── conftest.py
│   ├── test_bsp_manager.py
│   ├── test_cli_basic.py
│   ├── test_cli_remote_flags.py
│   ├── test_deploy.py        # Deployment tests
│   ├── test_gatherer.py      # Gather (download) tests
│   ├── test_lava_client.py   # LAVA client unit tests (HTTP mocked)
│   ├── test_lava_job_builder.py # LAVA job template renderer tests
│   ├── test_models.py
│   ├── test_kas_manager.py
│   ├── test_environment.py
│   ├── test_path_resolver.py
│   ├── test_registry_fetcher.py
│   └── test_utils.py
├── examples/
│   ├── bsp-registry.yaml      # Sample v2.0 BSP registry for QEMU targets
│   ├── bsp-registry.devices.yaml # Devices include fragment example
│   ├── lava/
│   │   └── job-template.yaml.j2  # Annotated example LAVA job Jinja2 template
│   └── kas/
│       ├── yocto/             # Yocto Project KAS configurations
│       │   ├── releases/      # Per-release KAS files (scarthgap, styhead, walnascar, …)
│       │   ├── devices/       # Yocto-specific device KAS files (qemuarm64, qemuarm, …)
│       │   ├── distro/        # Distro fragments (poky, harden)
│       │   └── features/      # Feature KAS files (systemd, debug, ssh, …)
│       ├── isar/              # Isar build system KAS configurations
│       ├── devices/qemu/      # Shared QEMU device configurations (qemuarm64, qemux86-64, …)
│       └── vendors/qemu/      # Vendor-level shared KAS fragments
└── .github/
    └── workflows/
        ├── tests.yml          # CI: run tests on push/PR
        ├── cli-tests.yml      # CI: integration CLI tests
        └── publish.yml        # CD: publish to PyPI on release
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
| `BspManager` | Main coordinator for BSP operations (build, shell, export, flash) |
| `KasManager` | Handles KAS build system operations |
| `EnvironmentManager` | Manages build environment variables with `$ENV{}` expansion |
| `PathResolver` | Utility for path resolution and validation |
| `RegistryFetcher` | Clones/updates a remote git-hosted BSP registry to a local cache |
| `RemotesManager` | Reads/writes `~/.config/bsp/remotes.yaml` — CRUD for named remote registry sources |
| `bsp.server.create_app` | Factory that creates a FastAPI app with REST + GraphQL endpoints |
| `ArtifactDeployer` | Discovers and uploads Yocto build artifacts to cloud storage |
| `ArtifactGatherer` | Downloads previously uploaded Yocto build artifacts from cloud storage |
| `AzureStorageBackend` | Azure Blob Storage backend (requires `azure-storage-blob`) |
| `AwsStorageBackend` | AWS S3 backend (requires `boto3`) |
| `LavaClient` | LAVA REST API wrapper — submit, poll, and fetch results for HIL test jobs |


### Data Classes

| Class | Description |
|-------|-------------|
| `RegistryRoot` | Root registry container (specification, registry, containers, environments, deploy, lava) |
| `Registry` | Contains devices, releases, features, presets, frameworks, and distros |
| `Device` | Hardware device/board definition (slug, vendor, soc_vendor, includes) |
| `Release` | Yocto/Isar release definition (slug, distro reference, includes) |
| `Feature` | Optional BSP feature (slug, includes, compatibility constraints, release_overrides, vendor_overrides) |
| `BspPreset` | Named preset combining device + release + features + optional deploy and testing configs |
| `Framework` | Build-system framework definition (e.g. Yocto, Isar) |
| `Distro` | Linux distribution definition (e.g. Poky, Isar distro) |
| `Docker` | Docker image, build arg, privileged mode, and runtime_args configuration |
| `NamedEnvironment` | Named environment bundling a container reference, variables, and optional copy entries |
| `EnvironmentVariable` | Name/value pair with `$ENV{}` expansion support |
| `DeployConfig` | Cloud deployment configuration (provider, container/bucket, prefix, patterns, artifact dirs) |
| `DeployResult` | Result of a deployment run: list of uploaded artifacts with URLs and checksums |
| `GatherResult` | Result of a gather run: list of local paths for downloaded artifacts |
| `LavaServerConfig` | Registry-level LAVA server connection settings (server, token, timeouts) |
| `LavaTestConfig` | Per-preset LAVA test settings (device_type, artifact_url, tags, job_template, robot) |
| `RobotTestConfig` | Robot Framework suite list and variable dict embedded in a LAVA job |
| `TestingConfig` | Top-level testing block on a `BspPreset` (currently wraps `LavaTestConfig`) |


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
