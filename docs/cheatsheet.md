# BSP Registry Tools — Cheat Sheet

> Quick reference for the `bsp` CLI.  For full docs see the [README](../README.md).

---

## Installation

```bash
pip install bsp-registry-tools               # core
pip install "bsp-registry-tools[server]"     # + HTTP server
pip install "bsp-registry-tools[completions]" # + tab completions
pip install "bsp-registry-tools[azure]"      # + Azure Blob Storage
pip install "bsp-registry-tools[aws]"        # + AWS S3
pip install "bsp-registry-tools[deploy]"     # + both cloud providers
```

---

## Shell Completions

```bash
# Install extra first
pip install "bsp-registry-tools[completions]"

eval "$(bsp completions bash)"   # Bash  → add to ~/.bashrc
eval "$(bsp completions zsh)"    # Zsh   → add to ~/.zshrc
bsp completions fish | source    # Fish  → add to ~/.config/fish/config.fish
eval `bsp completions tcsh`      # tcsh  → add to ~/.tcshrc
```

---

## Global Options

All commands accept these flags **before** the sub-command:

| Flag | Description |
|------|-------------|
| `-v`, `--verbose` | Enable debug output |
| `-r REGISTRY`, `--registry REGISTRY` | Use a local registry file (skips remote fetch) |
| `--no-color` | Disable coloured output |
| `--remote URL[@BRANCH][@name=NAME]` | Ad-hoc remote registry (repeatable for multi-registry) |
| `--branch BRANCH` | Branch for a single `--remote` (default: `main`) |
| `--update` / `--no-update` | Update cached registry clone before use (default: update) |
| `--local` | Force local lookup; never contact remote |
| `--version` | Show version |

### Registry Resolution Order

1. `--registry <path>` — explicit local file  
2. `--local` — `./bsp-registry.yaml` or `./bsp-registry.yml`  
3. Auto-detect `bsp-registry.yaml` / `bsp-registry.yml` in CWD  
4. `--remote URL` flag(s) on the command line  
5. Named remotes in `~/.config/bsp/remotes.yaml`  
6. Default remote `advantech-europe` (bootstrapped automatically)

---

## `bsp list` — Discover registry contents

```bash
bsp list                          # list all BSP presets
bsp list devices                  # list device slugs
bsp list releases                 # list release slugs
bsp list features                 # list feature slugs
bsp list distros                  # list distro slugs

bsp list releases --device imx8qm # filter releases by device
bsp list --remote myorg           # scope to a single named remote
```

---

## `bsp tree` — Visual registry overview

```bash
bsp tree                   # coloured ASCII tree (default)
bsp tree --full            # expand all details (includes, overrides)
bsp tree --compact         # names/slugs only
bsp tree --remote myorg    # scope to a single named remote
bsp --no-color tree        # plain text (suitable for logs/scripts)
```

---

## `bsp build` — Build a BSP image

```bash
# By preset name
bsp build <bsp_name>

# By components
bsp build --device <device> --release <release>

# Common options
bsp build <bsp_name> --feature <feat>          # enable a feature (repeatable)
bsp build <bsp_name> --vendor-release <slug>   # select vendor sub-release
bsp build <bsp_name> --override <slug>         # select vendor override slug
bsp build <bsp_name> --checkout                # validate + checkout only, no build
bsp build <bsp_name> --target <image>          # override Bitbake target
bsp build <bsp_name> --task <task>             # override Bitbake task (e.g. compile)
bsp build <bsp_name> --path /mnt/build         # override build output directory
bsp build <bsp_name> --clean                   # clean before building
```

### Build → Deploy (cloud)

```bash
bsp build <bsp_name> --deploy                                   # Azure (default)
bsp build <bsp_name> --deploy --deploy-provider aws \
    --deploy-container my-s3-bucket
bsp build <bsp_name> --deploy --deploy-prefix "{device}/{release}/{date}"
bsp build <bsp_name> --deploy --deploy-archive-name "image-{device}-{date}.tar.gz"
bsp build <bsp_name> --deploy --deploy-cache                    # also upload caches
bsp build <bsp_name> --deploy --update-index                    # also publish index.html
```

### Build → Test (LAVA HIL)

```bash
bsp build <bsp_name> --test                    # submit LAVA job after build
bsp build <bsp_name> --test --wait             # submit and wait for result
bsp build <bsp_name> --test --lava-server https://lava.example.com \
    --lava-token $LAVA_TOKEN \
    --artifact-url http://files.example.com/builds
```

### Build → Scan (CRA/CVE)

```bash
bsp build <bsp_name> --scan                    # scan after build (Trivy default)
bsp build <bsp_name> --scan --scan-fail-on CRITICAL
bsp build <bsp_name> --scan --scan-tool syft+grype --scan-severity HIGH
bsp build <bsp_name> --scan --scan-output-dir /reports
```

### Build → Flash (SD card)

```bash
bsp build <bsp_name> --flash /dev/sdb
```

### Docker options

```bash
bsp build <bsp_name> --docker-no-cache                          # disable layer cache
bsp build <bsp_name> --docker-build-options "--network host"    # extra docker flags
```

