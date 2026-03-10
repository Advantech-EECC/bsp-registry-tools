"""
YAML parsing utilities and Docker build helper for BSP registry tools.
"""

import logging
import os
import subprocess
import sys

import dacite
import yaml
from pathlib import Path
from typing import List, Optional, Dict, Any

from .models import Docker, DockerArg, RegistryRoot

# =============================================================================
# YAML Configuration Parser with Container Support
# =============================================================================

SUPPORTED_REGISTRY_VERSION = "2.0"


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
                # Convert to Docker dataclass
                containers_dict[container_name] = Docker(
                    image=container_config.get('image'),
                    file=container_config.get('file'),
                    args=[DockerArg(name=arg['name'], value=arg['value'])
                          for arg in container_config.get('args', [])],
                    runtime_args=container_config.get('runtime_args'),
                    privileged=container_config.get('privileged', False)
                )
            else:
                logging.warning(f"Invalid container configuration for {container_name}, skipping")

    return containers_dict


def get_registry_from_yaml_file(filename: Path) -> RegistryRoot:
    """
    Parse YAML file into structured RegistryRoot object using dacite.

    This function converts the raw YAML dictionary into strongly-typed
    dataclasses with comprehensive type checking and validation.

    Args:
        filename: Path to registry YAML file

    Returns:
        Structured registry configuration as RegistryRoot object

    Raises:
        SystemExit: If configuration is invalid, malformed, or missing required fields
    """
    yaml_string = read_yaml_file(filename)
    yaml_dict = parse_yaml_file(yaml_string)

    # Fail fast if the registry version is not supported
    spec = yaml_dict.get('specification') or {}
    version = spec.get('version') if isinstance(spec, dict) else None
    if version != SUPPORTED_REGISTRY_VERSION:
        logging.error(
            f"Unsupported registry version '{version}' in {filename}. "
            f"This tool requires version '{SUPPORTED_REGISTRY_VERSION}'. "
            f"See docs/migration-v1-to-v2.md in the bsp-registry-tools repository "
            f"for upgrade instructions."
        )
        sys.exit(1)

    # Pre-process containers list to dictionary format if needed
    if 'containers' in yaml_dict and isinstance(yaml_dict['containers'], list):
        logging.debug("Converting containers list to dictionary format")
        yaml_dict['containers'] = convert_containers_list_to_dict(yaml_dict['containers'])

    try:
        # Use dacite to convert dictionary to strongly-typed dataclass
        # strict=False allows forward compatibility with new fields
        cfg = dacite.Config(strict=False)
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
                 verbose: bool = False) -> None:
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
