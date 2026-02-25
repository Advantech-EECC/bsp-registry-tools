"""
Tests for PathResolver utility class.
"""

from pathlib import Path

from bsp import PathResolver


class TestPathResolver:
    def test_resolve_returns_path(self, tmp_dir):
        result = PathResolver.resolve(str(tmp_dir))
        assert isinstance(result, Path)

    def test_resolve_str_returns_string(self, tmp_dir):
        result = PathResolver.resolve_str(str(tmp_dir))
        assert isinstance(result, str)

    def test_resolve_tilde_expansion(self):
        result = PathResolver.resolve("~")
        assert str(result) == str(Path.home())

    def test_exists_true_for_existing(self, tmp_dir):
        assert PathResolver.exists(str(tmp_dir)) is True

    def test_exists_false_for_nonexistent(self, tmp_dir):
        assert PathResolver.exists(str(tmp_dir / "nonexistent")) is False

    def test_is_file_true(self, tmp_dir):
        test_file = tmp_dir / "test.txt"
        test_file.write_text("content")
        assert PathResolver.is_file(str(test_file)) is True

    def test_is_file_false_for_dir(self, tmp_dir):
        assert PathResolver.is_file(str(tmp_dir)) is False

    def test_is_dir_true(self, tmp_dir):
        assert PathResolver.is_dir(str(tmp_dir)) is True

    def test_is_dir_false_for_file(self, tmp_dir):
        test_file = tmp_dir / "test.txt"
        test_file.write_text("content")
        assert PathResolver.is_dir(str(test_file)) is False

    def test_ensure_directory_creates_dir(self, tmp_dir):
        new_dir = tmp_dir / "new" / "nested" / "dir"
        PathResolver.ensure_directory(str(new_dir))
        assert new_dir.is_dir()

    def test_ensure_directory_existing_dir_ok(self, tmp_dir):
        # Should not raise for existing directories
        PathResolver.ensure_directory(str(tmp_dir))
        assert tmp_dir.is_dir()