---

## `bsp fetch` — Fetch sources only

```bash
bsp fetch <bsp_name>
bsp fetch --device <device> --release <release>

bsp fetch <bsp_name> --feature <feat>          # enable a feature (repeatable)
bsp fetch <bsp_name> --vendor-release <slug>   # vendor sub-release
bsp fetch <bsp_name> --override <slug>         # vendor override slug
bsp fetch <bsp_name> --target <image>          # Bitbake target to fetch
bsp fetch <bsp_name> --path /mnt/build         # override build directory
```

---

## `bsp shell` — Interactive build-environment shell

```bash
bsp shell <bsp_name>                           # open interactive shell
bsp shell <bsp_name> --command "bitbake core-image-minimal"  # run single command
bsp shell --device <device> --release <release>
```

---

## `bsp export` — Export KAS configuration

```bash
bsp export <bsp_name>                          # print merged KAS YAML to stdout
bsp export <bsp_name> --output config.yaml     # save to file
bsp export --device <device> --release <release> [--feature <feat>]
```

---

## `bsp containers` — Manage Docker container images

```bash
bsp containers                                 # list container definitions (default)
bsp containers list

bsp containers build                           # build all containers with a Dockerfile
bsp containers build <name>                    # build a single container
bsp containers build <name> --docker-no-cache  # bypass Docker layer cache
bsp containers build upstream:<name>           # multi-registry: target specific registry
```

---

## `bsp deploy` — Upload artifacts to cloud storage

```bash
bsp deploy <bsp_name>
bsp deploy --device <device> --release <release>

bsp deploy <bsp_name> --provider azure --container my-container
bsp deploy <bsp_name> --provider aws --bucket my-s3-bucket
bsp deploy <bsp_name> --prefix "{device}/{release}/{date}"
bsp deploy <bsp_name> --pattern "*.wic*" --pattern "*.tar.gz"
bsp deploy <bsp_name> --archive-name "image-{device}-{datetime}.tar.gz"
bsp deploy <bsp_name> --deploy-cache                   # also upload Yocto caches
bsp deploy <bsp_name> --no-deploy-cache-downloads      # skip DL_DIR upload
bsp deploy <bsp_name> --no-deploy-cache-sstate         # skip SSTATE_DIR upload
bsp deploy <bsp_name> --update-index                   # also publish a browsable index.html
bsp deploy <bsp_name> --no-update-index                # never publish an index.html
bsp deploy <bsp_name> --no-build-manifest              # skip uploading build-manifest.json
bsp deploy <bsp_name> --dry-run                        # preview without uploading

# Rebuild the SAS-signed HTML index without a build (e.g. from a cron job)
bsp deploy index                                    # container from registry deploy: block
bsp deploy index <container>
bsp deploy index <container> --collapse-depth 2     # tree view, 2 levels open
bsp deploy index <container> --exclude 'cache/*'    # omit paths from the index
bsp deploy index <container> --flat                 # legacy flat table
```

---

## `bsp gather` — Download artifacts from cloud storage

```bash
bsp gather <bsp_name>
bsp gather --device <device> --release <release>

bsp gather <bsp_name> --dest-dir /mnt/artifacts
bsp gather <bsp_name> --date 2025-03-15
bsp gather <bsp_name> --provider aws --bucket my-s3-bucket
bsp gather <bsp_name> --gather-cache \
    --cache-downloads-dir /mnt/yocto/downloads \
    --cache-sstate-dir /mnt/yocto/sstate
bsp gather <bsp_name> --dry-run                        # preview without downloading
```

---

## `bsp scan` — CVE scanning & SBOM generation

```bash
bsp scan <bsp_name>
bsp scan --device <device> --release <release>

bsp scan <bsp_name> --tool trivy               # default scanner
bsp scan <bsp_name> --tool syft+grype
bsp scan <bsp_name> --severity HIGH            # min severity to report (default: HIGH)
bsp scan <bsp_name> --fail-on CRITICAL         # exit non-zero threshold (default: CRITICAL)
bsp scan <bsp_name> --sbom-format cyclonedx    # or spdx-json / spdx-tag-value
bsp scan <bsp_name> --output-dir /reports
bsp scan <bsp_name> --image-path path/to/image.wic   # explicit artifact (repeatable)
bsp scan <bsp_name> --dry-run                  # list what would be scanned
```

---

## `bsp flash` — Flash image to SD card / block device

```bash
bsp flash <bsp_name> --target /dev/sdb
bsp flash --device <device> --release <release> --target /dev/sdb

bsp flash <bsp_name> --target /dev/sdb --tool bmaptool  # default
bsp flash <bsp_name> --target /dev/sdb --tool dd
bsp flash <bsp_name> --tool uuu  # NXP USB flashing (defaults to "-b emmc_all")

bsp flash <bsp_name> --target /dev/sdb \
    --image-path build/tmp/deploy/images/core-image-minimal.wic.bz2
bsp flash <bsp_name> --target /dev/sdb --image-pattern "*.wic.bz2"
bsp flash <bsp_name> --build-path /mnt/build   # override artifact search dir
bsp flash <bsp_name> --dry-run                 # preview without writing
```

