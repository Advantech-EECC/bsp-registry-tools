"""
CLI entry point for the BSP registry manager.
"""

import argparse
import logging
import sys
from pathlib import Path

from .bsp_manager import BspManager
from .completions import (
    ContainerCompleter,
    DevicesCompleter,
    FeaturesCompleter,
    OverrideCompleter,
    PresetsCompleter,
    ReleasesCompleter,
    RemotesCompleter,
    TestSuitesCompleter,
    VendorReleaseCompleter,
)
from .exceptions import COLORAMA_AVAILABLE, ColoramaFormatter
from .models import ArchiveConfig, IndexConfig, YoctoCacheConfig
from .registry_fetcher import DEFAULT_BRANCH, DEFAULT_REMOTE_URL, RegistryFetcher
from .remotes_manager import RemotesManager
from .utils import SUPPORTED_REGISTRY_VERSION, get_installed_package_version

# =============================================================================
# Helpers
# =============================================================================


def _collect_deploy_overrides(args) -> dict:
    """
    Extract deploy-related CLI arguments into a flat override dict.

    Keys with ``None`` values are omitted so they do not clobber registry
    config defaults in the merge step inside ``BspManager``.
    """
    overrides = {}
    provider = getattr(args, "deploy_provider", None)
    if provider is not None:
        overrides["provider"] = provider
    container = getattr(args, "deploy_container", None)
    if container is not None:
        overrides["container"] = container
    prefix = getattr(args, "deploy_prefix", None)
    if prefix is not None:
        overrides["prefix"] = prefix
    patterns = getattr(args, "deploy_patterns", None)
    if patterns:
        overrides["patterns"] = patterns
    archive_name = getattr(args, "deploy_archive_name", None)
    archive_format = getattr(args, "deploy_archive_format", None)
    if archive_name is not None or archive_format is not None:
        defaults = ArchiveConfig()
        overrides["archive"] = ArchiveConfig(
            name=archive_name if archive_name is not None else defaults.name,
            format=archive_format if archive_format is not None else defaults.format,
        )

    # Yocto cache upload config
    deploy_cache = getattr(args, "deploy_cache", None)
    if deploy_cache is not None:
        overrides["yocto_cache"] = YoctoCacheConfig(
            enabled=deploy_cache,
            downloads=getattr(args, "deploy_cache_downloads", True),
            sstate=getattr(args, "deploy_cache_sstate", True),
        )

    include_build_manifest = getattr(args, "include_build_manifest", None)
    if include_build_manifest is not None:
        overrides["include_build_manifest"] = include_build_manifest

    # HTML index config
    #
    # ``--update-index/--no-update-index`` is forwarded separately as the
    # ``update_index`` argument of ``ArtifactDeployer.deploy()``, which
    # toggles ``IndexConfig.enabled`` only.  Building a fresh ``IndexConfig``
    # here would clobber every other registry-configured index setting
    # (title, sign_urls, tree, facets, theme, ...) and make the page differ
    # from the one produced by ``bsp deploy index``.

    return overrides


#: Global options that consume a following value, used when scanning argv.
_GLOBAL_VALUE_OPTIONS = {"--registry", "-r", "--remote", "--branch"}


def _rewrite_deploy_index_argv(argv):
    """
    Normalize ``bsp deploy index ...`` into the internal ``index`` subcommand.

    ``deploy`` takes an optional ``bsp_name`` positional, which argparse cannot
    combine with nested subparsers.  The ``index`` command is therefore kept as
    a top-level (hidden) subparser and the ``deploy`` prefix is stripped here.
    """
    argv = list(argv)
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in _GLOBAL_VALUE_OPTIONS:
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        if token == "deploy" and i + 1 < len(argv) and argv[i + 1] == "index":
            del argv[i]
        break
    return argv


def _index_display_url(backend, remote_path: str, index_cfg, fallback: str) -> str:
    """
    Return the URL to print for an uploaded index page.

    When URL signing is enabled the plain blob URL returned by the upload is
    not directly openable for private containers, so a read-only signed URL
    (including the access token) is requested from the backend instead.  Any
    failure falls back to the plain upload URL.
    """
    if not getattr(index_cfg, "sign_urls", False) or getattr(
        backend, "dry_run", False
    ):
        return fallback
    try:
        signed = backend.get_signed_url(
            remote_path, expiry=getattr(index_cfg, "sas_expiry", None)
        )
    except NotImplementedError:
        return fallback
    except Exception as exc:  # noqa: BLE001
        logging.warning("Failed to sign index URL for %s: %s", remote_path, exc)
        return fallback
    return signed or fallback


def _run_index_command(args, bsp_mgr=None) -> int:
    """
    Rebuild the browsable HTML index for a storage container.

    The index is regenerated purely from the live container listing, so no
    local build is required.  This is what lets a scheduled job refresh
    expiring signed URLs.

    Provider, container and Azure account URL default to the root-level
    ``deploy:`` block of the bsp-registry model (when a registry is loaded);
    any explicitly given CLI option wins over the registry value.
    """
    from .deployer import ArtifactDeployer
    from .models import DeployConfig
    from .storage import create_backend

    registry_deploy = None
    if bsp_mgr is not None:
        try:
            registry_deploy = bsp_mgr.get_registry_deploy_config()
        except Exception as exc:  # noqa: BLE001
            logging.warning("Failed to read deploy config from registry: %s", exc)

    def _registry(attr, default=None):
        value = getattr(registry_deploy, attr, None) if registry_deploy else None
        return default if value is None else value

    provider = (
        getattr(args, "deploy_provider", None)
        or _registry("provider")
        or "azure"
    )
    container = (
        getattr(args, "container", None)
        or _registry("container")
        or _registry("bucket")
    )
    if not container:
        logging.error(
            "No container given: pass it on the command line or define "
            "'deploy.container' in the registry configuration."
        )
        return 1
    account_url = getattr(args, "index_account_url", None) or _registry("account_url")
    dry_run = getattr(args, "dry_run", False)

    registry_index = getattr(registry_deploy, "index", None)
    defaults = registry_index or IndexConfig()

    def _opt(attr, default):
        value = getattr(args, attr, None)
        return default if value is None else value

    collapse_depth = getattr(args, "index_collapse_depth", None)
    facets_cli = [str(f) for f in (getattr(args, "index_facets", None) or [])]
    index_cfg = IndexConfig(
        enabled=True,
        title=defaults.title,
        sign_urls=_opt("index_sign_urls", defaults.sign_urls),
        sas_expiry=getattr(args, "index_sas_expiry", None) or defaults.sas_expiry,
        root_index=True,
        tree=_opt("index_tree", defaults.tree),
        collapse_depth=(
            defaults.collapse_depth if collapse_depth is None else collapse_depth
        ),
        search=_opt("index_search", defaults.search),
        exclude=getattr(args, "index_exclude", None) or list(defaults.exclude),
        show_dates=defaults.show_dates,
        facets=(
            []
            if getattr(args, "index_no_facets", False) is True
            else facets_cli or list(defaults.facets)
        ),
        theme=str(getattr(args, "index_theme", None) or defaults.theme or "auto"),
        accent=str(getattr(args, "index_accent", None) or defaults.accent or ""),
    )
    deploy_cfg = DeployConfig(provider=provider, container=container, index=index_cfg)

    if provider == "azure":
        backend_kwargs = {
            "container_name": container,
            "account_url": account_url,
            "dry_run": dry_run,
        }
    elif provider == "aws":
        backend_kwargs = {
            "bucket_name": container,
            "region": _registry("region"),
            "profile": _registry("profile"),
            "dry_run": dry_run,
        }
    else:
        logging.error("Unsupported index provider: %s", provider)
        return 1

    try:
        backend = create_backend(provider, **backend_kwargs)
    except (ImportError, ValueError) as exc:
        logging.error("Failed to initialize storage backend: %s", exc)
        return 1

    deployer = ArtifactDeployer(deploy_cfg, backend)
    prefix = getattr(args, "index_prefix", None) or ""
    if prefix.strip("/"):
        logging.warning(
            "--prefix is deprecated and ignored: a single index.html is "
            "generated at the container root covering every prefix."
        )

    # A single container-root index.html is (re)generated, always.
    urls = deployer.refresh_container_indexes(index_config=index_cfg)
    for remote in sorted(urls):
        print(f"{remote} → {_index_display_url(backend, remote, index_cfg, urls[remote])}")

    return 0


def _collect_gather_overrides(args) -> dict:
    """
    Extract gather-related CLI arguments into a flat deploy-override dict.

    Only the storage location fields are extracted (provider, container,
    prefix).  Archive and pattern fields are upload-only concepts and are
    therefore intentionally omitted.

    Keys with ``None`` values are omitted so they do not clobber registry
    config defaults in the merge step inside ``BspManager``.
    """
    overrides = {}
    provider = getattr(args, "deploy_provider", None)
    if provider is not None:
        overrides["provider"] = provider
    container = getattr(args, "deploy_container", None)
    if container is not None:
        overrides["container"] = container
    prefix = getattr(args, "deploy_prefix", None)
    if prefix is not None:
        overrides["prefix"] = prefix
    return overrides


def _collect_scan_overrides(args) -> dict:
    """
    Extract scan-related CLI arguments into a flat scan-override dict.

    Keys with ``None`` values are omitted so they do not clobber registry
    config defaults in the merge step inside ``BspManager``.
    """
    overrides = {}
    tool = getattr(args, "scan_tool", None)
    if tool is not None:
        overrides["tool"] = tool
    severity = getattr(args, "scan_severity", None)
    if severity is not None:
        overrides["severity"] = severity
    fail_on = getattr(args, "scan_fail_on", None)
    if fail_on is not None:
        overrides["fail_on"] = fail_on
    sbom_format = getattr(args, "scan_sbom_format", None)
    if sbom_format is not None:
        overrides["sbom_format"] = sbom_format
    output_dir = getattr(args, "scan_output_dir", None)
    if output_dir is not None:
        overrides["output_dir"] = output_dir
    return overrides


