"""
Shell tab-completion helpers for the ``bsp`` CLI.

Each completer is a callable that accepts ``(prefix, parsed_args, **kwargs)``
matching the argcomplete completer protocol and returns a list of completion
strings.  All completers swallow exceptions and return ``[]`` on failure so
that a broken registry never crashes the user's shell.

Usage (in cli.py)::

    from .completions import PresetsCompleter, DevicesCompleter
    arg = parser.add_argument("bsp_name", ...)
    arg.completer = PresetsCompleter()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

from .bsp_manager import BspManager
from .registry_fetcher import DEFAULT_BRANCH, RegistryFetcher, RemoteRegistrySpec
from .remotes_manager import RemotesManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared registry-manager factory
# ---------------------------------------------------------------------------


def _build_manager_for_completion(parsed_args) -> Optional[BspManager]:
    """Build a :class:`~bsp.bsp_manager.BspManager` suitable for completions.

    Mirrors the registry-resolution logic in ``cli.main()`` but always passes
    ``update=False`` so completions never trigger a slow ``git fetch``.

    Returns the initialised manager, or ``None`` if building it fails.
    """
    try:
        # --- mirror the registry-path resolution logic from main() ---
        LOCAL_DEFAULTS = ["bsp-registry.yaml", "bsp-registry.yml"]
        local_registry = next(
            (name for name in LOCAL_DEFAULTS if Path(name).is_file()), None
        )

        registry_arg = getattr(parsed_args, "registry", None)
        local_flag = getattr(parsed_args, "local", False)
        remote_arg = getattr(parsed_args, "remote", None)
        branch_arg = getattr(parsed_args, "branch", DEFAULT_BRANCH) or DEFAULT_BRANCH

        if registry_arg is not None:
            mgr = BspManager(registry_arg)
        elif local_flag:
            path = local_registry or LOCAL_DEFAULTS[0]
            mgr = BspManager(path)
        elif local_registry is not None:
            mgr = BspManager(local_registry)
        else:
            fetcher = RegistryFetcher()
            if remote_arg:
                remotes_raw = remote_arg if isinstance(remote_arg, list) else [remote_arg]
            else:
                stored = RemotesManager().ensure_default_remote(branch=branch_arg)
                remotes_raw = [
                    f"{r.url}@{r.branch}@name={r.name}" for r in stored
                ]

            # Every remote is fetched into its own cache subdirectory; the
            # cache dir itself is never used as a git repository.
            specs = [
                RemoteRegistrySpec.parse(r, default_branch=branch_arg)
                for r in remotes_raw
            ]
            registry_pairs = fetcher.fetch_multiple(specs, update=False)
            config_paths = [(name, str(path)) for name, path in registry_pairs]
            mgr = BspManager(config_paths=config_paths)

        mgr.initialize()
        return mgr

    except (Exception, SystemExit):  # pylint: disable=broad-except
        # BspManager.load_configuration() calls sys.exit(1) on registry errors
        # (missing file, invalid YAML, unsupported version, etc.).  Catching
        # SystemExit here prevents those errors from crashing the user's shell
        # session when tab-completion is triggered on a broken registry.
        logger.debug("_build_manager_for_completion failed", exc_info=True)
        return None


def _derive_completion_selection(
    parsed_args, mgr: BspManager
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Derive effective registry/device/release selection for completions."""
    device_slug: Optional[str] = getattr(parsed_args, "device", None)
    release_slug: Optional[str] = getattr(parsed_args, "release", None)
    bsp_name: Optional[str] = getattr(parsed_args, "bsp_name", None)
    if not bsp_name:
        return None, device_slug, release_slug

    registry_hint, preset_name = BspManager._parse_qualified_name(bsp_name)
    for reg_name, _reg_model, reg_resolver, _reg_path in mgr._iter_registries():
        if registry_hint is not None and reg_name != registry_hint:
            continue
        for preset in reg_resolver.list_presets():
            if preset.name == preset_name:
                return (
                    reg_name,
                    device_slug if device_slug is not None else preset.device,
                    release_slug if release_slug is not None else preset.release,
                )

    return registry_hint, device_slug, release_slug


# ---------------------------------------------------------------------------
# Completers
# ---------------------------------------------------------------------------


