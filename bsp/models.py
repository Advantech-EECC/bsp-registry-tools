"""
Configuration data classes for BSP registry definitions (schema v2.0).
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict

# =============================================================================
# Factory Functions
# =============================================================================


def empty_list():
    """Factory function for creating empty lists in dataclass fields."""
    return []


def empty_dict():
    """Factory function for creating empty dictionaries in dataclass fields."""
    return {}


# =============================================================================
# Shared Data Classes (used across v1 and v2)
# =============================================================================

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
        runtime_args: Extra arguments appended to the container engine
                      ``run`` command (e.g. ``-p 2222:2222
                      --device=/dev/net/tun --cap-add=NET_ADMIN``).
                      Passed to kas-container via ``KAS_CONTAINER_ARGS``.
        privileged: Run container in privileged mode (enables --isar for kas-container)
    """
    image: Optional[str]
    file: Optional[str]
    args: List[DockerArg] = field(default_factory=empty_list)
    runtime_args: Optional[str] = None
    privileged: bool = False


@dataclass
class Specification:
    """
    Registry specification version.

    Attributes:
        version: Specification version string (e.g., '2.0')
    """
    version: str


# =============================================================================
# v2.0 Data Classes
# =============================================================================

@dataclass
class NamedEnvironment:
    """
    A named build environment bundling a container reference and environment
    variables.

    Named environments allow different builds (especially different releases)
    to use distinct container images and variable sets without repeating the
    configuration on every device or release entry.

    A special name ``"default"`` is used as the fallback environment for any
    release that does not explicitly specify one.

    Attributes:
        container: Optional container name (references the top-level
                   ``containers`` dict).  When ``None`` the device's own
                   ``build.container`` must be set.
        variables: Environment variables provided by this environment
                   (merged on top of the root-level ``environment`` list).
        copy: List of ``{source: destination}`` file-copy entries executed
              before every build that uses this environment.  Both paths are
              resolved relative to the registry file's parent directory.
              Entries are prepended before any device-level copy entries.
    """
    container: Optional[str] = None
    variables: List[EnvironmentVariable] = field(default_factory=empty_list)
    copy: List[Dict[str, str]] = field(default_factory=empty_list)


@dataclass
class DeviceBuild:
    """
    Build configuration for a hardware device (legacy – kept for backward
    compatibility with older registry files that still use the nested
    ``build:`` block inside a device entry).

    New registries should place device-level KAS includes directly on the
    ``Device`` and use ``BspPreset.build`` for the container and output
    path.

    Attributes:
        path: Build output directory for Yocto artifacts
        container: Optional container name override (references containers
                   section).  When ``None`` the active named environment's
                   container is used instead.
        includes: List of device-specific KAS configuration files
        local_conf: List of local.conf lines to append for this device
        copy: List of ``{source: destination}`` file-copy entries.  Each
              entry copies a single file (source) to a directory or path
              (destination) before the build starts.  Both paths are
              resolved relative to the registry file's parent directory.
    """
    path: str = ""
    container: Optional[str] = None
    includes: List[str] = field(default_factory=empty_list)
    local_conf: List[str] = field(default_factory=empty_list)
    copy: List[Dict[str, str]] = field(default_factory=empty_list)


@dataclass
class BspBuild:
    """
    Build configuration for a BSP preset.

    When present on a ``BspPreset``, this section controls the container
    used for the build and the output directory.  Both fields are optional:

    * If ``container`` is omitted the container is taken from the release's
      named environment (or the ``"default"`` environment as a fallback).
    * If ``path`` is omitted the resolver auto-composes a path from the
      distro slug, device slug, release slug, and any feature slugs under
      the top-level ``build/`` directory.

    Attributes:
        container: Optional container name (references the top-level
                   ``containers`` dict).
        path: Optional build output directory.  When ``None`` the resolver
              derives the path automatically.
    """
    container: Optional[str] = None
    path: Optional[str] = None


