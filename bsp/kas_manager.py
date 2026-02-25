"""
KAS build system manager for Yocto-based BSP builds.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any

import yaml

from .environment import EnvironmentManager
from .path_resolver import resolver

# =============================================================================
# KAS Build System Manager
# =============================================================================


class KasManager:
    """
    Manager for KAS (KAS is Yet Another Build System for Yocto) operations.

    This class handles KAS configuration validation, build execution,
    and environment management with comprehensive error handling.
    It supports both native KAS installations and containerized builds
    using kas-container.
    """

    def __init__(self, kas_files: List[str], build_dir: str = "build", use_container: bool = False,
                 download_dir: str = None, sstate_dir: str = None,
                 container_engine: str = None, container_image: str = None,
                 search_paths: List[str] = None, env_manager: EnvironmentManager = None):
        """
        Initialize KAS manager with configuration.

        Args:
            kas_files: List of KAS configuration files (YAML) for the build
            build_dir: Build output directory for Yocto artifacts
            use_container: Use kas-container instead of native kas installation
            download_dir: Downloads cache directory for Yocto sources
            sstate_dir: Shared state cache directory for build acceleration
            container_engine: Container runtime (docker, podman)
            container_image: Custom container image for kas-container
            search_paths: Additional paths to search for configuration files
            env_manager: Environment configuration manager

        Raises:
            SystemExit: If initialization fails due to invalid parameters
        """
        if not isinstance(kas_files, list) or not kas_files:
            logging.error("kas_files must be a non-empty list of file paths")
            sys.exit(1)

        self.kas_files = kas_files
        self.build_dir = Path(build_dir).resolve()
        self.use_container = use_container
        self.container_engine = container_engine
        self.container_image = container_image
        self.search_paths = search_paths or []
        self.download_dir = download_dir
        self.sstate_dir = sstate_dir
        self.env_manager = env_manager or EnvironmentManager()

        # Add common search paths for configuration files
        self.search_paths.extend([
            str(Path.cwd()),              # Current working directory
            str(self.build_dir),          # Build directory
            str(Path(__file__).parent),   # Script directory
            "/repo",                      # Common container path
            "/repo/examples",             # Examples in container
        ])

        self.original_cwd = Path.cwd()
        self._yaml_cache = {}  # Cache for parsed YAML files to avoid re-parsing

        # Ensure build directory exists before starting any operations
        resolver.ensure_directory(str(self.build_dir))

    def _get_kas_command(self) -> List[str]:
        """Get the appropriate KAS command (native or container)."""
        if self.use_container:
            return ["kas-container"]
        else:
            return ["kas"]

    def _get_environment_with_container_vars(self) -> dict:
        """
        Prepare environment variables for KAS execution.

        Sets up cache directories and container-specific environment
        variables required for KAS operation.

        Returns:
            Environment dictionary with KAS-specific variables configured
        """
        env = os.environ.copy()

        # Set cache directories if provided (override environment manager if specified)
        if self.download_dir:
            env['DL_DIR'] = self.download_dir
        elif not env.get('DL_DIR'):  # Only set from env_manager if not already set
            dl_dir = self.env_manager.get_value('DL_DIR')
            if dl_dir:
                env['DL_DIR'] = dl_dir

        if self.sstate_dir:
            env["SSTATE_DIR"] = self.sstate_dir
        elif not env.get('SSTATE_DIR'):  # Only set from env_manager if not already set
            sstate_dir = self.env_manager.get_value('SSTATE_DIR')
            if sstate_dir:
                env['SSTATE_DIR'] = sstate_dir

        # Set container-specific environment variables
        if self.use_container:
            if self.container_engine:
                env['KAS_CONTAINER_ENGINE'] = self.container_engine
            if self.container_image:
                env['KAS_CONTAINER_IMAGE'] = self.container_image

        # Apply environment manager configuration (overrides any previous settings)
        env = self.env_manager.setup_environment(env)

        return env

    def _resolve_kas_file(self, kas_file: str) -> str:
        """
        Resolve KAS file path to absolute path.

        Searches in multiple locations in order:
        - Absolute path
        - Relative to current directory
        - Relative to build directory
        - Script directory
        - Custom search paths

        Args:
            kas_file: KAS file path to resolve

        Returns:
            Absolute path to KAS file

        Raises:
            SystemExit: If file cannot be found in any search location
        """
        path = Path(kas_file)

        # Check absolute path
        if path.is_absolute() and path.exists():
            return str(path.resolve())

        # Check relative to current working directory
        if path.exists():
            return str(path.resolve())

        # Check relative to build directory
        build_dir_path = self.build_dir / path
        if build_dir_path.exists():
            return str(build_dir_path.resolve())

        # Check relative to script directory
        script_dir_path = Path(__file__).parent / path
        if script_dir_path.exists():
            return str(script_dir_path.resolve())

        # Check additional search paths
        for search_path in self.search_paths:
            search_path_obj = Path(search_path)
            candidate_path = search_path_obj / path
            if candidate_path.exists():
                return str(candidate_path.resolve())

        # File not found in any location
        logging.error(f"KAS file not found: {kas_file}")
        logging.error(f"Searched in: {', '.join(self.search_paths)}")
        sys.exit(1)

    def _find_file_in_search_paths(self, filename: str) -> Optional[str]:
        """Find a file in the configured search paths."""
        # Check absolute path
        if Path(filename).is_absolute() and Path(filename).exists():
            return str(Path(filename).resolve())

        # Check relative to current directory
        if Path(filename).exists():
            return str(Path(filename).resolve())

        # Check all search paths
        for search_path in self.search_paths:
            candidate = Path(search_path) / filename
            if candidate.exists():
                return str(candidate.resolve())

        return None

    def _get_kas_files_string(self) -> str:
        """Convert list of KAS files to colon-delimited string with resolved paths."""
        resolved_files = [self._resolve_kas_file(f) for f in self.kas_files]
        return ":".join(resolved_files)

    def _parse_yaml_file(self, file_path: str) -> Dict[str, Any]:
        """
        Parse YAML file with caching.

        Args:
            file_path: Path to YAML file

        Returns:
            Parsed YAML content as dictionary

        Raises:
            SystemExit: If file cannot be parsed due to YAML syntax errors
        """
        resolved_path = self._resolve_kas_file(file_path)
        if resolved_path in self._yaml_cache:
            return self._yaml_cache[resolved_path]

        try:
            with open(resolved_path, 'r', encoding='utf-8') as f:
                content = yaml.safe_load(f) or {}
                self._yaml_cache[resolved_path] = content
                return content
        except (yaml.YAMLError, IOError) as e:
            logging.error(f"Failed to parse YAML file {file_path}: {e}")
            sys.exit(1)

    def _find_includes_in_yaml(self, yaml_content: Dict[str, Any]) -> List[str]:
        """
        Extract include files from YAML content.

        KAS configuration files can include other files through:
        - Top-level 'includes' key
        - 'header' -> 'includes' nested key (less common)

        Args:
            yaml_content: Parsed YAML content

        Returns:
            List of include file paths found in the configuration
        """
        includes = []

        # Check top-level includes (most common)
        if 'includes' in yaml_content:
            include_list = yaml_content['includes']
            if isinstance(include_list, list):
                includes.extend(include_list)

        # Check header includes (less common, older format)
        if 'header' in yaml_content and 'includes' in yaml_content['header']:
            header_includes = yaml_content['header']['includes']
            if isinstance(header_includes, list):
                includes.extend(header_includes)

        return includes

    def _resolve_include_path(self, include_file: str, parent_file: str) -> str:
        """
        Resolve include file path relative to its parent file.

        Args:
            include_file: Include file path (may be relative)
            parent_file: Parent file path for relative resolution

        Returns:
            Absolute path to include file

        Raises:
            SystemExit: If include file cannot be found in any search location
        """
        # Absolute paths are used as-is
        if include_file.startswith('/'):
            return include_file

        # First try relative to parent file directory
        parent_dir = Path(parent_file).parent
        relative_path = parent_dir / include_file
        if relative_path.exists():
            return str(relative_path.resolve())

        # Search in all configured paths
        found_path = self._find_file_in_search_paths(include_file)
        if found_path:
            return found_path

        # Include file not found
        logging.error(f"Include file not found: {include_file} (referenced from {parent_file})")
        sys.exit(1)

    def _get_all_included_files(self, main_files: List[str]) -> List[str]:
        """
        Recursively find all included files from main KAS files.

        Performs depth-first search to build complete dependency tree
        and ensure proper inclusion order.

        Args:
            main_files: List of main KAS configuration files

        Returns:
            Flat list of all files in dependency order (includes first)

        Raises:
            SystemExit: If any included file is missing or circular dependency detected
        """
        all_files = []
        processed_files = set()

        def process_file(file_path: str):
            """Recursive function to process files and their includes."""
            if file_path in processed_files:
                return

            resolved_path = self._resolve_kas_file(file_path)
            if resolved_path in processed_files:
                return

            processed_files.add(resolved_path)

            # Verify file exists
            if not Path(resolved_path).exists():
                logging.error(f"File not found: {file_path} (resolved to: {resolved_path})")
                sys.exit(1)

            # Parse file and find includes
            yaml_content = self._parse_yaml_file(file_path)
            includes = self._find_includes_in_yaml(yaml_content)

            # Process includes first (depth-first for proper dependency resolution)
            for include in includes:
                include_path = self._resolve_include_path(include, file_path)
                process_file(include_path)

            # Add current file after its includes
            all_files.append(file_path)

        # Process all main files
        for main_file in main_files:
            process_file(main_file)

        return all_files

    def validate_kas_files(self, check_includes: bool = True) -> bool:
        """
        Validate that all KAS configuration files exist and are accessible.

        Args:
            check_includes: Whether to recursively validate include files

        Returns:
            True if validation succeeds

        Raises:
            SystemExit: If any file is missing or inaccessible
        """
        try:
            # Check main files
            for kas_file in self.kas_files:
                self._resolve_kas_file(kas_file)  # Will exit if file not found

            # Recursively check include files if requested
            if check_includes:
                self._get_all_included_files(self.kas_files)
                logging.info("All KAS files validated successfully")

            return True

        except SystemExit:
            # Re-raise system exit exceptions
            raise
        except Exception as e:
            logging.error(f"KAS file validation failed: {e}")
            sys.exit(1)

    def check_kas_available(self) -> bool:
        """
        Check if KAS or kas-container is installed and available.

        Returns:
            True if KAS is available, False otherwise
        """
        kas_cmd = self._get_kas_command()
        env = self._get_environment_with_container_vars()

        try:
            if self.use_container:
                # For container version, check if help command works
                test_cmd = kas_cmd + ["--help"]
                result = subprocess.run(
                    test_cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env
                )
                return result.returncode == 0 or len(result.stdout) > 0 or len(result.stderr) > 0
            else:
                # For native version, check version command
                test_cmd = kas_cmd + ["--version"]
                subprocess.run(test_cmd, check=True, capture_output=True, timeout=30, env=env)
                return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            logging.error(f"KAS command not available: {e}")
            return False

    def _run_kas_command(self, args: List[str], show_output: bool = True) -> subprocess.CompletedProcess:
        """
        Execute KAS command with proper environment and error handling.

        Args:
            args: Command arguments to pass to KAS
            show_output: Whether to show live output or capture it

        Returns:
            Completed process information

        Raises:
            SystemExit: If command fails or is interrupted by user
        """
        cmd = self._get_kas_command() + args
        env = self._get_environment_with_container_vars()

        logging.info(f"Running: {' '.join(cmd)}")
        logging.info(f"Build directory: {self.build_dir}")
        logging.info(f"Using container: {self.use_container}")

        # Log important environment variables for debugging
        important_vars = ['DL_DIR', 'SSTATE_DIR', 'GITCONFIG_FILE']
        for var in important_vars:
            if var in env:
                logging.info(f"Using {var}: {env[var]}")

        try:
            if show_output:
                # Show live output to console for build progress
                result = subprocess.run(
                    cmd,
                    check=True,
                    cwd=self.build_dir,
                    env=env
                )
            else:
                # Capture output for programmatic use (export, validation)
                result = subprocess.run(
                    cmd,
                    check=True,
                    cwd=self.build_dir,
                    capture_output=True,
                    text=True,
                    env=env
                )
            return result

        except subprocess.CalledProcessError as e:
            logging.error(f"KAS command failed with return code {e.returncode}")
            if not show_output and e.stderr:
                logging.error(f"Error output: {e.stderr}")
            sys.exit(1)
        except KeyboardInterrupt:
            logging.error("Command interrupted by user")
            sys.exit(1)

    def build_project(self, target: str = None, task: str = None, show_output: bool = True) -> None:
        """
        Build the Yocto project using KAS.

        This is the main build method that orchestrates the complete
        Yocto build process through KAS.

        Args:
            target: Specific build target (recipe or image)
            task: Specific build task (compile, configure, etc.)
            show_output: Whether to show build output in real-time

        Raises:
            SystemExit: If build fails or prerequisites are not met
        """
        # Validate environment configuration first
        if not self.env_manager.validate_environment():
            logging.error("Environment configuration validation failed")
            sys.exit(1)

        # Validate configuration files
        if not self.validate_kas_files(check_includes=True):
            logging.error("Cannot build due to missing files")
            sys.exit(1)

        # Check KAS availability
        if not self.check_kas_available():
            logging.error("KAS is not available. Please install KAS (e.g., 'pip install kas' or use your package manager)")
            sys.exit(1)

        # Build KAS command arguments
        kas_files_str = self._get_kas_files_string()
        args = ["build", kas_files_str]

        if target:
            args.extend(["--target", target])
        if task:
            args.extend(["--task", task])

        try:
            self._run_kas_command(args, show_output)
            logging.info("Build completed successfully!")
        except SystemExit:
            raise
        except Exception as e:
            logging.error(f"Build failed: {e}")
            sys.exit(1)

    def checkout_project(self, show_output: bool = True) -> None:
        """
        Checkout/validate the Yocto project repositories using KAS.

        This method validates that the KAS configuration is correct and
        repositories can be cloned without performing a full build. This is
        useful for quick validation of build configurations.

        Args:
            show_output: Whether to show checkout output in real-time

        Raises:
            SystemExit: If checkout/validation fails or prerequisites are not met
        """
        # Validate environment configuration first
        if not self.env_manager.validate_environment():
            logging.error("Environment configuration validation failed")
            sys.exit(1)

        # Validate configuration files
        if not self.validate_kas_files(check_includes=True):
            logging.error("Cannot checkout due to missing files")
            sys.exit(1)

        # Check KAS availability
        if not self.check_kas_available():
            logging.error("KAS is not available. Please install KAS (e.g., 'pip install kas' or use your package manager)")
            sys.exit(1)

        # Build KAS command arguments
        kas_files_str = self._get_kas_files_string()
        args = ["checkout", kas_files_str]

        try:
            self._run_kas_command(args, show_output)
            logging.info("Checkout/validation completed successfully!")
        except SystemExit:
            raise
        except Exception as e:
            logging.error(f"Checkout/validation failed: {e}")
            sys.exit(1)

    def shell_session(self, command: str = None, show_output: bool = True) -> None:
        """
        Start KAS shell session or execute command in build environment.

        This method launches an interactive shell session within the
        build environment, allowing users to run commands manually.

        Args:
            command: Optional command to execute in shell (if not provided, starts interactive shell)
            show_output: Whether to show command output

        Raises:
            SystemExit: If shell session fails to start
        """
        if not self.validate_kas_files(check_includes=True):
            sys.exit(1)

        if not self.check_kas_available():
            logging.error("KAS is not available")
            sys.exit(1)

        kas_files_str = self._get_kas_files_string()
        args = ["shell", kas_files_str]

        if command:
            args.extend(["--command", command])
            logging.info(f"Executing command in KAS shell: {command}")
        else:
            logging.info("Starting interactive KAS shell session...")
            logging.info("Type 'exit' to leave the shell when done.")

        try:
            self._run_kas_command(args, show_output)
        except SystemExit:
            raise
        except Exception as e:
            logging.error(f"Shell session failed: {e}")
            sys.exit(1)

    def run_bitbake_command(self, recipe: str, bitbake_args: List[str] = None, show_output: bool = True) -> None:
        """
        Run BitBake command through KAS shell.

        Args:
            recipe: BitBake recipe to build
            bitbake_args: Additional BitBake arguments
            show_output: Whether to show command output

        Raises:
            SystemExit: If BitBake command fails
        """
        if not self.validate_kas_files(check_includes=True):
            sys.exit(1)

        if not self.check_kas_available():
            logging.error("KAS is not available")
            sys.exit(1)

        # Build BitBake command
        bitbake_cmd = ["bitbake", recipe]
        if bitbake_args:
            bitbake_cmd.extend(bitbake_args)

        # Execute through KAS shell
        kas_files_str = self._get_kas_files_string()
        args = ["shell", kas_files_str, "--command", " ".join(bitbake_cmd)]

        logging.info(f"Running BitBake: {' '.join(bitbake_cmd)}")

        try:
            self._run_kas_command(args, show_output)
            logging.info("BitBake command completed successfully!")
        except SystemExit:
            raise
        except Exception as e:
            logging.error(f"BitBake command failed: {e}")
            sys.exit(1)

    def dump_config(self, show_output: bool = True) -> Optional[str]:
        """
        Dump expanded KAS configuration for verification.

        This method shows the fully resolved KAS configuration after
        processing all includes and variable expansions.

        Args:
            show_output: Whether to show output or return it

        Returns:
            Configuration string if show_output=False, None otherwise

        Raises:
            SystemExit: If config dump fails
        """
        if not self.validate_kas_files(check_includes=True):
            sys.exit(1)

        if not self.check_kas_available():
            logging.error("KAS is not available")
            sys.exit(1)

        kas_files_str = self._get_kas_files_string()
        args = ["dump", kas_files_str]

        try:
            if show_output:
                self._run_kas_command(args, show_output=True)
                return None
            else:
                result = self._run_kas_command(args, show_output=False)
                return result.stdout
        except SystemExit:
            raise
        except Exception as e:
            logging.error(f"Config dump failed: {e}")
            sys.exit(1)

    def export_kas_config(self, output_file: Optional[str] = None) -> str:
        """
        Export the complete KAS configuration as YAML.

        This method uses KAS to dump the fully resolved configuration
        and saves it to a file or returns it as a string.

        Args:
            output_file: Optional path to save the configuration

        Returns:
            The KAS configuration as YAML string

        Raises:
            SystemExit: If export fails
        """
        logging.info("Exporting KAS configuration...")

        if not self.validate_kas_files(check_includes=True):
            logging.error("Cannot export due to missing files")
            sys.exit(1)

        if not self.check_kas_available():
            logging.error("KAS is not available")
            sys.exit(1)

        try:
            # Get the complete configuration dump
            config_yaml = self.dump_config(show_output=False)

            if not config_yaml:
                logging.error("Failed to get KAS configuration")
                sys.exit(1)

            # Save to file if specified
            if output_file:
                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)

                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(config_yaml)

                logging.info(f"KAS configuration exported to: {output_path}")
            else:
                logging.info("KAS configuration exported successfully")

            return config_yaml

        except SystemExit:
            raise
        except Exception as e:
            logging.error(f"Failed to export KAS configuration: {e}")
            sys.exit(1)
