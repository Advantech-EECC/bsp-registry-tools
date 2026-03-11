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
        self, feature: Feature, release: Release
    ) -> bool:
        """
        Check whether a feature is compatible with the framework/distro of the
        given release, based on the feature's ``compatible_with`` list.

        A feature is considered compatible when **any** of the following is true:

        * ``feature.compatible_with`` is empty (no restriction).
        * The release's distro slug appears in ``compatible_with``.
        * The release's distro's ``framework`` slug appears in ``compatible_with``.

        When ``compatible_with`` is non-empty but the release has no distro, the
        feature is treated as incompatible and an error is logged.

        Args:
            feature: Feature to check.
            release: Release being resolved.

        Returns:
            True if compatible, False otherwise (also logs a clear error).
        """
        if not feature.compatible_with:
            return True

        if not release.distro:
            self.logger.error(
                f"Feature '{feature.slug}' has compatible_with={feature.compatible_with} "
                f"but release '{release.slug}' does not specify a distro – "
                f"framework/distro compatibility cannot be determined"
            )
            return False

        distro_slug = release.distro

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

    def resolve(
        self,
        device_slug: str,
        release_slug: str,
        feature_slugs: Optional[List[str]] = None,
    ) -> ResolvedConfig:
        """
        Resolve device + release + features into a ResolvedConfig.

        Merging order for KAS files: framework.includes -> distro.includes -> release.includes -> device.includes -> feature.includes
        Merging order for local_conf:  device.local_conf -> feature.local_conf (in order)

        Args:
            device_slug: Device slug to build for
            release_slug: Release slug to use
            feature_slugs: Optional list of feature slugs to enable

        Returns:
            ResolvedConfig ready to drive a build

        Raises:
            SystemExit: If any slug is not found or a feature is incompatible
        """
        feature_slugs = feature_slugs or []

        device = self.get_device(device_slug)
        release = self.get_release(release_slug)
        features = [self.get_feature(s) for s in feature_slugs]

        # Check compatibility for every requested feature
        for feature in features:
            if not self.check_feature_compatibility(feature, device):
                sys.exit(1)
            if not self.check_feature_framework_compatibility(feature, release):
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
        # Order: framework.includes -> distro.includes -> release.includes -> device.includes -> feature.includes
        # Prefer device.includes (new style); fall back to device.build.includes (legacy).
        kas_files: List[str] = []
        if release.distro:
            distro_obj = self.get_distro(release.distro)
            if distro_obj.framework:
                framework_obj = self.get_framework(distro_obj.framework)
                kas_files.extend(framework_obj.includes)
            kas_files.extend(distro_obj.includes)
        kas_files.extend(release.includes)
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
        )

    def _compose_build_path(self, resolved: ResolvedConfig) -> str:
        """
        Auto-compose a build output directory path from the resolved config.

        The path is built as ``build/<parts>`` where *parts* is a
        dash-separated sequence of:

        1. Distro slug (from ``release.distro``), if set
        2. Device slug
        3. Release slug
        4. Feature slugs (in order), if any

        Args:
            resolved: Resolved build configuration.

        Returns:
            Auto-composed path string (e.g. ``build/poky-qemuarm64-scarthgap``).
        """
        parts: List[str] = []
        if resolved.release.distro:
            parts.append(resolved.release.distro)
        parts.append(resolved.device.slug)
        parts.append(resolved.release.slug)
        for feature in resolved.features:
            parts.append(feature.slug)
        return "build/" + "-".join(p for p in parts if p)

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

        Args:
            preset_name: Name of the preset in registry.bsp

        Returns:
            Tuple of (ResolvedConfig, BspPreset)

        Raises:
            SystemExit: If preset is not found
        """
        preset: Optional[BspPreset] = None
        for p in self.model.registry.bsp or []:
            if p.name == preset_name:
                preset = p
                break

        if preset is None:
            self.logger.error(f"BSP preset not found: '{preset_name}'")
            available = [p.name for p in (self.model.registry.bsp or [])]
            self.logger.info(
                "Available presets: " + (", ".join(available) or "(none)")
            )
            sys.exit(1)

        resolved = self.resolve(preset.device, preset.release, preset.features)

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
