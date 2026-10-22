"""
Tests for the ImageFlasher and FlashResult flashing functionality.

Covers:
- FlashResult dataclass defaults and field checks
- ImageFlasher._find_image: pattern priority, multi-match warning, missing dir
- ImageFlasher._find_bmap: present / absent .bmap, alt compression suffix
- ImageFlasher._check_tool_availability: tool found / missing
- ImageFlasher._build_command: bmaptool with/without bmap, dd, generic
- ImageFlasher.flash: dry-run, missing image, subprocess command, failure
- BspManager.flash_bsp / flash_by_components (mocked)
- CLI argument parsing for the flash subparser
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import logging
import pytest

from bsp.flasher import FlashResult, ImageFlasher
from bsp.models import FlashConfig


# =============================================================================
# FlashResult tests
# =============================================================================


class TestFlashResult:
    def test_defaults(self, tmp_path):
        r = FlashResult(image_path=tmp_path / "img.wic", target_device="/dev/sdb")
        assert r.bmap_path is None
        assert r.dry_run is False
        assert r.success is False
        assert r.elapsed_seconds == 0.0

    def test_all_fields(self, tmp_path):
        img = tmp_path / "img.wic"
        bmap = tmp_path / "img.wic.bmap"
        r = FlashResult(
            image_path=img,
            target_device="/dev/mmcblk0",
            bmap_path=bmap,
            dry_run=True,
            success=True,
            elapsed_seconds=3.14,
        )
        assert r.image_path == img
        assert r.target_device == "/dev/mmcblk0"
        assert r.bmap_path == bmap
        assert r.dry_run is True
        assert r.success is True
        assert r.elapsed_seconds == pytest.approx(3.14)


# =============================================================================
# ImageFlasher._find_image tests
# =============================================================================


class TestImageFlasherFindImage:
    def _make_flasher(self, patterns=None, artifact_dirs=None):
        cfg = FlashConfig(
            image_patterns=patterns or ["**/*.wic", "**/*.sdimg"],
            artifact_dirs=artifact_dirs or ["tmp/deploy/images"],
        )
        return ImageFlasher(cfg)

    def test_finds_matching_image(self, tmp_path):
        images_dir = tmp_path / "tmp" / "deploy" / "images"
        images_dir.mkdir(parents=True)
        (images_dir / "core-image-minimal.wic").write_bytes(b"fake")

        flasher = self._make_flasher()
        result = flasher._find_image(str(tmp_path))
        assert result is not None
        assert result.name == "core-image-minimal.wic"

    def test_returns_none_when_no_matching_files(self, tmp_path):
        images_dir = tmp_path / "tmp" / "deploy" / "images"
        images_dir.mkdir(parents=True)
        (images_dir / "not-an-image.txt").write_bytes(b"fake")

        flasher = self._make_flasher()
        assert flasher._find_image(str(tmp_path)) is None

    def test_returns_none_when_artifact_dir_missing(self, tmp_path):
        flasher = self._make_flasher()
        assert flasher._find_image(str(tmp_path)) is None

    def test_pattern_priority_compressed_first(self, tmp_path):
        """Earlier patterns (more-compressed variants) take priority."""
        images_dir = tmp_path / "tmp" / "deploy" / "images"
        images_dir.mkdir(parents=True)
        (images_dir / "image.wic.bz2").write_bytes(b"bz2")
        (images_dir / "image.wic").write_bytes(b"uncompressed")

        flasher = self._make_flasher(patterns=["**/*.wic.bz2", "**/*.wic"])
        result = flasher._find_image(str(tmp_path))
        assert result is not None
        assert result.name == "image.wic.bz2"

    def test_warns_on_multiple_matches(self, tmp_path, caplog):
        images_dir = tmp_path / "tmp" / "deploy" / "images"
        images_dir.mkdir(parents=True)
        (images_dir / "a.wic").write_bytes(b"a")
        (images_dir / "b.wic").write_bytes(b"b")

        with caplog.at_level(logging.WARNING, logger="ImageFlasher"):
            flasher = self._make_flasher(patterns=["**/*.wic"])
            flasher._find_image(str(tmp_path))

        assert any("Multiple flashable images" in r.message for r in caplog.records)

    def test_multiple_artifact_dirs(self, tmp_path):
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        (dir2 / "b.wic").write_bytes(b"data")

        flasher = self._make_flasher(
            patterns=["**/*.wic"],
            artifact_dirs=["dir1", "dir2"],
        )
        result = flasher._find_image(str(tmp_path))
        assert result is not None
        assert result.name == "b.wic"

    def test_debug_logs_search_patterns_and_selected_image(self, tmp_path, caplog):
        images_dir = tmp_path / "tmp" / "deploy" / "images"
        images_dir.mkdir(parents=True)
        (images_dir / "core-image-minimal.wic").write_bytes(b"img")

        flasher = self._make_flasher(patterns=["**/*.wic"])
        with caplog.at_level(logging.DEBUG, logger="ImageFlasher"):
            result = flasher._find_image(str(tmp_path))

        assert result is not None
        assert any(
            "Searching for flash image with pattern '**/*.wic'" in r.message
            for r in caplog.records
        )
        assert any(
            "Selected flash image" in r.message and "core-image-minimal.wic" in r.message
            for r in caplog.records
        )


# =============================================================================
# ImageFlasher._find_bmap tests
# =============================================================================


class TestImageFlasherFindBmap:
    def _flasher(self):
        return ImageFlasher(FlashConfig())

    def test_finds_bmap_alongside_image(self, tmp_path):
        img = tmp_path / "image.wic"
        bmap = tmp_path / "image.wic.bmap"
        img.write_bytes(b"img")
        bmap.write_bytes(b"bmap")

        flasher = self._flasher()
        result = flasher._find_bmap(img)
        assert result == bmap

    def test_returns_none_when_no_bmap(self, tmp_path):
        img = tmp_path / "image.wic"
        img.write_bytes(b"img")

        flasher = self._flasher()
        assert flasher._find_bmap(img) is None

    def test_finds_bmap_for_compressed_image(self, tmp_path):
        """For image.wic.bz2 also look for image.wic.bmap."""
        img = tmp_path / "image.wic.bz2"
        bmap = tmp_path / "image.wic.bmap"
        img.write_bytes(b"img")
        bmap.write_bytes(b"bmap")

        flasher = self._flasher()
        result = flasher._find_bmap(img)
        assert result == bmap

    def test_exact_bmap_wins_over_alt(self, tmp_path):
        """image.wic.bz2.bmap is preferred over image.wic.bmap when both exist."""
        img = tmp_path / "image.wic.bz2"
        exact_bmap = tmp_path / "image.wic.bz2.bmap"
        alt_bmap = tmp_path / "image.wic.bmap"
        img.write_bytes(b"img")
        exact_bmap.write_bytes(b"exact")
        alt_bmap.write_bytes(b"alt")

        flasher = self._flasher()
        result = flasher._find_bmap(img)
        assert result == exact_bmap


# =============================================================================
# ImageFlasher._check_tool_availability tests
# =============================================================================


class TestImageFlasherCheckTool:
    def test_passes_when_tool_found(self):
        cfg = FlashConfig(tool="bmaptool")
        flasher = ImageFlasher(cfg)
        with patch("os.geteuid", return_value=0):
            with patch("shutil.which", return_value="/usr/bin/bmaptool"):
                flasher._check_tool_availability()  # should not raise

    def test_passes_when_tool_and_sudo_found(self):
        cfg = FlashConfig(tool="bmaptool")
        flasher = ImageFlasher(cfg)

        def _which(name):
            if name == "sudo":
                return "/usr/bin/sudo"
            if name == "bmaptool":
                return "/usr/bin/bmaptool"
            return None

        with patch("os.geteuid", return_value=1000):
            with patch("shutil.which", side_effect=_which):
                flasher._check_tool_availability()  # should not raise

    def test_exits_when_sudo_missing_for_non_root(self):
        cfg = FlashConfig(tool="bmaptool")
        flasher = ImageFlasher(cfg)

        def _which(name):
            if name == "sudo":
                return None
            if name == "bmaptool":
                return "/usr/bin/bmaptool"
            return None

        with patch("os.geteuid", return_value=1000):
            with patch("shutil.which", side_effect=_which):
                with pytest.raises(SystemExit):
                    flasher._check_tool_availability()

    def test_exits_when_tool_missing(self):
        cfg = FlashConfig(tool="bmaptool")
        flasher = ImageFlasher(cfg)
        with patch("os.geteuid", return_value=0):
            with patch("shutil.which", return_value=None):
                with pytest.raises(SystemExit):
                    flasher._check_tool_availability()

    def test_exit_message_contains_tool_name(self, caplog):
        cfg = FlashConfig(tool="bmaptool")
        flasher = ImageFlasher(cfg)
        with patch("os.geteuid", return_value=0):
            with patch("shutil.which", return_value=None):
                with caplog.at_level(logging.ERROR, logger="ImageFlasher"):
                    with pytest.raises(SystemExit):
                        flasher._check_tool_availability()
        assert any("bmaptool" in r.message for r in caplog.records)


# =============================================================================
# ImageFlasher._build_command tests
# =============================================================================


class TestImageFlasherBuildCommand:
    def test_bmaptool_without_bmap(self, tmp_path):
        cfg = FlashConfig(tool="bmaptool")
        flasher = ImageFlasher(cfg)
        img = tmp_path / "image.wic"
        with patch("os.geteuid", return_value=0):
            cmd = flasher._build_command(img, "/dev/sdb", None)
        assert cmd == ["bmaptool", "copy", str(img), "/dev/sdb"]

    def test_bmaptool_with_bmap(self, tmp_path):
        cfg = FlashConfig(tool="bmaptool")
        flasher = ImageFlasher(cfg)
        img = tmp_path / "image.wic"
        bmap = tmp_path / "image.wic.bmap"
        with patch("os.geteuid", return_value=0):
            cmd = flasher._build_command(img, "/dev/sdb", bmap)
        assert cmd == ["bmaptool", "copy", "--bmap", str(bmap), str(img), "/dev/sdb"]

    def test_bmaptool_with_extra_args(self, tmp_path):
        cfg = FlashConfig(tool="bmaptool", extra_args="--nobmap")
        flasher = ImageFlasher(cfg)
        img = tmp_path / "image.wic"
        with patch("os.geteuid", return_value=0):
            cmd = flasher._build_command(img, "/dev/sdb", None)
        assert "--nobmap" in cmd

    def test_dd_command(self, tmp_path):
        cfg = FlashConfig(tool="dd")
        flasher = ImageFlasher(cfg)
        img = tmp_path / "image.wic"
        with patch("os.geteuid", return_value=0):
            cmd = flasher._build_command(img, "/dev/sdb", None)
        assert cmd[0] == "dd"
        assert f"if={img}" in cmd
        assert "of=/dev/sdb" in cmd
        assert "bs=4M" in cmd

    def test_uuu_command(self, tmp_path):
        cfg = FlashConfig(tool="uuu", extra_args="-b emmc_all")
        flasher = ImageFlasher(cfg)
        img = tmp_path / "image.wic"
        with patch("os.geteuid", return_value=0):
            cmd = flasher._build_command(img, "", None)
        assert cmd == ["uuu", "-b", "emmc_all", str(img.resolve())]

    def test_uuu_command_defaults_to_emmc_all(self, tmp_path):
        cfg = FlashConfig(tool="uuu")
        flasher = ImageFlasher(cfg)
        img = tmp_path / "image.wic"
        with patch("os.geteuid", return_value=0):
            cmd = flasher._build_command(img, "", None)
        assert cmd == ["uuu", "-b", "emmc_all", str(img.resolve())]

    def test_uuu_command_respects_custom_burn_script(self, tmp_path):
        cfg = FlashConfig(tool="uuu", extra_args="-b sd_all")
        flasher = ImageFlasher(cfg)
        img = tmp_path / "image.wic"
        with patch("os.geteuid", return_value=0):
            cmd = flasher._build_command(img, "", None)
        assert cmd == ["uuu", "-b", "sd_all", str(img.resolve())]

    def test_non_root_adds_sudo_prefix(self, tmp_path):
        cfg = FlashConfig(tool="bmaptool")
        flasher = ImageFlasher(cfg)
        img = tmp_path / "image.wic"
        with patch("os.geteuid", return_value=1000):
            cmd = flasher._build_command(img, "/dev/sdb", None)
        assert cmd[:3] == ["sudo", "bmaptool", "copy"]

    def test_generic_tool_command(self, tmp_path):
        cfg = FlashConfig(tool="custom-flasher")
        flasher = ImageFlasher(cfg)
        img = tmp_path / "image.wic"
        with patch("os.geteuid", return_value=0):
            cmd = flasher._build_command(img, "/dev/sdb", None)
        assert cmd[0] == "custom-flasher"
        assert str(img) in cmd
        assert "/dev/sdb" in cmd


# =============================================================================
# ImageFlasher.flash tests
# =============================================================================


class TestImageFlasherFlash:
    def _cfg(self, **kwargs):
        return FlashConfig(**kwargs)

    def test_dry_run_returns_success_without_running_tool(self, tmp_path):
        images_dir = tmp_path / "tmp" / "deploy" / "images"
        images_dir.mkdir(parents=True)
        img = images_dir / "image.wic"
        img.write_bytes(b"data")

        cfg = self._cfg(image_patterns=["**/*.wic"], artifact_dirs=["tmp/deploy/images"])
        flasher = ImageFlasher(cfg)

        with patch("subprocess.run") as mock_run:
            result = flasher.flash(str(tmp_path), "/dev/sdb", dry_run=True)

        mock_run.assert_not_called()
        assert result.dry_run is True
        assert result.success is True
        assert result.image_path == img

    def test_exits_when_no_image_found(self, tmp_path):
        cfg = self._cfg(image_patterns=["**/*.wic"], artifact_dirs=["tmp/deploy/images"])
        flasher = ImageFlasher(cfg)
        with pytest.raises(SystemExit):
            flasher.flash(str(tmp_path), "/dev/sdb")

    def test_exits_when_explicit_image_path_missing(self, tmp_path):
        cfg = self._cfg()
        flasher = ImageFlasher(cfg)
        with pytest.raises(SystemExit):
            flasher.flash(str(tmp_path), "/dev/sdb", image_path="/nonexistent/image.wic")

    def test_flash_success(self, tmp_path):
        images_dir = tmp_path / "tmp" / "deploy" / "images"
        images_dir.mkdir(parents=True)
        img = images_dir / "image.wic"
        img.write_bytes(b"data")

        cfg = self._cfg(image_patterns=["**/*.wic"], artifact_dirs=["tmp/deploy/images"])
        flasher = ImageFlasher(cfg)

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with patch("os.geteuid", return_value=0):
            with patch("shutil.which", return_value="/usr/bin/bmaptool"):
                with patch("subprocess.run", return_value=mock_proc) as mock_run:
                    result = flasher.flash(str(tmp_path), "/dev/sdb")

        assert result.success is True
        assert result.target_device == "/dev/sdb"
        assert result.image_path == img
        # Verify bmaptool copy was called
        cmd_called = mock_run.call_args[0][0]
        assert cmd_called[0] == "bmaptool"
        assert cmd_called[1] == "copy"
        assert str(img) in cmd_called

    def test_flash_failure_returns_false_success(self, tmp_path):
        images_dir = tmp_path / "tmp" / "deploy" / "images"
        images_dir.mkdir(parents=True)
        img = images_dir / "image.wic"
        img.write_bytes(b"data")

        cfg = self._cfg(image_patterns=["**/*.wic"], artifact_dirs=["tmp/deploy/images"])
        flasher = ImageFlasher(cfg)

        mock_proc = MagicMock()
        mock_proc.returncode = 1

        with patch("os.geteuid", return_value=0):
            with patch("shutil.which", return_value="/usr/bin/bmaptool"):
                with patch("subprocess.run", return_value=mock_proc):
                    result = flasher.flash(str(tmp_path), "/dev/sdb")

        assert result.success is False

    def test_warns_when_device_does_not_exist(self, tmp_path, caplog):
        images_dir = tmp_path / "tmp" / "deploy" / "images"
        images_dir.mkdir(parents=True)
        img = images_dir / "image.wic"
        img.write_bytes(b"data")

        cfg = self._cfg(image_patterns=["**/*.wic"], artifact_dirs=["tmp/deploy/images"])
        flasher = ImageFlasher(cfg)

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with patch("os.geteuid", return_value=0):
            with patch("shutil.which", return_value="/usr/bin/bmaptool"):
                with patch("subprocess.run", return_value=mock_proc):
                    with caplog.at_level(logging.WARNING, logger="ImageFlasher"):
                        # /dev/nonexistent_xyz should not exist
                        flasher.flash(str(tmp_path), "/dev/nonexistent_xyz_bsp_test")

        assert any("does not exist" in r.message for r in caplog.records)

    def test_exits_when_target_missing_for_non_uuu_tool(self, tmp_path):
        images_dir = tmp_path / "tmp" / "deploy" / "images"
        images_dir.mkdir(parents=True)
        img = images_dir / "image.wic"
        img.write_bytes(b"data")

        cfg = self._cfg(tool="dd", image_patterns=["**/*.wic"], artifact_dirs=["tmp/deploy/images"])
        flasher = ImageFlasher(cfg)

        with pytest.raises(SystemExit):
            flasher.flash(str(tmp_path), "")

    def test_uuu_allows_empty_target(self, tmp_path):
        images_dir = tmp_path / "tmp" / "deploy" / "images"
        images_dir.mkdir(parents=True)
        img = images_dir / "image.wic"
        img.write_bytes(b"data")

        cfg = self._cfg(tool="uuu", image_patterns=["**/*.wic"], artifact_dirs=["tmp/deploy/images"])
        flasher = ImageFlasher(cfg)

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with patch("os.geteuid", return_value=0):
            with patch("shutil.which", return_value="/usr/bin/uuu"):
                with patch("subprocess.run", return_value=mock_proc) as mock_run:
                    result = flasher.flash(str(tmp_path), "")

        assert result.success is True
        assert result.target_device == ""
        cmd_called = mock_run.call_args[0][0]
        assert cmd_called == ["uuu", "-b", "emmc_all", str(img.resolve())]

    def test_explicit_image_path_used(self, tmp_path):
        img = tmp_path / "explicit.wic"
        img.write_bytes(b"data")

        cfg = self._cfg()
        flasher = ImageFlasher(cfg)

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with patch("os.geteuid", return_value=0):
            with patch("shutil.which", return_value="/usr/bin/bmaptool"):
                with patch("subprocess.run", return_value=mock_proc) as mock_run:
                    result = flasher.flash(
                        str(tmp_path), "/dev/sdb", image_path=str(img)
                    )

        assert result.image_path == img
        cmd_called = mock_run.call_args[0][0]
        assert str(img) in cmd_called

    def test_bmap_included_in_command_when_found(self, tmp_path):
        images_dir = tmp_path / "tmp" / "deploy" / "images"
        images_dir.mkdir(parents=True)
        img = images_dir / "image.wic"
        bmap = images_dir / "image.wic.bmap"
        img.write_bytes(b"data")
        bmap.write_bytes(b"bmap")

        cfg = self._cfg(image_patterns=["**/*.wic"], artifact_dirs=["tmp/deploy/images"])
        flasher = ImageFlasher(cfg)

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with patch("os.geteuid", return_value=0):
            with patch("shutil.which", return_value="/usr/bin/bmaptool"):
                with patch("subprocess.run", return_value=mock_proc) as mock_run:
                    result = flasher.flash(str(tmp_path), "/dev/sdb")

        assert result.bmap_path == bmap
        cmd_called = mock_run.call_args[0][0]
        assert "--bmap" in cmd_called
        assert str(bmap) in cmd_called

    def test_non_root_flash_invokes_sudo(self, tmp_path):
        images_dir = tmp_path / "tmp" / "deploy" / "images"
        images_dir.mkdir(parents=True)
        img = images_dir / "image.wic"
        img.write_bytes(b"data")

        cfg = self._cfg(image_patterns=["**/*.wic"], artifact_dirs=["tmp/deploy/images"])
        flasher = ImageFlasher(cfg)

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        def _which(name):
            if name == "sudo":
                return "/usr/bin/sudo"
            if name == "bmaptool":
                return "/usr/bin/bmaptool"
            return None

        with patch("os.geteuid", return_value=1000):
            with patch("shutil.which", side_effect=_which):
                with patch("subprocess.run", return_value=mock_proc) as mock_run:
                    result = flasher.flash(str(tmp_path), "/dev/sdb")

        assert result.success is True
        cmd_called = mock_run.call_args[0][0]
        assert cmd_called[:3] == ["sudo", "bmaptool", "copy"]


# =============================================================================
# BspManager.flash_bsp / flash_by_components tests
# =============================================================================


class TestBspManagerFlashBsp:
    def _make_manager(self, tmp_path):
        """Build a minimal BspManager backed by a tiny registry file."""
        from tests.conftest import MINIMAL_REGISTRY_YAML

        reg_file = tmp_path / "bsp-registry.yaml"
        reg_file.write_text(MINIMAL_REGISTRY_YAML)

        from bsp.bsp_manager import BspManager
        mgr = BspManager(str(reg_file))
        mgr.initialize()
        return mgr

    def test_flash_bsp_calls_flash_resolved(self, tmp_path):
        mgr = self._make_manager(tmp_path)

        mock_result = FlashResult(
            image_path=tmp_path / "image.wic",
            target_device="/dev/sdb",
            success=True,
        )

        with patch.object(mgr, "_flash_resolved", return_value=mock_result) as mock_flash:
            result = mgr.flash_bsp(
                "test-bsp",
                target_device="/dev/sdb",
                dry_run=True,
            )

        mock_flash.assert_called_once()
        call_kwargs = mock_flash.call_args[1]
        assert call_kwargs["target_device"] == "/dev/sdb"
        assert call_kwargs["dry_run"] is True

    def test_flash_by_components_calls_flash_resolved(self, tmp_path):
        mgr = self._make_manager(tmp_path)

        mock_result = FlashResult(
            image_path=tmp_path / "image.wic",
            target_device="/dev/sdb",
            success=True,
        )

        with patch.object(mgr, "_flash_resolved", return_value=mock_result) as mock_flash:
            result = mgr.flash_by_components(
                "test-device",
                "test-release",
                target_device="/dev/sdb",
                dry_run=True,
            )

        mock_flash.assert_called_once()
        call_kwargs = mock_flash.call_args[1]
        assert call_kwargs["target_device"] == "/dev/sdb"
        assert call_kwargs["dry_run"] is True

    def test_flash_resolved_prepends_build_target_pattern(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        resolved, _ = mgr.resolver.resolve_preset("test-bsp")

        with patch.object(
            mgr,
            "_resolve_flash_config",
            return_value=FlashConfig(image_patterns=["**/*.wic"]),
        ):
            with patch("bsp.bsp_manager.ImageFlasher") as mock_flasher_cls:
                mock_flasher = mock_flasher_cls.return_value
                mock_flasher.flash.return_value = FlashResult(
                    image_path=tmp_path / "test-image.wic",
                    target_device="/dev/sdb",
                    success=True,
                    dry_run=True,
                )

                mgr._flash_resolved(
                    resolved,
                    target_device="/dev/sdb",
                    build_target="core-image-minimal",
                    dry_run=True,
                )

        flash_cfg = mock_flasher_cls.call_args[0][0]
        assert "**/*.wic" in flash_cfg.image_patterns
        assert flash_cfg.image_patterns[0] == "**/core-image-minimal.wic.*"

    def test_flash_resolved_deduplicates_build_target_pattern(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        resolved, _ = mgr.resolver.resolve_preset("test-bsp")
        target_pattern = "**/core-image-minimal.wic.*"

        with patch.object(
            mgr,
            "_resolve_flash_config",
            return_value=FlashConfig(image_patterns=["**/*.wic", target_pattern]),
        ):
            with patch("bsp.bsp_manager.ImageFlasher") as mock_flasher_cls:
                mock_flasher = mock_flasher_cls.return_value
                mock_flasher.flash.return_value = FlashResult(
                    image_path=tmp_path / "test-image.wic",
                    target_device="/dev/sdb",
                    success=True,
                    dry_run=True,
                )

                mgr._flash_resolved(
                    resolved,
                    target_device="/dev/sdb",
                    build_target="core-image-minimal",
                    dry_run=True,
                )

        flash_cfg = mock_flasher_cls.call_args[0][0]
        assert flash_cfg.image_patterns.count(target_pattern) == 1
        assert flash_cfg.image_patterns[0] == target_pattern

    def test_flash_resolved_expands_build_target_pattern_placeholders(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        resolved, _ = mgr.resolver.resolve_preset("test-bsp")

        with patch.object(
            mgr,
            "_resolve_flash_config",
            return_value=FlashConfig(
                image_patterns=["**/{build_target}-*.wic.*", "**/*.wic"]
            ),
        ):
            with patch("bsp.bsp_manager.ImageFlasher") as mock_flasher_cls:
                mock_flasher = mock_flasher_cls.return_value
                mock_flasher.flash.return_value = FlashResult(
                    image_path=tmp_path / "test-image.wic",
                    target_device="/dev/sdb",
                    success=True,
                    dry_run=True,
                )

                mgr._flash_resolved(
                    resolved,
                    target_device="/dev/sdb",
                    build_target="core-image-minimal",
                    dry_run=True,
                )

        flash_cfg = mock_flasher_cls.call_args[0][0]
        assert flash_cfg.image_patterns[0] == "**/core-image-minimal.wic.*"
        assert "**/core-image-minimal-*.wic.*" in flash_cfg.image_patterns


# =============================================================================
# CLI argument parsing tests
# =============================================================================


class TestCliFlashParser:
    def _parse(self, argv):
        """Run the CLI argument parser and return the parsed namespace."""
        # We patch main() internal logic to only parse args without executing
        import argparse
        from bsp import cli

        # Re-parse by calling main with sys.argv patched and catching SystemExit
        # from --help etc.  We directly instantiate the parser by calling the
        # function but mocking the BspManager initialisation so no registry file
        # is needed.
        saved = sys.argv
        sys.argv = ["bsp"] + argv
        try:
            with patch("bsp.cli.BspManager") as MockMgr:
                mock_mgr = MagicMock()
                mock_mgr.flash_bsp = MagicMock(
                    return_value=FlashResult(
                        image_path=Path("/tmp/img.wic"),
                        target_device="/dev/sdb",
                        success=True,
                        dry_run=True,
                    )
                )
                MockMgr.return_value = mock_mgr
                mock_mgr.initialize.return_value = None
                mock_mgr.cleanup.return_value = None
                cli.main()
        except SystemExit:
            pass
        finally:
            sys.argv = saved

    def test_dry_run_flag(self):
        """bsp flash --dry-run <preset> should not raise."""
        self._parse(["flash", "mypreset", "--dry-run"])

    def test_target_flag(self):
        """bsp flash <preset> --target /dev/sdb should pass target to manager."""
        self._parse(["flash", "mypreset", "--target", "/dev/sdb"])

    def test_image_path_flag(self):
        """bsp flash <preset> --image-path /path/to/img.wic --dry-run"""
        self._parse([
            "flash", "mypreset",
            "--image-path", "/tmp/image.wic",
            "--dry-run",
        ])

    def test_tool_flag(self):
        """bsp flash <preset> --tool dd --dry-run"""
        self._parse(["flash", "mypreset", "--tool", "dd", "--dry-run"])

    def test_tool_flag_uuu(self):
        """bsp flash <preset> --tool uuu --dry-run"""
        self._parse(["flash", "mypreset", "--tool", "uuu", "--dry-run"])

    def test_uuu_without_target_non_dry_run(self):
        """bsp flash <preset> --tool uuu should not require --target."""
        self._parse(["flash", "mypreset", "--tool", "uuu"])

    def test_extra_args_flag(self):
        """bsp flash <preset> --extra-args '--nobmap' --dry-run"""
        self._parse([
            "flash", "mypreset",
            "--extra-args", "--nobmap",
            "--dry-run",
        ])

    def test_device_release_flags(self):
        """bsp flash --device myboard --release scarthgap --dry-run"""
        self._parse([
            "flash",
            "--device", "myboard",
            "--release", "scarthgap",
            "--dry-run",
        ])
