"""
Advantech Board Support Package (BSP) Registry Manager

This package provides a comprehensive command-line interface for managing and building
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
  $ bsp list                    # List available BSPs
  $ bsp build <bsp_name>        # Build a specific BSP
  $ bsp shell <bsp_name>        # Enter interactive shell for BSP
  $ bsp export <bsp_name>       # Export BSP configuration
"""

from .exceptions import (
    COLORAMA_AVAILABLE,
    ColoramaFormatter,
    ScriptError,
    ConfigurationError,
    BuildError,
    DockerError,
    KasError,
)
from .models import (
    empty_list,
    empty_dict,
    EnvironmentVariable,
    DockerArg,
    Docker,
    ContainerDefinition,
    BuildEnvironment,
    BuildSetup,
    Specification,
    OperatingSystem,
    BSP,
    Registry,
    RegistryRoot,
)
from .utils import (
    read_yaml_file,
    parse_yaml_file,
    convert_containers_list_to_dict,
    get_registry_from_yaml_file,
    build_docker,
)
from .path_resolver import PathResolver, resolver
from .environment import EnvironmentManager
from .kas_manager import KasManager
from .bsp_manager import BspManager
from .registry_fetcher import RegistryFetcher
from .cli import main

__all__ = [
    # Logging / exceptions
    "COLORAMA_AVAILABLE",
    "ColoramaFormatter",
    "ScriptError",
    "ConfigurationError",
    "BuildError",
    "DockerError",
    "KasError",
    # Factory functions
    "empty_list",
    "empty_dict",
    # Data classes
    "EnvironmentVariable",
    "DockerArg",
    "Docker",
    "ContainerDefinition",
    "BuildEnvironment",
    "BuildSetup",
    "Specification",
    "OperatingSystem",
    "BSP",
    "Registry",
    "RegistryRoot",
    # YAML / Docker utilities
    "read_yaml_file",
    "parse_yaml_file",
    "convert_containers_list_to_dict",
    "get_registry_from_yaml_file",
    "build_docker",
    # Core classes
    "PathResolver",
    "resolver",
    "EnvironmentManager",
    "KasManager",
    "BspManager",
    "RegistryFetcher",
    # CLI
    "main",
]