---

## `bsp test` — Submit LAVA HIL test job

```bash
bsp test <bsp_name>
bsp test --device <device> --release <release>

bsp test <bsp_name> --wait                     # block until job completes
bsp test <bsp_name> --wait \
    --lava-server https://lava.example.com \
    --lava-token $LAVA_TOKEN \
    --artifact-url http://files.example.com/builds

# Direct execution on a DUT from a local LAVA job YAML
bsp test <bsp_name> --backend direct-ssh \
    --test-job-path jobs/rsb3720-modbsp.yaml \
    --ssh-host 192.168.3.195 --ssh-user root

# Run only selected suites from the job YAML (actions[].test.definitions[].name)
bsp test <bsp_name> --backend direct-ssh \
    --test-job-path jobs/rsb3720-modbsp.yaml \
    --ssh-host 192.168.3.195 --ssh-user root \
    --test-suite adv-context

# Enrich the generated report with requirement descriptions/specifications
bsp test <bsp_name> --backend direct-ssh \
    --test-job-path jobs/rsb3720-modbsp.yaml \
    --test-requirements requirements.yaml \
    --ssh-host 192.168.3.195 --ssh-user root

# Reuse the requirement descriptions published by another repository
bsp test <bsp_name> --backend direct-ssh \
    --test-job-path jobs/rsb3720-modbsp.yaml \
    --test-requirements https://github.com/miketsukerman/modular-bsp-test-definitions/blob/main/requirements.yaml \
    --ssh-host 192.168.3.195 --ssh-user root

# Also print every test case with its description in the console summary
bsp test <bsp_name> --backend direct-ssh \
    --test-job-path jobs/rsb3720-modbsp.yaml \
    --test-requirements requirements.yaml \
    --show-cases \
    --ssh-host 192.168.3.195 --ssh-user root
```

---

## `bsp remotes` — Manage named remote registries

Stored in `~/.config/bsp/remotes.yaml` (override with `BSP_REMOTES_CONFIG=…`).

```bash
bsp remotes                                      # list remote names
bsp remotes -v                                   # list with URLs and branches

bsp remotes add <name> <url>                     # add remote (branch: main)
bsp remotes add <name> <url> --branch develop    # add on a specific branch

bsp remotes remove <name>                        # remove a remote
bsp remotes rm <name>                            # alias for remove

bsp remotes rename <old> <new>                   # rename a remote

bsp remotes set-url <name> <url>                 # change URL
bsp remotes set-url <name> <url> --branch main   # change URL + branch

bsp remotes show <name>                          # show details
```

---

## `bsp server` — HTTP server (REST + GraphQL)

Requires: `pip install "bsp-registry-tools[server]"`

```bash
bsp server                                  # http://127.0.0.1:8080
bsp server --host 0.0.0.0 --port 9000
bsp --registry /path/to/registry.yaml server --host 0.0.0.0
bsp server --reload                         # auto-reload (development)
```

| URL | Description |
|-----|-------------|
| `http://localhost:8080/docs` | Swagger / OpenAPI UI |
| `http://localhost:8080/redoc` | ReDoc UI |
| `http://localhost:8080/graphql` | GraphiQL interactive editor |
| `http://localhost:8080/api/v1/…` | REST API endpoints |

---

## Common Patterns

```bash
# Use a local registry file
bsp --registry ./my-registry.yaml list

# Use an ad-hoc remote registry on a non-default branch
bsp --remote https://github.com/my-org/registry.git@develop list

# Multi-registry mode (both remotes queried simultaneously)
bsp --remote https://github.com/org-a/registry.git \
    --remote https://github.com/org-b/registry.git \
    list

# Full build pipeline: build → deploy → test
bsp build <bsp_name> --deploy --test --wait

# Build, scan, and flash in one command
bsp build <bsp_name> --scan --flash /dev/sdb

# Skip registry update (useful offline or in CI after initial fetch)
bsp --no-update build <bsp_name>

# Fully offline build with local registry
bsp --local build <bsp_name>
```

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `BSP_REMOTES_CONFIG` | Override path to `remotes.yaml` (default: `~/.config/bsp/remotes.yaml`) |
| `DL_DIR` | Yocto downloads cache directory (used by `--deploy-cache` / `--gather-cache`) |
| `SSTATE_DIR` | Yocto sstate cache directory (used by `--deploy-cache` / `--gather-cache`) |

---

## Build Outputs

| Artifact | Location |
|----------|---------|
| Build log | `<build_dir>/bsp-build-YYYYMMDD-HHMMSS-ffffff.log` |
| KAS invocation log | `<build_dir>/bsp-invocation-YYYYMMDD-HHMMSS-ffffff.log` |
| Build manifest | `<build_dir>/build-manifest.json` (paths are relative to the `roots` anchors; also uploaded by `bsp deploy` unless `--no-build-manifest`) |
| CVE / SBOM reports | `<build_dir>/reports/` (default) |
