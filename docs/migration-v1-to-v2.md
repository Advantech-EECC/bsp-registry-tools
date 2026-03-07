# Migration Guide: v1.0 → v2.0

This guide explains how to upgrade your BSP registry file from **schema v1.0**
to **schema v2.0**.

> See [registry-v1.md](registry-v1.md) for a reference description of the old format.
> See [registry-v2.md](registry-v2.md) for a complete description of the new format.

---

## Breaking Changes

- `specification.version` **must** be `"2.0"`.  The tool exits immediately with a
  clear error if it detects any other version.
- The monolithic `registry.bsp` list of v1.0 is replaced by separate
  `registry.devices`, `registry.releases`, and `registry.features` sections.
- The v1.0 `registry.bsp[*].build` structure (`path`, `environment`, `configuration`)
  no longer exists on preset entries.  Build configuration now lives on `devices[*]`.
- The v1.0 `registry.bsp[*].os` block is removed; set `yocto_version` / `isar_version`
  on the release instead.
- The `containers` section now uses a **dict** format (`name: {…}`) instead of a
  list (`- name: {…}`).  The list format is still accepted for backward compatibility
  in the containers section only.

---

## Field Mapping

### `specification`

| v1.0                     | v2.0                     |
|--------------------------|--------------------------|
| `specification.version: "1.0"` | `specification.version: "2.0"` |

### `containers`

| v1.0                            | v2.0                             |
|---------------------------------|----------------------------------|
| `containers:` (list of dicts)   | `containers:` (dict)             |

**v1.0:**
```yaml
containers:
  - debian-bookworm:
      image: "my-registry/debian/kas:5.1"
      file: Dockerfile
      args:
        - name: "KAS_VERSION"
          value: "5.1"
```

**v2.0:**
```yaml
containers:
  debian-bookworm:
    image: "my-registry/debian/kas:5.1"
    file: Dockerfile
    args:
      - name: "KAS_VERSION"
        value: "5.1"
```

### `registry.bsp` entries → `registry.devices` + `registry.releases` + `registry.bsp`

Each v1.0 BSP entry must be decomposed:

| v1.0 field                          | v2.0 destination                          |
|-------------------------------------|-------------------------------------------|
| `bsp[*].name`                       | `bsp[*].name` (preset name)               |
| `bsp[*].description`                | `bsp[*].description` (preset description) |
| `bsp[*].build.path`                 | `devices[*].build.path`                   |
| `bsp[*].build.environment.container`| `devices[*].build.container`              |
| `bsp[*].build.configuration[0]` (release file) | `releases[*].includes`        |
| `bsp[*].build.configuration[1+]` (board files) | `devices[*].build.includes`   |
| `bsp[*].os.version`                 | `releases[*].yocto_version`               |
| `bsp[*].os.name`, `build_system`    | (informational only, not in v2.0 schema)  |

---

## Worked Example

### v1.0 Registry (before)

```yaml
specification:
  version: "1.0"

environment:
  - name: "DL_DIR"
    value: "$ENV{HOME}/data/cache/downloads"

containers:
  - debian-bookworm:
      image: "bsp/registry/debian/kas:5.1"
      file: Dockerfile
      args:
        - name: "DISTRO"
          value: "debian-bookworm"

registry:
  bsp:
    - name: poky-qemuarm64-scarthgap
      description: "Poky QEMU ARM64 Scarthgap (Yocto 5.0 LTS)"
      os:
        name: linux
        build_system: yocto
        version: "5.0"
      build:
        path: build/qemu-arm64-scarthgap
        environment:
          container: "debian-bookworm"
        configuration:
          - kas/scarthgap.yaml
          - kas/qemu/qemuarm64.yaml

    - name: poky-qemuarm64-styhead
      description: "Poky QEMU ARM64 Styhead (Yocto 5.1)"
      os:
        name: linux
        build_system: yocto
        version: "5.1"
      build:
        path: build/qemu-arm64-styhead
        environment:
          container: "debian-bookworm"
        configuration:
          - kas/styhead.yaml
          - kas/qemu/qemuarm64.yaml

    - name: poky-qemux86-64-scarthgap
      description: "Poky QEMU x86-64 Scarthgap (Yocto 5.0 LTS)"
      os:
        name: linux
        build_system: yocto
        version: "5.0"
      build:
        path: build/qemu-x86-64-scarthgap
        environment:
          container: "debian-bookworm"
        configuration:
          - kas/scarthgap.yaml
          - kas/qemu/qemux86-64.yaml
```

### v2.0 Registry (after)

```yaml
specification:
  version: "2.0"

environment:
  - name: "DL_DIR"
    value: "$ENV{HOME}/data/cache/downloads"

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
        path: build/qemu-arm64        # shared base path; per-preset subdir no longer needed
        includes:
          - kas/qemu/qemuarm64.yaml

    - slug: qemux86-64
      description: "QEMU x86-64 (emulated)"
      vendor: qemu
      soc_vendor: intel
      build:
        container: "debian-bookworm"
        path: build/qemu-x86-64
        includes:
          - kas/qemu/qemux86-64.yaml

  releases:
    - slug: scarthgap
      description: "Yocto 5.0 LTS (Scarthgap)"
      yocto_version: "5.0"
      includes:
        - kas/scarthgap.yaml

    - slug: styhead
      description: "Yocto 5.1 (Styhead)"
      yocto_version: "5.1"
      includes:
        - kas/styhead.yaml

  features: []    # no features in this example

  bsp:
    - name: poky-qemuarm64-scarthgap
      description: "Poky QEMU ARM64 Scarthgap (Yocto 5.0 LTS)"
      device: qemuarm64
      release: scarthgap
      features: []

    - name: poky-qemuarm64-styhead
      description: "Poky QEMU ARM64 Styhead (Yocto 5.1)"
      device: qemuarm64
      release: styhead
      features: []

    - name: poky-qemux86-64-scarthgap
      description: "Poky QEMU x86-64 Scarthgap (Yocto 5.0 LTS)"
      device: qemux86-64
      release: scarthgap
      features: []
```

---

## CLI Command Mapping

| v1.0 command                       | v2.0 equivalent                                    |
|------------------------------------|----------------------------------------------------|
| `bsp list`                         | `bsp list` (shows presets) or `bsp list devices`   |
| `bsp build <bsp_name>`             | `bsp build <preset_name>` (unchanged)              |
| `bsp build <bsp_name>`             | `bsp build --device <d> --release <r>` (new style) |
| `bsp export <bsp_name>`            | `bsp export <preset_name>` (unchanged)             |
| `bsp shell <bsp_name>`             | `bsp shell <preset_name>` (unchanged)              |
| `bsp containers`                   | `bsp containers` (unchanged)                       |

New v2.0 CLI commands:
```bash
bsp list devices
bsp list releases
bsp list releases --device <device_slug>
bsp list features
bsp build --device <d> --release <r> [--feature <f> ...]
bsp export --device <d> --release <r> [--feature <f> ...] [--output file]
bsp shell --device <d> --release <r> [--feature <f> ...]
```
