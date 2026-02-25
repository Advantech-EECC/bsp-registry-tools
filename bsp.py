#!/usr/bin/env python3
"""
Advantech Board Support Package (BSP) Registry Manager

This script provides a comprehensive command-line interface for managing and building
Yocto-based BSPs using the KAS build system. It supports Docker containers, cached builds,
and sophisticated configuration management for embedded Linux development.

Key Features:
- BSP registry management via YAML configuration files
- Docker container building and management for reproducible builds
- KAS build system integration for Yocto-based builds
- Interactive shell access to build environments
- Comprehensive error handling and configuration validation
- Advanced cache management for faster incremental builds
- Environment variable configuration management with expansion
- KAS configuration export functionality

Architecture:
- BspManager: Main coordinator for BSP operations
- KasManager: Handles KAS build system operations  
- EnvironmentManager: Manages build environment variables with expansion
- PathResolver: Utility for path resolution and validation

Typical Usage:
  $ python bsp.py list                    # List available BSPs
  $ python bsp.py build <bsp_name>        # Build a specific BSP
  $ python bsp.py shell <bsp_name>        # Enter interactive shell for BSP
  $ python bsp.py export <bsp_name>       # Export BSP configuration

Configuration:
  Uses YAML configuration files (default: bsp-registry.yml) to define:
  - BSP specifications and dependencies
  - Build environment settings (Docker, environment variables)
  - Cache directories and build parameters
  - Environment variables with expansion support (e.g., $ENV{HOME})
  - Container definitions for different build environments
"""

import subprocess
import os
import sys
import logging
import argparse
import dacite
import tempfile
import re

import yaml
from pathlib import Path
from typing import List, Optional, Dict, Any

from dataclasses import dataclass, field

# =============================================================================
# Logging Colors
# =============================================================================

try:
    import colorama
    from colorama import Fore, Style
    colorama.init()  # Initialize colorama for Windows support
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False

class ColoramaFormatter(logging.Formatter):
    """Colored formatter using colorama for cross-platform compatibility."""
    
    if COLORAMA_AVAILABLE:
        COLOR_MAP = {
            logging.DEBUG: Fore.CYAN,
            logging.INFO: Fore.GREEN,
            logging.WARNING: Fore.YELLOW,
            logging.ERROR: Fore.RED,
            logging.CRITICAL: Fore.RED + Style.BRIGHT
        }
    else:
        # Fallback to ANSI codes if colorama not available
        COLOR_MAP = {
            logging.DEBUG: '\033[36m',
            logging.INFO: '\033[32m',
            logging.WARNING: '\033[33m',
            logging.ERROR: '\033[31m',
            logging.CRITICAL: '\033[1;31m'
        }
    
    RESET = Style.RESET_ALL if COLORAMA_AVAILABLE else '\033[0m'
    
    def format(self, record):
        color = self.COLOR_MAP.get(record.levelno, '')
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        record.msg = f"{color}{record.msg}{self.RESET}"
        return super().format(record)
    
# =============================================================================
# Exception Hierarchy
# =============================================================================

class ScriptError(Exception):
    """Base exception class for all script-related errors."""
    pass

class ConfigurationError(ScriptError):
    """Raised when there are issues with configuration files or settings."""
    pass

class BuildError(ScriptError):
    """Raised when build processes fail."""
    pass

class DockerError(ScriptError):
    """Raised when Docker operations fail."""
    pass

class KasError(ScriptError):
    """Raised when KAS operations fail."""
    pass

# =============================================================================
# Configuration Data Classes
# =============================================================================

def empty_list():
    """Factory function for creating empty lists in dataclass fields."""
    return []

def empty_dict():
    """Factory function for creating empty dictionaries in dataclass fields."""
    return {}

@dataclass
class EnvironmentVariable:
    """
    Represents an environment variable name-value pair.
    
    Attributes:
        name: Environment variable name
        value: Environment variable value (supports $ENV{VAR} expansion)
    """
    name: str
    value: str

