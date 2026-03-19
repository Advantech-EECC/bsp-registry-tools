# BSP Registry Schema v2.0

This document describes the v2.0 registry YAML schema used by `bsp-registry-tools`.

---

## Overview

Schema v2.0 separates the registry into independent sections:

| Section        | Purpose                                                       |
|----------------|---------------------------------------------------------------|
| `devices`      | Hardware board/device definitions                             |
| `releases`     | Yocto / Isar release definitions                              |
| `features`     | Optional feature definitions (OTA, secure-boot, …)           |
| `bsp`          | Optional named presets (device + release + features)          |
| `frameworks`   | Optional build-system framework definitions (Yocto, Isar, …) |
| `distro`       | Optional distribution definitions (Poky, Isar distro, …)     |
| `vendors`      | Optional top-level vendor definitions (cross-release vendor KAS includes) |
| `include`      | Optional list of additional registry files to merge in        |

Builds can be driven either by a **named preset** (`bsp build my-preset`) or by
composing components directly (`bsp build --device <d> --release <r>`).

Large registries can be **split across multiple files** using the top-level
`include` directive.  Each included file is merged into the root registry before
the root file's own content is applied.

---

## Top-level Structure

```yaml
specification:
  version: "2.0"          # required

include:                  # optional – list of additional registry files to merge in
  - devices/boards.yaml
  - releases/scarthgap.yaml

environment:              # optional – global environment for all builds
  variables:              # optional – global env vars ($ENV{} expansion supported)
    - name: "DL_DIR"
      value: "$ENV{HOME}/downloads"
  copy:                   # optional – global file copies executed before every build
    - scripts/global-setup.sh: build/

environments:             # optional – named build environments
  default:                # special name: used when release has no environment field
    container: "debian-bookworm"
    variables:
      - name: "DL_DIR"
        value: "$ENV{HOME}/downloads"
    copy:                 # optional – file copies executed for every build using this environment
      - scripts/env-setup.sh: build/

containers:               # optional – Docker container definitions (dict)
  debian-bookworm:
    image: "my-registry/debian/kas:5.1"
    file: Dockerfile
    args:
      - name: "KAS_VERSION"
        value: "5.1"

registry:
  frameworks: [...]       # optional list of build-system framework definitions
  distro: [...]           # optional list of distribution definitions
  vendors: [...]          # optional list of top-level vendor definitions
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

## `include` (optional)

The `include` directive splits a registry across multiple YAML files.  It is a
top-level list of paths (relative to the file that contains the directive).
Each referenced file is loaded and merged **before** the current file's content
is applied, so entries in the including file always take precedence.

```yaml
# registry.yaml  ← main file (must contain specification)
specification:
  version: "2.0"

include:
  - devices/boards.yaml      # relative to the directory of this file
  - releases/scarthgap.yaml

registry:
  features: []
  bsp:
    - name: my-bsp
      description: "My BSP"
      device: my-board
      release: scarthgap
      features: []
```

```yaml
# devices/boards.yaml  ← included file (no specification required)
registry:
  devices:
    - slug: my-board
      description: "My Board"
      vendor: acme
      soc_vendor: nxp
      includes:
        - kas/boards/my-board.yaml
  releases: []
  features: []
```

### Merging rules

| Data type | Merge behaviour |
|-----------|-----------------|
| Lists (e.g. `devices`, `releases`, `features`, `environment`) | Concatenated — included items appear **before** the including file's items |
| Dicts (e.g. `containers`, `environments`) | Merged recursively — including file wins on conflicting keys |
| Scalars | Including file wins |

> **Note:** `environment` (global variable list) is a **list** and is
> concatenated.  `environments` (named environment dict) is a **dict** and is
> merged recursively.

### Nested includes

Included files can themselves contain `include` directives.  Paths are always
resolved **relative to the file that contains the directive**.

### Circular include detection

Circular includes are detected at load time.  The tool exits immediately with a
clear error message if the same file is visited twice.

### `specification` in included files

The `specification` block is silently stripped from included files — version
validation is performed only once on the root registry file.

---

## `environment` (optional)

Global build environment applied to every build.  It groups two sub-fields:

| Sub-field   | Type               | Description                                                                 |
|-------------|--------------------|-----------------------------------------------------------------------------|
| `variables` | list[{name,value}] | Environment variables (supports `$ENV{VAR}` expansion against the host shell environment). |
| `copy`      | list[dict]         | File-copy entries executed inside the build environment before every build.  Entries run first, before named-environment and device-level entries. |

```yaml
environment:
  variables:
    - name: "DL_DIR"
      value: "$ENV{HOME}/data/cache/downloads"
    - name: "SSTATE_DIR"
      value: "$ENV{HOME}/data/cache/sstate"
    - name: "GITCONFIG_FILE"
      value: "$ENV{HOME}/.gitconfig"
  copy:
    - scripts/global-setup.sh: build/
    - config/global.conf: build/conf/
```

Both `variables` and `copy` are optional and can be omitted independently.

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

Named build environments bundle a **container reference**, optional
**environment variables**, and optional **file-copy entries** together under a
single name.  This makes it easy to associate a specific container image,
variable set, and setup scripts with a particular class of releases (e.g., a
separate Isar container with its own runqemu helper script).

```yaml
environments:
  default:                    # used for any release that does not name an environment
    container: "debian-bookworm"
    variables:
      - name: "DL_DIR"
        value: "$ENV{HOME}/data/cache/downloads"
      - name: "SSTATE_DIR"
        value: "$ENV{HOME}/data/cache/sstate"
    copy:                     # optional: files to copy before builds that use this env
      - scripts/env-setup.sh: build/

  isar-build:                 # named environment for Isar releases
    container: "debian-bookworm-isar"
    variables:
      - name: "DL_DIR"
        value: "$ENV{HOME}/data/cache/isar-downloads"
    copy:
      - isar/scripts/isar-runqemu.sh: build/    # copy helper script into every Isar build dir
