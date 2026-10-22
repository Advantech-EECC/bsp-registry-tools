# Artifact Deployment Guide

`bsp-registry-tools` can upload Yocto/Isar build artifacts produced by
`bsp build` to **Azure Blob Storage** (default) or **AWS S3** after the build
completes.  It also supports uploading and restoring **Yocto build caches**
(`DL_DIR` and `SSTATE_DIR`) so team members and CI agents can seed their local
caches without running a full build.

---

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Registry Configuration](#registry-configuration)
  - [Global `deploy:` block](#global-deploy-block)
  - [Per-preset override](#per-preset-override)
  - [Field reference](#field-reference)
  - [Prefix template placeholders](#prefix-template-placeholders)
  - [Archive bundling](#archive-bundling)
  - [Yocto cache upload](#yocto-cache-upload)
  - [HTML index generation](#html-index-generation)
- [Public access without anonymous blob access](#public-access-without-anonymous-blob-access)
- [Authentication](#authentication)
  - [Azure](#azure)
  - [AWS](#aws)
- [CLI Reference](#cli-reference)
  - [`bsp deploy`](#bsp-deploy)
  - [`bsp build --deploy`](#bsp-build---deploy)
  - [`bsp gather`](#bsp-gather)
  - [`bsp deploy index`](#bsp-deploy-index)
- [Dry-run mode](#dry-run-mode)
- [Artifact manifest](#artifact-manifest)
- [Partial failures](#partial-failures)
- [Python API](#python-api)
- [CI/CD integration](#cicd-integration)
  - [GitHub Actions – Azure](#github-actions--azure)
  - [GitHub Actions – AWS](#github-actions--aws)

---

## Overview

After a Yocto build, images and SDKs land under:

```
<build_path>/tmp/deploy/images/
<build_path>/tmp/deploy/sdk/
```

`bsp deploy` finds all files that match the configured glob patterns in those
directories and uploads them to your cloud storage provider.  An optional JSON
manifest (with artifact names, sizes, and SHA-256 checksums) is uploaded
alongside the artifacts.

When `yocto_cache` is enabled, the tool also packs the Yocto download cache
(`DL_DIR`) and/or the shared-state cache (`SSTATE_DIR`) as `tar.gz` archives
and uploads them under a `cache/` sub-directory of the same prefix.

`bsp gather` downloads previously deployed artifacts.  With `--gather-cache` it
also downloads and extracts the cache archives back to the configured local
directories — no full build needed to warm up the cache on a fresh machine.

Config can live either in the registry YAML (checked in, shared by the team) or
be overridden entirely from the command line.

---

## Quick Start

```bash
# 1. Install cloud SDK extras (one-time)
pip install "bsp-registry-tools[azure]"   # Azure
pip install "bsp-registry-tools[aws]"     # AWS
pip install "bsp-registry-tools[deploy]"  # both

# 2. Authenticate (one-time)
az login                          # Azure (interactive)
aws configure                     # AWS (interactive)

# 3. Build and deploy in one step
bsp build poky-qemuarm64-scarthgap --deploy --deploy-container bsp-artifacts

# — or — deploy separately after a successful build
bsp deploy poky-qemuarm64-scarthgap --container bsp-artifacts

# Also upload Yocto caches (DL_DIR / SSTATE_DIR) after a build
bsp deploy poky-qemuarm64-scarthgap --container bsp-artifacts --deploy-cache

# Download artifacts from cloud storage
bsp gather poky-qemuarm64-scarthgap --dest-dir ./downloads

# Download artifacts AND restore Yocto caches
bsp gather poky-qemuarm64-scarthgap \
    --dest-dir ./downloads \
    --gather-cache \
    --cache-downloads-dir /mnt/yocto/downloads \
    --cache-sstate-dir /mnt/yocto/sstate

# Preview what would be uploaded (no credentials required)
bsp deploy poky-qemuarm64-scarthgap --dry-run
```

---

## Installation

Cloud SDK dependencies are **optional** to avoid forcing them on users who do
not need deployment.

```bash
# Azure Blob Storage support
pip install "bsp-registry-tools[azure]"
# installs: azure-storage-blob>=12.0, azure-identity>=1.0

# AWS S3 support
pip install "bsp-registry-tools[aws]"
# installs: boto3>=1.20

# Both providers
pip install "bsp-registry-tools[deploy]"
```

`--dry-run` mode works **without any cloud SDK installed**.

---

## Registry Configuration

### Global `deploy:` block

Add a top-level `deploy:` block to your registry YAML.  It applies to every
build by default.

```yaml
specification:
  version: "2.0"

deploy:
  provider: azure
  account_url: $ENV{AZURE_STORAGE_ACCOUNT_URL}   # supports $ENV{} expansion
  container: bsp-artifacts
  prefix: "{vendor}/{device}/{release}/{date}"
  patterns:
    - "**/*.wic.gz"
    - "**/*.wic.bz2"
    - "**/*.tar.bz2"
    - "**/*.ext4"
    - "**/*.sdimg"
  artifact_dirs:
    - tmp/deploy/images
    - tmp/deploy/sdk
  include_manifest: true
  include_build_manifest: true
  # Optional: bundle all artifacts into a single archive before uploading
  archive:
    name: "firmware-{device}-{release}-{date}"
    format: tar.gz

registry:
  # ...
```

**AWS variant:**

```yaml
deploy:
  provider: aws
  bucket: my-s3-bucket
  region: eu-west-1
  prefix: "{device}/{release}/{date}"
  patterns:
    - "**/*.wic.gz"
  artifact_dirs:
    - tmp/deploy/images
```

### Per-preset override

An individual `BspPreset` entry can include its own `deploy:` block.  Only the
fields that differ from the `DeployConfig` defaults override the global config;
all other fields keep their global values.

**Merge order** (later entries win):
1. **Global `deploy:`** — baseline for every build
2. **Preset `deploy:`** — overrides only fields that differ from their defaults
3. **CLI flags** (`--provider`, `--container`, …) — highest priority

```yaml
deploy:                               # global: Azure, shared container
  provider: azure
  account_url: $ENV{AZURE_STORAGE_ACCOUNT_URL}
  container: bsp-artifacts
  prefix: "{vendor}/{device}/{release}/{date}"

registry:
  bsp:
    # Uses global settings unchanged.
    - name: qemuarm64-scarthgap
      device: qemuarm64
      release: scarthgap
      features: []

    # Overrides only container and prefix; provider and account_url come from global.
    - name: imx8mp-adv-scarthgap-release
      description: "Advantech i.MX8MP Scarthgap – release artefacts"
      device: imx8mp-adv
      release: scarthgap
      features: []
      deploy:
        container: imx8mp-release-artifacts           # ← override
        prefix: "release/{device}/{release}/{date}"   # ← override
        patterns:                                     # ← override
          - "**/*.wic.gz"

    # Switches to AWS entirely for this preset only.
    - name: aws-build-scarthgap
      device: qemuarm64
      release: scarthgap
      features: []
      deploy:
        provider: aws                 # ← override: switch provider
        container: my-s3-bucket       # ← override: bucket name
```

### Field reference

| Field              | Type          | Default | Description |
|--------------------|---------------|---------|-------------|
| `provider`         | string        | `"azure"` | Cloud provider: `"azure"` or `"aws"` |
| `container`        | string (opt.) | —       | Azure Blob container name |
| `bucket`           | string (opt.) | —       | AWS S3 bucket name |
| `account_url`      | string (opt.) | —       | Azure account URL; supports `$ENV{VAR}` expansion. Falls back to the `AZURE_STORAGE_ACCOUNT_URL` env var. |
| `prefix`           | string (opt.) | `"{vendor}/{device}/{release}/{date}"` | Remote path prefix template (see [placeholders](#prefix-template-placeholders)) |
| `patterns`         | list[str]     | `["**/*.wic*", "**/*.tar.gz", "**/*.ext4", "**/*.sdimg"]` | Glob patterns for artifact files |
| `artifact_dirs`    | list[str]     | `["tmp/deploy/images", "tmp/deploy/sdk"]` | Subdirectories under the build path to scan |
| `include_manifest` | bool          | `true`  | Upload a JSON manifest alongside artifacts |
| `include_build_manifest` | bool    | `true`  | Upload the `build-manifest.json` written by `bsp build` |
| `archive`          | object (opt.) | —       | Bundle all artifacts into a single archive before uploading. See [Archive bundling](#archive-bundling). |
| `region`           | string (opt.) | —       | AWS region (optional; boto3 default otherwise) |
| `profile`          | string (opt.) | —       | AWS credentials profile (optional) |
| `yocto_cache`      | object (opt.) | —       | Upload / restore Yocto DL_DIR / SSTATE_DIR caches. See [Yocto cache upload](#yocto-cache-upload). |
| `index`            | object (opt.) | —       | Generate a browsable `index.html` of the uploaded artifacts. See [HTML index generation](#html-index-generation). |

### Prefix template placeholders

The `prefix` field is a Python format string.  The following variables are
available at deploy time:

| Placeholder  | Example value    | Description |
|--------------|------------------|-------------|
| `{device}`   | `qemuarm64`      | Device slug |
| `{release}`  | `scarthgap`      | Release slug |
| `{distro}`   | `poky`           | Effective distro slug |
| `{vendor}`   | `qemu`           | Device vendor slug |
| `{date}`     | `2025-03-15`     | Build date (UTC, `YYYY-MM-DD`) |
| `{datetime}` | `20250315-143022` | Build date + time (UTC, `YYYYMMDD-HHMMSS`) |

**Example prefixes:**

```
{vendor}/{device}/{release}/{date}
→  qemu/qemuarm64/scarthgap/2025-03-15/

builds/{device}/{date}
→  builds/qemuarm64/2025-03-15/

release/{release}/{device}
→  release/scarthgap/qemuarm64/
```

---

## Archive bundling

By default every matching artifact file is uploaded individually.  Set the
`archive:` sub-object inside `deploy:` to collect all artifacts into a single
compressed archive **before** uploading.  Only the archive (plus the manifest
when `include_manifest: true`) is uploaded.

```yaml
deploy:
  provider: azure
  container: bsp-artifacts
  archive:
    name: "firmware-{device}-{release}-{date}"
    format: tar.gz
```

### `archive` fields

| Field    | Type   | Default                       | Description |
|----------|--------|-------------------------------|-------------|
| `name`   | string | `"artifacts-{device}-{date}"` | Archive filename template (without extension).  Supports the same placeholders as `prefix`: `{device}`, `{release}`, `{distro}`, `{vendor}`, `{date}`, `{datetime}`. |
| `format` | string | `"tar.gz"`                    | Compression format: `tar.gz`, `tar.bz2`, `tar.xz`, or `zip`. |

The appropriate file extension is appended automatically (e.g. `.tar.gz` for
`tar.gz`).

**CLI equivalents:**

```bash
# bsp deploy
bsp deploy my-preset \
    --archive-name "firmware-{device}-{release}-{date}" \
    --archive-format tar.gz

# bsp build --deploy
bsp build my-preset --deploy \
    --deploy-archive-name "firmware-{device}-{release}-{date}" \
    --deploy-archive-format tar.gz
```

---

## Yocto cache upload

Enable `yocto_cache` in your `deploy:` block to also upload the Yocto build
caches (`DL_DIR` downloads cache and `SSTATE_DIR` shared-state cache) to the
same cloud prefix.  Cache upload is **opt-in** (disabled by default) and has
no impact on the regular artifact upload pipeline.

```yaml
deploy:
  provider: azure
  container: bsp-artifacts
  prefix: "{vendor}/{device}/{release}/{date}"

  yocto_cache:
    enabled: true          # master switch — must be true to upload anything
    downloads: true        # upload DL_DIR  (default: true)
    sstate: true           # upload SSTATE_DIR (default: true)
    # Optional: hard-code paths instead of using DL_DIR / SSTATE_DIR env vars
    # downloads_path: /mnt/yocto/downloads
    # sstate_path: /mnt/yocto/sstate
```

### How it works

1. **Deploy** – the tool reads `DL_DIR` / `SSTATE_DIR` from the environment
   (or from `downloads_path` / `sstate_path` if set in the registry).  Each
   enabled cache directory is packed into a `tar.gz` archive and uploaded under
   `{prefix}/cache/`:

   ```
   {prefix}/cache/downloads.tar.gz
   {prefix}/cache/sstate.tar.gz
   ```

   Cache metadata (remote URL, size, SHA-256) is recorded in the
   `yocto_cache` section of `manifest.json`.

2. **Gather** – run `bsp gather --gather-cache` to download and extract the
   cache archives back to the local filesystem.  A missing cache archive is
   treated as a soft warning — the rest of the gather succeeds normally.

### `yocto_cache` fields

| Field            | Type          | Default | Description |
|------------------|---------------|---------|-------------|
| `enabled`        | bool          | `false` | Master switch.  Must be `true` to upload any caches. |
| `downloads`      | bool          | `true`  | Include `DL_DIR` in the upload / restore. |
| `sstate`         | bool          | `true`  | Include `SSTATE_DIR` in the upload / restore. |
| `downloads_path` | string (opt.) | —       | Override the local `DL_DIR` path. Falls back to `DL_DIR`, then `<topdir>/downloads` (TOPDIR inferred from `artifact_dirs`). |
| `sstate_path`    | string (opt.) | —       | Override the local `SSTATE_DIR` path. Falls back to `SSTATE_DIR`, then `<topdir>/sstate-cache` (TOPDIR inferred from `artifact_dirs`). |

### CLI flags

**Upload caches with `bsp deploy`:**

```bash
# Upload artifacts + DL_DIR + SSTATE_DIR
bsp deploy my-preset --deploy-cache

# Upload artifacts + DL_DIR only (skip sstate)
bsp deploy my-preset --deploy-cache --no-deploy-cache-sstate

# Upload artifacts + SSTATE_DIR only (skip downloads)
bsp deploy my-preset --deploy-cache --no-deploy-cache-downloads

# Same flags work with bsp build --deploy
bsp build my-preset --deploy --deploy-cache
```

**Restore caches with `bsp gather`:**

```bash
# Download artifacts + restore both caches to default dirs
bsp gather my-preset --gather-cache

# Specify exact restore paths
bsp gather my-preset \
    --gather-cache \
    --cache-downloads-dir /mnt/yocto/downloads \
    --cache-sstate-dir /mnt/yocto/sstate

# Dry run – see what would be downloaded/restored
bsp gather my-preset --dry-run --gather-cache
```

> **Note**: `bsp gather --gather-cache` uses the `DL_DIR` and `SSTATE_DIR`
> environment variables as default restore destinations (same as the deploy
> side).  Explicit `--cache-downloads-dir` / `--cache-sstate-dir` flags take
> priority.  If neither is set, archives are extracted into
> `<topdir>/downloads` and `<topdir>/sstate-cache`, where TOPDIR is the
> Yocto build directory inferred from the `artifact_dirs` configuration
> (e.g. `build/tmp/deploy/images` → TOPDIR = `<dest-dir>/build/`).

### Manifest with cache entries

When caches are uploaded the `manifest.json` gains a `yocto_cache` section:

```json
{
  "schema_version": "1",
  "artifacts": [ ... ],
  "yocto_cache": {
    "downloads": {
      "name": "downloads.tar.gz",
      "remote_url": "https://<account>.blob.core.windows.net/bsp-artifacts/acme/myboard/scarthgap/2025-01-15/cache/downloads.tar.gz",
      "size_bytes": 2147483648,
      "sha256": "..."
    },
    "sstate": {
      "name": "sstate.tar.gz",
      "remote_url": "https://...",
      "size_bytes": 5368709120,
      "sha256": "..."
    }
  }
}
```

`bsp gather --gather-cache` uses this section to locate the correct archive
URLs.  Old manifests that lack the `yocto_cache` section are handled
gracefully — the gatherer falls back to the heuristic
`{prefix}/cache/{type}.tar.gz` path.

---

## HTML index generation

Add an `index:` block to `deploy:` to publish a browsable `index.html` next to
the uploaded artifacts:

```yaml
deploy:
  provider: azure
  container: bsp-artifacts
  index:
    enabled: true
    title: "{vendor} {device} — {release}"
    sign_urls: true
    sas_expiry: "2038-01-19T03:14:06Z"
    tree: true
    collapse_depth: 1
    search: true
    show_dates: true
    facets: [preset, machine, release, date]
    theme: auto
    exclude:
      - "cache/*"
```

### `index` fields

| Field        | Type   | Default | Description |
|--------------|--------|---------|-------------|
| `enabled`    | bool   | `false` | Master switch.  Index generation is opt-in. |
| `title`      | string | `"{vendor} {device} — {release}"` | Page title template.  Supports the same placeholders as `prefix`. |
| `sign_urls`  | bool   | `true`  | Link artifacts through read-only signed URLs (Azure SAS / S3 presigned).  Set to `false` when a CDN, Front Door or custom domain fronts the container — relative links are emitted instead. |
| `sas_expiry` | string | `"2038-01-19T03:14:06Z"` | Expiry timestamp (ISO-8601) for generated signed URLs.  The default is the 32-bit `time_t` limit. |
| `root_index` | bool   | `true`  | Deprecated and ignored.  A single `index.html` is always written at the container root; no `index.html` is generated inside artifact folders. |
| `tree`       | bool   | `true`  | Render a collapsible tree that preserves the remote directory structure below the indexed prefix.  Set to `false` for the legacy flat table. |
| `collapse_depth` | int | `1`    | Directory depth expanded by default in the tree view (`1` expands only the top level). |
| `search`     | bool   | `true`  | Show the search / filter box.  Plain substrings and simple `*` / `?` globs are matched against the full relative path. |
| `exclude`    | list   | `[]`    | Glob patterns (matched against the path relative to the indexed prefix, or against the bare file name) omitted from the index. |
| `show_dates` | bool   | `true`  | Show last-modified timestamps when the storage backend provides them. |
| `facets`     | list   | `[preset, machine, release, date]` | Facet groups shown in the filter bar.  Supported names: `preset`, `machine`, `release`, `distro`, `vendor`, `date`.  An empty list disables faceted filtering. |
| `theme`      | string | `"auto"` | Colour scheme: `auto` (follows `prefers-color-scheme`), `light` or `dark`. |
| `accent`     | string | `""`    | CSS colour used as the page accent (e.g. `"#0366d6"`).  Empty keeps the built-in accent. |

The page is self-contained (no external assets, no CDN JavaScript, no server),
so it loads from a private container through a single signed URL.  It ships a
design-token stylesheet with automatic dark mode, a sticky header holding the
title, a clickable prefix breadcrumb and the filter bar, per-type artifact
icons, click-to-copy SHA-256 values, keyboard-navigable tree rows and a live
"N files · M total" summary.  It lists
every artifact with its human-readable size, last-modified timestamp and short
SHA-256, links to `manifest.json`, and carries no-cache `<meta>` tags so
browsers never show stale, expired links.

Above the tree a faceted filter bar offers multi-select chips for the BSP
preset, machine, Yocto release and upload date (with `Today` / `Last 7 days` /
`Last 30 days` / `Older` buckets and a `From`–`To` date range).  Values are
ANDed across groups and ORed within a group, chip counts update live, and every
active facet is encoded in the URL fragment so a filtered view can be
bookmarked or shared.  Facet values are recorded at deploy time in an
`index-meta.json` sidecar next to `manifest.json`, so `bsp deploy index`
rebuilds and the container-root index keep them; when the sidecar is missing
they are recovered by inverting the configured `prefix` template.  The
container-root index lists one row per build prefix with its facets, newest
first, and is filtered by the same bar.

In the default tree view the remote directory structure of the container is
preserved, so nested artifacts (`images/…`, `sdk/…`, cache archives)
keep their folders and identically named files in different directories stay
distinct.  The inlined vanilla-JavaScript renderer provides:

- **fold / unfold** of directories, with per-directory file counts and
  aggregated sizes, plus *Expand all* / *Collapse all* buttons;
- **search** by substring or simple glob against the full relative path,
  auto-expanding the ancestors of every match;
- **sorting** by name, size or last-modified within each directory level;
- **shareable state** — the active query, type filter and expanded folders are
  mirrored into the URL hash.

A `<noscript>` fallback renders the same artifacts as the plain flat table, and
`--flat` (or `tree: false`) selects that table unconditionally.  Only
`index.html` pages are skipped, so genuine HTML build artifacts such as reports
remain listed.  Every interpolated value is HTML-escaped and the embedded JSON
data island is escaped so a hostile blob name cannot break out of its
`<script>` element.

The index is **fully regenerated** on every run from the current artifact set
(or, for `bsp deploy index`, from the live container listing) — it is never appended
to, so links are always fresh.

---

## Public access without anonymous blob access

Storage accounts with `allowBlobPublicAccess=false` (and no `$web` static
website endpoint) cannot serve blobs anonymously.  The generated index solves
this without weakening that posture: each artifact link is a **read-only signed
URL**, and `index.html` itself is fetched through a signed URL.

On Azure the backend picks the strongest available option:

1. **Account-key SAS** — used when `AZURE_STORAGE_CONNECTION_STRING` (or an
   explicit connection string) is available.  Supports arbitrary expiry, so the
   2038 sentinel works as-is.
2. **User-delegation SAS** — used when authenticated via
   `DefaultAzureCredential` (`az login`, managed identity, service principal).
   Azure caps delegation keys at **7 days**, so longer expiries are clamped
   automatically with a warning.

On AWS `get_signed_url()` returns an S3 presigned URL (capped at 7 days).

Trade-offs to be aware of:

- Anyone holding a link can download that blob until the SAS expires — treat
  the links as bearer tokens.
- User-delegation links expire after at most 7 days; schedule
  `bsp deploy index <container>` (for example from a nightly job) to re-sign
  them.
- Signed links are not written to logs, and the account key / connection string
  is never logged or embedded in the page.
- Uploads set `Content-Type: application/octet-stream` (with **no**
  `Content-Encoding`) for artifacts so browsers do not transparently decompress
  `*.wic.gz` images and corrupt them; `index.html` is stored as `text/html` so
  it renders instead of downloading.

---

## Authentication

### Azure

Credentials are resolved in the following order:

1. **`AZURE_STORAGE_CONNECTION_STRING`** environment variable — if set, the
   connection string is used directly (no `account_url` needed).
2. **`deploy.account_url`** (or `AZURE_STORAGE_ACCOUNT_URL` env var) +
   `DefaultAzureCredential` — supports any of the methods below transparently:

| Method | Required setup |
|--------|---------------|
| Azure CLI | `az login` |
| Service principal | `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID` env vars |
| Managed Identity | Automatic on Azure VMs / AKS / App Service |
| Workload Identity | Automatic in AKS with OIDC |

**Minimal local setup:**

```bash
export AZURE_STORAGE_ACCOUNT_URL=https://myaccount.blob.core.windows.net
az login
bsp deploy my-preset --container bsp-artifacts
```

**Service principal (CI):**

```bash
export AZURE_CLIENT_ID=...
export AZURE_CLIENT_SECRET=...
export AZURE_TENANT_ID=...
export AZURE_STORAGE_ACCOUNT_URL=https://myaccount.blob.core.windows.net
bsp deploy my-preset --container bsp-artifacts
```

### AWS

Credentials are resolved using the standard **boto3 credential chain**:

1. Environment variables: `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN`
2. Shared credentials file: `~/.aws/credentials` (set up with `aws configure`)
3. AWS config file: `~/.aws/config`
4. IAM role (EC2 instance profile, ECS task role, Lambda execution role)

**Minimal local setup:**

```bash
aws configure        # interactive prompts for key, secret, region
bsp deploy my-preset --provider aws --bucket my-s3-bucket
```

**Environment variables (CI):**

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=eu-west-1
bsp deploy my-preset --provider aws --bucket my-s3-bucket
```

---

## CLI Reference

### `bsp deploy`

Upload artifacts from a previous build to cloud storage.

```
bsp deploy <bsp_name> [OPTIONS]
bsp deploy --device <d> --release <r> [--feature <f>] [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--provider PROVIDER` | Override provider: `azure` or `aws` |
| `--container CONTAINER` / `--bucket CONTAINER` | Override Azure container or AWS bucket name |
| `--prefix PREFIX` | Override remote path prefix template |
| `--pattern PATTERN` | Override glob patterns (repeatable; replaces registry config) |
| `--archive-name NAME` | Bundle artifacts into a single archive with this name (supports `{device}`, `{release}`, `{distro}`, `{vendor}`, `{date}`, `{datetime}`) |
| `--archive-format FORMAT` | Archive format: `tar.gz` (default), `tar.bz2`, `tar.xz`, `zip` |
| `--deploy-cache` | Also upload Yocto DL_DIR / SSTATE_DIR caches |
| `--no-deploy-cache-downloads` | Skip uploading the DL_DIR downloads cache (use with `--deploy-cache`) |
| `--no-deploy-cache-sstate` | Skip uploading the SSTATE_DIR sstate cache (use with `--deploy-cache`) |
| `--update-index` | Regenerate and upload the browsable container-root `index.html` after a successful deploy |
| `--no-update-index` | Never generate an index, even when enabled in the registry |
| `--dry-run` | List what would be uploaded without uploading (no credentials needed) |

**Examples:**

```bash
# Deploy using registry settings
bsp deploy poky-qemuarm64-scarthgap

# Dry run – see what would be uploaded
bsp deploy poky-qemuarm64-scarthgap --dry-run

# Override container at runtime
bsp deploy poky-qemuarm64-scarthgap --container my-other-container

# Deploy to AWS with a custom prefix
bsp deploy poky-qemuarm64-scarthgap \
    --provider aws \
    --bucket my-s3-bucket \
    --prefix "builds/{device}/{release}/{date}"

# Upload only *.wic.gz files
bsp deploy poky-qemuarm64-scarthgap --pattern "**/*.wic.gz"

# Deploy by components (no preset required)
bsp deploy --device qemuarm64 --release scarthgap --container bsp-artifacts

# Deploy artifacts + Yocto caches
bsp deploy poky-qemuarm64-scarthgap --deploy-cache

# Deploy and publish a browsable, SAS-signed index.html
bsp deploy poky-qemuarm64-scarthgap --update-index
```

### `bsp build --deploy`

Deploy artifacts automatically after a successful build.  All `--deploy-*`
flags mirror the `bsp deploy` options.

```
bsp build <bsp_name> --deploy [--deploy-provider PROVIDER]
    [--deploy-container CONTAINER] [--deploy-prefix PREFIX]
```

| Option | Description |
|--------|-------------|
| `--deploy` | Deploy artifacts after a successful build |
| `--deploy-provider PROVIDER` | Override storage provider |
| `--deploy-container CONTAINER` | Override container or bucket name |
| `--deploy-prefix PREFIX` | Override path prefix template |
| `--deploy-archive-name NAME` | Bundle artifacts into a single archive with this name (supports `{device}`, `{release}`, `{distro}`, `{vendor}`, `{date}`, `{datetime}`) |
| `--deploy-archive-format FORMAT` | Archive format: `tar.gz` (default), `tar.bz2`, `tar.xz`, `zip` |
| `--deploy-cache` | Also upload Yocto DL_DIR / SSTATE_DIR caches after a successful build |
| `--no-deploy-cache-downloads` | Skip uploading the DL_DIR downloads cache |
| `--no-deploy-cache-sstate` | Skip uploading the SSTATE_DIR sstate cache |

**Examples:**

```bash
# Build and deploy in one step
bsp build poky-qemuarm64-scarthgap --deploy

# Build and deploy to a specific AWS bucket
bsp build poky-qemuarm64-scarthgap \
    --deploy \
    --deploy-provider aws \
    --deploy-container my-s3-bucket

# Build, deploy artifacts and caches in one step
bsp build poky-qemuarm64-scarthgap --deploy --deploy-cache
```

### `bsp deploy index`

Rebuild the browsable HTML index straight from the live container listing —
no build required.  This is the command to schedule when signed URLs expire.

A container has exactly **one** index page: `index.html` at its root, listing
every artifact of every prefix as a navigable tree.  No `index.html` is written
inside artifact folders.  Deploying with `--update-index` refreshes the same
page, so `bsp deploy index` and `bsp build --deploy --update-index` leave the
container in the same state.

```
bsp deploy index [container] [OPTIONS]
```

The provider, container/bucket, Azure account URL, AWS region/profile and the
`index:` options are taken from the root-level `deploy:` block of the registry
configuration (`bsp-registry.yaml`); any option given on the command line wins:

```yaml
deploy:
  provider: azure                                           # "azure" (default) or "aws"
  account_url: "https://modularbsp.blob.core.windows.net"   # Azure only; supports $ENV{} expansion
  container: bsp-registry-artifacts                         # Azure container name
```

With such a registry, `bsp deploy index` needs no further arguments.

| Option | Description |
|--------|-------------|
| `--prefix PREFIX` | Deprecated and ignored: the root `index.html` always covers the whole container |
| `--root` | Deprecated and ignored: the root `index.html` is always generated |
| `--provider PROVIDER` | Provider: `azure` or `aws` (default: `deploy.provider`, else `azure`) |
| `--account-url URL` | Azure storage account URL (default: `deploy.account_url`) |
| `--no-sign-urls` | Emit relative links instead of signed URLs (CDN / custom domain) |
| `--sas-expiry ISO8601` | Expiry for generated signed URLs (default `2038-01-19T03:14:06Z`) |
| `--tree` / `--flat` | Render the collapsible directory tree (default) or the legacy flat table |
| `--collapse-depth N` | Directory depth expanded by default in the tree view (default `1`) |
| `--exclude PATTERN` | Glob pattern of paths to omit from the index (repeatable) |
| `--no-search` | Omit the interactive search box |
| `--dry-run` | Show what would be generated without uploading (no credentials needed) |

```bash
bsp deploy index                              # container from bsp-registry.yaml
bsp deploy index bsp-artifacts
bsp deploy index bsp-artifacts --dry-run
bsp deploy index bsp-artifacts --collapse-depth 2
bsp deploy index bsp-artifacts --exclude 'cache/*' --exclude '*.sig'
bsp deploy index bsp-artifacts --flat --no-search
```

### `bsp gather`

Download previously deployed artifacts from cloud storage.

```
bsp gather <bsp_name> [OPTIONS]
bsp gather --device <d> --release <r> [--feature <f>] [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--provider PROVIDER` | Override provider: `azure` or `aws` |
| `--container CONTAINER` / `--bucket CONTAINER` | Override Azure container or AWS bucket name |
| `--prefix PREFIX` | Override remote path prefix template |
| `--dest-dir PATH` | Local directory to write artifacts into (default: `<build_path>/build/tmp/deploy/images` under the registry build path) |
| `--date DATE` | Date override for `{date}` placeholder (`YYYY-MM-DD`) |
| `--gather-cache` | Also restore Yocto caches from cloud storage if available |
| `--cache-downloads-dir PATH` | Local directory to restore the DL_DIR cache into |
| `--cache-sstate-dir PATH` | Local directory to restore the SSTATE_DIR cache into |
| `--dry-run` | List what would be downloaded without downloading (no credentials needed) |

**Examples:**

```bash
# Download latest artifacts for a preset
bsp gather poky-qemuarm64-scarthgap --dest-dir ./artifacts

# Download artifacts from a specific date
bsp gather poky-qemuarm64-scarthgap --dest-dir ./artifacts --date 2025-01-15

# Download artifacts + restore Yocto caches
bsp gather poky-qemuarm64-scarthgap \
    --dest-dir ./artifacts \
    --gather-cache

# Restore caches to explicit directories
bsp gather poky-qemuarm64-scarthgap \
    --gather-cache \
    --cache-downloads-dir /mnt/yocto/downloads \
    --cache-sstate-dir /mnt/yocto/sstate

# Dry run
bsp gather poky-qemuarm64-scarthgap --dry-run --gather-cache
```

---

## Dry-run mode

`--dry-run` lists all artifacts that would be uploaded and where they would go,
without performing any uploads and **without requiring cloud credentials or
installed cloud SDKs**.

```bash
bsp deploy poky-qemuarm64-scarthgap --dry-run
bsp deploy poky-qemuarm64-scarthgap --dry-run --deploy-cache
```

Example output:

```
[dry-run] Would upload 3 artifact(s):
  core-image-minimal-qemuarm64.rootfs.wic.gz → dry-run:qemu/qemuarm64/scarthgap/2025-03-15/core-image-minimal-qemuarm64.rootfs.wic.gz
  core-image-minimal-qemuarm64.rootfs.tar.bz2 → dry-run:qemu/qemuarm64/scarthgap/2025-03-15/core-image-minimal-qemuarm64.rootfs.tar.bz2
  manifest.json → dry-run:qemu/qemuarm64/scarthgap/2025-03-15/manifest.json

[dry-run] Would upload 2 Yocto cache archive(s):
  downloads: downloads.tar.gz → dry-run:qemu/qemuarm64/scarthgap/2025-03-15/cache/downloads.tar.gz
  sstate: sstate.tar.gz → dry-run:qemu/qemuarm64/scarthgap/2025-03-15/cache/sstate.tar.gz
```

---

## Build manifest

When `include_build_manifest: true` (default), the `build-manifest.json`
written by `bsp build` into the build path is uploaded as
`<prefix>/build-manifest.json`, so the deployed artifacts stay traceable to
the exact registry, device, release and feature set they were built from.
It is looked up at `<build_path>/build-manifest.json` and, failing that, at
`<build_path>/build/build-manifest.json`.  When the file does not exist a
warning is logged and the deploy continues.  Its remote URL is also recorded
under the `build_manifest` key of `manifest.json`.

Pass `--no-build-manifest` to `bsp deploy` (or to `bsp build --deploy`) to
skip the upload for a single run.

### Relative paths

The build manifest (`schema_version: "2"`) never contains absolute host paths.
Every path is emitted relative to one of the anchors described in its `roots`
section:

| Anchor | Meaning |
|--------|---------|
| `roots.registry` | The directory containing the registry YAML (always `.`) |
| `roots.build` | The build directory, relative to the registry root |

Paths that fall outside both anchors are replaced by placeholders:
`${HOME}/<relative>` when below the user's home directory, and
`<external>/<name>` otherwise.  Free-form values that may embed paths
(`inputs.local_conf` lines, `components.container.runtime_args`,
`inputs.environment_variables[].value`, build options and
`provenance.cli.command`) are scrubbed with the same rules, using the
`${registry}` and `${build}` tokens for anchor prefixes.  `provenance.cli.argv[0]`
is reduced to the bare program name (e.g. `bsp`).

## Artifact manifest

When `include_manifest: true` (default), a `manifest.json` file is uploaded
alongside the artifacts.  It contains:

```json
{
  "schema_version": "1",
  "generated_at": "2025-03-15T14:30:22+00:00",
  "provider": "azure",
  "build": {
    "device": "qemuarm64",
    "release": "scarthgap",
    "distro": "poky",
    "vendor": "qemu"
  },
  "artifacts": [
    {
      "name": "core-image-minimal-qemuarm64.rootfs.wic.gz",
      "remote_url": "https://myaccount.blob.core.windows.net/bsp-artifacts/qemu/qemuarm64/scarthgap/2025-03-15/core-image-minimal-qemuarm64.rootfs.wic.gz",
      "size_bytes": 35651584,
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    }
  ],
  "total_size_bytes": 35651584,
  "yocto_cache": {
    "downloads": {
      "name": "downloads.tar.gz",
      "remote_url": "https://myaccount.blob.core.windows.net/bsp-artifacts/qemu/qemuarm64/scarthgap/2025-03-15/cache/downloads.tar.gz",
      "size_bytes": 2147483648,
      "sha256": "..."
    },
    "sstate": {
      "name": "sstate.tar.gz",
      "remote_url": "https://myaccount.blob.core.windows.net/bsp-artifacts/qemu/qemuarm64/scarthgap/2025-03-15/cache/sstate.tar.gz",
      "size_bytes": 5368709120,
      "sha256": "..."
    }
  }
}
```

The `yocto_cache` section is only present when caches were uploaded.

---

## Partial failures

If an individual file upload fails, the tool **continues uploading the
remaining files** and reports a summary at the end:

```
Uploaded 2 artifact(s):
  core-image-minimal-qemuarm64.rootfs.tar.bz2 → https://...
  manifest.json → https://...

WARNING: 1 artifact(s) failed to upload:
  core-image-minimal-qemuarm64.rootfs.wic.gz: [Errno 32] Broken pipe
```

The process exits with code 0 when at least one file succeeded, or 1 when all
uploads fail.

---

## Python API

```python
from bsp import BspManager

manager = BspManager("bsp-registry.yaml")
manager.initialize()

# Dry-run deploy for a preset
result = manager.deploy_bsp("poky-qemuarm64-scarthgap", dry_run=True)
print(f"Would upload {result.success_count} artifact(s)")

# Deploy with runtime overrides
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
    print(f"  sha256: {artifact.sha256}")

# Gather artifacts
result = manager.gather_bsp(
    "poky-qemuarm64-scarthgap",
    dest_dir="./artifacts",
)
print(f"Downloaded {result.total_count} artifact(s)")

# Gather artifacts + restore Yocto caches
result = manager.gather_bsp(
    "poky-qemuarm64-scarthgap",
    dest_dir="./artifacts",
    gather_cache=True,
    cache_downloads_dest="/mnt/yocto/downloads",
    cache_sstate_dest="/mnt/yocto/sstate",
)
print(f"Restored {len(result.cache_artifacts)} cache(s)")

# Use the lower-level deployer + storage backend directly
from bsp.storage import create_backend
from bsp.deployer import ArtifactDeployer
from bsp.models import ArchiveConfig, DeployConfig, YoctoCacheConfig

config = DeployConfig(
    provider="azure",
    container="bsp-artifacts",
    prefix="{device}/{release}/{date}",
    patterns=["**/*.wic.gz"],
    artifact_dirs=["tmp/deploy/images"],
    archive=ArchiveConfig(
        name="firmware-{device}-{release}-{date}",
        format="tar.gz",
    ),
    yocto_cache=YoctoCacheConfig(
        enabled=True,
        downloads=True,
        sstate=True,
    ),
)
backend = create_backend("azure", container_name="bsp-artifacts")
deployer = ArtifactDeployer(config, backend)

result = deployer.deploy(
    build_path="build/poky-qemuarm64-scarthgap",
    device="qemuarm64",
    release="scarthgap",
    distro="poky",
    vendor="qemu",
    downloads_path="/mnt/yocto/downloads",
    sstate_path="/mnt/yocto/sstate",
)
print(deployer.generate_manifest(result, device="qemuarm64", release="scarthgap"))
```

---

## CI/CD integration

### GitHub Actions – Azure

```yaml
name: Build and Deploy BSP

on:
  push:
    branches: [main]

jobs:
  build-deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write   # required for OIDC / Workload Identity federation
      contents: read

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install bsp-registry-tools with Azure support
        run: pip install "bsp-registry-tools[azure]"

      - name: Azure Login (OIDC)
        uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

      - name: Build BSP
        run: bsp build poky-qemuarm64-scarthgap

      - name: Deploy artifacts (+ caches)
        env:
          AZURE_STORAGE_ACCOUNT_URL: ${{ secrets.AZURE_STORAGE_ACCOUNT_URL }}
        run: |
          bsp deploy poky-qemuarm64-scarthgap \
            --container bsp-artifacts \
            --prefix "ci/{device}/{release}/${{ github.sha }}" \
            --deploy-cache
```

### GitHub Actions – AWS

```yaml
name: Build and Deploy BSP (AWS)

on:
  push:
    branches: [main]

jobs:
  build-deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write   # required for OIDC
      contents: read

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install bsp-registry-tools with AWS support
        run: pip install "bsp-registry-tools[aws]"

      - name: Configure AWS Credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: eu-west-1

      - name: Build BSP
        run: bsp build poky-qemuarm64-scarthgap

      - name: Deploy artifacts (+ caches)
        run: |
          bsp deploy poky-qemuarm64-scarthgap \
            --provider aws \
            --bucket my-bsp-artifacts \
            --prefix "ci/{device}/{release}/${{ github.sha }}" \
            --deploy-cache
```


---

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Registry Configuration](#registry-configuration)
  - [Global `deploy:` block](#global-deploy-block)
  - [Per-preset override](#per-preset-override)
  - [Field reference](#field-reference)
  - [Prefix template placeholders](#prefix-template-placeholders)
  - [Archive bundling](#archive-bundling)
- [Authentication](#authentication)
  - [Azure](#azure)
  - [AWS](#aws)
- [CLI Reference](#cli-reference)
  - [`bsp deploy`](#bsp-deploy)
  - [`bsp build --deploy`](#bsp-build---deploy)
- [Dry-run mode](#dry-run-mode)
- [Artifact manifest](#artifact-manifest)
- [Partial failures](#partial-failures)
- [Python API](#python-api)
- [CI/CD integration](#cicd-integration)
  - [GitHub Actions – Azure](#github-actions--azure)
  - [GitHub Actions – AWS](#github-actions--aws)

---

## Overview

After a Yocto build, images and SDKs land under:

```
<build_path>/tmp/deploy/images/
<build_path>/tmp/deploy/sdk/
```

`bsp deploy` finds all files that match the configured glob patterns in those
directories and uploads them to your cloud storage provider.  An optional JSON
manifest (with artifact names, sizes, and SHA-256 checksums) is uploaded
alongside the artifacts.

Config can live either in the registry YAML (checked in, shared by the team) or
be overridden entirely from the command line.

---

## Quick Start

```bash
# 1. Install cloud SDK extras (one-time)
pip install "bsp-registry-tools[azure]"   # Azure
pip install "bsp-registry-tools[aws]"     # AWS
pip install "bsp-registry-tools[deploy]"  # both

# 2. Authenticate (one-time)
az login                          # Azure (interactive)
aws configure                     # AWS (interactive)

# 3. Build and deploy in one step
bsp build poky-qemuarm64-scarthgap --deploy --deploy-container bsp-artifacts

# — or — deploy separately after a successful build
bsp deploy poky-qemuarm64-scarthgap --container bsp-artifacts

# Preview what would be uploaded (no credentials required)
bsp deploy poky-qemuarm64-scarthgap --dry-run
```

---

## Installation

Cloud SDK dependencies are **optional** to avoid forcing them on users who do
not need deployment.

```bash
# Azure Blob Storage support
pip install "bsp-registry-tools[azure]"
# installs: azure-storage-blob>=12.0, azure-identity>=1.0

# AWS S3 support
pip install "bsp-registry-tools[aws]"
# installs: boto3>=1.20

# Both providers
pip install "bsp-registry-tools[deploy]"
```

`--dry-run` mode works **without any cloud SDK installed**.

---

## Registry Configuration

### Global `deploy:` block

Add a top-level `deploy:` block to your registry YAML.  It applies to every
build by default.

```yaml
specification:
  version: "2.0"

deploy:
  provider: azure
  account_url: $ENV{AZURE_STORAGE_ACCOUNT_URL}   # supports $ENV{} expansion
  container: bsp-artifacts
  prefix: "{vendor}/{device}/{release}/{date}"
  patterns:
    - "**/*.wic.gz"
    - "**/*.wic.bz2"
    - "**/*.tar.bz2"
    - "**/*.ext4"
    - "**/*.sdimg"
  artifact_dirs:
    - tmp/deploy/images
    - tmp/deploy/sdk
  include_manifest: true
  include_build_manifest: true
  # Optional: bundle all artifacts into a single archive before uploading
  archive:
    name: "firmware-{device}-{release}-{date}"
    format: tar.gz

registry:
  # ...
```

**AWS variant:**

```yaml
deploy:
  provider: aws
  bucket: my-s3-bucket
  region: eu-west-1
  prefix: "{device}/{release}/{date}"
  patterns:
    - "**/*.wic.gz"
  artifact_dirs:
    - tmp/deploy/images
```

### Per-preset override

An individual `BspPreset` entry can include its own `deploy:` block.  Only the
fields that differ from the `DeployConfig` defaults override the global config;
all other fields keep their global values.

**Merge order** (later entries win):
1. **Global `deploy:`** — baseline for every build
2. **Preset `deploy:`** — overrides only fields that differ from their defaults
3. **CLI flags** (`--provider`, `--container`, …) — highest priority

```yaml
deploy:                               # global: Azure, shared container
  provider: azure
  account_url: $ENV{AZURE_STORAGE_ACCOUNT_URL}
  container: bsp-artifacts
  prefix: "{vendor}/{device}/{release}/{date}"

registry:
  bsp:
    # Uses global settings unchanged.
    - name: qemuarm64-scarthgap
      device: qemuarm64
      release: scarthgap
      features: []

    # Overrides only container and prefix; provider and account_url come from global.
    - name: imx8mp-adv-scarthgap-release
      description: "Advantech i.MX8MP Scarthgap – release artefacts"
      device: imx8mp-adv
      release: scarthgap
      features: []
      deploy:
        container: imx8mp-release-artifacts           # ← override
        prefix: "release/{device}/{release}/{date}"   # ← override
        patterns:                                     # ← override
          - "**/*.wic.gz"

    # Switches to AWS entirely for this preset only.
    - name: aws-build-scarthgap
      device: qemuarm64
      release: scarthgap
      features: []
      deploy:
        provider: aws                 # ← override: switch provider
        container: my-s3-bucket       # ← override: bucket name
```

### Field reference

| Field              | Type          | Default | Description |
|--------------------|---------------|---------|-------------|
| `provider`         | string        | `"azure"` | Cloud provider: `"azure"` or `"aws"` |
| `container`        | string (opt.) | —       | Azure Blob container name |
| `bucket`           | string (opt.) | —       | AWS S3 bucket name |
| `account_url`      | string (opt.) | —       | Azure account URL; supports `$ENV{VAR}` expansion. Falls back to the `AZURE_STORAGE_ACCOUNT_URL` env var. |
| `prefix`           | string (opt.) | `"{vendor}/{device}/{release}/{date}"` | Remote path prefix template (see [placeholders](#prefix-template-placeholders)) |
| `patterns`         | list[str]     | `["**/*.wic*", "**/*.tar.gz", "**/*.ext4", "**/*.sdimg"]` | Glob patterns for artifact files |
| `artifact_dirs`    | list[str]     | `["tmp/deploy/images", "tmp/deploy/sdk"]` | Subdirectories under the build path to scan |
| `include_manifest` | bool          | `true`  | Upload a JSON manifest alongside artifacts |
| `include_build_manifest` | bool    | `true`  | Upload the `build-manifest.json` written by `bsp build` |
| `archive`          | object (opt.) | —       | Bundle all artifacts into a single archive before uploading. See [Archive bundling](#archive-bundling). |
| `region`           | string (opt.) | —       | AWS region (optional; boto3 default otherwise) |
| `profile`          | string (opt.) | —       | AWS credentials profile (optional) |

### Prefix template placeholders

The `prefix` field is a Python format string.  The following variables are
available at deploy time:

| Placeholder  | Example value    | Description |
|--------------|------------------|-------------|
| `{device}`   | `qemuarm64`      | Device slug |
| `{release}`  | `scarthgap`      | Release slug |
| `{distro}`   | `poky`           | Effective distro slug |
| `{vendor}`   | `qemu`           | Device vendor slug |
| `{date}`     | `2025-03-15`     | Build date (UTC, `YYYY-MM-DD`) |
| `{datetime}` | `20250315-143022` | Build date + time (UTC, `YYYYMMDD-HHMMSS`) |

**Example prefixes:**

```
{vendor}/{device}/{release}/{date}
→  qemu/qemuarm64/scarthgap/2025-03-15/

builds/{device}/{date}
→  builds/qemuarm64/2025-03-15/

release/{release}/{device}
→  release/scarthgap/qemuarm64/
```

---

## Archive bundling

By default every matching artifact file is uploaded individually.  Set the
`archive:` sub-object inside `deploy:` to collect all artifacts into a single
compressed archive **before** uploading.  Only the archive (plus the manifest
when `include_manifest: true`) is uploaded.

```yaml
deploy:
  provider: azure
  container: bsp-artifacts
  archive:
    name: "firmware-{device}-{release}-{date}"
    format: tar.gz
```

### `archive` fields

| Field    | Type   | Default                       | Description |
|----------|--------|-------------------------------|-------------|
| `name`   | string | `"artifacts-{device}-{date}"` | Archive filename template (without extension).  Supports the same placeholders as `prefix`: `{device}`, `{release}`, `{distro}`, `{vendor}`, `{date}`, `{datetime}`. |
| `format` | string | `"tar.gz"`                    | Compression format: `tar.gz`, `tar.bz2`, `tar.xz`, or `zip`. |

The appropriate file extension is appended automatically (e.g. `.tar.gz` for
`tar.gz`).

**CLI equivalents:**

```bash
# bsp deploy
bsp deploy my-preset \
    --archive-name "firmware-{device}-{release}-{date}" \
    --archive-format tar.gz

# bsp build --deploy
bsp build my-preset --deploy \
    --deploy-archive-name "firmware-{device}-{release}-{date}" \
    --deploy-archive-format tar.gz
```

---

## HTML index generation

Add an `index:` block to `deploy:` to publish a browsable `index.html` next to
the uploaded artifacts:

```yaml
deploy:
  provider: azure
  container: bsp-artifacts
  index:
    enabled: true
    title: "{vendor} {device} — {release}"
    sign_urls: true
    sas_expiry: "2038-01-19T03:14:06Z"
    tree: true
    collapse_depth: 1
    search: true
    show_dates: true
    facets: [preset, machine, release, date]
    theme: auto
    exclude:
      - "cache/*"
```

### `index` fields

| Field        | Type   | Default | Description |
|--------------|--------|---------|-------------|
| `enabled`    | bool   | `false` | Master switch.  Index generation is opt-in. |
| `title`      | string | `"{vendor} {device} — {release}"` | Page title template.  Supports the same placeholders as `prefix`. |
| `sign_urls`  | bool   | `true`  | Link artifacts through read-only signed URLs (Azure SAS / S3 presigned).  Set to `false` when a CDN, Front Door or custom domain fronts the container — relative links are emitted instead. |
| `sas_expiry` | string | `"2038-01-19T03:14:06Z"` | Expiry timestamp (ISO-8601) for generated signed URLs.  The default is the 32-bit `time_t` limit. |
| `root_index` | bool   | `true`  | Deprecated and ignored.  A single `index.html` is always written at the container root; no `index.html` is generated inside artifact folders. |
| `tree`       | bool   | `true`  | Render a collapsible tree that preserves the remote directory structure below the indexed prefix.  Set to `false` for the legacy flat table. |
| `collapse_depth` | int | `1`    | Directory depth expanded by default in the tree view (`1` expands only the top level). |
| `search`     | bool   | `true`  | Show the search / filter box.  Plain substrings and simple `*` / `?` globs are matched against the full relative path. |
| `exclude`    | list   | `[]`    | Glob patterns (matched against the path relative to the indexed prefix, or against the bare file name) omitted from the index. |
| `show_dates` | bool   | `true`  | Show last-modified timestamps when the storage backend provides them. |
| `facets`     | list   | `[preset, machine, release, date]` | Facet groups shown in the filter bar.  Supported names: `preset`, `machine`, `release`, `distro`, `vendor`, `date`.  An empty list disables faceted filtering. |
| `theme`      | string | `"auto"` | Colour scheme: `auto` (follows `prefers-color-scheme`), `light` or `dark`. |
| `accent`     | string | `""`    | CSS colour used as the page accent (e.g. `"#0366d6"`).  Empty keeps the built-in accent. |

The page is self-contained (no external assets, no CDN JavaScript, no server),
so it loads from a private container through a single signed URL.  It ships a
design-token stylesheet with automatic dark mode, a sticky header holding the
title, a clickable prefix breadcrumb and the filter bar, per-type artifact
icons, click-to-copy SHA-256 values, keyboard-navigable tree rows and a live
"N files · M total" summary.  It lists
every artifact with its human-readable size, last-modified timestamp and short
SHA-256, links to `manifest.json`, and carries no-cache `<meta>` tags so
browsers never show stale, expired links.

Above the tree a faceted filter bar offers multi-select chips for the BSP
preset, machine, Yocto release and upload date (with `Today` / `Last 7 days` /
`Last 30 days` / `Older` buckets and a `From`–`To` date range).  Values are
ANDed across groups and ORed within a group, chip counts update live, and every
active facet is encoded in the URL fragment so a filtered view can be
bookmarked or shared.  Facet values are recorded at deploy time in an
`index-meta.json` sidecar next to `manifest.json`, so `bsp deploy index`
rebuilds and the container-root index keep them; when the sidecar is missing
they are recovered by inverting the configured `prefix` template.  The
container-root index lists one row per build prefix with its facets, newest
first, and is filtered by the same bar.

In the default tree view the remote directory structure of the container is
preserved, so nested artifacts (`images/…`, `sdk/…`, cache archives)
keep their folders and identically named files in different directories stay
distinct.  The inlined vanilla-JavaScript renderer provides:

- **fold / unfold** of directories, with per-directory file counts and
  aggregated sizes, plus *Expand all* / *Collapse all* buttons;
- **search** by substring or simple glob against the full relative path,
  auto-expanding the ancestors of every match;
- **sorting** by name, size or last-modified within each directory level;
- **shareable state** — the active query, type filter and expanded folders are
  mirrored into the URL hash.

A `<noscript>` fallback renders the same artifacts as the plain flat table, and
`--flat` (or `tree: false`) selects that table unconditionally.  Only
`index.html` pages are skipped, so genuine HTML build artifacts such as reports
remain listed.  Every interpolated value is HTML-escaped and the embedded JSON
data island is escaped so a hostile blob name cannot break out of its
`<script>` element.

The index is **fully regenerated** on every run from the current artifact set
(or, for `bsp deploy index`, from the live container listing) — it is never appended
to, so links are always fresh.

---

## Public access without anonymous blob access

Storage accounts with `allowBlobPublicAccess=false` (and no `$web` static
website endpoint) cannot serve blobs anonymously.  The generated index solves
this without weakening that posture: each artifact link is a **read-only signed
URL**, and `index.html` itself is fetched through a signed URL.

On Azure the backend picks the strongest available option:

1. **Account-key SAS** — used when `AZURE_STORAGE_CONNECTION_STRING` (or an
   explicit connection string) is available.  Supports arbitrary expiry, so the
   2038 sentinel works as-is.
2. **User-delegation SAS** — used when authenticated via
   `DefaultAzureCredential` (`az login`, managed identity, service principal).
   Azure caps delegation keys at **7 days**, so longer expiries are clamped
   automatically with a warning.

On AWS `get_signed_url()` returns an S3 presigned URL (capped at 7 days).

Trade-offs to be aware of:

- Anyone holding a link can download that blob until the SAS expires — treat
  the links as bearer tokens.
- User-delegation links expire after at most 7 days; schedule
  `bsp deploy index <container>` (for example from a nightly job) to re-sign
  them.
- Signed links are not written to logs, and the account key / connection string
  is never logged or embedded in the page.
- Uploads set `Content-Type: application/octet-stream` (with **no**
  `Content-Encoding`) for artifacts so browsers do not transparently decompress
  `*.wic.gz` images and corrupt them; `index.html` is stored as `text/html` so
  it renders instead of downloading.

---

## Authentication

### Azure

Credentials are resolved in the following order:

1. **`AZURE_STORAGE_CONNECTION_STRING`** environment variable — if set, the
   connection string is used directly (no `account_url` needed).
2. **`deploy.account_url`** (or `AZURE_STORAGE_ACCOUNT_URL` env var) +
   `DefaultAzureCredential` — supports any of the methods below transparently:

| Method | Required setup |
|--------|---------------|
| Azure CLI | `az login` |
| Service principal | `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID` env vars |
| Managed Identity | Automatic on Azure VMs / AKS / App Service |
| Workload Identity | Automatic in AKS with OIDC |

**Minimal local setup:**

```bash
export AZURE_STORAGE_ACCOUNT_URL=https://myaccount.blob.core.windows.net
az login
bsp deploy my-preset --container bsp-artifacts
```

**Service principal (CI):**

```bash
export AZURE_CLIENT_ID=...
export AZURE_CLIENT_SECRET=...
export AZURE_TENANT_ID=...
export AZURE_STORAGE_ACCOUNT_URL=https://myaccount.blob.core.windows.net
bsp deploy my-preset --container bsp-artifacts
```

### AWS

Credentials are resolved using the standard **boto3 credential chain**:

1. Environment variables: `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN`
2. Shared credentials file: `~/.aws/credentials` (set up with `aws configure`)
3. AWS config file: `~/.aws/config`
4. IAM role (EC2 instance profile, ECS task role, Lambda execution role)

**Minimal local setup:**

```bash
aws configure        # interactive prompts for key, secret, region
bsp deploy my-preset --provider aws --bucket my-s3-bucket
```

**Environment variables (CI):**

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=eu-west-1
bsp deploy my-preset --provider aws --bucket my-s3-bucket
```

---

## CLI Reference

### `bsp deploy`

Upload artifacts from a previous build to cloud storage.

```
bsp deploy <bsp_name> [OPTIONS]
bsp deploy --device <d> --release <r> [--feature <f>] [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--provider PROVIDER` | Override provider: `azure` or `aws` |
| `--container CONTAINER` / `--bucket CONTAINER` | Override Azure container or AWS bucket name |
| `--prefix PREFIX` | Override remote path prefix template |
| `--pattern PATTERN` | Override glob patterns (repeatable; replaces registry config) |
| `--archive-name NAME` | Bundle artifacts into a single archive with this name (supports `{device}`, `{release}`, `{distro}`, `{vendor}`, `{date}`, `{datetime}`) |
| `--archive-format FORMAT` | Archive format: `tar.gz` (default), `tar.bz2`, `tar.xz`, `zip` |
| `--update-index` | Regenerate and upload the browsable container-root `index.html` after a successful deploy |
| `--no-update-index` | Never generate an index, even when enabled in the registry |
| `--dry-run` | List what would be uploaded without uploading (no credentials needed) |

**Examples:**

```bash
# Deploy using registry settings
bsp deploy poky-qemuarm64-scarthgap

# Dry run – see what would be uploaded
bsp deploy poky-qemuarm64-scarthgap --dry-run

# Override container at runtime
bsp deploy poky-qemuarm64-scarthgap --container my-other-container

# Deploy to AWS with a custom prefix
bsp deploy poky-qemuarm64-scarthgap \
    --provider aws \
    --bucket my-s3-bucket \
    --prefix "builds/{device}/{release}/{date}"

# Upload only *.wic.gz files
bsp deploy poky-qemuarm64-scarthgap --pattern "**/*.wic.gz"

# Deploy by components (no preset required)
bsp deploy --device qemuarm64 --release scarthgap --container bsp-artifacts
```

### `bsp build --deploy`

Deploy artifacts automatically after a successful build.  All `--deploy-*`
flags mirror the `bsp deploy` options.

```
bsp build <bsp_name> --deploy [--deploy-provider PROVIDER]
    [--deploy-container CONTAINER] [--deploy-prefix PREFIX]
```

| Option | Description |
|--------|-------------|
| `--deploy` | Deploy artifacts after a successful build |
| `--deploy-provider PROVIDER` | Override storage provider |
| `--deploy-container CONTAINER` | Override container or bucket name |
| `--deploy-prefix PREFIX` | Override path prefix template |
| `--deploy-archive-name NAME` | Bundle artifacts into a single archive with this name (supports `{device}`, `{release}`, `{distro}`, `{vendor}`, `{date}`, `{datetime}`) |
| `--deploy-archive-format FORMAT` | Archive format: `tar.gz` (default), `tar.bz2`, `tar.xz`, `zip` |

**Examples:**

```bash
# Build and deploy in one step
bsp build poky-qemuarm64-scarthgap --deploy

# Build and deploy to a specific AWS bucket
bsp build poky-qemuarm64-scarthgap \
    --deploy \
    --deploy-provider aws \
    --deploy-container my-s3-bucket
```

---

## Dry-run mode

`--dry-run` lists all artifacts that would be uploaded and where they would go,
without performing any uploads and **without requiring cloud credentials or
installed cloud SDKs**.

```bash
bsp deploy poky-qemuarm64-scarthgap --dry-run
```

Example output:

```
[dry-run] Would upload 3 artifact(s):
  core-image-minimal-qemuarm64.rootfs.wic.gz → dry-run:qemu/qemuarm64/scarthgap/2025-03-15/core-image-minimal-qemuarm64.rootfs.wic.gz
  core-image-minimal-qemuarm64.rootfs.tar.bz2 → dry-run:qemu/qemuarm64/scarthgap/2025-03-15/core-image-minimal-qemuarm64.rootfs.tar.bz2
  manifest.json → dry-run:qemu/qemuarm64/scarthgap/2025-03-15/manifest.json
```

---

## Build manifest

When `include_build_manifest: true` (default), the `build-manifest.json`
written by `bsp build` into the build path is uploaded as
`<prefix>/build-manifest.json`, so the deployed artifacts stay traceable to
the exact registry, device, release and feature set they were built from.
It is looked up at `<build_path>/build-manifest.json` and, failing that, at
`<build_path>/build/build-manifest.json`.  When the file does not exist a
warning is logged and the deploy continues.  Its remote URL is also recorded
under the `build_manifest` key of `manifest.json`.

Pass `--no-build-manifest` to `bsp deploy` (or to `bsp build --deploy`) to
skip the upload for a single run.

### Relative paths

The build manifest (`schema_version: "2"`) never contains absolute host paths.
Every path is emitted relative to one of the anchors described in its `roots`
section:

| Anchor | Meaning |
|--------|---------|
| `roots.registry` | The directory containing the registry YAML (always `.`) |
| `roots.build` | The build directory, relative to the registry root |

Paths that fall outside both anchors are replaced by placeholders:
`${HOME}/<relative>` when below the user's home directory, and
`<external>/<name>` otherwise.  Free-form values that may embed paths
(`inputs.local_conf` lines, `components.container.runtime_args`,
`inputs.environment_variables[].value`, build options and
`provenance.cli.command`) are scrubbed with the same rules, using the
`${registry}` and `${build}` tokens for anchor prefixes.  `provenance.cli.argv[0]`
is reduced to the bare program name (e.g. `bsp`).

## Artifact manifest

When `include_manifest: true` (default), a `manifest.json` file is uploaded
alongside the artifacts.  It contains:

```json
{
  "schema_version": "1",
  "generated_at": "2025-03-15T14:30:22+00:00",
  "provider": "azure",
  "build": {
    "device": "qemuarm64",
    "release": "scarthgap",
    "distro": "poky",
    "vendor": "qemu"
  },
  "artifacts": [
    {
      "name": "core-image-minimal-qemuarm64.rootfs.wic.gz",
      "remote_url": "https://myaccount.blob.core.windows.net/bsp-artifacts/qemu/qemuarm64/scarthgap/2025-03-15/core-image-minimal-qemuarm64.rootfs.wic.gz",
      "size_bytes": 35651584,
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    }
  ],
  "total_size_bytes": 35651584
}
```

---

## Partial failures

If an individual file upload fails, the tool **continues uploading the
remaining files** and reports a summary at the end:

```
Uploaded 2 artifact(s):
  core-image-minimal-qemuarm64.rootfs.tar.bz2 → https://...
  manifest.json → https://...

WARNING: 1 artifact(s) failed to upload:
  core-image-minimal-qemuarm64.rootfs.wic.gz: [Errno 32] Broken pipe
```

The process exits with code 0 when at least one file succeeded, or 1 when all
uploads fail.

---

## Python API

```python
from bsp import BspManager

manager = BspManager("bsp-registry.yaml")
manager.initialize()

# Dry-run deploy for a preset
result = manager.deploy_bsp("poky-qemuarm64-scarthgap", dry_run=True)
print(f"Would upload {result.success_count} artifact(s)")

# Deploy with runtime overrides
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
    print(f"  sha256: {artifact.sha256}")

# Deploy by components
result = manager.deploy_by_components(
    device_slug="qemuarm64",
    release_slug="scarthgap",
    deploy_overrides={"container": "bsp-artifacts"},
)

# Use the lower-level deployer + storage backend directly
from bsp.storage import create_backend
from bsp.deployer import ArtifactDeployer
from bsp.models import ArchiveConfig, DeployConfig

config = DeployConfig(
    provider="azure",
    container="bsp-artifacts",
    prefix="{device}/{release}/{date}",
    patterns=["**/*.wic.gz"],
    artifact_dirs=["tmp/deploy/images"],
    archive=ArchiveConfig(
        name="firmware-{device}-{release}-{date}",
        format="tar.gz",
    ),
)
backend = create_backend("azure", container_name="bsp-artifacts")
deployer = ArtifactDeployer(config, backend)

result = deployer.deploy(
    build_path="build/poky-qemuarm64-scarthgap",
    device="qemuarm64",
    release="scarthgap",
    distro="poky",
    vendor="qemu",
)
print(deployer.generate_manifest(result, device="qemuarm64", release="scarthgap"))
```

---

## CI/CD integration

### GitHub Actions – Azure

```yaml
name: Build and Deploy BSP

on:
  push:
    branches: [main]

jobs:
  build-deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write   # required for OIDC / Workload Identity federation
      contents: read

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install bsp-registry-tools with Azure support
        run: pip install "bsp-registry-tools[azure]"

      - name: Azure Login (OIDC)
        uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

      - name: Build BSP
        run: bsp build poky-qemuarm64-scarthgap

      - name: Deploy artifacts
        env:
          AZURE_STORAGE_ACCOUNT_URL: ${{ secrets.AZURE_STORAGE_ACCOUNT_URL }}
        run: |
          bsp deploy poky-qemuarm64-scarthgap \
            --container bsp-artifacts \
            --prefix "ci/{device}/{release}/${{ github.sha }}"
```

### GitHub Actions – AWS

```yaml
name: Build and Deploy BSP (AWS)

on:
  push:
    branches: [main]

jobs:
  build-deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write   # required for OIDC
      contents: read

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install bsp-registry-tools with AWS support
        run: pip install "bsp-registry-tools[aws]"

      - name: Configure AWS Credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: eu-west-1

      - name: Build BSP
        run: bsp build poky-qemuarm64-scarthgap

      - name: Deploy artifacts
        run: |
          bsp deploy poky-qemuarm64-scarthgap \
            --provider aws \
            --bucket my-bsp-artifacts \
            --prefix "ci/{device}/{release}/${{ github.sha }}"
```