@dataclass
class DockerArg:
    """
    Represents a Docker build argument (name=value pair).
    
    Attributes:
        name: Argument name
        value: Argument value
    """
    name: str
    value: str

@dataclass
class Docker:
    """
    Docker configuration for build environment.
    
    Attributes:
        image: Docker image name/tag for the build environment
        file: Path to Dockerfile for building custom images
        args: List of Docker build arguments (name=value pairs)
    """
    image: Optional[str]
    file: Optional[str]
    args: List[DockerArg] = field(default_factory=empty_list)

@dataclass
class ContainerDefinition:
    """
    Container definition with name and Docker configuration.
    
    Attributes:
        name: Container name/identifier (e.g., 'ubuntu-20.04')
        docker: Docker configuration for this container
    """
    name: str
    docker: Docker

@dataclass
class BuildEnvironment:
    """
    Build environment configuration including Docker settings.
    
    Attributes:
        container: Name of the container to use (references containers in registry)
        docker: Direct Docker configuration (alternative to container reference)
    """
    container: Optional[str] = None
    docker: Optional[Docker] = None

@dataclass
class BuildSetup:
    """
    Complete build setup configuration.
    
    Attributes:
        path: Build directory path for output artifacts
        environment: Build environment settings (Docker, container reference)
        docker: Docker runtime to use (docker, podman, etc.)
        configuration: List of KAS configuration files for the build
    """
    path: str
    environment: BuildEnvironment
    docker: Optional[str]
    configuration: List[str]

@dataclass
class Specification:
    """
    Registry specification version.
    
    Attributes:
        version: Specification version string (e.g., '1.0')
    """
    version: str

@dataclass
class OperatingSystem:
    """
    Operating system configuration for the BSP.
    
    Attributes:
        name: OS name (e.g., 'linux')
        build_system: Build system (e.g., 'yocto')
        version: OS version string
    """
    name: str
    build_system: str
    version: str

@dataclass
class BSP:
    """
    Board Support Package definition.
    
    Attributes:
        name: Unique BSP identifier
        description: Human-readable description
        os: Operating system configuration
        build: Build configuration and setup
    """
    name: str
    description: str
    build: BuildSetup
    os: Optional[OperatingSystem] = None

@dataclass
class Registry:
    """
    Main registry containing BSP definitions.
    
    Attributes:
        bsp: List of BSP definitions in the registry
    """
    bsp: Optional[List[BSP]] = field(default_factory=empty_list)

@dataclass
class RegistryRoot:
    """
    Root container for the registry configuration.
    
    Attributes:
        specification: Specification version information
        registry: Main registry data containing BSP definitions
        containers: Dictionary of container definitions keyed by name
        environment: Global environment variables for all builds (supports expansion)
    """
    specification: Specification
    registry: Registry
    containers: Optional[Dict[str, Docker]] = field(default_factory=empty_dict)
    environment: Optional[List[EnvironmentVariable]] = field(default_factory=empty_list)

# =============================================================================
# YAML Configuration Parser with Container Support
# =============================================================================

def read_yaml_file(filename: Path) -> str:
    """
    Read a YAML file into a string with comprehensive error handling.
    
    Args:
        filename: Path to the YAML file to read
        
    Returns:
        String containing the complete file contents
        
    Raises:
        SystemExit: If file cannot be read due to I/O errors or permissions
    """
    try:
        with open(filename, 'r', encoding='utf-8') as yaml_file:
            return yaml_file.read()
    except (IOError, OSError) as e:
        logging.error(f"Failed to read YAML file {filename}: {e}")
        sys.exit(1)

def parse_yaml_file(yaml_string: str) -> Dict[Any, Any]:
    """
    Parse YAML string into a Python dictionary with validation.
    
    Args:
        yaml_string: YAML formatted string to parse
        
    Returns:
        Dictionary representation of YAML content
        
    Raises:
        SystemExit: If YAML parsing fails due to malformed content
    """
    try:
        return yaml.safe_load(yaml_string)
    except yaml.YAMLError as e:
        logging.error(f"Failed to parse YAML: {e}")
        sys.exit(1)

