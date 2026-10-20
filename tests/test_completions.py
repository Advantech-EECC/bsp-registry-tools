"""
Tests for bsp/completions.py and the ``bsp completions`` CLI sub-command.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

import bsp
from bsp.completions import (
    ContainerCompleter,
    DevicesCompleter,
    FeaturesCompleter,
    OverrideCompleter,
    PresetsCompleter,
    ReleasesCompleter,
    RemotesCompleter,
    VendorReleaseCompleter,
    _build_manager_for_completion,
)
from tests.conftest import (
    MINIMAL_REGISTRY_YAML,
    REGISTRY_WITH_FEATURES_YAML,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry_file(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "bsp-registry.yaml"
    path.write_text(content)
    return path


def _parsed_args(**kwargs) -> SimpleNamespace:
    """Build a minimal argparse-like namespace for completion calls."""
    defaults = dict(registry=None, local=False, remote=None, branch="main")
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# _build_manager_for_completion
# ---------------------------------------------------------------------------


class TestBuildManagerForCompletion:
    def test_returns_manager_for_local_registry(self, tmp_path):
        reg = _make_registry_file(tmp_path, MINIMAL_REGISTRY_YAML)
        args = _parsed_args(registry=str(reg))
        mgr = _build_manager_for_completion(args)
        assert mgr is not None
        assert mgr.model is not None

    def test_returns_none_on_missing_registry(self, tmp_path):
        args = _parsed_args(registry=str(tmp_path / "nonexistent.yaml"))
        mgr = _build_manager_for_completion(args)
        assert mgr is None

    def test_passes_update_false_to_fetch_registry(self, tmp_path):
        reg = _make_registry_file(tmp_path, MINIMAL_REGISTRY_YAML)
        fetcher_mock = MagicMock()
        fetcher_mock.fetch_multiple.return_value = [("r", reg)]
        with patch("bsp.completions.RegistryFetcher", return_value=fetcher_mock):
            # Force the "no local registry found, no --registry" path
            args = _parsed_args(registry=None, remote=["https://example.com/r.git"])
            _build_manager_for_completion(args)
        fetcher_mock.fetch_multiple.assert_called_once()
        # update=False must have been passed (positionally or as a keyword arg)
        call_args = fetcher_mock.fetch_multiple.call_args
        passed_as_kwarg = call_args.kwargs.get("update") is False
        passed_positionally = len(call_args.args) >= 2 and call_args.args[1] is False
        assert passed_as_kwarg or passed_positionally

    def test_swallows_exception_returns_none(self, tmp_path):
        args = _parsed_args(registry=str(tmp_path / "not-there.yaml"))
        result = _build_manager_for_completion(args)
        assert result is None

    def test_uses_fetch_multiple_for_configured_single_remote(self, tmp_path):
        reg = _make_registry_file(tmp_path, MINIMAL_REGISTRY_YAML)
        fetcher_mock = MagicMock()
        fetcher_mock.fetch_multiple.return_value = [("advantech-europe", reg)]
        with patch("bsp.completions.RegistryFetcher", return_value=fetcher_mock):
            with patch("bsp.completions.RemotesManager") as MockRM:
                from bsp.remotes_manager import RemoteEntry
                MockRM.return_value.ensure_default_remote.return_value = [
                    RemoteEntry(
                        name="advantech-europe",
                        url="https://github.com/Advantech-EECC/bsp-registry.git",
                        branch="main",
                    )
                ]
                args = _parsed_args(registry=None, remote=None, branch="main")
                _build_manager_for_completion(args)
        fetcher_mock.fetch_registry.assert_not_called()
        fetcher_mock.fetch_multiple.assert_called_once()


# ---------------------------------------------------------------------------
# PresetsCompleter
# ---------------------------------------------------------------------------


class TestPresetsCompleter:
    def test_returns_preset_names(self, tmp_path):
        reg = _make_registry_file(tmp_path, MINIMAL_REGISTRY_YAML)
        args = _parsed_args(registry=str(reg))
        completions = PresetsCompleter()("", args)
        assert "test-bsp" in completions

    def test_returns_empty_on_bad_registry(self, tmp_path):
        args = _parsed_args(registry=str(tmp_path / "gone.yaml"))
        completions = PresetsCompleter()("", args)
        assert completions == []

    def test_multi_registry_includes_qualified_names(self, tmp_path):
        reg1 = tmp_path / "reg1.yaml"
        reg2 = tmp_path / "reg2.yaml"
        reg1.write_text(MINIMAL_REGISTRY_YAML)
        reg2.write_text(MINIMAL_REGISTRY_YAML.replace("test-bsp", "other-bsp"))

        from bsp.bsp_manager import BspManager
        mgr = BspManager(config_paths=[("regA", str(reg1)), ("regB", str(reg2))])
        mgr.initialize()

        mock_args = _parsed_args(registry=str(reg1))
        with patch("bsp.completions._build_manager_for_completion", return_value=mgr):
            completions = PresetsCompleter()("", mock_args)

        # Both bare and qualified names should appear
        assert "test-bsp" in completions
        assert "regA:test-bsp" in completions
        assert "other-bsp" in completions
        assert "regB:other-bsp" in completions

    def test_does_not_raise_on_exception(self, tmp_path):
        args = _parsed_args(registry=None)
        with patch("bsp.completions._build_manager_for_completion", side_effect=RuntimeError("boom")):
            result = PresetsCompleter()("", args)
        assert result == []


# ---------------------------------------------------------------------------
# DevicesCompleter
# ---------------------------------------------------------------------------


class TestDevicesCompleter:
    def test_returns_device_slugs(self, tmp_path):
        reg = _make_registry_file(tmp_path, MINIMAL_REGISTRY_YAML)
        args = _parsed_args(registry=str(reg))
        completions = DevicesCompleter()("", args)
        assert "test-device" in completions

    def test_returns_empty_on_bad_registry(self, tmp_path):
        args = _parsed_args(registry=str(tmp_path / "gone.yaml"))
        assert DevicesCompleter()("", args) == []

    def test_does_not_raise_on_exception(self, tmp_path):
        args = _parsed_args(registry=None)
        with patch("bsp.completions._build_manager_for_completion", side_effect=RuntimeError("boom")):
            assert DevicesCompleter()("", args) == []


# ---------------------------------------------------------------------------
# ContainerCompleter
# ---------------------------------------------------------------------------


class TestContainerCompleter:
    def test_returns_container_names(self, tmp_path):
        reg = _make_registry_file(tmp_path, MINIMAL_REGISTRY_YAML)
        args = _parsed_args(registry=str(reg))
        completions = ContainerCompleter()("", args)
        assert "ubuntu-22.04" in completions

    def test_multi_registry_includes_qualified_names(self, tmp_path):
        reg1 = tmp_path / "reg1.yaml"
        reg2 = tmp_path / "reg2.yaml"
        reg1.write_text(MINIMAL_REGISTRY_YAML)
        reg2.write_text(MINIMAL_REGISTRY_YAML.replace("ubuntu-22.04", "other-container"))

        from bsp.bsp_manager import BspManager
        mgr = BspManager(config_paths=[("regA", str(reg1)), ("regB", str(reg2))])
        mgr.initialize()

        mock_args = _parsed_args(registry=str(reg1))
        with patch("bsp.completions._build_manager_for_completion", return_value=mgr):
            completions = ContainerCompleter()("", mock_args)

        assert "ubuntu-22.04" in completions
        assert "regA:ubuntu-22.04" in completions
        assert "other-container" in completions
        assert "regB:other-container" in completions

    def test_does_not_raise_on_exception(self):
        args = _parsed_args(registry=None)
        with patch("bsp.completions._build_manager_for_completion", side_effect=RuntimeError("boom")):
            assert ContainerCompleter()("", args) == []


# ---------------------------------------------------------------------------
# ReleasesCompleter
# ---------------------------------------------------------------------------


class TestReleasesCompleter:
    def test_returns_release_slugs(self, tmp_path):
        reg = _make_registry_file(tmp_path, MINIMAL_REGISTRY_YAML)
        args = _parsed_args(registry=str(reg))
        completions = ReleasesCompleter()("", args)
        assert "test-release" in completions

    def test_filters_by_device_when_provided(self, tmp_path):
        # REGISTRY_WITH_FEATURES_YAML has two devices: imx8-board (vendor=advantech)
        # and qemu-arm64 (vendor=qemu).  The single release has no vendor_overrides
        # so it should appear regardless.
        reg = _make_registry_file(tmp_path, REGISTRY_WITH_FEATURES_YAML)
        args = _parsed_args(registry=str(reg), device="imx8-board")
        completions = ReleasesCompleter()("", args)
        assert "scarthgap" in completions

    def test_returns_empty_on_bad_registry(self, tmp_path):
        args = _parsed_args(registry=str(tmp_path / "gone.yaml"))
        assert ReleasesCompleter()("", args) == []

    def test_does_not_raise_on_exception(self, tmp_path):
        args = _parsed_args(registry=None)
        with patch("bsp.completions._build_manager_for_completion", side_effect=RuntimeError("boom")):
            assert ReleasesCompleter()("", args) == []


# ---------------------------------------------------------------------------
# FeaturesCompleter
# ---------------------------------------------------------------------------


class TestFeaturesCompleter:
    def test_returns_feature_slugs(self, tmp_path):
        reg = _make_registry_file(tmp_path, REGISTRY_WITH_FEATURES_YAML)
        args = _parsed_args(registry=str(reg))
        completions = FeaturesCompleter()("", args)
        assert "ota" in completions
        assert "secure-boot" in completions

    def test_returns_empty_for_registry_without_features(self, tmp_path):
        reg = _make_registry_file(tmp_path, MINIMAL_REGISTRY_YAML)
        args = _parsed_args(registry=str(reg))
        completions = FeaturesCompleter()("", args)
        assert completions == []

    def test_returns_empty_on_bad_registry(self, tmp_path):
        args = _parsed_args(registry=str(tmp_path / "gone.yaml"))
        assert FeaturesCompleter()("", args) == []

    def test_does_not_raise_on_exception(self, tmp_path):
        args = _parsed_args(registry=None)
        with patch("bsp.completions._build_manager_for_completion", side_effect=RuntimeError("boom")):
            assert FeaturesCompleter()("", args) == []


# ---------------------------------------------------------------------------
# VendorReleaseCompleter
# ---------------------------------------------------------------------------


class TestVendorReleaseCompleter:
    def test_returns_vendor_release_slugs(self, registry_with_vendor_overrides_file):
        args = _parsed_args(
            registry=str(registry_with_vendor_overrides_file),
            device="adv-imx8",
            release="scarthgap",
        )
        completions = VendorReleaseCompleter()("", args)
        assert "imx-6.6.53" in completions
        assert "imx-6.12.0" in completions

    def test_filters_by_selected_device_vendor(self, registry_with_vendor_overrides_file):
        args = _parsed_args(
            registry=str(registry_with_vendor_overrides_file),
            device="qemu-arm64",
            release="scarthgap",
        )
        completions = VendorReleaseCompleter()("", args)
        assert completions == []

    def test_uses_bsp_name_to_filter_by_preset_soc_vendor(
        self, registry_with_soc_vendor_overrides_file
    ):
        args = _parsed_args(
            registry=str(registry_with_soc_vendor_overrides_file),
            bsp_name="adv-imx8-scarthgap-imx6.6.53",
        )
        completions = VendorReleaseCompleter()("", args)
        assert "imx-6.6.53" in completions
        assert "imx-6.12.0" in completions
        assert "mt8186-2.0" not in completions

    def test_does_not_raise_on_exception(self):
        args = _parsed_args(registry=None)
        with patch("bsp.completions._build_manager_for_completion", side_effect=RuntimeError("boom")):
            assert VendorReleaseCompleter()("", args) == []


# ---------------------------------------------------------------------------
# OverrideCompleter
# ---------------------------------------------------------------------------


class TestOverrideCompleter:
    def test_returns_override_slugs(self, registry_with_vendor_override_slug_file):
        args = _parsed_args(
            registry=str(registry_with_vendor_override_slug_file),
            release="scarthgap",
        )
        completions = OverrideCompleter()("", args)
        assert "imx-6.6.23-2.0.0" in completions
        assert "imx-6.6.36-2.1.0" in completions
        assert "imx-xwayland-6.6.52" in completions

    def test_excludes_override_slugs_for_mismatched_device_vendor(self, registry_with_vendor_override_slug_file):
        args = _parsed_args(
            registry=str(registry_with_vendor_override_slug_file),
            device="adv-imx8",
            release="scarthgap",
        )
        completions = OverrideCompleter()("", args)
        assert completions == []

    def test_uses_bsp_name_to_filter_by_preset_vendor(
        self, registry_with_vendor_override_slug_file
    ):
        args = _parsed_args(
            registry=str(registry_with_vendor_override_slug_file),
            bsp_name="adv-imx8-scarthgap",
        )
        completions = OverrideCompleter()("", args)
        assert completions == []

    def test_does_not_raise_on_exception(self):
        args = _parsed_args(registry=None)
        with patch("bsp.completions._build_manager_for_completion", side_effect=RuntimeError("boom")):
            assert OverrideCompleter()("", args) == []


# ---------------------------------------------------------------------------
# RemotesCompleter
# ---------------------------------------------------------------------------


class TestRemotesCompleter:
    def test_returns_remote_names(self, tmp_path):
        cfg = tmp_path / "remotes.yaml"
        cfg.write_text(yaml.safe_dump({
            "remotes": [
                {"name": "origin", "url": "https://example.com/r.git", "branch": "main"},
                {"name": "upstream", "url": "https://example.com/u.git", "branch": "dev"},
            ]
        }))
        with patch.dict(os.environ, {"BSP_REMOTES_CONFIG": str(cfg)}):
            completions = RemotesCompleter()("", SimpleNamespace())
        assert "origin" in completions
        assert "upstream" in completions

    def test_bootstraps_default_when_no_remotes_file(self, tmp_path):
        with patch.dict(os.environ, {"BSP_REMOTES_CONFIG": str(tmp_path / "missing.yaml")}):
            completions = RemotesCompleter()("", SimpleNamespace())
        assert "advantech-europe" in completions

    def test_does_not_raise_on_exception(self):
        with patch("bsp.completions.RemotesManager", side_effect=RuntimeError("boom")):
            result = RemotesCompleter()("", SimpleNamespace())
        assert result == []


# ---------------------------------------------------------------------------
# ``bsp completions`` CLI sub-command
# ---------------------------------------------------------------------------


class TestCompletionsCLI:
    """Tests for the ``bsp completions`` sub-command."""

    @pytest.mark.parametrize("shell,expected_fragment", [
        ("bash", "register-python-argcomplete bsp"),
        ("zsh", "register-python-argcomplete bsp"),
        ("fish", "register-python-argcomplete --shell fish bsp"),
        ("tcsh", "register-python-argcomplete --shell tcsh bsp"),
    ])
    def test_completions_prints_snippet(self, shell, expected_fragment, capsys):
        try:
            import argcomplete  # noqa: F401
        except ImportError:
            pytest.skip("argcomplete not installed")

        with patch("sys.argv", ["bsp", "completions", shell]):
            exit_code = bsp.main()

        assert exit_code == 0
        out = capsys.readouterr().out
        assert expected_fragment in out

    def test_completions_no_shell_arg_succeeds(self, capsys):
        try:
            import argcomplete  # noqa: F401
        except ImportError:
            pytest.skip("argcomplete not installed")

        with patch("sys.argv", ["bsp", "completions"]):
            with patch.dict(os.environ, {"SHELL": "/bin/bash"}):
                exit_code = bsp.main()

        assert exit_code == 0
        out = capsys.readouterr().out
        assert len(out.strip()) > 0

    def test_completions_without_argcomplete_returns_error(self, capsys):
        with patch("sys.argv", ["bsp", "completions", "bash"]):
            with patch.dict(sys.modules, {"argcomplete": None}):
                exit_code = bsp.main()

        assert exit_code != 0
        err = capsys.readouterr().err
        assert "argcomplete" in err.lower() or "completions" in err.lower()

    def test_completions_autodetects_zsh(self, capsys):
        try:
            import argcomplete  # noqa: F401
        except ImportError:
            pytest.skip("argcomplete not installed")

        with patch("sys.argv", ["bsp", "completions"]):
            with patch.dict(os.environ, {"SHELL": "/usr/bin/zsh"}):
                exit_code = bsp.main()

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "bashcompinit" in out

    def test_completions_autodetects_fish(self, capsys):
        try:
            import argcomplete  # noqa: F401
        except ImportError:
            pytest.skip("argcomplete not installed")

        with patch("sys.argv", ["bsp", "completions"]):
            with patch.dict(os.environ, {"SHELL": "/usr/bin/fish"}):
                exit_code = bsp.main()

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "fish" in out
