"""
KAS build system manager for Yocto-based BSP builds.
"""

import logging
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

import yaml

from .environment import EnvironmentManager
from .models import DockerVolume
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
                 container_runtime_args: str = None,
                 container_privileged: bool = False,
                 container_volumes: List[DockerVolume] = None,
                 search_paths: List[str] = None, env_manager: EnvironmentManager = None,
                 verbose: bool = False):
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
            container_runtime_args: Extra arguments appended to the container engine run command
            container_privileged: Run container in privileged mode (enables --isar flag)
            container_volumes: List of host-to-container directory mappings; each entry is
                               converted to a ``-v host:container[:ro]`` flag passed via
                               ``--runtime-args``. Host paths support ``$ENV{VAR}``
                               expansion.
            search_paths: Additional paths to search for configuration files
            env_manager: Environment configuration manager
            verbose: If True, pass ``-l debug`` to kas-container for detailed logging

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
        self.container_runtime_args = container_runtime_args
        self.container_privileged = container_privileged
        self.container_volumes = container_volumes or []
        self.search_paths = search_paths or []
        self.download_dir = download_dir
        self.sstate_dir = sstate_dir
        self.env_manager = env_manager or EnvironmentManager()
        self.verbose = verbose

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
        """
        Get the appropriate KAS command (native or container).

        For privileged container builds (e.g., ISAR), adds the --isar flag
        which enables the --privileged Docker flag, granting the container
        all capabilities including SYS_ADMIN and MKNOD.

        Note: The --isar flag is a kas-container feature that enables privileged
        Docker capabilities. Despite the name, it can be used for any build requiring
        elevated container privileges, not just ISAR builds.

        See: https://github.com/siemens/kas/blob/master/kas-container
        """
        if self.use_container:
            cmd = ["kas-container"]
            # Add --isar flag for privileged builds, which sets --privileged
            # (granting all capabilities including SYS_ADMIN and MKNOD)
            if self.container_privileged:
                cmd.append("--isar")
            # Enable kas-container debug logging in verbose mode
            if self.verbose:
                cmd.extend(["-l", "debug"])
            return cmd
        else:
            return ["kas"]

    def _get_environment_with_container_vars(self) -> dict:
        """
        Prepare environment variables for KAS execution.

        Sets up cache directories and container-specific environment
        variables required for KAS operation.

        When running inside a container (``use_container=True``) the method
        sets ``KAS_CONTAINER_ENGINE`` and ``KAS_CONTAINER_IMAGE`` when
        configured.  All environment variables from ``env_manager`` and named
        environment model sections are resolved and placed directly in the
        process environment so that ``kas-container`` inherits them.  Volume
        mounts and explicit ``container_runtime_args`` are forwarded via the
        ``--runtime-args`` CLI option in :meth:`_run_kas_command`.

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

        # Apply environment manager so that env_manager variables are resolved
        # and available for _build_runtime_args_str().
        env = self.env_manager.setup_environment(env)

        # Set container-specific environment variables
        if self.use_container:
            if self.container_engine:
                env['KAS_CONTAINER_ENGINE'] = self.container_engine
            if self.container_image:
                env['KAS_CONTAINER_IMAGE'] = self.container_image

        return env

    def _build_runtime_args_str(self, env: dict) -> Optional[str]:
        """
        Build the value to pass to ``kas-container --runtime-args``.

        Collects container runtime flags in order:

        1. Any ``KAS_RUNTIME_ARGS`` already present in *env* (e.g. set by
           ``env_manager`` or inherited from the host shell).
        2. Explicit ``container_runtime_args`` from the registry config.
        3. Volume mounts as ``-v host:container[:ro]`` flags.

        All environment variables — whether they come from the registry's
        ``environment`` sections, named environment model sections, or the
        host shell — are passed to ``kas-container`` via the process
        environment (see :meth:`_get_environment_with_container_vars`).
        They are **not** duplicated as ``-e`` flags inside ``--runtime-args``.

        Args:
            env: Resolved environment dictionary (from
                 :meth:`_get_environment_with_container_vars`).

        Returns:
            Space-joined flags string, or ``None`` if there is nothing to
            pass.
        """
        if not self.use_container:
            return None

        parts: List[str] = []

        # Honor any KAS_RUNTIME_ARGS already set via env_manager or host shell
        existing = env.get('KAS_RUNTIME_ARGS', '').strip()
        if existing:
            parts.append(existing)

        if self.container_runtime_args:
            parts.append(self.container_runtime_args)

        for vol in self.container_volumes:
            expanded_host = self._expand_env_vars(vol.host)
            flag = f"-v {expanded_host}:{vol.container}"
            if vol.read_only:
                flag += ":ro"
            parts.append(flag)

        return " ".join(parts) if parts else None

    def get_runtime_args(self) -> Optional[str]:
        """Return resolved runtime args that will be forwarded to kas-container."""
        env = self._get_environment_with_container_vars()
        return self._build_runtime_args_str(env)

    def _expand_env_vars(self, value: str) -> str:
        """
        Expand ``$ENV{VAR}`` patterns and standard ``$VAR`` / ``%VAR%`` patterns
        in *value*, consistent with ``EnvironmentManager``.

        Reuses ``EnvironmentManager.ENV_VAR_PATTERN`` so the two implementations
        cannot diverge.  A warning is logged for any ``$ENV{VAR}`` that is not
        set; the token is replaced with an empty string so the volume flag is
        still produced.

        Args:
            value: String that may contain ``$ENV{VAR}`` tokens.

        Returns:
            Expanded string.
        """
        def _replace(match):
            var_name = match.group(1)
            if var_name in os.environ:
                return os.environ[var_name]
            logging.warning(
                f"Environment variable '{var_name}' is not set; "
                f"using empty string for expansion in volume host path: {value}"
            )
            return ""

        expanded = EnvironmentManager.ENV_VAR_PATTERN.sub(_replace, value)
        return os.path.expandvars(expanded)

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
                # KAS also allows repo-relative includes written as a dict
                # ({repo: <name>, file: <path>}). The repo only exists after
                # checkout, so kas resolves these itself; skip them here.
                if not isinstance(include, str):
                    if isinstance(include, dict):
                        logging.warning(
                            f"Include in {file_path} references external "
                            f"repository '{include.get('repo', '?')}' "
                            f"(file: {include.get('file', '?')}); it will be "
                            f"resolved by kas after checkout and is not "
                            f"validated here"
                        )
                    else:
                        logging.warning(
                            f"Skipping unsupported include entry {include!r} "
                            f"in {file_path}"
                        )
                    continue
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
        env = self._get_environment_with_container_vars()

        cmd = self._get_kas_command()
        if self.use_container:
            runtime_args = self._build_runtime_args_str(env)
            # Remove KAS_RUNTIME_ARGS from the environment — all flags are
            # now forwarded via --runtime-args on the command line instead.
            env.pop('KAS_RUNTIME_ARGS', None)
            if runtime_args:
                cmd = cmd + ["--runtime-args", runtime_args]
                logging.debug(f"--runtime-args: {runtime_args}")
        cmd = cmd + args

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

        build_start = time.monotonic()
        try:
            self._run_kas_command(args, show_output)
            elapsed = time.monotonic() - build_start
            total_seconds = round(elapsed)
            minutes, seconds = divmod(total_seconds, 60)
            hours, minutes = divmod(minutes, 60)
            if hours:
                duration_str = f"{hours}h {minutes}m {seconds}s"
            elif minutes:
                duration_str = f"{minutes}m {seconds}s"
            elif total_seconds > 0:
                duration_str = f"{seconds}s"
            else:
                duration_str = f"{elapsed:.2f}s"
            logging.info("Build completed successfully!")
            logging.info(f"Build time: {duration_str}")
        except SystemExit:
            raise
        except Exception as e:
            logging.error(f"Build failed: {e}")
            sys.exit(1)

    def fetch_project(self, targets: List[str], show_output: bool = True) -> None:
        """
        Fetch all sources required for the given BitBake targets.

        Args:
            targets: BitBake targets whose dependency trees should be fetched
            show_output: Whether to show fetch output in real-time

        Raises:
            SystemExit: If fetch fails or prerequisites are not met
        """
        if not targets:
            logging.error("At least one BitBake target is required for source fetch")
            sys.exit(1)

        if not self.env_manager.validate_environment():
            logging.error("Environment configuration validation failed")
            sys.exit(1)

        if not self.validate_kas_files(check_includes=True):
            logging.error("Cannot fetch due to missing files")
            sys.exit(1)

        if not self.check_kas_available():
            logging.error("KAS is not available. Please install KAS (e.g., 'pip install kas' or use your package manager)")
            sys.exit(1)

        kas_files_str = self._get_kas_files_string()
        bitbake_cmd = "bitbake --runall=fetch " + " ".join(targets)
        args = ["shell", kas_files_str, "--command", bitbake_cmd]

        try:
            self._run_kas_command(args, show_output)
            logging.info("Source fetch completed successfully!")
        except SystemExit:
            raise
        except Exception as e:
            logging.error(f"Source fetch failed: {e}")
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

    def dump_config(self, show_output: bool = True, lock: bool = False) -> Optional[str]:
        """
        Dump expanded KAS configuration for verification.

        This method shows the fully resolved KAS configuration after
        processing all includes and variable expansions.

        Args:
            show_output: Whether to show output or return it
            lock: Whether to include ``--lock`` in ``kas dump``

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
        args = ["dump"]
        if lock:
            args.append("--lock")
        args.append(kas_files_str)

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

    def _extract_locked_repos(self, lock_yaml: str, require_url: bool = True) -> List[Dict[str, str]]:
        """Parse kas dump YAML and return normalized repository rows."""
        try:
            docs = list(yaml.safe_load_all(lock_yaml))
        except Exception as e:
            logging.error(f"Failed to parse locked KAS configuration: {e}")
            sys.exit(1)

        if not any(isinstance(doc, (dict, list)) for doc in docs):
            logging.error("Locked KAS output did not contain a YAML mapping document")
            sys.exit(1)

        def _repo_candidates(doc: Dict[str, Any]) -> List[Any]:
            candidates = [
                doc.get("repos"),
                doc.get("repositories"),
                doc.get("sources"),
            ]
            nested = doc.get("config")
            if isinstance(nested, dict):
                candidates.extend(
                    [
                        nested.get("repos"),
                        nested.get("repositories"),
                        nested.get("sources"),
                    ]
                )
            return candidates

        def _find_repo_candidates_recursive(node: Any) -> List[Any]:
            found: List[Any] = []
            if isinstance(node, dict):
                for key in ("repos", "repositories", "sources"):
                    candidate = node.get(key)
                    if isinstance(candidate, (dict, list)) and candidate:
                        found.append(candidate)
                for value in node.values():
                    found.extend(_find_repo_candidates_recursive(value))
            elif isinstance(node, list):
                for item in node:
                    found.extend(_find_repo_candidates_recursive(item))
            return found

        repos: Any = None
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            for candidate in _repo_candidates(doc):
                if isinstance(candidate, (dict, list)) and candidate:
                    repos = candidate
                    break
            if repos is not None:
                break

        if repos is None:
            for doc in docs:
                for candidate in _find_repo_candidates_recursive(doc):
                    if isinstance(candidate, (dict, list)) and candidate:
                        repos = candidate
                        break
                if repos is not None:
                    break

        if not isinstance(repos, (dict, list)) or not repos:
            logging.error("No repositories found in locked KAS configuration")
            sys.exit(1)

        rows: List[Dict[str, str]] = []
        repo_items: List[Tuple[str, Dict[str, Any]]] = []
        if isinstance(repos, dict):
            for repo_name, repo_cfg in repos.items():
                if isinstance(repo_cfg, dict):
                    repo_items.append((str(repo_name), repo_cfg))
        else:
            for idx, repo_cfg in enumerate(repos):
                if not isinstance(repo_cfg, dict):
                    continue
                fallback_name = f"repo-{idx + 1}"
                repo_name = (
                    repo_cfg.get("name")
                    or repo_cfg.get("repo")
                    or repo_cfg.get("id")
                    or repo_cfg.get("path")
                    or repo_cfg.get("url")
                    or fallback_name
                )
                repo_items.append((str(repo_name), repo_cfg))

        for repo_name, repo_cfg in sorted(repo_items, key=lambda item: item[0]):
            if not isinstance(repo_cfg, dict):
                continue
            url = repo_cfg.get("url")
            if require_url and not url:
                # Skip local/non-fetch repositories when URL is required
                continue
            revision = (
                repo_cfg.get("commit")
                or repo_cfg.get("revision")
                or repo_cfg.get("branch")
                or repo_cfg.get("tag")
                or repo_cfg.get("refspec")
            )
            if not url and not revision:
                # Skip repos with no URL and no revision — nothing useful to contribute
                continue
            if not revision:
                logging.warning(
                    "Repository '%s' has no revision/commit in lock output; exporting manifest project without revision",
                    repo_name,
                )
            row: Dict[str, str] = {
                "name": str(repo_name),
                "path": str(repo_cfg.get("path") or repo_name),
            }
            if url:
                row["url"] = str(url)
            if revision:
                row["revision"] = str(revision)
            rows.append(row)
        if require_url and not rows:
            logging.error("No remote repositories found in lock output")
            sys.exit(1)
        return rows

    @staticmethod
    def _looks_like_git_sha(revision: Optional[str]) -> bool:
        """Return True when revision looks like a full Git commit SHA."""
        if not revision:
            return False
        return bool(re.fullmatch(r"[0-9a-fA-F]{40}", revision))

    def _merge_manifest_rows(
        self,
        locked_rows: List[Dict[str, str]],
        unlocked_rows: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        """
        Merge lock/unlocked repo rows for manifest generation.

        URL/path/name come from unlocked dump when available.
        Revision prefers locked values, especially full commit SHAs.
        """
        merged: Dict[str, Dict[str, str]] = {}

        for row in unlocked_rows:
            merged[row["name"]] = dict(row)

        for row in locked_rows:
            key = row["name"]
            current = merged.get(key, {"name": key})

            if not current.get("url") and row.get("url"):
                current["url"] = row["url"]
            if not current.get("path") and row.get("path"):
                current["path"] = row["path"]

            locked_revision = row.get("revision")
            current_revision = current.get("revision")
            if locked_revision and (
                self._looks_like_git_sha(locked_revision)
                or not current_revision
                or not self._looks_like_git_sha(current_revision)
            ):
                current["revision"] = locked_revision

            merged[key] = current

        return sorted(merged.values(), key=lambda row: row["name"])

    def _build_android_repo_manifest_xml(self, rows: List[Dict[str, str]]) -> str:
        """Render Android repo manifest XML from normalized repository rows."""
        def _split_repo_url(url: str) -> Dict[str, str]:
            parsed = urlparse(url)
            if parsed.scheme and parsed.netloc:
                fetch = f"{parsed.scheme}://{parsed.netloc}"
                name = parsed.path.lstrip("/").removesuffix(".git")
                return {"fetch": fetch, "name": name}
            # Handle scp-like syntax: git@host:org/repo.git
            at_pos = url.find("@")
            colon_pos = url.find(":")
            host_and_path = url[at_pos + 1:] if at_pos != -1 else ""
            # Match scp-like git URLs (git@host:path), but avoid absolute paths.
            if (
                at_pos != -1
                and colon_pos > at_pos
                and not url.startswith("/")
                and host_and_path.count(":") == 1
            ):
                user_host, repo_path = url.split(":", 1)
                fetch = f"ssh://{user_host}"
                name = repo_path.lstrip("/").removesuffix(".git")
                return {"fetch": fetch, "name": name}
            logging.warning("Could not split repository URL '%s' into fetch/name for Android manifest", url)
            return {"fetch": url, "name": ""}

        split = {row["url"]: _split_repo_url(row["url"]) for row in rows}
        fetches = sorted({v["fetch"] for v in split.values()})
        remote_name_by_fetch = {fetch: f"remote-{idx + 1}" for idx, fetch in enumerate(fetches)}

        manifest = ET.Element("manifest")
        for fetch in fetches:
            ET.SubElement(
                manifest,
                "remote",
                {
                    "name": remote_name_by_fetch[fetch],
                    "fetch": fetch,
                },
            )
        for row in sorted(rows, key=lambda x: x["name"]):
            split_info = split[row["url"]]
            project_name = split_info["name"] or row["name"]
            attrs = {
                "name": project_name,
                "path": row["path"],
                "remote": remote_name_by_fetch[split_info["fetch"]],
            }
            revision = row.get("revision")
            if revision:
                attrs["revision"] = revision
            ET.SubElement(manifest, "project", attrs)

        ET.indent(manifest, space="  ")
        xml_bytes = ET.tostring(manifest, encoding="utf-8", xml_declaration=True)
        return xml_bytes.decode("utf-8")

    def export_repo_manifest_xml(self, output_file: Optional[str] = None) -> str:
        """
        Export Android repo manifest XML from KAS lock data.

        Args:
            output_file: Optional file path to save the manifest XML

        Returns:
            Manifest XML string

        Raises:
            SystemExit: If export fails
        """
        logging.info("Exporting Android repo manifest XML...")

        if not self.validate_kas_files(check_includes=True):
            logging.error("Cannot export repo manifest due to missing files")
            sys.exit(1)

        if not self.check_kas_available():
            logging.error("KAS is not available")
            sys.exit(1)

        kas_files_str = self._get_kas_files_string()
        lock_args = ["dump", "--lock", "--sort", kas_files_str]
        unlocked_args = ["dump", "--sort", kas_files_str]

        try:
            lock_result = self._run_kas_command(lock_args, show_output=False)
            unlocked_result = self._run_kas_command(unlocked_args, show_output=False)
            locked_rows = self._extract_locked_repos(lock_result.stdout, require_url=False)
            unlocked_rows = self._extract_locked_repos(unlocked_result.stdout)
            rows = self._merge_manifest_rows(locked_rows, unlocked_rows)
            rows = [row for row in rows if row.get("url")]
            if not rows:
                logging.error("No remote repositories found in lock output")
                sys.exit(1)
            manifest_xml = self._build_android_repo_manifest_xml(rows)

            if output_file:
                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(manifest_xml)
                logging.info(f"Android repo manifest exported to: {output_path}")
            else:
                logging.info("Android repo manifest exported successfully")

            return manifest_xml
        except SystemExit:
            raise
        except Exception as e:
            logging.error(f"Failed to export Android repo manifest XML: {e}")
            sys.exit(1)

    def export_kas_config(self, output_file: Optional[str] = None, lock: bool = False) -> str:
        """
        Export the complete KAS configuration as YAML.

        This method uses KAS to dump the fully resolved configuration
        and saves it to a file or returns it as a string.

        Args:
            output_file: Optional path to save the configuration
            lock: Whether to include ``--lock`` in ``kas dump``

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
            config_yaml = self.dump_config(show_output=False, lock=lock)

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
