"""
Path resolution utility for BSP registry tools.
"""

import logging
import sys
from pathlib import Path

# =============================================================================
# Path Resolution Utility
# =============================================================================


class PathResolver:
    """
    Utility class for path resolution and validation.

    Provides centralized methods for handling path operations with:
    - Home directory expansion (~/ paths)
    - Existence and type validation
    - Directory creation with proper error handling
    - Consistent path normalization

    All methods handle path strings with home directory notation and
    provide consistent behavior across different platforms.
    """

    @staticmethod
    def resolve(path_string: str) -> Path:
        """
        Resolve path with ~ expansion to absolute Path object.

        Args:
            path_string: Path string that may contain ~ for home directory

        Returns:
            Resolved absolute Path object
        """
        return Path(path_string).expanduser().resolve()

    @staticmethod
    def resolve_str(path_string: str) -> str:
        """
        Resolve path with ~ expansion to absolute string.

        Args:
            path_string: Path string that may contain ~ for home directory

        Returns:
            Resolved absolute path as string
        """
        return str(PathResolver.resolve(path_string))

    @staticmethod
    def exists(path_string: str) -> bool:
        """
        Check if path exists after resolving ~ expansion.

        Args:
            path_string: Path to check for existence

        Returns:
            True if path exists, False otherwise
        """
        return PathResolver.resolve(path_string).exists()

    @staticmethod
    def is_file(path_string: str) -> bool:
        """
        Check if path is a file after resolving ~ expansion.

        Args:
            path_string: Path to check

        Returns:
            True if path exists and is a file, False otherwise
        """
        return PathResolver.resolve(path_string).is_file()

    @staticmethod
    def is_dir(path_string: str) -> bool:
        """
        Check if path is a directory after resolving ~ expansion.

        Args:
            path_string: Path to check

        Returns:
            True if path exists and is a directory, False otherwise
        """
        return PathResolver.resolve(path_string).is_dir()

    @staticmethod
    def ensure_directory(path_string: str) -> None:
        """
        Ensure directory exists, create if necessary with parent directories.

        This method creates the directory and all intermediate directories
        if they don't exist, similar to 'mkdir -p' command.

        Args:
            path_string: Directory path to ensure existence of

        Raises:
            SystemExit: If directory cannot be created due to permissions or I/O errors
        """
        path = PathResolver.resolve(path_string)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except (OSError, IOError) as e:
            logging.error(f"Failed to create directory {path}: {e}")
            sys.exit(1)


# Global path resolver instance for consistent path handling
resolver = PathResolver()
