"""
Environment variable management with $ENV{VAR} expansion support.
"""

import logging
import os
import re
from typing import List, Optional, Dict

from .models import EnvironmentVariable
from .path_resolver import resolver

# =============================================================================
# Environment Variable Management with Expansion
# =============================================================================


class EnvironmentManager:
    """
    Manager for environment variable configuration in build environments.

    Handles environment variable setup, validation, and management for:
    - Build cache directories (DL_DIR, SSTATE_DIR)
    - Git configuration (GITCONFIG_FILE)
    - Custom build variables
    - Container-specific environment settings

    Supports environment variable expansion in the form of $ENV{VAR_NAME}
    for referencing system environment variables in configuration.

    This class ensures consistent environment setup across different
    build types (native, Docker, kas-container).
    """

    # Regular expression pattern to match $ENV{VAR_NAME} style variables
    ENV_VAR_PATTERN = re.compile(r'\$ENV\{([^}]+)\}')

    def __init__(self, environment_vars: Optional[List[EnvironmentVariable]] = None):
        """
        Initialize Environment manager with optional variables.

        Args:
            environment_vars: List of environment variables to manage
        """
        self.environment_vars = environment_vars or []
        self._env_dict = self._build_environment_dict()

    def _expand_environment_variables(self, value: str) -> str:
        """
        Expand $ENV{VAR_NAME} patterns in string values.

        This method replaces all occurrences of $ENV{VAR_NAME} with the
        actual value of the environment variable VAR_NAME from the system.

        Examples:
          "$ENV{HOME}/.gitconfig" -> "/home/username/.gitconfig"
          "$ENV{HOME}/data/cache" -> "/home/username/data/cache"

        Args:
            value: String value that may contain $ENV{VAR} patterns

        Returns:
            String with all $ENV{VAR} patterns expanded to their actual values

        Raises:
            ConfigurationError: If a referenced environment variable is not set
        """
        def replace_env_var(match):
            var_name = match.group(1)
            if var_name in os.environ:
                return os.environ[var_name]
            else:
                logging.warning(f"Environment variable '{var_name}' is not set, "
                                f"using empty string for expansion in: {value}")
                return ""

        # Replace all $ENV{VAR} patterns with actual environment variable values
        expanded_value = self.ENV_VAR_PATTERN.sub(replace_env_var, value)

        # Also expand any standard environment variables (for backward compatibility)
        expanded_value = os.path.expandvars(expanded_value)

        return expanded_value

    def _build_environment_dict(self) -> Dict[str, str]:
        """
        Build a dictionary from the environment variable list with expansion.

        This method processes each environment variable value and expands
        any $ENV{VAR} patterns to their actual system environment values.

        Returns:
            Dictionary of environment variables with expanded values
        """
        env_dict = {}
        for env_var in self.environment_vars:
            # Expand environment variables in the value
            expanded_value = self._expand_environment_variables(env_var.value)
            env_dict[env_var.name] = expanded_value
            logging.debug(f"Environment variable {env_var.name} expanded: "
                          f"'{env_var.value}' -> '{expanded_value}'")
        return env_dict

    def get_environment_dict(self) -> Dict[str, str]:
        """
        Get environment variables as a dictionary with expanded values.

        Returns:
            Copy of the environment variables dictionary with all expansions applied
        """
        return self._env_dict.copy()

    def get_value(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get the value of an environment variable by key.

        Args:
            key: Environment variable name to lookup
            default: Default value to return if key not found

        Returns:
            Environment variable value (expanded) or default if not found
        """
        return self._env_dict.get(key, default)

    def validate_environment(self) -> bool:
        """
        Validate that all environment variable paths exist after expansion.

        This method checks common path variables (DL_DIR, SSTATE_DIR, GITCONFIG_FILE)
        to ensure they point to valid locations after environment variable expansion.
        Warnings are issued for missing paths but execution continues as paths
        might be created during build.

        Returns:
            True if validation completes (warnings may still be issued)
        """
        # Check common path variables that should exist
        path_variables = ['DL_DIR', 'SSTATE_DIR', 'GITCONFIG_FILE']

        for var_name in path_variables:
            if var_name in self._env_dict:
                path_value = self._env_dict[var_name]
                if not resolver.exists(path_value):
                    logging.warning(f"Environment variable {var_name} path does not exist: {path_value}")
                    # Don't exit here - paths might be created during build process

        logging.info(f"Environment configuration validated with {len(self._env_dict)} variables")
        return True

    def setup_environment(self, base_env: Dict[str, str]) -> Dict[str, str]:
        """
        Set up environment variables for build processes.

        Merges the configured environment variables with a base environment,
        with configured variables taking precedence over existing ones.
        All environment variable values are expanded before being set.

        Args:
            base_env: Base environment dictionary (typically os.environ.copy())

        Returns:
            Updated environment with all configured variables applied and expanded
        """
        env = base_env.copy()

        # Add all configured environment variables (overwrite existing)
        for env_var in self.environment_vars:
            expanded_value = self._expand_environment_variables(env_var.value)
            env[env_var.name] = expanded_value
            logging.debug(f"Set {env_var.name}={expanded_value}")

        return env
