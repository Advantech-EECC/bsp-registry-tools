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

environment:              # optional – global env vars for all builds
  - name: "DL_DIR"
    value: "$ENV{HOME}/downloads"

copy:                     # optional – global file copies executed before every build
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

## `copy` (optional)

Global file-copy entries executed inside the **build environment** before every
build in the registry.  Files are placed in the build workspace — the project
tree that is mounted inside the container — so they are available during the
build regardless of device, release, or environment.

Each entry is a single-key dict mapping a source path to a destination path.
Both paths are resolved relative to the registry file's parent directory (the
project root).  The destination should be within the build workspace (e.g.
`build/`).  If the destination ends with `/` or is an existing directory, the
source filename is preserved inside it.

```yaml
copy:
  - scripts/global-setup.sh: build/
  - config/global.conf: build/conf/
```

See [Copy merge order](#copy-merge-order) below for how global, environment, and device copies are combined.

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
| `copy`      | list[dict] (opt.)    | File-copy entries executed inside the build environment before every build that uses this environment. Files are placed in the build workspace (project root mounted inside the container). Same format as `Device.copy` and root-level `copy`. |

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
| `copy`       | list[dict[str, str]] | Files to copy into the build environment before the build starts. Each entry is a single-key dict `{"source": "destination"}`. Both paths are resolved relative to the registry file's parent directory (the project root mounted inside the container). The destination should be within the build workspace. If the destination ends with `/` or is an existing directory, the source filename is preserved. |

> **Note on build output path and container:** In v2.0 the container and output path are **optional** preset-level overrides configured in the preset's `build:` block (see [`registry.bsp`](#registrybsp-optional-presets) below).  When `build:` is absent, or when individual fields are omitted, the container falls back to the release's named environment (or `"default"`), and the path is auto-composed as `build/<distro>-<device>-<release>`.  New registries should use the flat `includes`/`local_conf`/`copy` fields directly on the device instead of the legacy `device.build:` nested block.

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
      vendor_includes:               # optional vendor-specific overrides
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

### `releases[*].vendor_includes`

When a device's `vendor` matches a `vendor_includes` entry, those additional KAS
files are added **after** the base release includes.

> **Note:** In v2.0, `vendor_includes` is stored in the registry for informational
> purposes.  The resolver uses `device.vendor` to select relevant vendor overrides
> automatically (this is on the roadmap for a future resolver improvement).

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

### `bsp[*]` fields

| Field         | Type          | Description                                                                     |
|---------------|---------------|---------------------------------------------------------------------------------|
| `name`        | string        | Unique preset name (referenced by CLI `bsp build <name>`)                       |
| `description` | string        | Human-readable description                                                      |
| `device`      | string        | Device slug (references `devices[*].slug`)                                      |
| `release`     | string        | Release slug (references `releases[*].slug`)                                    |
| `features`    | list[str]     | Optional list of feature slugs to enable (references `features[*].slug`)        |
| `build`       | object (opt.) | Optional build overrides (container and/or output path)                         |

### `bsp[*].build` fields

| Field       | Type          | Description                                                                       |
|-------------|---------------|-----------------------------------------------------------------------------------|
| `container` | string (opt.) | Container name override (key in `containers` section). When absent the container is taken from the release's named environment (or `"default"`). |
| `path`      | string (opt.) | Build output directory. When absent the path is auto-composed as `build/<distro>-<device>-<release>[-<feature>…]`. |

### KAS file ordering

The resolver assembles the final KAS file list in the following order:

```
framework.includes → distro.includes → release.includes → device.includes → feature.includes
```

This ensures that base build-system configuration (framework) is loaded first, followed
by distribution defaults, then release-specific settings, device-specific machine config,
and finally any optional feature additions.

---

## Full Example

The example below keeps everything in a single file.  See the
[`include` section](#include-optional) above for how to split it across multiple
files.

```yaml
specification:
  version: "2.0"

# Global environment variables (applied to all builds as a base)
environment:
  - name: "GITCONFIG_FILE"
    value: "$ENV{HOME}/.gitconfig"

# Global file copies executed before every build in this registry
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
      vendor_includes:
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

