"""
V2 registry resolver: combines device + release + features into a build configuration.
"""

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from .models import (
    BspBuild,
    BspPreset,
    Device,
    Distro,
    Docker,
    EnvironmentVariable,
    Feature,
    Framework,
    NamedEnvironment,
    Release,
    RegistryRoot,
    Vendor,
    VendorOverride,
    empty_list,
)

# =============================================================================
# Resolved Configuration
# =============================================================================


@dataclass
class ResolvedConfig:
    """
    Result of resolving a device + release + features combination.

    Attributes:
        device: Resolved device definition
        release: Resolved release definition
        features: List of resolved feature definitions
        kas_files: Ordered list of KAS configuration file paths
        build_path: Build output directory path
        container: Docker configuration for the build environment
        local_conf: Combined local.conf lines from device and features
        env: Combined environment variables from features
        copy: Ordered list of ``{source: destination}`` file-copy entries
              resolved from the global registry copy, the active named
              environment copy, and the device-level copy (in that order).
              All paths are relative to the registry file's parent directory.
        effective_distro: Effective distro slug used for the build.  This is
                          the vendor override's distro (if set) or the
                          release's distro.  Used by ``_compose_build_path``
                          and available to callers that need the actual distro.
    """
    device: Device
    release: Release
    features: List[Feature] = field(default_factory=empty_list)
    kas_files: List[str] = field(default_factory=empty_list)
    build_path: str = ""
    container: Optional[Docker] = None
    local_conf: List[str] = field(default_factory=empty_list)
    env: List[EnvironmentVariable] = field(default_factory=empty_list)
    copy: List[Dict[str, str]] = field(default_factory=empty_list)
    effective_distro: Optional[str] = None


# =============================================================================
# V2 Resolver
# =============================================================================


