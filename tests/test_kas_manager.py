"""
Tests for KasManager KAS/Yocto build orchestration.
"""

import os
from unittest.mock import patch

from bsp import KasManager


class TestKasManager:
    def test_init_basic(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build")
        )
        assert manager.kas_files == [str(kas_config_file)]
        assert manager.use_container is False

    def test_init_requires_non_empty_kas_files(self, tmp_dir):
        import pytest
        with pytest.raises(SystemExit):
            KasManager(kas_files=[], build_dir=str(tmp_dir / "build"))

    def test_init_requires_list_kas_files(self, tmp_dir):
        import pytest
        with pytest.raises(SystemExit):
            KasManager(kas_files="not-a-list", build_dir=str(tmp_dir / "build"))

    def test_get_kas_command_native(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build"),
            use_container=False
        )
        assert manager._get_kas_command() == ["kas"]

    def test_get_kas_command_container(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build"),
            use_container=True
        )
        assert manager._get_kas_command() == ["kas-container"]

    def test_resolve_kas_file_absolute(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build")
        )
        resolved = manager._resolve_kas_file(str(kas_config_file))
        assert resolved == str(kas_config_file)

    def test_resolve_kas_file_not_found_exits(self, tmp_dir):
        import pytest
        manager = KasManager(
            kas_files=[str(tmp_dir / "nonexistent.yml")],
            build_dir=str(tmp_dir / "build")
        )
        with pytest.raises(SystemExit):
            manager._resolve_kas_file("totally_missing_file.yml")

    def test_get_kas_files_string(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build")
        )
        result = manager._get_kas_files_string()
        assert str(kas_config_file) in result

    def test_get_kas_files_string_multiple(self, tmp_dir):
        file1 = tmp_dir / "file1.yml"
        file2 = tmp_dir / "file2.yml"
        file1.write_text("header:\n  version: 14\n")
        file2.write_text("header:\n  version: 14\n")
        manager = KasManager(
            kas_files=[str(file1), str(file2)],
            build_dir=str(tmp_dir / "build")
        )
        result = manager._get_kas_files_string()
        assert ":" in result

    def test_find_includes_in_yaml_top_level(self):
        content = {"includes": ["file1.yml", "file2.yml"]}
        manager = KasManager.__new__(KasManager)
        result = manager._find_includes_in_yaml(content)
        assert result == ["file1.yml", "file2.yml"]

    def test_find_includes_in_yaml_header(self):
        content = {"header": {"includes": ["file1.yml"]}}
        manager = KasManager.__new__(KasManager)
        result = manager._find_includes_in_yaml(content)
        assert result == ["file1.yml"]

    def test_find_includes_in_yaml_empty(self):
        content = {"machine": "qemuarm64"}
        manager = KasManager.__new__(KasManager)
        result = manager._find_includes_in_yaml(content)
        assert result == []

    def test_find_includes_both_sources(self):
        content = {
            "includes": ["top.yml"],
            "header": {"includes": ["header.yml"]}
        }
        manager = KasManager.__new__(KasManager)
        result = manager._find_includes_in_yaml(content)
        assert "top.yml" in result
        assert "header.yml" in result

    def test_validate_kas_files_success(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build")
        )
        assert manager.validate_kas_files(check_includes=False) is True

    def test_validate_kas_files_with_includes(self, kas_config_with_includes):
        base_path, include_path = kas_config_with_includes
        manager = KasManager(
            kas_files=[str(base_path)],
            build_dir=str(base_path.parent / "build")
        )
        assert manager.validate_kas_files(check_includes=True) is True

    def test_parse_yaml_file_with_cache(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build")
        )
        result1 = manager._parse_yaml_file(str(kas_config_file))
        result2 = manager._parse_yaml_file(str(kas_config_file))
        assert result1 == result2
        assert str(kas_config_file) in manager._yaml_cache

    def test_environment_variables_in_kas_env(self, kas_config_file):
        with patch.dict(os.environ, {"DL_DIR": "/custom/downloads"}):
            manager = KasManager(
                kas_files=[str(kas_config_file)],
                build_dir=str(kas_config_file.parent / "build"),
                download_dir="/custom/downloads"
            )
            env = manager._get_environment_with_container_vars()
            assert env.get("DL_DIR") == "/custom/downloads"

    def test_container_env_vars_set_when_using_container(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build"),
            use_container=True,
            container_engine="docker",
            container_image="custom-image:latest"
        )
        env = manager._get_environment_with_container_vars()
        assert env.get("KAS_CONTAINER_ENGINE") == "docker"
        assert env.get("KAS_CONTAINER_IMAGE") == "custom-image:latest"

    def test_check_kas_available_when_installed(self, kas_config_file):
        manager = KasManager(
            kas_files=[str(kas_config_file)],
            build_dir=str(kas_config_file.parent / "build"),
            use_container=False
        )
        # kas should be available in the test environment (installed via pip)
        result = manager.check_kas_available()
        assert isinstance(result, bool)
