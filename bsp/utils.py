"""
YAML parsing utilities and Docker build helper for BSP registry tools.
"""

import logging
import os
import re
import shlex
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version as pkg_version

import dacite
import yaml
from pathlib import Path
from typing import List, Optional, Dict, Any, Set

from .models import Docker, DockerArg, DockerVolume, RegistryRoot


def get_installed_package_version(package_name: str) -> str:
    """Return installed package version or ``unknown`` when unavailable."""
    try:
        return pkg_version(package_name)
    except PackageNotFoundError:
        return "unknown"


def expand_build_options_env(value: str) -> str:
    """Expand ``$ENV{VAR}`` placeholders in *value* with OS environment values.

    Unrecognised placeholders (variable not set) are left unchanged.
    This is the same ``$ENV{}`` convention used everywhere else in the registry.
    """
    def _replace(m: re.Match) -> str:
        return os.environ.get(m.group(1), m.group(0))
    return re.sub(r'\$ENV\{([^}]+)\}', _replace, value)


def normalize_build_option_tokens(tokens: List[str]) -> List[str]:
    """Normalize docker build-option tokens for compatibility across engines.

    Currently this rewrites ``--network=<mode>`` to ``--network <mode>``.
    """
    normalized: List[str] = []
    for token in tokens:
        if token.startswith("--network="):
            network_mode = token.split("=", 1)[1]
            normalized.extend(["--network", network_mode])
        else:
            normalized.append(token)
    return normalized

# =============================================================================
# YAML Configuration Parser with Container Support
# =============================================================================

SUPPORTED_REGISTRY_VERSION = "2.2"

# Registry schema follows semantic versioning (https://semver.org/).
# Minor-version increments are backward compatible: a tool supporting version
# MAJOR.MINOR accepts any registry that declares MAJOR.x where x <= MINOR.
_SUPPORTED_MAJOR, _SUPPORTED_MINOR = (int(p) for p in SUPPORTED_REGISTRY_VERSION.split("."))


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
                # Parse volumes list (each entry is a dict with host/container/read_only)
                raw_volumes = container_config.get('volumes', [])
                volumes = [
                    DockerVolume(
                        host=v['host'],
                        container=v['container'],
                        read_only=v.get('read_only', False),
                    )
                    for v in raw_volumes
                    if isinstance(v, dict) and 'host' in v and 'container' in v
                ]
                # Convert to Docker dataclass
                containers_dict[container_name] = Docker(
                    image=container_config.get('image'),
                    file=container_config.get('file'),
                    args=[DockerArg(name=arg['name'], value=arg['value'])
                          for arg in container_config.get('args', [])],
                    runtime_args=container_config.get('runtime_args'),
                    build_options=container_config.get('build_options'),
                    privileged=container_config.get('privileged', False),
                    copy=container_config.get('copy', []),
                    volumes=volumes,
                )
            else:
                logging.warning(f"Invalid container configuration for {container_name}, skipping")

    return containers_dict


def _deep_merge_yaml_dicts(base: Dict[Any, Any], override: Dict[Any, Any]) -> Dict[Any, Any]:
    """
    Deep-merge two YAML dictionaries.

    Merging rules:
    - Lists are concatenated: base list first, then override list.
    - Nested dicts are merged recursively with the same rules.
    - Scalar values: the *override* value wins.

    Args:
        base: Base dictionary (lower priority for scalars)
        override: Override dictionary (higher priority for scalars)

    Returns:
        New merged dictionary
    """
    result = dict(base)
    for key, value in override.items():
        if key in result:
            if isinstance(result[key], list) and isinstance(value, list):
                result[key] = [*result[key], *value]
            elif isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = _deep_merge_yaml_dicts(result[key], value)
            else:
                result[key] = value
        else:
            result[key] = value
    return result


