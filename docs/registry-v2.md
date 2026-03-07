# BSP Registry Schema v2.0

This document describes the v2.0 registry YAML schema used by `bsp-registry-tools`.

---

## Overview

Schema v2.0 separates the registry into four independent sections:

| Section     | Purpose                                                    |
|-------------|------------------------------------------------------------|
| `devices`   | Hardware board/device definitions                          |
| `releases`  | Yocto / Isar release definitions                           |
| `features`  | Optional feature definitions (OTA, secure-boot, …)        |
| `bsp`       | Optional named presets (device + release + features)       |

Builds can be driven either by a **named preset** (`bsp build my-preset`) or by
composing components directly (`bsp build --device <d> --release <r>`).

---

## Top-level Structure

```yaml
specification:
  version: "2.0"          # required

environment:              # optional – global env vars for all builds
  - name: "DL_DIR"
    value: "$ENV{HOME}/downloads"

environments:             # optional – named build environments
  default:                # special name: used when release has no environment field
    container: "debian-bookworm"
    variables:
      - name: "DL_DIR"
        value: "$ENV{HOME}/downloads"

containers:               # optional – Docker container definitions (dict)
  debian-bookworm:
    image: "my-registry/debian/kas:5.1"
    file: Dockerfile
    args:
      - name: "KAS_VERSION"
        value: "5.1"

registry:
  devices: [...]          # list of device definitions
  releases: [...]         # list of release definitions
  features: [...]         # list of feature definitions (may be empty)
  bsp: [...]              # optional list of named presets
```

---

## `specification`

```yaml
specification:
  version: "2.0"
```

The tool will exit with a clear error if `version` is not `"2.0"`.

---

## `environment` (optional)

Global environment variables applied to all builds.  Values support
`$ENV{VAR}` expansion against the host shell environment.

```yaml
environment:
  - name: "DL_DIR"
    value: "$ENV{HOME}/data/cache/downloads"
  - name: "SSTATE_DIR"
    value: "$ENV{HOME}/data/cache/sstate"
  - name: "GITCONFIG_FILE"
    value: "$ENV{HOME}/.gitconfig"
```

---

## `containers` (optional)

Docker container definitions used as build environments.  Containers are
referenced from `devices[*].build.container` **or** from
`environments[*].container`.

```yaml
containers:
  debian-bookworm:        # container name / key
    image: "bsp/debian/kas:5.1"   # Docker image (used at runtime)
    file: Dockerfile              # optional: path to Dockerfile for `docker build`
    args:                         # optional: Docker build-args
      - name: "DISTRO"
        value: "debian-bookworm"
      - name: "KAS_VERSION"
        value: "5.1"

  isar-qemu:
    image: "ghcr.io/ilbers/isar:latest"
    file: null
    args: []
    # Optional: extra arguments appended to the container engine `run` command.
    # Passed to kas-container via the KAS_CONTAINER_ARGS environment variable.
    runtime_args: "-p 2222:2222 --device=/dev/net/tun --cap-add=NET_ADMIN"
```

### `containers[*]` fields

| Field           | Type          | Description                                                    |
|-----------------|---------------|----------------------------------------------------------------|
| `image`         | string (opt.) | Docker image to use at runtime                                 |
| `file`          | string (opt.) | Path to Dockerfile for `docker build`                          |
| `args`          | list          | Docker build arguments (`name`/`value` pairs)                  |
| `runtime_args`  | string (opt.) | Extra flags appended to the container engine `run` invocation. Forwarded to `kas-container` via `KAS_CONTAINER_ARGS`. Useful for port-forwarding, device access (`--device`), or capability grants (`--cap-add`). |

> The legacy **list** format (`- debian-bookworm: {…}`) is still accepted for
> backward compatibility in the containers section.

---

## `environments` (optional)

Named build environments bundle a **container reference** and optional
**environment variables** together under a single name.  This makes it
easy to associate a specific container image and variable set with a
particular class of releases (e.g., a separate Isar container).

```yaml
environments:
  default:                    # used for any release that does not name an environment
    container: "debian-bookworm"
    variables:
      - name: "DL_DIR"
        value: "$ENV{HOME}/data/cache/downloads"
      - name: "SSTATE_DIR"
        value: "$ENV{HOME}/data/cache/sstate"

  isar-build:                 # named environment for Isar releases
    container: "debian-bookworm-isar"
    variables:
      - name: "DL_DIR"
        value: "$ENV{HOME}/data/cache/isar-downloads"
```

### Resolution rules

1. If `release.environment` is set, the resolver looks up that name in
   `environments`.  If not found, the tool exits with a clear error.
2. If `release.environment` is **not** set, the resolver uses the
   `"default"` named environment (if defined).
3. If no named environment applies, the device's `build.container` (if set)
   and the root `environment` variable list are used as before.

### Container priority

| Source | Priority |
|--------|----------|
| `device.build.container` | **Highest** – explicit device override |
| Named environment container | Used when device has no container set |
| None | No container (bare `kas` run) |