def convert_containers_list_to_dict(containers_list: List[Dict[str, Any]]) -> Dict[str, Docker]:
    """
    Convert containers list format to dictionary format for dacite.
    
    The YAML format uses a list of dictionaries where each dictionary has one key
    (the container name). This function converts it to a dictionary keyed by container name.
    
    Example input:
        [
            {"ubuntu-20.04": {"file": "...", "image": "...", "args": [...]}},
            {"ubuntu-22.04": {"file": "...", "image": "...", "args": [...]}}
        ]
    
    Example output:
        {
            "ubuntu-20.04": {"file": "...", "image": "...", "args": [...]},
            "ubuntu-22.04": {"file": "...", "image": "...", "args": [...]}
        }
    
    Args:
        containers_list: List of container definitions in YAML format
        
    Returns:
        Dictionary mapping container names to Docker configurations
    """
    containers_dict = {}
    
    for container_item in containers_list:
        for container_name, container_config in container_item.items():
            if isinstance(container_config, dict):
                # Convert to Docker dataclass
                containers_dict[container_name] = Docker(
                    image=container_config.get('image'),
                    file=container_config.get('file'),
                    args=[DockerArg(name=arg['name'], value=arg['value']) 
                          for arg in container_config.get('args', [])]
                )
            else:
                logging.warning(f"Invalid container configuration for {container_name}, skipping")
    
    return containers_dict

def get_registry_from_yaml_file(filename: Path) -> RegistryRoot:
    """
    Parse YAML file into structured RegistryRoot object using dacite.
    
    This function converts the raw YAML dictionary into strongly-typed
    dataclasses with comprehensive type checking and validation.
    
    Args:
        filename: Path to registry YAML file
        
    Returns:
        Structured registry configuration as RegistryRoot object
        
    Raises:
        SystemExit: If configuration is invalid, malformed, or missing required fields
    """
    yaml_string = read_yaml_file(filename)
    yaml_dict = parse_yaml_file(yaml_string)

    # Pre-process containers list to dictionary format if needed
    if 'containers' in yaml_dict and isinstance(yaml_dict['containers'], list):
        logging.debug("Converting containers list to dictionary format")
        yaml_dict['containers'] = convert_containers_list_to_dict(yaml_dict['containers'])

    try:
        # Use dacite to convert dictionary to strongly-typed dataclass
        # strict=False allows forward compatibility with new fields
        cfg = dacite.Config(strict=False)
        ast = dacite.from_dict(data_class=RegistryRoot, data=yaml_dict, config=cfg)
        return ast
    except dacite.UnexpectedDataError as e:
        logging.error(f"Configuration error in {filename}: Unknown fields found - {e}")
        sys.exit(1)
    except dacite.WrongTypeError as e:
        logging.error(f"Type error in configuration {filename}: Field type mismatch - {e}")
        sys.exit(1)
    except dacite.MissingValueError as e:
        logging.error(f"Missing value in configuration {filename}: Required field missing - {e}")
        sys.exit(1)

# =============================================================================
# Docker Operations
# =============================================================================