@dataclass
class Device:
    """
    Hardware device/board definition.

    Attributes:
        slug: Unique identifier for the device
        description: Human-readable description
        vendor: Board vendor name (e.g., 'advantech', 'qemu')
        soc_vendor: Silicon vendor name (e.g., 'nxp', 'intel', 'arm')
        includes: List of device-specific KAS configuration files
        local_conf: List of local.conf lines to append for this device
        copy: List of ``{source: destination}`` file-copy entries executed
              before the build.  Both paths resolve relative to the
              registry file's parent directory.
        soc_family: Optional SoC family identifier (e.g., 'imx8', 'cortex-a57')
        build: Deprecated – legacy nested build block.  Use ``includes`` /
               ``local_conf`` / ``copy`` directly and ``BspPreset.build``
               for container and path.
    """
    slug: str
    description: str
    vendor: str
    soc_vendor: str
    includes: List[str] = field(default_factory=empty_list)
    local_conf: List[str] = field(default_factory=empty_list)
    copy: List[Dict[str, str]] = field(default_factory=empty_list)
    soc_family: Optional[str] = None
    build: Optional[DeviceBuild] = None


@dataclass
class VendorIncludes:
    """
    Vendor-specific KAS includes for a release.

    Attributes:
        vendor: Board vendor name this applies to
        includes: List of vendor-specific KAS files for this release
    """
    vendor: str
    includes: List[str] = field(default_factory=empty_list)


@dataclass
class Framework:
    """
    Build-system framework definition (e.g. Yocto, Isar).

    A ``Framework`` describes a top-level build system that one or more
    distros are built on.  Distros reference a framework by its ``slug``
    via the ``Distro.framework`` field.  Features can restrict themselves
    to specific frameworks via ``Feature.compatible_with``.

    Attributes:
        slug: Unique identifier for the framework (e.g., 'yocto', 'isar')
        description: Human-readable description
        vendor: Framework vendor/maintainer name
        includes: KAS configuration files that configure this framework
    """
    slug: str
    description: str
    vendor: str
    includes: List[str] = field(default_factory=empty_list)


@dataclass
class Distro:
    """
    Linux distribution / build-system definition.

    A ``Distro`` groups the KAS configuration files that set up a particular
    build system or Linux distribution (e.g. Poky, Isar).  Releases reference
    a distro by its ``slug`` via the ``Release.distro`` field so that the
    resolver can prepend the distro includes before the release includes.

    Attributes:
        slug: Unique identifier for the distro (e.g., 'poky', 'isar')
        description: Human-readable description
        vendor: Distro vendor/maintainer name (e.g., 'yocto', 'siemens')
        includes: KAS configuration files that configure this distro
        framework: Optional slug of the build-system framework this distro
                   is based on (references ``Registry.frameworks``).  Used
                   by ``Feature.compatible_with`` checks.
    """
    slug: str
    description: str
    vendor: str = ""
    includes: List[str] = field(default_factory=empty_list)
    framework: Optional[str] = None


@dataclass
class Release:
    """
    Yocto/Isar release definition.

    Attributes:
        slug: Unique identifier for the release (e.g., 'scarthgap')
        description: Human-readable description
        includes: Base KAS configuration files for this release
        yocto_version: Yocto Project version string (e.g., '5.0')
        isar_version: Isar version string (optional)
        vendor_includes: Vendor-specific KAS includes for this release
        environment: Optional name of the named environment to use for this
                     release (references ``RegistryRoot.environments``).
                     When omitted the ``"default"`` named environment is used
                     if one is defined, otherwise the global environment list
                     and device container apply.
        distro: Optional slug of the distro this release belongs to
                (references ``Registry.distro``).  When set the resolver
                prepends the distro's includes before the release includes.
    """
    slug: str
    description: str
    includes: List[str] = field(default_factory=empty_list)
    yocto_version: Optional[str] = None
    isar_version: Optional[str] = None
    vendor_includes: List[VendorIncludes] = field(default_factory=empty_list)
    environment: Optional[str] = None
    distro: Optional[str] = None