### Variable merging

Named environment variables are merged **on top of** the root-level
`environment` list (root vars first, named-env vars win on conflict).
Feature-level `env` variables are applied last.

---

## `registry.devices`

Each device represents a specific hardware board or emulated target.

```yaml
registry:
  devices:
    - slug: imx8mp-adv-board         # unique identifier (used in CLI / presets)
      description: "Advantech i.MX8M Plus board"
      vendor: advantech              # board vendor
      soc_vendor: nxp                # silicon vendor (used in feature compat checks)
      soc_family: imx8               # optional SoC family
      build:
        container: "debian-bookworm" # optional – references containers section
                                     # if omitted, the named environment's container is used
        path: build/imx8mp-adv       # build output directory
        includes:                    # device-specific KAS files
          - kas/boards/imx8mp-adv.yaml
        local_conf:                  # optional extra local.conf lines
          - "MACHINE_EXTRA_RDEPENDS += 'kernel-modules'"
        copy:                        # optional files to copy before the build
          - scripts/setup.sh: build/imx8mp-adv/
```

### `devices[*].build` fields

| Field        | Type              | Description                                           |
|--------------|-------------------|-------------------------------------------------------|
| `container`  | string (opt.)     | Container name (key in `containers` section). Omit to rely on the named environment's container. |
| `path`       | string            | Build output directory                                |
| `includes`   | list[str]         | Device-specific KAS configuration files               |
| `local_conf` | list[str]         | Lines appended to `local.conf` for this device        |
| `copy`       | list[dict[str, str]] | Files to copy into the build tree before the build starts. Each entry is a single-key dict `{"source": "destination"}`. Both paths are resolved relative to the registry file's parent directory. If the destination ends with `/` or is an existing directory, the source filename is preserved. |

---

## `registry.releases`

Releases define Yocto / Isar base configurations shared across multiple devices.

```yaml
registry:
  releases:
    - slug: scarthgap                # unique identifier
      description: "Yocto 5.0 LTS (Scarthgap)"
      yocto_version: "5.0"           # optional Yocto version string
      isar_version: null             # optional Isar version string
      # environment: default         # optional – name of the environment to use
      includes:                      # base KAS files for this release
        - kas/scarthgap.yaml
      vendor_includes:               # optional vendor-specific overrides
        - vendor: advantech
          includes:
            - kas/advantech/scarthgap-vendor.yaml

    - slug: isar-v0.11
      description: "Isar v0.11"
      environment: isar-build        # use the 'isar-build' named environment
      includes:
        - kas/isar/v0.11.yaml
```