class PresetsCompleter:
    """Complete BSP preset names from the registry.

    In multi-registry mode both bare names (``preset``) and fully-qualified
    names (``registry:preset``) are returned so users can disambiguate when
    the same preset name exists in more than one registry.
    """

    def __call__(self, prefix: str, parsed_args, **kwargs) -> List[str]:
        try:
            mgr = _build_manager_for_completion(parsed_args)
            if mgr is None:
                return []
            results: List[str] = []
            multi = len(mgr.registries) > 1
            for reg_name, _reg_model, reg_resolver, _ in mgr._iter_registries():
                for preset in reg_resolver.list_presets():
                    results.append(preset.name)
                    if multi:
                        results.append(f"{reg_name}:{preset.name}")
            return results
        except (Exception, SystemExit):  # pylint: disable=broad-except
            return []


class ContainerCompleter:
    """Complete container names from the registry.

    In multi-registry mode both bare names (``container``) and fully-qualified
    names (``registry:container``) are returned so users can disambiguate when
    the same container name exists in more than one registry.
    """

    def __call__(self, prefix: str, parsed_args, **kwargs) -> List[str]:
        try:
            mgr = _build_manager_for_completion(parsed_args)
            if mgr is None:
                return []
            results: List[str] = []
            multi = len(mgr.registries) > 1
            for reg_name, reg_model, _reg_resolver, _ in mgr._iter_registries():
                containers = reg_model.containers or {} if reg_model else {}
                for container_name in containers:
                    results.append(container_name)
                    if multi:
                        results.append(f"{reg_name}:{container_name}")
            return results
        except (Exception, SystemExit):  # pylint: disable=broad-except
            return []


class DevicesCompleter:
    """Complete device slugs from the registry."""

    def __call__(self, prefix: str, parsed_args, **kwargs) -> List[str]:
        try:
            mgr = _build_manager_for_completion(parsed_args)
            if mgr is None:
                return []
            results: List[str] = []
            for _reg_name, reg_model, _reg_resolver, _ in mgr._iter_registries():
                devices = reg_model.registry.devices if reg_model else []
                for d in (devices or []):
                    results.append(d.slug)
            return results
        except (Exception, SystemExit):  # pylint: disable=broad-except
            return []


class ReleasesCompleter:
    """Complete release slugs from the registry.

    When ``--device`` is already present in the partial args the list is
    filtered to releases compatible with that device's vendor, matching the
    behaviour of ``BspManager.list_releases(device_slug=...)``.
    """

    def __call__(self, prefix: str, parsed_args, **kwargs) -> List[str]:
        try:
            mgr = _build_manager_for_completion(parsed_args)
            if mgr is None:
                return []
            device_slug: Optional[str] = getattr(parsed_args, "device", None)
            results: List[str] = []
            for _reg_name, reg_model, reg_resolver, _ in mgr._iter_registries():
                releases = reg_model.registry.releases if reg_model else []
                if not releases:
                    continue
                if device_slug:
                    try:
                        device = reg_resolver.get_device(device_slug)
                        releases = [
                            r
                            for r in releases
                            if not r.vendor_overrides
                            or any(
                                vo.vendor == device.vendor
                                for vo in r.vendor_overrides
                            )
                        ]
                    except SystemExit:
                        pass
                for r in releases:
                    results.append(r.slug)
            return results
        except (Exception, SystemExit):  # pylint: disable=broad-except
            return []


class FeaturesCompleter:
    """Complete feature slugs from the registry."""

    def __call__(self, prefix: str, parsed_args, **kwargs) -> List[str]:
        try:
            mgr = _build_manager_for_completion(parsed_args)
            if mgr is None:
                return []
            results: List[str] = []
            for _reg_name, reg_model, _reg_resolver, _ in mgr._iter_registries():
                features = reg_model.registry.features if reg_model else []
                for f in (features or []):
                    results.append(f.slug)
            return results
        except (Exception, SystemExit):  # pylint: disable=broad-except
            return []


