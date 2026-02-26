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
referenced from `devices[*].build.container`.

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
```

> The legacy **list** format (`- debian-bookworm: {…}`) is still accepted for
> backward compatibility in the containers section.

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
        container: "debian-bookworm" # references containers section
        path: build/imx8mp-adv       # build output directory
        includes:                    # device-specific KAS files
          - kas/boards/imx8mp-adv.yml
        local_conf:                  # optional extra local.conf lines
          - "MACHINE_EXTRA_RDEPENDS += 'kernel-modules'"
```

### `devices[*].build` fields

| Field        | Type       | Description                                  |
|--------------|------------|----------------------------------------------|
| `container`  | string     | Container name (key in `containers` section) |
| `path`       | string     | Build output directory                       |
| `includes`   | list[str]  | Device-specific KAS configuration files      |
| `local_conf` | list[str]  | Lines appended to `local.conf` for this device |

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
      includes:                      # base KAS files for this release
        - kas/scarthgap.yml
      vendor_includes:               # optional vendor-specific overrides
        - vendor: advantech
          includes:
            - kas/advantech/scarthgap-vendor.yml
    - slug: styhead
      description: "Yocto 5.1 (Styhead)"
      yocto_version: "5.1"
      includes:
        - kas/styhead.yml
```

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
        - kas/features/ota.yml
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
        - kas/features/secure-boot.yml
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

environment:
  - name: "DL_DIR"
    value: "$ENV{HOME}/data/cache/downloads"
  - name: "SSTATE_DIR"
    value: "$ENV{HOME}/data/cache/sstate"
  - name: "GITCONFIG_FILE"
    value: "$ENV{HOME}/.gitconfig"

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
  devices:
    - slug: imx8mp-adv
      description: "Advantech i.MX8M Plus"
      vendor: advantech
      soc_vendor: nxp
      soc_family: imx8
      build:
        container: "debian-bookworm"
        path: build/imx8mp-adv
        includes:
          - kas/boards/imx8mp-adv.yml

    - slug: qemuarm64
      description: "QEMU ARM64 (emulated)"
      vendor: qemu
      soc_vendor: arm
      build:
        container: "debian-bookworm"
        path: build/qemuarm64
        includes:
          - kas/qemu/qemuarm64.yml

  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS (Scarthgap)"
      yocto_version: "5.0"
      includes:
        - kas/scarthgap.yml
      vendor_includes:
        - vendor: advantech
          includes:
            - kas/advantech/scarthgap-vendor.yml

    - slug: styhead
      description: "Yocto 5.1 (Styhead)"
      yocto_version: "5.1"
      includes:
        - kas/styhead.yml

  features:
    - slug: ota
      description: "Over-the-Air Update via SWUpdate"
      includes:
        - kas/features/ota.yml
      local_conf:
        - "DISTRO_FEATURES:append = ' swupdate'"

    - slug: secure-boot
      description: "Secure Boot (NXP HABv4 / AHAB)"
      compatibility:
        soc_vendor:
          - nxp
      includes:
        - kas/features/secure-boot.yml
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
bsp export --device imx8mp-adv --release scarthgap --feature ota --output /tmp/kas-config.yml

# Enter interactive shell for a preset
bsp shell imx8mp-adv-scarthgap

# Enter shell by components
bsp shell --device qemuarm64 --release scarthgap

# Run a single command in the shell
bsp shell imx8mp-adv-scarthgap --command "bitbake core-image-minimal"
```
