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
        copy: List of ``{source: destination}`` file-copy entries executed
              before every build that uses this container.  Both paths are
              resolved relative to the registry file's parent directory.
              Entries are merged between named-environment copy and
              device-level copy entries.
    """
    image: Optional[str]
    file: Optional[str]
    args: List[DockerArg] = field(default_factory=empty_list)
    runtime_args: Optional[str] = None
    privileged: bool = False
    copy: List[Dict[str, str]] = field(default_factory=empty_list)


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
class GlobalEnvironment:
    """
    Global build environment applied to every build in the registry.

    Groups the global environment variables and global file-copy entries
    under a single ``environment:`` key in the registry YAML, keeping the
    schema symmetric with ``NamedEnvironment``.

    Attributes:
        variables: Environment variables applied to every build (supports
                   ``$ENV{}`` expansion).
        copy: List of ``{source: destination}`` file-copy entries executed
              inside the build environment before every build.  Both paths are
              resolved relative to the registry file's parent directory (the
              project root mounted inside the container).  These entries run
              first, before named-environment and device-level entries.
    """
    variables: List[EnvironmentVariable] = field(default_factory=empty_list)
    copy: List[Dict[str, str]] = field(default_factory=empty_list)


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
                   (merged on top of the root-level ``environment.variables``
                   list).
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
class VendorRelease:
    """
    A vendor-specific sub-release (e.g. a specific BSP kernel version for a board vendor).

    ``VendorRelease`` entries live inside ``VendorOverride.releases`` and let a
    single top-level release (e.g. ``scarthgap``) expose multiple BSP versions
    for the same vendor (e.g. ``imx-6.6.53``, ``imx-6.12.0``).  The resolver
    adds the matching ``VendorRelease.includes`` after the parent
    ``VendorOverride.includes`` when the caller specifies a ``vendor_release``.

    Attributes:
        slug: Unique identifier for this vendor sub-release (e.g. 'imx-6.6.53')
        description: Human-readable description
        includes: KAS configuration files specific to this vendor sub-release
    """
    slug: str
    description: str
    includes: List[str] = field(default_factory=empty_list)


@dataclass
class SocVendorOverride:
    """
    SoC-vendor-specific KAS configuration overrides within a board-vendor override.

    ``SocVendorOverride`` entries live inside ``VendorOverride.soc_vendors`` and
    allow a single board-vendor override (e.g. Advantech) to carry separate
    include sets and sub-releases for each underlying SoC vendor (e.g. NXP,
    MediaTek, Qualcomm).  The resolver matches the entry whose ``vendor`` field
    equals ``Device.soc_vendor``.

    Include ordering when a ``SocVendorOverride`` is active::

        VendorOverride.includes          (common to all SoC families)
        → SocVendorOverride.includes     (common to this SoC family)
        → VendorRelease.includes         (specific sub-release, if requested)

    Attributes:
        vendor: SoC vendor slug this entry applies to (e.g. 'nxp', 'mediatek').
                Must match ``Device.soc_vendor`` for the entry to be selected.
        includes: KAS configuration files common to all sub-releases for this
                  SoC vendor (e.g. a shared NXP BSP fragment).
        releases: Optional list of vendor sub-releases specific to this SoC
                  vendor (e.g. different NXP i.MX kernel versions).
        distro: Optional distro slug that overrides both the parent
                ``VendorOverride.distro`` and the release's own ``distro``
                field when this SoC vendor override is active.
    """
    vendor: str
    includes: List[str] = field(default_factory=empty_list)
    releases: List[VendorRelease] = field(default_factory=empty_list)
    distro: Optional[str] = None


@dataclass
class VendorOverride:
    """
    Vendor-specific KAS configuration overrides for a release.

    Each ``VendorOverride`` entry groups, for a single board vendor:

    * ``includes`` — KAS files added for **every** build targeting that vendor
      (e.g. a common Advantech BSP meta-layer fragment).
    * ``releases`` — Optional list of vendor sub-releases (e.g. different NXP
      i.MX kernel versions).  When the resolver is given a ``vendor_release``
      slug it looks up the matching ``VendorRelease`` entry and appends its
      includes after the common ``includes``.
    * ``soc_vendors`` — Optional list of :class:`SocVendorOverride` entries,
      one per SoC vendor family (e.g. NXP, MediaTek, Qualcomm).  When
      present the resolver selects the entry whose ``vendor`` field matches
      ``Device.soc_vendor`` and applies its ``includes`` and ``releases``
      **after** the board-vendor-level ``includes``.  Use this instead of
      (or in addition to) ``releases`` when a single board vendor ships
      products based on multiple SoC families.
    * ``slug`` — Optional unique identifier that allows a BSP preset to
      reference this exact override entry via the preset's ``override`` field,
      independently of the ``vendor`` matching logic.  Multiple overrides for
      the same vendor can coexist when they each carry a distinct slug.
    * ``distro`` — Optional distro slug that overrides the release's own
      ``distro`` field when this vendor override is active.  Allows a specific
      vendor/BSP combination to be built against a different distro than the
      parent release normally uses.  A ``SocVendorOverride.distro`` takes
      precedence over this field when both are set.

    Attributes:
        vendor: Board vendor name this override applies to
        includes: KAS files common to all sub-releases for this vendor
        releases: Optional list of vendor-specific sub-releases (used when
                  all boards from this vendor share the same SoC family)
        soc_vendors: Optional list of per-SoC-vendor override entries (used
                     when the board vendor ships products with multiple SoC
                     families)
        slug: Optional unique identifier for this override entry
        distro: Optional distro slug that overrides the release distro for
                this vendor override
    """
    vendor: str
    includes: List[str] = field(default_factory=empty_list)
    releases: List[VendorRelease] = field(default_factory=empty_list)
    soc_vendors: List[SocVendorOverride] = field(default_factory=empty_list)
    slug: Optional[str] = None
    distro: Optional[str] = None


@dataclass
class Vendor:
    """
    Board vendor definition.

    A ``Vendor`` entry in ``Registry.vendors`` describes a hardware board
    vendor (e.g. Advantech, QEMU).  The resolver matches the vendor ``slug``
    against ``Device.vendor`` and, when a match is found, prepends the
    vendor's ``includes`` in the KAS file list after the distro includes.

    Attributes:
        slug: Unique identifier for the vendor (e.g., 'advantech', 'qemu').
              Must match the ``vendor`` field of the device definitions that
              belong to this vendor.
        name: Human-readable display name (e.g., 'Advantech')
        description: Optional longer description of the vendor
        website: Optional vendor website URL
        includes: KAS configuration files common to all boards from this vendor
    """
    slug: str
    name: str
    description: str = ""
    website: str = ""
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
        vendor_overrides: Vendor-specific KAS configuration overrides.  Each
                          entry targets a single board vendor and may contain
                          both common includes (applied for every build of that
                          vendor) and a list of sub-releases (e.g. different
                          kernel / BSP versions).  The resolver selects the
                          entry whose ``vendor`` matches the device's board
                          vendor, appends its ``includes``, and—when a
                          ``vendor_release`` slug is given—appends the matching
                          sub-release ``includes`` as well.  Multiple sub-
                          releases for the same Yocto release (e.g.
                          ``imx-6.6.53``, ``imx-6.12.0``) can thus coexist
                          without duplicating the Yocto release entry.
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
    vendor_overrides: List[VendorOverride] = field(default_factory=empty_list)
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
        vendor_overrides: Optional list of vendor-specific KAS configuration
                          overrides for this feature.  Works identically to
                          ``Release.vendor_overrides`` but is scoped to a
                          single feature: the resolver matches entries by
                          ``device.vendor`` (and ``device.soc_vendor`` when
                          ``soc_vendors`` are defined) and appends the
                          resulting includes *after* the feature's base
                          ``includes``.  ``VendorRelease`` sub-entries inside
                          a feature override are selected via the same
                          ``vendor_release_slug`` passed to ``resolve()``.
    """
    slug: str
    description: str
    compatibility: Optional[FeatureCompatibility] = None
    compatible_with: List[str] = field(default_factory=empty_list)
    includes: List[str] = field(default_factory=empty_list)
    local_conf: List[str] = field(default_factory=empty_list)
    env: List[EnvironmentVariable] = field(default_factory=empty_list)
    vendor_overrides: List[VendorOverride] = field(default_factory=empty_list)


