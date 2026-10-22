"""
Main BSP management class coordinating registry, builds, and exports.
"""

import logging
import os
import json
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from contextlib import contextmanager
from dataclasses import replace, fields as dataclass_fields
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .deployer import ArtifactDeployer, DeployResult
from .environment import EnvironmentManager
from .exceptions import COLORAMA_AVAILABLE
from .flasher import FlashResult, ImageFlasher
from .gatherer import ArtifactGatherer, GatherResult
from .kas_manager import KasManager
from .manifest_paths import ManifestPathSanitizer
from .models import BspPreset, DeployConfig, Docker, EnvironmentVariable, YoctoCacheConfig, FlashConfig, ScanConfig
from .path_resolver import resolver
from .resolver import ResolvedConfig, V2Resolver
from .scanner import ImageScanner, ScanResult
from .storage import create_backend
from .utils import (
    get_registry_from_yaml_file,
    build_docker,
    expand_build_options_env,
    get_installed_package_version,
)

if COLORAMA_AVAILABLE:
    from colorama import Fore, Style

# =============================================================================
# Helpers
# =============================================================================


def _expand_env(value: str) -> str:
    """Expand ``$ENV{VAR}`` placeholders in *value* with OS environment values."""
    import re
    def _replace(m):
        var = m.group(1)
        return os.environ.get(var, m.group(0))
    return re.sub(r'\$ENV\{([^}]+)\}', _replace, value)


_RPI_SOC_FAMILY_MAP = {
    "rpi4": "bcm2711",
    "rpi5": "bcm2712",
}

# =============================================================================
# Main BSP Management Class with v2.0 Support
# =============================================================================


