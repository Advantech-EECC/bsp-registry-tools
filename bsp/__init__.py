"""
Advantech Board Support Package (BSP) Registry Manager

This package provides a comprehensive command-line interface and Python API for
managing and building Yocto-based BSPs using the KAS build system. It uses a
YAML-based registry (schema v2.2) to define devices, releases, features, and
optional named BSP presets, making reproducible Yocto builds straightforward.

Key Features:
- BSP registry management via YAML configuration files (schema v2.2)
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
    DockerVolume,
    Docker,
    Specification,
    GlobalEnvironment,
    NamedEnvironment,
    DeviceBuild,
    BspBuild,
    Device,
    VendorRelease,
    SocVendorOverride,
    VendorOverride,
    Vendor,
    FrameworkOverride,
    Framework,
    Distro,
    Release,
    FeatureCompatibility,
    FeatureReleaseOverride,
    Feature,
    LavaServerConfig,
    RobotTestConfig,
    LavaTestConfig,
    TestingConfig,
    TestDefinitionSource,
    DirectTransportConfig,
    DirectTestConfig,
    BspPreset,
    Registry,
    RegistryRoot,
    DeployConfig,
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
from .lava_client import LavaClient, LavaTestCase, LavaTestSuite
from .lava_job_builder import build_lava_job
from .bsp_manager import BspManager
from .cli import main
from .deployer import ArtifactDeployer, DeployResult, UploadedArtifact
from .gatherer import ArtifactGatherer, GatherResult
from .storage import CloudStorageBackend, create_backend
from .gui import launch_gui, TEXTUAL_AVAILABLE
from .remotes_manager import RemotesManager, RemoteEntry
from .overlay_manager import OverlayManager, OverlayEntry, RepoOverride

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
    "DockerVolume",
    "Docker",
    "Specification",
    # v2.0 data classes
    "GlobalEnvironment",
    "DeviceBuild",
    "BspBuild",
    "Device",
    "NamedEnvironment",
    "VendorRelease",
    "SocVendorOverride",
    "VendorOverride",
    "Framework",
    "Distro",
    "Release",
    "FeatureCompatibility",
    "FeatureReleaseOverride",
    "Feature",
    "LavaServerConfig",
    "RobotTestConfig",
    "LavaTestConfig",
    "TestingConfig",
    "TestDefinitionSource",
    "DirectTransportConfig",
    "DirectTestConfig",
    "BspPreset",
    "Registry",
    "RegistryRoot",
    "DeployConfig",
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
    "LavaClient",
    "LavaTestCase",
    "LavaTestSuite",
    "build_lava_job",
    "BspManager",
    # CLI
    "main",
    # Deployer
    "ArtifactDeployer",
    "DeployResult",
    "UploadedArtifact",
    # Gatherer
    "ArtifactGatherer",
    "GatherResult",
    # Storage
    "CloudStorageBackend",
    "create_backend",
    # GUI
    "launch_gui",
    "TEXTUAL_AVAILABLE",
    # Remotes
    "RemotesManager",
    "RemoteEntry",
    # Overlays
    "OverlayManager",
    "OverlayEntry",
    "RepoOverride",
]