class V2Resolver:
    """
    Resolver for v2.0 registry format.

    Combines device, release, and feature definitions into a single
    ResolvedConfig that can be used to drive a KAS build.
    """

    def __init__(self, model: RegistryRoot, containers: Dict[str, Docker]):
        """
        Initialize the resolver.

        Args:
            model: Parsed RegistryRoot (v2.0)
            containers: Dictionary of Docker container configurations
        """
        self.model = model
        self.containers = containers
        self.logger = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Named environment helper
    # ------------------------------------------------------------------

    def get_named_environment(self, release: Release) -> Optional[NamedEnvironment]:
        """
        Return the NamedEnvironment that should be applied for *release*.

        Resolution order:
        1. If ``release.environment`` is set, look it up in
           ``model.environments``; exit with an error if not found.
        2. If no name is specified on the release but a ``"default"``
           environment exists, return that.
        3. Otherwise return ``None`` (no named environment applies).

        Args:
            release: The release being resolved.

        Returns:
            Matching NamedEnvironment or None.

        Raises:
            SystemExit: If an explicitly-named environment is not found.
        """
        envs = self.model.environments or {}

        if release.environment:
            if release.environment in envs:
                return envs[release.environment]
            self.logger.error(
                f"Named environment '{release.environment}' referenced by release "
                f"'{release.slug}' not found in registry environments"
            )
            available = ", ".join(envs.keys()) or "(none)"
            self.logger.info(f"Available environments: {available}")
            sys.exit(1)

        # Fall back to "default" named environment if present
        return envs.get("default")

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def get_device(self, slug: str) -> Device:
        """
        Retrieve a device definition by slug.

        Raises:
            SystemExit: If device slug is not found
        """
        for device in self.model.registry.devices:
            if device.slug == slug:
                return device
        self.logger.error(f"Device not found: '{slug}'")
        available = ", ".join(d.slug for d in self.model.registry.devices)
        self.logger.info(f"Available devices: {available or '(none)'}")
        sys.exit(1)

    def get_release(self, slug: str) -> Release:
        """
        Retrieve a release definition by slug.

        Raises:
            SystemExit: If release slug is not found
        """
        for release in self.model.registry.releases:
            if release.slug == slug:
                return release
        self.logger.error(f"Release not found: '{slug}'")
        available = ", ".join(r.slug for r in self.model.registry.releases)
        self.logger.info(f"Available releases: {available or '(none)'}")
        sys.exit(1)

    def get_feature(self, slug: str) -> Feature:
        """
        Retrieve a feature definition by slug.

        Raises:
            SystemExit: If feature slug is not found
        """
        for feature in self.model.registry.features:
            if feature.slug == slug:
                return feature
        self.logger.error(f"Feature not found: '{slug}'")
        available = ", ".join(f.slug for f in self.model.registry.features)
        self.logger.info(f"Available features: {available or '(none)'}")
        sys.exit(1)

    def get_distro(self, slug: str) -> Distro:
        """
        Retrieve a distro definition by slug.

        Raises:
            SystemExit: If distro slug is not found
        """
        for distro in self.model.registry.distro:
            if distro.slug == slug:
                return distro
        self.logger.error(f"Distro not found: '{slug}'")
        available = ", ".join(d.slug for d in self.model.registry.distro)
        self.logger.info(f"Available distros: {available or '(none)'}")
        sys.exit(1)

    def list_distros(self) -> List[Distro]:
        """Return all distro definitions in the registry."""
        return list(self.model.registry.distro)

    def get_framework(self, slug: str) -> Framework:
        """
        Retrieve a framework definition by slug.

        Raises:
            SystemExit: If framework slug is not found
        """
        for framework in self.model.registry.frameworks:
            if framework.slug == slug:
                return framework
        self.logger.error(f"Framework not found: '{slug}'")
        available = ", ".join(f.slug for f in self.model.registry.frameworks)
        self.logger.info(f"Available frameworks: {available or '(none)'}")
        sys.exit(1)

    def list_frameworks(self) -> List[Framework]:
        """Return all framework definitions in the registry."""
        return list(self.model.registry.frameworks)

    def get_vendor(self, slug: str) -> Vendor:
        """
        Retrieve a vendor definition by slug.

        Raises:
            SystemExit: If vendor slug is not found
        """
        for vendor in self.model.registry.vendors:
            if vendor.slug == slug:
                return vendor
        self.logger.error(f"Vendor not found: '{slug}'")
        available = ", ".join(v.slug for v in self.model.registry.vendors)
        self.logger.info(f"Available vendors: {available or '(none)'}")
        sys.exit(1)

    def list_vendors(self) -> List[Vendor]:
        """Return all vendor definitions in the registry."""
        return list(self.model.registry.vendors)

    # ------------------------------------------------------------------
    # Compatibility check
    # ------------------------------------------------------------------

    def check_feature_compatibility(self, feature: Feature, device: Device) -> bool:
        """
        Check whether a feature is compatible with the given device.

        An empty list in compatibility means "all" (no restriction on that axis).

        Args:
            feature: Feature to check
            device: Target device

        Returns:
            True if compatible, False otherwise (also logs a clear error)
        """
        if feature.compatibility is None:
            return True

        compat = feature.compatibility

        if compat.vendor and device.vendor not in compat.vendor:
            self.logger.error(
                f"Feature '{feature.slug}' is not compatible with board vendor "
                f"'{device.vendor}'. Compatible vendors: {compat.vendor}"
            )
            return False

        if compat.soc_vendor and device.soc_vendor not in compat.soc_vendor:
            self.logger.error(
                f"Feature '{feature.slug}' is not compatible with SoC vendor "
                f"'{device.soc_vendor}'. Compatible SoC vendors: {compat.soc_vendor}"
            )
            return False

        if compat.soc_family:
            device_soc_family = device.soc_family or ""
            if device_soc_family not in compat.soc_family:
                self.logger.error(
                    f"Feature '{feature.slug}' is not compatible with SoC family "
                    f"'{device_soc_family}'. Compatible SoC families: {compat.soc_family}"
                )
                return False

        return True

    def check_feature_framework_compatibility(
        self,
        feature: Feature,
        release: Release,
        effective_distro_slug: Optional[str] = None,
    ) -> bool:
        """
        Check whether a feature is compatible with the framework/distro of the
        given release, based on the feature's ``compatible_with`` list.

        A feature is considered compatible when **any** of the following is true:

        * ``feature.compatible_with`` is empty (no restriction).
        * The effective distro slug appears in ``compatible_with``.
        * The effective distro's ``framework`` slug appears in ``compatible_with``.

        The *effective* distro is ``effective_distro_slug`` when provided (e.g.
        a vendor override's distro), otherwise ``release.distro``.  Passing the
        effective distro ensures that features are checked against the distro
        that will actually be used for the build rather than the release's
        default distro.

        When ``compatible_with`` is non-empty but no distro is resolvable, the
        feature is treated as incompatible and an error is logged.

        Args:
            feature: Feature to check.
            release: Release being resolved.
            effective_distro_slug: Optional override distro slug.  When set
                this distro is used for the compatibility check instead of
                ``release.distro``.

        Returns:
            True if compatible, False otherwise (also logs a clear error).
        """
        if not feature.compatible_with:
            return True

        distro_slug = effective_distro_slug if effective_distro_slug is not None else release.distro

        if not distro_slug:
            self.logger.error(
                f"Feature '{feature.slug}' has compatible_with={feature.compatible_with} "
                f"but release '{release.slug}' does not specify a distro – "
                f"framework/distro compatibility cannot be determined"
            )
            return False

        # Accept if the distro slug itself is listed
        if distro_slug in feature.compatible_with:
            return True

        # Accept if the distro's framework slug is listed
        distro_obj = self.get_distro(distro_slug)
        if distro_obj.framework and distro_obj.framework in feature.compatible_with:
            return True

        self.logger.error(
            f"Feature '{feature.slug}' is not compatible with distro '{distro_slug}' "
            f"(framework: '{distro_obj.framework}'). "
            f"Compatible frameworks/distros: {feature.compatible_with}"
        )
        return False

    # ------------------------------------------------------------------
    # Core resolver
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_vendor_overrides(
        vendor_overrides: List[VendorOverride],
        device_vendor: str,
        vendor_release_slug: Optional[str] = None,
        override_slug: Optional[str] = None,
    ) -> List[str]:
        """
        Return KAS include paths from *vendor_overrides* for *device_vendor*.

        Resolution when *override_slug* is given:
        1. Find the ``VendorOverride`` entry whose ``slug`` matches
           *override_slug*.  If none found, return an empty list.
        2. Always add ``VendorOverride.includes`` (common vendor includes).

        Resolution when *override_slug* is **not** given (legacy vendor matching):
        1. Find the ``VendorOverride`` entry whose ``vendor`` matches
           *device_vendor*.  If none found, return an empty list.
        2. Always add ``VendorOverride.includes`` (common vendor includes).
        3. If *vendor_release_slug* is given, find the matching
           ``VendorRelease`` inside the override and append its includes.
           An unrecognized slug is silently ignored (callers validate earlier).

        Args:
            vendor_overrides: List of ``VendorOverride`` entries from a release.
            device_vendor: Board vendor of the device being resolved.
            vendor_release_slug: Optional sub-release slug to look up.
            override_slug: Optional ``VendorOverride.slug`` to select a
                specific override entry by slug instead of vendor matching.

        Returns:
            Flat list of KAS file paths to append.
        """
        result: List[str] = []
        if override_slug:
            for vo in vendor_overrides:
                if vo.slug == override_slug:
                    result.extend(vo.includes)
                    break
        else:
            for vo in vendor_overrides:
                if vo.vendor == device_vendor:
                    result.extend(vo.includes)
                    if vendor_release_slug:
                        for vr in vo.releases:
                            if vr.slug == vendor_release_slug:
                                result.extend(vr.includes)
                                break
                    break
        return result

    def resolve(
        self,
        device_slug: str,
        release_slug: str,
        feature_slugs: Optional[List[str]] = None,
        vendor_release_slug: Optional[str] = None,
        override_slug: Optional[str] = None,
    ) -> "ResolvedConfig":
        """
        Resolve device + release + features into a ResolvedConfig.

        Merging order for KAS files:
          framework.includes -> distro.includes (release.distro or override.distro)
          -> registry.vendors[device.vendor].includes
          -> release.includes -> release.vendor_overrides[device.vendor or override.slug].includes
          -> release.vendor_overrides[device.vendor].releases[vendor_release].includes
          -> device.includes -> feature.includes
        Merging order for local_conf:  device.local_conf -> feature.local_conf (in order)

        Args:
            device_slug: Device slug to build for
            release_slug: Release slug to use
            feature_slugs: Optional list of feature slugs to enable
            vendor_release_slug: Optional vendor sub-release slug.  When set
                the resolver looks for a matching ``VendorRelease`` inside the
                release's ``VendorOverride`` for the device's board vendor and
                appends its includes after the vendor's common includes.
            override_slug: Optional ``VendorOverride.slug`` to select a specific
                vendor override entry by its slug.  When set the resolver uses
                the matching override entry's includes (and its ``distro`` field,
                if present, to override the release's distro).  Cannot be used
                together with ``vendor_release_slug``.

        Returns:
            ResolvedConfig ready to drive a build

        Raises:
            SystemExit: If any slug is not found or a feature is incompatible
        """
        feature_slugs = feature_slugs or []

        device = self.get_device(device_slug)
        release = self.get_release(release_slug)
        features = [self.get_feature(s) for s in feature_slugs]

        # Resolve the active vendor override entry (used for distro override and includes)
        active_vendor_override: Optional[VendorOverride] = None
        if override_slug:
            active_vendor_override = next(
                (vo for vo in release.vendor_overrides if vo.slug == override_slug),
                None,
            )
            if active_vendor_override is None:
                available = ", ".join(
                    vo.slug for vo in release.vendor_overrides if vo.slug
                ) or "(none)"
                self.logger.error(
                    f"override '{override_slug}' not found in release "
                    f"'{release_slug}' vendor_overrides. "
                    f"Available slugs: {available}"
                )
                sys.exit(1)

        # Validate vendor_release_slug when provided
        if vendor_release_slug:
            matching_vo = next(
                (vo for vo in release.vendor_overrides if vo.vendor == device.vendor),
                None,
            )
            if matching_vo is None:
                self.logger.error(
                    f"vendor_release '{vendor_release_slug}' requested but release "
                    f"'{release_slug}' has no vendor_overrides entry for vendor "
                    f"'{device.vendor}'"
                )
                sys.exit(1)
            matching_vr = next(
                (vr for vr in matching_vo.releases if vr.slug == vendor_release_slug),
                None,
            )
            if matching_vr is None:
                available = ", ".join(vr.slug for vr in matching_vo.releases) or "(none)"
                self.logger.error(
                    f"vendor_release '{vendor_release_slug}' not found in release "
                    f"'{release_slug}' / vendor '{device.vendor}'. "
                    f"Available: {available}"
                )
                sys.exit(1)
            # Pin the active override so its distro field is picked up when
            # computing effective_distro_slug later in the function.
            active_vendor_override = matching_vo

        # Auto-select the first matching vendor override when vendor_overrides exist
        # but neither override_slug nor vendor_release_slug was explicitly specified.
        # This ensures the caller always gets vendor includes while being warned to
        # make an explicit selection.
        if release.vendor_overrides and not override_slug and not vendor_release_slug:
            first_matching = next(
                (vo for vo in release.vendor_overrides if vo.vendor == device.vendor),
                None,
            )
            if first_matching is not None:
                slug_hint = first_matching.slug or first_matching.vendor
                available_slugs = ", ".join(
                    vo.slug for vo in release.vendor_overrides if vo.slug
                )
                hint = (
                    f" Available override slugs: {available_slugs}."
                    if available_slugs
                    else ""
                )
                self.logger.warning(
                    f"Release '{release_slug}' has vendor_overrides defined but no "
                    f"`override` or `vendor_release` was specified. "
                    f"Automatically selecting first matching entry "
                    f"(vendor='{first_matching.vendor}', slug='{slug_hint}').{hint} "
                    f"Add `override:` or `vendor_release:` to the BSP preset to "
                    f"suppress this warning."
                )
                # Set the active override so its distro field is picked up below.
                active_vendor_override = first_matching
                # When the override has a slug, drive _apply_vendor_overrides by slug
                # so it selects this specific entry rather than the first vendor match.
                if first_matching.slug:
                    override_slug = first_matching.slug

        # Determine the effective distro slug early so that feature compatibility
        # checks use the distro that will actually be built, not the release's
        # default.  A vendor override's ``distro`` field takes precedence over the
        # release-level ``distro``.
        effective_distro_slug: Optional[str] = (
            active_vendor_override.distro
            if active_vendor_override and active_vendor_override.distro
            else release.distro
        )

        # Check compatibility for every requested feature
        for feature in features:
            if not self.check_feature_compatibility(feature, device):
                sys.exit(1)
            if not self.check_feature_framework_compatibility(
                feature, release, effective_distro_slug=effective_distro_slug
            ):
                sys.exit(1)

        # Resolve named environment for the release
        named_env: Optional[NamedEnvironment] = self.get_named_environment(release)

        # Resolve container configuration.
        # Priority (new-style, preset-based): handled in resolve_preset().
        # For direct resolve() calls the legacy device.build.container is
        # used as the first fallback, then the named-env container.
        container: Optional[Docker] = None
        named_env_name = release.environment or ("default" if "default" in (self.model.environments or {}) else None)
        # Legacy device.build.container takes precedence over named env
        legacy_container = device.build.container if device.build else None
        container_name = legacy_container or (
            named_env.container if named_env else None
        )
        if container_name:
            if container_name in self.containers:
                container = self.containers[container_name]
            else:
                source = (
                    f"named environment '{named_env_name}'"
                    if not legacy_container
                    else f"device '{device_slug}'"
                )
                self.logger.error(
                    f"Container '{container_name}' not found in registry containers "
                    f"(referenced by {source})"
                )
                sys.exit(1)

        # Build ordered KAS file list
        # Order: framework.includes -> distro.includes (effective distro)
        #        -> vendor.includes (registry.vendors[device.vendor])
        #        -> release.includes -> release.vendor_overrides[vendor or override slug]
        #        -> device.includes -> feature.includes
        # Prefer device.includes (new style); fall back to device.build.includes (legacy).
        kas_files: List[str] = []
        if effective_distro_slug:
            distro_obj = self.get_distro(effective_distro_slug)
            if distro_obj.framework:
                framework_obj = self.get_framework(distro_obj.framework)
                kas_files.extend(framework_obj.includes)
            kas_files.extend(distro_obj.includes)
        # Include vendor-level includes when a matching vendor entry exists
        vendor_obj = next(
            (v for v in self.model.registry.vendors if v.slug == device.vendor),
            None,
        )
        if vendor_obj:
            kas_files.extend(vendor_obj.includes)
        kas_files.extend(release.includes)
        kas_files.extend(self._apply_vendor_overrides(
            release.vendor_overrides, device.vendor, vendor_release_slug, override_slug
        ))
        device_includes = device.includes if device.includes else (
            device.build.includes if device.build else []
        )
        kas_files.extend(device_includes)
        for feature in features:
            kas_files.extend(feature.includes)

        # Build merged local_conf
        # Prefer device.local_conf (new style); fall back to device.build.local_conf (legacy).
        local_conf: List[str] = []
        device_local_conf = device.local_conf if device.local_conf else (
            device.build.local_conf if device.build else []
        )
        local_conf.extend(device_local_conf)
        for feature in features:
            local_conf.extend(feature.local_conf)

        # Build merged env: named environment variables first (base),
        # then feature-level variables (overrides).
        env: List[EnvironmentVariable] = []
        if named_env:
            env.extend(named_env.variables)
        for feature in features:
            env.extend(feature.env)

        # Build path: from legacy device.build.path when present, otherwise
        # empty (resolve_preset will fill it in, or caller must set it).
        build_path = device.build.path if device.build else ""

        # Copy entries merged in order (lowest to highest priority):
        #   1. Global registry-level copy (applies to every build)
        #   2. Named environment copy (applies when this env is active)
        #   3. Device-level copy (prefer device.copy; fall back to legacy device.build.copy)
        global_copy = list(self.model.environment.copy) if self.model.environment and self.model.environment.copy else []
        named_env_copy = list(named_env.copy) if named_env and named_env.copy else []
        device_copy = device.copy if device.copy else (
            device.build.copy if device.build else []
        )
        merged_copy = global_copy + named_env_copy + list(device_copy)

        return ResolvedConfig(
            device=device,
            release=release,
            features=features,
            kas_files=kas_files,
            build_path=build_path,
            container=container,
            local_conf=local_conf,
            env=env,
            copy=merged_copy,
            effective_distro=effective_distro_slug,
        )

    def _compose_build_path(self, resolved: ResolvedConfig) -> str:
        """
        Auto-compose a build output directory path from the resolved config.

        The path is built as ``build/<parts>`` where *parts* is a
        dash-separated sequence of:

        1. Effective distro slug (vendor override's distro or ``release.distro``), if set
        2. Device slug
        3. Release slug
        4. Feature slugs (in order), if any

        Args:
            resolved: Resolved build configuration.

        Returns:
            Auto-composed path string (e.g. ``build/poky-qemuarm64-scarthgap``).
        """
        parts: List[str] = []
        distro_for_path = resolved.effective_distro or resolved.release.distro
        if distro_for_path:
            parts.append(distro_for_path)
        parts.append(resolved.device.slug)
        parts.append(resolved.release.slug)
        for feature in resolved.features:
            parts.append(feature.slug)
        return "build/" + "-".join(p for p in parts if p)

    def expand_preset(self, preset: BspPreset) -> List[BspPreset]:
        """
        Expand a ``BspPreset`` into one or more concrete presets.

        * If the preset uses the singular ``release`` field it is returned as-is
          (wrapped in a list).
        * If the preset uses the plural ``releases`` field it is expanded into
          one preset per release slug.  Each expanded preset is named
          ``{preset.name}-{release_slug}`` and its ``build.path`` is always
          auto-composed (ignored even if set on the original entry).

        Validation:
        * Exactly one of ``release`` / ``releases`` must be set.
        * Having both or neither set is an error.

        Args:
            preset: The BSP preset entry to expand.

        Returns:
            List of one or more concrete ``BspPreset`` objects with a
            single ``release`` field each.

        Raises:
            SystemExit: If the preset has neither or both of ``release`` /
                        ``releases``.
        """
        has_single = bool(preset.release)
        has_multi = bool(preset.releases)

        if has_single and has_multi:
            self.logger.error(
                f"BSP preset '{preset.name}' specifies both 'release' and "
                f"'releases' – use exactly one of these fields"
            )
            sys.exit(1)

        if not has_single and not has_multi:
            self.logger.error(
                f"BSP preset '{preset.name}' must specify either 'release' "
                f"(single) or 'releases' (list of release slugs)"
            )
            sys.exit(1)

        if has_single:
            return [preset]

        # Expand multi-release preset
        expanded: List[BspPreset] = []
        for release_slug in preset.releases:
            # Build section: keep container override but drop explicit path so
            # it is always auto-composed per-release.
            if preset.build and preset.build.path:
                expanded_build = BspBuild(
                    container=preset.build.container,
                    path=None,
                )
            else:
                expanded_build = preset.build

            expanded.append(
                BspPreset(
                    name=f"{preset.name}-{release_slug}",
                    description=preset.description,
                    device=preset.device,
                    release=release_slug,
                    releases=[],
                    vendor_release=preset.vendor_release,
                    override=preset.override,
                    features=list(preset.features),
                    build=expanded_build,
                )
            )
        return expanded

    def list_presets(self) -> List[BspPreset]:
        """
        Return all concrete BSP presets, expanding any multi-release entries.

        Each preset that uses the ``releases`` list is expanded into one
        concrete preset per release (see :meth:`expand_preset`).

        Returns:
            Flat list of concrete ``BspPreset`` objects.
        """
        result: List[BspPreset] = []
        for preset in self.model.registry.bsp or []:
            result.extend(self.expand_preset(preset))
        return result

    def resolve_preset(self, preset_name: str) -> Tuple[ResolvedConfig, BspPreset]:
        """
        Resolve a named BSP preset to a ResolvedConfig.

        After resolving the underlying device + release + features the
        preset's ``build`` section (if present) is applied:

        * ``build.container`` overrides the container resolved from the
          named environment.
        * ``build.path`` sets the output directory; if absent the path is
          auto-composed via :meth:`_compose_build_path`.

        When no ``build`` section is present the container comes from the
        release's named environment (or ``"default"``) and the path is
        auto-composed.

        Presets that use the ``releases`` list are expanded first; the
        caller must use the expanded name (``{name}-{release_slug}``).

        Args:
            preset_name: Name of the preset in registry.bsp

        Returns:
            Tuple of (ResolvedConfig, BspPreset)

        Raises:
            SystemExit: If preset is not found
        """
        preset: Optional[BspPreset] = None
        for p in self.list_presets():
            if p.name == preset_name:
                preset = p
                break

        if preset is None:
            self.logger.error(f"BSP preset not found: '{preset_name}'")
            available = [p.name for p in self.list_presets()]
            self.logger.info(
                "Available presets: " + (", ".join(available) or "(none)")
            )
            sys.exit(1)

        resolved = self.resolve(
            preset.device, preset.release, preset.features,
            vendor_release_slug=preset.vendor_release,
            override_slug=preset.override,
        )

        # Apply preset build overrides
        preset_build: Optional[BspBuild] = preset.build
        if preset_build:
            # Container override from the preset build section
            if preset_build.container:
                container_name = preset_build.container
                if container_name in self.containers:
                    resolved.container = self.containers[container_name]
                else:
                    self.logger.error(
                        f"Container '{container_name}' not found in registry "
                        f"containers (referenced by preset '{preset_name}')"
                    )
                    sys.exit(1)
            # Build path: explicit or auto-composed
            resolved.build_path = (
                preset_build.path or self._compose_build_path(resolved)
            )
        else:
            # No build section – auto-compose path if not already set from
            # legacy device.build.path.
            if not resolved.build_path:
                resolved.build_path = self._compose_build_path(resolved)

        return resolved, preset

    # ------------------------------------------------------------------
    # Temp KAS YAML generation
    # ------------------------------------------------------------------

    def generate_kas_yaml(
        self,
        resolved: ResolvedConfig,
        output_path: str,
        base_dir: Optional[str] = None,
    ) -> None:
        """
        Write a temporary KAS YAML file that combines all resolved includes
        and local_conf additions into a single entry-point file.

        Include paths are converted to absolute paths so the temp file can
        reside anywhere (e.g. /tmp).

        Args:
            resolved: Resolved build configuration
            output_path: Destination path for the generated YAML file
            base_dir: Directory used to resolve relative include paths
                      (defaults to the current working directory)
        """
        base = Path(base_dir).resolve() if base_dir and base_dir.strip() else Path.cwd()

        # Convert all include paths to absolute
        abs_includes: List[str] = []
        for inc in resolved.kas_files:
            inc_path = Path(inc)
            if inc_path.is_absolute():
                abs_includes.append(str(inc_path))
            else:
                abs_includes.append(str((base / inc_path).resolve()))

        kas_config: dict = {
            "header": {
                "version": 14,
                "includes": abs_includes,
            }
        }

        # Add local_conf_header entries if any local_conf lines are present
        if resolved.local_conf:
            local_conf_header: dict = {}
            for idx, conf_line in enumerate(resolved.local_conf):
                key = f"bsp_local_conf_{idx:02d}"
                local_conf_header[key] = conf_line + "\n"
            kas_config["local_conf_header"] = local_conf_header

        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(kas_config, f, default_flow_style=False, sort_keys=False)

        self.logger.debug(f"Generated composed KAS YAML: {output_path}")
