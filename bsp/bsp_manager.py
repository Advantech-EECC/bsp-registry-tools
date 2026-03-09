"""
Main BSP management class coordinating registry, builds, and exports.
"""

import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

from .environment import EnvironmentManager
from .kas_manager import KasManager
from .models import BspPreset, Docker, EnvironmentVariable
from .path_resolver import resolver
from .resolver import ResolvedConfig, V2Resolver
from .utils import get_registry_from_yaml_file, build_docker

# =============================================================================
# Main BSP Management Class with v2.0 Support
# =============================================================================


class BspManager:
    """
    Main BSP management class for BSP registry management (v2.0 schema).

    This class coordinates the overall BSP management flow including
    configuration loading, device/release/feature discovery, build execution,
    shell access, and configuration export operations with container support.
    """

    def __init__(self, config_path: str = "bsp-registry.yaml"):
        """
        Initialize BSP manager.

        Args:
            config_path: Path to BSP registry configuration file
        """
        self.config_path = Path(config_path)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.model = None  # Will hold parsed registry configuration
        self.env_manager = None  # Environment configuration manager
        self.containers = {}  # Dictionary of container configurations
        self.resolver = None  # V2Resolver instance

    def load_configuration(self) -> None:
        """
        Load and parse BSP configuration from YAML file.

        Raises:
            SystemExit: If configuration file is missing, invalid, or not v2.0
        """
        try:
            if not self.config_path.exists():
                logging.error(f"Config file not found: {self.config_path}")
                sys.exit(1)

            # Parse YAML configuration into structured model
            self.model = get_registry_from_yaml_file(self.config_path)
            logging.info(f"Configuration loaded successfully from {self.config_path}")

            # Store containers from model
            if self.model.containers:
                self.containers = self.model.containers
                logging.info(f"Loaded {len(self.containers)} container definitions")

            # Initialize Environment manager if configuration exists
            if self.model.environment:
                self.env_manager = EnvironmentManager(self.model.environment)
                logging.info(
                    f"Environment configuration initialized with "
                    f"{len(self.model.environment)} variables"
                )

        except SystemExit:
            raise
        except Exception as e:
            logging.error(f"Failed to load configuration: {e}")
            sys.exit(1)

    def initialize(self) -> None:
        """Initialize BSP manager components and validate configuration."""
        logging.info("Initializing BSP manager...")
        self.load_configuration()

        # Create v2 resolver
        self.resolver = V2Resolver(self.model, self.containers)

        # Validate environment configuration if present
        if self.env_manager:
            if not self.env_manager.validate_environment():
                logging.error("Environment configuration validation failed")
                sys.exit(1)

        logging.info("BSP manager initialized successfully")

    # ------------------------------------------------------------------
    # Listing commands
    # ------------------------------------------------------------------

    def list_bsp(self) -> None:
        """
        List all BSP presets defined in the registry.

        In v2, presets are optional shortcuts. If no presets are defined,
        a helpful message is shown instead of exiting with an error.
        """
        presets = self.model.registry.bsp if self.model else []
        if not presets:
            print("No BSP presets defined in registry")
            print(
                "Use 'bsp list devices', 'bsp list releases', or "
                "'bsp list features' to see available components."
            )
            return

        print("Available BSP presets:")
        for preset in presets:
            features_str = (
                f", features: {', '.join(preset.features)}" if preset.features else ""
            )
            print(
                f"- {preset.name}: {preset.description} "
                f"(device: {preset.device}, release: {preset.release}{features_str})"
            )

    def list_devices(self) -> None:
        """List all hardware devices defined in the registry."""
        devices = self.model.registry.devices if self.model else []
        if not devices:
            print("No devices found in registry")
            return

        print("Available devices:")
        for device in devices:
            soc_family = (
                f", soc_family: {device.soc_family}" if device.soc_family else ""
            )
            print(
                f"- {device.slug}: {device.description} "
                f"(vendor: {device.vendor}, soc_vendor: {device.soc_vendor}{soc_family})"
            )

    def list_releases(self, device_slug: Optional[str] = None) -> None:
        """
        List all release definitions in the registry.

        Args:
            device_slug: If provided, filter releases to those compatible with
                         the device's vendor (via vendor_includes). When omitted,
                         all releases are shown.
        """
        releases = self.model.registry.releases if self.model else []
        if not releases:
            print("No releases found in registry")
            return

        if device_slug:
            # Validate the device exists (exits on failure)
            device = self.resolver.get_device(device_slug)
            print(f"Releases compatible with device '{device_slug}':")
        else:
            print("Available releases:")
            device = None

        for release in releases:
            yocto = f" [Yocto {release.yocto_version}]" if release.yocto_version else ""
            isar = f" [Isar {release.isar_version}]" if release.isar_version else ""
            vendors = [vi.vendor for vi in release.vendor_includes]
            vendor_str = f", vendor overrides: {', '.join(vendors)}" if vendors else ""
            env_str = f", environment: {release.environment}" if release.environment else ""
            print(
                f"- {release.slug}: {release.description}{yocto}{isar}{vendor_str}{env_str}"
            )

    def list_features(self) -> None:
        """List all feature definitions in the registry."""
        features = self.model.registry.features if self.model else []
        if not features:
            print("No features found in registry")
            return

        print("Available features:")
        for feature in features:
            compat = ""
            if feature.compatibility:
                parts = []
                if feature.compatibility.vendor:
                    parts.append(f"vendor: {feature.compatibility.vendor}")
                if feature.compatibility.soc_vendor:
                    parts.append(f"soc_vendor: {feature.compatibility.soc_vendor}")
                if feature.compatibility.soc_family:
                    parts.append(f"soc_family: {feature.compatibility.soc_family}")
                if parts:
                    compat = f" [requires {', '.join(parts)}]"
            print(f"- {feature.slug}: {feature.description}{compat}")

    def list_containers(self) -> None:
        """List all available containers in the registry."""
        if not self.containers:
            print("No container definitions found in registry")
            return

        print("Available Containers:")
        for container_name, container_config in self.containers.items():
            print(f"- {container_name}:")
            print(f"    Image: {container_config.image}")
            print(f"    File: {container_config.file}")
            if container_config.args:
                print(
                    f"    Args: "
                    f"{', '.join([f'{arg.name}={arg.value}' for arg in container_config.args])}"
                )

    # ------------------------------------------------------------------
    # Preset lookup
    # ------------------------------------------------------------------

    def get_bsp_by_name(self, bsp_name: str) -> BspPreset:
        """
        Retrieve a BSP preset configuration by name.

        Args:
            bsp_name: Name of the preset to retrieve

        Returns:
            BspPreset configuration object

        Raises:
            SystemExit: If preset with given name is not found
        """
        for preset in self.model.registry.bsp or []:
            if preset.name == bsp_name:
                return preset

        logging.error(f"BSP preset not found: '{bsp_name}'")
        available = [p.name for p in (self.model.registry.bsp or [])]
        print("Available presets: " + (", ".join(available) or "(none)"))
        sys.exit(1)

    # ------------------------------------------------------------------
    # Build directory helpers
    # ------------------------------------------------------------------

    def prepare_build_directory(self, build_path: str) -> None:
        """
        Prepare build directory, creating it if necessary.

        Args:
            build_path: Path to build directory

        Raises:
            SystemExit: If directory cannot be created
        """
        logging.info(f"Preparing build directory: {build_path}")
        resolver.ensure_directory(build_path)

    def _copy_files(self, resolved: ResolvedConfig) -> None:
        """
        Copy files specified in ``device.build.copy`` into their destinations.

        Each entry in ``resolved.copy`` is a single-key dict mapping a source
        path to a destination path.  Both paths are resolved relative to the
        registry file's parent directory.  If the destination ends with ``/``
        or is an existing directory the source filename is preserved inside it.

        Args:
            resolved: Resolved build configuration containing copy entries.

        Raises:
            SystemExit: If a source file does not exist.
        """
        if not resolved.copy:
            return

        base = self.config_path.parent
        for copy_entry in resolved.copy:
            for src, dst in copy_entry.items():
                src_path = Path(src)
                if not src_path.is_absolute():
                    src_path = (base / src_path).resolve()

                if not src_path.exists():
                    self.logger.error(
                        f"Copy source file not found: {src_path}"
                    )
                    sys.exit(1)

                dst_path = Path(dst)
                if not dst_path.is_absolute():
                    dst_path = (base / dst_path).resolve()

                # If destination looks like a directory (trailing slash or
                # already is one), place the file inside it.
                if str(dst).endswith("/") or dst_path.is_dir():
                    dst_path = dst_path / src_path.name

                dst_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(str(src_path), str(dst_path))
                except OSError as e:
                    self.logger.error(
                        f"Failed to copy '{src_path}' to '{dst_path}': {e}"
                    )
                    sys.exit(1)
                self.logger.info(f"Copied {src_path} -> {dst_path}")

    # ------------------------------------------------------------------
    # Internal: KasManager factory for a resolved config
    # ------------------------------------------------------------------

    def _get_kas_manager_for_resolved(
        self,
        resolved: ResolvedConfig,
        use_container: bool = True,
    ) -> KasManager:
        """
        Create a KasManager for the given ResolvedConfig.

        If the resolved config includes local_conf additions, a temporary
        KAS YAML file is generated to carry those into the build.  The
        caller is responsible for deleting the temp file when done.

        Environment variables are merged in this order (later entries win):
        1. Root-level ``environment`` list (global defaults)
        2. Named environment variables from ``resolved.env``

        Args:
            resolved: Resolved device+release+features build config
            use_container: Whether to use containerized KAS

        Returns:
            Configured KasManager instance
        """
        # Build per-build EnvironmentManager: root vars merged with
        # named-env / feature vars from the resolved config.
        root_vars: List[EnvironmentVariable] = (
            list(self.model.environment) if self.model.environment else []
        )
        # resolved.env contains named-env vars first, then feature vars.
        # Merge by appending; later keys win in EnvironmentManager.
        merged_vars = root_vars + list(resolved.env)
        # Always create a fresh EnvironmentManager from merged vars so that
        # named-env and feature variables are applied for this specific build.
        # Fall back to the global env_manager only when no vars exist at all.
        env_mgr = EnvironmentManager(merged_vars) if merged_vars else self.env_manager

        downloads = env_mgr.get_value("DL_DIR") if env_mgr else None
        sstate = env_mgr.get_value("SSTATE_DIR") if env_mgr else None

        if downloads:
            resolver.ensure_directory(downloads)
        if sstate:
            resolver.ensure_directory(sstate)

        # Determine KAS file list: generate a composed YAML when we have
        # local_conf additions so that everything is in a single entry-point.
        if resolved.local_conf:
            temp_fd, temp_path = tempfile.mkstemp(
                prefix="bsp_composed_", suffix=".yml"
            )
            os.close(temp_fd)
            self._resolver_ref = self.resolver  # keep a ref
            self.resolver.generate_kas_yaml(
                resolved,
                temp_path,
                base_dir=str(self.config_path.parent),
            )
            kas_files = [temp_path]
            self._temp_kas_file = temp_path
        else:
            # Resolve relative paths against the registry directory
            base = self.config_path.parent
            kas_files = []
            for f in resolved.kas_files:
                p = Path(f)
                if p.is_absolute():
                    kas_files.append(str(p))
                else:
                    kas_files.append(str((base / p).resolve()))
            self._temp_kas_file = None

        container_image = (
            resolved.container.image
            if resolved.container and use_container
            else None
        )
        container_runtime_args = (
            resolved.container.runtime_args
            if resolved.container and use_container
            else None
        )

        kas_mgr = KasManager(
            kas_files,
            resolved.build_path,
            download_dir=downloads,
            sstate_dir=sstate,
            use_container=use_container,
            container_image=container_image,
            container_runtime_args=container_runtime_args,
            container_privileged=(
                resolved.container.privileged if resolved.container and use_container else False
            ),
            search_paths=[str(self.config_path.parent)],
            env_manager=env_mgr,
        )
        return kas_mgr

    def _cleanup_temp_kas_file(self) -> None:
        """Remove the temporary KAS YAML file if one was created."""
        temp_file = getattr(self, "_temp_kas_file", None)
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
                logging.debug(f"Removed temporary KAS file: {temp_file}")
            except OSError as e:
                logging.warning(f"Could not remove temporary KAS file: {e}")
        self._temp_kas_file = None

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_resolved(
        self,
        resolved: ResolvedConfig,
        checkout_only: bool = False,
        label: str = "",
    ) -> None:
        """
        Execute a build (or checkout) for the given ResolvedConfig.

        Args:
            resolved: Resolved build configuration
            checkout_only: If True, only checkout and validate without building
            label: Descriptive label for log messages
        """
        action = "Checking out" if checkout_only else "Building"
        logging.info(f"{action} {label or resolved.device.slug}")

        # Build Docker image if needed (skip in checkout mode)
        if not checkout_only and resolved.container:
            container = resolved.container
            if container.file and container.image:
                build_docker(str(self.config_path.parent), container.file, container.image, container.args)
        else:
            if checkout_only:
                logging.info("Skipping Docker build in checkout mode")

        self.prepare_build_directory(resolved.build_path)
        self._copy_files(resolved)

        kas_mgr = self._get_kas_manager_for_resolved(
            resolved, use_container=not checkout_only
        )

        try:
            config_output = kas_mgr.dump_config(show_output=False)
            if config_output:
                logging.debug("Configuration dump:\n" + config_output)

            if checkout_only:
                logging.info("Performing checkout and validation (no build)...")
                kas_mgr.checkout_project()
                logging.info(f"Checkout and validation completed successfully!")
            else:
                kas_mgr.build_project()
                logging.info(f"Build completed successfully!")
        finally:
            self._cleanup_temp_kas_file()

    def build_bsp(self, bsp_name: str, checkout_only: bool = False) -> None:
        """
        Build a BSP by preset name.

        Args:
            bsp_name: Name of the BSP preset to build
            checkout_only: If True, only checkout and validate without building

        Raises:
            SystemExit: If preset not found or build fails
        """
        logging.info(f"{'Checking out' if checkout_only else 'Building'} BSP preset: {bsp_name}")
        resolved, preset = self.resolver.resolve_preset(bsp_name)
        self._build_resolved(
            resolved,
            checkout_only=checkout_only,
            label=f"{preset.name} - {preset.description}",
        )

    def build_by_components(
        self,
        device_slug: str,
        release_slug: str,
        feature_slugs: Optional[List[str]] = None,
        checkout_only: bool = False,
    ) -> None:
        """
        Build by specifying device, release, and optional features directly.

        Args:
            device_slug: Device slug
            release_slug: Release slug
            feature_slugs: Optional list of feature slugs to enable
            checkout_only: If True, only checkout and validate without building

        Raises:
            SystemExit: If any component is not found, incompatible, or build fails
        """
        logging.info(
            f"{'Checking out' if checkout_only else 'Building'} "
            f"device={device_slug} release={release_slug} "
            f"features={feature_slugs or []}"
        )
        resolved = self.resolver.resolve(device_slug, release_slug, feature_slugs)
        self._build_resolved(
            resolved,
            checkout_only=checkout_only,
            label=f"{device_slug}/{release_slug}",
        )

    # ------------------------------------------------------------------
    # Shell
    # ------------------------------------------------------------------

    def _shell_resolved(
        self,
        resolved: ResolvedConfig,
        command: Optional[str] = None,
        label: str = "",
    ) -> None:
        """
        Start a KAS shell session for the given ResolvedConfig.

        Args:
            resolved: Resolved build configuration
            command: Optional command to run in the shell
            label: Descriptive label for log messages
        """
        logging.info(f"Starting shell for {label or resolved.device.slug}")

        if resolved.container:
            container = resolved.container
            if container.file and container.image:
                logging.info("Building Docker image for shell environment...")
                build_docker(str(self.config_path.parent), container.file, container.image, container.args)

        self.prepare_build_directory(resolved.build_path)

        kas_mgr = self._get_kas_manager_for_resolved(resolved, use_container=True)

        try:
            if command:
                logging.info(f"Executing command: {command}")
            else:
                logging.info("Starting interactive KAS shell session...")
                logging.info("Use 'Ctrl+D' or type 'exit' to leave the shell.")
            kas_mgr.shell_session(command=command)
        finally:
            self._cleanup_temp_kas_file()

    def shell_into_bsp(self, bsp_name: str, command: Optional[str] = None) -> None:
        """
        Enter interactive shell for a BSP preset.

        Args:
            bsp_name: Name of the BSP preset
            command: Optional command to execute in the shell

        Raises:
            SystemExit: If preset not found or shell fails
        """
        logging.info(f"Entering shell for BSP preset: {bsp_name}")
        resolved, preset = self.resolver.resolve_preset(bsp_name)
        self._shell_resolved(
            resolved, command=command, label=f"{preset.name} - {preset.description}"
        )

    def shell_by_components(
        self,
        device_slug: str,
        release_slug: str,
        feature_slugs: Optional[List[str]] = None,
        command: Optional[str] = None,
    ) -> None:
        """
        Enter interactive shell by specifying device, release, and features directly.

        Args:
            device_slug: Device slug
            release_slug: Release slug
            feature_slugs: Optional list of feature slugs
            command: Optional command to execute in the shell

        Raises:
            SystemExit: If any component is not found or shell fails
        """
        logging.info(
            f"Entering shell for device={device_slug} release={release_slug} "
            f"features={feature_slugs or []}"
        )
        resolved = self.resolver.resolve(device_slug, release_slug, feature_slugs)
        self._shell_resolved(
            resolved, command=command, label=f"{device_slug}/{release_slug}"
        )

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export_resolved(
        self,
        resolved: ResolvedConfig,
        output_file: Optional[str] = None,
        label: str = "",
    ) -> None:
        """
        Export KAS configuration for the given ResolvedConfig.

        Args:
            resolved: Resolved build configuration
            output_file: Optional file path to save the configuration
            label: Descriptive label for log messages
        """
        logging.info(f"Exporting KAS configuration for {label or resolved.device.slug}")

        downloads = None
        sstate = None
        if self.env_manager:
            downloads = self.env_manager.get_value("DL_DIR")
            sstate = self.env_manager.get_value("SSTATE_DIR")

        # Use a temporary build directory for export
        with tempfile.TemporaryDirectory(prefix="bsp_export_") as temp_dir:
            if resolved.local_conf:
                temp_fd, temp_path = tempfile.mkstemp(
                    prefix="bsp_composed_", suffix=".yml"
                )
                os.close(temp_fd)
                self.resolver.generate_kas_yaml(
                    resolved,
                    temp_path,
                    base_dir=str(self.config_path.parent),
                )
                kas_files = [temp_path]
            else:
                base = self.config_path.parent
                kas_files = []
                for f in resolved.kas_files:
                    p = Path(f)
                    if p.is_absolute():
                        kas_files.append(str(p))
                    else:
                        kas_files.append(str((base / p).resolve()))
                temp_path = None

            try:
                kas_mgr = KasManager(
                    kas_files,
                    temp_dir,
                    download_dir=downloads,
                    sstate_dir=sstate,
                    use_container=False,
                    search_paths=[str(self.config_path.parent)],
                    env_manager=self.env_manager,
                )
                config_yaml = kas_mgr.export_kas_config(output_file)
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)

        if not output_file:
            print("\n" + "=" * 60)
            print(f"KAS Configuration for {label or resolved.device.slug}")
            print("=" * 60)
            print(config_yaml)
            print("=" * 60)

        logging.info("Configuration exported successfully!")

    def export_bsp_config(
        self, bsp_name: str, output_file: Optional[str] = None
    ) -> None:
        """
        Export KAS configuration for a BSP preset.

        Args:
            bsp_name: Name of the BSP preset to export
            output_file: Optional file path to save the configuration

        Raises:
            SystemExit: If preset not found or export fails
        """
        logging.info(f"Exporting KAS configuration for BSP preset: {bsp_name}")
        resolved, preset = self.resolver.resolve_preset(bsp_name)
        self._export_resolved(
            resolved,
            output_file=output_file,
            label=f"{preset.name} - {preset.description}",
        )

    def export_by_components(
        self,
        device_slug: str,
        release_slug: str,
        feature_slugs: Optional[List[str]] = None,
        output_file: Optional[str] = None,
    ) -> None:
        """
        Export KAS configuration by specifying device, release, and features directly.

        Args:
            device_slug: Device slug
            release_slug: Release slug
            feature_slugs: Optional list of feature slugs
            output_file: Optional file path to save the configuration

        Raises:
            SystemExit: If any component is not found or export fails
        """
        logging.info(
            f"Exporting configuration for device={device_slug} release={release_slug} "
            f"features={feature_slugs or []}"
        )
        resolved = self.resolver.resolve(device_slug, release_slug, feature_slugs)
        self._export_resolved(
            resolved,
            output_file=output_file,
            label=f"{device_slug}/{release_slug}",
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Cleanup resources and perform any necessary finalization."""
        logging.debug("Cleaning up resources...")
        self._cleanup_temp_kas_file()
