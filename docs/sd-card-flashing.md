# SD Card / Block Device Flashing

`bsp flash` discovers the Yocto image produced by `bsp build` and writes it to
an SD card or USB storage device using
[**bmap-tools**](https://github.com/intel/bmap-tools) (`bmaptool copy`).

**Why bmap-tools?**  A `.bmap` block-map file is generated alongside every Yocto
WIC image by Yocto's `do_image_wic` task.  It records which 4 KiB blocks in the
image are non-empty and their SHA-256 checksums.  `bmaptool` reads this map to:

- **Skip empty blocks** — flashing a 4 GB image that is only 10 % full takes 10 %
  of the time.
- **Verify integrity** — each written block is verified against its stored
  checksum.
- **Flash compressed images directly** — `.wic.bz2`, `.wic.gz`, and `.wic.xz`
  images are decompressed on-the-fly without a prior extraction step.

`dd` is available as a fallback when bmap-tools is not installed.

---

## Prerequisites

### bmap-tools (recommended)

```bash
# Debian / Ubuntu
sudo apt install bmap-tools

# Arch Linux
sudo pacman -S bmap-tools

# From source (any distro)
pip install bmaptool

# Verify
bmaptool --version
```

Project page: <https://github.com/intel/bmap-tools>

### dd (fallback)

`dd` is part of GNU coreutils and is pre-installed on every Linux system.  It
does **not** read `.bmap` files, so every block is written regardless of whether
it contains data.  Use `dd` only when bmap-tools is unavailable.

---

## Quick Start

```bash
# 1. Build the image
bsp build imx8mp-adv-scarthgap

# 2. Insert the SD card (e.g. /dev/sdb — confirm with lsblk)
lsblk

# 3. Flash
bsp flash imx8mp-adv-scarthgap --target /dev/sdb

# — or — in one step
bsp build imx8mp-adv-scarthgap --flash /dev/sdb
```

> **Warning**: `--target /dev/sdb` writes directly to the block device.  Always
> double-check that the path points to the correct removable device before
> proceeding.

---

## Registry YAML configuration

A `flash:` block may be added at **root level** (global defaults for every
build) and/or at **preset level** (overrides the root config for that preset).
When no `flash:` block is defined anywhere, sensible defaults are used.

```yaml
# bsp-registry.yaml

specification:
  version: "2.2"

# -------------------------------------------------------------------
# Global flash defaults (applied to every preset unless overridden)
# -------------------------------------------------------------------
flash:
  tool: bmaptool                  # "bmaptool" (default) | "dd" | "uuu"
  image_patterns:                 # glob patterns, tried in order (first match wins)
    - "**/{build_target}-*.wic.*" # expanded at runtime when --target is given (first priority)
    - "**/*.wic.bz2"              # most-compressed variant preferred
    - "**/*.wic.gz"
    - "**/*.wic.xz"
    - "**/*.wic"
    - "**/*.sdimg"
    - "**/*.rpi-sdimg"
  artifact_dirs:                  # subdirs under build_path to search
    - "tmp/deploy/images"
  extra_args: null                # forwarded verbatim to the flash tool

registry:
  devices: [...]
  releases: [...]
  bsp:
    - name: imx8mp-adv-scarthgap
      description: "Advantech i.MX8MP Scarthgap"
      device: imx8mp-adv
      release: scarthgap
      build:
        path: build/imx8mp-adv/scarthgap

    # Preset-level flash override: skip the block-map for this board
    - name: rpi4-scarthgap
      description: "Raspberry Pi 4 Scarthgap"
      device: rpi4
      release: scarthgap
      flash:
        extra_args: "--nobmap"
```

### `flash:` field reference

| Field | Default | Description |
|-------|---------|-------------|
| `tool` | `bmaptool` | Flash tool: `bmaptool`, `dd`, or `uuu` (NXP mfgtools) |
| `image_patterns` | `["**/*.wic.bz2", "**/*.wic.gz", "**/*.wic.xz", "**/*.wic", "**/*.sdimg", "**/*.rpi-sdimg"]` | Glob patterns (relative to each artifact directory) used to discover flashable images. Evaluated in order; the first match wins. Patterns may contain `{build_target}` which is expanded to the BitBake target name at runtime (see below). |
| `artifact_dirs` | `["tmp/deploy/images"]` | Subdirectories under the build output path to search for images |
| `extra_args` | `null` | Additional arguments forwarded verbatim to the flash tool (e.g. `"--nobmap"` to skip block-map verification even when a `.bmap` file is present) |

### `{build_target}` placeholder in patterns

When `bsp build --target <name> --flash ...` (or `bsp flash --build-target <name>`) is
used, any `{build_target}` placeholder in `image_patterns` is replaced with the
actual BitBake target name at runtime.  This lets you write generic registry files
that automatically prefer the image produced by the requested build target.

**Example** — registry YAML:

```yaml
flash:
  image_patterns:
    - "**/{build_target}-*.wic.*"   # target-specific variant; highest priority when --target is given
    - "**/*.wic.bz2"
    - "**/*.wic.gz"
    - "**/*.wic.xz"
    - "**/*.wic"
```

When `bsp build my-preset --target core-image-minimal --flash /dev/sdb` runs:

1. `**/{build_target}-*.wic.*` → `**/core-image-minimal-*.wic.*` (expanded)
2. An additional exact-match pattern `**/core-image-minimal.wic.*` is **prepended** automatically as the highest-priority entry.
3. The resulting effective pattern list is:
   ```
   **/core-image-minimal.wic.*          ← auto-prepended (highest priority)
   **/core-image-minimal-*.wic.*        ← from registry (after expansion)
   **/*.wic.bz2
   **/*.wic.gz
   **/*.wic.xz
   **/*.wic
   ```

If `--target` is **not** supplied, `{build_target}` placeholders remain literal
and will not match any real file path — omit them from the fallback patterns if
you do not always provide a target.

### Config merge order

1. **Global `flash:`** from the registry root — baseline defaults
2. **Preset `flash:`** — overrides only the fields that differ from their defaults
3. **CLI flags** (`--tool`, `--image-pattern`, `--extra-args`, …) — highest priority

---

## CLI Usage

### `bsp flash` — standalone flash command

Flash the image for a named BSP preset:

```bash
bsp flash imx8mp-adv-scarthgap --target /dev/sdb
```

Flash by specifying device and release directly:

```bash
bsp flash --device imx8mp-adv --release scarthgap --target /dev/sdb
```

#### Common flags

```
bsp flash <preset | --device D --release R [--feature F ...]>
          [--target /dev/sdX]        # destination block device (required unless --dry-run or --tool uuu)
          [--image-path PATH]        # explicit image file (overrides auto-discovery)
          [--image-pattern PATTERN]  # override glob patterns (repeatable)
          [--tool bmaptool|dd|uuu]   # flash tool override
          [--extra-args ARGS]        # forwarded verbatim to the flash tool
          [--build-path PATH]        # override the build output directory
          [--dry-run]                # show what would be flashed without writing
```

For non-dry-run flashes, `bsp` executes the final flash command with superuser
rights (via `sudo` when not already running as root).

#### Examples

```bash
# Standard flash (bmaptool detects and uses the .bmap file automatically)
bsp flash imx8mp-adv-scarthgap --target /dev/sdb

# Preview — list what would be flashed without writing anything
bsp flash imx8mp-adv-scarthgap --target /dev/sdb --dry-run

# Flash a specific image file explicitly (skips auto-discovery)
bsp flash imx8mp-adv-scarthgap \
    --target /dev/sdb \
    --image-path build/imx8mp-adv/scarthgap/tmp/deploy/images/core-image-minimal.wic.bz2

# Use dd instead of bmaptool (no block-map acceleration)
bsp flash imx8mp-adv-scarthgap --target /dev/sdb --tool dd

# Use uuu (mfgtools) for NXP USB flashing (target device path not required;
# "-b emmc_all" is used by default unless --extra-args supplies a burn script)
bsp flash imx8mp-adv-scarthgap --tool uuu

# Pass extra args to bmaptool (e.g. skip block-map verification)
bsp flash imx8mp-adv-scarthgap --target /dev/sdb --extra-args "--nobmap"

# Flash using component selectors (no preset needed)
bsp flash --device imx8mp-adv --release scarthgap --target /dev/sdb

# Dry-run without --target (--dry-run does not require a real device)
bsp flash imx8mp-adv-scarthgap --dry-run
```

#### Dry-run output

```
[dry-run] Would flash:
  image : build/imx8mp-adv/scarthgap/tmp/deploy/images/core-image-minimal-imx8mp.wic.bz2
  bmap  : build/imx8mp-adv/scarthgap/tmp/deploy/images/core-image-minimal-imx8mp.wic.bmap
  target: /dev/sdb
```

### `bsp build --flash` — flash after build

The `--flash DEVICE` flag on `bsp build` flashes the image immediately after a
successful build (analogous to `--deploy` and `--scan`):

```bash
# Build and immediately flash the result
bsp build imx8mp-adv-scarthgap --flash /dev/sdb

# Combined: build, deploy to cloud, then flash to SD card
bsp build imx8mp-adv-scarthgap --deploy --flash /dev/sdb

# Build, flash, and override the tool
bsp build imx8mp-adv-scarthgap --flash /dev/sdb --flash-tool dd
```

#### `--flash` flags on `bsp build`

| Option | Description |
|--------|-------------|
| `--flash DEVICE` | Flash the built image to `DEVICE` after a successful build |
| `--flash-tool TOOL` | Override the flash tool (`bmaptool`, `dd`, or `uuu`) |

---

## How image discovery works

When `--image-path` is not given, `ImageFlasher` searches for the flashable
image automatically:

1. For each directory listed in `artifact_dirs` (default: `tmp/deploy/images`),
   the directory `<build_path>/<artifact_dir>` is searched.
2. The `image_patterns` list is iterated **in order**.  For each pattern all
   matching files are collected.
3. The **first** matching file from the **first** successful pattern is used.
   This means `.wic.bz2` is preferred over `.wic.gz`, which is preferred over
   `.wic`, and so on.
4. When more than one file matches the winning pattern, a `WARNING` is logged
   and the **first** (alphabetically earliest) file is used.  Specify
   `--image-path` to select a particular file when multiple images exist.

### `{build_target}` placeholder expansion

Before the patterns are evaluated, any `{build_target}` token in each pattern
string is replaced with the BitBake target name supplied via `--target`.  In
addition, the exact pattern `**/<target>.wic.*` is always **prepended** as the
highest-priority entry so that the exact output image for the requested target
is tried first.

See [above](#build_target-placeholder-in-patterns) for a worked example.

### Block-map (`.bmap`) discovery

`bmaptool` can locate `.bmap` files automatically when they are in the same
directory as the image.  `bsp flash` additionally probes the following locations
so the path is visible in the dry-run output and in `FlashResult`:

| Image filename | Probed `.bmap` filename |
|----------------|------------------------|
| `image.wic` | `image.wic.bmap` |
| `image.wic.bz2` | `image.wic.bz2.bmap` (preferred) → `image.wic.bmap` (fallback) |
| `image.wic.gz` | `image.wic.gz.bmap` (preferred) → `image.wic.bmap` (fallback) |
| `image.wic.xz` | `image.wic.xz.bmap` (preferred) → `image.wic.bmap` (fallback) |

---

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Flash completed successfully |
| `1` | No image found, flash tool missing, or flash command failed |

---

## Supported image formats

| Format | Tool | Notes |
|--------|------|-------|
| `*.wic.bz2` | `bmaptool` | Decompressed on-the-fly; `.bmap` used if present |
| `*.wic.gz` | `bmaptool` | Decompressed on-the-fly; `.bmap` used if present |
| `*.wic.xz` | `bmaptool` | Decompressed on-the-fly; `.bmap` used if present |
| `*.wic` | `bmaptool` | Block-map accelerated; `.bmap` used if present |
| `*.sdimg` | `bmaptool` / `dd` | Raw disk image; pass `--tool dd` if no `.bmap` available |
| `*.rpi-sdimg` | `bmaptool` / `dd` | Raspberry Pi SD card image; same as `*.sdimg` |

---

## Python API

```python
from bsp import BspManager

manager = BspManager("bsp-registry.yaml")
manager.initialize()

# Dry-run flash for a preset
result = manager.flash_bsp(
    "imx8mp-adv-scarthgap",
    target_device="/dev/sdb",
    dry_run=True,
)
print(f"Would flash: {result.image_path}")
if result.bmap_path:
    print(f"  bmap: {result.bmap_path}")

# Flash with runtime overrides
result = manager.flash_bsp(
    "imx8mp-adv-scarthgap",
    target_device="/dev/sdb",
    flash_overrides={
        "tool": "dd",
        "extra_args": None,
    },
)
print(f"Success: {result.success}, elapsed: {result.elapsed_seconds:.1f}s")

# Flash by components (no preset needed)
result = manager.flash_by_components(
    device_slug="imx8mp-adv",
    release_slug="scarthgap",
    target_device="/dev/sdb",
)

# Use the lower-level flasher directly
from bsp.flasher import ImageFlasher
from bsp.models import FlashConfig

config = FlashConfig(
    tool="bmaptool",
    image_patterns=["**/*.wic.bz2", "**/*.wic"],
    artifact_dirs=["tmp/deploy/images"],
)
flasher = ImageFlasher(config)

result = flasher.flash(
    build_path="build/imx8mp-adv/scarthgap",
    target_device="/dev/sdb",
)
print(f"Flashed {result.image_path.name} in {result.elapsed_seconds:.1f}s")
```

---

## Integration with CI/CD

Flashing a physical device from a CI runner requires the runner to have the
device connected (or use a lab environment with a remote flasher).  The typical
pattern in CI is:

1. Build the image and upload it to cloud storage.
2. A separate hardware-in-the-loop (HIL) step (see `bsp test`) downloads the
   image and flashes it to the DUT.

For local development, `bsp build --flash` is the most convenient one-liner:

```yaml
# GitHub Actions example (self-hosted runner with SD card writer attached)
- name: Build and flash BSP
  run: |
    bsp build imx8mp-adv-scarthgap --flash /dev/sdb

- name: Flash a pre-built image
  run: |
    bsp flash imx8mp-adv-scarthgap \
      --build-path /mnt/artifacts/build \
      --target /dev/sdb
```