def _load_and_merge_includes(filename: Path, _visited: Optional[Set[Path]] = None) -> Dict[Any, Any]:
    """
    Load a YAML file and recursively process ``include`` directives.

    When the parsed YAML contains a top-level ``include`` key its value must be
    a list of paths (relative to the file that contains the directive).  Each
    referenced file is loaded recursively and deep-merged into the result
    **before** the content of the current file is applied, so entries defined
    in the including file always take precedence over entries from the included
    files.

    The ``specification`` block is silently stripped from included files
    because version validation is performed only once on the root registry.

    Circular includes are detected and cause an immediate error exit.

    Args:
        filename: Absolute (or resolvable) path to the YAML file to load
        _visited: Set of already-visited canonical file paths used internally
                  for cycle detection; callers should leave this as ``None``.

    Returns:
        Merged YAML dictionary with all ``include`` directives resolved

    Raises:
        SystemExit: On I/O errors, YAML parse errors, circular includes, or if
                    the ``include`` value is not a list
    """
    if _visited is None:
        _visited = set()

    canonical = filename.resolve()
    if canonical in _visited:
        logging.error(f"Circular include detected: {filename}")
        sys.exit(1)
    _visited = _visited | {canonical}

    yaml_string = read_yaml_file(filename)
    yaml_dict = parse_yaml_file(yaml_string)

    if yaml_dict is None:
        return {}

    base_dir = filename.parent

    # Pop the include directive before any further processing
    includes = yaml_dict.pop('include', None)
    if includes is None:
        includes = []

    if not isinstance(includes, list):
        logging.error(f"'include' in {filename} must be a list of file paths")
        sys.exit(1)

    # Accumulate included content first (lower priority)
    accumulated: Dict[Any, Any] = {}
    for include_path in includes:
        include_file = (base_dir / include_path).resolve()
        logging.debug(f"Processing include: {include_file}")
        included_dict = _load_and_merge_includes(Path(include_file), _visited)
        # Strip specification from included files; only root file is validated
        included_dict.pop('specification', None)
        accumulated = _deep_merge_yaml_dicts(accumulated, included_dict)

    # Merge current file on top (higher priority)
    return _deep_merge_yaml_dicts(accumulated, yaml_dict)


# Slug-keyed registry lists: list name -> identifying key.  Used when merging
# a registry overlay so that an overlay entry with an existing slug/name
# deep-merges into the base entry instead of being appended as a duplicate.
_REGISTRY_KEYED_LISTS: Dict[str, str] = {
    "devices": "slug",
    "releases": "slug",
    "features": "slug",
    "distro": "slug",
    "frameworks": "slug",
    "vendors": "slug",
    "bsp": "name",
}


def _merge_keyed_list(base: List[Any], override: List[Any], key: str) -> List[Any]:
    """Merge two lists of dicts by identifying *key*.

    Entries in *override* whose key matches an entry in *base* are deep-merged
    into (and override) the base entry in place; entries with new keys are
    appended.  Non-dict or key-less entries are appended as-is.
    """
    result = list(base)
    index = {
        item.get(key): i
        for i, item in enumerate(result)
        if isinstance(item, dict) and item.get(key) is not None
    }
    for item in override:
        if isinstance(item, dict) and item.get(key) is not None and item.get(key) in index:
            i = index[item[key]]
            result[i] = _deep_merge_yaml_dicts(result[i], item)
        else:
            result.append(item)
    return result


def merge_registry_overlay(base: Dict[Any, Any], overlay: Dict[Any, Any]) -> Dict[Any, Any]:
    """Merge a registry *overlay* document on top of a *base* registry dict.

    Like :func:`_deep_merge_yaml_dicts` (scalars from the overlay win, nested
    dicts merge recursively) with one refinement: the slug/name-keyed lists
    under ``registry`` (``devices``, ``releases``, ``features``, ``distro``,
    ``frameworks``, ``vendors``, ``bsp``) merge entries **by their
    identifying key** instead of concatenating, so an overlay entry with an
    existing slug overrides the base entry while new slugs are appended.

    The overlay's ``specification`` block is stripped, mirroring how include
    files are treated: version validation applies only to the base registry.
    """
    overlay = dict(overlay)
    overlay.pop("specification", None)

    result = dict(base)
    for key, value in overlay.items():
        if key == "registry" and isinstance(result.get(key), dict) and isinstance(value, dict):
            base_reg = dict(result[key])
            for reg_key, reg_value in value.items():
                keyed = _REGISTRY_KEYED_LISTS.get(reg_key)
                if (
                    keyed
                    and isinstance(base_reg.get(reg_key), list)
                    and isinstance(reg_value, list)
                ):
                    base_reg[reg_key] = _merge_keyed_list(
                        base_reg[reg_key], reg_value, keyed
                    )
                elif isinstance(base_reg.get(reg_key), dict) and isinstance(reg_value, dict):
                    base_reg[reg_key] = _deep_merge_yaml_dicts(base_reg[reg_key], reg_value)
                else:
                    base_reg[reg_key] = reg_value
            result[key] = base_reg
        elif isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge_yaml_dicts(result[key], value)
        else:
            result[key] = value
    return result


