"""
Tests for the exception hierarchy and ColoramaFormatter.
"""

import logging
import pytest

import bsp
from bsp import (
    ScriptError,
    ConfigurationError,
    BuildError,
    DockerError,
    KasError,
)


# =============================================================================
# Tests for Exception Hierarchy
# =============================================================================

class TestExceptionHierarchy:
    def test_script_error_is_exception(self):
        assert issubclass(ScriptError, Exception)

    def test_configuration_error_inherits_script_error(self):
        assert issubclass(ConfigurationError, ScriptError)

    def test_build_error_inherits_script_error(self):
        assert issubclass(BuildError, ScriptError)

    def test_docker_error_inherits_script_error(self):
        assert issubclass(DockerError, ScriptError)

    def test_kas_error_inherits_script_error(self):
        assert issubclass(KasError, ScriptError)

    def test_raise_configuration_error(self):
        with pytest.raises(ConfigurationError):
            raise ConfigurationError("test error")

    def test_raise_build_error(self):
        with pytest.raises(BuildError):
            raise BuildError("build failed")


# =============================================================================
# Tests for ColoramaFormatter
# =============================================================================

class TestColoramaFormatter:
    def test_formatter_is_logging_formatter(self):
        formatter = bsp.ColoramaFormatter()
        assert isinstance(formatter, logging.Formatter)

    def test_format_record(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None
        )
        formatter = bsp.ColoramaFormatter()
        result = formatter.format(record)
        assert "Test message" in result
