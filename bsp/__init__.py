"""
Advantech Board Support Package (BSP) Registry Manager

This package provides a comprehensive command-line interface and Python API for
managing and building Yocto-based BSPs using the KAS build system. It uses a
YAML-based registry (schema v2.0) to define devices, releases, features, and
optional named BSP presets, making reproducible Yocto builds straightforward.

Key Features:
- BSP registry management via YAML configuration files (schema v2.0)
- Device / release / feature decomposition with compatibility checking
- Docker container building and management for reproducible builds
- KAS build system integration for Yocto-based builds
- Interactive shell access to build environments
- Comprehensive error handling and configuration validation

Architecture:
- BspManager: Main coordinator for BSP operations
- V2Resolver: Resolves device+release+features into a build config
- KasManager: Handles KAS build system operations
- EnvironmentManager: Manages build environment variables with expansion
- PathResolver: Utility for path resolution and validation

Typical Usage:
  $ bsp list                              # List BSP presets
  $ bsp list devices                      # List devices
  $ bsp list releases                     # List releases
  $ bsp list features                     # List features
  $ bsp build <preset>                    # Build a named preset
  $ bsp build --device <d> --release <r>  # Build by components
  $ bsp shell <preset>                    # Enter interactive shell for preset
  $ bsp export <preset>                   # Export BSP configuration
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
from .registry_fetcher import (
    DEFAULT_REMOTE_URL,
    DEFAULT_BRANCH,
    RegistryFetcher,
)
from .models import (
    empty_list,
    empty_dict,
    EnvironmentVariable,
    DockerArg,
    Docker,
    Specification,
    GlobalEnvironment,
    NamedEnvironment,
    DeviceBuild,
    BspBuild,
    Device,
    VendorRelease,
    VendorOverride,
    Framework,
    Distro,
    Release,
    FeatureCompatibility,
    Feature,
    BspPreset,
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
from .resolver import ResolvedConfig, V2Resolver
from .path_resolver import PathResolver, resolver
from .environment import EnvironmentManager
from .kas_manager import KasManager
from .bsp_manager import BspManager
from .cli import main

__all__ = [
    # Exceptions
    "COLORAMA_AVAILABLE",
    "ColoramaFormatter",
    "ScriptError",
    "ConfigurationError",
    "BuildError",
    "DockerError",
    "KasError",
    # Registry fetcher
    "DEFAULT_REMOTE_URL",
    "DEFAULT_BRANCH",
    "RegistryFetcher",
    # Factory functions
    "empty_list",
    "empty_dict",
    # Shared data classes
    "EnvironmentVariable",
    "DockerArg",
    "Docker",
    "Specification",
    # v2.0 data classes
    "GlobalEnvironment",
    "DeviceBuild",
    "BspBuild",
    "Device",
    "NamedEnvironment",
    "VendorRelease",
    "VendorOverride",
    "Framework",
    "Distro",
    "Release",
    "FeatureCompatibility",
    "Feature",
    "BspPreset",
    "Registry",
    "RegistryRoot",
    # YAML / Docker utilities
    "read_yaml_file",
    "parse_yaml_file",
    "convert_containers_list_to_dict",
    "get_registry_from_yaml_file",
    "build_docker",
    # Resolver
    "ResolvedConfig",
    "V2Resolver",
    # Core classes
    "PathResolver",
    "resolver",
    "EnvironmentManager",
    "KasManager",
    "BspManager",
    # CLI
    "main",
]
