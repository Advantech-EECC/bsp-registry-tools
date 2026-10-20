"""
Tests for the RegistryFetcher class.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from bsp.registry_fetcher import (
    DEFAULT_BRANCH,
    DEFAULT_REMOTE_URL,
    REGISTRY_FILENAME,
    REGISTRY_FILENAMES,
    RegistryFetcher,
    RemoteRegistrySpec,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fetcher(tmp_dir: Path) -> RegistryFetcher:
    return RegistryFetcher(cache_dir=tmp_dir / "registry-cache")


# ---------------------------------------------------------------------------
# Tests for _is_cloned
# ---------------------------------------------------------------------------

class TestIsCloned:
    def test_returns_false_when_directory_missing(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        assert not fetcher._is_cloned()

    def test_returns_false_when_no_git_dir(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        fetcher.cache_dir.mkdir(parents=True)
        assert not fetcher._is_cloned()

    def test_returns_true_when_git_dir_present(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        (fetcher.cache_dir / ".git").mkdir(parents=True)
        assert fetcher._is_cloned()


# ---------------------------------------------------------------------------
# Tests for fetch_registry (clone path)
# ---------------------------------------------------------------------------

class TestFetchRegistryClone:
    def test_clones_when_not_already_cloned(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)

        def fake_clone(cmd, **kwargs):
            # Simulate the side-effect of git clone: create .git and registry file
            (fetcher.cache_dir / ".git").mkdir(parents=True, exist_ok=True)
            (fetcher.cache_dir / REGISTRY_FILENAME).write_text("registry:\n  bsp: []\n")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_clone) as mock_run:
            result = fetcher.fetch_registry(
                repo_url="https://example.com/repo.git",
                branch="main",
                update=True,
            )

        assert result == fetcher.cache_dir / REGISTRY_FILENAME
        assert mock_run.call_count == 1
        clone_cmd = mock_run.call_args[0][0]
        assert "clone" in clone_cmd
        assert "https://example.com/repo.git" in clone_cmd

    def test_clones_and_finds_yml_extension(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)

        def fake_clone(cmd, **kwargs):
            # Simulate the side-effect of git clone: create .git and registry file with .yml
            (fetcher.cache_dir / ".git").mkdir(parents=True, exist_ok=True)
            (fetcher.cache_dir / "bsp-registry.yml").write_text("registry:\n  bsp: []\n")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_clone):
            result = fetcher.fetch_registry(
                repo_url="https://example.com/repo.git",
                branch="main",
                update=True,
            )

        assert result == fetcher.cache_dir / "bsp-registry.yml"

    def test_yaml_takes_priority_over_yml(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)

        def fake_clone(cmd, **kwargs):
            # Simulate both .yaml and .yml files present
            (fetcher.cache_dir / ".git").mkdir(parents=True, exist_ok=True)
            (fetcher.cache_dir / "bsp-registry.yaml").write_text("registry:\n  bsp: []\n")
            (fetcher.cache_dir / "bsp-registry.yml").write_text("registry:\n  bsp: []\n")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_clone):
            result = fetcher.fetch_registry(
                repo_url="https://example.com/repo.git",
                branch="main",
                update=True,
            )

        assert result == fetcher.cache_dir / "bsp-registry.yaml"

    def test_clone_failure_exits(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        fetcher.cache_dir.mkdir(parents=True)

        error = subprocess.CalledProcessError(128, "git clone", stderr="fatal: repo not found")
        with patch("subprocess.run", side_effect=error):
            with pytest.raises(SystemExit):
                fetcher.fetch_registry()


# ---------------------------------------------------------------------------
# Tests for fetch_registry (pull path)
# ---------------------------------------------------------------------------

class TestFetchRegistryPull:
    def _setup_cloned(self, fetcher: RegistryFetcher, filename: str = REGISTRY_FILENAME) -> None:
        """Create a minimal fake cloned repository."""
        (fetcher.cache_dir / ".git").mkdir(parents=True)
        (fetcher.cache_dir / filename).write_text("registry:\n  bsp: []\n")

    def test_pulls_when_already_cloned_and_update_true(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        self._setup_cloned(fetcher)

        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            result = fetcher.fetch_registry(update=True)

        assert result == fetcher.cache_dir / REGISTRY_FILENAME
        # fetch + checkout + pull
        assert mock_run.call_count == 3
        cmds = [mock_run.call_args_list[i][0][0] for i in range(3)]
        assert "fetch" in cmds[0]
        assert "checkout" in cmds[1]
        assert "pull" in cmds[2]

    def test_pull_uses_requested_branch(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        self._setup_cloned(fetcher)

        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            fetcher.fetch_registry(branch="development", update=True)

        cmds = [mock_run.call_args_list[i][0][0] for i in range(3)]
        assert "development" in cmds[1]   # checkout development
        assert "development" in cmds[2]   # pull origin development

    def test_skips_pull_when_no_update(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        self._setup_cloned(fetcher)

        with patch("subprocess.run") as mock_run:
            result = fetcher.fetch_registry(update=False)

        mock_run.assert_not_called()
        assert result == fetcher.cache_dir / REGISTRY_FILENAME

    def test_pull_failure_retries_with_rebase(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        self._setup_cloned(fetcher)

        pull_error = subprocess.CalledProcessError(1, "git pull", stderr="error: local changes")
        # fetch and checkout succeed; first pull fails; rebase pull succeeds
        side_effects = [
            MagicMock(returncode=0),  # fetch
            MagicMock(returncode=0),  # checkout
            pull_error,               # pull (fails)
            MagicMock(returncode=0),  # pull --rebase (succeeds)
        ]
        with patch("subprocess.run", side_effect=side_effects) as mock_run:
            result = fetcher.fetch_registry(update=True)

        assert result == fetcher.cache_dir / REGISTRY_FILENAME
        assert mock_run.call_count == 4
        rebase_call = mock_run.call_args_list[3][0][0]
        assert "--rebase" in rebase_call

    def test_pull_failure_exits_when_rebase_also_fails(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        self._setup_cloned(fetcher)

        pull_error = subprocess.CalledProcessError(1, "git pull", stderr="error: network")
        rebase_error = subprocess.CalledProcessError(1, "git pull --rebase", stderr="error: conflicts")
        side_effects = [
            MagicMock(returncode=0),  # fetch
            MagicMock(returncode=0),  # checkout
            pull_error,               # pull (fails)
            rebase_error,             # pull --rebase (also fails)
        ]
        with patch("subprocess.run", side_effect=side_effects):
            with pytest.raises(SystemExit):
                fetcher.fetch_registry(update=True)

    def test_pull_failure_exits(self, tmp_dir):
        """When even the pre-flight fetch/checkout fails (e.g. network down), the process exits."""
        fetcher = _make_fetcher(tmp_dir)
        self._setup_cloned(fetcher)

        error = subprocess.CalledProcessError(1, "git pull", stderr="error: network")
        with patch("subprocess.run", side_effect=error):
            with pytest.raises(SystemExit):
                fetcher.fetch_registry(update=True)

    def test_finds_yml_extension_after_pull(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)
        self._setup_cloned(fetcher, filename="bsp-registry.yml")

        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            result = fetcher.fetch_registry(update=True)

        assert result == fetcher.cache_dir / "bsp-registry.yml"


# ---------------------------------------------------------------------------
# Tests for missing registry file after clone/pull
# ---------------------------------------------------------------------------

class TestFetchRegistryMissingFile:
    def test_exits_when_registry_file_missing_after_clone(self, tmp_dir):
        fetcher = _make_fetcher(tmp_dir)

        def fake_clone(cmd, **kwargs):
            # Clone succeeds but does NOT create the registry file
            (fetcher.cache_dir / ".git").mkdir(parents=True, exist_ok=True)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_clone):
            with pytest.raises(SystemExit):
                fetcher.fetch_registry()


# ---------------------------------------------------------------------------
# Tests for CLI integration with remote registry
# ---------------------------------------------------------------------------

class TestCliRemoteRegistry:
    def test_cli_uses_remote_when_no_local_registry(self, tmp_dir, registry_file):
        """When no local bsp-registry.yaml exists, CLI should invoke RegistryFetcher."""
        import bsp

        fetched_path = registry_file  # reuse existing minimal registry as the "fetched" file

        with patch("sys.argv", ["bsp", "list"]):
            with patch("pathlib.Path.is_file", return_value=False):
                with patch(
                    "bsp.registry_fetcher.RegistryFetcher.fetch_registry",
                    return_value=fetched_path,
                ):
                    exit_code = bsp.main()

        assert exit_code == 0

    def test_cli_explicit_registry_overrides_remote(self, registry_file):
        """--registry flag should use the given path, skipping remote fetch."""
        import bsp

        with patch("sys.argv", ["bsp", "--registry", str(registry_file), "list"]):
            with patch(
                "bsp.registry_fetcher.RegistryFetcher.fetch_registry"
            ) as mock_fetch:
                exit_code = bsp.main()

        mock_fetch.assert_not_called()
        assert exit_code == 0

    def test_cli_local_flag_skips_remote(self, tmp_dir):
        """--local flag should fall back to local bsp-registry.yaml, not fetch remote."""
        import bsp
        from bsp import BspManager

        # No local registry file -> would normally trigger remote fetch
        with patch("sys.argv", ["bsp", "--local", "list"]):
            with patch(
                "bsp.registry_fetcher.RegistryFetcher.fetch_registry"
            ) as mock_fetch:
                with patch.object(BspManager, "initialize", side_effect=SystemExit(1)):
                    exit_code = bsp.main()

        mock_fetch.assert_not_called()
        assert exit_code != 0  # exits because the local file doesn't exist


# ---------------------------------------------------------------------------
# Tests for RemoteRegistrySpec
# ---------------------------------------------------------------------------

class TestRemoteRegistrySpec:
    def test_parse_url_only(self):
        spec = RemoteRegistrySpec.parse("https://example.com/registry.git")
        assert spec.url == "https://example.com/registry.git"
        assert spec.branch == DEFAULT_BRANCH
        assert spec.name is None

    def test_parse_url_with_branch(self):
        spec = RemoteRegistrySpec.parse("https://example.com/registry.git@develop")
        assert spec.url == "https://example.com/registry.git"
        assert spec.branch == "develop"
        assert spec.name is None

    def test_parse_url_with_branch_and_name(self):
        spec = RemoteRegistrySpec.parse(
            "https://example.com/registry.git@develop@name=myregistry"
        )
        assert spec.url == "https://example.com/registry.git"
        assert spec.branch == "develop"
        assert spec.name == "myregistry"

    def test_parse_url_with_name_no_branch(self):
        spec = RemoteRegistrySpec.parse(
            "https://example.com/registry.git@name=myregistry"
        )
        assert spec.url == "https://example.com/registry.git"
        assert spec.name == "myregistry"

    def test_resolved_name_explicit(self):
        spec = RemoteRegistrySpec(url="https://example.com/foo.git", name="myname")
        assert spec.resolved_name() == "myname"

    def test_resolved_name_from_url(self):
        spec = RemoteRegistrySpec(url="https://example.com/my-registry.git")
        assert spec.resolved_name() == "my-registry"

    def test_resolved_name_from_url_no_git(self):
        spec = RemoteRegistrySpec(url="https://example.com/my-registry")
        assert spec.resolved_name() == "my-registry"

    def test_cache_subdir_name_includes_hash(self):
        spec = RemoteRegistrySpec(url="https://example.com/foo.git", name="foo")
        subdir = spec.cache_subdir_name()
        assert "foo" in subdir
        assert len(subdir) > len("foo")  # includes hash suffix

    def test_cache_subdir_name_differs_for_different_urls(self):
        spec1 = RemoteRegistrySpec(url="https://example.com/a.git", name="foo")
        spec2 = RemoteRegistrySpec(url="https://other.com/a.git", name="foo")
        assert spec1.cache_subdir_name() != spec2.cache_subdir_name()


# ---------------------------------------------------------------------------
# Tests for fetch_multiple
# ---------------------------------------------------------------------------

class TestFetchMultiple:
    def test_fetch_multiple_returns_name_path_pairs(self, tmp_dir):
        fetcher = RegistryFetcher(cache_dir=tmp_dir / "cache")
        spec_a = RemoteRegistrySpec(url="https://example.com/a.git", name="alpha")
        spec_b = RemoteRegistrySpec(url="https://example.com/b.git", name="beta")

        # Pre-create fake sub-repos
        for spec in [spec_a, spec_b]:
            subdir = fetcher.cache_dir / spec.cache_subdir_name()
            subdir.mkdir(parents=True, exist_ok=True)
            (subdir / ".git").mkdir()
            (subdir / REGISTRY_FILENAME).write_text("# fake")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            results = fetcher.fetch_multiple([spec_a, spec_b], update=True)

        assert len(results) == 2
        names = [name for name, _ in results]
        assert "alpha" in names
        assert "beta" in names
        for _, path in results:
            assert path.name == REGISTRY_FILENAME

    def test_fetch_multiple_uses_separate_subdirs(self, tmp_dir):
        fetcher = RegistryFetcher(cache_dir=tmp_dir / "cache")
        spec_a = RemoteRegistrySpec(url="https://example.com/a.git", name="a")
        spec_b = RemoteRegistrySpec(url="https://example.com/b.git", name="b")

        for spec in [spec_a, spec_b]:
            subdir = fetcher.cache_dir / spec.cache_subdir_name()
            subdir.mkdir(parents=True, exist_ok=True)
            (subdir / ".git").mkdir()
            (subdir / REGISTRY_FILENAME).write_text("# fake")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            results = fetcher.fetch_multiple([spec_a, spec_b], update=True)

        parent_dirs = {path.parent for _, path in results}
        assert len(parent_dirs) == 2

    def test_fetch_multiple_migrates_legacy_cache(self, tmp_dir):
        """If cache_dir/.git exists, it should be renamed before cloning sub-registries."""
        cache_dir = tmp_dir / "legacy-cache"
        cache_dir.mkdir()
        legacy_git = cache_dir / ".git"
        legacy_git.mkdir()
        (cache_dir / REGISTRY_FILENAME).write_text("# old registry")

        fetcher = RegistryFetcher(cache_dir=cache_dir)
        spec = RemoteRegistrySpec(url="https://example.com/new.git", name="new")
        subdir = cache_dir / spec.cache_subdir_name()

        def fake_clone(*a, **kw):
            subdir.mkdir(parents=True, exist_ok=True)
            (subdir / ".git").mkdir(exist_ok=True)
            (subdir / REGISTRY_FILENAME).write_text("# new")

        with patch.object(RegistryFetcher, "_clone", side_effect=fake_clone):
            results = fetcher.fetch_multiple([spec], update=False)

        assert not legacy_git.exists()
        assert len(results) == 1

    def test_fetch_multiple_deduplicates_display_names(self, tmp_dir):
        fetcher = RegistryFetcher(cache_dir=tmp_dir / "cache")
        spec_a = RemoteRegistrySpec(url="https://example.com/a.git")
        spec_b = RemoteRegistrySpec(url="https://example.com/b.git")

        for spec in [spec_a, spec_b]:
            subdir = fetcher.cache_dir / spec.cache_subdir_name()
            subdir.mkdir(parents=True, exist_ok=True)
            (subdir / ".git").mkdir()
            (subdir / REGISTRY_FILENAME).write_text("# fake")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            results = fetcher.fetch_multiple([spec_a, spec_b], update=True)

        names = [name for name, _ in results]
        assert len(set(names)) == 2
