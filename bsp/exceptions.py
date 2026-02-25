"""
Exception hierarchy and colored logging formatter for BSP registry tools.
"""

import logging

# =============================================================================
# Logging Colors
# =============================================================================

try:
    import colorama
    from colorama import Fore, Style
    colorama.init()  # Initialize colorama for Windows support
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False


class ColoramaFormatter(logging.Formatter):
    """Colored formatter using colorama for cross-platform compatibility."""

    if COLORAMA_AVAILABLE:
        COLOR_MAP = {
            logging.DEBUG: Fore.CYAN,
            logging.INFO: Fore.GREEN,
            logging.WARNING: Fore.YELLOW,
            logging.ERROR: Fore.RED,
            logging.CRITICAL: Fore.RED + Style.BRIGHT
        }
    else:
        # Fallback to ANSI codes if colorama not available
        COLOR_MAP = {
            logging.DEBUG: '\033[36m',
            logging.INFO: '\033[32m',
            logging.WARNING: '\033[33m',
            logging.ERROR: '\033[31m',
            logging.CRITICAL: '\033[1;31m'
        }

    RESET = Style.RESET_ALL if COLORAMA_AVAILABLE else '\033[0m'

    def format(self, record):
        color = self.COLOR_MAP.get(record.levelno, '')
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        record.msg = f"{color}{record.msg}{self.RESET}"
        return super().format(record)


# =============================================================================
# Exception Hierarchy
# =============================================================================

class ScriptError(Exception):
    """Base exception class for all script-related errors."""
    pass


class ConfigurationError(ScriptError):
    """Raised when there are issues with configuration files or settings."""
    pass


class BuildError(ScriptError):
    """Raised when build processes fail."""
    pass


class DockerError(ScriptError):
    """Raised when Docker operations fail."""
    pass


class KasError(ScriptError):
    """Raised when KAS operations fail."""
    pass
