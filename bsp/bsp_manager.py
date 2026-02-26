"""
Main BSP management class coordinating registry, builds, and exports.
"""

import logging
import sys
import tempfile
from pathlib import Path
from typing import Optional

from .environment import EnvironmentManager
from .kas_manager import KasManager
from .models import BSP, Docker
from .path_resolver import resolver
from .utils import get_registry_from_yaml_file, build_docker

# =============================================================================
# Main BSP Management Class with Container Support
# =============================================================================


class BspManager:
    """
    Main BSP management class for BSP registry management.

    This class coordinates the overall BSP management flow including
    configuration loading, BSP discovery, build execution, shell access,
    and configuration export operations with container support.
    """

    def __init__(self, config_path: str = "bsp-registry.yml"):
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

    def load_configuration(self) -> None:
        """
        Load and parse BSP configuration from YAML file.

        Raises:
            SystemExit: If configuration file is missing or invalid
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
                logging.info(f"Environment configuration initialized with {len(self.model.environment)} variables")

        except SystemExit:
            raise
        except Exception as e:
            logging.error(f"Failed to load configuration: {e}")
            sys.exit(1)

    def initialize(self) -> None:
        """Initialize BSP manager components and validate configuration."""
        logging.info("Initializing BSP manager...")
        self.load_configuration()

        # Validate environment configuration if present
        if self.env_manager:
            if not self.env_manager.validate_environment():
                logging.error("Environment configuration validation failed")
                sys.exit(1)

        logging.info("BSP manager initialized successfully")

    def list_bsp(self) -> None:
        """
        List all available BSPs in the registry.

        Raises:
            SystemExit: If no BSPs are found in registry
        """
        if not self.model or not self.model.registry.bsp:
            logging.error("No BSPs found in registry")
            sys.exit(1)

        logging.info("Available BSPs:")
        for bsp in self.model.registry.bsp:
            print(f"- {bsp.name}: {bsp.description}")

    def list_containers(self) -> None:
        """
        List all available containers in the registry.

        Raises:
            SystemExit: If no containers are found in registry
        """
        if not self.containers:
            logging.info("No container definitions found in registry")
            return

        logging.info("Available Containers:")
        for container_name, container_config in self.containers.items():
            print(f"- {container_name}:")
            print(f"    Image: {container_config.image}")
            print(f"    File: {container_config.file}")
            if container_config.args:
                print(f"    Args: {', '.join([f'{arg.name}={arg.value}' for arg in container_config.args])}")

    def get_bsp_by_name(self, bsp_name: str) -> BSP:
        """
        Retrieve BSP configuration by name.

        Args:
            bsp_name: Name of the BSP to retrieve

        Returns:
            BSP configuration object

        Raises:
            SystemExit: If BSP with given name is not found
        """
        for bsp in self.model.registry.bsp:
            if bsp.name == bsp_name:
                return bsp

        # BSP not found - show error with available options
        logging.error(f"BSP not found: {bsp_name}")
        logging.info("Available BSPs:")
        for bsp in self.model.registry.bsp:
            logging.info(f"  - {bsp.name}")
        sys.exit(1)

    def get_container_config_for_bsp(self, bsp: BSP) -> Docker:
        """
        Get the Docker configuration for a BSP, resolving container references.

        This method supports both direct Docker configuration and container references.
        Priority: container reference > direct Docker configuration.

        Args:
            bsp: BSP configuration object

        Returns:
            Docker configuration for the BSP

        Raises:
            SystemExit: If container reference cannot be resolved or configuration is missing
        """
        build_env = bsp.build.environment

        # First check for container reference
        if build_env.container:
            container_name = build_env.container
            if container_name in self.containers:
                logging.info(f"Using container reference: {container_name}")
                return self.containers[container_name]
            else:
                logging.error(f"Container '{container_name}' not found in registry containers")
                logging.info("Available containers:")
                for name in self.containers.keys():
                    logging.info(f"  - {name}")
                sys.exit(1)

        # Fall back to direct Docker configuration
        elif build_env.docker:
            logging.info("Using direct Docker configuration")
            return build_env.docker

        # No container configuration found
        else:
            logging.error(f"No container configuration found for BSP {bsp.name}")
            logging.info("Either specify 'container' to reference a registry container or provide 'docker' configuration")
            sys.exit(1)

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

    def _get_kas_manager_for_bsp(self, bsp: BSP, use_container: bool = True) -> KasManager:
        """
        Create and configure a KAS manager for the specified BSP.

        Args:
            bsp: BSP configuration object
            use_container: Whether to use containerized KAS (default: True)

        Returns:
            Configured KasManager instance
        """
        # Get container configuration
        container_config = self.get_container_config_for_bsp(bsp)

        # Get cache directories from environment manager
        downloads = None
        sstate = None

        if self.env_manager:
            downloads = self.env_manager.get_value('DL_DIR')
            sstate = self.env_manager.get_value('SSTATE_DIR')

        # Ensure cache directories exist if specified
        if downloads:
            resolver.ensure_directory(downloads)
        if sstate:
            resolver.ensure_directory(sstate)

        # Initialize KAS manager with environment configuration
        kas_mgr = KasManager(
            bsp.build.configuration,
            bsp.build.path,
            download_dir=downloads,
            sstate_dir=sstate,
            use_container=use_container,
            container_image=container_config.image if use_container else None,
            search_paths=[str(self.config_path.parent)],
            env_manager=self.env_manager
        )

        return kas_mgr

    def build_bsp(self, bsp_name: str, checkout_only: bool = False) -> None:
        """
        Build a specific BSP including Docker image and Yocto build.

        This is the main build method that orchestrates the complete
        BSP build process from Docker image creation to Yocto build.
        When checkout_only is True, performs checkout and validation without the full build.

        Args:
            bsp_name: Name of the BSP to build
            checkout_only: If True, only checkout and validate configuration without building

        Raises:
            SystemExit: If any step of the build process fails
        """
        if checkout_only:
            logging.info(f"Checking out BSP: {bsp_name}")
        else:
            logging.info(f"Building BSP: {bsp_name}")

        # Retrieve BSP configuration
        bsp = self.get_bsp_by_name(bsp_name)

        if checkout_only:
            logging.info(f"Checking out {bsp.name} - {bsp.description}")
        else:
            logging.info(f"Building {bsp.name} - {bsp.description}")

        # Get container configuration
        container_config = self.get_container_config_for_bsp(bsp)

        # Build Docker image if configured (skip for checkout mode)
        if not checkout_only:
            if container_config.file and container_config.image:
                build_docker(
                    str(self.config_path.parent),
                    container_config.file,
                    container_config.image,
                    container_config.args
                )
        else:
            logging.info("Skipping Docker build in checkout mode")

        # Prepare build directory
        self.prepare_build_directory(bsp.build.path)

        # Get KAS manager - use native KAS for checkout, container for builds
        kas_mgr = self._get_kas_manager_for_bsp(bsp, use_container=not checkout_only)

        # Dump configuration for verification (debugging)
        config_output = kas_mgr.dump_config(show_output=False)
        if config_output:
            logging.debug("Configuration dump:")
            logging.debug(config_output)

        if checkout_only:
            # Execute checkout for validation only
            logging.info("Performing checkout and validation (no build)...")
            kas_mgr.checkout_project()
            logging.info(f"BSP {bsp_name} checked out and validated successfully!")
        else:
            # Execute full build
            kas_mgr.build_project()
            logging.info(f"BSP {bsp_name} built successfully!")

    def shell_into_bsp(self, bsp_name: str, command: str = None) -> None:
        """
        Enter interactive shell session for the specified BSP.

        This method launches an interactive shell within the Docker
        container environment for the BSP, allowing manual execution
        of build commands, BitBake operations, and debugging.

        Args:
            bsp_name: Name of the BSP to enter shell for
            command: Optional command to execute in the shell (if not provided, starts interactive shell)

        Raises:
            SystemExit: If shell session cannot be started
        """
        logging.info(f"Entering shell for BSP: {bsp_name}")

        # Retrieve BSP configuration
        bsp = self.get_bsp_by_name(bsp_name)

        logging.info(f"Starting shell session for {bsp.name} - {bsp.description}")

        # Get container configuration
        container_config = self.get_container_config_for_bsp(bsp)

        # Build Docker image if configured (same as build process)
        if container_config.file and container_config.image:
            logging.info("Building Docker image for shell environment...")
            build_docker(
                str(self.config_path.parent),
                container_config.file,
                container_config.image,
                container_config.args
            )

        # Prepare build directory
        self.prepare_build_directory(bsp.build.path)

        # Get KAS manager and start shell session
        kas_mgr = self._get_kas_manager_for_bsp(bsp)

        # Start interactive shell session
        logging.info("Starting KAS shell session...")
        if command:
            logging.info(f"Executing command: {command}")
        else:
            logging.info("Interactive shell started. Available commands:")
            logging.info("  - bitbake <recipe>    : Build a specific recipe")
            logging.info("  - devtool <command>   : Use devtool for development workflows")
            logging.info("  - oe-init-build-env   : Initialize build environment")
            logging.info("  - exit                : Exit the shell session")
            logging.info("Use 'Ctrl+D' or type 'exit' to leave the shell.")

        kas_mgr.shell_session(command=command)

    def export_bsp_config(self, bsp_name: str, output_file: Optional[str] = None) -> None:
        """
        Export BSP configuration in KAS format.

        Args:
            bsp_name: Name of the BSP to export
            output_file: Optional file path to save the configuration

        Raises:
            SystemExit: If export fails
        """
        logging.info(f"Exporting KAS configuration for BSP: {bsp_name}")

        # Retrieve BSP configuration
        bsp = self.get_bsp_by_name(bsp_name)

        logging.info(f"Exporting configuration for {bsp.name} - {bsp.description}")

        # Get cache directories from environment manager
        downloads = None
        sstate = None

        if self.env_manager:
            downloads = self.env_manager.get_value('DL_DIR')
            sstate = self.env_manager.get_value('SSTATE_DIR')

        # Create a temporary build directory for export operations
        with tempfile.TemporaryDirectory(prefix=f"bsp_export_{bsp_name}_") as temp_dir:
            # Initialize KAS manager with environment configuration
            kas_mgr = KasManager(
                bsp.build.configuration,
                temp_dir,  # Use temporary directory for export
                download_dir=downloads,
                sstate_dir=sstate,
                use_container=False,  # Don't need container for export
                search_paths=[str(self.config_path.parent)],
                env_manager=self.env_manager
            )

            # Export KAS configuration
            config_yaml = kas_mgr.export_kas_config(output_file)

            # If no output file specified, print to stdout
            if not output_file:
                print("\n" + "="*60)
                print(f"KAS Configuration for BSP: {bsp_name}")
                print("="*60)
                print(config_yaml)
                print("="*60)

        logging.info(f"BSP {bsp_name} configuration exported successfully!")

    def cleanup(self) -> None:
        """Cleanup resources and perform any necessary finalization."""
        logging.debug("Cleaning up resources...")
        # Add cleanup logic here if needed (e.g., temp files, connections)