The optional `environment` field names an entry from the top-level
`environments` dict.  When omitted, the `"default"` named environment is
used (if defined).  See [Named environments](#environments-optional) for
full resolution rules.

### `releases[*].vendor_includes`

When a device's `vendor` matches a `vendor_includes` entry, those additional KAS
files are added **after** the base release includes.

> **Note:** In v2.0, `vendor_includes` is stored in the registry for informational
> purposes.  The resolver uses `device.vendor` to select relevant vendor overrides
> automatically (this is on the roadmap for a future resolver improvement).

---

## `registry.features`

Features are optional add-ons (OTA update, secure boot, …) that can be enabled
per-build.  Each feature can declare device compatibility constraints.

```yaml
registry:
  features:
    - slug: ota                      # unique identifier
      description: "Over-the-Air Update support via SWUpdate"
      includes:                      # feature-specific KAS files
        - kas/features/ota.yaml
      local_conf:                    # lines appended to local.conf
        - "DISTRO_FEATURES:append = ' swupdate'"
      env: []                        # feature-specific env vars (optional)
      # No compatibility block = works with ALL devices

    - slug: secure-boot
      description: "Secure Boot (NXP HABv4 / AHAB)"
      compatibility:
        soc_vendor:                  # empty list = all; non-empty = allow-list
          - nxp
        # vendor: []                 # optional vendor filter (empty = all)
        # soc_family: []             # optional soc_family filter
      includes:
        - kas/features/secure-boot.yaml
      env:
        - name: "SIGNING_KEY"
          value: "$ENV{SIGNING_KEY}"
```

### Feature compatibility rules

| `compatibility` key | Meaning                                           |
|---------------------|---------------------------------------------------|
| `vendor`            | Allow-list of board vendor names (empty = all)    |
| `soc_vendor`        | Allow-list of SoC vendor names (empty = all)      |
| `soc_family`        | Allow-list of SoC family strings (empty = all)    |

If any constraint fails, the build exits with a clear error message.

---

## `registry.bsp` (optional presets)

Named presets are convenience shortcuts for a device + release + features
combination.  They are optional — builds can also be triggered by passing
`--device`/`--release` flags directly on the CLI.

```yaml
registry:
  bsp:
    - name: imx8mp-adv-scarthgap     # unique preset name
      description: "Advantech i.MX8MP Scarthgap baseline"
      device: imx8mp-adv-board       # references devices[*].slug
      release: scarthgap             # references releases[*].slug
      features: []                   # optional list of feature slugs

    - name: imx8mp-adv-scarthgap-ota
      description: "Advantech i.MX8MP Scarthgap with OTA"
      device: imx8mp-adv-board
      release: scarthgap
      features:
        - ota
```

---

## Full Example

```yaml
specification:
  version: "2.0"

# Global environment variables (applied to all builds as a base)
environment:
  - name: "GITCONFIG_FILE"
    value: "$ENV{HOME}/.gitconfig"

# Named environments: bundle a container + variables under a name
environments:
  default:                              # used by all releases unless overridden
    container: "debian-bookworm"
    variables:
      - name: "DL_DIR"
        value: "$ENV{HOME}/data/cache/downloads"
      - name: "SSTATE_DIR"
        value: "$ENV{HOME}/data/cache/sstate"

  isar-build:                           # used only by Isar releases
    container: "debian-bookworm-isar"
    variables:
      - name: "DL_DIR"
        value: "$ENV{HOME}/data/cache/isar-downloads"
      - name: "SSTATE_DIR"
        value: "$ENV{HOME}/data/cache/isar-sstate"

containers:
  debian-bookworm:
    image: "bsp/registry/debian/kas:5.1"
    file: Dockerfile
    args:
      - name: "DISTRO"
        value: "debian-bookworm"
      - name: "KAS_VERSION"
        value: "5.1"
  debian-bookworm-isar:
    image: "bsp/registry/debian/isar-kas:1.2"
    file: Dockerfile.isar
    args:
      - name: "KAS_VERSION"
        value: "1.2"

registry:
  devices:
    - slug: imx8mp-adv
      description: "Advantech i.MX8M Plus"
      vendor: advantech
      soc_vendor: nxp
      soc_family: imx8
      build:
        # No container specified – uses the active named environment's container
        path: build/imx8mp-adv
        includes:
          - kas/boards/imx8mp-adv.yaml

    - slug: qemuarm64
      description: "QEMU ARM64 (emulated)"
      vendor: qemu
      soc_vendor: arm
      build:
        container: "debian-bookworm"   # explicit override (still valid)
        path: build/qemuarm64
        includes:
          - kas/qemu/qemuarm64.yaml

  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS (Scarthgap)"
      yocto_version: "5.0"
      # No environment field → uses 'default' named environment
      includes:
        - kas/scarthgap.yaml
      vendor_includes:
        - vendor: advantech
          includes:
            - kas/advantech/scarthgap-vendor.yaml

    - slug: styhead
      description: "Yocto 5.1 (Styhead)"
      yocto_version: "5.1"
      includes:
        - kas/styhead.yaml

    - slug: isar-v0.11
      description: "Isar v0.11"
      environment: isar-build          # use the 'isar-build' named environment
      includes:
        - kas/isar/v0.11.yaml

  features:
    - slug: ota
      description: "Over-the-Air Update via SWUpdate"
      includes:
        - kas/features/ota.yaml
      local_conf:
        - "DISTRO_FEATURES:append = ' swupdate'"

    - slug: secure-boot
      description: "Secure Boot (NXP HABv4 / AHAB)"
      compatibility:
        soc_vendor:
          - nxp
      includes:
        - kas/features/secure-boot.yaml
      env:
        - name: "SIGNING_KEY"
          value: "$ENV{SIGNING_KEY}"

  bsp:
    - name: imx8mp-adv-scarthgap
      description: "Advantech i.MX8MP Scarthgap baseline"
      device: imx8mp-adv
      release: scarthgap
      features: []

    - name: imx8mp-adv-scarthgap-ota
      description: "Advantech i.MX8MP Scarthgap with OTA"
      device: imx8mp-adv
      release: scarthgap
      features:
        - ota

    - name: qemuarm64-scarthgap
      description: "QEMU ARM64 Scarthgap"
      device: qemuarm64
      release: scarthgap
      features: []
```

---

## CLI Examples

```bash
# List all BSP presets
bsp list

# List all devices
bsp list devices

# List all releases
bsp list releases

# List all features (with compatibility info)
bsp list features

# Build a named preset
bsp build imx8mp-adv-scarthgap

# Build by specifying components directly (no preset needed)
bsp build --device qemuarm64 --release scarthgap

# Build with optional features
bsp build --device imx8mp-adv --release scarthgap --feature ota

# Build with multiple features
bsp build --device imx8mp-adv --release scarthgap --feature ota --feature secure-boot

# Export KAS configuration for a preset
bsp export imx8mp-adv-scarthgap

# Export by components to a file
bsp export --device imx8mp-adv --release scarthgap --feature ota --output /tmp/kas-config.yaml

# Enter interactive shell for a preset
bsp shell imx8mp-adv-scarthgap

# Enter shell by components
bsp shell --device qemuarm64 --release scarthgap

# Run a single command in the shell
bsp shell imx8mp-adv-scarthgap --command "bitbake core-image-minimal"
```
