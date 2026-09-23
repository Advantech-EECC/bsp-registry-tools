"""
Tests for OverlayManager and the ``bsp overlay`` CLI sub-command.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import bsp
from bsp import BspManager
from bsp.overlay_manager import (
    OverlayEntry,
    OverlayManager,
    RepoOverride,
    parse_path_spec,
    parse_repo_spec,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def overlays_config(tmp_path) -> Path:
    """Return a temp path for the overlays config file and set BSP_OVERLAYS_CONFIG."""
    cfg = tmp_path / "overlays.yaml"
    with patch.dict(os.environ, {"BSP_OVERLAYS_CONFIG": str(cfg)}):
        yield cfg


@pytest.fixture
def mgr(overlays_config) -> OverlayManager:
    """An OverlayManager backed by a temp config file (via env var)."""
    return OverlayManager(config_path=overlays_config)


# ---------------------------------------------------------------------------
# Repo spec parsing
# ---------------------------------------------------------------------------

class TestParseRepoSpec:
    def test_refspec_only_branch(self):
        repo, ov = parse_repo_spec("meta-modular-bsp-nxp@feature/ota-rework")
        assert repo == "meta-modular-bsp-nxp"
        assert ov.url is None
        assert ov.branch == "feature/ota-rework"
        assert ov.tag is None and ov.commit is None

    def test_refspec_only_commit_sha(self):
        sha = "a" * 40
        repo, ov = parse_repo_spec(f"meta-imx@{sha}")
        assert repo == "meta-imx"
        assert ov.commit == sha
        assert ov.branch is None

    def test_refspec_explicit_tag(self):
        repo, ov = parse_repo_spec("meta-imx@tag:v1.2")
        assert ov.tag == "v1.2"
        assert ov.branch is None and ov.commit is None

    def test_refspec_explicit_commit(self):
        repo, ov = parse_repo_spec("meta-imx@commit:abc123")
        assert ov.commit == "abc123"

    def test_refspec_explicit_branch(self):
        repo, ov = parse_repo_spec("meta-imx@branch:main")
        assert ov.branch == "main"

    def test_url_only(self):
        repo, ov = parse_repo_spec("meta-imx=https://github.com/example/meta-imx.git")
        assert repo == "meta-imx"
        assert ov.url == "https://github.com/example/meta-imx.git"
        assert ov.branch is None

    def test_url_with_refspec(self):
        repo, ov = parse_repo_spec(
            "meta-imx=https://github.com/example/meta-imx.git@fix/display"
        )
        assert ov.url == "https://github.com/example/meta-imx.git"
        assert ov.branch == "fix/display"

    def test_ssh_url_without_refspec(self):
        repo, ov = parse_repo_spec("meta-imx=git@github.com:example/meta-imx.git")
        assert ov.url == "git@github.com:example/meta-imx.git"
        assert ov.branch is None

    def test_ssh_url_with_refspec(self):
        repo, ov = parse_repo_spec("meta-imx=git@github.com:example/meta-imx.git@main")
        assert ov.url == "git@github.com:example/meta-imx.git"
        assert ov.branch == "main"

    def test_ssh_url_with_explicit_refspec(self):
        repo, ov = parse_repo_spec(
            "meta-imx=git@github.com:example/meta-imx.git@tag:v2.0"
        )
        assert ov.url == "git@github.com:example/meta-imx.git"
        assert ov.tag == "v2.0"

    def test_bare_url_derives_repo_name(self):
        repo, ov = parse_repo_spec("https://github.com/example/meta-imx.git")
        assert repo == "meta-imx"
        assert ov.url == "https://github.com/example/meta-imx.git"
        assert ov.branch is None

    def test_bare_url_with_refspec(self):
        repo, ov = parse_repo_spec(
            "https://github.com/example/meta-imx.git@fix/display"
        )
        assert repo == "meta-imx"
        assert ov.url == "https://github.com/example/meta-imx.git"
        assert ov.branch == "fix/display"

    def test_bare_url_with_credentials_and_refspec(self):
        # Regression: URLs with embedded credentials must not be split at the
        # userinfo '@' (https://user@host/...).
        repo, ov = parse_repo_spec(
            "https://AdvEECC@dev.azure.com/AdvEECC/EECC_Internal/_git/"
            "preprod-meta-modular-bsp-nxp@feature/aom2521b0-preliminary-support"
        )
        assert repo == "preprod-meta-modular-bsp-nxp"
        assert ov.url == (
            "https://AdvEECC@dev.azure.com/AdvEECC/EECC_Internal/_git/"
            "preprod-meta-modular-bsp-nxp"
        )
        assert ov.branch == "feature/aom2521b0-preliminary-support"

    def test_bare_url_with_credentials_no_refspec(self):
        repo, ov = parse_repo_spec(
            "https://user@dev.azure.com/org/project/_git/meta-x"
        )
        assert repo == "meta-x"
        assert ov.url == "https://user@dev.azure.com/org/project/_git/meta-x"
        assert ov.branch is None

    def test_bare_ssh_url(self):
        repo, ov = parse_repo_spec("git@github.com:example/meta-imx.git")
        assert repo == "meta-imx"
        assert ov.url == "git@github.com:example/meta-imx.git"
        assert ov.branch is None

    def test_bare_ssh_url_with_refspec(self):
        repo, ov = parse_repo_spec("git@github.com:example/meta-imx.git@main")
        assert repo == "meta-imx"
        assert ov.url == "git@github.com:example/meta-imx.git"
        assert ov.branch == "main"

    def test_bare_url_with_explicit_tag_refspec(self):
        repo, ov = parse_repo_spec(
            "https://github.com/example/meta-imx.git@tag:v1.2"
        )
        assert repo == "meta-imx"
        assert ov.tag == "v1.2"
        assert ov.branch is None

    def test_invalid_spec_exits(self):
        with pytest.raises(SystemExit):
            parse_repo_spec("just-a-repo-name")

    def test_missing_repo_name_exits(self):
        with pytest.raises(SystemExit):
            parse_repo_spec("=https://example.com/repo.git")

    def test_missing_url_exits(self):
        with pytest.raises(SystemExit):
            parse_repo_spec("meta-imx=")


class TestParsePathSpec:
    def test_basic(self, tmp_path):
        repo, path = parse_path_spec(f"meta-x={tmp_path}")
        assert repo == "meta-x"
        assert path == str(tmp_path.resolve())

    def test_expands_home(self):
        repo, path = parse_path_spec("meta-x=~/src/meta-x")
        assert repo == "meta-x"
        assert path.startswith(str(Path.home()))
        assert path.endswith("src/meta-x")

    def test_invalid_exits(self):
        with pytest.raises(SystemExit):
            parse_path_spec("meta-x")
        with pytest.raises(SystemExit):
            parse_path_spec("meta-x=")


# ---------------------------------------------------------------------------
# OverlayManager unit tests
# ---------------------------------------------------------------------------

class TestOverlayManagerCrud:
    def test_load_empty_when_no_file(self, tmp_path):
        mgr = OverlayManager(config_path=tmp_path / "nonexistent.yaml")
        assert mgr.load() == []

    def test_add_and_load(self, mgr):
        entry = mgr.add(
            "modular-bsp-dev",
            description="Local work on modular BSP",
            repo_specs=["meta-modular-bsp-nxp@feature/ota-rework"],
        )
        assert entry.name == "modular-bsp-dev"
        loaded = mgr.load()
        assert len(loaded) == 1
        assert loaded[0].description == "Local work on modular BSP"
        assert loaded[0].repos["meta-modular-bsp-nxp"].branch == "feature/ota-rework"

    def test_add_duplicate_exits(self, mgr):
        mgr.add("dev")
        with pytest.raises(SystemExit):
            mgr.add("dev")

    def test_remove(self, mgr):
        mgr.add("dev")
        mgr.remove("dev")
        assert mgr.load() == []

    def test_remove_unknown_exits(self, mgr):
        with pytest.raises(SystemExit):
            mgr.remove("nope")

    def test_get(self, mgr):
        mgr.add("dev")
        assert mgr.get("dev").name == "dev"

    def test_get_unknown_exits(self, mgr):
        with pytest.raises(SystemExit):
            mgr.get("nope")

    def test_set_repo(self, mgr):
        mgr.add("dev")
        entry = mgr.set_repo(
            "dev", "meta-imx=https://github.com/example/meta-imx.git@fix/display"
        )
        ov = entry.repos["meta-imx"]
        assert ov.url == "https://github.com/example/meta-imx.git"
        assert ov.branch == "fix/display"

    def test_set_repo_replaces_previous(self, mgr):
        mgr.add("dev", repo_specs=["meta-imx@old-branch"])
        entry = mgr.set_repo("dev", "meta-imx@tag:v1.0")
        ov = entry.repos["meta-imx"]
        assert ov.tag == "v1.0"
        assert ov.branch is None

    def test_set_repo_unknown_overlay_exits(self, mgr):
        with pytest.raises(SystemExit):
            mgr.set_repo("nope", "meta-imx@main")

    def test_set_path(self, mgr, tmp_path):
        mgr.add("dev")
        entry = mgr.set_path("dev", f"meta-x={tmp_path}")
        ov = entry.repos["meta-x"]
        assert ov.path == str(tmp_path.resolve())
        assert ov.url is None

    def test_unset_repo(self, mgr):
        mgr.add("dev", repo_specs=["meta-imx@main"])
        entry = mgr.unset_repo("dev", "meta-imx")
        assert "meta-imx" not in entry.repos

    def test_unset_repo_unknown_repo_exits(self, mgr):
        mgr.add("dev")
        with pytest.raises(SystemExit):
            mgr.unset_repo("dev", "meta-imx")

    def test_persistence_roundtrip(self, mgr, overlays_config):
        mgr.add("dev", description="desc", repo_specs=["meta-imx@main"])
        data = yaml.safe_load(overlays_config.read_text())
        assert data["overlays"][0]["name"] == "dev"
        assert data["overlays"][0]["repos"]["meta-imx"]["branch"] == "main"
        # Fresh manager sees the same data
        loaded = OverlayManager(config_path=overlays_config).load()
        assert loaded[0].repos["meta-imx"].branch == "main"


# ---------------------------------------------------------------------------
# KAS overlay YAML generation
# ---------------------------------------------------------------------------

class TestOverlayKasGeneration:
    def test_url_and_branch_override(self):
        entry = OverlayEntry(name="dev", repos={
            "meta-imx": RepoOverride(url="https://example.com/meta-imx.git", branch="fix/x"),
        })
        cfg = OverlayManager.build_overlay_kas_config(entry)
        assert cfg["header"]["version"]
        repo = cfg["repos"]["meta-imx"]
        assert repo["url"] == "https://example.com/meta-imx.git"
        assert repo["branch"] == "fix/x"
        # Conflicting refspec keys are explicitly cleared; the KAS schema
        # forbids null for commit, so an empty string is used instead.
        assert repo["tag"] is None
        assert repo["commit"] == ""

    def test_url_only_override_keeps_registry_refspec(self):
        entry = OverlayEntry(name="dev", repos={
            "meta-imx": RepoOverride(url="https://example.com/meta-imx.git"),
        })
        repo = OverlayManager.build_overlay_kas_config(entry)["repos"]["meta-imx"]
        assert repo == {"url": "https://example.com/meta-imx.git"}

    def test_path_override_clears_url_and_refspecs(self):
        entry = OverlayEntry(name="dev", repos={
            "meta-x": RepoOverride(path="/home/user/src/meta-x"),
        })
        repo = OverlayManager.build_overlay_kas_config(entry)["repos"]["meta-x"]
        assert repo["path"] == "/home/user/src/meta-x"
        assert repo["url"] is None
        assert repo["branch"] is None
        assert repo["tag"] is None
        assert repo["commit"] == ""

    def test_kas_schema_accepts_generated_fragment(self):
        """The generated fragment must validate against the KAS schema."""
        jsonschema = pytest.importorskip("jsonschema")
        try:
            import json
            import pkgutil
            schema = json.loads(pkgutil.get_data("kas", "schema-kas.json"))
        except (ImportError, TypeError):
            pytest.skip("kas package not installed")
        entry = OverlayEntry(name="dev", repos={
            "meta-imx": RepoOverride(
                url="https://user@example.com/org/_git/meta-imx",
                branch="feature/x",
            ),
            "meta-local": RepoOverride(path="/home/user/src/meta-local"),
        })
        cfg = OverlayManager.build_overlay_kas_config(entry)
        jsonschema.validate(cfg, schema)

    def test_generate_yaml_file(self, mgr, tmp_path):
        entry = OverlayEntry(name="dev", repos={
            "meta-imx": RepoOverride(branch="main"),
        })
        out = tmp_path / "overlay.yml"
        mgr.generate_overlay_kas_yaml(entry, str(out))
        data = yaml.safe_load(out.read_text())
        assert data["repos"]["meta-imx"]["branch"] == "main"


# ---------------------------------------------------------------------------
# BspManager integration
# ---------------------------------------------------------------------------

class TestBspManagerOverlayIntegration:
    def _resolved(self, manager):
        return manager.resolver.resolve("test-device", "test-release")

    def test_overlay_appends_kas_fragment(self, registry_file, tmp_path):
        overlay = OverlayEntry(name="dev", repos={
            "meta-imx": RepoOverride(branch="feature/x"),
        })
        manager = BspManager(config_path=str(registry_file), overlay=overlay)
        manager.initialize()
        build_path = tmp_path / "build"
        kas_mgr = manager._get_kas_manager_for_resolved(
            self._resolved(manager), use_container=False,
            build_path_override=str(build_path),
        )
        overlay_file = kas_mgr.kas_files[-1]
        assert "bsp_overlay_dev_" in overlay_file
        # Overlay fragments are generated under <build_path>/overlays/
        assert Path(overlay_file).parent == build_path / "overlays"
        data = yaml.safe_load(Path(overlay_file).read_text())
        assert data["repos"]["meta-imx"]["branch"] == "feature/x"
        # Fragment is kept after cleanup for traceability
        manager._cleanup_temp_kas_file()
        assert Path(overlay_file).exists()

    def test_no_overlay_keeps_kas_files_unchanged(self, registry_file):
        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        kas_mgr = manager._get_kas_manager_for_resolved(
            self._resolved(manager), use_container=False
        )
        assert not any("bsp_overlay_" in f for f in kas_mgr.kas_files)
        manager._cleanup_temp_kas_file()

    def test_empty_overlay_is_noop(self, registry_file):
        overlay = OverlayEntry(name="dev")
        manager = BspManager(config_path=str(registry_file), overlay=overlay)
        manager.initialize()
        kas_mgr = manager._get_kas_manager_for_resolved(
            self._resolved(manager), use_container=False
        )
        assert not any("bsp_overlay_" in f for f in kas_mgr.kas_files)
        manager._cleanup_temp_kas_file()

    def test_overlay_path_override_adds_container_volume(self, registry_file, tmp_path):
        overlay = OverlayEntry(name="dev", repos={
            "meta-x": RepoOverride(path=str(tmp_path)),
        })
        manager = BspManager(config_path=str(registry_file), overlay=overlay)
        manager.initialize()
        kas_mgr = manager._get_kas_manager_for_resolved(
            self._resolved(manager), use_container=True,
            build_path_override=str(tmp_path / "build"),
        )
        assert any(
            v.host == str(tmp_path) and v.container == str(tmp_path)
            for v in kas_mgr.container_volumes
        )
        manager._cleanup_temp_kas_file()

    def test_build_manifest_records_overlay(self, registry_file, tmp_path):
        import json
        from unittest.mock import patch as _patch

        overlay = OverlayEntry(
            name="dev",
            description="Local work",
            repos={
                "meta-imx": RepoOverride(
                    url="https://example.com/meta-imx.git", branch="feature/x"
                ),
            },
        )
        manager = BspManager(config_path=str(registry_file), overlay=overlay)
        manager.initialize()
        output_dir = tmp_path / "build"
        with _patch("bsp.bsp_manager.build_docker"), \
             _patch("bsp.kas_manager.KasManager.build_project"), \
             _patch("bsp.kas_manager.KasManager.dump_config", return_value=""), \
             _patch("bsp.kas_manager.KasManager.validate_kas_files", return_value=True), \
             _patch("bsp.kas_manager.KasManager.check_kas_available", return_value=True):
            manager.build_by_components(
                "test-device", "test-release", [],
                build_path_override=str(output_dir),
            )

        data = json.loads((output_dir / "build-manifest.json").read_text())
        assert data["build"]["overlay_used"] is True
        ov = data["overlay"]
        assert ov["name"] == "dev"
        assert ov["description"] == "Local work"
        assert ov["fragment"] and "overlays/" in ov["fragment"]
        assert ov["repos"]["meta-imx"]["url"] == "https://example.com/meta-imx.git"
        assert ov["repos"]["meta-imx"]["branch"] == "feature/x"
        # The referenced fragment survives the build for traceability
        overlays_dir = output_dir / "overlays"
        assert any(overlays_dir.glob("bsp_overlay_dev_*.yml"))

    def test_build_manifest_without_overlay(self, registry_file, tmp_path):
        import json
        from unittest.mock import patch as _patch

        manager = BspManager(config_path=str(registry_file))
        manager.initialize()
        output_dir = tmp_path / "build"
        with _patch("bsp.bsp_manager.build_docker"), \
             _patch("bsp.kas_manager.KasManager.build_project"), \
             _patch("bsp.kas_manager.KasManager.dump_config", return_value=""), \
             _patch("bsp.kas_manager.KasManager.validate_kas_files", return_value=True), \
             _patch("bsp.kas_manager.KasManager.check_kas_available", return_value=True):
            manager.build_by_components(
                "test-device", "test-release", [],
                build_path_override=str(output_dir),
            )

        data = json.loads((output_dir / "build-manifest.json").read_text())
        assert data["build"]["overlay_used"] is False
        assert data["overlay"] is None


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestOverlayCli:
    def test_add_list_show_remove(self, overlays_config, capsys):
        with patch("sys.argv", [
            "bsp", "overlay", "add", "modular-bsp-dev",
            "--description", "Local work on modular BSP",
            "--repo", "meta-modular-bsp-nxp@feature/ota-rework",
        ]):
            assert bsp.main() == 0

        with patch("sys.argv", ["bsp", "overlay", "list"]):
            assert bsp.main() == 0
        assert "modular-bsp-dev" in capsys.readouterr().out

        with patch("sys.argv", ["bsp", "overlay", "show", "modular-bsp-dev"]):
            assert bsp.main() == 0
        out = capsys.readouterr().out
        assert "meta-modular-bsp-nxp" in out
        assert "feature/ota-rework" in out

        with patch("sys.argv", ["bsp", "overlay", "remove", "modular-bsp-dev"]):
            assert bsp.main() == 0
        capsys.readouterr()
        with patch("sys.argv", ["bsp", "overlay", "list"]):
            assert bsp.main() == 0
        assert "modular-bsp-dev" not in capsys.readouterr().out

    def test_set_repo_set_path_unset_repo(self, overlays_config, tmp_path, capsys):
        with patch("sys.argv", ["bsp", "overlay", "add", "dev"]):
            assert bsp.main() == 0
        with patch("sys.argv", [
            "bsp", "overlay", "set-repo", "dev",
            "meta-imx=https://github.com/example/meta-imx.git@fix/display",
        ]):
            assert bsp.main() == 0
        with patch("sys.argv", [
            "bsp", "overlay", "set-path", "dev", f"meta-x={tmp_path}",
        ]):
            assert bsp.main() == 0

        mgr = OverlayManager(config_path=overlays_config)
        entry = mgr.get("dev")
        assert entry.repos["meta-imx"].url == "https://github.com/example/meta-imx.git"
        assert entry.repos["meta-imx"].branch == "fix/display"
        assert entry.repos["meta-x"].path == str(tmp_path.resolve())

        with patch("sys.argv", ["bsp", "overlay", "unset-repo", "dev", "meta-imx"]):
            assert bsp.main() == 0
        entry = mgr.get("dev")
        assert "meta-imx" not in entry.repos

    def test_plain_overlay_lists(self, overlays_config, capsys):
        with patch("sys.argv", ["bsp", "overlay", "add", "dev"]):
            assert bsp.main() == 0
        capsys.readouterr()
        with patch("sys.argv", ["bsp", "overlay"]):
            assert bsp.main() == 0
        assert "dev" in capsys.readouterr().out

    def test_build_with_overlay_flag_passes_overlay_to_manager(
        self, overlays_config, registry_file
    ):
        with patch("sys.argv", [
            "bsp", "overlay", "add", "dev", "--repo", "meta-imx@main",
        ]):
            assert bsp.main() == 0

        with patch("sys.argv", [
            "bsp", "--registry", str(registry_file), "--overlay", "dev",
            "build", "test-bsp",
        ]):
            with patch("bsp.BspManager.build_bsp"):
                with patch.object(
                    BspManager, "__init__", return_value=None
                ) as mock_init:
                    # __init__ mocked → main() will fail later; only inspect args
                    try:
                        bsp.main()
                    except Exception:
                        pass
        _, kwargs = mock_init.call_args
        overlay = kwargs.get("overlay")
        assert overlay is not None
        assert overlay.name == "dev"
        assert overlay.repos["meta-imx"].branch == "main"

    def test_build_with_unknown_overlay_fails(self, overlays_config, registry_file):
        with patch("sys.argv", [
            "bsp", "--registry", str(registry_file), "--overlay", "nope",
            "build", "test-bsp",
        ]):
            with patch("bsp.BspManager.build_bsp") as mock_build:
                assert bsp.main() != 0
        mock_build.assert_not_called()