```

### `environments[*]` fields

| Field       | Type                 | Description                                                                                   |
|-------------|----------------------|-----------------------------------------------------------------------------------------------|
| `container` | string (opt.)        | Container name (references `containers` section). Used when the device has no container set. |
| `variables` | list (opt.)          | Environment variables merged on top of the root `environment` list.                           |
| `copy`      | list[dict] (opt.)    | File-copy entries executed inside the build environment before every build that uses this environment. The destination is resolved relative to the BSP's build directory (same as `Device.copy`). |

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

### Copy merge order

File-copy entries from all three levels are **concatenated** in the following
order before the build starts:

```
root-level copy → named environment copy → device copy
```

All entries are executed inside the build environment — files are placed in the
build workspace (the project root that is mounted inside the container) so they
are accessible during the build.  Root-level copies always execute first
(shared setup), then environment-specific copies, and finally device-specific
copies.

**Destination path resolution**: the *source* is always resolved relative to
the registry file's parent directory.  The *destination* is resolved relative
to the BSP's build directory.  For example, if the BSP preset's build path is
`build/isar-qemuarm64-ubuntu-noble` and the copy entry specifies `scripts/` as
the destination, the file lands at
`build/isar-qemuarm64-ubuntu-noble/scripts/<filename>`.  This ensures the
copied file is accessible inside the build workspace that is mounted into the
container.  When no preset build path is set (direct `resolve()` call without
a preset) the destination falls back to being relative to the registry
directory.

---

## `registry.frameworks` (optional)

Build-system framework definitions group related distros and enable
framework-level feature compatibility checking via `Feature.compatible_with`.

```yaml
registry:
  frameworks:
    - slug: yocto              # unique identifier (used in distro.framework and compatible_with)
      description: |
        Yocto Project build system
      vendor: "Yocto Project"
      includes:                # optional: KAS files that configure this framework
        - kas/yocto/yocto.yaml

    - slug: isar
      description: |
        Set of scripts for building software packages and repeatable
        generation of Debian-based root filesystems with customizations
      vendor: "Ilbers GmbH"
      includes:
        - kas/isar/isar.yaml
```

### `frameworks[*]` fields

| Field         | Type          | Description                                              |
|---------------|---------------|----------------------------------------------------------|
| `slug`        | string        | Unique framework identifier                              |
| `description` | string        | Human-readable description                               |
| `vendor`      | string        | Framework vendor/maintainer name                         |
| `includes`    | list[str]     | Optional KAS configuration files for this framework      |

Distros reference a framework via their `framework` field.  Features use
`compatible_with` to declare which frameworks (or distros) they support.

---

## `registry.distro` (optional)

Distribution / build-system definitions group the KAS configuration files that
set up a particular Linux distribution (e.g. Poky, Isar).  Releases reference
a distro by slug via `Release.distro`, causing the resolver to prepend the
distro's includes before the release includes.

```yaml
registry:
  distro:
    - slug: poky
      description: "Poky (Yocto Project reference distro)"
      vendor: yocto
      framework: yocto         # optional: references frameworks[*].slug
      includes:
        - kas/yocto/distro/poky.yaml

    - slug: poky-harden
      description: "Hardened Poky"
      vendor: yocto
      framework: yocto
      includes:
        - kas/yocto/distro/harden.yaml

    - slug: isar
      description: "Isar v0.11 (Siemens build system)"
      vendor: siemens
      framework: isar
      includes:
        - kas/isar/isar-v0.11.yaml
```

### `distro[*]` fields

| Field         | Type          | Description                                              |
|---------------|---------------|----------------------------------------------------------|
| `slug`        | string        | Unique distro identifier                                 |
| `description` | string        | Human-readable description                               |
| `vendor`      | string        | Distro vendor/maintainer name                            |
| `includes`    | list[str]     | KAS configuration files that configure this distro       |
| `framework`   | string (opt.) | Framework slug this distro is based on (references `frameworks[*].slug`). Used for `Feature.compatible_with` checks. |

---

## `registry.devices`

Each device represents a specific hardware board or emulated target.

```yaml
registry:
  devices:
    - slug: imx8mp-adv              # unique identifier (used in CLI / presets)
      description: "Advantech i.MX8M Plus board"
      vendor: advantech             # board vendor
      soc_vendor: nxp               # silicon vendor (used in feature compat checks)
      soc_family: imx8              # optional SoC family
      includes:                     # device-specific KAS configuration files
        - kas/boards/imx8mp-adv.yaml
      local_conf:                   # optional extra local.conf lines
        - "MACHINE_EXTRA_RDEPENDS += 'kernel-modules'"
      copy:                         # optional files to copy before the build
        - scripts/setup.sh: build/imx8mp-adv/

    - slug: qemuarm64
      description: "QEMU ARM64 (emulated)"
      vendor: qemu
      soc_vendor: arm
      includes:
        - kas/qemu/qemuarm64.yaml
```

### `devices[*]` fields

| Field        | Type                 | Description                                                                 |
|--------------|----------------------|-----------------------------------------------------------------------------|
| `slug`       | string               | Unique device identifier (referenced by presets and CLI)                    |
| `description`| string               | Human-readable description                                                  |
| `vendor`     | string               | Board vendor name (used for vendor-specific release includes and feature compatibility checks) |
| `soc_vendor` | string               | Silicon vendor name (used in feature compatibility checks)                  |
| `soc_family` | string (opt.)        | SoC family identifier (used in feature compatibility checks)                |
| `includes`   | list[str]            | Device-specific KAS configuration files                                     |
| `local_conf` | list[str]            | Lines appended to `local.conf` for this device                              |
| `copy`       | list[dict[str, str]] | Files to copy into the build environment before the build starts. Each entry is a single-key dict `{"source": "destination"}`. The source is resolved relative to the registry file's parent directory. The destination is resolved relative to the BSP's build directory, so `scripts/` means a `scripts/` subdirectory *inside* the BSP output folder (e.g. `build/my-bsp/scripts/`). If the destination ends with `/` or is an existing directory, the source filename is preserved. |

> **Note on build output path and container:** In v2.0 the container and output path are **optional** preset-level overrides configured in the preset's `build:` block (see [`registry.bsp`](#registrybsp-optional-presets) below).  When `build:` is absent, or when individual fields are omitted, the container falls back to the release's named environment (or `"default"`), and the path is auto-composed as `build/<distro>-<device>-<release>`.  New registries should use the flat `includes`/`local_conf`/`copy` fields directly on the device instead of the legacy `device.build:` nested block.

---

## `registry.vendors` (optional)

Top-level vendor definitions group KAS configuration files that apply to **all**
boards from a given hardware vendor, regardless of which release is being built.
When the resolver finds a `registry.vendors` entry whose `slug` matches the
device's `vendor` field it prepends those includes in the KAS file list (after
distro includes but before release includes).

This is useful for KAS fragments that are truly cross-release — for example a
vendor-wide toolchain configuration or a shared download mirror setup — while
release-specific or BSP-version-specific vendor additions belong in
`releases[*].vendor_overrides` instead.

```yaml
registry:
  vendors:
    - slug: advantech                  # must match devices[*].vendor
      name: "Advantech"
      description: "Advantech Corporation"
      website: "https://www.advantech.com/"
      includes:
        - vendors/advantech/nxp/advantech.yml   # added for ALL Advantech devices

    - slug: qemu
      name: "QEMU"
      description: "QEMU emulator targets"
      includes:
        - vendors/qemu/qemu-base.yml