@dataclass
class BspPreset:
    """
    Named BSP preset (optional shortcut for a device+release+features combination).

    A preset can target either a single release (``release``) or multiple
    releases at once (``releases``).  Exactly one of these two fields must be
    provided.  When ``releases`` is used the resolver expands the preset into
    one virtual preset per release; each expanded preset is named
    ``{name}-{release_slug}`` and its build path is auto-composed.

    Attributes:
        name: Unique preset name
        description: Human-readable description
        device: Device slug (references a device in registry.devices)
        release: Single release slug (mutually exclusive with ``releases``).
        releases: List of release slugs (mutually exclusive with ``release``).
                  The resolver expands each entry into an individual virtual
                  preset named ``{name}-{release_slug}``.
        vendor_release: Optional vendor sub-release slug (references a
                        ``VendorRelease.slug`` inside the matching
                        ``VendorOverride`` entry for the device's board vendor).
                        When set the resolver appends the sub-release's includes
                        after the vendor's common includes.
        override: Optional ``VendorOverride.slug`` to select a specific
                  vendor override entry by its slug rather than by vendor
                  matching.  When set the resolver looks up the matching
                  ``VendorOverride`` entry in the release's ``vendor_overrides``
                  list and applies its includes (and its ``distro`` override, if
                  present) regardless of the device's vendor field.
        features: List of feature slugs to enable (references registry.features)
        local_conf: Optional block of local.conf lines to append for this
                    preset.  Specified as a YAML block scalar (``|``); each
                    non-empty line is appended to the resolved local_conf
                    after device- and feature-level entries.
        targets: Optional list of Bitbake build targets (images/recipes) to
                 pass to KAS.  When non-empty these are written into the
                 ``target`` section of the generated KAS YAML file.
        build: Optional build configuration (container + output path).  When
               absent the container is taken from the release's named
               environment and the path is auto-composed from the distro,
               device, release, and feature slugs.  When ``releases`` is used,
               the ``path`` sub-field is ignored and the path is always
               auto-composed; the ``container`` override is still applied.
    """
    name: str
    description: str
    device: str
    release: Optional[str] = None
    releases: List[str] = field(default_factory=empty_list)
    vendor_release: Optional[str] = None
    override: Optional[str] = None
    features: List[str] = field(default_factory=empty_list)
    local_conf: Optional[str] = None
    targets: List[str] = field(default_factory=empty_list)
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
        vendors: Optional list of board vendor definitions.  When a vendor's
                 ``slug`` matches a device's ``vendor`` field the resolver
                 prepends the vendor's ``includes`` in the KAS file list
                 (after distro includes, before release includes).
    """
    devices: List[Device] = field(default_factory=empty_list)
    releases: List[Release] = field(default_factory=empty_list)
    features: List[Feature] = field(default_factory=empty_list)
    bsp: Optional[List[BspPreset]] = field(default_factory=empty_list)
    frameworks: List[Framework] = field(default_factory=empty_list)
    distro: List[Distro] = field(default_factory=empty_list)
    vendors: List[Vendor] = field(default_factory=empty_list)


@dataclass
class RegistryRoot:
    """
    Root container for the v2.0 registry configuration.

    Attributes:
        specification: Specification version information (must be '2.0')
        registry: Main registry data containing devices, releases, features, and presets
        containers: Dictionary of Docker container definitions keyed by name
        environment: Global environment applied to every build.  Contains
                     ``variables`` (``$ENV{}``-expandable) and ``copy``
                     (file-copy entries executed inside the build environment
                     before every build).
        environments: Optional dictionary of named environments.  Each entry
                      bundles a container reference and environment variables.
                      The special name ``"default"`` is applied to any release
                      that does not explicitly name an environment.
    """
    specification: Specification
    registry: Registry
    containers: Optional[Dict[str, Docker]] = field(default_factory=empty_dict)
    environment: Optional[GlobalEnvironment] = None
    environments: Optional[Dict[str, NamedEnvironment]] = field(default_factory=empty_dict)