def build_docker(dockerfile_dir: str, dockerfile: str, tag: str, 
                 build_args: Optional[List[DockerArg]] = None) -> None:
    """
    Build Docker image from Dockerfile with comprehensive validation.
    
    This function handles the complete Docker build process including:
    - Prerequisite validation (directory and file existence)
    - Build argument processing
    - Directory context management
    - Error handling and logging
    
    Args:
        dockerfile_dir: Directory containing Dockerfile and build context
        dockerfile: Dockerfile name (e.g., 'Dockerfile')
        tag: Image tag for the built image (e.g., 'my-bsp:latest')
        build_args: List of Docker build arguments for parameterized builds
        
    Raises:
        SystemExit: If Docker build fails, prerequisites are missing, or Docker is unavailable
    """
    logging.info(f"Building docker container {tag} using {dockerfile}")
    
    # Validate prerequisites before attempting build
    if not os.path.isdir(dockerfile_dir):
        logging.error(f"Docker build directory does not exist: {dockerfile_dir}")
        sys.exit(1)
        
    dockerfile_path = os.path.join(dockerfile_dir, dockerfile)
    if not os.path.isfile(dockerfile_path):
        logging.error(f"Dockerfile not found: {dockerfile_path}")
        sys.exit(1)

    original_dir = os.getcwd()
    try:
        # Change to Dockerfile directory for proper build context
        os.chdir(dockerfile_dir)
        
        # Build docker command with all required parameters
        cmd = ["docker", "build", "-f", dockerfile, "-t", tag]
        
        # Add build arguments if provided (for parameterized Docker builds)
        if build_args:
            for argument in build_args:
                cmd.extend(["--build-arg", f"{argument.name}={argument.value}"])

        cmd.extend(["."])  # Build context is current directory
        
        logging.info(f"Running: {' '.join(cmd)}")
        
        # Execute build command with real-time output capture
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logging.info("Docker build completed successfully")
        
    except subprocess.CalledProcessError as e:
        logging.error(f"Docker build failed with return code {e.returncode}")
        logging.error(f"Error output: {e.stderr}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error during Docker build: {e}")
        sys.exit(1)
    finally:
        # Always return to original directory regardless of build outcome
        os.chdir(original_dir)

# =============================================================================
# Path Resolution Utility
# =============================================================================

class PathResolver:
    """
    Utility class for path resolution and validation.
    
    Provides centralized methods for handling path operations with:
    - Home directory expansion (~/ paths)
    - Existence and type validation
    - Directory creation with proper error handling
    - Consistent path normalization
    
    All methods handle path strings with home directory notation and
    provide consistent behavior across different platforms.
    """
    
    @staticmethod
    def resolve(path_string: str) -> Path:
        """
        Resolve path with ~ expansion to absolute Path object.
        
        Args:
            path_string: Path string that may contain ~ for home directory
            
        Returns:
            Resolved absolute Path object
        """
        return Path(path_string).expanduser().resolve()
    
    @staticmethod
    def resolve_str(path_string: str) -> str:
        """
        Resolve path with ~ expansion to absolute string.
        
        Args:
            path_string: Path string that may contain ~ for home directory
            
        Returns:
            Resolved absolute path as string
        """
        return str(PathResolver.resolve(path_string))
    
    @staticmethod
    def exists(path_string: str) -> bool:
        """
        Check if path exists after resolving ~ expansion.
        
        Args:
            path_string: Path to check for existence
            
        Returns:
            True if path exists, False otherwise
        """
        return PathResolver.resolve(path_string).exists()
    
    @staticmethod
    def is_file(path_string: str) -> bool:
        """
        Check if path is a file after resolving ~ expansion.
        
        Args:
            path_string: Path to check
            
        Returns:
            True if path exists and is a file, False otherwise
        """
        return PathResolver.resolve(path_string).is_file()
    
    @staticmethod
    def is_dir(path_string: str) -> bool:
        """
        Check if path is a directory after resolving ~ expansion.
        
        Args:
            path_string: Path to check
            
        Returns:
            True if path exists and is a directory, False otherwise
        """
        return PathResolver.resolve(path_string).is_dir()
    
    @staticmethod
    def ensure_directory(path_string: str) -> None:
        """
        Ensure directory exists, create if necessary with parent directories.
        
        This method creates the directory and all intermediate directories
        if they don't exist, similar to 'mkdir -p' command.
        
        Args:
            path_string: Directory path to ensure existence of
            
        Raises:
            SystemExit: If directory cannot be created due to permissions or I/O errors
        """
        path = PathResolver.resolve(path_string)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except (OSError, IOError) as e:
            logging.error(f"Failed to create directory {path}: {e}")
            sys.exit(1)

# Global path resolver instance for consistent path handling
resolver = PathResolver()

# =============================================================================
# Environment Variable Management with Expansion
# =============================================================================