def get_registry_from_yaml_file(
    filename: Path,
    overlay_registry: Optional[Path] = None,
    overlay_name: Optional[str] = None,
) -> RegistryRoot:
    """
    Parse YAML file into structured RegistryRoot object using dacite.

    This function converts the raw YAML dictionary into strongly-typed
    dataclasses with comprehensive type checking and validation.

    Top-level ``include`` directives are resolved first so that a registry can
    be split across multiple files::

        include:
          - devices/boards.yaml
          - releases/scarthgap.yaml

    Included paths are relative to the file that contains the directive and
    can themselves contain further ``include`` directives.

    Args:
        filename: Path to registry YAML file
        overlay_registry: Optional path to a registry overlay YAML document
                          merged on top of the loaded registry (slug-aware,
                          see :func:`merge_registry_overlay`) before type
                          validation.  Include directives inside the overlay
                          are resolved relative to the overlay file.
        overlay_name: Optional overlay name used in log/error messages when
                      *overlay_registry* is given.

    Returns:
        Structured registry configuration as RegistryRoot object

    Raises:
        SystemExit: If configuration is invalid, malformed, or missing required fields
    """
    yaml_dict = _load_and_merge_includes(filename)

    # Fail fast if the registry version is not supported.
    # Schema follows semver: accept any MAJOR.x where x <= supported MINOR.
    spec = yaml_dict.get('specification') or {}
    version = spec.get('version') if isinstance(spec, dict) else None
    _version_ok = False
    if isinstance(version, str) and version.count(".") == 1:
        try:
            v_major, v_minor = (int(p) for p in version.split("."))
            _version_ok = (v_major == _SUPPORTED_MAJOR and v_minor <= _SUPPORTED_MINOR)
        except ValueError:
            pass
    if not _version_ok:
        logging.error(
            f"Unsupported registry version '{version}' in {filename}. "
            f"This tool supports schema versions "
            f"{_SUPPORTED_MAJOR}.0 – {SUPPORTED_REGISTRY_VERSION}. "
            f"See docs/migration-v1-to-v2.md in the bsp-registry-tools repository "
            f"for upgrade instructions."
        )
        sys.exit(1)

    # Apply an overlay registry document (slug-aware merge) before validation
    if overlay_registry is not None:
        label = f"overlay '{overlay_name}'" if overlay_name else "registry overlay"
        if not Path(overlay_registry).is_file():
            logging.error(
                f"Registry overlay file for {label} not found: {overlay_registry}"
            )
            sys.exit(1)
        try:
            overlay_dict = _load_and_merge_includes(Path(overlay_registry))
        except SystemExit:
            logging.error(f"Error while applying {label} registry: {overlay_registry}")
            raise
        yaml_dict = merge_registry_overlay(yaml_dict, overlay_dict)
        logging.info(
            f"Registry overlay active ({label}): {overlay_registry}"
        )

    # Pre-process containers list to dictionary format if needed
    if 'containers' in yaml_dict and isinstance(yaml_dict['containers'], list):
        logging.debug("Converting containers list to dictionary format")
        yaml_dict['containers'] = convert_containers_list_to_dict(yaml_dict['containers'])

    try:
        # Use dacite to convert dictionary to strongly-typed dataclass
        # strict=False allows forward compatibility with new fields
        # The DockerVolume type hook converts raw dicts to DockerVolume objects.
        cfg = dacite.Config(
            strict=False,
            type_hooks={DockerVolume: lambda d: DockerVolume(**d) if isinstance(d, dict) else d},
        )
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
                 build_args: Optional[List[DockerArg]] = None,
                 verbose: bool = False,
                 build_options: Optional[str] = None) -> None:
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
        verbose: If True, stream docker build output live; otherwise show
                 only a status message and suppress build output
        build_options: Extra flags appended to the ``docker build`` command
                       before the build context (e.g. ``--no-cache
                       --network host``).  Split with shell quoting rules.
                       ``$ENV{VAR}`` placeholders are expanded at build time
                       (e.g. ``$ENV{BSP_REGISTRY_DOCKER_BUILD_OPTIONS}``).

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

        # Add extra build options (e.g. --no-cache, --network host).
        # Expand $ENV{VAR} placeholders so users can write
        #   build_options: "$ENV{BSP_REGISTRY_DOCKER_BUILD_OPTIONS}"
        # and have the variable resolved at build time.
        if build_options:
            raw_tokens = shlex.split(expand_build_options_env(build_options))
            cmd.extend(normalize_build_option_tokens(raw_tokens))

        cmd.extend(["."])  # Build context is current directory

        logging.info(f"Running: {' '.join(cmd)}")

        if verbose:
            # Stream docker build output live so the user can follow progress
            subprocess.run(cmd, check=True)
        else:
            # Quiet mode: show a brief status line, then suppress build output
            print(f"Preparing docker environment: {tag} ...")
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if result.stdout:
                logging.debug(result.stdout)
            if result.stderr:
                logging.debug(result.stderr)

        logging.info("Docker build completed successfully")

    except subprocess.CalledProcessError as e:
        logging.error(f"Docker build failed with return code {e.returncode}")
        if e.stderr:
            logging.error(f"Error output: {e.stderr}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error during Docker build: {e}")
        sys.exit(1)
    finally:
        # Always return to original directory regardless of build outcome
        os.chdir(original_dir)
