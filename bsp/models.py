"""
Configuration data classes for BSP registry definitions.
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
# Configuration Data Classes
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
    """
    image: Optional[str]
    file: Optional[str]
    args: List[DockerArg] = field(default_factory=empty_list)


@dataclass
class ContainerDefinition:
    """
    Container definition with name and Docker configuration.

    Attributes:
        name: Container name/identifier (e.g., 'ubuntu-20.04')
        docker: Docker configuration for this container
    """
    name: str
    docker: Docker


@dataclass
class BuildEnvironment:
    """
    Build environment configuration including Docker settings.

    Attributes:
        container: Name of the container to use (references containers in registry)
        docker: Direct Docker configuration (alternative to container reference)
    """
    container: Optional[str] = None
    docker: Optional[Docker] = None


@dataclass
class BuildSetup:
    """
    Complete build setup configuration.

    Attributes:
        path: Build directory path for output artifacts
        environment: Build environment settings (Docker, container reference)
        docker: Docker runtime to use (docker, podman, etc.)
        configuration: List of KAS configuration files for the build
    """
    path: str
    environment: BuildEnvironment
    docker: Optional[str]
    configuration: List[str]


@dataclass
class Specification:
    """
    Registry specification version.

    Attributes:
        version: Specification version string (e.g., '1.0')
    """
    version: str


@dataclass
class OperatingSystem:
    """
    Operating system configuration for the BSP.

    Attributes:
        name: OS name (e.g., 'linux')
        build_system: Build system (e.g., 'yocto')
        version: OS version string
    """
    name: str
    build_system: str
    version: str


@dataclass
class BSP:
    """
    Board Support Package definition.

    Attributes:
        name: Unique BSP identifier
        description: Human-readable description
        os: Operating system configuration
        build: Build configuration and setup
    """
    name: str
    description: str
    build: BuildSetup
    os: Optional[OperatingSystem] = None


@dataclass
class Registry:
    """
    Main registry containing BSP definitions.

    Attributes:
        bsp: List of BSP definitions in the registry
    """
    bsp: Optional[List[BSP]] = field(default_factory=empty_list)


@dataclass
class RegistryRoot:
    """
    Root container for the registry configuration.

    Attributes:
        specification: Specification version information
        registry: Main registry data containing BSP definitions
        containers: Dictionary of container definitions keyed by name
        environment: Global environment variables for all builds (supports expansion)
    """
    specification: Specification
    registry: Registry
    containers: Optional[Dict[str, Docker]] = field(default_factory=empty_dict)
    environment: Optional[List[EnvironmentVariable]] = field(default_factory=empty_list)