def _collect_flash_overrides(args) -> dict:
    """
    Extract flash-related CLI arguments into a flat flash-override dict.

    Keys with ``None`` values are omitted so they do not clobber registry
    config defaults in the merge step inside ``BspManager``.
    """
    overrides = {}
    tool = getattr(args, "flash_tool", None)
    if tool is not None:
        overrides["tool"] = tool
    patterns = getattr(args, "flash_image_patterns", None)
    if patterns:
        overrides["image_patterns"] = patterns
    extra_args = getattr(args, "flash_extra_args", None)
    if extra_args is not None:
        overrides["extra_args"] = extra_args
    return overrides


def _parse_key_value_params(raw_params) -> dict:
    """Parse repeated KEY=VALUE parameters into a dictionary."""
    parsed = {}
    for entry in raw_params or []:
        if "=" not in entry:
            raise ValueError(
                f"Invalid --test-param value '{entry}'. Expected format: KEY=VALUE (e.g., BOARD=dut-1)."
            )
        key, value = entry.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid --test-param value '{entry}'. KEY must not be empty.")
        if not value:
            raise ValueError(f"Invalid --test-param value '{entry}'. VALUE must not be empty.")
        parsed[key] = value
    return parsed


# =============================================================================
# Remotes sub-command dispatcher (no registry loading required)
# =============================================================================


def _dispatch_remotes(args) -> int:
    """Handle all ``bsp remotes`` sub-commands.

    Returns an integer exit code (0 = success).
    """
    mgr = RemotesManager()
    subcmd = getattr(args, "remotes_command", None)

    if subcmd is None:
        # Plain ``bsp remotes`` — list all remotes
        remotes = mgr.ensure_default_remote(branch=getattr(args, "branch", DEFAULT_BRANCH))
        verbose = getattr(args, "remotes_verbose", False)
        for r in remotes:
            if verbose:
                print(f"{r.name}\t{r.url} (branch: {r.branch})")
            else:
                print(r.name)
        return 0

    if subcmd == "add":
        entry = mgr.add(name=args.name, url=args.url, branch=args.branch)
        print(f"Added remote '{entry.name}' -> {entry.url} (branch: {entry.branch})")
        return 0

    if subcmd in ("remove", "rm"):
        mgr.remove(args.name)
        print(f"Removed remote '{args.name}'")
        return 0

    if subcmd == "rename":
        updated = mgr.rename(args.old_name, args.new_name)
        print(f"Renamed remote '{args.old_name}' -> '{updated.name}'")
        return 0

    if subcmd == "set-url":
        updated = mgr.set_url(args.name, args.url)
        if args.branch:
            updated = mgr.set_branch(args.name, args.branch)
        print(f"Updated remote '{updated.name}': {updated.url} (branch: {updated.branch})")
        return 0

    if subcmd == "show":
        r = mgr.get(args.name)
        print(f"name:   {r.name}")
        print(f"url:    {r.url}")
        print(f"branch: {r.branch}")
        return 0

    logging.error("Unknown remotes sub-command: %s", subcmd)
    return 1


# =============================================================================
# Completions sub-command dispatcher (no registry loading required)
# =============================================================================


def _dispatch_completions(args) -> int:
    """Handle ``bsp completions [shell]``.

    Prints the shell-specific snippet that activates tab completions for the
    ``bsp`` command.  The user pastes (or eval-sources) this into their shell
    configuration file.

    Returns an integer exit code (0 = success).
    """
    try:
        import argcomplete  # noqa: F401
    except ImportError:
        print(
            "Error: argcomplete is not installed.\n"
            "Install it with:  pip install 'bsp-registry-tools[completions]'",
            file=__import__("sys").stderr,
        )
        return 1

    # Detect shell from $SHELL when none given on the CLI
    import os as _os
    shell = getattr(args, "shell", None)
    if not shell:
        shell_bin = _os.environ.get("SHELL", "")
        shell_name = shell_bin.rsplit("/", 1)[-1].lower()
        if shell_name in ("bash", "zsh", "fish", "tcsh"):
            shell = shell_name
        else:
            shell = "bash"  # sane default

    if shell == "bash":
        print('eval "$(register-python-argcomplete bsp)"')
    elif shell == "zsh":
        print("autoload -U bashcompinit && bashcompinit")
        print('eval "$(register-python-argcomplete bsp)"')
    elif shell == "fish":
        print("register-python-argcomplete --shell fish bsp | source")
    elif shell == "tcsh":
        print("eval `register-python-argcomplete --shell tcsh bsp`")
    else:
        print(f"Unsupported shell: {shell}", file=__import__("sys").stderr)
        return 1

    return 0

# =============================================================================
# Main Entry Point with Enhanced Commands (v2.0)
# =============================================================================


