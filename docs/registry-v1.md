# BSP Registry Schema v1.0 (Reference)

> **Note:** Schema v1.0 is no longer supported by `bsp-registry-tools`.
> This document is kept for historical reference only.
> See [migration-v1-to-v2.md](migration-v1-to-v2.md) to upgrade your registry file.

---

## Overview

In schema v1.0, the registry file contained a flat list of BSP definitions.
Each BSP entry bundled together the build system configuration, Docker container
reference, and KAS configuration files into a single monolithic object.

## Top-level Structure

```yaml
specification:
  version: "1.0"

environment:           # optional global env vars
  - name: "DL_DIR"
    value: "/path/to/downloads"

containers:            # list of container definitions
  - ubuntu-22.04:
      image: "my-registry/ubuntu:22.04"
      file: Dockerfile.ubuntu
      args:
        - name: "DISTRO"
          value: "ubuntu:22.04"

registry:
  bsp:                 # list of BSP definitions
    - name: poky-qemuarm64-scarthgap
      description: "Poky QEMU ARM64 Scarthgap"
      os:
        name: linux
        build_system: yocto
        version: "5.0"
      build:
        path: build/qemu-arm64-scarthgap
        environment:
          container: "ubuntu-22.04"   # or use docker: directly
        configuration:
          - kas/scarthgap.yaml
          - kas/qemu/qemuarm64.yaml
```

## Sections

### `specification`

| Field     | Type   | Description              |
|-----------|--------|--------------------------|
| `version` | string | Must be `"1.0"` for v1.0 |

### `environment` (optional)

Global environment variables applied to every build.

| Field   | Type   | Description                                     |
|---------|--------|-------------------------------------------------|
| `name`  | string | Variable name                                   |
| `value` | string | Value; may use `$ENV{VAR}` for system env lookup|

### `containers`

A **list** of container definitions.  Each item has one key (the container name)
whose value is a Docker configuration object.

```yaml
containers:
  - my-container:
      image: "my-image:latest"       # required
      file: Dockerfile               # optional: path to Dockerfile for build
      args:                          # optional: build args
        - name: "ARG_NAME"
          value: "arg_value"
```

### `registry.bsp`

A list of BSP definitions.  Each entry represents one buildable artefact.

| Field         | Type     | Description                                          |
|---------------|----------|------------------------------------------------------|
| `name`        | string   | Unique BSP identifier                                |
| `description` | string   | Human-readable description                           |
| `os`          | object   | Optional OS info (`name`, `build_system`, `version`) |
| `build.path`  | string   | Build output directory                               |
| `build.environment.container` | string | Container name from `containers` section |
| `build.environment.docker`    | object | Inline Docker config (alternative to `container`)   |
| `build.configuration`         | list   | Ordered list of KAS configuration files              |

## Limitations of v1.0

- All configuration is duplicated across every BSP entry (e.g., every board
  that shares the same Yocto release must repeat the release KAS file path).
- No concept of reusable features (OTA, secure-boot, etc.).
- No built-in compatibility rules.
- Board-specific and release-specific includes are not separated.