class VendorReleaseCompleter:
    """Complete vendor release slugs from release vendor overrides."""

    def __call__(self, prefix: str, parsed_args, **kwargs) -> List[str]:
        try:
            mgr = _build_manager_for_completion(parsed_args)
            if mgr is None:
                return []
            registry_filter, device_slug, release_slug = _derive_completion_selection(
                parsed_args, mgr
            )
            results: List[str] = []
            for reg_name, reg_model, reg_resolver, _ in mgr._iter_registries():
                if registry_filter is not None and reg_name != registry_filter:
                    continue
                releases = reg_model.registry.releases if reg_model else []
                if not releases:
                    continue
                if release_slug:
                    releases = [r for r in releases if r.slug == release_slug]
                device_vendor: Optional[str] = None
                device_soc_vendor: Optional[str] = None
                if device_slug:
                    try:
                        device = reg_resolver.get_device(device_slug)
                        device_vendor = device.vendor
                        device_soc_vendor = device.soc_vendor
                    except SystemExit:
                        continue
                for release in releases:
                    for vo in (release.vendor_overrides or []):
                        if device_vendor and vo.vendor != device_vendor:
                            continue
                        results.extend(vr.slug for vr in (vo.releases or []))
                        if not vo.soc_vendors:
                            continue
                        if device_vendor and device_soc_vendor:
                            matching_svo = next(
                                (
                                    svo for svo in vo.soc_vendors
                                    if svo.vendor == device_soc_vendor
                                ),
                                None,
                            )
                            if matching_svo:
                                results.extend(vr.slug for vr in matching_svo.releases)
                        elif not device_vendor:
                            for svo in vo.soc_vendors:
                                results.extend(vr.slug for vr in svo.releases)
            return results
        except (Exception, SystemExit):  # pylint: disable=broad-except
            return []


class OverrideCompleter:
    """Complete vendor override slugs from release vendor overrides."""

    def __call__(self, prefix: str, parsed_args, **kwargs) -> List[str]:
        try:
            mgr = _build_manager_for_completion(parsed_args)
            if mgr is None:
                return []
            registry_filter, device_slug, release_slug = _derive_completion_selection(
                parsed_args, mgr
            )
            results: List[str] = []
            for reg_name, reg_model, reg_resolver, _ in mgr._iter_registries():
                if registry_filter is not None and reg_name != registry_filter:
                    continue
                releases = reg_model.registry.releases if reg_model else []
                if not releases:
                    continue
                if release_slug:
                    releases = [r for r in releases if r.slug == release_slug]
                device_vendor: Optional[str] = None
                if device_slug:
                    try:
                        device_vendor = reg_resolver.get_device(device_slug).vendor
                    except SystemExit:
                        continue
                for release in releases:
                    for vo in (release.vendor_overrides or []):
                        if device_vendor and vo.vendor != device_vendor:
                            continue
                        if vo.slug:
                            results.append(vo.slug)
            return results
        except (Exception, SystemExit):  # pylint: disable=broad-except
            return []


class RemotesCompleter:
    """Complete named remote names from ``~/.config/bsp/remotes.yaml``."""

    def __call__(self, prefix: str, parsed_args, **kwargs) -> List[str]:
        try:
            branch = getattr(parsed_args, "branch", DEFAULT_BRANCH)
            if branch is None:
                branch = DEFAULT_BRANCH
            return [r.name for r in RemotesManager().ensure_default_remote(branch=branch)]
        except (Exception, SystemExit):  # pylint: disable=broad-except
            return []



class TestSuitesCompleter:
    """Complete LAVA job test-suite names for ``--test-suite``.

    Suite names are read from ``actions[].test.definitions[].name`` of the
    ``--test-job-path`` files already present on the command line.
    """

    def __call__(self, prefix: str, parsed_args, **kwargs) -> List[str]:
        try:
            import yaml  # local import keeps completion startup cheap

            names: List[str] = []
            seen = set()
            for job_path in getattr(parsed_args, "test_job_paths", None) or []:
                path = Path(str(job_path)).expanduser()
                if not path.is_file() or path.suffix.lower() in (".jinja2", ".j2"):
                    continue
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if not isinstance(raw, dict):
                    continue
                for action in raw.get("actions", []) or []:
                    if not isinstance(action, dict):
                        continue
                    test_block = action.get("test")
                    if not isinstance(test_block, dict):
                        continue
                    for test_def in test_block.get("definitions", []) or []:
                        if not isinstance(test_def, dict):
                            continue
                        name = str(test_def.get("name") or "")
                        if name and name not in seen:
                            seen.add(name)
                            names.append(name)
            return [n for n in names if n.startswith(prefix)]
        except (Exception, SystemExit):  # pylint: disable=broad-except
            return []


class ScanToolCompleter:
    """Complete scanner backend names for ``--tool`` / ``--scan-tool``."""

    _TOOLS = ["trivy", "syft+grype", "emba"]

    def __call__(self, prefix: str, parsed_args, **kwargs) -> List[str]:
        return [t for t in self._TOOLS if t.startswith(prefix)]


class SeverityCompleter:
    """Complete CVE severity level names for ``--severity``, ``--fail-on``, etc."""

    _LEVELS = ["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

    def __call__(self, prefix: str, parsed_args, **kwargs) -> List[str]:
        return [lvl for lvl in self._LEVELS if lvl.startswith(prefix.upper())]