```

### `vendors[*]` fields

| Field         | Type          | Description                                                                        |
|---------------|---------------|------------------------------------------------------------------------------------|
| `slug`        | string        | Unique vendor identifier (must match `devices[*].vendor`)                          |
| `name`        | string        | Human-readable vendor name                                                         |
| `description` | string (opt.) | Longer description of the vendor                                                   |
| `website`     | string (opt.) | Vendor website URL                                                                 |
| `includes`    | list[str]     | KAS configuration files applied to every device whose `vendor` matches this entry |

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
      distro: poky                   # optional – references distro[*].slug
      includes:                      # base KAS files for this release
        - kas/scarthgap.yaml
      vendor_overrides:              # optional vendor-specific overrides
        - vendor: advantech
          includes:
            - kas/advantech/scarthgap-vendor.yaml

    - slug: isar-v0.11
      description: "Isar v0.11"
      environment: isar-build        # use the 'isar-build' named environment
      distro: isar
      includes:
        - kas/isar/v0.11.yaml
```

The optional `environment` field names an entry from the top-level
`environments` dict.  When omitted, the `"default"` named environment is
used (if defined).  See [Named environments](#environments-optional) for
full resolution rules.

The optional `distro` field references a `registry.distro` entry.  When set
the resolver prepends the distro's includes before the release includes and uses
the distro's `framework` for `Feature.compatible_with` checks.

### `releases[*].vendor_overrides`

`vendor_overrides` is an optional list of vendor-specific configuration overrides
attached to a release.  Each entry targets one board vendor and can contribute:

- **common includes** added to every build that uses this vendor + release combination, and
- **sub-releases** (optional, via the `releases` sub-list) that let a single top-level
  release expose multiple BSP kernel/firmware versions for the same vendor.

#### Basic usage — common vendor includes

When a device's `vendor` matches a `vendor_overrides` entry (and no `override` slug is
given on the preset), the resolver appends that entry's `includes` after the base
release includes.

```yaml
releases:
  - slug: scarthgap
    distro: poky
    description: "Yocto 5.0 LTS (Scarthgap)"
    yocto_version: "5.0"
    includes:
      - kas/scarthgap.yaml
    vendor_overrides:
      - vendor: advantech
        includes:
          - kas/advantech/scarthgap-vendor.yaml   # added for every Advantech device
```

#### `vendor_overrides[*]` fields

