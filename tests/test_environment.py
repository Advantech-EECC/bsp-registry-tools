"""
Tests for EnvironmentManager with $ENV{VAR} expansion.
"""

import logging
import os
from unittest.mock import patch

from bsp import EnvironmentVariable, EnvironmentManager


class TestEnvironmentManager:
    def test_init_empty(self):
        manager = EnvironmentManager()
        assert manager.get_environment_dict() == {}

    def test_init_with_variables(self):
        vars_ = [
            EnvironmentVariable(name="VAR1", value="value1"),
            EnvironmentVariable(name="VAR2", value="value2"),
        ]
        manager = EnvironmentManager(vars_)
        env_dict = manager.get_environment_dict()
        assert env_dict["VAR1"] == "value1"
        assert env_dict["VAR2"] == "value2"

    def test_expand_env_var_pattern(self):
        with patch.dict(os.environ, {"MY_HOME": "/home/testuser"}):
            vars_ = [EnvironmentVariable(name="DL_DIR", value="$ENV{MY_HOME}/downloads")]
            manager = EnvironmentManager(vars_)
            assert manager.get_value("DL_DIR") == "/home/testuser/downloads"

    def test_expand_env_var_missing_warns(self, caplog):
        vars_ = [EnvironmentVariable(name="TEST_VAR", value="$ENV{NONEXISTENT_VAR_12345}/path")]
        with caplog.at_level(logging.WARNING):
            manager = EnvironmentManager(vars_)
        assert manager.get_value("TEST_VAR") == "/path"

    def test_get_value_existing(self):
        vars_ = [EnvironmentVariable(name="MY_KEY", value="my_val")]
        manager = EnvironmentManager(vars_)
        assert manager.get_value("MY_KEY") == "my_val"

    def test_get_value_missing_returns_default(self):
        manager = EnvironmentManager()
        assert manager.get_value("MISSING_KEY", "default") == "default"

    def test_get_value_missing_returns_none(self):
        manager = EnvironmentManager()
        assert manager.get_value("MISSING_KEY") is None

    def test_get_environment_dict_returns_copy(self):
        vars_ = [EnvironmentVariable(name="KEY", value="value")]
        manager = EnvironmentManager(vars_)
        d1 = manager.get_environment_dict()
        d1["NEW_KEY"] = "new_value"
        d2 = manager.get_environment_dict()
        assert "NEW_KEY" not in d2

    def test_validate_environment_returns_true(self):
        manager = EnvironmentManager()
        assert manager.validate_environment() is True

    def test_setup_environment_merges(self):
        vars_ = [EnvironmentVariable(name="MY_VAR", value="configured")]
        manager = EnvironmentManager(vars_)
        base = {"EXISTING": "base_value", "MY_VAR": "original"}
        result = manager.setup_environment(base)
        assert result["EXISTING"] == "base_value"
        assert result["MY_VAR"] == "configured"

    def test_setup_environment_does_not_modify_base(self):
        vars_ = [EnvironmentVariable(name="NEW_VAR", value="new_value")]
        manager = EnvironmentManager(vars_)
        base = {"EXISTING": "base_value"}
        manager.setup_environment(base)
        assert "NEW_VAR" not in base

    def test_multiple_env_expansions(self):
        with patch.dict(os.environ, {"USER": "testuser", "HOST": "testhost"}):
            vars_ = [
                EnvironmentVariable(name="FULL_ADDR", value="$ENV{USER}@$ENV{HOST}")
            ]
            manager = EnvironmentManager(vars_)
            assert manager.get_value("FULL_ADDR") == "testuser@testhost"