class BspManager:
    """
    Main BSP management class for BSP registry management (v2.0 schema).

    This class coordinates the overall BSP management flow including
    configuration loading, device/release/feature discovery, build execution,
    shell access, and configuration export operations with container support.

    Multiple registries are supported: pass *config_paths* as an ordered list
    of ``(name, path)`` pairs to load several independent registries at once.
    All listing commands annotate output with ``[registry-name]`` prefixes and
    all preset-selection arguments accept the ``registry:preset`` syntax for
    unambiguous targeting.
    """

    def __init__(
        self,
        config_path: str = "bsp-registry.yaml",
        verbose: bool = False,
        config_paths: Optional[List[Tuple[str, str]]] = None,
    ):
        """
        Initialize BSP manager.

        Args:
            config_path: Path to BSP registry configuration file (single-registry
                         mode, backward compatible).
            verbose: If True, stream docker build output live during builds.
            config_paths: Ordered list of ``(name, path)`` pairs for
                          multi-registry mode.  When provided *config_path* is
                          ignored.
        """
        if config_paths:
            self._config_pairs: List[Tuple[str, Path]] = [
                (name, Path(path)) for name, path in config_paths
            ]
        else:
            self._config_pairs = [("default", Path(config_path))]

        self.verbose = verbose
        self.logger = logging.getLogger(self.__class__.__name__)

        # Multi-registry state — populated by load_configuration / initialize
        self.registries: List[Tuple[str, object]] = []   # [(name, RegistryRoot)]
        self.resolvers: List[Tuple[str, V2Resolver]] = [] # [(name, V2Resolver)]

        # Active single-registry state (backward compatible public API)
        self.model = None          # RegistryRoot | None
        self.config_path = self._config_pairs[0][1]
        self.env_manager = None    # EnvironmentManager | None
        self.containers = {}       # Dict[str, Docker]
        self.resolver = None       # V2Resolver | None

    def load_configuration(self) -> None:
        """
        Load and parse BSP configuration from all registry YAML files.

        In multi-registry mode each registry is loaded independently without
        merging.  The first registry provides the backward-compatible
        ``self.model`` and ``self.config_path`` attributes.

        Raises:
            SystemExit: If any configuration file is missing, invalid, or not v2.0.
        """
        self.registries = []
        for reg_name, reg_path in self._config_pairs:
            try:
                if not reg_path.exists():
                    logging.error(f"Config file not found: {reg_path}")
                    sys.exit(1)
                model = get_registry_from_yaml_file(reg_path)
                self.registries.append((reg_name, model))
                logging.info(
                    f"Registry '{reg_name}' loaded successfully from {reg_path}"
                )
            except SystemExit:
                raise
            except Exception as e:
                logging.error(f"Failed to load registry '{reg_name}': {e}")
                sys.exit(1)

        # Backward-compat: point self.model / config_path at the first registry
        if self.registries:
            first_name, first_model = self.registries[0]
            self.model = first_model
            self.config_path = self._config_pairs[0][1]

            if first_model.containers:
                self.containers = first_model.containers
                logging.info(f"Loaded {len(self.containers)} container definitions")

            if first_model.environment and first_model.environment.variables:
                self.env_manager = EnvironmentManager(first_model.environment.variables)
                logging.info(
                    f"Environment configuration initialized with "
                    f"{len(first_model.environment.variables)} variables"
                )

    def initialize(self) -> None:
        """Initialize BSP manager components and validate configuration."""
        logging.info("Initializing BSP manager...")
        self.load_configuration()

        # Create one V2Resolver per registry
        self.resolvers = []
        for reg_name, reg_model in self.registries:
            reg_containers = reg_model.containers or {}
            self.resolvers.append((reg_name, V2Resolver(reg_model, reg_containers)))

        # Backward compat: point self.resolver at the first registry's resolver
        if self.resolvers:
            self.resolver = self.resolvers[0][1]

        # Validate environment configuration if present
        if self.env_manager:
            if not self.env_manager.validate_environment():
                logging.error("Environment configuration validation failed")
                sys.exit(1)

        logging.info("BSP manager initialized successfully")

    # ------------------------------------------------------------------
    # Listing commands
    # ------------------------------------------------------------------

    def _color_helpers(self, use_color: bool):
        """
        Return ``(header, name, dim)`` color-formatting helpers.

        Each helper accepts a string and returns it wrapped in the
        appropriate ANSI escape sequences when *use_color* is ``True``
        and colorama is available; otherwise the string is returned
        unchanged.
        """
        colored = use_color and COLORAMA_AVAILABLE

        def _c(text: str, *styles) -> str:
            if not colored:
                return text
            return "".join(styles) + text + Style.RESET_ALL

        def _header(text: str) -> str:
            return _c(text, Fore.CYAN, Style.BRIGHT)

        def _name(text: str) -> str:
            return _c(text, Fore.YELLOW)

        def _dim(text: str) -> str:
            return _c(text, Style.DIM)

        return _header, _name, _dim

    # ------------------------------------------------------------------
    # Multi-registry helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_qualified_name(value: str) -> Tuple[Optional[str], str]:
        """Split a registry-qualified value into ``(registry_name, item_name)``.

        If *value* contains no colon the returned registry_name is ``None``.
        Supports both preset selectors (``registry:preset``) and container
        selectors (``registry:container``).
        """
        if ":" in value:
            registry_name, item_name = value.split(":", 1)
            return registry_name.strip(), item_name.strip()
        return None, value

    @staticmethod
    def _parse_registry_preset(value: str) -> Tuple[Optional[str], str]:
        """Backward-compatible wrapper for parsing ``registry:preset`` values."""
        return BspManager._parse_qualified_name(value)

    def _iter_registries(self) -> Iterator[Tuple[str, object, V2Resolver, Path]]:
        """Iterate over (name, model, resolver, config_path) tuples for all registries."""
        if self.resolvers:
            for (reg_name, reg_model), (_, reg_resolver), (_, reg_path) in zip(
                self.registries, self.resolvers, self._config_pairs
            ):
                yield reg_name, reg_model, reg_resolver, reg_path
        elif self.resolver is not None and self.registries:
            # Backward-compat: resolver was set directly without populating self.resolvers
            reg_name, reg_model = self.registries[0]
            _, reg_path = self._config_pairs[0]
            yield reg_name, reg_model, self.resolver, reg_path

    def _validate_registry_filter(self, registry_filter: Optional[str]) -> None:
        """Validate *registry_filter* against known registry names.

        Exits with an error message listing available remote names when the
        given filter does not match any loaded registry.
        """
        if registry_filter is None:
            return
        known = [name for name, _, _, _ in self._iter_registries()]
        if registry_filter not in known:
            logging.error(
                "Remote '%s' not found. Available remotes: %s",
                registry_filter,
                ", ".join(known) if known else "(none)",
            )
            sys.exit(1)

    @contextmanager
    def _use_registry_context(
        self,
        model: object,
        reg_resolver: V2Resolver,
        config_path: Path,
    ) -> Iterator[None]:
        """Context manager that temporarily switches the active registry.

        This allows preset-based action methods (build, shell, export, deploy,
        gather, test) to call downstream helpers (``_get_kas_manager_for_resolved``,
        ``_resolve_deploy_config``, etc.) which rely on ``self.model``,
        ``self.resolver``, and ``self.config_path`` for the *correct* registry.
        """
        old_model = self.model
        old_resolver = self.resolver
        old_config_path = self.config_path
        self.model = model
        self.resolver = reg_resolver
        self.config_path = config_path
        try:
            yield
        finally:
            self.model = old_model
            self.resolver = old_resolver
            self.config_path = old_config_path

    def _resolve_preset_multi(
        self,
        bsp_name: str,
        extra_feature_slugs: Optional[List[str]] = None,
        vendor_release_slug: Optional[str] = None,
        override_slug: Optional[str] = None,
    ) -> Tuple[ResolvedConfig, BspPreset, str, object, V2Resolver, Path]:
        """Resolve a BSP preset across all loaded registries.

        Handles the ``registry:preset`` syntax for unambiguous targeting.

        Args:
            bsp_name: Preset name, optionally prefixed with a registry name
                      using the ``registry:preset`` format.
            extra_feature_slugs: Additional features to enable on top of the
                                 preset's own feature list.

        Returns:
            Tuple of ``(resolved, preset, registry_name, model, resolver, config_path)``.

        Raises:
            SystemExit: If the registry or preset is not found.
        """
        registry_hint, preset_name = self._parse_qualified_name(bsp_name)

        if registry_hint is not None:
            # Look only in the named registry
            for reg_name, reg_model, reg_resolver, reg_path in self._iter_registries():
                if reg_name == registry_hint:
                    resolved, preset = reg_resolver.resolve_preset(
                        preset_name,
                        extra_feature_slugs=extra_feature_slugs,
                        vendor_release_slug_override=vendor_release_slug,
                        override_slug_override=override_slug,
                    )
                    return resolved, preset, reg_name, reg_model, reg_resolver, reg_path
            logging.error(
                f"Registry '{registry_hint}' not found. "
                f"Available: {', '.join(n for n, _, _, _ in self._iter_registries()) or '(none)'}"
            )
            sys.exit(1)

        # Search all registries in order; warn on ambiguity
        found_in: List[Tuple[str, object, V2Resolver, Path]] = []
        for reg_name, reg_model, reg_resolver, reg_path in self._iter_registries():
            for p in reg_resolver.list_presets():
                if p.name == preset_name:
                    found_in.append((reg_name, reg_model, reg_resolver, reg_path))
                    break

        if not found_in:
            logging.error(f"BSP preset not found: '{preset_name}'")
            all_presets = [
                f"{n}:{p.name}"
                for n, _, r, _ in self._iter_registries()
                for p in r.list_presets()
            ]
            print("Available presets: " + (", ".join(all_presets) or "(none)"))
            sys.exit(1)

        if len(found_in) > 1:
            names = [n for n, _, _, _ in found_in]
            logging.warning(
                "Preset '%s' found in multiple registries: %s. "
                "Using '%s'. Use '%s:%s' to be explicit.",
                preset_name,
                names,
                names[0],
                names[0],
                preset_name,
            )

        reg_name, reg_model, reg_resolver, reg_path = found_in[0]
        resolved, preset = reg_resolver.resolve_preset(
            preset_name,
            extra_feature_slugs=extra_feature_slugs,
            vendor_release_slug_override=vendor_release_slug,
            override_slug_override=override_slug,
        )
        return resolved, preset, reg_name, reg_model, reg_resolver, reg_path

    # ------------------------------------------------------------------
    # Listing commands
    # ------------------------------------------------------------------

    def list_bsp(self, use_color: bool = True, registry_filter: Optional[str] = None) -> None:
        """
        List all BSP presets defined in the registry (or registries).

        In v2, presets are optional shortcuts. If no presets are defined,
        a helpful message is shown instead of exiting with an error.

        When multiple registries are loaded each preset is annotated with
        ``[registry-name]`` so the source is always visible.

        Args:
            use_color: Enable colored output (requires colorama).
            registry_filter: When set, only show presets from the named registry.
        """
        self._validate_registry_filter(registry_filter)
        _header, _name, _dim = self._color_helpers(use_color)

        multi = len(self.registries) > 1

        # Collect all presets across registries
        all_preset_rows: List[Tuple[str, object]] = []  # (registry_name, preset)
        for reg_name, reg_model, reg_resolver, _ in self._iter_registries():
            if registry_filter and reg_name != registry_filter:
                continue
            raw = reg_model.registry.bsp if reg_model else []
            if raw:
                for preset in reg_resolver.list_presets():
                    all_preset_rows.append((reg_name, preset))

        if not all_preset_rows:
            print("No BSP presets defined in registry")
            print(
                "Use 'bsp list devices', 'bsp list releases', or "
                "'bsp list features' to see available components."
            )
            return

        print(_header("Available BSP presets:"))
        for reg_name, preset in all_preset_rows:
            extra_parts = []
            if preset.vendor_release:
                extra_parts.append(f"vendor_release: {preset.vendor_release}")
            if getattr(preset, "override", None):
                extra_parts.append(f"override: {preset.override}")
            if preset.features:
                extra_parts.append(f"features: {', '.join(preset.features)}")
            extra_str = (", " + ", ".join(extra_parts)) if extra_parts else ""
            reg_prefix = _dim(f"[{reg_name}] ") if multi else ""
            print(
                f"- {reg_prefix}{_name(preset.name)}: {preset.description} "
                + _dim(f"(device: {preset.device}, release: {preset.release}{extra_str})")
            )

    def list_devices(self, use_color: bool = True, registry_filter: Optional[str] = None) -> None:
        """
        List all hardware devices defined across all registries.

        When multiple registries are loaded each entry is annotated with
        ``[registry-name]`` so the source is always visible.

        Args:
            use_color: Enable colored output (requires colorama).
            registry_filter: When set, only show devices from the named registry.
        """
        self._validate_registry_filter(registry_filter)
        _header, _name, _dim = self._color_helpers(use_color)
        multi = len(self.registries) > 1

        all_devices: List[Tuple[str, object]] = []
        for reg_name, reg_model, _, _ in self._iter_registries():
            if registry_filter and reg_name != registry_filter:
                continue
            devices = reg_model.registry.devices if reg_model else []
            for d in (devices or []):
                all_devices.append((reg_name, d))

        if not all_devices:
            print("No devices found in registry")
            return

        print(_header("Available devices:"))
        for reg_name, device in all_devices:
            soc_family = (
                f", soc_family: {device.soc_family}" if device.soc_family else ""
            )
            reg_prefix = _dim(f"[{reg_name}] ") if multi else ""
            print(
                f"- {reg_prefix}{_name(device.slug)}: {device.description} "
                + _dim(f"(vendor: {device.vendor}, soc_vendor: {device.soc_vendor}{soc_family})")
            )

    def list_releases(self, device_slug: Optional[str] = None, use_color: bool = True, registry_filter: Optional[str] = None) -> None:
        """
        List all release definitions across all registries.

        For each release, vendor overrides are shown together with their
        optional sub-releases (vendor releases).

        Args:
            device_slug: If provided, filter releases to those compatible with
                         the device's vendor (via vendor_overrides). A release is
                         shown when it has no vendor_overrides (generic), or when
                         it has at least one vendor_overrides entry whose vendor
                         matches the device's board vendor.  When omitted, all
                         releases are shown.
            use_color: Enable colored output (requires colorama).
            registry_filter: When set, only show releases from the named registry.
        """
        self._validate_registry_filter(registry_filter)
        _header, _name, _dim = self._color_helpers(use_color)
        multi = len(self.registries) > 1

        # Collect (registry_name, device|None, releases_list) per registry
        rows: List[Tuple[str, List]] = []
        for reg_name, reg_model, reg_resolver, _ in self._iter_registries():
            if registry_filter and reg_name != registry_filter:
                continue
            releases = reg_model.registry.releases if reg_model else []
            if not releases:
                continue
            if device_slug:
                # Find device in this registry (may not be present)
                try:
                    device = reg_resolver.get_device(device_slug)
                    releases = [
                        r for r in releases
                        if not r.vendor_overrides
                        or any(vo.vendor == device.vendor for vo in r.vendor_overrides)
                    ]
                except SystemExit:
                    # Device not found in this registry — skip releases from it
                    continue
            rows.append((reg_name, releases))

        if not rows:
            print("No releases found in registry")
            return

        if device_slug:
            print(_header(f"Releases compatible with device '{device_slug}':"))
        else:
            print(_header("Available releases:"))

        for reg_name, releases in rows:
            if multi:
                print(_dim(f"[{reg_name}]"))
                indent = "  "
            else:
                indent = ""
            for release in releases:
                yocto = f" [Yocto {release.yocto_version}]" if release.yocto_version else ""
                isar = f" [Isar {release.isar_version}]" if release.isar_version else ""
                distro_str = f", distro: {release.distro}" if release.distro else ""
                env_str = f", environment: {release.environment}" if release.environment else ""
                meta = f"{yocto}{isar}{distro_str}{env_str}"
                print(
                    f"{indent}- {_name(release.slug)}: {release.description}"
                    + (_dim(meta) if meta else "")
                )
                # Show vendor overrides and their sub-releases
                for vo in release.vendor_overrides:
                    vo_parts = [f"vendor: {vo.vendor}"]
                    if vo.slug:
                        vo_parts.append(f"slug: {vo.slug}")
                    if vo.distro:
                        vo_parts.append(f"distro: {vo.distro}")
                    vo_line = f"{indent}  " + _dim(f"  override [{', '.join(vo_parts)}]")
                    print(vo_line)
                    for vr in vo.releases:
                        print(f"{indent}  " + _dim(f"    release: {vr.slug} — {vr.description}"))
                    for svo in vo.soc_vendors:
                        svo_parts = [f"soc_vendor: {svo.vendor}"]
                        if svo.distro:
                            svo_parts.append(f"distro: {svo.distro}")
                        print(f"{indent}  " + _dim(f"    [{', '.join(svo_parts)}]"))
                        for vr in svo.releases:
                            print(f"{indent}  " + _dim(f"      release: {vr.slug} — {vr.description}"))

    def list_features(self, use_color: bool = True, registry_filter: Optional[str] = None) -> None:
        """
        List all feature definitions across all registries.

        Args:
            use_color: Enable colored output (requires colorama).
            registry_filter: When set, only show features from the named registry.
        """
        self._validate_registry_filter(registry_filter)
        _header, _name, _dim = self._color_helpers(use_color)
        multi = len(self.registries) > 1

        all_features: List[Tuple[str, object]] = []
        for reg_name, reg_model, _, _ in self._iter_registries():
            if registry_filter and reg_name != registry_filter:
                continue
            features = reg_model.registry.features if reg_model else []
            for f in (features or []):
                all_features.append((reg_name, f))

        if not all_features:
            print("No features found in registry")
            return

        print(_header("Available features:"))
        for reg_name, feature in all_features:
            compat_parts = []
            if feature.compatibility:
                if feature.compatibility.vendor:
                    compat_parts.append(f"vendor: {feature.compatibility.vendor}")
                if feature.compatibility.soc_vendor:
                    compat_parts.append(f"soc_vendor: {feature.compatibility.soc_vendor}")
                if feature.compatibility.soc_family:
                    compat_parts.append(f"soc_family: {feature.compatibility.soc_family}")
            if feature.compatible_with:
                compat_parts.append(f"compatible_with: {', '.join(feature.compatible_with)}")
            compat_str = _dim(f" [requires {', '.join(compat_parts)}]") if compat_parts else ""
            reg_prefix = _dim(f"[{reg_name}] ") if multi else ""
            print(f"- {reg_prefix}{_name(feature.slug)}: {feature.description}{compat_str}")

    def list_distros(self, use_color: bool = True, registry_filter: Optional[str] = None) -> None:
        """
        List all distribution/build-system definitions across all registries.

        Args:
            use_color: Enable colored output (requires colorama).
            registry_filter: When set, only show distros from the named registry.
        """
        self._validate_registry_filter(registry_filter)
        _header, _name, _dim = self._color_helpers(use_color)
        multi = len(self.registries) > 1

        all_distros: List[Tuple[str, object]] = []
        for reg_name, reg_model, _, _ in self._iter_registries():
            if registry_filter and reg_name != registry_filter:
                continue
            distros = reg_model.registry.distro if reg_model else []
            for d in (distros or []):
                all_distros.append((reg_name, d))

        if not all_distros:
            print("No distros found in registry")
            return

        print(_header("Available distros:"))
        for reg_name, distro in all_distros:
            fw_str = f", framework: {distro.framework}" if distro.framework else ""
            reg_prefix = _dim(f"[{reg_name}] ") if multi else ""
            print(
                f"- {reg_prefix}{_name(distro.slug)}: {distro.description} "
                + _dim(f"(vendor: {distro.vendor}{fw_str})")
            )

    def list_frameworks(self, use_color: bool = True) -> None:
        """
        List all build-system framework definitions across all registries.

        Args:
            use_color: Enable colored output (requires colorama).
        """
        _header, _name, _dim = self._color_helpers(use_color)
        multi = len(self.registries) > 1

        all_frameworks: List[Tuple[str, object]] = []
        for reg_name, reg_model, _, _ in self._iter_registries():
            frameworks = reg_model.registry.frameworks if reg_model else []
            for fw in (frameworks or []):
                all_frameworks.append((reg_name, fw))

        if not all_frameworks:
            print("No frameworks found in registry")
            return

        print(_header("Available frameworks:"))
        for reg_name, framework in all_frameworks:
            reg_prefix = _dim(f"[{reg_name}] ") if multi else ""
            print(
                f"- {reg_prefix}{_name(framework.slug)}: {framework.description} "
                + _dim(f"(vendor: {framework.vendor})")
            )

    def list_containers(self, use_color: bool = True) -> None:
        """
        List all available containers across all registries.

        Args:
            use_color: Enable colored output (requires colorama).
        """
        _header, _name, _dim = self._color_helpers(use_color)
        multi = len(self.registries) > 1

        # Collect all containers from all registries
        all_containers: List[Tuple[str, str, object]] = []  # (reg_name, container_name, config)
        for reg_name, reg_model, _, _ in self._iter_registries():
            reg_containers = reg_model.containers or {} if reg_model else {}
            for container_name, container_config in reg_containers.items():
                all_containers.append((reg_name, container_name, container_config))

        if not all_containers:
            print("No container definitions found in registry")
            return

        print(_header("Available Containers:"))
        for reg_name, container_name, container_config in all_containers:
            reg_prefix = _dim(f"[{reg_name}] ") if multi else ""
            print(f"- {reg_prefix}{_name(container_name)}:")
            print(f"    Image: {_dim(container_config.image)}")
            print(f"    File: {_dim(container_config.file)}")
            if container_config.args:
                args_str = ', '.join([f'{arg.name}={arg.value}' for arg in container_config.args])
                print(f"    Args: {_dim(args_str)}")

    def tree_bsp(self, use_color: bool = True, mode: str = "default", registry_filter: Optional[str] = None) -> None:
        """
        Print a colored ASCII tree of the full BSP registry hierarchy.

        The tree is organized into sections (Frameworks, Distros, Releases,
        Devices, Features, BSP Presets) and uses Unicode box-drawing characters
        for the connectors.  Colorama colors are applied when *use_color* is
        ``True`` and colorama is installed; otherwise plain text is rendered.

        Args:
            use_color: Enable colored output (requires colorama).  Ignored when
                       colorama is not installed.
            mode: Display mode — ``"default"`` (standard detail level including
                  vendor overrides/releases), ``"compact"`` (names/slugs only),
                  or ``"full"`` (all details including includes lists).
            registry_filter: When set, only show entries from the named registry.
        """

        self._validate_registry_filter(registry_filter)
        colored = use_color and COLORAMA_AVAILABLE

        # -----------------------------------------------------------------
        # Color helpers (no-op when color is disabled)
        # -----------------------------------------------------------------
        def _c(text: str, *styles) -> str:
            if not colored:
                return text
            return "".join(styles) + text + Style.RESET_ALL

        # Convenience aliases
        def _header(text: str) -> str:
            return _c(text, Fore.CYAN, Style.BRIGHT)

        def _name(text: str) -> str:
            return _c(text, Fore.YELLOW)

        def _dim(text: str) -> str:
            return _c(text, Style.DIM)

        def _slug(text: str) -> str:
            return _c(text, Fore.GREEN) if colored else text

        # -----------------------------------------------------------------
        # Tree connector characters
        # -----------------------------------------------------------------
        BRANCH = "├── "
        LAST   = "└── "
        PIPE   = "│   "
        BLANK  = "    "

        compact = mode == "compact"
        full    = mode == "full"

        def _print_sub_lines(sub_lines: list, prefix: str) -> None:
            """Print a list of already-formatted sub-lines with tree connectors."""
            for idx, line in enumerate(sub_lines):
                conn = LAST if idx == len(sub_lines) - 1 else BRANCH
                print(f"{prefix}{conn}{line}")

        def _print_includes(includes: list, prefix: str, label: str = "includes") -> None:
            """Print an includes list as a sub-tree node."""
            if not includes:
                return
            print(f"{prefix}{BRANCH}{_dim(label + ':')}")
            inc_prefix = prefix + PIPE
            for inc_idx, inc in enumerate(includes):
                conn = LAST if inc_idx == len(includes) - 1 else BRANCH
                print(f"{inc_prefix}{conn}{_dim(inc)}")

        def _print_tree_item(sec_name: str, item: object, item_connector: str, parent_prefix: str, item_prefix: str) -> None:
            """Print a single tree item under its section, handling all section types."""
            if sec_name == "Frameworks":
                detail = _dim(f" (vendor: {item.vendor})") if not compact else ""
                print(f"{parent_prefix}{item_connector}{_name(item.slug)}: {item.description}{detail}")
                if full:
                    _print_includes(item.includes, item_prefix)

            elif sec_name == "Distros":
                if not compact:
                    parts = [f"vendor: {item.vendor}"] if item.vendor else []
                    if item.framework:
                        parts.append(f"framework: {item.framework}")
                    detail = _dim(f" ({', '.join(parts)})") if parts else ""
                else:
                    detail = ""
                print(f"{parent_prefix}{item_connector}{_name(item.slug)}: {item.description}{detail}")
                if full:
                    _print_includes(item.includes, item_prefix)

            elif sec_name == "Releases":
                if not compact:
                    tags = []
                    if item.yocto_version:
                        tags.append(f"Yocto {item.yocto_version}")
                    if item.isar_version:
                        tags.append(f"Isar {item.isar_version}")
                    tag_str = _dim(f" [{', '.join(tags)}]") if tags else ""
                else:
                    tag_str = ""
                print(f"{parent_prefix}{item_connector}{_name(item.slug)}: {item.description}{tag_str}")
                if compact:
                    return
                if full:
                    sub_lines = []
                    if item.distro:
                        sub_lines.append(_dim(f"distro: {item.distro}"))
                    if item.includes:
                        sub_lines.append(_dim(f"includes: {', '.join(item.includes)}"))
                    _print_sub_lines(sub_lines, item_prefix)
                    for vo_idx, vo in enumerate(item.vendor_overrides):
                        is_last_vo = vo_idx == len(item.vendor_overrides) - 1
                        vo_conn   = LAST if is_last_vo else BRANCH
                        vo_prefix = item_prefix + (BLANK if is_last_vo else PIPE)
                        vo_tags = []
                        if vo.slug:
                            vo_tags.append(f"slug: {vo.slug}")
                        if vo.distro:
                            vo_tags.append(f"distro: {vo.distro}")
                        vo_tag_str = _dim(f" ({', '.join(vo_tags)})") if vo_tags else ""
                        print(f"{item_prefix}{vo_conn}{_dim('vendor override: ')}{_slug(vo.vendor)}{vo_tag_str}")
                        vo_sub = []
                        if vo.includes:
                            vo_sub.append(_dim(f"includes: {', '.join(vo.includes)}"))
                        _print_sub_lines(vo_sub, vo_prefix)
                        if vo.soc_vendors:
                            for svo_idx, svo in enumerate(vo.soc_vendors):
                                is_last_svo = svo_idx == len(vo.soc_vendors) - 1
                                svo_conn   = LAST if is_last_svo else BRANCH
                                svo_prefix = vo_prefix + (BLANK if is_last_svo else PIPE)
                                svo_tag_str = _dim(f" (distro: {svo.distro})") if svo.distro else ""
                                print(f"{vo_prefix}{svo_conn}{_dim('soc vendor: ')}{_slug(svo.vendor)}{svo_tag_str}")
                                svo_sub = []
                                if svo.includes:
                                    svo_sub.append(_dim(f"includes: {', '.join(svo.includes)}"))
                                _print_sub_lines(svo_sub, svo_prefix)
                                for vr_idx, vr in enumerate(svo.releases):
                                    is_last_vr = vr_idx == len(svo.releases) - 1
                                    vr_conn   = LAST if is_last_vr else BRANCH
                                    vr_prefix = svo_prefix + (BLANK if is_last_vr else PIPE)
                                    print(f"{svo_prefix}{vr_conn}{_dim('vendor release: ')}{_slug(vr.slug)}: {vr.description}")
                                    _print_includes(vr.includes, vr_prefix)
                        else:
                            for vr_idx, vr in enumerate(vo.releases):
                                is_last_vr = vr_idx == len(vo.releases) - 1
                                vr_conn   = LAST if is_last_vr else BRANCH
                                vr_prefix = vo_prefix + (BLANK if is_last_vr else PIPE)
                                print(f"{vo_prefix}{vr_conn}{_dim('vendor release: ')}{_slug(vr.slug)}: {vr.description}")
                                _print_includes(vr.includes, vr_prefix)
                else:
                    sub_items = []
                    if item.distro:
                        sub_items.append(_dim(f"distro: {item.distro}"))
                    for vo in item.vendor_overrides:
                        vo_parts = [f"vendor override: {vo.vendor}"]
                        if vo.slug:
                            vo_parts.append(f"slug: {vo.slug}")
                        if vo.distro:
                            vo_parts.append(f"distro: {vo.distro}")
                        if vo.soc_vendors:
                            svo_strs = []
                            for svo in vo.soc_vendors:
                                svo_p = [svo.vendor]
                                if svo.distro:
                                    svo_p.append(f"distro: {svo.distro}")
                                svo_vr_names = [vr.slug for vr in svo.releases]
                                if svo_vr_names:
                                    svo_p.append(f"releases: {', '.join(svo_vr_names)}")
                                svo_strs.append(f"[{'; '.join(svo_p)}]")
                            vo_parts.append(f"soc vendors: {', '.join(svo_strs)}")
                        else:
                            vr_names = [vr.slug for vr in vo.releases]
                            if vr_names:
                                vo_parts.append(f"releases: {', '.join(vr_names)}")
                        sub_items.append(_dim(", ".join(vo_parts)))
                    _print_sub_lines(sub_items, item_prefix)

            elif sec_name == "Devices":
                if not compact:
                    parts = [f"vendor: {item.vendor}", f"soc_vendor: {item.soc_vendor}"]
                    if item.soc_family:
                        parts.append(f"soc_family: {item.soc_family}")
                    detail = _dim(f" ({', '.join(parts)})")
                else:
                    detail = ""
                print(f"{parent_prefix}{item_connector}{_name(item.slug)}: {item.description}{detail}")
                if full:
                    _print_includes(item.includes, item_prefix)

            elif sec_name == "Features":
                if not compact:
                    compat_parts = []
                    if item.compatibility:
                        if item.compatibility.vendor:
                            compat_parts.append(f"vendor: {item.compatibility.vendor}")
                        if item.compatibility.soc_vendor:
                            compat_parts.append(f"soc_vendor: {item.compatibility.soc_vendor}")
                        if item.compatibility.soc_family:
                            compat_parts.append(f"soc_family: {item.compatibility.soc_family}")
                    if item.compatible_with:
                        compat_parts.append(f"compatible_with: {', '.join(item.compatible_with)}")
                    compat_str = _dim(f" [requires {', '.join(compat_parts)}]") if compat_parts else ""
                else:
                    compat_str = ""
                print(f"{parent_prefix}{item_connector}{_name(item.slug)}: {item.description}{compat_str}")
                if full:
                    _print_includes(item.includes, item_prefix)
                    has_vendor_overrides = bool(item.vendor_overrides)
                    for ro_idx, ro in enumerate(item.release_overrides):
                        is_last_ro = ro_idx == len(item.release_overrides) - 1 and not has_vendor_overrides
                        ro_conn   = LAST if is_last_ro else BRANCH
                        ro_prefix = item_prefix + (BLANK if is_last_ro else PIPE)
                        print(f"{item_prefix}{ro_conn}{_dim('release override: ')}{_slug(ro.release)}")
                        _print_includes(ro.includes, ro_prefix)
                    for vo_idx, vo in enumerate(item.vendor_overrides):
                        is_last_vo = vo_idx == len(item.vendor_overrides) - 1
                        vo_conn   = LAST if is_last_vo else BRANCH
                        vo_prefix = item_prefix + (BLANK if is_last_vo else PIPE)
                        vo_tags = []
                        if vo.slug:
                            vo_tags.append(f"slug: {vo.slug}")
                        if vo.distro:
                            vo_tags.append(f"distro: {vo.distro}")
                        vo_tag_str = _dim(f" ({', '.join(vo_tags)})") if vo_tags else ""
                        print(f"{item_prefix}{vo_conn}{_dim('vendor override: ')}{_slug(vo.vendor)}{vo_tag_str}")
                        vo_sub = []
                        if vo.includes:
                            vo_sub.append(_dim(f"includes: {', '.join(vo.includes)}"))
                        _print_sub_lines(vo_sub, vo_prefix)
                        if vo.soc_vendors:
                            for svo_idx, svo in enumerate(vo.soc_vendors):
                                is_last_svo = svo_idx == len(vo.soc_vendors) - 1
                                svo_conn   = LAST if is_last_svo else BRANCH
                                svo_prefix = vo_prefix + (BLANK if is_last_svo else PIPE)
                                svo_tag_str = _dim(f" (distro: {svo.distro})") if svo.distro else ""
                                print(f"{vo_prefix}{svo_conn}{_dim('soc vendor: ')}{_slug(svo.vendor)}{svo_tag_str}")
                                svo_sub = []
                                if svo.includes:
                                    svo_sub.append(_dim(f"includes: {', '.join(svo.includes)}"))
                                _print_sub_lines(svo_sub, svo_prefix)
                                for vr_idx, vr in enumerate(svo.releases):
                                    is_last_vr = vr_idx == len(svo.releases) - 1
                                    vr_conn   = LAST if is_last_vr else BRANCH
                                    vr_prefix = svo_prefix + (BLANK if is_last_vr else PIPE)
                                    print(f"{svo_prefix}{vr_conn}{_dim('vendor release: ')}{_slug(vr.slug)}: {vr.description}")
                                    _print_includes(vr.includes, vr_prefix)
                        else:
                            for vr_idx, vr in enumerate(vo.releases):
                                is_last_vr = vr_idx == len(vo.releases) - 1
                                vr_conn   = LAST if is_last_vr else BRANCH
                                vr_prefix = vo_prefix + (BLANK if is_last_vr else PIPE)
                                print(f"{vo_prefix}{vr_conn}{_dim('vendor release: ')}{_slug(vr.slug)}: {vr.description}")
                                _print_includes(vr.includes, vr_prefix)

            elif sec_name == "BSP Presets":
                print(f"{parent_prefix}{item_connector}{_name(item.name)}: {item.description}")
                if compact:
                    return
                sub_lines = [_dim(f"device: {item.device}  release: {item.release}")]
                if item.vendor_release:
                    sub_lines.append(_dim(f"vendor release: {item.vendor_release}"))
                if full and getattr(item, "override", None):
                    sub_lines.append(_dim(f"override: {item.override}"))
                if item.features:
                    sub_lines.append(_dim(f"features: {', '.join(item.features)}"))
                _print_sub_lines(sub_lines, item_prefix)



        # -----------------------------------------------------------------
        # Registry root
        # -----------------------------------------------------------------
        multi = len(self.registries) > 1
        print(_header("BSP Registry"))

        def _collect_section(section_key: str) -> List[Tuple[str, object]]:
            """Collect (registry_name, item) pairs for a given section key."""
            result = []
            for reg_name, reg_model, reg_resolver, _ in self._iter_registries():
                if registry_filter and reg_name != registry_filter:
                    continue
                if not reg_model:
                    continue
                registry = reg_model.registry
                if section_key == "frameworks":
                    items = registry.frameworks or []
                elif section_key == "distros":
                    items = registry.distro or []
                elif section_key == "releases":
                    items = registry.releases or []
                elif section_key == "devices":
                    items = registry.devices or []
                elif section_key == "features":
                    items = registry.features or []
                elif section_key == "presets":
                    items = reg_resolver.list_presets()
                else:
                    items = []
                for it in items:
                    result.append((reg_name, it))
            return result

        # Determine which top-level sections are present and non-empty
        frameworks_rows = _collect_section("frameworks")
        distros_rows    = _collect_section("distros")
        releases_rows   = _collect_section("releases")
        devices_rows    = _collect_section("devices")
        features_rows   = _collect_section("features")
        presets_rows    = _collect_section("presets")

        sections = [
            ("Frameworks", frameworks_rows),
            ("Distros",    distros_rows),
            ("Releases",   releases_rows),
            ("Devices",    devices_rows),
            ("Features",   features_rows),
            ("BSP Presets", presets_rows),
        ]
        # Filter empty sections
        sections = [(name, rows) for name, rows in sections if rows]

        for sec_idx, (sec_name, rows) in enumerate(sections):
            is_last_section = sec_idx == len(sections) - 1
            sec_connector  = LAST if is_last_section else BRANCH
            sec_prefix     = BLANK if is_last_section else PIPE

            print(f"{sec_connector}{_header(sec_name)} ({len(rows)})")

            # When multiple registries are loaded, group items under registry sub-nodes
            if multi:
                # Gather unique registry names in order
                reg_names_seen: List[str] = []
                for rn, _ in rows:
                    if rn not in reg_names_seen:
                        reg_names_seen.append(rn)

                for rn_idx, rn in enumerate(reg_names_seen):
                    is_last_rn = rn_idx == len(reg_names_seen) - 1
                    rn_connector = LAST if is_last_rn else BRANCH
                    rn_prefix    = sec_prefix + (BLANK if is_last_rn else PIPE)
                    rn_items = [it for r, it in rows if r == rn]
                    print(f"{sec_prefix}{rn_connector}{_dim('[' + rn + ']')} ({len(rn_items)})")

                    for item_idx, item in enumerate(rn_items):
                        is_last_item = item_idx == len(rn_items) - 1
                        item_connector = LAST if is_last_item else BRANCH
                        item_prefix    = rn_prefix + (BLANK if is_last_item else PIPE)
                        _print_tree_item(sec_name, item, item_connector, rn_prefix, item_prefix)
            else:
                items = [it for _, it in rows]
                for item_idx, item in enumerate(items):
                    is_last_item = item_idx == len(items) - 1
                    item_connector = LAST if is_last_item else BRANCH
                    item_prefix    = sec_prefix + (BLANK if is_last_item else PIPE)
                    _print_tree_item(sec_name, item, item_connector, sec_prefix, item_prefix)

        if not sections:
            print(f"{LAST}{_dim('(empty registry)')}")

    # ------------------------------------------------------------------
    # Preset lookup
    # ------------------------------------------------------------------

    def get_bsp_by_name(self, bsp_name: str) -> BspPreset:
        """
        Retrieve a BSP preset configuration by name.

        Accepts ``registry:preset`` syntax for unambiguous lookup when
        multiple registries are loaded.  When a plain preset name is given,
        all registries are searched in order; if the name appears in more
        than one registry a warning is emitted and the first match is
        returned.

        Args:
            bsp_name: Name of the preset to retrieve, optionally prefixed
                      with the registry name (``registry:preset``).

        Returns:
            BspPreset configuration object

        Raises:
            SystemExit: If preset with given name is not found
        """
        # Use _resolve_preset_multi for the lookup; we only need the preset object
        _, preset, _, _, _, _ = self._resolve_preset_multi(bsp_name)
        return preset

    def _resolve_container_multi(
        self, container_name: str
    ) -> Tuple[Docker, str, object, V2Resolver, Path]:
        """Resolve a named container across all loaded registries."""
        registry_hint, plain_name = self._parse_qualified_name(container_name)
        matches: List[Tuple[Docker, str, object, V2Resolver, Path]] = []

        if registry_hint is not None:
            known = [name for name, _, _, _ in self._iter_registries()]
            if registry_hint not in known:
                logging.error(
                    "Registry '%s' not found. Available registries: %s",
                    registry_hint,
                    ", ".join(known) if known else "(none)",
                )
                sys.exit(1)

        for reg_name, reg_model, reg_resolver, reg_path in self._iter_registries():
            if registry_hint is not None and reg_name != registry_hint:
                continue
            reg_containers = reg_model.containers or {} if reg_model else {}
            if plain_name in reg_containers:
                matches.append(
                    (reg_containers[plain_name], reg_name, reg_model, reg_resolver, reg_path)
                )

        if not matches:
            if registry_hint is not None:
                logging.error(
                    "Container '%s' not found in registry '%s'.",
                    plain_name,
                    registry_hint,
                )
            else:
                logging.error("Container '%s' not found in any loaded registry.", plain_name)
            sys.exit(1)

        if len(matches) > 1 and registry_hint is None:
            found_in = [reg_name for _, reg_name, _, _, _ in matches]
            logging.warning(
                "Container '%s' found in multiple registries: %s. "
                "Using first match from '%s'.",
                plain_name,
                ", ".join(found_in),
                found_in[0],
            )

        return matches[0]

    @staticmethod
    def _compose_docker_build_options(
        base_options: Optional[str],
        use_cache: Optional[bool] = None,
    ) -> Optional[str]:
        """Apply cache policy on top of an optional docker-build options string.

        ``$ENV{VAR}`` placeholders in *base_options* are expanded before any
        token manipulation so that patterns like
        ``$ENV{BSP_REGISTRY_DOCKER_BUILD_OPTIONS}`` are resolved correctly
        (e.g. when determining whether ``--no-cache`` is already present).
        """
        expanded = expand_build_options_env(base_options) if base_options else None
        tokens = shlex.split(expanded) if expanded else []
        if use_cache is True:
            tokens = [token for token in tokens if token != "--no-cache"]
        elif use_cache is False and "--no-cache" not in tokens:
            tokens.append("--no-cache")
        return shlex.join(tokens) if tokens else None

    def _build_container_image(
        self,
        container: Docker,
        *,
        label: str = "",
        docker_build_options: Optional[str] = None,
        use_cache: Optional[bool] = None,
        require_definition: bool = False,
    ) -> bool:
        """Build a Docker image from a container definition."""
        if not container.file or not container.image:
            if require_definition:
                logging.error(
                    "Container '%s' must define both 'file' and 'image' to be built locally.",
                    label or "(unnamed)",
                )
                sys.exit(1)
            return False

        build_opts = docker_build_options if docker_build_options is not None else container.build_options
        build_docker(
            str(self.config_path.parent),
            container.file,
            container.image,
            container.args,
            verbose=self.verbose,
            build_options=self._compose_docker_build_options(build_opts, use_cache=use_cache),
        )
        return True

    def build_container(
        self,
        container_name: str,
        *,
        use_cache: Optional[bool] = None,
    ) -> None:
        """Build a named container from the registry."""
        logging.info("Building container: %s", container_name)
        container, _, reg_model, reg_resolver, reg_path = self._resolve_container_multi(container_name)
        with self._use_registry_context(reg_model, reg_resolver, reg_path):
            self._build_container_image(
                container,
                label=container_name,
                use_cache=use_cache,
                require_definition=True,
            )

    def build_containers(
        self,
        container_name: Optional[str] = None,
        *,
        no_cache: bool = False,
    ) -> None:
        """Build container images from the registry.

        When *container_name* is provided, only that container is built
        (equivalent to ``build_container`` but using ``no_cache``).  When
        omitted, every container across all loaded registries that has both
        ``file`` and ``image`` set is built.

        Containers that declare an ``image`` but no ``file`` (pre-built images
        pulled from a registry) are skipped with a warning.  Containers with
        neither ``file`` nor ``image`` are silently skipped.

        Args:
            container_name: Optional name of a single container to build;
                            supports ``registry:container`` syntax in
                            multi-registry mode.
            no_cache: When ``True``, pass ``--no-cache`` to every ``docker
                      build`` invocation.

        Raises:
            SystemExit: If a named container is not found, or if any build
                        fails.
        """
        # use_cache=False tells _compose_docker_build_options to add --no-cache;
        # use_cache=None means "defer to registry build_options" (no override).
        use_cache: Optional[bool] = False if no_cache else None

        if container_name is not None:
            self.build_container(container_name, use_cache=use_cache)
            return

        built = 0
        skipped = 0
        for reg_name, reg_model, reg_resolver, reg_path in self._iter_registries():
            reg_containers = reg_model.containers or {} if reg_model else {}
            with self._use_registry_context(reg_model, reg_resolver, reg_path):
                for cname, container in reg_containers.items():
                    if not container.file or not container.image:
                        if container.image and not container.file:
                            logging.warning(
                                "Container '%s' has an image but no Dockerfile ('file'); "
                                "skipping build.",
                                cname,
                            )
                        else:
                            logging.debug(
                                "Container '%s' has no image or file; skipping.", cname
                            )
                        skipped += 1
                        continue
                    logging.info(
                        "Building container '%s' from registry '%s'", cname, reg_name
                    )
                    self._build_container_image(
                        container,
                        label=cname,
                        use_cache=use_cache,
                    )
                    built += 1

        if built == 0 and skipped == 0:
            logging.info("No containers found in registry.")
        else:
            logging.info("Built %d container(s), skipped %d.", built, skipped)

    # ------------------------------------------------------------------
    # Build directory helpers
    # ------------------------------------------------------------------

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

    def _copy_files(
        self, resolved: ResolvedConfig, build_path_override: Optional[str] = None
    ) -> None:
        """
        Copy files into the build environment before the build starts.

        Each entry in ``resolved.copy`` is a single-key dict mapping a source
        path to a destination path.  The source path is resolved relative to
        the registry file's parent directory.  The destination path is resolved
        relative to the BSP's build directory (``resolved.build_path``), so
        that copied files land directly inside the build workspace for the
        current BSP.  If the destination ends with ``/`` or is an existing
        directory the source filename is preserved inside it.

        The copied files are therefore accessible inside the build container
        because the build directory is mounted into the container during the
        build.

        Args:
            resolved: Resolved build configuration containing copy entries.
            build_path_override: Optional build path to use instead of
                                ``resolved.build_path``.

        Raises:
            SystemExit: If a source file does not exist.
        """
        if not resolved.copy:
            return

        base = self.config_path.parent
        # Destination paths are relative to the BSP's build directory so that
        # copied files land inside the build workspace for the current BSP.
        # When build_path is empty (no preset, direct resolve() call) fall back
        # to the registry directory to preserve backward-compatible behaviour.
        if build_path_override is not None:
            raw_build_path = build_path_override
        else:
            raw_build_path = resolved.build_path or ""
        if raw_build_path:
            build_abs = Path(raw_build_path)
            if not build_abs.is_absolute():
                build_abs = (base / build_abs).resolve()
            else:
                build_abs = build_abs.resolve()
        else:
            build_abs = base.resolve()

        for copy_entry in resolved.copy:
            for src, dst in copy_entry.items():
                src_path = Path(src)
                if not src_path.is_absolute():
                    src_path = (base / src_path).resolve()

                if not src_path.exists():
                    self.logger.error(
                        f"Copy source file not found: {src_path}"
                    )
                    sys.exit(1)

                dst_path = Path(dst)
                if not dst_path.is_absolute():
                    dst_path = (build_abs / dst_path).resolve()

                # If destination looks like a directory (trailing slash or
                # already is one), place the file inside it.
                if str(dst).endswith("/") or dst_path.is_dir():
                    dst_path = dst_path / src_path.name

                dst_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    self.logger.info(f"Copying file: {src_path} -> {dst_path}")
                    shutil.copy2(str(src_path), str(dst_path))
                except OSError as e:
                    self.logger.error(
                        f"Failed to copy '{src_path}' to '{dst_path}': {e}"
                    )
                    sys.exit(1)
                self.logger.info(f"Copied {src_path} -> {dst_path}")

    # ------------------------------------------------------------------
    # Internal: KasManager factory for a resolved config
    # ------------------------------------------------------------------

    def _get_kas_manager_for_resolved(
        self,
        resolved: ResolvedConfig,
        use_container: bool = True,
        build_path_override: Optional[str] = None,
    ) -> KasManager:
        """
        Create a KasManager for the given ResolvedConfig.

        If the resolved config includes local_conf additions, a temporary
        KAS YAML file is generated to carry those into the build.  The
        caller is responsible for deleting the temp file when done.

        Environment variables are merged in this order (later entries win):
        1. Root-level ``environment`` list (global defaults)
        2. Named environment variables from ``resolved.env``

        Args:
            resolved: Resolved device+release+features build config
            use_container: Whether to use containerized KAS
            build_path_override: Optional build path to use instead of
                                ``resolved.build_path``.

        Returns:
            Configured KasManager instance
        """
        # Build per-build EnvironmentManager: root vars merged with
        # named-env / feature vars from the resolved config.
        root_vars: List[EnvironmentVariable] = (
            list(self.model.environment.variables)
            if self.model.environment and self.model.environment.variables
            else []
        )
        # resolved.env contains named-env vars first, then feature vars.
        # Merge by appending; later keys win in EnvironmentManager.
        merged_vars = root_vars + list(resolved.env)
        # Always create a fresh EnvironmentManager from merged vars so that
        # named-env and feature variables are applied for this specific build.
        # Fall back to the global env_manager only when no vars exist at all.
        env_mgr = EnvironmentManager(merged_vars) if merged_vars else self.env_manager

        downloads = env_mgr.get_value("DL_DIR") if env_mgr else None
        sstate = env_mgr.get_value("SSTATE_DIR") if env_mgr else None

        if downloads:
            resolver.ensure_directory(downloads)
        if sstate:
            resolver.ensure_directory(sstate)

        # Determine KAS file list: generate a composed YAML when we have
        # local_conf additions or preset-level target overrides so that
        # everything is in a single entry-point.
        if resolved.local_conf or resolved.targets:
            temp_fd, temp_path = tempfile.mkstemp(
                prefix="bsp_composed_", suffix=".yml",
                dir=str(self.config_path.parent),
            )
            os.close(temp_fd)
            self.resolver.generate_kas_yaml(
                resolved,
                temp_path,
                base_dir=str(self.config_path.parent),
            )
            kas_files = [temp_path]
            self._temp_kas_file = temp_path
        else:
            # Resolve relative paths against the registry directory
            base = self.config_path.parent
            kas_files = []
            for f in resolved.kas_files:
                p = Path(f)
                if p.is_absolute():
                    kas_files.append(str(p))
                else:
                    kas_files.append(str((base / p).resolve()))
            self._temp_kas_file = None

        container_image = (
            resolved.container.image
            if resolved.container and use_container
            else None
        )
        container_runtime_args = (
            resolved.container.runtime_args
            if resolved.container and use_container
            else None
        )
        container_volumes = (
            resolved.container.volumes
            if resolved.container and use_container
            else []
        )
        effective_build_path = (
            build_path_override if build_path_override is not None else resolved.build_path
        )

        kas_mgr = KasManager(
            kas_files,
            effective_build_path,
            download_dir=downloads,
            sstate_dir=sstate,
            use_container=use_container,
            container_image=container_image,
            container_runtime_args=container_runtime_args,
            container_volumes=container_volumes,
            container_privileged=(
                resolved.container.privileged if resolved.container and use_container else False
            ),
            search_paths=[str(self.config_path.parent)],
            env_manager=env_mgr,
            verbose=self.verbose,
        )
        return kas_mgr

    def _cleanup_temp_kas_file(self) -> None:
        """Remove the temporary KAS YAML file if one was created."""
        temp_file = getattr(self, "_temp_kas_file", None)
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
                logging.debug(f"Removed temporary KAS file: {temp_file}")
            except OSError as e:
                logging.warning(f"Could not remove temporary KAS file: {e}")
        self._temp_kas_file = None

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_resolved(
        self,
        resolved: ResolvedConfig,
        checkout_only: bool = False,
        label: str = "",
        deploy_after_build: bool = False,
        preset: Optional[BspPreset] = None,
        deploy_overrides: Optional[Dict] = None,
        target: Optional[str] = None,
        task: Optional[str] = None,
        build_path_override: Optional[str] = None,
        scan_after_build: bool = False,
        scan_overrides: Optional[Dict] = None,
        flash_after_build: bool = False,
        flash_target: Optional[str] = None,
        flash_overrides: Optional[Dict] = None,
        docker_build_options: Optional[str] = None,
        update_index: Optional[bool] = None,
    ) -> None:
        """
        Execute a build (or checkout) for the given ResolvedConfig.

        Args:
            resolved: Resolved build configuration
            checkout_only: If True, only checkout and validate without building
            label: Descriptive label for log messages
            deploy_after_build: If True, deploy artifacts after a successful build
            preset: Optional BSP preset whose ``deploy`` block is applied on
                    top of the global deploy config before CLI overrides.
            deploy_overrides: CLI-level overrides for the deploy configuration
            target: Optional Bitbake build target to override registry targets
            task: Optional Bitbake task to run (e.g. compile, configure)
            build_path_override: If provided, overrides the build output path from the registry
            scan_after_build: If True, scan artifacts for CVEs after a successful build
            scan_overrides: CLI-level overrides for the scan configuration
            flash_after_build: If True, flash artifacts to *flash_target* after a successful build
            flash_target: Block device path used when *flash_after_build* is True
            flash_overrides: CLI-level overrides for the flash configuration
            docker_build_options: Extra flags for ``docker build`` (e.g. ``--no-cache``).
                                  Overrides ``build_options`` from the registry container
                                  definition when provided.
        """
        action = "Checking out" if checkout_only else "Building"
        logging.info(f"{action} {label or resolved.device.slug}")

        # Build Docker image if needed (skip in checkout mode)
        if not checkout_only and resolved.container:
            self._build_container_image(
                resolved.container,
                label=label or resolved.device.slug,
                docker_build_options=docker_build_options,
            )
        else:
            if checkout_only:
                logging.info("Skipping Docker build in checkout mode")

        if build_path_override is not None:
            logging.info(f"Overriding build path: {build_path_override}")
        build_path = build_path_override or resolved.build_path
        self.prepare_build_directory(build_path)
        self._copy_files(resolved, build_path_override=build_path_override)

        kas_mgr = self._get_kas_manager_for_resolved(
            resolved,
            use_container=not checkout_only,
            build_path_override=build_path_override,
        )

        try:
            config_output = kas_mgr.dump_config(show_output=False)
            self._log_config_dump(config_output)
            runtime_args_value = kas_mgr.get_runtime_args()
            manifest_runtime_args = (
                runtime_args_value if isinstance(runtime_args_value, str) else None
            )
            self._write_build_manifest(
                resolved=resolved,
                build_path=build_path,
                checkout_only=checkout_only,
                preset=preset,
                target=target,
                task=task,
                config_output=config_output,
                docker_build_options=docker_build_options,
                resolved_runtime_args=manifest_runtime_args,
            )

            if checkout_only:
                logging.info("Performing checkout and validation (no build)...")
                kas_mgr.checkout_project()
                logging.info(f"Checkout and validation completed successfully!")
            else:
                kas_mgr.build_project(target=target, task=task)
                logging.info(f"Build completed successfully!")
                if deploy_after_build:
                    self._deploy_resolved(
                        resolved,
                        preset=preset,
                        deploy_overrides=deploy_overrides or {},
                        build_path_override=build_path_override,
                        update_index=update_index,
                    )
                if scan_after_build:
                    self._scan_resolved(
                        resolved,
                        preset=preset,
                        scan_overrides=scan_overrides or {},
                        build_path_override=build_path_override,
                    )
                if flash_after_build and flash_target:
                    self._flash_resolved(
                        resolved,
                        target_device=flash_target,
                        preset=preset,
                        build_target=target,
                        flash_overrides=flash_overrides or {},
                        build_path_override=build_path_override,
                    )
        finally:
            self._cleanup_temp_kas_file()

    @staticmethod
    def _extract_targets_from_kas_config(config_output: Optional[Any]) -> List[str]:
        """Return normalized targets from ``kas dump`` YAML output."""
        import yaml

        if not config_output or not isinstance(config_output, str):
            return []
        try:
            config = yaml.safe_load(config_output) or {}
        except yaml.YAMLError as exc:
            logging.debug(f"Unable to parse KAS dump for targets: {exc}")
            return []
        if not isinstance(config, dict):
            return []
        targets = config.get("target")
        if isinstance(targets, str):
            return [targets]
        if isinstance(targets, list):
            return [str(target) for target in targets if target]
        return []

    @staticmethod
    def _log_config_dump(config_output: Optional[Any]) -> None:
        """Log KAS dump output only when it is a non-empty string."""
        if isinstance(config_output, str) and config_output:
            logging.debug("Configuration dump:\n" + config_output)

    @staticmethod
    def _resolve_manifest_soc_family(
        resolved: ResolvedConfig,
        preset: Optional[BspPreset],
    ) -> Optional[str]:
        """Resolve a best-effort SoC family value for build-manifest output."""
        if resolved.device.soc_family:
            return resolved.device.soc_family

        family_patterns = (
            (r"(?:i\.?mx|imx)[\s-]?([0-9][a-z0-9]*)", lambda m: f"imx{m.group(1).lower()}"),
            (r"\b(rk[0-9]{3,4}[a-z0-9]*)\b", lambda m: m.group(1).lower()),
            (r"\b((?:qcs|sa|sm|sc)[0-9]{3,4}[a-z0-9]*)\b", lambda m: m.group(1).lower()),
            (r"\b(bcm[0-9]{4}[a-z0-9]*)\b", lambda m: m.group(1).lower()),
            (r"\b(rpi[0-9]+)\b", lambda m: m.group(1).lower()),
            (r"\bras(?:pberry)?\s*pi\s*([0-9]+)\b", lambda m: f"rpi{m.group(1).lower()}"),
            (r"\b(am[0-9]{2}[a-z0-9]*)\b", lambda m: m.group(1).lower()),
            (r"\b(j[0-9]{4}[a-z0-9]*)\b", lambda m: m.group(1).lower()),
        )
        soc_vendor = (resolved.device.soc_vendor or "").lower().replace("-", "").replace(" ", "")

        for source in (
            resolved.device.description,
            preset.description if preset else None,
            resolved.device.slug,
        ):
            if not source:
                continue
            for pattern, formatter in family_patterns:
                match = re.search(pattern, source, re.IGNORECASE)
                if not match:
                    continue
                family = formatter(match)
                if soc_vendor in {"broadcom", "raspberrypi"} and family in _RPI_SOC_FAMILY_MAP:
                    return _RPI_SOC_FAMILY_MAP[family]
                return family
        return None

    @staticmethod
    def _resolve_manifest_container_build_options(
        resolved: ResolvedConfig,
        docker_build_options: Optional[str],
    ) -> Optional[str]:
        """Resolve effective docker build options for manifest output."""
        if not resolved.container:
            return None
        base_options = (
            docker_build_options
            if docker_build_options is not None
            else resolved.container.build_options
        )
        return BspManager._compose_docker_build_options(base_options, use_cache=None)

    @staticmethod
    def _resolve_manifest_registry_git_provenance(config_path: Path) -> Dict[str, Optional[Any]]:
        """Resolve git commit and dirty status for the registry repository."""
        registry_dir = config_path.parent if config_path.is_file() else config_path
        try:
            rev_parse = subprocess.run(
                ["git", "-C", str(registry_dir), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            )
            status = subprocess.run(
                ["git", "-C", str(registry_dir), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return {
                "commit_sha": None,
                "is_dirty": None,
            }
        return {
            "commit_sha": rev_parse.stdout.strip() or None,
            "is_dirty": bool(status.stdout.strip()),
        }

    def _build_manifest_path_sanitizer(self, build_path: str) -> ManifestPathSanitizer:
        """Create the path sanitizer used to keep manifest paths relative."""
        config_path = self.config_path
        registry_root = config_path.parent if config_path.is_file() else config_path

        build_root: Optional[Path] = None
        if build_path and str(build_path).strip():
            candidate = Path(os.path.expanduser(str(build_path).strip()))
            build_root = candidate if candidate.is_absolute() else registry_root / candidate

        return ManifestPathSanitizer(registry_root=registry_root, build_root=build_root)

    def _generate_build_manifest(
        self,
        resolved: ResolvedConfig,
        build_path: str,
        checkout_only: bool,
        preset: Optional[BspPreset],
        target: Optional[str],
        task: Optional[str],
        config_output: Optional[Any],
        docker_build_options: Optional[str],
        resolved_runtime_args: Optional[str],
    ) -> Dict[str, Any]:
        """Build a JSON-serializable manifest with resolved build components.

        All paths are emitted relative to the registry root or the build root
        (see the ``roots`` section); paths outside both anchors are replaced
        with ``${HOME}/...`` or ``<external>/<name>`` placeholders so that no
        absolute host path ends up in the manifest.
        """
        effective_distro = resolved.effective_distro or resolved.release.distro or ""
        distro_obj = None
        if effective_distro:
            distro_obj = next(
                (d for d in self.model.registry.distro if d.slug == effective_distro),
                None,
            )

        paths = self._build_manifest_path_sanitizer(build_path)
        relative_build_path = paths.relativize_to_registry(build_path) if build_path else ""

        selected_targets = [target] if target else self._extract_targets_from_kas_config(config_output)
        manifest_soc_family = self._resolve_manifest_soc_family(resolved, preset)
        manifest_container_build_options = self._resolve_manifest_container_build_options(
            resolved, docker_build_options
        )
        registry_git_provenance = self._resolve_manifest_registry_git_provenance(self.config_path)

        container_name = None
        if resolved.container:
            for name, definition in self.containers.items():
                if definition is resolved.container:
                    container_name = name
                    break

        scrubbed_argv = paths.scrub_argv(list(sys.argv))

        return {
            "schema_version": "2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "roots": {
                "registry": ".",
                "build": relative_build_path,
            },
            "registry": {
                "path": self.config_path.name if self.config_path.is_file() else ".",
            },
            "provenance": {
                "tool": {
                    "name": "bsp-registry-tools",
                    "version": get_installed_package_version("bsp-registry-tools"),
                },
                "cli": {
                    "argv": scrubbed_argv,
                    "command": shlex.join(scrubbed_argv),
                },
                "python": {
                    "version": platform.python_version(),
                },
                "registry_git": registry_git_provenance,
            },
            "preset": (
                {
                    "name": preset.name,
                    "description": preset.description,
                    "vendor_release": (
                        resolved.resolved_vendor_release
                        if resolved.resolved_vendor_release is not None
                        else preset.vendor_release
                    ),
                    "override": (
                        resolved.resolved_override
                        if resolved.resolved_override is not None
                        else preset.override
                    ),
                }
                if preset
                else None
            ),
            "build": {
                "path": relative_build_path,
                "name": Path(str(build_path)).name if build_path else "",
                "checkout_only": checkout_only,
                "target": target,
                "task": task,
                "docker_build_options": paths.scrub_text(docker_build_options),
                "resolved_targets": selected_targets,
            },
            "components": {
                "device": {
                    "slug": resolved.device.slug,
                    "vendor": resolved.device.vendor,
                    "soc_vendor": resolved.device.soc_vendor,
                    "soc_family": manifest_soc_family,
                    "architecture": resolved.device.architecture,
                },
                "release": {
                    "slug": resolved.release.slug,
                    "yocto_version": resolved.release.yocto_version,
                    "isar_version": resolved.release.isar_version,
                },
                "distro": {
                    "slug": effective_distro,
                    "framework": getattr(distro_obj, "framework", None) if distro_obj else None,
                },
                "features": [
                    {"slug": feature.slug, "description": feature.description}
                    for feature in resolved.features
                ],
                "container": (
                    {
                        "name": container_name,
                        "image": resolved.container.image,
                        "file": paths.relativize(resolved.container.file),
                        "runtime_args": paths.scrub_text(resolved_runtime_args),
                        "build_options": paths.scrub_text(manifest_container_build_options),
                        "privileged": resolved.container.privileged,
                        "args": [
                            {"name": arg.name, "value": paths.scrub_text(arg.value)}
                            for arg in resolved.container.args
                        ],
                    }
                    if resolved.container
                    else None
                ),
            },
            "inputs": {
                "kas_files": [paths.relativize(kas_file) for kas_file in resolved.kas_files],
                "local_conf": [paths.scrub_text(line) for line in resolved.local_conf],
                "environment_variables": [
                    {"name": env_var.name, "value": paths.scrub_text(env_var.value)}
                    for env_var in resolved.env
                ],
                "copy": [
                    {
                        paths.relativize(source): paths.relativize(destination)
                        for source, destination in entry.items()
                    }
                    for entry in resolved.copy
                ],
            },
        }

    def _write_build_manifest(
        self,
        resolved: ResolvedConfig,
        build_path: str,
        checkout_only: bool,
        preset: Optional[BspPreset],
        target: Optional[str],
        task: Optional[str],
        config_output: Optional[Any],
        docker_build_options: Optional[str],
        resolved_runtime_args: Optional[str],
    ) -> Path:
        """Write build manifest JSON to ``<build_path>/build-manifest.json``."""
        if build_path and str(build_path).strip():
            effective_build_path = build_path
        else:
            effective_build_path = resolved.build_path or "build"
        manifest_path = Path(effective_build_path) / "build-manifest.json"
        manifest = self._generate_build_manifest(
            resolved=resolved,
            build_path=effective_build_path,
            checkout_only=checkout_only,
            preset=preset,
            target=target,
            task=task,
            config_output=config_output,
            docker_build_options=docker_build_options,
            resolved_runtime_args=resolved_runtime_args,
        )
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        logging.info("Build manifest generated: %s", manifest_path)
        return manifest_path

    def _fetch_resolved(
        self,
        resolved: ResolvedConfig,
        target: Optional[str] = None,
        build_path_override: Optional[str] = None,
        label: str = "",
    ) -> None:
        """
        Fetch all sources required for the given ResolvedConfig.

        Args:
            resolved: Resolved build configuration
            target: Optional BitBake target to fetch instead of configured targets
            build_path_override: If provided, overrides the build output path
            label: Descriptive label for log messages
        """
        logging.info(f"Fetching sources for {label or resolved.device.slug}")

        if resolved.container:
            container = resolved.container
            if container.file and container.image:
                build_docker(
                    str(self.config_path.parent),
                    container.file,
                    container.image,
                    container.args,
                    verbose=self.verbose,
                )

        if build_path_override is not None:
            logging.info(f"Overriding build path: {build_path_override}")
        build_path = build_path_override or resolved.build_path
        self.prepare_build_directory(build_path)
        self._copy_files(resolved, build_path_override=build_path_override)

        kas_mgr = self._get_kas_manager_for_resolved(
            resolved,
            use_container=True,
            build_path_override=build_path_override,
        )

        try:
            config_output = kas_mgr.dump_config(show_output=False)
            self._log_config_dump(config_output)

            targets = [target] if target else self._extract_targets_from_kas_config(config_output)
            if not targets:
                logging.error(
                    "No BitBake targets found for source fetch. "
                    "Provide --target or configure targets in the KAS configuration."
                )
                sys.exit(1)

            kas_mgr.fetch_project(targets=targets)
        finally:
            self._cleanup_temp_kas_file()

    def build_bsp(
        self,
        bsp_name: str,
        checkout_only: bool = False,
        deploy_after_build: bool = False,
        deploy_overrides: Optional[Dict] = None,
        target: Optional[str] = None,
        task: Optional[str] = None,
        build_path_override: Optional[str] = None,
        feature_slugs: Optional[List[str]] = None,
        scan_after_build: bool = False,
        scan_overrides: Optional[Dict] = None,
        flash_after_build: bool = False,
        flash_target: Optional[str] = None,
        flash_overrides: Optional[Dict] = None,
        vendor_release_slug: Optional[str] = None,
        override_slug: Optional[str] = None,
        docker_build_options: Optional[str] = None,
        update_index: Optional[bool] = None,
    ) -> None:
        """
        Build a BSP by preset name.

        Args:
            bsp_name: Name of the BSP preset to build
            checkout_only: If True, only checkout and validate without building
            deploy_after_build: If True, deploy artifacts after a successful build
            deploy_overrides: CLI-level overrides for the deploy configuration
            target: Optional Bitbake build target to override registry targets
            task: Optional Bitbake task to run (e.g. compile, configure)
            build_path_override: If provided, overrides the build output path from the registry
            feature_slugs: Additional feature slugs to enable on top of those in the preset
            scan_after_build: If True, scan artifacts for CVEs after a successful build
            scan_overrides: CLI-level overrides for the scan configuration
            flash_after_build: If True, flash artifacts to *flash_target* after a successful build
            flash_target: Block device path used when *flash_after_build* is True
            flash_overrides: CLI-level overrides for the flash configuration
            vendor_release_slug: Optional vendor sub-release slug to override preset/default selection
            override_slug: Optional vendor override slug to force a specific vendor override
            docker_build_options: Extra flags for ``docker build`` (e.g. ``--no-cache``).
                                  Overrides ``build_options`` from the registry container
                                  definition when provided.

        Raises:
            SystemExit: If preset not found or build fails
        """
        logging.info(f"{'Checking out' if checkout_only else 'Building'} BSP preset: {bsp_name}")
        resolved, preset, _, reg_model, reg_resolver, reg_path = self._resolve_preset_multi(
            bsp_name,
            extra_feature_slugs=feature_slugs,
            vendor_release_slug=vendor_release_slug,
            override_slug=override_slug,
        )
        with self._use_registry_context(reg_model, reg_resolver, reg_path):
            self._build_resolved(
                resolved,
                checkout_only=checkout_only,
                label=f"{preset.name} - {preset.description}",
                deploy_after_build=deploy_after_build,
                preset=preset,
                deploy_overrides=deploy_overrides,
                target=target,
                task=task,
                build_path_override=build_path_override,
                scan_after_build=scan_after_build,
                scan_overrides=scan_overrides,
                flash_after_build=flash_after_build,
                flash_target=flash_target,
                flash_overrides=flash_overrides,
                docker_build_options=docker_build_options,
                update_index=update_index,
            )

    def fetch_bsp(
        self,
        bsp_name: str,
        target: Optional[str] = None,
        build_path_override: Optional[str] = None,
        feature_slugs: Optional[List[str]] = None,
        vendor_release_slug: Optional[str] = None,
        override_slug: Optional[str] = None,
    ) -> None:
        """
        Fetch all sources for a BSP preset.

        Args:
            bsp_name: Name of the BSP preset to fetch
            target: Optional BitBake target to fetch instead of configured targets
            build_path_override: If provided, overrides the build output path
            feature_slugs: Additional feature slugs to enable
            vendor_release_slug: Optional vendor sub-release slug to override preset/default selection
            override_slug: Optional vendor override slug to force a specific vendor override
        """
        logging.info(f"Fetching BSP preset: {bsp_name}")
        resolved, preset, _, reg_model, reg_resolver, reg_path = self._resolve_preset_multi(
            bsp_name,
            extra_feature_slugs=feature_slugs,
            vendor_release_slug=vendor_release_slug,
            override_slug=override_slug,
        )
        with self._use_registry_context(reg_model, reg_resolver, reg_path):
            self._fetch_resolved(
                resolved,
                target=target,
                build_path_override=build_path_override,
                label=f"{preset.name} - {preset.description}",
            )

    def build_by_components(
        self,
        device_slug: str,
        release_slug: str,
        feature_slugs: Optional[List[str]] = None,
        vendor_release_slug: Optional[str] = None,
        override_slug: Optional[str] = None,
        checkout_only: bool = False,
        deploy_after_build: bool = False,
        deploy_overrides: Optional[Dict] = None,
        target: Optional[str] = None,
        task: Optional[str] = None,
        build_path_override: Optional[str] = None,
        scan_after_build: bool = False,
        scan_overrides: Optional[Dict] = None,
        flash_after_build: bool = False,
        flash_target: Optional[str] = None,
        flash_overrides: Optional[Dict] = None,
        docker_build_options: Optional[str] = None,
        update_index: Optional[bool] = None,
    ) -> None:
        """
        Build by specifying device, release, and optional features directly.

        Args:
            device_slug: Device slug
            release_slug: Release slug
            feature_slugs: Optional list of feature slugs to enable
            vendor_release_slug: Optional vendor sub-release slug
            override_slug: Optional vendor override slug
            checkout_only: If True, only checkout and validate without building
            deploy_after_build: If True, deploy artifacts after a successful build
            deploy_overrides: CLI-level overrides for the deploy configuration
            target: Optional Bitbake build target to override registry targets
            task: Optional Bitbake task to run (e.g. compile, configure)
            build_path_override: If provided, overrides the build output path from the registry
            scan_after_build: If True, scan artifacts for CVEs after a successful build
            scan_overrides: CLI-level overrides for the scan configuration
            flash_after_build: If True, flash artifacts to *flash_target* after a successful build
            flash_target: Block device path used when *flash_after_build* is True
            flash_overrides: CLI-level overrides for the flash configuration
            docker_build_options: Extra flags for ``docker build`` (e.g. ``--no-cache``).
                                  Overrides ``build_options`` from the registry container
                                  definition when provided.

        Raises:
            SystemExit: If any component is not found, incompatible, or build fails
        """
        logging.info(
            f"{'Checking out' if checkout_only else 'Building'} "
            f"device={device_slug} release={release_slug} "
            f"features={feature_slugs or []}"
        )
        resolved = self.resolver.resolve(
            device_slug,
            release_slug,
            feature_slugs,
            vendor_release_slug=vendor_release_slug,
            override_slug=override_slug,
        )
        self._build_resolved(
            resolved,
            checkout_only=checkout_only,
            label=f"{device_slug}/{release_slug}",
            deploy_after_build=deploy_after_build,
            deploy_overrides=deploy_overrides,
            target=target,
            task=task,
            build_path_override=build_path_override,
            scan_after_build=scan_after_build,
            scan_overrides=scan_overrides,
            flash_after_build=flash_after_build,
            flash_target=flash_target,
            flash_overrides=flash_overrides,
            docker_build_options=docker_build_options,
            update_index=update_index,
        )

    def fetch_by_components(
        self,
        device_slug: str,
        release_slug: str,
        feature_slugs: Optional[List[str]] = None,
        vendor_release_slug: Optional[str] = None,
        override_slug: Optional[str] = None,
        target: Optional[str] = None,
        build_path_override: Optional[str] = None,
    ) -> None:
        """
        Fetch all sources by specifying device, release, and optional features.

        Args:
            device_slug: Device slug
            release_slug: Release slug
            feature_slugs: Optional list of feature slugs to enable
            vendor_release_slug: Optional vendor sub-release slug
            override_slug: Optional vendor override slug
            target: Optional BitBake target to fetch instead of configured targets
            build_path_override: If provided, overrides the build output path
        """
        logging.info(
            f"Fetching sources for device={device_slug} release={release_slug} "
            f"features={feature_slugs or []}"
        )
        resolved = self.resolver.resolve(
            device_slug,
            release_slug,
            feature_slugs,
            vendor_release_slug=vendor_release_slug,
            override_slug=override_slug,
        )
        self._fetch_resolved(
            resolved,
            target=target,
            build_path_override=build_path_override,
            label=f"{device_slug}/{release_slug}",
        )

    # ------------------------------------------------------------------
    # Shell
    # ------------------------------------------------------------------

    def _shell_resolved(
        self,
        resolved: ResolvedConfig,
        command: Optional[str] = None,
        label: str = "",
        build_path_override: Optional[str] = None,
    ) -> None:
        """
        Start a KAS shell session for the given ResolvedConfig.

        Args:
            resolved: Resolved build configuration
            command: Optional command to run in the shell
            label: Descriptive label for log messages
            build_path_override: If provided, overrides the build output path from the registry
        """
        logging.info(f"Starting shell for {label or resolved.device.slug}")

        if resolved.container:
            container = resolved.container
            if container.file and container.image:
                logging.info("Building Docker image for shell environment...")
                self._build_container_image(
                    container,
                    label=label or resolved.device.slug,
                )

        if build_path_override is not None:
            logging.info(f"Overriding build path: {build_path_override}")
        build_path = build_path_override or resolved.build_path
        self.prepare_build_directory(build_path)
        self._copy_files(resolved, build_path_override=build_path_override)

        kas_mgr = self._get_kas_manager_for_resolved(
            resolved, use_container=True, build_path_override=build_path_override
        )

        try:
            if command:
                logging.info(f"Executing command: {command}")
            else:
                logging.info("Starting interactive KAS shell session...")
                logging.info("Use 'Ctrl+D' or type 'exit' to leave the shell.")
            kas_mgr.shell_session(command=command)
        finally:
            self._cleanup_temp_kas_file()

    def shell_into_bsp(
        self,
        bsp_name: str,
        command: Optional[str] = None,
        build_path_override: Optional[str] = None,
    ) -> None:
        """
        Enter interactive shell for a BSP preset.

        Args:
            bsp_name: Name of the BSP preset
            command: Optional command to execute in the shell
            build_path_override: If provided, overrides the build output path from the registry

        Raises:
            SystemExit: If preset not found or shell fails
        """
        logging.info(f"Entering shell for BSP preset: {bsp_name}")
        resolved, preset, _, reg_model, reg_resolver, reg_path = self._resolve_preset_multi(bsp_name)
        with self._use_registry_context(reg_model, reg_resolver, reg_path):
            self._shell_resolved(
                resolved,
                command=command,
                label=f"{preset.name} - {preset.description}",
                build_path_override=build_path_override,
            )

    def shell_by_components(
        self,
        device_slug: str,
        release_slug: str,
        feature_slugs: Optional[List[str]] = None,
        command: Optional[str] = None,
        build_path_override: Optional[str] = None,
    ) -> None:
        """
        Enter interactive shell by specifying device, release, and features directly.

        Args:
            device_slug: Device slug
            release_slug: Release slug
            feature_slugs: Optional list of feature slugs
            command: Optional command to execute in the shell
            build_path_override: If provided, overrides the build output path from the registry

        Raises:
            SystemExit: If any component is not found or shell fails
        """
        logging.info(
            f"Entering shell for device={device_slug} release={release_slug} "
            f"features={feature_slugs or []}"
        )
        resolved = self.resolver.resolve(device_slug, release_slug, feature_slugs)
        self._shell_resolved(
            resolved,
            command=command,
            label=f"{device_slug}/{release_slug}",
            build_path_override=build_path_override,
        )

    # ------------------------------------------------------------------
    # Flash
    # ------------------------------------------------------------------

    def _get_deploy_dir(self, bsp_name: str) -> Path:
        """Return the Yocto deploy/images directory for *bsp_name*.

        Yocto places its output under::

            <build_path>/build/tmp/deploy/images/

        Args:
            bsp_name: BSP preset name.

        Returns:
            Path to the deploy/images directory (may not exist yet).
        """
        resolved, _ = self.resolver.resolve_preset(bsp_name)
        build_path = Path(resolved.build_path)
        return build_path / "build" / "tmp" / "deploy" / "images"

    def list_flash_images(self, bsp_name: str) -> List[Path]:
        """Return a list of flashable image files for *bsp_name*.

        Searches ``<build_path>/build/tmp/deploy/images/`` recursively for
        ``.wic``, ``.wic.gz``, ``.wic.bz2``, ``.wic.xz``, ``.wic.zst``,
        and ``.img`` files (excluding ``.bmap`` sidecars).

        Compressed ``.wic.*`` variants are included because Yocto builds
        commonly produce them when ``IMAGE_FSTYPES`` includes ``wic.gz``,
        ``wic.bz2``, etc.  ``bmaptool`` can flash these directly; plain
        ``dd`` will pipe them through the appropriate decompressor.

        Args:
            bsp_name: BSP preset name (must have been built first).

        Returns:
            List of :class:`pathlib.Path` objects for candidate images, sorted
            with ``.wic`` / compressed-wic files first and then by descending
            modification time.
        """
        deploy_dir = self._get_deploy_dir(bsp_name)
        if not deploy_dir.exists():
            return []

        candidates: List[Path] = []
        for pattern in (
            "*.wic",
            "*.wic.gz",
            "*.wic.bz2",
            "*.wic.xz",
            "*.wic.zst",
            "*.img",
        ):
            candidates.extend(deploy_dir.rglob(pattern))
        # Filter out bmap sidecar files (e.g. *.wic.bmap, *.img.bmap)
        candidates = [f for f in candidates if ".bmap" not in f.suffixes]
        # Remove duplicates that may arise from overlapping glob patterns
        seen: set[str] = set()
        unique: List[Path] = []
        for f in candidates:
            key = str(f)
            if key not in seen:
                seen.add(key)
                unique.append(f)
        candidates = unique

        # Sort: wic files (plain or compressed) first, then by descending
        # modification time.  A file is considered a "wic" if .wic appears
        # anywhere in its suffix chain (e.g. image.rootfs.wic.gz).
        stat_cache = {f: f.stat() for f in candidates}
        candidates.sort(
            key=lambda f: (0 if ".wic" in f.suffixes else 1, -stat_cache[f].st_mtime)
        )
        return candidates

    def flash_bsp(self, bsp_name: str, target: str, image_path: Optional[str] = None) -> None:
        """
        Flash a BSP image to a target block device (SD card or eMMC).

        Resolves the BSP preset to locate its build output directory
        (``<build_path>/build/tmp/deploy/images/``).  The caller must supply
        the image to flash via *image_path*; use :meth:`list_flash_images` to
        enumerate available candidates.

        If the chosen image is a ``.wic`` or compressed ``.wic.*`` file
        (e.g. ``.wic.gz``, ``.wic.bz2``, ``.wic.xz``, ``.wic.zst``) and
        ``bmaptool`` is available, it is used for flashing (bmaptool handles
        compressed images natively).  Otherwise ``dd`` is used, piping the
        image through the appropriate decompressor when needed.

        Args:
            bsp_name: BSP preset name (must have been built first).
            target: Target block device path (e.g. ``/dev/sda``,
                    ``/dev/mmcblk0``).
            image_path: Path to the image file to flash.  When *None* the most
                recently produced ``.wic`` or ``.img`` image in the deploy
                directory is selected automatically.

        Raises:
            SystemExit: If the preset is not found, no image file is present,
                        or the flash tool exits with a non-zero status.
        """
        import shutil as _shutil
        import subprocess as _sp

        def _privilege_prefix() -> list:
            """Return a privilege-escalation prefix for subprocess commands.

            Prefers ``pkexec`` (shows a graphical Polkit password dialog, suitable
            for GUI applications) and falls back to ``sudo`` (works in terminals).
            Logs a warning and returns an empty list when neither is found.
            """
            for tool in ("pkexec", "sudo"):
                if _shutil.which(tool):
                    return [tool]
            logging.warning(
                "Neither 'pkexec' nor 'sudo' found; flash command will run without "
                "elevated privileges and may fail on restricted devices."
            )
            print(
                "Warning: Neither 'pkexec' nor 'sudo' is available. "
                "The flash command will run without elevated privileges.",
                file=sys.stderr,
            )
            return []

        logging.info(f"Flashing BSP preset '{bsp_name}' to '{target}'")

        if image_path:
            selected_image = Path(image_path)
            if not selected_image.exists():
                print(
                    f"Error: Image file '{image_path}' does not exist.",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            # Fall back to auto-selection: most recently modified image
            candidates = self.list_flash_images(bsp_name)
            if not candidates:
                deploy_dir = self._get_deploy_dir(bsp_name)
                print(
                    f"Error: No .wic, .wic.gz, .wic.bz2, .wic.xz, .wic.zst, or .img "
                    f"image files found in {deploy_dir}.\n"
                    f"Run 'bsp build {bsp_name}' first.",
                    file=sys.stderr,
                )
                sys.exit(1)
            selected_image = candidates[0]

        # Validate the target is a block device to prevent accidental overwrites
        target_path = Path(target)
        if target_path.exists():
            import stat as _stat
            if not _stat.S_ISBLK(target_path.stat().st_mode):
                print(
                    f"Error: '{target}' is not a block device. "
                    "Specify a target such as /dev/sda or /dev/mmcblk0.",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            print(
                f"Error: Target device '{target}' does not exist. "
                "Check the device path and ensure the storage medium is connected.",
                file=sys.stderr,
            )
            sys.exit(1)

        bmaptool = _shutil.which("bmaptool")
        # A file is a "wic" image if .wic appears in its suffix chain
        # (handles both plain .wic and compressed variants like .wic.gz).
        is_wic = ".wic" in selected_image.suffixes
        priv = _privilege_prefix()

        if is_wic and bmaptool:
            # bmaptool handles both plain and compressed wic images natively.
            # bmaptool expects image paths as file:// URIs, not bare filesystem paths.
            # Resolve to an absolute path first so as_uri() doesn't raise on relative paths.
            resolved_image = selected_image.resolve()
            image_uri = resolved_image.as_uri()
            # Yocto names the bmap file after the uncompressed image stem, e.g.
            # "image.wic.bmap" for both "image.wic" and "image.wic.gz".
            # Check that canonical name first, then fall back to "<image>.bmap".
            wic_stem = resolved_image.name
            for suffix in (".gz", ".bz2", ".xz", ".zst", ".lz4"):
                if wic_stem.endswith(suffix):
                    wic_stem = wic_stem[: -len(suffix)]
                    break
            bmap_path = resolved_image.parent / (wic_stem + ".bmap")
            if not bmap_path.exists():
                bmap_path = resolved_image.parent / (resolved_image.name + ".bmap")
            if bmap_path.exists():
                logging.info(f"Flashing {selected_image} → {target} using bmaptool (with bmap)")
                print(f"Flashing {selected_image.name} → {target} (bmaptool)…")
                proc = _sp.Popen(
                    [*priv, "bmaptool", "copy", "--bmap", str(bmap_path), image_uri, target],
                    stdout=_sp.PIPE, stderr=_sp.STDOUT, text=True,
                )
                for line in proc.stdout:
                    print(line, end="", flush=True)
                proc.wait()
                result = proc
            else:
                logging.info(f"Flashing {selected_image} → {target} using bmaptool (no bmap)")
                print(f"Flashing {selected_image.name} → {target} (bmaptool --nobmap)…")
                proc = _sp.Popen(
                    [*priv, "bmaptool", "copy", "--nobmap", image_uri, target],
                    stdout=_sp.PIPE, stderr=_sp.STDOUT, text=True,
                )
                for line in proc.stdout:
                    print(line, end="", flush=True)
                proc.wait()
                result = proc
        elif is_wic and selected_image.suffix != ".wic":
            # Compressed wic but no bmaptool — decompress then pipe into dd.
            compression_ext = selected_image.suffix  # e.g. ".gz", ".bz2"
            decomp_map = {
                ".gz": ["gunzip", "--stdout"],
                ".bz2": ["bunzip2", "--stdout"],
                ".xz": ["xz", "--decompress", "--stdout"],
                ".zst": ["zstd", "--decompress", "--stdout"],
            }
            decomp_cmd = decomp_map.get(compression_ext)
            if decomp_cmd is None or _shutil.which(decomp_cmd[0]) is None:
                print(
                    f"Error: Cannot flash compressed image '{selected_image.name}': "
                    f"install bmaptool or {decomp_cmd[0] if decomp_cmd else 'a suitable decompressor'}.",
                    file=sys.stderr,
                )
                sys.exit(1)
            logging.info(
                f"Flashing {selected_image} → {target} via {decomp_cmd[0]} | dd"
            )
            print(
                f"Flashing {selected_image.name} → {target} "
                f"({decomp_cmd[0]} | dd)…"
            )
            print("⚠  This will overwrite all data on the target device!")
            decomp = _sp.Popen(
                [*decomp_cmd, str(selected_image)],
                stdout=_sp.PIPE,
            )
            result = _sp.run(
                [*priv, "dd", f"of={target}", "bs=4M", "conv=fsync", "status=progress"],
                stdin=decomp.stdout,
            )
            if decomp.stdout:
                decomp.stdout.close()
            decomp.wait()
            if result.returncode != 0:
                print(
                    f"Error: Flash failed with exit code {result.returncode}.\n"
                    "Common causes: insufficient permissions (try with sudo), "
                    "device busy, or incorrect target path.",
                    file=sys.stderr,
                )
                sys.exit(result.returncode)
            if decomp.returncode != 0:
                print(
                    f"Error: Decompression failed with exit code {decomp.returncode}.",
                    file=sys.stderr,
                )
                sys.exit(decomp.returncode)
            print(f"Successfully flashed {selected_image.name} to {target}")
            return
        else:
            logging.info(f"Flashing {selected_image} → {target} using dd")
            print(f"Flashing {selected_image.name} → {target} (dd)…")
            print("⚠  This will overwrite all data on the target device!")
            proc = _sp.Popen(
                [*priv, "dd", f"if={selected_image}", f"of={target}", "bs=4M", "conv=fsync", "status=progress"],
                stderr=_sp.PIPE, text=True,
            )
            for line in proc.stderr:
                print(line, end="", flush=True)
            proc.wait()
            result = proc

        if result.returncode != 0:
            print(
                f"Error: Flash failed with exit code {result.returncode}.\n"
                "Common causes: insufficient permissions (try with sudo), "
                "device busy, or incorrect target path.",
                file=sys.stderr,
            )
            sys.exit(result.returncode)

        print(f"Successfully flashed {selected_image.name} to {target}")

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export_resolved(
        self,
        resolved: ResolvedConfig,
        output_file: Optional[str] = None,
        label: str = "",
        repo_manifest: bool = False,
        lock: bool = False,
    ) -> None:
        """
        Export KAS configuration for the given ResolvedConfig.

        Args:
            resolved: Resolved build configuration
            output_file: Optional file path to save the configuration
            label: Descriptive label for log messages
        """
        export_kind = "Android repo manifest" if repo_manifest else "KAS configuration"
        logging.info(f"Exporting {export_kind} for {label or resolved.device.slug}")

        downloads = None
        sstate = None
        if self.env_manager:
            downloads = self.env_manager.get_value("DL_DIR")
            sstate = self.env_manager.get_value("SSTATE_DIR")

        # Use a temporary build directory for export
        with tempfile.TemporaryDirectory(prefix="bsp_export_") as temp_dir:
            if resolved.local_conf or resolved.targets:
                temp_fd, temp_path = tempfile.mkstemp(
                    prefix="bsp_composed_", suffix=".yml",
                    dir=str(self.config_path.parent),
                )
                os.close(temp_fd)
                self.resolver.generate_kas_yaml(
                    resolved,
                    temp_path,
                    base_dir=str(self.config_path.parent),
                )
                kas_files = [temp_path]
            else:
                base = self.config_path.parent
                kas_files = []
                for f in resolved.kas_files:
                    p = Path(f)
                    if p.is_absolute():
                        kas_files.append(str(p))
                    else:
                        kas_files.append(str((base / p).resolve()))
                temp_path = None

            try:
                kas_mgr = KasManager(
                    kas_files,
                    temp_dir,
                    download_dir=downloads,
                    sstate_dir=sstate,
                    use_container=False,
                    search_paths=[str(self.config_path.parent)],
                    env_manager=self.env_manager,
                )
                if repo_manifest:
                    exported_content = kas_mgr.export_repo_manifest_xml(output_file)
                else:
                    exported_content = kas_mgr.export_kas_config(output_file, lock=lock)
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)

        if not output_file:
            target_label = label or resolved.device.slug
            title = (
                f"Android Repo Manifest for {target_label}"
                if repo_manifest
                else f"KAS Configuration for {target_label}"
            )
            print("\n" + "=" * 60)
            print(title)
            print("=" * 60)
            print(exported_content)
            print("=" * 60)

        logging.info("Configuration exported successfully!")

    def export_bsp_config(
        self,
        bsp_name: str,
        output_file: Optional[str] = None,
        repo_manifest: bool = False,
        lock: bool = False,
    ) -> None:
        """
        Export KAS configuration for a BSP preset.

        Args:
            bsp_name: Name of the BSP preset to export
            output_file: Optional file path to save the configuration

        Raises:
            SystemExit: If preset not found or export fails
        """
        logging.info(f"Exporting KAS configuration for BSP preset: {bsp_name}")
        resolved, preset, _, reg_model, reg_resolver, reg_path = self._resolve_preset_multi(bsp_name)
        with self._use_registry_context(reg_model, reg_resolver, reg_path):
            self._export_resolved(
                resolved,
                output_file=output_file,
                label=f"{preset.name} - {preset.description}",
                repo_manifest=repo_manifest,
                lock=lock,
            )

    def export_by_components(
        self,
        device_slug: str,
        release_slug: str,
        feature_slugs: Optional[List[str]] = None,
        output_file: Optional[str] = None,
        repo_manifest: bool = False,
        lock: bool = False,
    ) -> None:
        """
        Export KAS configuration by specifying device, release, and features directly.

        Args:
            device_slug: Device slug
            release_slug: Release slug
            feature_slugs: Optional list of feature slugs
            output_file: Optional file path to save the configuration

        Raises:
            SystemExit: If any component is not found or export fails
        """
        logging.info(
            f"Exporting configuration for device={device_slug} release={release_slug} "
            f"features={feature_slugs or []}"
        )
        resolved = self.resolver.resolve(device_slug, release_slug, feature_slugs)
        self._export_resolved(
            resolved,
            output_file=output_file,
            label=f"{device_slug}/{release_slug}",
            repo_manifest=repo_manifest,
            lock=lock,
        )

    # ------------------------------------------------------------------
    # Deploy
    # ------------------------------------------------------------------

    def get_registry_deploy_config(self) -> Optional[DeployConfig]:
        """
        Return the root-level ``deploy`` config of the loaded registry.

        ``$ENV{VAR}`` placeholders in ``account_url`` are expanded.  Returns
        ``None`` when the registry defines no ``deploy`` block.
        """
        deploy = self.model.deploy if self.model else None
        if deploy is None:
            return None
        if deploy.account_url:
            deploy = replace(deploy, account_url=_expand_env(deploy.account_url))
        return deploy

    def _resolve_deploy_config(
        self,
        resolved: ResolvedConfig,
        preset: Optional[BspPreset] = None,
        deploy_overrides: Optional[Dict] = None,
    ) -> DeployConfig:
        """
        Resolve the effective ``DeployConfig`` for a build.

        Merge order (later entries override earlier ones):
        1. Root-level ``deploy`` from the registry (global defaults)
        2. Preset-level ``deploy`` (if the preset defines one) — only fields
           that differ from the ``DeployConfig`` defaults are applied, so a
           minimal preset block only needs to specify the fields it wants to
           override.
        3. CLI-supplied *deploy_overrides* dict

        If no deploy config is defined anywhere a default ``DeployConfig``
        is returned.

        Args:
            resolved: Resolved build configuration.
            preset: Optional BSP preset whose ``deploy`` block (if any) is
                    merged on top of the root-level config.
            deploy_overrides: Dict of field overrides from the CLI.

        Returns:
            Effective ``DeployConfig`` instance.
        """
        # Start with global registry deploy config or defaults
        base = self.get_registry_deploy_config() or DeployConfig()

        # Apply preset-level deploy overrides (only fields that differ from defaults)
        if preset is not None and preset.deploy is not None:
            preset_deploy = preset.deploy
            defaults = DeployConfig()
            preset_overrides = {
                f.name: getattr(preset_deploy, f.name)
                for f in dataclass_fields(preset_deploy)
                if getattr(preset_deploy, f.name) != getattr(defaults, f.name)
            }
            if preset_overrides:
                base = replace(base, **preset_overrides)

        # Apply CLI overrides
        if deploy_overrides:
            base = replace(base, **{k: v for k, v in deploy_overrides.items() if v is not None})

        return base

    @staticmethod
    def _normalize_cache_path(path: str) -> str:
        """Normalize a cache path to an absolute string."""
        return str(Path(path).expanduser().resolve())

    @staticmethod
    def _infer_yocto_topdir(build_path: str, artifact_dirs: List[str]) -> str:
        """
        Infer the Yocto TOPDIR from *build_path* and *artifact_dirs*.

        Yocto's ``DL_DIR`` and ``SSTATE_DIR`` default to subdirectories of
        ``TOPDIR`` (the directory passed to ``oe-init-build-env``).  The
        ``artifact_dirs`` in :class:`~bsp.models.DeployConfig` are relative
        to *build_path* and typically contain a ``tmp/`` segment, e.g.
        ``build/tmp/deploy/images``.  The prefix before the ``tmp/`` segment
        is the path from *build_path* to TOPDIR.

        Examples::

            artifact_dirs = ["tmp/deploy/images"]
            # tmp/ is at index 0 → no prefix → TOPDIR = build_path

            artifact_dirs = ["build/tmp/deploy/images"]
            # tmp/ is at index 1 → prefix = "build" → TOPDIR = build_path/build

        Args:
            build_path: Absolute or relative path to the BSP build directory.
            artifact_dirs: List of artifact directory paths relative to
                           *build_path*, as configured in
                           :attr:`~bsp.models.DeployConfig.artifact_dirs`.

        Returns:
            Inferred Yocto TOPDIR path string.  Falls back to *build_path*
            when no ``tmp/`` segment can be found in any artifact dir.
        """
        for adir in artifact_dirs:
            parts = Path(adir).parts
            if "tmp" in parts:
                tmp_idx = parts.index("tmp")
                if tmp_idx == 0:
                    return build_path
                prefix = Path(*parts[:tmp_idx])
                return str(Path(build_path) / prefix)
        return build_path

    def _resolve_cache_paths(
        self,
        deploy_cfg: "DeployConfig",
        build_path: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Return ``(downloads_path, sstate_path)`` for cache upload.

        Priority order:
        1. Explicit paths set in ``deploy_cfg.yocto_cache`` (from registry /
           CLI overrides).
        2. ``DL_DIR`` / ``SSTATE_DIR`` from the active
           :class:`~bsp.environment.EnvironmentManager`.
        3. Yocto defaults under the inferred TOPDIR
           (``<topdir>/downloads`` and ``<topdir>/sstate-cache``) where
           TOPDIR is derived from *build_path* and
           ``deploy_cfg.artifact_dirs``.
        4. ``None`` (cache upload skipped for that directory).

        Args:
            deploy_cfg: Effective deploy configuration.
            build_path: Effective build path used for Yocto default fallbacks.

        Returns:
            Tuple of (downloads_path, sstate_path); each may be ``None``.
        """
        cache_cfg = deploy_cfg.yocto_cache
        if not cache_cfg or not cache_cfg.enabled:
            return None, None

        downloads_path: Optional[str] = cache_cfg.downloads_path
        sstate_path: Optional[str] = cache_cfg.sstate_path

        if cache_cfg.downloads and not downloads_path and self.env_manager:
            downloads_path = self.env_manager.get_value("DL_DIR")
        if cache_cfg.sstate and not sstate_path and self.env_manager:
            sstate_path = self.env_manager.get_value("SSTATE_DIR")

        if build_path:
            yocto_topdir = Path(
                self._infer_yocto_topdir(build_path, deploy_cfg.artifact_dirs)
            )
            if cache_cfg.downloads and not downloads_path:
                downloads_path = str(yocto_topdir / "downloads")
            if cache_cfg.sstate and not sstate_path:
                sstate_path = str(yocto_topdir / "sstate-cache")

        if downloads_path:
            downloads_path = self._normalize_cache_path(downloads_path)
        if sstate_path:
            sstate_path = self._normalize_cache_path(sstate_path)

        return downloads_path, sstate_path

    def _resolve_cache_restore_paths(
        self,
        cache_downloads_dest: Optional[str] = None,
        cache_sstate_dest: Optional[str] = None,
        base_dir: Optional[str] = None,
        artifact_dirs: Optional[List[str]] = None,
        create_dirs: bool = False,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Return ``(downloads_dest, sstate_dest)`` for cache restore.

        Priority order:
        1. Explicit CLI/API overrides (*cache_downloads_dest* / *cache_sstate_dest*).
        2. ``DL_DIR`` / ``SSTATE_DIR`` from the active
           :class:`~bsp.environment.EnvironmentManager`.
        3. Yocto defaults under the inferred TOPDIR
           (``<topdir>/downloads`` and ``<topdir>/sstate-cache``) where
           TOPDIR is derived from *base_dir* and *artifact_dirs* via
           :meth:`_infer_yocto_topdir`.
        4. ``None`` (gatherer uses its own fallback behavior).

        Args:
            cache_downloads_dest: Explicit downloads destination or ``None``.
            cache_sstate_dest: Explicit sstate destination or ``None``.
            base_dir: Base directory for Yocto default fallbacks.
            artifact_dirs: Artifact directory list used to infer the Yocto
                           TOPDIR relative to *base_dir*.  Defaults to the
                           standard ``["tmp/deploy/images"]`` pattern when
                           ``None``.
            create_dirs: When ``True``, create resolved directories.

        Returns:
            Tuple of (downloads_dest, sstate_dest); each may be ``None``.
        """
        downloads_dest = cache_downloads_dest
        sstate_dest = cache_sstate_dest

        if not downloads_dest and self.env_manager:
            downloads_dest = self.env_manager.get_value("DL_DIR")
        if not sstate_dest and self.env_manager:
            sstate_dest = self.env_manager.get_value("SSTATE_DIR")

        if base_dir:
            effective_artifact_dirs = artifact_dirs or ["tmp/deploy/images"]
            yocto_topdir = Path(
                self._infer_yocto_topdir(base_dir, effective_artifact_dirs)
            )
            if not downloads_dest:
                downloads_dest = str(yocto_topdir / "downloads")
            if not sstate_dest:
                sstate_dest = str(yocto_topdir / "sstate-cache")

        if downloads_dest:
            downloads_dest = self._normalize_cache_path(downloads_dest)
            if create_dirs:
                Path(downloads_dest).mkdir(parents=True, exist_ok=True)
        if sstate_dest:
            sstate_dest = self._normalize_cache_path(sstate_dest)
            if create_dirs:
                Path(sstate_dest).mkdir(parents=True, exist_ok=True)

        return downloads_dest, sstate_dest

    def _deploy_resolved(
        self,
        resolved: ResolvedConfig,
        preset: Optional[BspPreset] = None,
        deploy_overrides: Optional[Dict] = None,
        dry_run: bool = False,
        build_path_override: Optional[str] = None,
        update_index: Optional[bool] = None,
    ) -> DeployResult:
        """
        Deploy build artifacts for the given ResolvedConfig.

        Args:
            resolved: Resolved build configuration containing build path and
                      device/release/distro metadata.
            preset: Optional BSP preset whose ``deploy`` block is applied on
                    top of the global deploy config before CLI overrides.
            deploy_overrides: CLI-level overrides for the deploy configuration.
            dry_run: When True log what would be uploaded without uploading.
            build_path_override: Optional build path override for artifact lookup.
            update_index: Force-enable/disable HTML index generation,
                          overriding ``deploy.index.enabled``.

        Returns:
            ``DeployResult`` with metadata for every uploaded artifact.
        """
        deploy_cfg = self._resolve_deploy_config(resolved, preset=preset, deploy_overrides=deploy_overrides)

        if dry_run:
            deploy_cfg = DeployConfig(**{**deploy_cfg.__dict__, "provider": deploy_cfg.provider})

        # Determine container/bucket name
        container_or_bucket = deploy_cfg.container or deploy_cfg.bucket
        if not container_or_bucket and not dry_run:
            logging.error(
                "No storage container/bucket configured for deployment. "
                "Set 'deploy.container' in the registry or pass --container/--bucket."
            )
            sys.exit(1)

        # Build provider-specific kwargs
        provider = deploy_cfg.provider
        if provider == "azure":
            backend_kwargs: Dict = {
                "container_name": container_or_bucket or "bsp-artifacts",
                "account_url": deploy_cfg.account_url,
                "dry_run": dry_run,
            }
        elif provider == "aws":
            backend_kwargs = {
                "bucket_name": container_or_bucket or "bsp-artifacts",
                "region": deploy_cfg.region,
                "profile": deploy_cfg.profile,
                "dry_run": dry_run,
            }
        else:
            logging.error("Unsupported deploy provider: %s", provider)
            sys.exit(1)

        try:
            backend = create_backend(provider, **backend_kwargs)
        except (ImportError, ValueError) as exc:
            logging.error("Failed to initialize storage backend: %s", exc)
            sys.exit(1)

        effective_build_path = (
            build_path_override if build_path_override is not None else resolved.build_path
        )
        # Resolve Yocto cache paths from config/env/default Yocto locations.
        downloads_path, sstate_path = self._resolve_cache_paths(
            deploy_cfg,
            build_path=effective_build_path,
        )

        deployer = ArtifactDeployer(deploy_cfg, backend)
        result = deployer.deploy(
            build_path=effective_build_path,
            device=resolved.device.slug,
            release=resolved.release.slug,
            distro=resolved.effective_distro or "",
            vendor=resolved.device.vendor,
            downloads_path=downloads_path,
            sstate_path=sstate_path,
            update_index=update_index,
            preset=getattr(preset, "name", "") or "",
        )

        # Print summary
        action = "[dry-run] Would upload" if dry_run else "Uploaded"
        if result.artifacts:
            print(f"\n{action} {result.success_count} artifact(s):")
            for art in result.artifacts:
                print(f"  {art.local_path.name} → {art.remote_url}")
            if result.manifest_url:
                print(f"  manifest.json → {result.manifest_url}")
            if result.index_url:
                print(f"  index.html → {result.index_url}")
        else:
            print("No artifacts found to deploy.")

        if result.cache_uploads:
            cache_action = "[dry-run] Would upload" if dry_run else "Uploaded"
            print(f"\n{cache_action} {len(result.cache_uploads)} Yocto cache archive(s):")
            for cu in result.cache_uploads:
                print(f"  {cu.cache_type}: {cu.local_archive.name} → {cu.remote_url}")

        return result

    def deploy_bsp(
        self,
        bsp_name: str,
        deploy_overrides: Optional[Dict] = None,
        dry_run: bool = False,
        update_index: Optional[bool] = None,
    ) -> DeployResult:
        """
        Deploy artifacts for a BSP preset.

        Args:
            bsp_name: Name of the BSP preset.
            deploy_overrides: CLI-level overrides for the deploy configuration.
            dry_run: When True list what would be uploaded without uploading.

        Returns:
            ``DeployResult`` with upload metadata.

        Raises:
            SystemExit: If preset not found or deployment fails.
        """
        logging.info("Deploying artifacts for BSP preset: %s", bsp_name)
        resolved, preset, _, reg_model, reg_resolver, reg_path = self._resolve_preset_multi(bsp_name)
        with self._use_registry_context(reg_model, reg_resolver, reg_path):
            return self._deploy_resolved(
                resolved, preset=preset, deploy_overrides=deploy_overrides,
                dry_run=dry_run, update_index=update_index,
            )

    def deploy_by_components(
        self,
        device_slug: str,
        release_slug: str,
        feature_slugs: Optional[List[str]] = None,
        deploy_overrides: Optional[Dict] = None,
        dry_run: bool = False,
        update_index: Optional[bool] = None,
    ) -> DeployResult:
        """
        Deploy artifacts by specifying device, release, and features directly.

        Args:
            device_slug: Device slug.
            release_slug: Release slug.
            feature_slugs: Optional list of feature slugs.
            deploy_overrides: CLI-level overrides for the deploy configuration.
            dry_run: When True list what would be uploaded without uploading.

        Returns:
            ``DeployResult`` with upload metadata.

        Raises:
            SystemExit: If any component is not found or deployment fails.
        """
        logging.info(
            "Deploying artifacts for device=%s release=%s features=%s",
            device_slug, release_slug, feature_slugs or [],
        )
        resolved = self.resolver.resolve(device_slug, release_slug, feature_slugs)
        return self._deploy_resolved(
            resolved, deploy_overrides=deploy_overrides, dry_run=dry_run,
            update_index=update_index,
        )

    # ------------------------------------------------------------------
    # Gather (download artifacts from cloud storage)
    # ------------------------------------------------------------------

    def _gather_resolved(
        self,
        resolved: ResolvedConfig,
        preset: Optional[BspPreset] = None,
        dest_dir: Optional[str] = None,
        deploy_overrides: Optional[Dict] = None,
        dry_run: bool = False,
        date_override: Optional[str] = None,
        gather_cache: bool = False,
        cache_downloads_dest: Optional[str] = None,
        cache_sstate_dest: Optional[str] = None,
    ) -> GatherResult:
        """
        Download build artifacts for the given :class:`~bsp.resolver.ResolvedConfig`.

        The effective :class:`~bsp.models.DeployConfig` is resolved with the
        same merge order as :meth:`_deploy_resolved` so that ``gather`` and
        ``deploy`` always refer to the same storage location.

        Args:
            resolved: Resolved build configuration containing device/release
                      metadata and the default local build path.
            preset: Optional BSP preset whose ``deploy`` block is applied on
                    top of the global deploy config before CLI overrides.
            dest_dir: Local directory to write downloaded artifacts into.
                      When ``None`` the Yocto image deploy directory
                      ``<build_path>/build/tmp/deploy/images`` under the build
                      path from *resolved* is used.
            deploy_overrides: CLI-level overrides for the deploy configuration.
            dry_run: When ``True`` log what would be downloaded without
                     actually downloading anything.
            date_override: Override for the ``{date}`` placeholder in the
                           prefix template (``YYYY-MM-DD``).
            gather_cache: When ``True``, attempt to download and restore Yocto
                          cache archives from cloud storage.
            cache_downloads_dest: Local path to restore the downloads cache into.
                                  Falls back to the env ``DL_DIR`` or a default
                                  sub-directory when ``None``.
            cache_sstate_dest: Local path to restore the sstate cache into.
                                Falls back to the env ``SSTATE_DIR`` or a
                                default sub-directory when ``None``.

        Returns:
            :class:`~bsp.gatherer.GatherResult` with the local paths of every
            downloaded artifact.
        """
        deploy_cfg = self._resolve_deploy_config(resolved, preset=preset, deploy_overrides=deploy_overrides)

        # Determine container/bucket name
        container_or_bucket = deploy_cfg.container or deploy_cfg.bucket
        if not container_or_bucket and not dry_run:
            logging.error(
                "No storage container/bucket configured for gather. "
                "Set 'deploy.container' in the registry or pass --container/--bucket."
            )
            sys.exit(1)

        # Build provider-specific kwargs
        provider = deploy_cfg.provider
        if provider == "azure":
            backend_kwargs: Dict = {
                "container_name": container_or_bucket or "bsp-artifacts",
                "account_url": deploy_cfg.account_url,
                "dry_run": dry_run,
            }
        elif provider == "aws":
            backend_kwargs = {
                "bucket_name": container_or_bucket or "bsp-artifacts",
                "region": deploy_cfg.region,
                "profile": deploy_cfg.profile,
                "dry_run": dry_run,
            }
        else:
            logging.error("Unsupported gather provider: %s", provider)
            sys.exit(1)

        try:
            backend = create_backend(provider, **backend_kwargs)
        except (ImportError, ValueError) as exc:
            logging.error("Failed to initialize storage backend: %s", exc)
            sys.exit(1)

        if dest_dir is not None:
            effective_dest = dest_dir
            cache_base_dir = dest_dir
        else:
            # Default artifact destination is the Yocto image deploy directory
            # so downstream commands (flash/image discovery) find the images.
            effective_dest = str(
                Path(resolved.build_path) / "build" / "tmp" / "deploy" / "images"
            )
            # Cache restore defaults stay anchored at the build root, not the
            # image deploy directory.
            cache_base_dir = resolved.build_path

        # Resolve cache destination directories (CLI overrides > env > Yocto defaults)
        effective_downloads_dest, effective_sstate_dest = self._resolve_cache_restore_paths(
            cache_downloads_dest=cache_downloads_dest,
            cache_sstate_dest=cache_sstate_dest,
            base_dir=cache_base_dir,
            artifact_dirs=deploy_cfg.artifact_dirs,
            create_dirs=(gather_cache and not dry_run),
        )

        gatherer = ArtifactGatherer(deploy_cfg, backend)
        result = gatherer.gather(
            dest_dir=effective_dest,
            device=resolved.device.slug,
            release=resolved.release.slug,
            distro=resolved.effective_distro or "",
            vendor=resolved.device.vendor,
            date_override=date_override,
            gather_cache=gather_cache,
            downloads_dest=effective_downloads_dest,
            sstate_dest=effective_sstate_dest,
        )

        # Print summary
        action = "[dry-run] Would download" if dry_run else "Downloaded"
        if result.artifacts:
            print(f"\n{action} {result.total_count} artifact(s) → {effective_dest}:")
            for local_path in result.artifacts:
                print(f"  {local_path.name}")
        else:
            print(f"No artifacts found to gather from '{provider}' storage.")

        if result.cache_artifacts:
            cache_action = "[dry-run] Would restore" if dry_run else "Restored"
            print(f"\n{cache_action} {len(result.cache_artifacts)} Yocto cache(s):")
            for cp in result.cache_artifacts:
                print(f"  {cp}")

        return result

    def gather_bsp(
        self,
        bsp_name: str,
        dest_dir: Optional[str] = None,
        deploy_overrides: Optional[Dict] = None,
        dry_run: bool = False,
        date_override: Optional[str] = None,
        gather_cache: bool = False,
        cache_downloads_dest: Optional[str] = None,
        cache_sstate_dest: Optional[str] = None,
    ) -> GatherResult:
        """
        Download artifacts for a BSP preset from cloud storage.

        Args:
            bsp_name: Name of the BSP preset.
            dest_dir: Local destination directory.  Defaults to
                      ``<build_path>/build/tmp/deploy/images`` under the
                      preset's configured build path when ``None``.
            deploy_overrides: CLI-level overrides for the deploy configuration.
            dry_run: When ``True`` log what would be downloaded without
                     actually downloading anything.
            date_override: Override for the ``{date}`` prefix placeholder.
            gather_cache: When ``True``, attempt to download and restore Yocto
                          cache archives alongside the regular artifacts.
            cache_downloads_dest: Local path to restore the downloads cache into.
            cache_sstate_dest: Local path to restore the sstate cache into.

        Returns:
            :class:`~bsp.gatherer.GatherResult` with download metadata.
        """
        logging.info("Gathering artifacts for BSP preset: %s", bsp_name)
        resolved, preset, _, reg_model, reg_resolver, reg_path = self._resolve_preset_multi(bsp_name)
        with self._use_registry_context(reg_model, reg_resolver, reg_path):
            return self._gather_resolved(
                resolved,
                preset=preset,
                dest_dir=dest_dir,
                deploy_overrides=deploy_overrides,
                dry_run=dry_run,
                date_override=date_override,
                gather_cache=gather_cache,
                cache_downloads_dest=cache_downloads_dest,
                cache_sstate_dest=cache_sstate_dest,
            )

    def gather_by_components(
        self,
        device_slug: str,
        release_slug: str,
        feature_slugs: Optional[List[str]] = None,
        dest_dir: Optional[str] = None,
        deploy_overrides: Optional[Dict] = None,
        dry_run: bool = False,
        date_override: Optional[str] = None,
        gather_cache: bool = False,
        cache_downloads_dest: Optional[str] = None,
        cache_sstate_dest: Optional[str] = None,
    ) -> GatherResult:
        """
        Download artifacts by specifying device, release, and features directly.

        Args:
            device_slug: Device slug.
            release_slug: Release slug.
            feature_slugs: Optional list of feature slugs.
            dest_dir: Local destination directory.  Defaults to
                      ``<build_path>/build/tmp/deploy/images`` under the
                      resolved build path when ``None``.
            deploy_overrides: CLI-level overrides for the deploy configuration.
            dry_run: When ``True`` log what would be downloaded without
                     actually downloading anything.
            date_override: Override for the ``{date}`` prefix placeholder.
            gather_cache: When ``True``, attempt to download and restore Yocto
                          cache archives alongside the regular artifacts.
            cache_downloads_dest: Local path to restore the downloads cache into.
            cache_sstate_dest: Local path to restore the sstate cache into.

        Returns:
            :class:`~bsp.gatherer.GatherResult` with download metadata.
        """
        logging.info(
            "Gathering artifacts for device=%s release=%s features=%s",
            device_slug, release_slug, feature_slugs or [],
        )
        resolved = self.resolver.resolve(device_slug, release_slug, feature_slugs)
        return self._gather_resolved(
            resolved,
            dest_dir=dest_dir,
            deploy_overrides=deploy_overrides,
            dry_run=dry_run,
            date_override=date_override,
            gather_cache=gather_cache,
            cache_downloads_dest=cache_downloads_dest,
            cache_sstate_dest=cache_sstate_dest,
        )

    # ------------------------------------------------------------------
    # Scan (CRA image vulnerability scanning)
    # ------------------------------------------------------------------

    def _resolve_scan_config(
        self,
        resolved: ResolvedConfig,
        preset: Optional[BspPreset] = None,
        scan_overrides: Optional[Dict] = None,
    ) -> ScanConfig:
        """
        Resolve the effective ``ScanConfig`` for a build.

        Merge order (later entries override earlier ones):
        1. Root-level ``scan`` from the registry (global defaults)
        2. ``ResolvedConfig.scan_config`` (preset-level ``scan`` block, if any)
        3. CLI-supplied *scan_overrides* dict

        If no scan config is defined anywhere a default ``ScanConfig`` is
        returned.

        Args:
            resolved: Resolved build configuration (may carry scan_config from preset).
            preset: Unused (reserved for future preset-level merge if needed).
            scan_overrides: Dict of field overrides from the CLI.

        Returns:
            Effective ``ScanConfig`` instance.
        """
        # Start with global registry scan config or defaults
        base = self.model.scan if self.model and self.model.scan else ScanConfig()

        # Apply preset-level scan config from ResolvedConfig (set by resolver.resolve_preset)
        if resolved.scan_config is not None:
            preset_scan = resolved.scan_config
            defaults = ScanConfig()
            preset_overrides = {
                f.name: preset_val
                for f in dataclass_fields(preset_scan)
                if (preset_val := getattr(preset_scan, f.name)) != getattr(defaults, f.name)
            }
            if preset_overrides:
                base = replace(base, **preset_overrides)

        # Apply CLI overrides
        if scan_overrides:
            base = replace(base, **{k: v for k, v in scan_overrides.items() if v is not None})

        return base

    def _scan_resolved(
        self,
        resolved: ResolvedConfig,
        preset: Optional[BspPreset] = None,
        scan_overrides: Optional[Dict] = None,
        dry_run: bool = False,
        build_path_override: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
    ) -> ScanResult:
        """
        Scan build artifacts for CVEs and generate SBOMs.

        Args:
            resolved: Resolved build configuration.
            preset: Optional BSP preset (for scan config merge).
            scan_overrides: CLI-level overrides for the scan configuration.
            dry_run: When True, discover and list artifacts without scanning.
            build_path_override: Optional build path override for artifact lookup.
            image_paths: Explicit list of image file paths to scan (overrides
                         auto-discovery when provided).

        Returns:
            :class:`~bsp.scanner.ScanResult` with findings and SBOM metadata.
        """
        scan_cfg = self._resolve_scan_config(resolved, preset=preset, scan_overrides=scan_overrides)
        effective_build_path = (
            build_path_override if build_path_override is not None else resolved.build_path
        )

        scanner = ImageScanner(scan_cfg, effective_build_path)

        if dry_run:
            artifacts = [Path(p) for p in image_paths] if image_paths else scanner._find_artifacts()
            logging.info("[dry-run] Would scan %d artifact(s):", len(artifacts))
            for art in artifacts:
                logging.info("  %s", art)
            result = ScanResult(fail_on=scan_cfg.fail_on, dry_run=True)
            result.scanned_artifacts = artifacts
            return result

        # Run the actual scan
        artifact_path_objs = [Path(p) for p in image_paths] if image_paths else None
        result = scanner.scan(artifact_paths=artifact_path_objs)

        # Print summary
        print(f"\nScan completed: {result.total_count} finding(s) across {len(result.scanned_artifacts)} artifact(s)")
        if result.total_count:
            sev_counts = [
                f"CRITICAL={result.critical_count}",
                f"HIGH={result.high_count}",
                f"MEDIUM={result.medium_count}",
                f"LOW={result.low_count}",
            ]
            print("  Severity breakdown: " + "  ".join(sev_counts))
        if result.sboms:
            print(f"  SBOM(s) generated:")
            for sbom in result.sboms:
                print(f"    {sbom.path} ({sbom.component_count} components, format: {sbom.sbom_format})")
        if result.report_files:
            print(f"  Report(s):")
            for rpt in result.report_files:
                print(f"    {rpt}")
        if not result.passed:
            logging.error(
                "Scan FAILED: findings at or above '%s' severity found.",
                scan_cfg.fail_on,
            )
        else:
            logging.info("Scan passed (no findings at or above '%s' severity).", scan_cfg.fail_on)

        return result

    def scan_bsp(
        self,
        bsp_name: str,
        scan_overrides: Optional[Dict] = None,
        dry_run: bool = False,
        image_paths: Optional[List[str]] = None,
    ) -> ScanResult:
        """
        Scan built artifacts for a BSP preset for CVEs and generate SBOMs.

        Args:
            bsp_name: Name of the BSP preset.
            scan_overrides: CLI-level overrides for the scan configuration.
            dry_run: When True list what would be scanned without scanning.
            image_paths: Explicit artifact paths to scan (overrides auto-discovery).

        Returns:
            :class:`~bsp.scanner.ScanResult` with findings and SBOM metadata.

        Raises:
            SystemExit: If preset not found or scanner is not installed.
        """
        logging.info("Scanning artifacts for BSP preset: %s", bsp_name)
        resolved, preset, _, reg_model, reg_resolver, reg_path = self._resolve_preset_multi(bsp_name)
        with self._use_registry_context(reg_model, reg_resolver, reg_path):
            result = self._scan_resolved(
                resolved,
                preset=preset,
                scan_overrides=scan_overrides,
                dry_run=dry_run,
                image_paths=image_paths,
            )
        if not result.passed and not dry_run:
            sys.exit(1)
        return result

    def scan_by_components(
        self,
        device_slug: str,
        release_slug: str,
        feature_slugs: Optional[List[str]] = None,
        scan_overrides: Optional[Dict] = None,
        dry_run: bool = False,
        image_paths: Optional[List[str]] = None,
    ) -> ScanResult:
        """
        Scan built artifacts by specifying device, release, and features directly.

        Args:
            device_slug: Device slug.
            release_slug: Release slug.
            feature_slugs: Optional list of feature slugs.
            scan_overrides: CLI-level overrides for the scan configuration.
            dry_run: When True list what would be scanned without scanning.
            image_paths: Explicit artifact paths to scan (overrides auto-discovery).

        Returns:
            :class:`~bsp.scanner.ScanResult` with findings and SBOM metadata.

        Raises:
            SystemExit: If any component is not found or scanner is not installed.
        """
        logging.info(
            "Scanning artifacts for device=%s release=%s features=%s",
            device_slug, release_slug, feature_slugs or [],
        )
        resolved = self.resolver.resolve(device_slug, release_slug, feature_slugs)
        result = self._scan_resolved(
            resolved,
            scan_overrides=scan_overrides,
            dry_run=dry_run,
            image_paths=image_paths,
        )
        if not result.passed and not dry_run:
            sys.exit(1)
        return result

    # ------------------------------------------------------------------
    # Flash (SD-card / block-device flashing via bmap-tools)
    # ------------------------------------------------------------------

    def _resolve_flash_config(
        self,
        resolved: ResolvedConfig,
        preset: Optional[BspPreset] = None,
        flash_overrides: Optional[Dict] = None,
    ) -> FlashConfig:
        """
        Resolve the effective ``FlashConfig`` for a build.

        Merge order (later entries override earlier ones):
        1. Root-level ``flash`` from the registry (global defaults)
        2. ``ResolvedConfig.flash_config`` (preset-level ``flash`` block, if any)
        3. CLI-supplied *flash_overrides* dict

        If no flash config is defined anywhere a default ``FlashConfig`` is
        returned.

        Args:
            resolved: Resolved build configuration (may carry flash_config from preset).
            preset: Unused (reserved for future preset-level merge if needed).
            flash_overrides: Dict of field overrides from the CLI.

        Returns:
            Effective ``FlashConfig`` instance.
        """
        # Start with global registry flash config or defaults
        base = self.model.flash if self.model and self.model.flash else FlashConfig()

        # Apply preset-level flash config from ResolvedConfig
        if resolved.flash_config is not None:
            preset_flash = resolved.flash_config
            defaults = FlashConfig()
            preset_overrides = {
                f.name: preset_val
                for f in dataclass_fields(preset_flash)
                if (preset_val := getattr(preset_flash, f.name)) != getattr(defaults, f.name)
            }
            if preset_overrides:
                base = replace(base, **preset_overrides)

        # Apply CLI overrides
        if flash_overrides:
            base = replace(base, **{k: v for k, v in flash_overrides.items() if v is not None})

        return base

    def _flash_resolved(
        self,
        resolved: ResolvedConfig,
        target_device: str,
        preset: Optional[BspPreset] = None,
        build_target: Optional[str] = None,
        flash_overrides: Optional[Dict] = None,
        image_path: Optional[str] = None,
        dry_run: bool = False,
        build_path_override: Optional[str] = None,
    ) -> FlashResult:
        """
        Flash build artifacts for the given ResolvedConfig.

        Args:
            resolved: Resolved build configuration.
            target_device: Block device path (e.g. ``/dev/sdb``).
            preset: Optional BSP preset (for flash config merge).
            build_target: Optional BitBake target used by ``bsp build --target``.
                          When provided, an additional high-priority image pattern
                          ``**/{build_target}.wic.*`` is prepended for
                          auto-discovery and any ``{build_target}`` placeholders
                          in configured image patterns are expanded.
            flash_overrides: CLI-level overrides for the flash configuration.
            image_path: Explicit path to the image file to flash.  Overrides
                        auto-discovery when provided.
            dry_run: When True, print what would be flashed without flashing.
            build_path_override: Optional build path override for artifact lookup.

        Returns:
            :class:`~bsp.flasher.FlashResult` with the outcome of the operation.
        """
        flash_cfg = self._resolve_flash_config(resolved, preset=preset, flash_overrides=flash_overrides)
        patterns = list(flash_cfg.image_patterns or [])
        if build_target:
            patterns = [
                p.replace("{build_target}", build_target) if "{build_target}" in p else p
                for p in patterns
            ]
            target_pattern = f"**/{build_target}.wic.*"
            patterns = [p for p in patterns if p != target_pattern]
            patterns.insert(0, target_pattern)
        flash_cfg = replace(flash_cfg, image_patterns=patterns)
        effective_build_path = (
            build_path_override if build_path_override is not None else resolved.build_path
        )

        flasher = ImageFlasher(flash_cfg)
        result = flasher.flash(
            build_path=effective_build_path,
            target_device=target_device,
            image_path=image_path,
            dry_run=dry_run,
        )

        if not result.success and not dry_run:
            sys.exit(1)

        return result

    def flash_bsp(
        self,
        bsp_name: str,
        target_device: str,
        flash_overrides: Optional[Dict] = None,
        image_path: Optional[str] = None,
        dry_run: bool = False,
        build_path_override: Optional[str] = None,
    ) -> FlashResult:
        """
        Flash built artifacts for a BSP preset to a block device.

        Args:
            bsp_name: Name of the BSP preset.
            target_device: Block device path (e.g. ``/dev/sdb``).
            flash_overrides: CLI-level overrides for the flash configuration.
            image_path: Explicit path to the image file to flash.
            dry_run: When True, print what would be flashed without flashing.
            build_path_override: If provided, overrides the build output path
                                 from the registry.

        Returns:
            :class:`~bsp.flasher.FlashResult` with the outcome of the operation.

        Raises:
            SystemExit: If preset not found or flash tool is not installed.
        """
        logging.info("Flashing artifacts for BSP preset: %s", bsp_name)
        resolved, preset, _, reg_model, reg_resolver, reg_path = self._resolve_preset_multi(bsp_name)
        with self._use_registry_context(reg_model, reg_resolver, reg_path):
            return self._flash_resolved(
                resolved,
                target_device=target_device,
                preset=preset,
                flash_overrides=flash_overrides,
                image_path=image_path,
                dry_run=dry_run,
                build_path_override=build_path_override,
            )

    def flash_by_components(
        self,
        device_slug: str,
        release_slug: str,
        target_device: str,
        feature_slugs: Optional[List[str]] = None,
        flash_overrides: Optional[Dict] = None,
        image_path: Optional[str] = None,
        dry_run: bool = False,
        build_path_override: Optional[str] = None,
    ) -> FlashResult:
        """
        Flash built artifacts by specifying device, release, and features directly.

        Args:
            device_slug: Device slug.
            release_slug: Release slug.
            target_device: Block device path (e.g. ``/dev/sdb``).
            feature_slugs: Optional list of feature slugs.
            flash_overrides: CLI-level overrides for the flash configuration.
            image_path: Explicit path to the image file to flash.
            dry_run: When True, print what would be flashed without flashing.
            build_path_override: If provided, overrides the build output path
                                 from the registry.

        Returns:
            :class:`~bsp.flasher.FlashResult` with the outcome of the operation.

        Raises:
            SystemExit: If any component is not found or flash tool is not installed.
        """
        logging.info(
            "Flashing artifacts for device=%s release=%s features=%s",
            device_slug, release_slug, feature_slugs or [],
        )
        resolved = self.resolver.resolve(device_slug, release_slug, feature_slugs)
        return self._flash_resolved(
            resolved,
            target_device=target_device,
            flash_overrides=flash_overrides,
            image_path=image_path,
            dry_run=dry_run,
            build_path_override=build_path_override,
        )

    # ------------------------------------------------------------------
    # Test backends (LAVA + direct local/SSH/serial)
    # ------------------------------------------------------------------

    def _print_test_summary(
        self,
        backend_name: str,
        suites: List[dict],
        extra: str = "",
        case_summary: Optional[dict] = None,
        cases: Optional[List[dict]] = None,
    ) -> None:
        """Print a backend-neutral test summary table.

        *case_summary* optionally carries aggregate per-test-case counts
        (total/passed/failed/not run/manual) collected from LAVA signals.
        *cases* optionally carries per-test-case rows (``suite``, ``id``,
        ``status``, ``description``) that are listed below the suite table so
        a terminal run also explains what each test case means.
        """
        if extra:
            print(extra)
        if not suites:
            print(f"{backend_name}: no test suite results.")
            return
        print(f"\n{backend_name} Test Results:")
        if case_summary and int(case_summary.get("total", 0)) > 0:
            print(
                f"  Tests: {int(case_summary.get('total', 0))} total, "
                f"{int(case_summary.get('passed', 0))} passed, "
                f"{int(case_summary.get('failed', 0))} failed, "
                f"{int(case_summary.get('not_run', 0))} not run, "
                f"{int(case_summary.get('manual', 0))} manual"
            )
        for suite in suites:
            passed = bool(suite.get("passed", False))
            status_icon = "✓" if passed else "✗"
            suite_name = str(suite.get("name", "suite"))
            total = int(suite.get("total", 0))
            failures = int(suite.get("failures", 0))
            duration = suite.get("duration")
            duration_str = f" ({duration:.2f}s)" if isinstance(duration, (int, float)) else ""
            print(
                f"  {status_icon} Suite: {suite_name:<30} "
                f"{'PASS' if passed else 'FAIL'}  "
                f"({total - failures}/{total} passed){duration_str}"
            )
        if cases:
            print("\nTest Cases:")
            for case in cases:
                description = str(case.get("description", ""))
                suffix = f" — {description}" if description else ""
                print(
                    f"  {str(case.get('status', '')):<10} "
                    f"{case.get('suite', '')}/{case.get('id', '')}{suffix}"
                )

    def _test_resolved_lava(
        self,
        resolved: ResolvedConfig,
        testing_config=None,
        lava_server: Optional[str] = None,
        lava_token: Optional[str] = None,
        artifact_url: Optional[str] = None,
        wait: bool = False,
        label: str = "",
    ) -> bool:
        """Run the LAVA backend test flow for a resolved configuration."""
        from .lava_client import LavaClient
        from .lava_job_builder import build_lava_job

        # Gather server-level defaults from the registry
        registry_lava = getattr(self.model, "lava", None) if self.model else None

        def _registry_lava_str(attr: str) -> str:
            """Return the expanded string value of a registry LAVA field, or ''."""
            return _expand_env(getattr(registry_lava, attr) if registry_lava else "")

        # Resolve LAVA connection settings (CLI > preset > registry)
        lava_cfg = testing_config.lava if (testing_config and testing_config.lava) else None

        server = lava_server or _registry_lava_str("server")
        token = lava_token or _registry_lava_str("token")
        username = _registry_lava_str("username")
        wait_timeout = registry_lava.wait_timeout if registry_lava else 3600
        poll_interval = registry_lava.poll_interval if registry_lava else 30

        device_type = lava_cfg.device_type if lava_cfg else ""
        job_template_path = None
        if lava_cfg and lava_cfg.job_template:
            tpl = Path(lava_cfg.job_template)
            if not tpl.is_absolute():
                tpl = (self.config_path.parent / tpl).resolve()
            job_template_path = str(tpl)

        # Resolve artifact_server_url: registry default → preset override
        effective_artifact_server_url = _expand_env(
            (lava_cfg.artifact_server_url if lava_cfg else "")
            or _registry_lava_str("artifact_server_url")
        )
        # Resolve artifact_name from the preset (no registry-level equivalent)
        effective_artifact_name = _expand_env(lava_cfg.artifact_name if lava_cfg else "")

        # Resolve artifact_url: CLI flag > preset artifact_url
        # artifact_url is the "full URL" escape hatch and wins over the
        # artifact_server_url + artifact_name composition.
        effective_artifact_url = _expand_env(
            artifact_url
            or (lava_cfg.artifact_url if lava_cfg else "")
        )

        lava_tags = lava_cfg.tags if lava_cfg else []

        # Resolve LAVA job context (arch / machine).
        # Priority for arch:    preset testing.lava.context.arch > device.architecture > ""
        # Priority for machine: preset testing.lava.context.machine > device.slug
        # The context dict is None only when both arch and machine end up empty.
        device_arch_fallback = getattr(resolved.device, "architecture", None) or ""
        device_machine_fallback = resolved.device.slug

        if lava_cfg and lava_cfg.context:
            effective_arch = lava_cfg.context.arch or device_arch_fallback
            effective_machine = lava_cfg.context.machine or device_machine_fallback
        else:
            effective_arch = device_arch_fallback
            effective_machine = device_machine_fallback

        if effective_arch or effective_machine:
            effective_lava_context: Optional[dict] = {
                "device_arch": effective_arch,
                "device_machine": effective_machine,
            }
        else:
            effective_lava_context = None

        robot_suites: List[str] = []
        robot_variables: dict = {}
        if lava_cfg and lava_cfg.robot:
            robot_suites = list(lava_cfg.robot.suites)
            robot_variables = {k: _expand_env(v) for k, v in lava_cfg.robot.variables.items()}

        if not server:
            logging.error(
                "LAVA server URL is not configured. "
                "Set it via --lava-server, the registry 'lava.server' field, "
                "or $ENV{LAVA_SERVER}."
            )
            return False

        if not device_type:
            logging.error(
                "LAVA device_type is not configured for this preset. "
                "Add a 'testing.lava.device_type' block to the preset in the registry."
            )
            return False

        logging.info("Building LAVA job definition for %s...", label or resolved.device.slug)
        job_yaml = build_lava_job(
            resolved=resolved,
            device_type=device_type,
            artifact_url=effective_artifact_url,
            artifact_server_url=effective_artifact_server_url,
            artifact_name=effective_artifact_name,
            lava_context=effective_lava_context,
            job_template_path=job_template_path,
            lava_tags=lava_tags,
            robot_suites=robot_suites,
            robot_variables=robot_variables,
            wait_timeout=wait_timeout,
        )
        logging.debug("LAVA job YAML:\n%s", job_yaml)

        client = LavaClient(
            server=server,
            token=token,
            username=username,
        )

        job_id = client.submit_job(job_yaml)
        job_url = client.job_url(job_id)
        print(f"LAVA Job ID: {job_id}")
        print(f"Job URL:     {job_url}")

        if not wait:
            print(
                "Job submitted. Re-run with --wait to block until the job completes."
            )
            return True

        try:
            health = client.wait_for_job(
                job_id, timeout=wait_timeout, poll_interval=poll_interval
            )
        except TimeoutError as exc:
            logging.error(str(exc))
            return False

        suites = client.get_job_results(job_id)
        overall_pass = health == "Complete" and all(s.passed for s in suites)

        if self.verbose:
            logging.debug("Collected %d LAVA suite(s) for job %d.", len(suites), job_id)
            for suite in suites:
                logging.debug(
                    "LAVA suite result: suite=%s status=%s (%d/%d passed)",
                    suite.name,
                    "PASS" if suite.passed else "FAIL",
                    suite.total - suite.failures,
                    suite.total,
                )
                for case in suite.cases:
                    logging.debug(
                        "LAVA case result: suite=%s case=%s status=%s metadata=%s",
                        suite.name,
                        case.name,
                        "PASS" if case.passed else "FAIL",
                        case.metadata,
                    )

        summary_suites = [
            {
                "name": s.name,
                "passed": s.passed,
                "total": s.total,
                "failures": s.failures,
            }
            for s in suites
        ]
        self._print_test_summary(
            "LAVA",
            summary_suites,
            extra=f"\nLAVA Job {job_id} — Health: {health}",
        )

        if not overall_pass:
            logging.error("HIL test run FAILED (job: %d).", job_id)
        else:
            logging.info("HIL test run PASSED (job: %d).", job_id)

        return overall_pass

    def _test_resolved_direct(
        self,
        resolved: ResolvedConfig,
        testing_config=None,
        backend: str = "direct-local",
        test_repo_url: Optional[str] = None,
        test_repo_ref: Optional[str] = None,
        test_definition_paths: Optional[List[str]] = None,
        test_job_paths: Optional[List[str]] = None,
        test_requirement_catalogs: Optional[List[str]] = None,
        test_suites: Optional[List[str]] = None,
        test_params: Optional[Dict[str, str]] = None,
        direct_timeout: Optional[int] = None,
        direct_output_dir: Optional[str] = None,
        ssh_host: Optional[str] = None,
        ssh_user: Optional[str] = None,
        ssh_port: Optional[int] = None,
        ssh_key: Optional[str] = None,
        ssh_password: Optional[str] = None,
        ssh_known_hosts_file: Optional[str] = None,
        ssh_strict_host_key_checking: Optional[bool] = None,
        ssh_remote_workdir: Optional[str] = None,
        ssh_serial_device: Optional[str] = None,
        ssh_serial_baudrate: Optional[int] = None,
        show_cases: bool = False,
        label: str = "",
    ) -> bool:
        """Run the direct-local/direct-ssh/direct-serial backend test flow."""
        from .direct_runner import DirectRunOverrides, DirectTestRunner
        from .requirements_catalog import humanize_test_case_id

        direct_cfg = testing_config.direct if (testing_config and testing_config.direct) else None
        runner = DirectTestRunner(config_path=self.config_path)

        overrides = DirectRunOverrides(
            backend=backend,
            repo_url=test_repo_url,
            repo_ref=test_repo_ref,
            definition_paths=test_definition_paths,
            local_job_paths=test_job_paths,
            requirement_catalog_paths=test_requirement_catalogs,
            suites=test_suites,
            params=test_params,
            timeout=direct_timeout,
            output_dir=direct_output_dir,
            ssh_host=ssh_host,
            ssh_user=ssh_user,
            ssh_port=ssh_port,
            ssh_key=ssh_key,
            ssh_password=ssh_password,
            ssh_known_hosts_file=ssh_known_hosts_file,
            ssh_strict_host_key_checking=ssh_strict_host_key_checking,
            ssh_remote_workdir=ssh_remote_workdir,
            ssh_serial_device=ssh_serial_device,
            ssh_serial_baudrate=ssh_serial_baudrate,
        )
        try:
            result = runner.run(
                resolved=resolved,
                direct_config=direct_cfg,
                overrides=overrides,
                label=label,
            )
        except Exception as exc:
            logging.error("Direct test execution failed: %s", exc)
            return False

        summary_suites = [
            {
                "name": suite.name,
                "passed": suite.status == "PASS",
                "total": len(suite.cases),
                "failures": sum(1 for c in suite.cases if c.status != "PASS"),
                "duration": suite.duration,
            }
            for suite in result.suites
        ]
        if self.verbose:
            logging.debug(
                "Collected %d direct suite(s) for backend %s.",
                len(result.suites),
                result.backend,
            )
            for suite in result.suites:
                passed_cases = sum(1 for case in suite.cases if case.status == "PASS")
                logging.debug(
                    "Direct suite result: suite=%s status=%s (%d/%d passed) duration=%.2fs log_dir=%s",
                    suite.name,
                    suite.status,
                    passed_cases,
                    len(suite.cases),
                    suite.duration,
                    suite.log_dir,
                )
                for case in suite.cases:
                    logging.debug(
                        "Direct case result: suite=%s case=%s status=%s duration=%.2fs log=%s command=%s",
                        suite.name,
                        case.name,
                        case.status,
                        case.duration,
                        case.log_path,
                        case.command,
                    )
                    for signal in case.lava_signals:
                        logging.debug(
                            "Direct test case: suite=%s id=%s requirement=%s status=%s description=%s",
                            suite.name,
                            signal.test_case_id,
                            signal.requirement_id,
                            signal.report_result,
                            signal.description,
                        )
        signals = [
            signal
            for suite in result.suites
            for case in suite.cases
            for signal in case.lava_signals
        ]
        case_summary = {
            "total": len(signals),
            "passed": sum(1 for s in signals if s.passed),
            "failed": sum(1 for s in signals if s.failed),
            "not_run": sum(1 for s in signals if s.not_run),
            "manual": sum(1 for s in signals if s.is_manual),
        }
        self._print_test_summary(
            f"Direct ({result.backend})",
            summary_suites,
            case_summary=case_summary,
            cases=(
                [
                    {
                        "suite": suite.name,
                        "id": signal.test_case_id,
                        "status": signal.report_result,
                        "description": (
                            signal.description
                            or humanize_test_case_id(signal.test_case_id)
                        ),
                    }
                    for suite in result.suites
                    for case in suite.cases
                    for signal in case.lava_signals
                ]
                if (show_cases or self.verbose)
                else None
            ),
        )
        return result.passed

    def _test_resolved(
        self,
        resolved: ResolvedConfig,
        testing_config=None,
        lava_server: Optional[str] = None,
        lava_token: Optional[str] = None,
        artifact_url: Optional[str] = None,
        wait: bool = False,
        backend: Optional[str] = None,
        test_repo_url: Optional[str] = None,
        test_repo_ref: Optional[str] = None,
        test_definition_paths: Optional[List[str]] = None,
        test_job_paths: Optional[List[str]] = None,
        test_requirement_catalogs: Optional[List[str]] = None,
        test_suites: Optional[List[str]] = None,
        test_params: Optional[Dict[str, str]] = None,
        direct_timeout: Optional[int] = None,
        direct_output_dir: Optional[str] = None,
        ssh_host: Optional[str] = None,
        ssh_user: Optional[str] = None,
        ssh_port: Optional[int] = None,
        ssh_key: Optional[str] = None,
        ssh_password: Optional[str] = None,
        ssh_known_hosts_file: Optional[str] = None,
        ssh_strict_host_key_checking: Optional[bool] = None,
        ssh_remote_workdir: Optional[str] = None,
        ssh_serial_device: Optional[str] = None,
        ssh_serial_baudrate: Optional[int] = None,
        show_cases: bool = False,
        label: str = "",
    ) -> bool:
        """
        Run test flow for the selected backend (LAVA, direct-local, direct-ssh, direct-serial).
        """
        selected_backend = backend
        if selected_backend is None and testing_config is not None:
            selected_backend = testing_config.backend
        if not selected_backend:
            selected_backend = "lava"
        selected_backend = selected_backend.strip()
        if selected_backend not in ("lava", "direct-local", "direct-ssh", "direct-serial"):
            logging.error(
                "Unsupported test backend '%s'. Supported values: lava, direct-local, direct-ssh, direct-serial.",
                selected_backend,
            )
            return False

        if selected_backend == "lava":
            if test_suites:
                logging.warning(
                    "--test-suite is only supported by direct backends and is ignored for the LAVA backend."
                )
            return self._test_resolved_lava(
                resolved=resolved,
                testing_config=testing_config,
                lava_server=lava_server,
                lava_token=lava_token,
                artifact_url=artifact_url,
                wait=wait,
                label=label,
            )

        if wait:
            logging.debug("--wait is ignored for direct backends (execution is synchronous).")

        return self._test_resolved_direct(
            resolved=resolved,
            testing_config=testing_config,
            backend=selected_backend,
            test_repo_url=test_repo_url,
            test_repo_ref=test_repo_ref,
            test_definition_paths=test_definition_paths,
            test_job_paths=test_job_paths,
            test_requirement_catalogs=test_requirement_catalogs,
            test_suites=test_suites,
            test_params=test_params,
            direct_timeout=direct_timeout,
            direct_output_dir=direct_output_dir,
            ssh_host=ssh_host,
            ssh_user=ssh_user,
            ssh_port=ssh_port,
            ssh_key=ssh_key,
            ssh_password=ssh_password,
            ssh_known_hosts_file=ssh_known_hosts_file,
            ssh_strict_host_key_checking=ssh_strict_host_key_checking,
            ssh_remote_workdir=ssh_remote_workdir,
            ssh_serial_device=ssh_serial_device,
            ssh_serial_baudrate=ssh_serial_baudrate,
            show_cases=show_cases,
            label=label,
        )

    def test_bsp(
        self,
        bsp_name: str,
        lava_server: Optional[str] = None,
        lava_token: Optional[str] = None,
        artifact_url: Optional[str] = None,
        wait: bool = False,
        backend: Optional[str] = None,
        test_repo_url: Optional[str] = None,
        test_repo_ref: Optional[str] = None,
        test_definition_paths: Optional[List[str]] = None,
        test_job_paths: Optional[List[str]] = None,
        test_requirement_catalogs: Optional[List[str]] = None,
        test_suites: Optional[List[str]] = None,
        test_params: Optional[Dict[str, str]] = None,
        direct_timeout: Optional[int] = None,
        direct_output_dir: Optional[str] = None,
        ssh_host: Optional[str] = None,
        ssh_user: Optional[str] = None,
        ssh_port: Optional[int] = None,
        ssh_key: Optional[str] = None,
        ssh_password: Optional[str] = None,
        ssh_known_hosts_file: Optional[str] = None,
        ssh_strict_host_key_checking: Optional[bool] = None,
        ssh_remote_workdir: Optional[str] = None,
        ssh_serial_device: Optional[str] = None,
        ssh_serial_baudrate: Optional[int] = None,
        show_cases: bool = False,
    ) -> bool:
        """
        Submit a LAVA HIL test job for a BSP preset.

        Args:
            bsp_name: Name of the BSP preset to test.
            lava_server: LAVA server URL override (CLI ``--lava-server``).
            lava_token: LAVA authentication token override (CLI
                        ``--lava-token``).
            artifact_url: Artifact base URL override (CLI ``--artifact-url``).
            wait: If ``True``, block until the LAVA job completes.

        Returns:
            ``True`` on success (or when *wait* is ``False``), ``False`` on
            test failure.

        Raises:
            SystemExit: If the preset is not found.
        """
        logging.info("Submitting HIL test for BSP preset: %s", bsp_name)
        resolved, preset, _, reg_model, reg_resolver, reg_path = self._resolve_preset_multi(bsp_name)
        testing_config = getattr(preset, "testing", None)
        with self._use_registry_context(reg_model, reg_resolver, reg_path):
            return self._test_resolved(
                resolved,
                testing_config=testing_config,
                lava_server=lava_server,
                lava_token=lava_token,
                artifact_url=artifact_url,
                wait=wait,
                backend=backend,
                test_repo_url=test_repo_url,
                test_repo_ref=test_repo_ref,
                test_definition_paths=test_definition_paths,
                test_job_paths=test_job_paths,
                test_requirement_catalogs=test_requirement_catalogs,
                test_suites=test_suites,
                test_params=test_params,
                direct_timeout=direct_timeout,
                direct_output_dir=direct_output_dir,
                ssh_host=ssh_host,
                ssh_user=ssh_user,
                ssh_port=ssh_port,
                ssh_key=ssh_key,
                ssh_password=ssh_password,
                ssh_known_hosts_file=ssh_known_hosts_file,
                ssh_strict_host_key_checking=ssh_strict_host_key_checking,
                ssh_remote_workdir=ssh_remote_workdir,
                ssh_serial_device=ssh_serial_device,
                ssh_serial_baudrate=ssh_serial_baudrate,
                show_cases=show_cases,
                label=f"{preset.name} - {preset.description}",
            )

    def test_by_components(
        self,
        device_slug: str,
        release_slug: str,
        feature_slugs: Optional[List[str]] = None,
        lava_server: Optional[str] = None,
        lava_token: Optional[str] = None,
        artifact_url: Optional[str] = None,
        wait: bool = False,
        backend: Optional[str] = None,
        test_repo_url: Optional[str] = None,
        test_repo_ref: Optional[str] = None,
        test_definition_paths: Optional[List[str]] = None,
        test_job_paths: Optional[List[str]] = None,
        test_requirement_catalogs: Optional[List[str]] = None,
        test_suites: Optional[List[str]] = None,
        test_params: Optional[Dict[str, str]] = None,
        direct_timeout: Optional[int] = None,
        direct_output_dir: Optional[str] = None,
        ssh_host: Optional[str] = None,
        ssh_user: Optional[str] = None,
        ssh_port: Optional[int] = None,
        ssh_key: Optional[str] = None,
        ssh_password: Optional[str] = None,
        ssh_known_hosts_file: Optional[str] = None,
        ssh_strict_host_key_checking: Optional[bool] = None,
        ssh_remote_workdir: Optional[str] = None,
        ssh_serial_device: Optional[str] = None,
        ssh_serial_baudrate: Optional[int] = None,
        show_cases: bool = False,
    ) -> bool:
        """
        Submit a LAVA HIL test job by specifying device, release, and features.

        When using component-based invocation (no preset), only the CLI flags
        and the registry-level ``lava:`` block are used for LAVA settings.

        Args:
            device_slug: Device slug.
            release_slug: Release slug.
            feature_slugs: Optional list of feature slugs.
            lava_server: LAVA server URL (required when no registry-level
                         ``lava.server`` is set).
            lava_token: LAVA authentication token.
            artifact_url: Base URL for image artifacts.
            wait: Block until job completes when ``True``.

        Returns:
            ``True`` on success (or when *wait* is ``False``), ``False`` on
            test failure.
        """
        logging.info(
            "Submitting HIL test for device=%s release=%s features=%s",
            device_slug,
            release_slug,
            feature_slugs or [],
        )
        resolved = self.resolver.resolve(device_slug, release_slug, feature_slugs)
        return self._test_resolved(
            resolved,
            testing_config=None,
            lava_server=lava_server,
            lava_token=lava_token,
            artifact_url=artifact_url,
            wait=wait,
            backend=backend,
            test_repo_url=test_repo_url,
            test_repo_ref=test_repo_ref,
            test_definition_paths=test_definition_paths,
            test_job_paths=test_job_paths,
            test_requirement_catalogs=test_requirement_catalogs,
            test_suites=test_suites,
            test_params=test_params,
            direct_timeout=direct_timeout,
            direct_output_dir=direct_output_dir,
            ssh_host=ssh_host,
            ssh_user=ssh_user,
            ssh_port=ssh_port,
            ssh_key=ssh_key,
            ssh_password=ssh_password,
            ssh_known_hosts_file=ssh_known_hosts_file,
            ssh_strict_host_key_checking=ssh_strict_host_key_checking,
            ssh_remote_workdir=ssh_remote_workdir,
            ssh_serial_device=ssh_serial_device,
            ssh_serial_baudrate=ssh_serial_baudrate,
            show_cases=show_cases,
            label=f"{device_slug}/{release_slug}",
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Cleanup resources and perform any necessary finalization."""
        logging.debug("Cleaning up resources...")
        self._cleanup_temp_kas_file()