| Field        | Type          | Description                                                                                                  |
|--------------|---------------|--------------------------------------------------------------------------------------------------------------|
| `vendor`     | string        | Board vendor name this override applies to (matches `devices[*].vendor`)                                     |
| `includes`   | list[str]     | KAS files added for every build using this vendor override                                                   |
| `releases`   | list (opt.)   | Vendor-specific sub-releases; used when all boards from this vendor share the same SoC family (see below)   |
| `soc_vendors`| list (opt.)   | Per-SoC-vendor override entries; used when the board vendor ships boards based on multiple SoC families (NXP, MediaTek, Qualcomm, …).  Each entry targets one SoC vendor (see [SoC vendor overrides](#soc-vendor-overrides-vendor_overrides-soc_vendors)) |
| `slug`       | string (opt.) | Unique identifier for this override entry.  Required when multiple overrides exist for the same vendor, or when a preset must select an override by `override:` field rather than by vendor matching. |
| `distro`     | string (opt.) | Distro slug (references `distro[*].slug`) that **overrides** the release's own `distro` field when this vendor override is active.  Use this when a specific BSP combination requires a different distro (e.g. `poky-imx` instead of `poky`).  A `SocVendorOverride.distro` (see below) takes precedence over this field. |

#### Sub-releases (`vendor_overrides[*].releases`)

Sub-releases let a single top-level release (e.g. `scarthgap`) expose multiple
BSP / kernel versions for the same vendor.  The preset's `vendor_release` field
selects which sub-release to activate.  When `vendor_release` is **omitted** and
the active `vendor_overrides` entry has a non-empty `releases` list, the resolver
automatically selects the **first** sub-release as the default.

If the parent `vendor_overrides` entry has a `distro` field, that distro is used
as the effective distro for the build whenever any sub-release is selected via
`vendor_release`.  This means the `distro` override applies for all three
selection methods: `override`, `vendor_release`, and auto-selection.

```yaml
releases:
  - slug: scarthgap
    distro: poky
    description: "Yocto 5.0 LTS (Scarthgap)"
    yocto_version: "5.0"
    includes:
      - kas/scarthgap.yaml
    vendor_overrides:
      - vendor: advantech
        distro: fsl-imx-xwayland        # replaces release.distro for ALL sub-releases
        includes:
          - kas/advantech/scarthgap-common.yaml  # common includes for all Advantech sub-releases
        releases:
          - slug: imx-6.6.53
            description: "Scarthgap with i.MX BSP 6.6.53"
            includes:
              - kas/advantech/nxp/imx-6.6.53.yaml
          - slug: imx-6.12.0
            description: "Scarthgap with i.MX BSP 6.12.0"
            includes:
              - kas/advantech/nxp/imx-6.12.0.yaml
```

A preset then selects a sub-release with `vendor_release`:

```yaml
bsp:
  - name: my-board-scarthgap
    device: my-adv-board
    release: scarthgap
    vendor_release: imx-6.6.53      # selects the sub-release; distro: fsl-imx-xwayland is used
    features: [systemd, security]
```

| Sub-release field | Type      | Description                                          |
|-------------------|-----------|------------------------------------------------------|
| `slug`            | string    | Unique sub-release identifier (referenced by `bsp[*].vendor_release`) |
| `description`     | string    | Human-readable description                           |
| `includes`        | list[str] | KAS files added when this sub-release is selected    |

#### SoC vendor overrides (`vendor_overrides[*].soc_vendors`)

When a single board vendor ships boards based on **multiple SoC families** (e.g.
Advantech boards based on NXP, MediaTek, or Qualcomm), the `soc_vendors` list
allows each SoC family to carry its own set of includes, sub-releases, and
optional distro override — all within a single `vendor_overrides` entry.

The resolver selects the `soc_vendors` entry whose `vendor` field matches the
**device's `soc_vendor`** field automatically.

**Include ordering when `soc_vendors` is active:**

```
framework.includes
  → distro.includes                        (uses SocVendorOverride.distro if set, else VendorOverride.distro, else release.distro)
  → vendors[device.vendor].includes
  → release.includes
  → VendorOverride.includes                (common for every SoC family)
  → SocVendorOverride.includes             (specific to the matched SoC vendor)
  → VendorRelease.includes                 (sub-release, if vendor_release is set)
  → device.includes
  → feature.includes                       (base feature KAS files)
  → feature.VendorOverride.includes        (feature vendor-specific includes, if vendor matches)
  → feature.SocVendorOverride.includes     (feature SoC-vendor-specific includes, if soc_vendor matches)
  → feature.VendorRelease.includes         (feature vendor sub-release, if vendor_release is set)
```

**Distro resolution priority (highest → lowest):**

1. `SocVendorOverride.distro`
2. `VendorOverride.distro`
3. `Release.distro`

**Example — Advantech boards on NXP and MediaTek:**

```yaml
releases:
  - slug: scarthgap
    distro: poky
    description: "Yocto 5.0 LTS (Scarthgap)"
    yocto_version: "5.0"
    includes:
      - kas/scarthgap.yaml
    vendor_overrides:
      - vendor: advantech
        includes:
          - kas/advantech/scarthgap-common.yaml  # common for ALL Advantech boards
        soc_vendors:
          - vendor: nxp
            distro: fsl-imx-xwayland    # overrides release.distro for NXP boards
            includes:
              - kas/advantech/nxp/scarthgap.yaml  # common for all Advantech/NXP boards
            releases:
              - slug: imx-6.6.53
                description: "Scarthgap with i.MX BSP 6.6.53"
                includes:
                  - kas/advantech/nxp/imx-6.6.53.yaml
              - slug: imx-6.12.0
                description: "Scarthgap with i.MX BSP 6.12.0"
                includes:
                  - kas/advantech/nxp/imx-6.12.0.yaml
          - vendor: mediatek
            distro: mt-distro           # overrides release.distro for MediaTek boards
            includes:
              - kas/advantech/mediatek/scarthgap.yaml
            releases:
              - slug: mt8186-2.0
                description: "Scarthgap for MT8186 v2.0"
                includes:
                  - kas/advantech/mediatek/mt8186-2.0.yaml
```

Presets for an NXP-based Advantech device and a MediaTek-based Advantech device:

```yaml
devices:
  - slug: adv-imx8
    vendor: advantech
    soc_vendor: nxp       # → resolver selects soc_vendors[vendor=nxp]
    includes:
      - kas/boards/adv-imx8.yaml

  - slug: adv-mt8186
    vendor: advantech
    soc_vendor: mediatek   # → resolver selects soc_vendors[vendor=mediatek]
    includes:
      - kas/boards/adv-mt8186.yaml

bsp:
  - name: adv-imx8-scarthgap-imx6.6.53
    device: adv-imx8
    release: scarthgap
    vendor_release: imx-6.6.53     # references soc_vendors[vendor=nxp].releases[slug=imx-6.6.53]
    features: []

  - name: adv-mt8186-scarthgap-mt8186-2.0
    device: adv-mt8186
    release: scarthgap
    vendor_release: mt8186-2.0     # references soc_vendors[vendor=mediatek].releases[slug=mt8186-2.0]
    features: []
```

> **Note**: `soc_vendors` and `releases` are mutually exclusive within a single
> `vendor_overrides` entry.  Use `releases` when every board from the vendor shares
> the same SoC family; use `soc_vendors` when the vendor ships boards with multiple
> SoC families.

#### `soc_vendors[*]` fields

| Field       | Type          | Description                                                                           |
|-------------|---------------|---------------------------------------------------------------------------------------|
| `vendor`    | string        | SoC vendor this entry applies to (matches `devices[*].soc_vendor`)                   |
| `includes`  | list[str]     | KAS files added for every build using this SoC vendor override                       |
| `releases`  | list (opt.)   | SoC-vendor-specific sub-releases (same structure as `vendor_overrides[*].releases`)  |
| `distro`    | string (opt.) | Distro slug that overrides both the parent `VendorOverride.distro` and the release's own `distro` field when this SoC vendor override is active |

#### Distro override

The effective distro for a build is resolved using the following priority chain
(highest wins):

1. **`SocVendorOverride.distro`** — when `soc_vendors` is used and the matching
   SoC vendor entry has a `distro` field.
2. **`VendorOverride.distro`** — when the active `vendor_overrides` entry has a
   `distro` field (and no `SocVendorOverride.distro` is set).
3. **`Release.distro`** — the release's own default distro.

This allows fine-grained control: a board vendor override can declare a common
distro (e.g. a shared BSP base), while individual SoC vendor overrides can further
specialize the distro for boards built on different SoC families.

```yaml
releases:
  - slug: scarthgap
    distro: poky                       # lowest priority
    vendor_overrides:
      - vendor: advantech
        distro: vendor-default-distro  # overrides release.distro for all SoC families
        soc_vendors:
          - vendor: nxp
            distro: fsl-imx-xwayland   # overrides vendor-default-distro for NXP boards
          - vendor: mediatek
            # no distro here → inherits advantech's vendor-default-distro
```

#### Slug-based override selection

When multiple `vendor_overrides` entries exist for the same vendor (each with a
distinct `slug`), a preset can select a specific entry using the `override` field
instead of relying on vendor name matching.  If the selected entry has a `distro`
field it replaces the release's distro for that build.

```yaml
releases:
  - slug: scarthgap
    distro: poky                   # default distro for this release
    description: "Yocto 5.0 LTS"
    yocto_version: "5.0"
    includes:
      - kas/scarthgap.yaml
    vendor_overrides:
      - slug: imx-6.6.23-2.0.0    # selectable by preset override: field
        vendor: advantech-europe
        distro: poky-imx           # overrides release.distro for this entry
        includes:
          - kas/advantech-europe/nxp/imx-6.6.23-2.0.0-scarthgap.yaml
      - slug: imx-6.6.36-2.1.0
        vendor: advantech-europe
        includes:
          - kas/advantech-europe/nxp/imx-6.6.36-2.1.0-scarthgap.yaml
      - vendor: advantech          # matched by vendor name (no slug needed)
        includes:
          - kas/advantech/nxp/scarthgap.yaml
```

#### Auto-selection when no `override` or `vendor_release` is specified

If a release has `vendor_overrides` and a build is triggered **without** specifying
an explicit `override` or `vendor_release` (e.g. a preset that omits both fields),
the resolver:

1. Finds the **first** `vendor_overrides` entry whose `vendor` matches the device's vendor.
2. Applies that entry's includes (and its `distro` override, if present).
3. If the selected `vendor_overrides` entry has a non-empty `releases` list, automatically
   selects the **first** sub-release and applies its includes.
4. Emits a **WARNING** advising you to add an explicit `override:` or `vendor_release:`
   to the BSP preset.

This auto-selection ensures you always get usable vendor includes (and a vendor
sub-release) as a default, while being notified that an explicit choice is recommended.

```
WARNING  Release 'scarthgap' has vendor_overrides defined but no `override` or
         `vendor_release` was specified. Automatically selecting first matching
         entry (vendor='advantech-europe', slug='imx-6.6.23-2.0.0').
         Available override slugs: imx-6.6.23-2.0.0, imx-6.6.36-2.1.0.
         Add `override:` or `vendor_release:` to the BSP preset to suppress
         this warning.
```

To suppress the warning, add either field to the preset:

```yaml
bsp:
  - name: my-board-scarthgap
    device: my-board
    release: scarthgap
    override: imx-6.6.23-2.0.0   # explicit selection → no warning
    features: []
```

---

## `registry.features`

Features are optional add-ons (OTA update, secure boot, …) that can be enabled
per-build.  Each feature can declare device compatibility constraints
(`compatibility`) and/or framework/distro restrictions (`compatible_with`).

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
      # No compatible_with = works with ALL frameworks/distros

    - slug: secure-boot
      description: "Secure Boot (NXP HABv4 / AHAB)"
      compatibility:
        soc_vendor:                  # empty list = all; non-empty = allow-list
          - nxp
      includes:
        - kas/features/secure-boot.yaml
      env:
        - name: "SIGNING_KEY"
          value: "$ENV{SIGNING_KEY}"

    - slug: isar-users
      description: "Add sample non-root user accounts (Isar only)"
      compatible_with: [isar]        # only compatible with the Isar framework
      includes:
        - kas/isar/features/users.yaml

    - slug: yocto-systemd
      description: "Enable systemd as the init system (Yocto only)"
      compatible_with: [yocto]       # only compatible with the Yocto framework
      includes:
        - kas/yocto/features/systemd.yaml
```

### Device compatibility rules (`compatibility`)

| `compatibility` key | Meaning                                           |
|---------------------|---------------------------------------------------|
| `vendor`            | Allow-list of board vendor names (empty = all)    |
| `soc_vendor`        | Allow-list of SoC vendor names (empty = all)      |
| `soc_family`        | Allow-list of SoC family strings (empty = all)    |

If any constraint fails, the build exits with a clear error message.

### Framework/distro compatibility (`compatible_with`)

The `compatible_with` field is an optional list of framework slugs and/or
distro slugs.  When non-empty the resolver checks that the release's distro
or its framework appears in the list before allowing the feature.

| Condition | Result |
|-----------|--------|
| `compatible_with` is empty | Feature is compatible with all releases |
| Release's distro slug is in `compatible_with` | Compatible |
| Release's distro's `framework` slug is in `compatible_with` | Compatible |
| Neither the distro nor its framework is in the list | Build exits with error |
| `compatible_with` is set but the release has no distro | Build exits with error |

### Vendor-specific feature includes (`vendor_overrides`)

A feature can carry its own `vendor_overrides` list using **exactly the same
structure** as `releases[*].vendor_overrides`.  This lets a feature add
vendor-specific (and SoC-vendor-specific) KAS files on top of its base
`includes` without requiring separate feature definitions per vendor.

**Include ordering for a feature with `vendor_overrides`:**

```
feature.includes                        (always applied)
  → feature.VendorOverride.includes     (applied when device.vendor matches)
  → feature.SocVendorOverride.includes  (applied when device.soc_vendor matches, inside soc_vendors)
  → feature.VendorRelease.includes      (applied when vendor_release matches, from releases list)
```

The `vendor_release` slug used for release-level override selection is **reused**
for feature-level sub-release selection — no separate field is needed.

**Example — RAUC OTA feature with NXP-specific layers:**

```yaml
registry:
  features:
    - slug: rauc
      description: "Enable RAUC support in the Yocto image"
      compatible_with: [yocto]
      includes:
        - features/ota/rauc/rauc.yml        # always included
      vendor_overrides:
        - vendor: advantech
          includes:
            - features/ota/rauc/advantech-rauc.yml  # added for Advantech boards
          soc_vendors:
            - vendor: nxp
              includes:
                - features/ota/rauc/modular-bsp-ota-nxp.yml  # added for NXP SoCs
              releases:
                - slug: imx-6.6.53
                  description: "RAUC layers for i.MX BSP 6.6.53"
                  includes:
                    - features/ota/rauc/rauc-imx-6.6.53.yml  # added when vendor_release=imx-6.6.53
```

With a BSP preset that targets an Advantech NXP board and selects `vendor_release: imx-6.6.53`,
the resolver produces this KAS file order for the `rauc` feature:

```
features/ota/rauc/rauc.yml
features/ota/rauc/advantech-rauc.yml
features/ota/rauc/modular-bsp-ota-nxp.yml
features/ota/rauc/rauc-imx-6.6.53.yml
```

For a QEMU device (vendor `qemu`) with the same feature enabled, only the base
`features/ota/rauc/rauc.yml` is added — the `advantech` vendor_override is silently
skipped because `device.vendor` does not match.

#### `features[*].vendor_overrides[*]` fields

The structure is identical to `releases[*].vendor_overrides[*]`:

| Field        | Type          | Description                                                                                          |
|--------------|---------------|------------------------------------------------------------------------------------------------------|
| `vendor`     | string        | Board vendor this override applies to (matched against `devices[*].vendor`)                          |
| `includes`   | list[str]     | KAS files added when `device.vendor` matches                                                         |
| `soc_vendors`| list (opt.)   | Per-SoC-vendor overrides (same structure as `releases[*].vendor_overrides[*].soc_vendors`)           |
| `releases`   | list (opt.)   | Vendor sub-release entries (same structure as `releases[*].vendor_overrides[*].releases`).  The sub-release is selected by the `vendor_release` field on the BSP preset. |
| `slug`       | string (opt.) | Optional identifier (not used for feature overrides — matching is always by `vendor`)                |
| `distro`     | string (opt.) | Not used for feature overrides — distro resolution is driven by the release-level `vendor_overrides` |

> **Note**: `vendor_overrides` on a feature do **not** affect distro resolution.
> Distro selection is always driven by the release-level `vendor_overrides` (and
> the preset's `override` / `vendor_release` fields).  Feature vendor_overrides
> only influence which KAS files are added.

---

## `registry.bsp` (optional presets)

Named presets are convenience shortcuts for a device + release + features
combination.  They are optional — builds can also be triggered by passing
`--device`/`--release` flags directly on the CLI.

### Single-release preset

```yaml
registry:
  bsp:
    - name: imx8mp-adv-scarthgap     # unique preset name
      description: "Advantech i.MX8MP Scarthgap baseline"
      device: imx8mp-adv             # references devices[*].slug
      release: scarthgap             # references releases[*].slug
      features: []                   # optional list of feature slugs
                                     # no build: block → container from named environment;
                                     # path auto-composed as build/<distro>-<device>-<release>

    - name: imx8mp-adv-scarthgap-ota
      description: "Advantech i.MX8MP Scarthgap with OTA"
      device: imx8mp-adv
      release: scarthgap
      features:
        - ota
      build:                          # optional – override container and/or output path
        container: "debian-bookworm"  # optional container override (from containers section)
        path: build/imx8mp-adv-scarthgap-ota  # optional path override; auto-composed if absent
```

### Preset with vendor sub-release (`vendor_release`)

Use `vendor_release` to pin a specific BSP kernel/firmware version for the device's
vendor.  The slug must match a `releases[*].vendor_overrides[*].releases[*].slug`
entry.

```yaml
registry:
  bsp:
    - name: imx8mp-adv-scarthgap-imx6.6.53
      description: "Advantech i.MX8MP Scarthgap with BSP 6.6.53"
      device: imx8mp-adv
      release: scarthgap
      vendor_release: imx-6.6.53     # references vendor_overrides[vendor=advantech].releases[slug=imx-6.6.53]
      features: []
```

### Preset with vendor override selection (`override`)

Use `override` to select a specific `vendor_overrides` entry by its `slug`,
bypassing vendor name matching.  This is needed when multiple override entries
exist for the same vendor, or when the target override carries a `distro`
substitution.

```yaml
registry:
  bsp:
    - name: rsb3720-scarthgap-imx6.6.23
      description: "RSB-3720 Scarthgap (i.MX BSP 6.6.23)"
      device: rsb3720
      release: scarthgap
      override: imx-6.6.23-2.0.0    # selects vendor_overrides entry with slug=imx-6.6.23-2.0.0
      features: [systemd, security, virtualization]
```

### Multi-release preset (simplified syntax)

When the same device and feature set should target several releases, use the
`releases` (plural) list instead of repeating the entry:

```yaml
registry:
  bsp:
    # Example 1 – explicit build.path used as base:
    #   This single entry expands into:
    #   imx8mp-adv-scarthgap  →  build/imx8mp-adv-scarthgap
    #   imx8mp-adv-styhead    →  build/imx8mp-adv-styhead
    - name: imx8mp-adv
      description: "Advantech i.MX8MP baseline"
      device: imx8mp-adv
      releases: [scarthgap, styhead]   # expands into one preset per release slug
      features: []
      build:
        container: "debian-bookworm"   # container override is preserved per expansion
        path: build/imx8mp-adv         # used as base; release slug is appended automatically

    # Example 2 – no explicit build.path; path is auto-composed from preset name:
    #   rom2820-scarthgap  →  build/rom2820-scarthgap
    #   rom2820-styhead    →  build/rom2820-styhead
    #   rom2820-walnascar  →  build/rom2820-walnascar
    - name: rom2820
      description: "Advantech ROM-2820"
      device: rom2820
      releases: [scarthgap, styhead, walnascar]
      features: [systemd]
      # No build: block → path is auto-composed as build/{name}-{release_slug}
```

> **Note**: `release` (singular) and `releases` (plural) are mutually exclusive.
> Exactly one must be specified per preset entry.  When `releases` is used the
> expanded preset names follow the pattern `{name}-{release_slug}`.

#### Build path for multi-release presets

When the `releases` list is used the per-release build path is computed as:

```
{build.path or "build/{name}"}-{release_slug}[-{override_slug}]
```

- If `build.path` is set, it is used as the base directory stem.  The release
  slug (and the vendor override slug when `override` is also set) is appended
  with a `-` separator.
- If `build.path` is omitted, the base is formed from `build/{preset.name}`.

In both cases the `build.container` override (if present) is applied unchanged
to every expanded preset.

### `bsp[*]` fields

| Field            | Type             | Description                                                                     |
|------------------|------------------|---------------------------------------------------------------------------------|
| `name`           | string           | Unique preset name (referenced by CLI `bsp build <name>`)                       |
| `description`    | string           | Human-readable description                                                      |
| `device`         | string           | Device slug (references `devices[*].slug`)                                      |
| `release`        | string (opt.)    | Single release slug (mutually exclusive with `releases`)                        |
| `releases`       | list[str] (opt.) | List of release slugs; expanded into one preset per entry (mutually exclusive with `release`) |
| `vendor_release` | string (opt.)    | Vendor sub-release slug. Selects a specific BSP kernel/firmware version. When `soc_vendors` is used, the slug is looked up in the matching `SocVendorOverride.releases` list; otherwise it references the flat `releases[*].vendor_overrides[*].releases[*].slug`. When omitted and the active override has sub-releases, the **first** sub-release is selected automatically. |
| `override`       | string (opt.)    | Vendor override slug (references `releases[*].vendor_overrides[*].slug`). Selects a specific `vendor_overrides` entry by its `slug` field, bypassing vendor name matching. Useful when multiple overrides exist for the same vendor, or when the override carries a `distro` substitution. |
| `features`       | list[str]        | Optional list of feature slugs to enable (references `features[*].slug`)        |
| `local_conf`     | string (opt.)    | YAML block scalar (`\|`) of `local.conf` lines to append for this preset. Each non-empty line is appended to the resolved `local_conf` after device- and feature-level entries. Trailing whitespace is stripped; blank lines are ignored. |
| `targets`        | list[str] (opt.) | List of Bitbake build targets (images or recipes) for this preset. When set, the targets are written into the `target` section of the generated KAS YAML file, instructing KAS which images to build. |
| `build`          | object (opt.)    | Optional build overrides (container and/or output path)                         |

### `bsp[*].build` fields

| Field       | Type          | Description                                                                       |
|-------------|---------------|-----------------------------------------------------------------------------------|
| `container` | string (opt.) | Container name override (key in `containers` section). When absent the container is taken from the release's named environment (or `"default"`). |
| `path`      | string (opt.) | Build output directory. When absent, the path is auto-composed as `build/<distro>-<device>-<release>[-<feature>…]` for single-release presets, or `build/<name>-<release_slug>[-<override_slug>]` for multi-release presets. When `releases` (plural) is used, this value is treated as a *base path stem*: the release slug (and the vendor override slug when `override` is set) is appended to it — e.g. `path: build/my-bsp` expands to `build/my-bsp-scarthgap` and `build/my-bsp-styhead`. |

### Preset with `local_conf` and `targets`

Use `local_conf` to inject `local.conf` settings that are specific to a preset
without adding them to the device or feature definitions.  Use `targets` to
specify which Bitbake images or recipes to build.

```yaml
registry:
  bsp:
    - name: modular-ros-bsp-rsb3720
      description: "Advantech RSB-3720 (i.MX8) – ROS 2 Humble"
      device: rsb3720
      release: ros2-humble-scarthgap
      features: [systemd, security, virtualization, ipv6, usrmerge, x11, wayland]
      local_conf: |                      # block scalar – one assignment per line
        DISTRO_FEATURES += "x11"
        BB_NUMBER_THREADS = "4"
      targets:                           # Bitbake images/recipes to build
        - ros-image-core
      build:
        path: build/modular-bsp-rsb3720-ros2
```

The `local_conf` lines are appended **after** device- and feature-level
`local_conf` entries in the following priority order (lowest to highest):

```
device.local_conf  →  feature[*].local_conf  →  preset.local_conf
```

The `targets` list is forwarded as-is into the `target:` section of the
generated KAS YAML.  When no `targets` are specified the `target:` key is
omitted and KAS uses the default targets defined in the included KAS files.

### KAS file ordering

The resolver assembles the final KAS file list in the following order:

```
framework.includes
  → distro.includes           (effective distro; see distro override priority below)
  → vendors[device.vendor].includes
  → release.includes
  → vendor_overrides[vendor/override].includes          (VendorOverride common includes)
  → soc_vendors[device.soc_vendor].includes             (only when soc_vendors is used)
  → soc_vendors[device.soc_vendor].releases[vendor_release].includes  (or flat releases[vendor_release].includes)
  → device.includes
  → feature.includes
```

**Effective distro** is resolved in priority order (highest wins):

1. `SocVendorOverride.distro` — when a matching `soc_vendors` entry has a `distro` field
2. `VendorOverride.distro` — when the active `vendor_overrides` entry has a `distro` field
3. `Release.distro` — the release's own default distro

This ensures that base build-system configuration (framework) is loaded first, followed
by distribution defaults (which may be overridden by the active `vendor_overrides` entry's
`distro` field), then vendor-wide includes, then release-specific settings, then any
vendor override includes (common + selected sub-release), then device-specific machine
config, and finally any optional feature additions.

---

## Full Example

The example below keeps everything in a single file.  See the
[`include` section](#include-optional) above for how to split it across multiple
files.

```yaml
specification:
  version: "2.0"

# Global environment: variables and file copies applied to every build
environment:
  variables:
    - name: "GITCONFIG_FILE"
      value: "$ENV{HOME}/.gitconfig"
  copy:
    - scripts/global-setup.sh: build/

# Named environments: bundle a container + variables + optional copy under a name
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
    # Copy the QEMU run script into every Isar build directory
    copy:
      - isar/scripts/isar-runqemu.sh: build/

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

  # Build-system frameworks (Yocto, Isar)
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

  # Distributions (reference a framework)
  distro:
    - slug: poky
      description: "Poky (Yocto Project reference distro)"
      vendor: yocto
      framework: yocto
      includes:
        - kas/yocto/distro/poky.yaml

    - slug: isar
      description: "Isar v0.11"
      vendor: siemens
      framework: isar
      includes:
        - kas/isar/isar-v0.11.yaml

  devices:
    - slug: imx8mp-adv
      description: "Advantech i.MX8M Plus"
      vendor: advantech
      soc_vendor: nxp
      soc_family: imx8
      includes:
        - kas/boards/imx8mp-adv.yaml

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
      # No environment field → uses 'default' named environment
      includes:
        - kas/scarthgap.yaml
      vendor_overrides:
        - vendor: advantech
          includes:
            - kas/advantech/scarthgap-vendor.yaml

    - slug: styhead
      description: "Yocto 5.1 (Styhead)"
      distro: poky
      yocto_version: "5.1"
      includes:
        - kas/styhead.yaml

    - slug: isar-v0.11
      description: "Isar v0.11"
      distro: isar
      environment: isar-build          # use the 'isar-build' named environment
      includes:
        - kas/isar/v0.11.yaml

  features:
    - slug: ota
      description: "Over-the-Air Update via SWUpdate"
      compatible_with: [yocto]         # Yocto only
      includes:
        - kas/features/ota.yaml
      local_conf:
        - "DISTRO_FEATURES:append = ' swupdate'"

    - slug: secure-boot
      description: "Secure Boot (NXP HABv4 / AHAB)"
      compatibility:
        soc_vendor:
          - nxp
      compatible_with: [yocto]         # Yocto only
      includes:
        - kas/features/secure-boot.yaml
      env:
        - name: "SIGNING_KEY"
          value: "$ENV{SIGNING_KEY}"

    - slug: isar-users
      description: "Add sample non-root user accounts (Isar only)"
      compatible_with: [isar]          # Isar only
      includes:
        - kas/isar/features/users.yaml

  bsp:
    - name: imx8mp-adv-scarthgap
      description: "Advantech i.MX8MP Scarthgap baseline"
      device: imx8mp-adv
      release: scarthgap
      features: []
      # No build: block → container from 'default' named environment; path auto-composed

    - name: imx8mp-adv-scarthgap-ota
      description: "Advantech i.MX8MP Scarthgap with OTA"
      device: imx8mp-adv
      release: scarthgap
      features:
        - ota
      build:
        container: "debian-bookworm"
        path: build/imx8mp-adv-scarthgap-ota

    - name: imx8mp-adv-scarthgap-custom
      description: "Advantech i.MX8MP Scarthgap – custom local.conf and target"
      device: imx8mp-adv
      release: scarthgap
      features:
        - ota
      local_conf: |                      # appended after device/feature local_conf entries
        DISTRO_FEATURES += "x11"
        BB_NUMBER_THREADS = "4"
      targets:                           # Bitbake images to build
        - core-image-minimal
        - core-image-full-cmdline
      build:
        container: "debian-bookworm"
        path: build/imx8mp-adv-scarthgap-custom

    - name: qemuarm64-scarthgap
      description: "QEMU ARM64 Scarthgap"
      device: qemuarm64
      release: scarthgap
      features: []
      build:
        container: "debian-bookworm"
        path: build/qemuarm64-scarthgap

    - name: isar-v0.11-qemuarm64
      description: "Isar v0.11 QEMU ARM64"
      device: qemuarm64
      release: isar-v0.11
      features:
        - isar-users
      build:
        container: "debian-bookworm-isar"
        path: build/isar-qemuarm64-v0.11
```

---

## CLI Examples

```bash
# List all BSP presets (shows vendor_release and override when set)
bsp list

# List all devices
bsp list devices

# List all releases (shows vendor overrides + sub-releases beneath each entry)
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

# Display registry hierarchy (default detail level)
bsp tree

# Display compact tree (names/slugs only, no sub-items)
bsp tree --compact

# Display full tree (nested vendor overrides, vendor releases, and KAS includes)
bsp tree --full
```

---

## `bsp tree` command

The `bsp tree` command prints an ASCII tree of the full BSP registry hierarchy
organized into sections: Frameworks, Distros, Releases, Devices, Features, and
BSP Presets.

### Display modes

Three mutually-exclusive display levels are available via `--full` / `--compact`
flags. `--full` and `--compact` cannot be combined.

| Flag        | Behaviour                                                                                        |
|-------------|--------------------------------------------------------------------------------------------------|
| _(default)_ | Standard detail: vendor overrides shown inline with release slugs and distro override per entry  |
| `--compact` | Names/slugs only — no sub-items for any section. Useful for a quick registry inventory.          |
| `--full`    | Fully nested sub-tree: vendor overrides → vendor releases → KAS includes lists for every item.   |

### Default output example

When a `vendor_overrides` entry uses **flat releases** (no `soc_vendors`):

```
BSP Registry
├── Releases (1)
│   └── scarthgap: Yocto 5.0 LTS [Yocto 5.0]
│       ├── distro: poky
│       └── vendor override: advantech, distro: fsl-imx-xwayland, releases: imx-6.6.53, imx-6.12.0
├── Devices (1)
│   └── adv-imx8: Advantech i.MX8 Board (vendor: advantech, soc_vendor: nxp)
└── BSP Presets (1)
    └── adv-imx8-scarthgap: Advantech i.MX8 Scarthgap
        ├── device: adv-imx8  release: scarthgap
        └── vendor release: imx-6.6.53
```

When a `vendor_overrides` entry uses **`soc_vendors`**, each SoC vendor's name,
optional distro, and sub-releases are shown inline:

```
BSP Registry
├── Releases (1)
│   └── scarthgap: Yocto 5.0 LTS [Yocto 5.0]
│       ├── distro: poky
│       └── vendor override: advantech, soc vendors: [nxp; distro: fsl-imx-xwayland; releases: imx-6.6.53, imx-6.12.0], [mediatek; distro: mt-distro; releases: mt8186-2.0]
├── Devices (2)
│   ├── adv-imx8: Advantech i.MX8 Board (vendor: advantech, soc_vendor: nxp)
│   └── adv-mt8186: Advantech MT8186 Board (vendor: advantech, soc_vendor: mediatek)
└── BSP Presets (2)
    ├── adv-imx8-scarthgap: Advantech i.MX8 Scarthgap
    │   ├── device: adv-imx8  release: scarthgap
    │   └── vendor release: imx-6.6.53
    └── adv-mt8186-scarthgap: Advantech MT8186 Scarthgap
        ├── device: adv-mt8186  release: scarthgap
        └── vendor release: mt8186-2.0
```

### `--full` output example

When `soc_vendors` is used, each SoC vendor entry is rendered as a nested
subtree beneath the parent vendor override, with its own includes and
vendor releases:

```
BSP Registry
├── Releases (1)
│   └── scarthgap: Yocto 5.0 LTS [Yocto 5.0]
│       ├── distro: poky
│       ├── includes: kas/poky/scarthgap.yaml
│       └── vendor override: advantech
│           └── includes: kas/yocto/vendors/advantech/scarthgap.yaml
│           ├── soc vendor: nxp (distro: fsl-imx-xwayland)
│           │   └── includes: kas/yocto/vendors/advantech/nxp/scarthgap.yaml
│           │   ├── vendor release: imx-6.6.53: Scarthgap for i.MX 6.6.53
│           │   │   └── includes: kas/yocto/vendors/advantech/nxp/imx-6.6.53.yaml
│           │   └── vendor release: imx-6.12.0: Scarthgap for i.MX 6.12.0
│           │       └── includes: kas/yocto/vendors/advantech/nxp/imx-6.12.0.yaml
│           └── soc vendor: mediatek (distro: mt-distro)
│               └── includes: kas/yocto/vendors/advantech/mediatek/scarthgap.yaml
│               └── vendor release: mt8186-2.0: Scarthgap for MT8186 v2.0
│                   └── includes: kas/yocto/vendors/advantech/mediatek/mt8186-2.0.yaml
...
```

Without `soc_vendors` (flat releases), vendor releases appear directly
under the vendor override (unchanged behavior):

```
BSP Registry
├── Releases (1)
│   └── scarthgap: Yocto 5.0 LTS [Yocto 5.0]
│       ├── distro: poky
│       ├── includes: kas/poky/scarthgap.yaml
│       └── vendor override: advantech (distro: fsl-imx-xwayland)
│           ├── includes: kas/yocto/vendors/advantech/scarthgap.yaml
│           ├── vendor release: imx-6.6.53: Scarthgap for i.MX 6.6.53
│           │   └── includes: kas/yocto/vendors/advantech/nxp/imx-6.6.53.yaml
│           └── vendor release: imx-6.12.0: Scarthgap for i.MX 6.12.0
│               └── includes: kas/yocto/vendors/advantech/nxp/imx-6.12.0.yaml
...
```

### `--compact` output example

```
BSP Registry
├── Releases (1)
│   └── scarthgap: Yocto 5.0 LTS
├── Devices (1)
│   └── adv-imx8: Advantech i.MX8 Board
└── BSP Presets (1)
    └── adv-imx8-scarthgap: Advantech i.MX8 Scarthgap
```

---

## `bsp list releases` command

`bsp list releases` lists all release definitions. Vendor overrides and their
sub-releases are now printed beneath the corresponding release entry so you can
see the full override tree without opening the registry file.

Example output for a release that uses **flat vendor sub-releases**:

```
Available releases:
- scarthgap: Yocto 5.0 LTS (Scarthgap) [Yocto 5.0]
    override [vendor: advantech, distro: fsl-imx-xwayland]
      release: imx-6.6.53 — Scarthgap for i.MX 6.6.53
      release: imx-6.12.0 — Scarthgap for i.MX 6.12.0
```

Example output when the vendor override uses **`soc_vendors`** instead:

```
Available releases:
- scarthgap: Yocto 5.0 LTS (Scarthgap) [Yocto 5.0], distro: poky
    override [vendor: advantech]
      [soc_vendor: nxp, distro: fsl-imx-xwayland]
        release: imx-6.6.53 — Scarthgap for i.MX 6.6.53
        release: imx-6.12.0 — Scarthgap for i.MX 6.12.0
      [soc_vendor: mediatek, distro: mt-distro]
        release: mt8186-2.0 — Scarthgap for MT8186 v2.0
```

Use `bsp list releases --device <slug>` to filter releases to those compatible
with a specific device's vendor.

---

## `bsp list` (presets) command

`bsp list` now includes `vendor_release` and `override` fields in the summary
line when they are set on the preset:

```
Available BSP presets:
- adv-imx8-scarthgap: Advantech i.MX8 Scarthgap (device: adv-imx8, release: scarthgap, vendor_release: imx-6.6.53)
```