def main() -> int:
    """
    Main entry point for the BSP registry manager.

    Parses command line arguments, initializes the BSP manager,
    and executes the requested command.

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    try:
        # Parse command line arguments
        _version = get_installed_package_version("bsp-registry-tools")
        _version_str = (
            f"bsp-registry-tools {_version}\n"
            f"Supported model description version: {SUPPORTED_REGISTRY_VERSION}"
        )

        parser = argparse.ArgumentParser(description="Advantech Board Support Package Registry")
        parser.add_argument("--version", action="version", version=_version_str,
                            help="Show program version and supported model description version")
        parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
        parser.add_argument("--registry", "-r", default=None, help="BSP Registry file (local path)")
        parser.add_argument("--no-color", action="store_true", help="Disable colored output")
        parser.add_argument(
            "--remote",
            action="append",
            dest="remote",
            metavar="URL[@BRANCH][@name=NAME]",
            default=None,
            help=(
                "Remote registry git URL.  May be specified multiple times for "
                "multi-registry mode.  Each value may embed a branch and an "
                "optional display name using the format "
                "``URL@BRANCH@name=NAME``.  "
                "(default: %(const)s)"
            ),
        )
        parser.add_argument("--branch", default=DEFAULT_BRANCH,
                            help="Remote registry branch for a single --remote (default: %(default)s)")
        parser.add_argument("--update", dest="update", action="store_true", default=True,
                            help="Update the cached registry clone before use (default)")
        parser.add_argument("--no-update", dest="update", action="store_false",
                            help="Skip updating the cached registry clone")
        parser.add_argument("--local", action="store_true",
                            help="Force local registry lookup only (do not use remote)")

        # GUI shortcut: `bsp gui` launches the TUI launcher
        parser.add_argument(
            '--gui',
            action='store_true',
            help='Launch the interactive GUI (requires the [gui] extra)'
        )

        # Create subparsers for different commands
        subparsers = parser.add_subparsers(dest='command', help='Command to execute', required=False)

        # GUI subcommand (alias for --gui flag)
        subparsers.add_parser('gui', help='Launch the interactive GUI launcher')

        # ----------------------------------------------------------------
        # Build command
        # ----------------------------------------------------------------
        build_parser = subparsers.add_parser("build", help="Build an image for BSP")
        build_parser.add_argument(
            "bsp_name",
            nargs="?",
            type=str,
            help="BSP preset to build, optionally prefixed with registry name (registry:preset). Mutually exclusive with --device/--release."
        ).completer = PresetsCompleter()
        build_parser.add_argument(
            "--device", "-d",
            type=str,
            dest="device",
            help="Device slug (use with --release for component-based build)"
        ).completer = DevicesCompleter()
        build_parser.add_argument(
            "--release",
            type=str,
            dest="release",
            help="Release slug (use with --device for component-based build)"
        ).completer = ReleasesCompleter()
        build_parser.add_argument(
            "--vendor-release",
            type=str,
            dest="vendor_release",
            metavar="SLUG",
            help="Vendor sub-release slug to resolve for build selection"
        ).completer = VendorReleaseCompleter()
        build_parser.add_argument(
            "--override",
            type=str,
            dest="override_slug",
            metavar="SLUG",
            help="Vendor override slug to resolve for build selection"
        ).completer = OverrideCompleter()
        build_parser.add_argument(
            "--feature", "-f",
            action="append",
            dest="features",
            metavar="FEATURE",
            help="Feature slug to enable (can be specified multiple times)"
        ).completer = FeaturesCompleter()
        build_parser.add_argument(
            "--clean",
            action="store_true",
            help="Clean before building"
        )
        build_parser.add_argument(
            "--checkout",
            action="store_true",
            help="Checkout and validate build configuration without building (fast)"
        )
        build_parser.add_argument(
"--deploy",
            action="store_true",
            dest="deploy_after_build",
            help="Deploy artifacts to cloud storage after a successful build"
        )
        build_parser.add_argument(
            "--deploy-provider",
            type=str,
            dest="deploy_provider",
            metavar="PROVIDER",
            help="Cloud storage provider for deployment (azure, aws)"
        )
        build_parser.add_argument(
            "--deploy-container",
            "--deploy-bucket",
            type=str,
            dest="deploy_container",
            metavar="CONTAINER",
            help="Azure container or AWS bucket name for deployment"
        )
        build_parser.add_argument(
            "--deploy-prefix",
            type=str,
            dest="deploy_prefix",
            metavar="PREFIX",
            help="Remote path prefix template for deployment"
        )
        build_parser.add_argument(
            "--deploy-archive-name",
            type=str,
            dest="deploy_archive_name",
            default=None,
            metavar="NAME",
            help=(
                "Bundle all artifacts into a single archive with this name before uploading "
                "(supports {device}, {release}, {distro}, {vendor}, {date}, {datetime})"
            )
        )
        build_parser.add_argument(
            "--deploy-archive-format",
            type=str,
            dest="deploy_archive_format",
            default=None,
            metavar="FORMAT",
            choices=["tar.gz", "tar.bz2", "tar.xz", "zip"],
            help="Compression format for the archive bundle (default: tar.gz)"
        )
        build_parser.add_argument(
            "--deploy-cache",
            action="store_true",
            default=None,
            dest="deploy_cache",
            help=(
                "Also upload Yocto DL_DIR / SSTATE_DIR caches after build. "
                "Only effective when --deploy is used."
            )
        )
        build_parser.add_argument(
            "--no-deploy-cache-downloads",
            action="store_false",
            dest="deploy_cache_downloads",
            default=True,
            help="Skip uploading the DL_DIR downloads cache (only effective with --deploy-cache)."
        )
        build_parser.add_argument(
            "--no-deploy-cache-sstate",
            action="store_false",
            dest="deploy_cache_sstate",
            default=True,
            help="Skip uploading the SSTATE_DIR sstate cache (only effective with --deploy-cache)."
        )
        build_parser.add_argument(
            "--no-build-manifest",
            action="store_false",
            default=None,
            dest="include_build_manifest",
            help=(
                "Do not upload the build-manifest.json produced by the build "
                "(only effective when --deploy is used)."
            ),
        )
        build_parser.add_argument(
            "--update-index",
            action="store_true",
            default=None,
            dest="update_index",
            help=(
                "Regenerate and upload a browsable index.html after deployment "
                "(only effective when --deploy is used)."
            )
        )
        build_parser.add_argument(
            "--no-update-index",
            action="store_false",
            dest="update_index",
            help="Do not generate an index.html after deployment."
        )
        build_parser.add_argument(
            "--test",
            action="store_true",
            dest="run_test",
            help="Submit a LAVA HIL test job after a successful build"
        )
        build_parser.add_argument(
            "--wait",
            action="store_true",
            help="Wait for the LAVA job to complete (requires --test)"
        )
        build_parser.add_argument(
            "--lava-server",
            type=str,
            dest="lava_server",
            metavar="URL",
            help="LAVA server base URL (overrides registry 'lava.server')"
        )
        build_parser.add_argument(
            "--lava-token",
            type=str,
            dest="lava_token",
            metavar="TOKEN",
            help="LAVA authentication token (overrides registry 'lava.token')"
        )
        build_parser.add_argument(
            "--artifact-url",
            type=str,
            dest="artifact_url",
            metavar="URL",
            help="Base URL where build artifacts are served to the LAVA lab"
        )
        build_parser.add_argument(
            "--target",
            type=str,
            dest="target",
            metavar="TARGET",
            help="Bitbake build target (image or recipe) to pass to KAS (overrides registry targets)"
        )
        build_parser.add_argument(
            "--task",
            type=str,
            dest="task",
            metavar="TASK",
            help="Bitbake task to run (e.g. compile, configure) to pass to KAS"
        )
        build_parser.add_argument(
            '--path',
            type=str,
            dest='build_path',
            metavar='PATH',
            help='Override output build directory path'
        )
        build_parser.add_argument(
            "--scan",
            action="store_true",
            dest="scan_after_build",
            help="Scan built artifacts for CVEs (CRA) after a successful build"
        )
        build_parser.add_argument(
            "--scan-tool",
            type=str,
            dest="scan_tool",
            metavar="TOOL",
            choices=["trivy", "syft+grype"],
            default=None,
            help="Scanner backend to use: trivy (default) or syft+grype"
        )
        build_parser.add_argument(
            "--scan-severity",
            type=str,
            dest="scan_severity",
            metavar="LEVEL",
            choices=["LOW", "MEDIUM", "HIGH", "CRITICAL"],
            default=None,
            help="Minimum CVE severity to report (default: HIGH)"
        )
        build_parser.add_argument(
            "--scan-fail-on",
            type=str,
            dest="scan_fail_on",
            metavar="LEVEL",
            choices=["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"],
            default=None,
            help="Exit non-zero if any finding at this severity (default: CRITICAL)"
        )
        build_parser.add_argument(
            "--scan-output-dir",
            type=str,
            dest="scan_output_dir",
            metavar="PATH",
            default=None,
            help="Directory to write scan reports and SBOMs into"
        )
        build_parser.add_argument(
            "--flash",
            type=str,
            dest="flash_target",
            metavar="DEVICE",
            default=None,
            help="Flash built artifacts to DEVICE (e.g. /dev/sdb) after a successful build"
        )
        build_parser.add_argument(
            "--flash-tool",
            type=str,
            dest="flash_tool",
            metavar="TOOL",
            choices=["bmaptool", "dd", "uuu"],
            default=None,
            help="Flash tool to use: bmaptool (default), dd, or uuu"
        )
        build_parser.add_argument(
            "--docker-build-options",
            type=str,
            dest="docker_build_options",
            metavar="OPTIONS",
            default=None,
            help=(
                "Extra flags passed verbatim to 'docker build' (e.g. '--no-cache --network host'). "
                "Overrides 'build_options' in the registry container definition."
            )
        )
        build_parser.add_argument(
            "--docker-no-cache",
            dest="no_cache",
            action="store_true",
            default=False,
            help=(
                "Disable Docker layer cache when building the BSP container image. "
                "Shorthand for --docker-build-options '--no-cache'."
            ),
        )

        # ----------------------------------------------------------------
        # Fetch command
        # ----------------------------------------------------------------
        fetch_parser = subparsers.add_parser("fetch", help="Fetch sources for BSP")
        fetch_parser.add_argument(
            "bsp_name",
            nargs="?",
            type=str,
            help="BSP preset to fetch, optionally prefixed with registry name (registry:preset). Mutually exclusive with --device/--release."
        ).completer = PresetsCompleter()
        fetch_parser.add_argument(
            "--device", "-d",
            type=str,
            dest="device",
            help="Device slug (use with --release for component-based fetch)"
        ).completer = DevicesCompleter()
        fetch_parser.add_argument(
            "--release",
            type=str,
            dest="release",
            help="Release slug (use with --device for component-based fetch)"
        ).completer = ReleasesCompleter()
        fetch_parser.add_argument(
            "--vendor-release",
            type=str,
            dest="vendor_release",
            metavar="SLUG",
            help="Vendor sub-release slug to resolve for fetch selection"
        ).completer = VendorReleaseCompleter()
        fetch_parser.add_argument(
            "--override",
            type=str,
            dest="override_slug",
            metavar="SLUG",
            help="Vendor override slug to resolve for fetch selection"
        ).completer = OverrideCompleter()
        fetch_parser.add_argument(
            "--feature", "-f",
            action="append",
            dest="features",
            metavar="FEATURE",
            help="Feature slug to enable (can be specified multiple times)"
        ).completer = FeaturesCompleter()
        fetch_parser.add_argument(
            "--target",
            type=str,
            dest="target",
            metavar="TARGET",
            help="BitBake target to fetch (defaults to targets resolved from the KAS configuration)"
        )
        fetch_parser.add_argument(
            "--path",
            type=str,
            dest="build_path",
            metavar="PATH",
            help="Override output build directory path"
        )

        # ----------------------------------------------------------------
        # List command (with optional subtype)
        # ----------------------------------------------------------------
        list_parser = subparsers.add_parser("list", help="List available BSPs and components")
        list_parser.add_argument(
            "list_type",
            nargs="?",
            choices=["devices", "releases", "features", "distros"],
            default=None,
            help="Component type to list (omit to list BSP presets)"
        )
        list_parser.add_argument(
            "--device", "-d",
            type=str,
            dest="device",
            help='Filter releases by device slug (only used with "releases")'
        ).completer = DevicesCompleter()
        list_parser.add_argument(
            "--remote",
            type=str,
            dest="filter_remote",
            metavar="NAME",
            default=None,
            help="Show only entries from the named remote registry"
        ).completer = RemotesCompleter()

        # Containers command
        containers_parser = subparsers.add_parser(
            "containers",
            help="List or build container images from the registry",
        )
        containers_parser.add_argument(
            "containers_action",
            nargs="?",
            choices=["list", "build"],
            default="list",
            help="Action to perform: 'list' (default) to list containers, 'build' to build them",
        )
        containers_parser.add_argument(
            "container_name",
            nargs="?",
            type=str,
            default=None,
            help=(
                "Container name to build (only used with 'build'; omit to build all). "
                "Supports 'registry:container' syntax in multi-registry mode."
            ),
        ).completer = ContainerCompleter()
        containers_parser.add_argument(
            "--docker-no-cache",
            dest="no_cache",
            action="store_true",
            default=False,
            help="Disable Docker layer cache for the container build",
        )

        # ----------------------------------------------------------------
        # Tree command
        # ----------------------------------------------------------------
        tree_parser = subparsers.add_parser("tree", help="Display a tree view of the BSP registry")
        tree_mode_group = tree_parser.add_mutually_exclusive_group()
        tree_mode_group.add_argument(
            "--full",
            action="store_true",
            help="Show full details including includes and descriptions for all items"
        )
        tree_mode_group.add_argument(
            "--compact",
            action="store_true",
            help="Show compact output with names/slugs only"
        )
        tree_parser.add_argument(
            "--remote",
            type=str,
            dest="filter_remote",
            metavar="NAME",
            default=None,
            help="Show only entries from the named remote registry"
        ).completer = RemotesCompleter()

        # ----------------------------------------------------------------
        # Export command
        # ----------------------------------------------------------------
        export_parser = subparsers.add_parser("export", help="Export BSP configuration")
        export_parser.add_argument(
            "bsp_name",
            nargs="?",
            type=str,
            help="BSP preset to export, optionally prefixed with registry name (registry:preset). Mutually exclusive with --device/--release."
        ).completer = PresetsCompleter()
        export_parser.add_argument(
            "--device", "-d",
            type=str,
            dest="device",
            help="Device slug"
        ).completer = DevicesCompleter()
        export_parser.add_argument(
            "--release",
            type=str,
            dest="release",
            help="Release slug"
        ).completer = ReleasesCompleter()
        export_parser.add_argument(
            "--feature", "-f",
            action="append",
            dest="features",
            metavar="FEATURE",
            help="Feature slug to enable (can be specified multiple times)"
        ).completer = FeaturesCompleter()
        export_parser.add_argument(
            "--output", "-o",
            type=str,
            help="Output file path (default: stdout)"
        )
        export_parser.add_argument(
            "--repo-manifest",
            action="store_true",
            dest="repo_manifest",
            help="Export Android repo manifest XML"
        )
        export_parser.add_argument(
            "--lock",
            action="store_true",
            dest="lock",
            help="Use `kas dump --lock` when exporting KAS configuration"
        )

        # ----------------------------------------------------------------
        # Server command
        # ----------------------------------------------------------------
        server_parser = subparsers.add_parser(
            "server", help="Start a GraphQL / REST HTTP server"
        )
        server_parser.add_argument(
            "--host",
            default="127.0.0.1",
            help="Host address to bind to (default: %(default)s)",
        )
        server_parser.add_argument(
            "--port",
            type=int,
            default=8080,
            help="Port to listen on (default: %(default)s)",
        )
        server_parser.add_argument(
            "--reload",
            action="store_true",
            help="Enable auto-reload on code changes (development only)",
        )

        # ----------------------------------------------------------------
        # Shell command
        # ----------------------------------------------------------------
        shell_parser = subparsers.add_parser("shell", help="Enter interactive shell for BSP")
        shell_parser.add_argument(
            "bsp_name",
            nargs="?",
            type=str,
            help="BSP preset, optionally prefixed with registry name (registry:preset). Mutually exclusive with --device/--release."
        ).completer = PresetsCompleter()
        shell_parser.add_argument(
            "--device", "-d",
            type=str,
            dest="device",
            help="Device slug"
        ).completer = DevicesCompleter()
        shell_parser.add_argument(
            "--release",
            type=str,
            dest="release",
            help="Release slug"
        ).completer = ReleasesCompleter()
        shell_parser.add_argument(
            "--feature", "-f",
            action="append",
            dest="features",
            metavar="FEATURE",
            help="Feature slug to enable (can be specified multiple times)"
        ).completer = FeaturesCompleter()
        shell_parser.add_argument(
            "--command", "-c",
            type=str,
            dest="shell_command",
            help="Command to execute in shell (optional, if not provided starts interactive shell)"
        )
        shell_parser.add_argument(
            "--path",
            type=str,
            dest="build_path",
            metavar="PATH",
            help="Override output build directory path"
        )

        # ----------------------------------------------------------------
# Deploy command
        # ----------------------------------------------------------------
        deploy_parser = subparsers.add_parser(
            "deploy",
            help="Deploy build artifacts to cloud storage",
            epilog=(
                "Subcommands:\n"
                "  index  Rebuild the browsable HTML index of a storage container\n"
                "         (see `bsp deploy index --help`)"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        deploy_parser.add_argument(
            "bsp_name",
            nargs="?",
            type=str,
            help="BSP preset whose artifacts to deploy, optionally prefixed with registry name (registry:preset)."
        ).completer = PresetsCompleter()
        deploy_parser.add_argument(
            "--device", "-d",
            type=str,
            dest="device",
            help="Device slug (use with --release for component-based deployment)"
        ).completer = DevicesCompleter()
        deploy_parser.add_argument(
            "--release",
            type=str,
            dest="release",
            help="Release slug (use with --device for component-based deployment)"
        ).completer = ReleasesCompleter()
        deploy_parser.add_argument(
            "--feature", "-f",
            action="append",
            dest="features",
            metavar="FEATURE",
            help="Feature slug (can be specified multiple times)"
        ).completer = FeaturesCompleter()
        deploy_parser.add_argument(
            "--provider",
            type=str,
            dest="deploy_provider",
            default=None,
            metavar="PROVIDER",
            help="Cloud storage provider: azure (default) or aws"
        )
        deploy_parser.add_argument(
            "--container",
            "--bucket",
            type=str,
            dest="deploy_container",
            default=None,
            metavar="CONTAINER",
            help="Azure Blob container name or AWS S3 bucket name"
        )
        deploy_parser.add_argument(
            "--prefix",
            type=str,
            dest="deploy_prefix",
            default=None,
            metavar="PREFIX",
            help=(
                "Remote path prefix template "
                "(supports {device}, {release}, {distro}, {vendor}, {date})"
            )
        )
        deploy_parser.add_argument(
            "--pattern",
            action="append",
            dest="deploy_patterns",
            metavar="PATTERN",
            help="Glob pattern for artifacts to upload (can be specified multiple times)"
        )
        deploy_parser.add_argument(
            "--archive-name",
            type=str,
            dest="deploy_archive_name",
            default=None,
            metavar="NAME",
            help=(
                "Bundle all artifacts into a single archive with this name before uploading "
                "(supports {device}, {release}, {distro}, {vendor}, {date}, {datetime})"
            )
        )
        deploy_parser.add_argument(
            "--archive-format",
            type=str,
            dest="deploy_archive_format",
            default=None,
            metavar="FORMAT",
            choices=["tar.gz", "tar.bz2", "tar.xz", "zip"],
            help="Compression format for the archive bundle (default: tar.gz)"
        )
        deploy_parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="List what would be uploaded without actually uploading"
        )
        deploy_parser.add_argument(
            "--deploy-cache",
            action="store_true",
            default=None,
            dest="deploy_cache",
            help=(
                "Also upload Yocto DL_DIR / SSTATE_DIR caches to cloud storage. "
                "Cache directories are resolved from the registry environment config "
                "or from the DL_DIR / SSTATE_DIR environment variables."
            )
        )
        deploy_parser.add_argument(
            "--no-deploy-cache-downloads",
            action="store_false",
            dest="deploy_cache_downloads",
            default=True,
            help="Skip uploading the DL_DIR downloads cache (only effective with --deploy-cache)."
        )
        deploy_parser.add_argument(
            "--no-deploy-cache-sstate",
            action="store_false",
            dest="deploy_cache_sstate",
            default=True,
            help="Skip uploading the SSTATE_DIR sstate cache (only effective with --deploy-cache)."
        )
        deploy_parser.add_argument(
            "--no-build-manifest",
            action="store_false",
            default=None,
            dest="include_build_manifest",
            help="Do not upload the build-manifest.json produced by 'bsp build'."
        )
        deploy_parser.add_argument(
            "--update-index",
            action="store_true",
            default=None,
            dest="update_index",
            help=(
                "Regenerate and upload a browsable index.html (with signed "
                "read-only artifact links) after a successful deploy."
            )
        )
        deploy_parser.add_argument(
            "--no-update-index",
            action="store_false",
            dest="update_index",
            help="Do not generate an index.html, even when enabled in the registry config."
        )

        # ----------------------------------------------------------------
        # Index command (invoked as `bsp deploy index`)
        # ----------------------------------------------------------------
        index_parser = subparsers.add_parser(
            "index",
            prog="bsp deploy index",
            description="Rebuild the browsable HTML index of a storage container"
        )
        index_parser.add_argument(
            "container",
            type=str,
            nargs="?",
            default=None,
            help="Azure Blob container or AWS S3 bucket name "
                 "(default: 'deploy.container' from the registry configuration)"
        )
        index_parser.add_argument(
            "--prefix",
            type=str,
            dest="index_prefix",
            default=None,
            metavar="PREFIX",
            help="Deprecated and ignored: the container-root index.html "
                 "always covers the whole container"
        )
        index_parser.add_argument(
            "--root",
            action="store_true",
            dest="index_root",
            default=None,
            help="Deprecated and ignored: the container-root index.html is "
                 "always generated"
        )
        index_parser.add_argument(
            "--provider",
            type=str,
            dest="deploy_provider",
            default=None,
            metavar="PROVIDER",
            help="Cloud storage provider: azure or aws "
                 "(default: 'deploy.provider' from the registry configuration, "
                 "else azure)"
        )
        index_parser.add_argument(
            "--account-url",
            type=str,
            dest="index_account_url",
            default=None,
            metavar="URL",
            help="Azure storage account URL "
                 "(default: 'deploy.account_url' from the registry configuration)"
        )
        index_parser.add_argument(
            "--no-sign-urls",
            action="store_false",
            dest="index_sign_urls",
            default=None,
            help="Emit relative links instead of signed URLs (for CDN / custom domains)"
        )
        index_parser.add_argument(
            "--sas-expiry",
            type=str,
            dest="index_sas_expiry",
            default=None,
            metavar="ISO8601",
            help="Expiry timestamp for generated signed URLs (default: 2038-01-19T03:14:06Z)"
        )
        index_parser.add_argument(
            "--tree",
            action="store_true",
            dest="index_tree",
            default=None,
            help="Render a collapsible directory tree (default)"
        )
        index_parser.add_argument(
            "--flat",
            action="store_false",
            dest="index_tree",
            help="Render the legacy flat artifact table instead of a tree"
        )
        index_parser.add_argument(
            "--collapse-depth",
            type=int,
            dest="index_collapse_depth",
            default=None,
            metavar="N",
            help="Directory depth expanded by default in the tree view (default: 1)"
        )
        index_parser.add_argument(
            "--exclude",
            action="append",
            dest="index_exclude",
            metavar="PATTERN",
            help="Glob pattern of paths to omit from the index (repeatable)"
        )
        index_parser.add_argument(
            "--facet",
            action="append",
            dest="index_facets",
            choices=["preset", "machine", "release", "distro", "vendor", "date"],
            metavar="NAME",
            help="Facet group to offer in the filter bar (repeatable; "
                 "default: preset, machine, release, date)"
        )
        index_parser.add_argument(
            "--no-facets",
            action="store_true",
            dest="index_no_facets",
            help="Disable the faceted filter bar"
        )
        index_parser.add_argument(
            "--theme",
            choices=["auto", "light", "dark"],
            dest="index_theme",
            default=None,
            help="Colour scheme of the generated page (default: auto)"
        )
        index_parser.add_argument(
            "--accent",
            dest="index_accent",
            default=None,
            metavar="CSS_COLOR",
            help="Accent colour used by the generated page"
        )
        index_parser.add_argument(
            "--no-search",
            action="store_false",
            dest="index_search",
            default=None,
            help="Omit the interactive search box"
        )
        index_parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Show what would be generated without uploading (no credentials required)"
        )

        # ----------------------------------------------------------------
        # Gather command
        # ----------------------------------------------------------------
        gather_parser = subparsers.add_parser(
            "gather",
            help="Download BSP build artifacts from cloud storage"
        )
        gather_parser.add_argument(
            "bsp_name",
            nargs="?",
            type=str,
            help="BSP preset whose artifacts to download, optionally prefixed with registry name (registry:preset). Mutually exclusive with --device/--release."
        ).completer = PresetsCompleter()
        gather_parser.add_argument(
            "--device", "-d",
            type=str,
            dest="device",
            help="Device slug (use with --release for component-based gather)"
        ).completer = DevicesCompleter()
        gather_parser.add_argument(
            "--release",
            type=str,
            dest="release",
            help="Release slug (use with --device for component-based gather)"
        ).completer = ReleasesCompleter()
        gather_parser.add_argument(
            "--feature", "-f",
            action="append",
            dest="features",
            metavar="FEATURE",
            help="Feature slug (can be specified multiple times)"
        ).completer = FeaturesCompleter()
        gather_parser.add_argument(
            "--dest-dir",
            type=str,
            dest="dest_dir",
            default=None,
            metavar="PATH",
            help=(
                "Local directory to write downloaded artifacts into. "
                "Defaults to <build_path>/build/tmp/deploy/images under the "
                "build path configured in the registry."
            )
        )
        gather_parser.add_argument(
            "--provider",
            type=str,
            dest="deploy_provider",
            default=None,
            metavar="PROVIDER",
            help="Cloud storage provider: azure (default) or aws"
        )
        gather_parser.add_argument(
            "--container",
            "--bucket",
            type=str,
            dest="deploy_container",
            default=None,
            metavar="CONTAINER",
            help="Azure Blob container name or AWS S3 bucket name"
        )
        gather_parser.add_argument(
            "--prefix",
            type=str,
            dest="deploy_prefix",
            default=None,
            metavar="PREFIX",
            help=(
                "Remote path prefix template "
                "(supports {device}, {release}, {distro}, {vendor}, {date})"
            )
        )
        gather_parser.add_argument(
            "--date",
            type=str,
            dest="gather_date",
            default=None,
            metavar="DATE",
            help=(
                "Date override for the {date} placeholder in the prefix template "
                "(YYYY-MM-DD). Defaults to today's date."
            )
        )
        gather_parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="List what would be downloaded without actually downloading"
        )
        gather_parser.add_argument(
            "--gather-cache",
            action="store_true",
            dest="gather_cache",
            default=False,
            help=(
                "Also restore Yocto DL_DIR / SSTATE_DIR caches from cloud storage if "
                "available. Missing caches are silently skipped."
            )
        )
        gather_parser.add_argument(
            "--cache-downloads-dir",
            type=str,
            dest="cache_downloads_dest",
            default=None,
            metavar="PATH",
            help=(
                "Local directory to restore the Yocto downloads cache into. "
                "Defaults to the DL_DIR env variable or a 'downloads/' sub-directory "
                "inside --dest-dir. Only effective with --gather-cache."
            )
        )
        gather_parser.add_argument(
            "--cache-sstate-dir",
            type=str,
            dest="cache_sstate_dest",
            default=None,
            metavar="PATH",
            help=(
                "Local directory to restore the Yocto sstate cache into. "
                "Defaults to the SSTATE_DIR env variable or a 'sstate/' sub-directory "
                "inside --dest-dir. Only effective with --gather-cache."
            )
        )

        # ----------------------------------------------------------------
        # Scan command (CRA image vulnerability scanning)
        # ----------------------------------------------------------------
        scan_parser = subparsers.add_parser(
            "scan",
            help="Scan built artifacts for CVEs and generate an SBOM (CRA compliance)"
        )
        scan_parser.add_argument(
            "bsp_name",
            nargs="?",
            type=str,
            help="BSP preset whose artifacts to scan, optionally prefixed with registry name (registry:preset). Mutually exclusive with --device/--release."
        ).completer = PresetsCompleter()
        scan_parser.add_argument(
            "--device", "-d",
            type=str,
            dest="device",
            help="Device slug (use with --release for component-based scan)"
        ).completer = DevicesCompleter()
        scan_parser.add_argument(
            "--release",
            type=str,
            dest="release",
            help="Release slug (use with --device for component-based scan)"
        ).completer = ReleasesCompleter()
        scan_parser.add_argument(
            "--feature", "-f",
            action="append",
            dest="features",
            metavar="FEATURE",
            help="Feature slug to enable (can be specified multiple times)"
        ).completer = FeaturesCompleter()
        scan_parser.add_argument(
            "--tool",
            type=str,
            dest="scan_tool",
            metavar="TOOL",
            choices=["trivy", "syft+grype"],
            default=None,
            help="Scanner backend: trivy (default) or syft+grype"
        )
        scan_parser.add_argument(
            "--severity",
            type=str,
            dest="scan_severity",
            metavar="LEVEL",
            choices=["LOW", "MEDIUM", "HIGH", "CRITICAL"],
            default=None,
            help="Minimum CVE severity to report (default: HIGH)"
        )
        scan_parser.add_argument(
            "--fail-on",
            type=str,
            dest="scan_fail_on",
            metavar="LEVEL",
            choices=["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"],
            default=None,
            help="Exit non-zero if any finding at this severity (default: CRITICAL)"
        )
        scan_parser.add_argument(
            "--sbom-format",
            type=str,
            dest="scan_sbom_format",
            metavar="FORMAT",
            choices=["cyclonedx", "spdx-json", "spdx-tag-value"],
            default=None,
            help="SBOM output format (default: cyclonedx)"
        )
        scan_parser.add_argument(
            "--output-dir",
            type=str,
            dest="scan_output_dir",
            metavar="PATH",
            default=None,
            help="Directory to write scan reports and SBOMs into"
        )
        scan_parser.add_argument(
            "--image-path",
            action="append",
            dest="scan_image_paths",
            metavar="PATH",
            default=None,
            help=(
                "Explicit artifact file to scan (can be specified multiple times). "
                "Overrides auto-discovery when provided."
            )
        )
        scan_parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="List what would be scanned without actually scanning"
        )

        # ----------------------------------------------------------------
        # Flash command (SD-card / block-device flashing via bmap-tools)
        # ----------------------------------------------------------------
        flash_parser = subparsers.add_parser(
            "flash",
            help="Flash a built image to an SD card or block device using bmap-tools"
        )
        flash_parser.add_argument(
            "bsp_name",
            nargs="?",
            type=str,
            help="BSP preset whose image to flash, optionally prefixed with registry name (registry:preset). Mutually exclusive with --device/--release."
        ).completer = PresetsCompleter()
        flash_parser.add_argument(
            "--device", "-d",
            type=str,
            dest="device",
            help="Device slug (use with --release for component-based flash)"
        ).completer = DevicesCompleter()
        flash_parser.add_argument(
            "--release",
            type=str,
            dest="release",
            help="Release slug (use with --device for component-based flash)"
        ).completer = ReleasesCompleter()
        flash_parser.add_argument(
            "--feature", "-f",
            action="append",
            dest="features",
            metavar="FEATURE",
            help="Feature slug to enable (can be specified multiple times)"
        ).completer = FeaturesCompleter()
        flash_parser.add_argument(
            "--target", "-t",
            type=str,
            dest="flash_target",
            metavar="DEVICE",
            default=None,
            help="Block device path to flash to (e.g. /dev/sdb)"
        )
        flash_parser.add_argument(
            "--image-path",
            type=str,
            dest="flash_image_path",
            metavar="PATH",
            default=None,
            help=(
                "Explicit image file to flash. "
                "Overrides auto-discovery when provided."
            )
        )
        flash_parser.add_argument(
            "--image-pattern",
            action="append",
            dest="flash_image_patterns",
            metavar="PATTERN",
            default=None,
            help=(
                "Glob pattern to find the flashable image (can be specified multiple times). "
                "Overrides the default patterns when provided."
            )
        )
        flash_parser.add_argument(
            "--tool",
            type=str,
            dest="flash_tool",
            metavar="TOOL",
            choices=["bmaptool", "dd", "uuu"],
            default=None,
            help="Flash tool to use: bmaptool (default), dd, or uuu"
        )
        flash_parser.add_argument(
            "--extra-args",
            type=str,
            dest="flash_extra_args",
            metavar="ARGS",
            default=None,
            help="Extra arguments forwarded verbatim to the flash tool (e.g. '--nobmap')"
        )
        flash_parser.add_argument(
            "--build-path",
            type=str,
            dest="build_path",
            metavar="PATH",
            default=None,
            help="Override the build output directory used for artifact discovery"
        )
        flash_parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Show what would be flashed without actually writing to the device"
        )

        # ----------------------------------------------------------------
        # Test command
        # ----------------------------------------------------------------
        test_parser = subparsers.add_parser(
            "test",
            help="Run BSP tests via LAVA, direct-local, direct-ssh, or direct-serial backends"
        )
        test_parser.add_argument(
            "bsp_name",
            nargs="?",
            type=str,
            help="BSP preset to test, optionally prefixed with registry name (registry:preset). Mutually exclusive with --device/--release."
        ).completer = PresetsCompleter()
        test_parser.add_argument(
            "--device", "-d",
            type=str,
            dest="device",
            help="Device slug (use with --release for component-based test)"
        ).completer = DevicesCompleter()
        test_parser.add_argument(
            "--release",
            type=str,
            dest="release",
            help="Release slug (use with --device for component-based test)"
        ).completer = ReleasesCompleter()
        test_parser.add_argument(
            "--feature", "-f",
            action="append",
            dest="features",
            metavar="FEATURE",
            help="Feature slug to enable (can be specified multiple times)"
        ).completer = FeaturesCompleter()
        test_parser.add_argument(
            "--wait",
            action="store_true",
            help="Block until the LAVA job completes and print test results"
        )
        test_parser.add_argument(
            "--lava-server",
            type=str,
            dest="lava_server",
            metavar="URL",
            help="LAVA server base URL (overrides registry 'lava.server')"
        )
        test_parser.add_argument(
            "--lava-token",
            type=str,
            dest="lava_token",
            metavar="TOKEN",
            help="LAVA authentication token (overrides registry 'lava.token')"
        )
        test_parser.add_argument(
            "--artifact-url",
            type=str,
            dest="artifact_url",
            metavar="URL",
            help="Base URL where build artifacts are served to the LAVA lab"
        )
        test_parser.add_argument(
            "--backend",
            type=str,
            dest="test_backend",
            choices=["lava", "direct-local", "direct-ssh", "direct-serial"],
            default=None,
            help="Test backend override (default: registry testing.backend or lava)"
        )
        test_parser.add_argument(
            "--test-repo-url",
            type=str,
            dest="test_repo_url",
            metavar="URL",
            help="Git URL for direct test-definition repository"
        )
        test_parser.add_argument(
            "--test-repo-ref",
            type=str,
            dest="test_repo_ref",
            metavar="REF",
            help="Git ref (branch/tag/commit) for --test-repo-url"
        )
        test_parser.add_argument(
            "--test-definition-path",
            action="append",
            dest="test_definition_paths",
            metavar="PATH",
            help="Definition file/dir/glob path inside test-definition repo (repeatable)"
        )
        test_parser.add_argument(
            "--test-job-path",
            action="append",
            dest="test_job_paths",
            metavar="PATH",
            help="Local LAVA job YAML (or Jinja2 template) file path (repeatable). "
                 "Files ending in .jinja2 or .j2 are rendered as Jinja2 templates "
                 "before parsing. Suites are read from "
                 "actions[].test.definitions[].path relative to the job file's directory. "
                 "No --test-repo-url is required when using this option."
        )
        test_parser.add_argument(
            "--test-requirements",
            action="append",
            dest="test_requirement_catalogs",
            metavar="PATH_OR_URL",
            help="Requirement catalogue YAML providing test case descriptions, "
                 "specifications, versions and categories for the report "
                 "(repeatable). Accepts a path — resolved inside the "
                 "test-definition root first, then as an absolute path — or an "
                 "http(s) URL (GitHub blob URLs are downloaded as raw content), "
                 "which allows the catalogue of another repository to be reused. "
                 "Defaults to 'requirements.yaml' at "
                 "the test-definition root when present. Direct backends only."
        )
        test_parser.add_argument(
            "--show-cases",
            action="store_true",
            dest="show_cases",
            help="List every test case with its description in the console "
                 "summary (implied by --verbose). Direct backends only."
        )
        test_parser.add_argument(
            "--test-suite",
            action="append",
            dest="test_suites",
            metavar="NAME",
            help="Run only the named test suite(s) (repeatable). Matches "
                 "actions[].test.definitions[].name in the LAVA job YAML "
                 "(falls back to the definition's metadata.name / file stem "
                 "for plain test definitions). Direct backends only."
        ).completer = TestSuitesCompleter()
        test_parser.add_argument(
            "--test-param",
            action="append",
            dest="test_params",
            metavar="KEY=VALUE",
            help="Direct-run parameter override for Lava-Test definitions (repeatable)"
        )
        test_parser.add_argument(
            "--direct-timeout",
            type=int,
            dest="direct_timeout",
            metavar="SECONDS",
            help="Per-step timeout for direct test execution"
        )
        test_parser.add_argument(
            "--direct-output-dir",
            type=str,
            dest="direct_output_dir",
            metavar="PATH",
            help="Output directory for direct test logs/results"
        )
        test_parser.add_argument(
            "--ssh-host",
            type=str,
            dest="ssh_host",
            metavar="HOST",
            help="SSH host for direct-ssh/direct-serial backends"
        )
        test_parser.add_argument(
            "--ssh-user",
            type=str,
            dest="ssh_user",
            metavar="USER",
            help="SSH user for direct-ssh/direct-serial backends"
        )
        test_parser.add_argument(
            "--ssh-port",
            type=int,
            dest="ssh_port",
            metavar="PORT",
            help="SSH port for direct-ssh/direct-serial backends (default: 22)"
        )
        test_parser.add_argument(
            "--ssh-key",
            type=str,
            dest="ssh_key",
            metavar="PATH",
            help="SSH private key path for direct-ssh/direct-serial backends"
        )
        test_parser.add_argument(
            "--ssh-password",
            type=str,
            dest="ssh_password",
            metavar="PASSWORD",
            help="SSH password for direct-ssh/direct-serial backends (requires sshpass)"
        )
        test_parser.add_argument(
            "--ssh-known-hosts-file",
            type=str,
            dest="ssh_known_hosts_file",
            metavar="PATH",
            help="Known hosts file for direct-ssh/direct-serial backends"
        )
        test_parser.add_argument(
            "--ssh-no-strict-host-key-checking",
            action="store_false",
            dest="ssh_strict_host_key_checking",
            default=None,
            help="Disable strict host key checking for direct-ssh/direct-serial backends"
        )
        test_parser.add_argument(
            "--ssh-remote-workdir",
            type=str,
            dest="ssh_remote_workdir",
            metavar="PATH",
            help="Remote working directory for staged test definitions"
        )
        test_parser.add_argument(
            "--ssh-serial-device",
            type=str,
            dest="ssh_serial_device",
            metavar="DEVICE",
            help="Serial device (e.g. /dev/ttyUSB0) used as SSH ProxyCommand transport"
        )
        test_parser.add_argument(
            "--ssh-serial-baudrate",
            type=int,
            dest="ssh_serial_baudrate",
            metavar="BAUD",
            help="Serial baudrate for --ssh-serial-device (default: 115200)"
        )

        # ----------------------------------------------------------------
        # Remotes command  (git-remote-style management of named remote
        # registries persisted in ~/.config/bsp/remotes.yaml)
        # ----------------------------------------------------------------
        remotes_parser = subparsers.add_parser(
            "remotes",
            help="Manage named remote BSP registry sources (like git remote)",
        )
        remotes_parser.add_argument(
            "-v", "--verbose-list",
            dest="remotes_verbose",
            action="store_true",
            help="Show URL and branch alongside each remote name when listing",
        )
        remotes_subparsers = remotes_parser.add_subparsers(
            dest="remotes_command",
            help="Remotes sub-command",
        )

        # bsp remotes add <name> <url> [--branch BRANCH]
        remotes_add = remotes_subparsers.add_parser(
            "add",
            help="Register a new named remote registry",
        )
        remotes_add.add_argument("name", help="Unique name for the remote (e.g. 'advantech')")
        remotes_add.add_argument("url", help="Git repository URL of the remote registry")
        remotes_add.add_argument(
            "--branch", "-b",
            default=DEFAULT_BRANCH,
            help="Branch to fetch from (default: %(default)s)",
        )

        # bsp remotes remove <name>
        remotes_remove = remotes_subparsers.add_parser(
            "remove",
            aliases=["rm"],
            help="Remove a named remote",
        )
        remotes_remove.add_argument("name", help="Name of the remote to remove").completer = RemotesCompleter()

        # bsp remotes rename <old> <new>
        remotes_rename = remotes_subparsers.add_parser(
            "rename",
            help="Rename a remote",
        )
        remotes_rename.add_argument("old_name", metavar="old-name", help="Current name of the remote").completer = RemotesCompleter()
        remotes_rename.add_argument("new_name", metavar="new-name", help="New name for the remote")

        # bsp remotes set-url <name> <url>
        remotes_set_url = remotes_subparsers.add_parser(
            "set-url",
            help="Change the URL of an existing remote",
        )
        remotes_set_url.add_argument("name", help="Name of the remote to update").completer = RemotesCompleter()
        remotes_set_url.add_argument("url", help="New Git repository URL")
        remotes_set_url.add_argument(
            "--branch", "-b",
            default=None,
            help="Also update the branch",
        )

        # bsp remotes show <name>
        remotes_show = remotes_subparsers.add_parser(
            "show",
            help="Show details about a named remote",
        )
        remotes_show.add_argument("name", help="Name of the remote to show").completer = RemotesCompleter()

        # ----------------------------------------------------------------
        # Completions command
        # ----------------------------------------------------------------
        completions_parser = subparsers.add_parser(
            "completions",
            help="Print the shell completion registration snippet",
        )
        completions_parser.add_argument(
            "shell",
            nargs="?",
            choices=["bash", "zsh", "fish", "tcsh"],
            default=None,
            help=(
                "Shell to generate completions for "
                "(default: auto-detected from $SHELL). "
                "Choices: bash, zsh, fish, tcsh."
            ),
        )

        # Activate argcomplete (exits immediately when shell is completing;
        # no-ops when argcomplete is not installed).
        try:
            import argcomplete
            argcomplete.autocomplete(parser)
        except ImportError:
            pass

        args = parser.parse_args(_rewrite_deploy_index_argv(sys.argv[1:]))

        # --gui flag or 'bsp gui' subcommand → launch TUI
        if getattr(args, 'gui', False) or args.command == 'gui':
            from .gui import launch_gui
            return launch_gui(
                registry_path=args.registry,
                remotes=args.remote,
                branch=args.branch if args.branch != DEFAULT_BRANCH else None,
                no_update=not args.update,
            )

        if not args.command:
            parser.print_help()
            return 1

        # Setup logging based on verbosity
        log_level = logging.DEBUG if args.verbose else logging.WARNING

        # Setup logging colors
        if args.no_color or not COLORAMA_AVAILABLE:
            logging.basicConfig(
                level=log_level,
                format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        else:
            logging.basicConfig(level=log_level)
            logger = logging.getLogger()
            handler = logger.handlers[0]
            handler.setFormatter(ColoramaFormatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            ))

        # ----------------------------------------------------------------
        # Dispatch remotes commands — these do NOT need a loaded registry.
        # ----------------------------------------------------------------
        if args.command == "remotes":
            return _dispatch_remotes(args)

        if args.command == "completions":
            return _dispatch_completions(args)

        # Resolve registry file path
        LOCAL_DEFAULTS = ["bsp-registry.yaml", "bsp-registry.yml"]
        local_registry = next((name for name in LOCAL_DEFAULTS if Path(name).is_file()), None)
        if args.registry is not None:
            registry_path = args.registry
            logging.info("Using explicitly provided registry: %s", registry_path)
            bsp_mgr = BspManager(registry_path, verbose=args.verbose)
        elif args.local:
            registry_path = local_registry or LOCAL_DEFAULTS[0]
            logging.info("Using local registry (--local): %s", registry_path)
            bsp_mgr = BspManager(registry_path, verbose=args.verbose)
        elif local_registry is not None:
            registry_path = local_registry
            logging.info("Using local registry: %s", registry_path)
            bsp_mgr = BspManager(registry_path, verbose=args.verbose)
        else:
            from .registry_fetcher import RemoteRegistrySpec
            fetcher = RegistryFetcher()

            # If no --remote flags given on the CLI, fall back to configured
            # remotes — the first configured remote is the default, much like
            # git picks 'origin'.
            if args.remote:
                remotes_raw = args.remote
            else:
                stored = RemotesManager().ensure_default_remote(branch=args.branch)
                # Encode stored remotes as URL@BRANCH@name=NAME strings so the
                # existing parse / fetch_multiple path handles them uniformly.
                remotes_raw = [
                    f"{r.url}@{r.branch}@name={r.name}" for r in stored
                ]
                logging.info(
                    "Using %d configured remote(s): %s",
                    len(stored),
                    [r.name for r in stored],
                )

            # Every remote (explicit or configured) is fetched into its own
            # subdirectory of the cache dir; the cache dir itself is never
            # used as a git repository.
            specs = [RemoteRegistrySpec.parse(r, default_branch=args.branch) for r in remotes_raw]
            registry_pairs = fetcher.fetch_multiple(specs, update=args.update)
            logging.info(
                "Loaded %d remote registries: %s",
                len(registry_pairs),
                [name for name, _ in registry_pairs],
            )
            config_paths = [(name, str(path)) for name, path in registry_pairs]
            bsp_mgr = BspManager(config_paths=config_paths, verbose=args.verbose)

        bsp_mgr.initialize()

        # ----------------------------------------------------------------
        # Dispatch commands
        # ----------------------------------------------------------------
        def _check_exclusive(bsp_name, device, release, parser):
            """Return True and log error if bsp_name and device/release are both set."""
            if bsp_name and (device or release):
                logging.error(
                    "Cannot mix a positional preset name with --device/--release. "
                    "Use either '<command> <preset>' or "
                    "'<command> --device <d> --release <r>'."
                )
                return True
            return False

        if args.command == "build":
            checkout_only = getattr(args, "checkout", False)
            device = getattr(args, "device", None)
            release = getattr(args, "release", None)
            features = getattr(args, "features", None) or []
            bsp_name = getattr(args, "bsp_name", None)
            deploy_after_build = getattr(args, "deploy_after_build", False)
            deploy_overrides = _collect_deploy_overrides(args)
            update_index = getattr(args, "update_index", None)
            run_test = getattr(args, "run_test", False)
            scan_after_build = getattr(args, "scan_after_build", False)
            scan_overrides = _collect_scan_overrides(args)
            flash_target = getattr(args, "flash_target", None)
            flash_after_build = flash_target is not None
            flash_overrides = _collect_flash_overrides(args)
            wait = getattr(args, "wait", False)
            lava_server = getattr(args, "lava_server", None)
            lava_token = getattr(args, "lava_token", None)
            artifact_url = getattr(args, "artifact_url", None)
            target = getattr(args, "target", None)
            task = getattr(args, "task", None)
            build_path = getattr(args, "build_path", None)
            vendor_release = getattr(args, "vendor_release", None)
            override_slug = getattr(args, "override_slug", None)
            docker_build_options = getattr(args, "docker_build_options", None)
            no_cache = getattr(args, "no_cache", False)
            if no_cache:
                docker_build_options = BspManager._compose_docker_build_options(
                    docker_build_options, use_cache=False
                )

            if _check_exclusive(bsp_name, device, release, build_parser):
                return 1
            if bsp_name:
                bsp_mgr.build_bsp(
                    bsp_name,
                    checkout_only=checkout_only,
                    deploy_after_build=deploy_after_build,
                    deploy_overrides=deploy_overrides,
                    target=target,
                    task=task,
                    build_path_override=build_path,
                    feature_slugs=features,
                    scan_after_build=scan_after_build,
                    scan_overrides=scan_overrides,
                    flash_after_build=flash_after_build,
                    flash_target=flash_target,
                    flash_overrides=flash_overrides,
                    vendor_release_slug=vendor_release,
                    override_slug=override_slug,
                    docker_build_options=docker_build_options,
                    update_index=update_index,
                )
                if run_test:
                    passed = bsp_mgr.test_bsp(
                        bsp_name,
                        lava_server=lava_server,
                        lava_token=lava_token,
                        artifact_url=artifact_url,
                        wait=wait,
                        backend="lava",
                    )
                    if not passed:
                        return 1
            elif device and release:
                bsp_mgr.build_by_components(
                    device, release, features,
                    checkout_only=checkout_only,
                    deploy_after_build=deploy_after_build,
                    deploy_overrides=deploy_overrides,
                    target=target,
                    task=task,
                    build_path_override=build_path,
                    scan_after_build=scan_after_build,
                    scan_overrides=scan_overrides,
                    flash_after_build=flash_after_build,
                    flash_target=flash_target,
                    flash_overrides=flash_overrides,
                    vendor_release_slug=vendor_release,
                    override_slug=override_slug,
                    docker_build_options=docker_build_options,
                    update_index=update_index,
                )
                if run_test:
                    passed = bsp_mgr.test_by_components(
                        device,
                        release,
                        features,
                        lava_server=lava_server,
                        lava_token=lava_token,
                        artifact_url=artifact_url,
                        wait=wait,
                        backend="lava",
                    )
                    if not passed:
                        return 1
            else:
                logging.error(
                    "Specify either a BSP preset name or both --device and --release."
                )
                build_parser.print_help()
                return 1

        elif args.command == "fetch":
            device = getattr(args, "device", None)
            release = getattr(args, "release", None)
            features = getattr(args, "features", None) or []
            bsp_name = getattr(args, "bsp_name", None)
            target = getattr(args, "target", None)
            build_path = getattr(args, "build_path", None)
            vendor_release = getattr(args, "vendor_release", None)
            override_slug = getattr(args, "override_slug", None)

            if _check_exclusive(bsp_name, device, release, fetch_parser):
                return 1
            if bsp_name:
                bsp_mgr.fetch_bsp(
                    bsp_name,
                    target=target,
                    build_path_override=build_path,
                    feature_slugs=features,
                    vendor_release_slug=vendor_release,
                    override_slug=override_slug,
                )
            elif device and release:
                bsp_mgr.fetch_by_components(
                    device,
                    release,
                    features,
                    target=target,
                    build_path_override=build_path,
                    vendor_release_slug=vendor_release,
                    override_slug=override_slug,
                )
            else:
                logging.error(
                    "Specify either a BSP preset name or both --device and --release."
                )
                fetch_parser.print_help()
                return 1

        elif args.command == "list":
            list_type = getattr(args, "list_type", None)
            device = getattr(args, "device", None)
            registry_filter = getattr(args, "filter_remote", None)
            use_color = not args.no_color
            if list_type == "devices":
                bsp_mgr.list_devices(use_color=use_color, registry_filter=registry_filter)
            elif list_type == "releases":
                bsp_mgr.list_releases(device_slug=device, use_color=use_color, registry_filter=registry_filter)
            elif list_type == "features":
                bsp_mgr.list_features(use_color=use_color, registry_filter=registry_filter)
            elif list_type == "distros":
                bsp_mgr.list_distros(use_color=use_color, registry_filter=registry_filter)
            else:
                bsp_mgr.list_bsp(use_color=use_color, registry_filter=registry_filter)

        elif args.command == "containers":
            action = getattr(args, "containers_action", "list")
            if action == "build":
                bsp_mgr.build_containers(
                    container_name=getattr(args, "container_name", None),
                    no_cache=getattr(args, "no_cache", False),
                )
            else:
                bsp_mgr.list_containers(use_color=not args.no_color)

        elif args.command == "tree":
            full = getattr(args, "full", False)
            compact = getattr(args, "compact", False)
            mode = "full" if full else ("compact" if compact else "default")
            registry_filter = getattr(args, "filter_remote", None)
            bsp_mgr.tree_bsp(use_color=not args.no_color, mode=mode, registry_filter=registry_filter)

        elif args.command == "export":
            device = getattr(args, "device", None)
            release = getattr(args, "release", None)
            features = getattr(args, "features", None) or []
            bsp_name = getattr(args, "bsp_name", None)
            output = getattr(args, "output", None)
            repo_manifest = getattr(args, "repo_manifest", False)
            lock = getattr(args, "lock", False)

            if _check_exclusive(bsp_name, device, release, export_parser):
                return 1
            if bsp_name:
                bsp_mgr.export_bsp_config(
                    bsp_name=bsp_name,
                    output_file=output,
                    repo_manifest=repo_manifest,
                    lock=lock,
                )
            elif device and release:
                bsp_mgr.export_by_components(
                    device,
                    release,
                    features,
                    output_file=output,
                    repo_manifest=repo_manifest,
                    lock=lock,
                )
            else:
                logging.error(
                    "Specify either a BSP preset name or both --device and --release."
                )
                export_parser.print_help()
                return 1

        elif args.command == "server":
            try:
                import uvicorn
                from .server import create_app
            except ImportError:
                logging.error(
                    "Server dependencies are not installed. "
                    "Install them with: pip install bsp-registry-tools[server]"
                )
                return 1

            app = create_app(manager=bsp_mgr)
            uvicorn.run(
                app,
                host=args.host,
                port=args.port,
                reload=args.reload,
            )
            return 0

        elif args.command == "shell":
            shell_command = getattr(args, "shell_command", None)
            device = getattr(args, "device", None)
            release = getattr(args, "release", None)
            features = getattr(args, "features", None) or []
            bsp_name = getattr(args, "bsp_name", None)
            build_path = getattr(args, "build_path", None)

            if _check_exclusive(bsp_name, device, release, shell_parser):
                return 1
            if bsp_name:
                bsp_mgr.shell_into_bsp(
                    bsp_name=bsp_name,
                    command=shell_command,
                    build_path_override=build_path,
                )
            elif device and release:
                bsp_mgr.shell_by_components(
                    device, release, features,
                    command=shell_command,
                    build_path_override=build_path,
                )
            else:
                logging.error(
                    "Specify either a BSP preset name or both --device and --release."
                )
                shell_parser.print_help()
                return 1

        elif args.command == "deploy":
            device = getattr(args, "device", None)
            release = getattr(args, "release", None)
            features = getattr(args, "features", None) or []
            bsp_name = getattr(args, "bsp_name", None)
            dry_run = getattr(args, "dry_run", False)
            deploy_overrides = _collect_deploy_overrides(args)
            update_index = getattr(args, "update_index", None)

            if _check_exclusive(bsp_name, device, release, deploy_parser):
                return 1
            if bsp_name:
                bsp_mgr.deploy_bsp(
                    bsp_name,
                    deploy_overrides=deploy_overrides,
                    dry_run=dry_run,
                    update_index=update_index,
                )
            elif device and release:
                bsp_mgr.deploy_by_components(
                    device, release, features,
                    deploy_overrides=deploy_overrides,
                    dry_run=dry_run,
                    update_index=update_index,
                )
            else:
                logging.error(
                    "Specify either a BSP preset name or both --device and --release."
                )
                deploy_parser.print_help()
                return 1

        elif args.command == "index":
            return _run_index_command(args, bsp_mgr)

        elif args.command == "gather":
            device = getattr(args, "device", None)
            release = getattr(args, "release", None)
            features = getattr(args, "features", None) or []
            bsp_name = getattr(args, "bsp_name", None)
            dest_dir = getattr(args, "dest_dir", None)
            dry_run = getattr(args, "dry_run", False)
            date_override = getattr(args, "gather_date", None)
            gather_cache = getattr(args, "gather_cache", False)
            cache_downloads_dest = getattr(args, "cache_downloads_dest", None)
            cache_sstate_dest = getattr(args, "cache_sstate_dest", None)
            gather_overrides = _collect_gather_overrides(args)

            if _check_exclusive(bsp_name, device, release, gather_parser):
                return 1
            if bsp_name:
                bsp_mgr.gather_bsp(
                    bsp_name,
                    dest_dir=dest_dir,
                    deploy_overrides=gather_overrides,
                    dry_run=dry_run,
                    date_override=date_override,
                    gather_cache=gather_cache,
                    cache_downloads_dest=cache_downloads_dest,
                    cache_sstate_dest=cache_sstate_dest,
                )
            elif device and release:
                bsp_mgr.gather_by_components(
                    device, release, features,
                    dest_dir=dest_dir,
                    deploy_overrides=gather_overrides,
                    dry_run=dry_run,
                    date_override=date_override,
                    gather_cache=gather_cache,
                    cache_downloads_dest=cache_downloads_dest,
                    cache_sstate_dest=cache_sstate_dest,
                )
            else:
                logging.error(
                    "Specify either a BSP preset name or both --device and --release."
                )
                gather_parser.print_help()
                return 1

        elif args.command == "scan":
            device = getattr(args, "device", None)
            release = getattr(args, "release", None)
            features = getattr(args, "features", None) or []
            bsp_name = getattr(args, "bsp_name", None)
            dry_run = getattr(args, "dry_run", False)
            scan_overrides = _collect_scan_overrides(args)
            image_paths = getattr(args, "scan_image_paths", None)

            if _check_exclusive(bsp_name, device, release, scan_parser):
                return 1
            if bsp_name:
                bsp_mgr.scan_bsp(
                    bsp_name,
                    scan_overrides=scan_overrides,
                    dry_run=dry_run,
                    image_paths=image_paths,
                )
            elif device and release:
                bsp_mgr.scan_by_components(
                    device, release, features,
                    scan_overrides=scan_overrides,
                    dry_run=dry_run,
                    image_paths=image_paths,
                )
            else:
                logging.error(
                    "Specify either a BSP preset name or both --device and --release."
                )
                scan_parser.print_help()
                return 1

        elif args.command == "flash":
            device = getattr(args, "device", None)
            release = getattr(args, "release", None)
            features = getattr(args, "features", None) or []
            bsp_name = getattr(args, "bsp_name", None)
            flash_target = getattr(args, "flash_target", None)
            flash_image_path = getattr(args, "flash_image_path", None)
            dry_run = getattr(args, "dry_run", False)
            build_path = getattr(args, "build_path", None)
            flash_overrides = _collect_flash_overrides(args)

            if not dry_run and not flash_target and getattr(args, "flash_tool", None) != "uuu":
                logging.error(
                    "--target / -t is required unless --dry-run is specified or --tool uuu is used."
                )
                flash_parser.print_help()
                return 1

            if _check_exclusive(bsp_name, device, release, flash_parser):
                return 1
            if bsp_name:
                bsp_mgr.flash_bsp(
                    bsp_name,
                    target_device=flash_target or "",
                    flash_overrides=flash_overrides,
                    image_path=flash_image_path,
                    dry_run=dry_run,
                    build_path_override=build_path,
                )
            elif device and release:
                bsp_mgr.flash_by_components(
                    device, release,
                    target_device=flash_target or "",
                    feature_slugs=features,
                    flash_overrides=flash_overrides,
                    image_path=flash_image_path,
                    dry_run=dry_run,
                    build_path_override=build_path,
                )
            else:
                logging.error(
                    "Specify either a BSP preset name or both --device and --release."
                )
                flash_parser.print_help()
                return 1

        elif args.command == "test":
            device = getattr(args, "device", None)
            release = getattr(args, "release", None)
            features = getattr(args, "features", None) or []
            bsp_name = getattr(args, "bsp_name", None)
            wait = getattr(args, "wait", False)
            lava_server = getattr(args, "lava_server", None)
            lava_token = getattr(args, "lava_token", None)
            artifact_url = getattr(args, "artifact_url", None)
            test_backend = getattr(args, "test_backend", None)
            test_repo_url = getattr(args, "test_repo_url", None)
            test_repo_ref = getattr(args, "test_repo_ref", None)
            test_definition_paths = getattr(args, "test_definition_paths", None)
            test_job_paths = getattr(args, "test_job_paths", None)
            test_suites = getattr(args, "test_suites", None)
            test_requirement_catalogs = getattr(args, "test_requirement_catalogs", None)
            show_cases = getattr(args, "show_cases", False)
            direct_timeout = getattr(args, "direct_timeout", None)
            direct_output_dir = getattr(args, "direct_output_dir", None)
            ssh_host = getattr(args, "ssh_host", None)
            ssh_user = getattr(args, "ssh_user", None)
            ssh_port = getattr(args, "ssh_port", None)
            ssh_key = getattr(args, "ssh_key", None)
            ssh_password = getattr(args, "ssh_password", None)
            ssh_known_hosts_file = getattr(args, "ssh_known_hosts_file", None)
            ssh_strict_host_key_checking = getattr(args, "ssh_strict_host_key_checking", None)
            ssh_remote_workdir = getattr(args, "ssh_remote_workdir", None)
            ssh_serial_device = getattr(args, "ssh_serial_device", None)
            ssh_serial_baudrate = getattr(args, "ssh_serial_baudrate", None)
            try:
                test_params = _parse_key_value_params(getattr(args, "test_params", None))
            except ValueError as exc:
                logging.error(str(exc))
                return 1

            if _check_exclusive(bsp_name, device, release, test_parser):
                return 1
            if bsp_name:
                passed = bsp_mgr.test_bsp(
                    bsp_name,
                    lava_server=lava_server,
                    lava_token=lava_token,
                    artifact_url=artifact_url,
                    wait=wait,
                    backend=test_backend,
                    test_repo_url=test_repo_url,
                    test_repo_ref=test_repo_ref,
                    test_definition_paths=test_definition_paths,
                    test_job_paths=test_job_paths,
                    test_suites=test_suites,
                    test_requirement_catalogs=test_requirement_catalogs,
                    test_params=test_params,
                    direct_timeout=direct_timeout,
                    direct_output_dir=direct_output_dir,
                    ssh_host=ssh_host,
                    ssh_user=ssh_user,
                    ssh_port=ssh_port,
                    ssh_key=ssh_key,
                    ssh_password=ssh_password,
                    ssh_known_hosts_file=ssh_known_hosts_file,
                    ssh_strict_host_key_checking=ssh_strict_host_key_checking,
                    ssh_remote_workdir=ssh_remote_workdir,
                    ssh_serial_device=ssh_serial_device,
                    ssh_serial_baudrate=ssh_serial_baudrate,
                    show_cases=show_cases,
                )
            elif device and release:
                passed = bsp_mgr.test_by_components(
                    device,
                    release,
                    features,
                    lava_server=lava_server,
                    lava_token=lava_token,
                    artifact_url=artifact_url,
                    wait=wait,
                    backend=test_backend,
                    test_repo_url=test_repo_url,
                    test_repo_ref=test_repo_ref,
                    test_definition_paths=test_definition_paths,
                    test_job_paths=test_job_paths,
                    test_suites=test_suites,
                    test_requirement_catalogs=test_requirement_catalogs,
                    test_params=test_params,
                    direct_timeout=direct_timeout,
                    direct_output_dir=direct_output_dir,
                    ssh_host=ssh_host,
                    ssh_user=ssh_user,
                    ssh_port=ssh_port,
                    ssh_key=ssh_key,
                    ssh_password=ssh_password,
                    ssh_known_hosts_file=ssh_known_hosts_file,
                    ssh_strict_host_key_checking=ssh_strict_host_key_checking,
                    ssh_remote_workdir=ssh_remote_workdir,
                    ssh_serial_device=ssh_serial_device,
                    ssh_serial_baudrate=ssh_serial_baudrate,
                    show_cases=show_cases,
                )
            else:
                logging.error(
                    "Specify either a BSP preset name or both --device and --release."
                )
                test_parser.print_help()
                return 1
            if not passed:
                return 1

        else:
            logging.error(f"Unknown command: {args.command}")
            parser.print_help()
            return 1

        bsp_mgr.cleanup()
        logging.info("Command completed successfully")
        return 0

    except KeyboardInterrupt:
        logging.info("BSP manager interrupted by user")
        return 130  # Standard exit code for SIGINT
    except SystemExit as e:
        # Re-raise system exit with proper code
        return e.code if isinstance(e.code, int) else 1
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        return 1