@dataclass
class FeatureCompatibility:
    """
    Compatibility constraints for a feature.

    Empty lists mean "all" (no restriction on that dimension).

    Attributes:
        vendor: List of compatible board vendors (empty = all vendors)
        soc_vendor: List of compatible SoC vendors (empty = all)
        soc_family: List of compatible SoC families (empty = all)
    """
    vendor: List[str] = field(default_factory=empty_list)
    soc_vendor: List[str] = field(default_factory=empty_list)
    soc_family: List[str] = field(default_factory=empty_list)


@dataclass
class Feature:
    """
    Optional BSP feature definition (e.g., OTA update, secure boot).

    Attributes:
        slug: Unique identifier for the feature
        description: Human-readable description
        compatibility: Device compatibility constraints (vendor / SoC-level).
        compatible_with: Optional list of framework or distro slugs this
                         feature is restricted to.  An empty list means no
                         framework/distro restriction.  When non-empty the
                         resolver checks that the release's distro slug **or**
                         the distro's framework slug appears in this list; if
                         neither matches the build exits with an error.
        includes: KAS configuration files that enable this feature
        local_conf: local.conf lines to append when feature is enabled
        env: Environment variables required/set by this feature
    """
    slug: str
    description: str
    compatibility: Optional[FeatureCompatibility] = None
    compatible_with: List[str] = field(default_factory=empty_list)
    includes: List[str] = field(default_factory=empty_list)
    local_conf: List[str] = field(default_factory=empty_list)
    env: List[EnvironmentVariable] = field(default_factory=empty_list)


@dataclass
class BspPreset:
    """
    Named BSP preset (optional shortcut for a device+release+features combination).

    Attributes:
        name: Unique preset name
        description: Human-readable description
        device: Device slug (references a device in registry.devices)
        release: Release slug (references a release in registry.releases)
        features: List of feature slugs to enable (references registry.features)
        build: Optional build configuration (container + output path).  When
               absent the container is taken from the release's named
               environment and the path is auto-composed from the distro,
               device, release, and feature slugs.
    """
    name: str
    description: str
    device: str
    release: str
    features: List[str] = field(default_factory=empty_list)
    build: Optional[BspBuild] = None


@dataclass
class Registry:
    """
    Main v2.0 registry containing devices, releases, features, distros, and presets.

    Attributes:
        devices: List of hardware device definitions
        releases: List of Yocto/Isar release definitions
        features: List of optional feature definitions
        bsp: Optional list of named BSP presets (shortcuts)
        frameworks: Optional list of build-system framework definitions
        distro: Optional list of distribution/build-system definitions
    """
    devices: List[Device] = field(default_factory=empty_list)
    releases: List[Release] = field(default_factory=empty_list)
    features: List[Feature] = field(default_factory=empty_list)
    bsp: Optional[List[BspPreset]] = field(default_factory=empty_list)
    frameworks: List[Framework] = field(default_factory=empty_list)
    distro: List[Distro] = field(default_factory=empty_list)


@dataclass
class RegistryRoot:
    """
    Root container for the v2.0 registry configuration.

    Attributes:
        specification: Specification version information (must be '2.0')
        registry: Main registry data containing devices, releases, features, and presets
        containers: Dictionary of Docker container definitions keyed by name
        environment: Global environment variables for all builds (supports $ENV{} expansion)
        environments: Optional dictionary of named environments.  Each entry
                      bundles a container reference and environment variables.
                      The special name ``"default"`` is applied to any release
                      that does not explicitly name an environment.
        copy: Global list of ``{source: destination}`` file-copy entries
              executed before every build.  Both paths are resolved relative
              to the registry file's parent directory.  These entries are
              applied first, before named-environment and device-level entries.
    """
    specification: Specification
    registry: Registry
    containers: Optional[Dict[str, Docker]] = field(default_factory=empty_dict)
    environment: Optional[List[EnvironmentVariable]] = field(default_factory=empty_list)
    environments: Optional[Dict[str, NamedEnvironment]] = field(default_factory=empty_dict)
    copy: List[Dict[str, str]] = field(default_factory=empty_list)