class EnvironmentManager:
    """
    Manager for environment variable configuration in build environments.
    
    Handles environment variable setup, validation, and management for:
    - Build cache directories (DL_DIR, SSTATE_DIR)
    - Git configuration (GITCONFIG_FILE)
    - Custom build variables
    - Container-specific environment settings
    
    Supports environment variable expansion in the form of $ENV{VAR_NAME}
    for referencing system environment variables in configuration.
    
    This class ensures consistent environment setup across different
    build types (native, Docker, kas-container).
    """
    
    # Regular expression pattern to match $ENV{VAR_NAME} style variables
    ENV_VAR_PATTERN = re.compile(r'\$ENV\{([^}]+)\}')
    
    def __init__(self, environment_vars: Optional[List[EnvironmentVariable]] = None):
        """
        Initialize Environment manager with optional variables.
        
        Args:
            environment_vars: List of environment variables to manage
        """
        self.environment_vars = environment_vars or []
        self._env_dict = self._build_environment_dict()
        
    def _expand_environment_variables(self, value: str) -> str:
        """
        Expand $ENV{VAR_NAME} patterns in string values.
        
        This method replaces all occurrences of $ENV{VAR_NAME} with the
        actual value of the environment variable VAR_NAME from the system.
        
        Examples:
          "$ENV{HOME}/.gitconfig" -> "/home/username/.gitconfig"
          "$ENV{HOME}/data/cache" -> "/home/username/data/cache"
        
        Args:
            value: String value that may contain $ENV{VAR} patterns
            
        Returns:
            String with all $ENV{VAR} patterns expanded to their actual values
            
        Raises:
            ConfigurationError: If a referenced environment variable is not set
        """
        def replace_env_var(match):
            var_name = match.group(1)
            if var_name in os.environ:
                return os.environ[var_name]
            else:
                logging.warning(f"Environment variable '{var_name}' is not set, "
                               f"using empty string for expansion in: {value}")
                return ""
        
        # Replace all $ENV{VAR} patterns with actual environment variable values
        expanded_value = self.ENV_VAR_PATTERN.sub(replace_env_var, value)
        
        # Also expand any standard environment variables (for backward compatibility)
        expanded_value = os.path.expandvars(expanded_value)
        
        return expanded_value
        
    def _build_environment_dict(self) -> Dict[str, str]:
        """
        Build a dictionary from the environment variable list with expansion.
        
        This method processes each environment variable value and expands
        any $ENV{VAR} patterns to their actual system environment values.
        
        Returns:
            Dictionary of environment variables with expanded values
        """
        env_dict = {}
        for env_var in self.environment_vars:
            # Expand environment variables in the value
            expanded_value = self._expand_environment_variables(env_var.value)
            env_dict[env_var.name] = expanded_value
            logging.debug(f"Environment variable {env_var.name} expanded: "
                         f"'{env_var.value}' -> '{expanded_value}'")
        return env_dict
    
    def get_environment_dict(self) -> Dict[str, str]:
        """
        Get environment variables as a dictionary with expanded values.
        
        Returns:
            Copy of the environment variables dictionary with all expansions applied
        """
        return self._env_dict.copy()
    
    def get_value(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get the value of an environment variable by key.
        
        Args:
            key: Environment variable name to lookup
            default: Default value to return if key not found
            
        Returns:
            Environment variable value (expanded) or default if not found
        """
        return self._env_dict.get(key, default)
    
    def validate_environment(self) -> bool:
        """
        Validate that all environment variable paths exist after expansion.
        
        This method checks common path variables (DL_DIR, SSTATE_DIR, GITCONFIG_FILE)
        to ensure they point to valid locations after environment variable expansion.
        Warnings are issued for missing paths but execution continues as paths 
        might be created during build.
        
        Returns:
            True if validation completes (warnings may still be issued)
        """
        # Check common path variables that should exist
        path_variables = ['DL_DIR', 'SSTATE_DIR', 'GITCONFIG_FILE']
        
        for var_name in path_variables:
            if var_name in self._env_dict:
                path_value = self._env_dict[var_name]
                if not resolver.exists(path_value):
                    logging.warning(f"Environment variable {var_name} path does not exist: {path_value}")
                    # Don't exit here - paths might be created during build process
        
        logging.info(f"Environment configuration validated with {len(self._env_dict)} variables")
        return True
        
    def setup_environment(self, base_env: Dict[str, str]) -> Dict[str, str]:
        """
        Set up environment variables for build processes.
        
        Merges the configured environment variables with a base environment,
        with configured variables taking precedence over existing ones.
        All environment variable values are expanded before being set.
        
        Args:
            base_env: Base environment dictionary (typically os.environ.copy())
            
        Returns:
            Updated environment with all configured variables applied and expanded
        """
        env = base_env.copy()
        
        # Add all configured environment variables (overwrite existing)
        for env_var in self.environment_vars:
            expanded_value = self._expand_environment_variables(env_var.value)
            env[env_var.name] = expanded_value
            logging.debug(f"Set {env_var.name}={expanded_value}")
            
        return env

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
                    ".", 
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
                ".", 
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

# =============================================================================
# Main Entry Point with Enhanced Commands
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
        parser = argparse.ArgumentParser(description="Advantech Board Support Package Registry")
        parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
        parser.add_argument('--registry', '-r', default='bsp-registry.yml', help='BSP Registry file')
        parser.add_argument('--no-color', action='store_true', help='Disable colored output')
        
        # Create subparsers for different commands
        subparsers = parser.add_subparsers(dest='command', help='Command to execute', required=True)

        # Build command
        build_parser = subparsers.add_parser('build', help='Build an image for BSP')
        build_parser.add_argument(
            'bsp_name',
            type=str,
            help='Name of the BSP to build'
        )
        build_parser.add_argument(
            '--clean',
            action='store_true',
            help='Clean before building'
        )
        build_parser.add_argument(
            '--checkout',
            action='store_true',
            help='Checkout and validate build configuration without building (fast)'
        )

        # List command
        subparsers.add_parser('list', help='List available BSPs')

        # List containers command
        subparsers.add_parser('containers', help='List available containers')

        # Export command
        export_parser = subparsers.add_parser('export', help='Export BSP configuration')
        export_parser.add_argument(
            'bsp_name',
            type=str,
            help='Name of the BSP'
        )
        export_parser.add_argument(
            '--output', '-o',
            type=str,
            help='Output file path (default: stdout)'
        )

        # Shell command
        shell_parser = subparsers.add_parser('shell', help='Enter interactive shell for BSP')
        shell_parser.add_argument(
            'bsp_name', 
            type=str, 
            help='Name of the BSP'
        )
        shell_parser.add_argument(
            '--command', '-c',
            type=str,
            dest='shell_command',
            help='Command to execute in shell (optional, if not provided starts interactive shell)'
        )

        args = parser.parse_args()

        # Setup logging based on verbosity
        log_level = logging.DEBUG if args.verbose else logging.INFO

        # Setup logging colors
        if args.no_color or not COLORAMA_AVAILABLE:
            logging.basicConfig(
                level=log_level,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
        else:
            logging.basicConfig(level=log_level)
            logger = logging.getLogger()
            handler = logger.handlers[0]
            handler.setFormatter(ColoramaFormatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))

        # Initialize and run BSP manager
        bsp_mgr = BspManager(args.registry)
        bsp_mgr.initialize()

        # Execute requested command
        if args.command == 'build':
            checkout_only = getattr(args, 'checkout', False)
            bsp_mgr.build_bsp(args.bsp_name, checkout_only=checkout_only)
        elif args.command == 'list':
            bsp_mgr.list_bsp()
        elif args.command == 'containers':
            bsp_mgr.list_containers()
        elif args.command == 'export':
            bsp_mgr.export_bsp_config(
                bsp_name=args.bsp_name,
                output_file=args.output
            )
        elif args.command == 'shell':
            # Use getattr to safely access the shell_command attribute
            shell_command = getattr(args, 'shell_command', None)
            bsp_mgr.shell_into_bsp(
                bsp_name=args.bsp_name,
                command=shell_command
            )
        else:
            # This should not happen since subparsers are required=True
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
    
if __name__ == "__main__":
    # Execute main function and exit with proper code
    sys.exit(main())