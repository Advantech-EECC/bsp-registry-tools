"""
Tests for the ArtifactGatherer and related cloud-storage download functionality.

Covers:
- GatherResult dataclass
- ArtifactGatherer.compose_remote_prefix
- ArtifactGatherer.gather (manifest-guided and fallback listing paths)
- CloudStorageBackend.get_manifest (via a fake backend)
- CloudStorageBackend.download_prefix (via a fake backend)
- AzureStorageBackend.download_file (mocked SDK)
- AwsStorageBackend.download_file (mocked SDK)
- CLI gather command argument parsing
- BspManager.gather_bsp / gather_by_components (mocked)
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from bsp.models import DeployConfig
from bsp.gatherer import ArtifactGatherer, GatherResult
from bsp.storage.base import CloudStorageBackend
from bsp.storage import create_backend


# =============================================================================
# Fake backend for unit testing
# =============================================================================


class _FakeBackend(CloudStorageBackend):
    """
    In-memory backend for testing ArtifactGatherer without touching cloud APIs.

    Blobs are stored as ``remote_path → bytes`` in :attr:`blobs`.
    """

    def __init__(self, dry_run=False):
        super().__init__(dry_run=dry_run)
        self.blobs: dict = {}          # remote_path → bytes content
        self.downloaded: list = []     # (remote_path, local_path) tuples

    def upload_file(self, local_path, remote_path):
        if self.dry_run:
            return f"dry-run:{remote_path}"
        with open(local_path, "rb") as fh:
            self.blobs[remote_path] = fh.read()
        return f"fake://{remote_path}"

    def download_file(self, remote_path, local_path):
        local_path = Path(local_path)
        if self.dry_run:
            return
        if remote_path not in self.blobs:
            raise FileNotFoundError(f"Blob not found: {remote_path}")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(self.blobs[remote_path])
        self.downloaded.append((remote_path, local_path))

    def list_artifacts(self, remote_prefix):
        if self.dry_run:
            return []
        return [k for k in self.blobs if k.startswith(remote_prefix)]

    def get_upload_url(self, remote_path):
        return f"fake://{remote_path}"


# =============================================================================
# GatherResult tests
# =============================================================================


class TestGatherResult:
    def test_defaults(self):
        result = GatherResult()
        assert result.artifacts == []
        assert result.manifest is None
        assert result.dest_dir is None
        assert result.dry_run is False

    def test_total_count_empty(self):
        assert GatherResult().total_count == 0

    def test_total_count_with_artifacts(self, tmp_path):
        p1 = tmp_path / "a.wic.gz"
        p2 = tmp_path / "b.wic.gz"
        result = GatherResult(artifacts=[p1, p2])
        assert result.total_count == 2


# =============================================================================
# ArtifactGatherer.compose_remote_prefix tests
# =============================================================================


class TestComposeRemotePrefix:
    def _make_gatherer(self, **cfg_kwargs):
        return ArtifactGatherer(DeployConfig(**cfg_kwargs), _FakeBackend())

    def test_default_template_uses_today(self):
        import datetime
        g = self._make_gatherer()
        prefix = g.compose_remote_prefix(device="mydev", release="myrel", vendor="myvendor")
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        assert today in prefix
        assert "mydev" in prefix
        assert "myrel" in prefix
        assert "myvendor" in prefix

    def test_custom_prefix_template(self):
        g = self._make_gatherer(prefix="{device}/{release}")
        prefix = g.compose_remote_prefix(device="rpi5", release="scarthgap")
        assert prefix == "rpi5/scarthgap"

    def test_date_override(self):
        g = self._make_gatherer(prefix="{device}/{date}")
        prefix = g.compose_remote_prefix(device="rpi5", date_override="2024-01-15")
        assert prefix == "rpi5/2024-01-15"

    def test_strips_leading_trailing_slashes(self):
        g = self._make_gatherer(prefix="/{device}/")
        prefix = g.compose_remote_prefix(device="rpi5")
        assert not prefix.startswith("/")
        assert not prefix.endswith("/")

    def test_unknown_placeholders_filled(self):
        g = self._make_gatherer(prefix="{vendor}/{device}/{release}/{date}")
        prefix = g.compose_remote_prefix()
        assert "unknown" in prefix


# =============================================================================
# CloudStorageBackend.get_manifest tests
# =============================================================================


class TestGetManifest:
    def test_returns_none_when_blob_missing(self, tmp_path):
        backend = _FakeBackend()
        result = backend.get_manifest("myvendor/mydev/myrel/2024-01-01")
        assert result is None

    def test_parses_manifest_json(self, tmp_path):
        backend = _FakeBackend()
        manifest_data = {
            "schema_version": "1",
            "artifacts": [{"name": "image.wic.gz", "size_bytes": 1024, "sha256": "abc"}],
        }
        prefix = "myvendor/mydev/myrel/2024-01-01"
        backend.blobs[f"{prefix}/manifest.json"] = json.dumps(manifest_data).encode()

        result = backend.get_manifest(prefix)
        assert result is not None
        assert result["schema_version"] == "1"
        assert len(result["artifacts"]) == 1
        assert result["artifacts"][0]["name"] == "image.wic.gz"

    def test_returns_none_on_invalid_json(self, tmp_path):
        backend = _FakeBackend()
        prefix = "some/prefix"
        backend.blobs[f"{prefix}/manifest.json"] = b"not-valid-json{"

        result = backend.get_manifest(prefix)
        assert result is None

    def test_dry_run_returns_none(self):
        backend = _FakeBackend(dry_run=True)
        result = backend.get_manifest("some/prefix")
        assert result is None


# =============================================================================
# CloudStorageBackend.download_prefix tests
# =============================================================================


class TestDownloadPrefix:
    def test_downloads_all_blobs(self, tmp_path):
        backend = _FakeBackend()
        prefix = "vendor/device/rel/2024-01-01"
        backend.blobs[f"{prefix}/image.wic.gz"] = b"wic_data"
        backend.blobs[f"{prefix}/image.tar.gz"] = b"tar_data"

        downloaded = backend.download_prefix(prefix, tmp_path)
        assert len(downloaded) == 2
        names = {p.name for p in downloaded}
        assert "image.wic.gz" in names
        assert "image.tar.gz" in names

    def test_skips_manifest_json(self, tmp_path):
        backend = _FakeBackend()
        prefix = "vendor/device/rel/2024-01-01"
        backend.blobs[f"{prefix}/image.wic.gz"] = b"data"
        backend.blobs[f"{prefix}/manifest.json"] = b"{}"

        downloaded = backend.download_prefix(prefix, tmp_path)
        names = {p.name for p in downloaded}
        assert "manifest.json" not in names
        assert "image.wic.gz" in names

    def test_dry_run_returns_empty(self, tmp_path):
        backend = _FakeBackend(dry_run=True)
        result = backend.download_prefix("some/prefix", tmp_path)
        assert result == []

    def test_creates_dest_dir(self, tmp_path):
        backend = _FakeBackend()
        new_dir = tmp_path / "new" / "dir"
        backend.download_prefix("empty/prefix", new_dir)
        assert new_dir.is_dir()


# =============================================================================
# ArtifactGatherer.gather tests
# =============================================================================


class TestArtifactGathererGather:
    def _make_gatherer_with_artifacts(self, tmp_path):
        """Return a gatherer whose backend contains two blobs and a manifest."""
        backend = _FakeBackend()
        prefix = "vendor/mydev/myrel/2024-01-15"
        backend.blobs[f"{prefix}/image.wic.gz"] = b"wic_data"
        backend.blobs[f"{prefix}/image.tar.gz"] = b"tar_data"
        manifest = {
            "schema_version": "1",
            "artifacts": [
                {"name": "image.wic.gz"},
                {"name": "image.tar.gz"},
            ],
        }
        backend.blobs[f"{prefix}/manifest.json"] = json.dumps(manifest).encode()

        cfg = DeployConfig(
            provider="azure",
            container="my-container",
            prefix="{vendor}/{device}/{release}/{date}",
        )
        return ArtifactGatherer(cfg, backend), backend, prefix

    def test_gather_uses_manifest_when_available(self, tmp_path):
        gatherer, backend, prefix = self._make_gatherer_with_artifacts(tmp_path)
        result = gatherer.gather(
            dest_dir=str(tmp_path),
            device="mydev",
            release="myrel",
            vendor="vendor",
            date_override="2024-01-15",
        )
        assert result.manifest is not None
        assert result.total_count == 2
        names = {p.name for p in result.artifacts}
        assert "image.wic.gz" in names
        assert "image.tar.gz" in names

    def test_gather_falls_back_to_list_when_no_manifest(self, tmp_path):
        backend = _FakeBackend()
        prefix = "vendor/mydev/myrel/2024-01-15"
        backend.blobs[f"{prefix}/image.wic.gz"] = b"wic_data"

        cfg = DeployConfig(prefix="{vendor}/{device}/{release}/{date}")
        gatherer = ArtifactGatherer(cfg, backend)
        result = gatherer.gather(
            dest_dir=str(tmp_path),
            device="mydev",
            release="myrel",
            vendor="vendor",
            date_override="2024-01-15",
        )
        assert result.manifest is None
        assert result.total_count == 1
        assert result.artifacts[0].name == "image.wic.gz"

    def test_gather_dry_run_returns_empty_result(self, tmp_path):
        backend = _FakeBackend(dry_run=True)
        cfg = DeployConfig(prefix="{vendor}/{device}/{release}/{date}")
        gatherer = ArtifactGatherer(cfg, backend)
        result = gatherer.gather(
            dest_dir=str(tmp_path),
            device="mydev",
            release="myrel",
            vendor="vendor",
            date_override="2024-01-15",
        )
        assert result.dry_run is True
        assert result.total_count == 0

    def test_gather_result_dest_dir_is_set(self, tmp_path):
        gatherer, _, _ = self._make_gatherer_with_artifacts(tmp_path)
        result = gatherer.gather(
            dest_dir=str(tmp_path),
            device="mydev",
            release="myrel",
            vendor="vendor",
            date_override="2024-01-15",
        )
        assert result.dest_dir == tmp_path

    def test_gather_writes_files_to_dest(self, tmp_path):
        gatherer, _, _ = self._make_gatherer_with_artifacts(tmp_path)
        gatherer.gather(
            dest_dir=str(tmp_path),
            device="mydev",
            release="myrel",
            vendor="vendor",
            date_override="2024-01-15",
        )
        assert (tmp_path / "image.wic.gz").exists()
        assert (tmp_path / "image.tar.gz").exists()


# =============================================================================
# ArtifactGatherer progress output tests
# =============================================================================


class TestGatherProgressOutput:
    """Verify that gather() emits progress messages to stdout without --verbose."""

    def _make_gatherer_with_artifacts(self, tmp_path):
        backend = _FakeBackend()
        prefix = "vendor/mydev/myrel/2024-01-15"
        backend.blobs[f"{prefix}/image.wic.gz"] = b"wic_data"
        backend.blobs[f"{prefix}/image.tar.gz"] = b"tar_data"
        manifest = {
            "schema_version": "1",
            "artifacts": [
                {"name": "image.wic.gz"},
                {"name": "image.tar.gz"},
            ],
        }
        backend.blobs[f"{prefix}/manifest.json"] = json.dumps(manifest).encode()
        cfg = DeployConfig(prefix="{vendor}/{device}/{release}/{date}")
        return ArtifactGatherer(cfg, backend)

    def test_gather_banner_printed(self, tmp_path, capsys):
        gatherer = self._make_gatherer_with_artifacts(tmp_path)
        gatherer.gather(
            dest_dir=str(tmp_path),
            device="mydev",
            release="myrel",
            vendor="vendor",
            date_override="2024-01-15",
        )
        out = capsys.readouterr().out
        assert "Gathering artifacts" in out
        assert "mydev" in out
        assert "myrel" in out

    def test_per_file_download_printed(self, tmp_path, capsys):
        gatherer = self._make_gatherer_with_artifacts(tmp_path)
        gatherer.gather(
            dest_dir=str(tmp_path),
            device="mydev",
            release="myrel",
            vendor="vendor",
            date_override="2024-01-15",
        )
        out = capsys.readouterr().out
        assert "Downloading image.wic.gz" in out
        assert "Downloading image.tar.gz" in out

    def test_dry_run_banner_printed(self, tmp_path, capsys):
        backend = _FakeBackend(dry_run=True)
        cfg = DeployConfig(prefix="{vendor}/{device}/{release}/{date}")
        gatherer = ArtifactGatherer(cfg, backend)
        gatherer.gather(
            dest_dir=str(tmp_path),
            device="mydev",
            release="myrel",
            vendor="vendor",
            date_override="2024-01-15",
        )
        out = capsys.readouterr().out
        assert "[dry-run]" in out
        assert "Would download" in out

    def test_gather_cache_dry_run_message_printed(self, tmp_path, capsys):
        backend = _FakeBackend(dry_run=True)
        cfg = DeployConfig(prefix="{vendor}/{device}/{release}/{date}")
        gatherer = ArtifactGatherer(cfg, backend)
        gatherer.gather(
            dest_dir=str(tmp_path),
            device="mydev",
            release="myrel",
            vendor="vendor",
            date_override="2024-01-15",
            gather_cache=True,
        )
        out = capsys.readouterr().out
        assert "Would restore Yocto caches" in out


# =============================================================================
# AzureStorageBackend.download_file tests
# =============================================================================


class TestAzureStorageBackendDownload:
    def _make_azure_backend(self, container="test-container"):
        """Return an AzureStorageBackend wired to a mocked _client."""
        try:
            from bsp.storage.azure import AzureStorageBackend
        except ImportError:
            pytest.skip("azure-storage-blob not installed")

        backend = AzureStorageBackend(container_name=container, dry_run=True)
        # Replace the dry_run flag and inject a mock client so we can test real paths
        backend.dry_run = False
        mock_client = MagicMock()
        backend._client = mock_client
        return backend, mock_client

    def test_download_file_calls_readinto(self, tmp_path):
        try:
            from bsp.storage.azure import AzureStorageBackend
        except ImportError:
            pytest.skip("azure-storage-blob not installed")

        backend, mock_client = self._make_azure_backend()
        mock_blob_client = MagicMock()
        mock_stream = MagicMock()
        mock_client.get_blob_client.return_value = mock_blob_client
        mock_blob_client.download_blob.return_value = mock_stream

        dest = tmp_path / "image.wic.gz"
        backend.download_file("vendor/device/rel/date/image.wic.gz", dest)

        mock_client.get_blob_client.assert_called_once_with(
            container="test-container", blob="vendor/device/rel/date/image.wic.gz"
        )
        mock_blob_client.download_blob.assert_called_once()
        mock_stream.readinto.assert_called_once()

    def test_download_file_dry_run_skips_api(self, tmp_path):
        try:
            from bsp.storage.azure import AzureStorageBackend
        except ImportError:
            pytest.skip("azure-storage-blob not installed")

        backend = AzureStorageBackend(container_name="test", dry_run=True)
        dest = tmp_path / "image.wic.gz"
        backend.download_file("some/remote/image.wic.gz", dest)
        # File should NOT have been created
        assert not dest.exists()

    def test_download_file_creates_parent_dirs(self, tmp_path):
        try:
            from bsp.storage.azure import AzureStorageBackend
        except ImportError:
            pytest.skip("azure-storage-blob not installed")

        backend, mock_client = self._make_azure_backend()
        mock_blob_client = MagicMock()
        mock_stream = MagicMock()
        mock_client.get_blob_client.return_value = mock_blob_client
        mock_blob_client.download_blob.return_value = mock_stream

        deep_dest = tmp_path / "a" / "b" / "c" / "image.wic.gz"
        backend.download_file("some/key", deep_dest)
        assert deep_dest.parent.is_dir()


# =============================================================================
# AwsStorageBackend.download_file tests
# =============================================================================


class TestAwsStorageBackendDownload:
    def _make_aws_backend(self, bucket="test-bucket"):
        try:
            from bsp.storage.aws import AwsStorageBackend
        except ImportError:
            pytest.skip("boto3 not installed")

        backend = AwsStorageBackend(bucket_name=bucket, dry_run=True)
        backend.dry_run = False
        mock_s3 = MagicMock()
        backend._s3 = mock_s3
        return backend, mock_s3

    def test_download_file_calls_s3_download(self, tmp_path):
        try:
            from bsp.storage.aws import AwsStorageBackend
        except ImportError:
            pytest.skip("boto3 not installed")

        backend, mock_s3 = self._make_aws_backend()
        dest = tmp_path / "image.wic.gz"
        backend.download_file("vendor/device/rel/date/image.wic.gz", dest)

        mock_s3.download_file.assert_called_once_with(
            "test-bucket",
            "vendor/device/rel/date/image.wic.gz",
            str(dest),
        )

    def test_download_file_dry_run_skips_api(self, tmp_path):
        try:
            from bsp.storage.aws import AwsStorageBackend
        except ImportError:
            pytest.skip("boto3 not installed")

        backend = AwsStorageBackend(bucket_name="test", dry_run=True)
        dest = tmp_path / "image.wic.gz"
        backend.download_file("some/key", dest)
        assert not dest.exists()

    def test_download_file_creates_parent_dirs(self, tmp_path):
        try:
            from bsp.storage.aws import AwsStorageBackend
        except ImportError:
            pytest.skip("boto3 not installed")

        backend, mock_s3 = self._make_aws_backend()
        deep_dest = tmp_path / "a" / "b" / "image.wic.gz"
        backend.download_file("some/key", deep_dest)
        assert deep_dest.parent.is_dir()


# =============================================================================
# CLI gather command argument tests
# =============================================================================


class TestCliGatherArguments:
    def _run_cli(self, args, registry_path):
        from bsp.cli import main as cli_main
        with patch("sys.argv", ["bsp", "--registry", str(registry_path)] + args):
            with patch("bsp.bsp_manager.BspManager.gather_bsp") as mock_gather:
                mock_gather.return_value = GatherResult()
                with patch("bsp.bsp_manager.BspManager.initialize"):
                    with patch("bsp.bsp_manager.BspManager.load_configuration"):
                        with patch("bsp.bsp_manager.BspManager.cleanup"):
                            return cli_main(), mock_gather

    def test_gather_bsp_name(self, tmp_path):
        reg = tmp_path / "bsp-registry.yaml"
        reg.write_text("specification:\n  version: '2.0'\nregistry:\n  devices: []\n  releases: []\n")
        with patch("sys.argv", ["bsp", "--registry", str(reg), "gather", "my-preset"]):
            with patch("bsp.cli.BspManager") as MockBspMgr:
                mock_mgr = MockBspMgr.return_value
                mock_mgr.gather_bsp.return_value = GatherResult()
                from bsp.cli import main as cli_main
                cli_main()
                mock_mgr.gather_bsp.assert_called_once()
                call_kwargs = mock_mgr.gather_bsp.call_args
                assert call_kwargs[0][0] == "my-preset" or call_kwargs[1].get("bsp_name") == "my-preset" or "my-preset" in str(call_kwargs)

    def test_gather_dry_run_flag(self, tmp_path):
        reg = tmp_path / "bsp-registry.yaml"
        reg.write_text("specification:\n  version: '2.0'\nregistry:\n  devices: []\n  releases: []\n")
        with patch("sys.argv", ["bsp", "--registry", str(reg), "gather", "my-preset", "--dry-run"]):
            with patch("bsp.cli.BspManager") as MockBspMgr:
                mock_mgr = MockBspMgr.return_value
                mock_mgr.gather_bsp.return_value = GatherResult()
                from bsp.cli import main as cli_main
                cli_main()
                _, kwargs = mock_mgr.gather_bsp.call_args
                assert kwargs.get("dry_run") is True

    def test_gather_date_flag(self, tmp_path):
        reg = tmp_path / "bsp-registry.yaml"
        reg.write_text("specification:\n  version: '2.0'\nregistry:\n  devices: []\n  releases: []\n")
        with patch("sys.argv", ["bsp", "--registry", str(reg), "gather", "my-preset", "--date", "2024-01-15"]):
            with patch("bsp.cli.BspManager") as MockBspMgr:
                mock_mgr = MockBspMgr.return_value
                mock_mgr.gather_bsp.return_value = GatherResult()
                from bsp.cli import main as cli_main
                cli_main()
                _, kwargs = mock_mgr.gather_bsp.call_args
                assert kwargs.get("date_override") == "2024-01-15"

    def test_gather_dest_dir_flag(self, tmp_path):
        reg = tmp_path / "bsp-registry.yaml"
        reg.write_text("specification:\n  version: '2.0'\nregistry:\n  devices: []\n  releases: []\n")
        dest = str(tmp_path / "dest")
        with patch("sys.argv", ["bsp", "--registry", str(reg), "gather", "my-preset", "--dest-dir", dest]):
            with patch("bsp.cli.BspManager") as MockBspMgr:
                mock_mgr = MockBspMgr.return_value
                mock_mgr.gather_bsp.return_value = GatherResult()
                from bsp.cli import main as cli_main
                cli_main()
                _, kwargs = mock_mgr.gather_bsp.call_args
                assert kwargs.get("dest_dir") == dest

    def test_gather_by_components(self, tmp_path):
        reg = tmp_path / "bsp-registry.yaml"
        reg.write_text("specification:\n  version: '2.0'\nregistry:\n  devices: []\n  releases: []\n")
        with patch("sys.argv", ["bsp", "--registry", str(reg), "gather", "--device", "rpi5", "--release", "scarthgap"]):
            with patch("bsp.cli.BspManager") as MockBspMgr:
                mock_mgr = MockBspMgr.return_value
                mock_mgr.gather_by_components.return_value = GatherResult()
                from bsp.cli import main as cli_main
                cli_main()
                mock_mgr.gather_by_components.assert_called_once()


# =============================================================================
# BspManager gather methods (mocked backend)
# =============================================================================


GATHER_REGISTRY_YAML = """
specification:
  version: "2.1"
containers:
  ubuntu-22.04:
    image: "test/ubuntu-22.04:latest"
registry:
  devices:
    - slug: rpi5
      description: "Raspberry Pi 5"
      vendor: raspberrypi
      soc_vendor: broadcom
      includes: []
  releases:
    - slug: scarthgap
      description: "Scarthgap"
      yocto_version: "5.0"
      includes: []
  features: []
  bsp:
    - name: rpi5-scarthgap
      description: "RPI5 Scarthgap BSP"
      device: rpi5
      release: scarthgap
      features: []
      build:
        container: ubuntu-22.04
        path: build/rpi5/scarthgap
deploy:
  provider: azure
  container: bsp-artifacts
  account_url: https://myaccount.blob.core.windows.net
  prefix: "{vendor}/{device}/{release}/{date}"
"""


@pytest.fixture()
def gather_registry_file(tmp_path):
    reg = tmp_path / "bsp-registry.yaml"
    reg.write_text(GATHER_REGISTRY_YAML)
    return reg


class TestBspManagerGather:
    def test_gather_bsp_calls_gatherer(self, gather_registry_file, tmp_path):
        from bsp import BspManager
        mgr = BspManager(config_path=str(gather_registry_file))
        mgr.initialize()

        mock_result = GatherResult(dest_dir=tmp_path)
        with patch("bsp.bsp_manager.ArtifactGatherer") as MockGatherer:
            mock_instance = MockGatherer.return_value
            mock_instance.gather.return_value = mock_result
            with patch("bsp.bsp_manager.create_backend") as mock_factory:
                mock_backend = MagicMock()
                mock_factory.return_value = mock_backend
                result = mgr.gather_bsp(
                    "rpi5-scarthgap",
                    dest_dir=str(tmp_path),
                    dry_run=True,
                )

        assert isinstance(result, GatherResult)

    def test_gather_by_components_calls_gatherer(self, gather_registry_file, tmp_path):
        from bsp import BspManager
        mgr = BspManager(config_path=str(gather_registry_file))
        mgr.initialize()

        mock_result = GatherResult(dest_dir=tmp_path)
        with patch("bsp.bsp_manager.ArtifactGatherer") as MockGatherer:
            mock_instance = MockGatherer.return_value
            mock_instance.gather.return_value = mock_result
            with patch("bsp.bsp_manager.create_backend") as mock_factory:
                mock_backend = MagicMock()
                mock_factory.return_value = mock_backend
                result = mgr.gather_by_components(
                    "rpi5", "scarthgap",
                    dest_dir=str(tmp_path),
                    dry_run=True,
                )

        assert isinstance(result, GatherResult)

    def test_gather_bsp_default_dest_is_image_deploy_dir(self, gather_registry_file, tmp_path):
        """Without --dest-dir, artifacts go to <build_path>/build/tmp/deploy/images."""
        from pathlib import Path
        from bsp import BspManager
        mgr = BspManager(config_path=str(gather_registry_file))
        mgr.initialize()

        with patch("bsp.bsp_manager.ArtifactGatherer") as MockGatherer:
            mock_instance = MockGatherer.return_value
            mock_instance.gather.return_value = GatherResult()
            with patch("bsp.bsp_manager.create_backend") as mock_factory:
                mock_factory.return_value = MagicMock()
                mgr.gather_bsp("rpi5-scarthgap", dry_run=True)

        call_kwargs = mock_instance.gather.call_args.kwargs
        assert call_kwargs["dest_dir"] == str(
            Path("build/rpi5/scarthgap") / "build" / "tmp" / "deploy" / "images"
        )

    def test_gather_bsp_explicit_dest_dir_unchanged(self, gather_registry_file, tmp_path):
        """Explicit dest_dir is used exactly as given."""
        from bsp import BspManager
        mgr = BspManager(config_path=str(gather_registry_file))
        mgr.initialize()

        dest = str(tmp_path / "my-artifacts")
        with patch("bsp.bsp_manager.ArtifactGatherer") as MockGatherer:
            mock_instance = MockGatherer.return_value
            mock_instance.gather.return_value = GatherResult()
            with patch("bsp.bsp_manager.create_backend") as mock_factory:
                mock_factory.return_value = MagicMock()
                mgr.gather_bsp("rpi5-scarthgap", dest_dir=dest, dry_run=True)

        call_kwargs = mock_instance.gather.call_args.kwargs
        assert call_kwargs["dest_dir"] == dest

    def test_gather_bsp_dry_run_reports_effective_dest(self, gather_registry_file, tmp_path, capsys):
        """Dry-run summary reports the effective image deploy destination."""
        from pathlib import Path
        from bsp import BspManager
        mgr = BspManager(config_path=str(gather_registry_file))
        mgr.initialize()

        expected_dest = str(
            Path("build/rpi5/scarthgap") / "build" / "tmp" / "deploy" / "images"
        )
        with patch("bsp.bsp_manager.ArtifactGatherer") as MockGatherer:
            mock_instance = MockGatherer.return_value
            mock_instance.gather.return_value = GatherResult(
                artifacts=[Path(expected_dest) / "image.wic"],
                dry_run=True,
            )
            with patch("bsp.bsp_manager.create_backend") as mock_factory:
                mock_factory.return_value = MagicMock()
                mgr.gather_bsp("rpi5-scarthgap", dry_run=True)

        out = capsys.readouterr().out
        assert f"→ {expected_dest}" in out

    def test_gather_bsp_default_cache_dest_based_on_build_root(self, gather_registry_file, tmp_path):
        """Inferred cache restore defaults stay anchored at the build root."""
        from pathlib import Path
        from bsp import BspManager
        mgr = BspManager(config_path=str(gather_registry_file))
        mgr.initialize()
        mgr.env_manager = MagicMock()
        mgr.env_manager.get_value.return_value = None

        with patch("bsp.bsp_manager.ArtifactGatherer") as MockGatherer:
            mock_instance = MockGatherer.return_value
            mock_instance.gather.return_value = GatherResult()
            with patch("bsp.bsp_manager.create_backend") as mock_factory:
                mock_factory.return_value = MagicMock()
                mgr.gather_bsp("rpi5-scarthgap", dry_run=True, gather_cache=True)

        call_kwargs = mock_instance.gather.call_args.kwargs
        build_root = Path("build/rpi5/scarthgap")
        assert call_kwargs["downloads_dest"] == str((build_root / "downloads").resolve())
        assert call_kwargs["sstate_dest"] == str((build_root / "sstate-cache").resolve())
        # Cache defaults must not be shifted into the images directory
        assert "deploy" not in call_kwargs["downloads_dest"]
        assert "deploy" not in call_kwargs["sstate_dest"]

    def test_gather_bsp_explicit_dest_dir_drives_cache_base(self, gather_registry_file, tmp_path):
        """With explicit dest_dir, inferred cache defaults stay based on it."""
        from pathlib import Path
        from bsp import BspManager
        mgr = BspManager(config_path=str(gather_registry_file))
        mgr.initialize()
        mgr.env_manager = MagicMock()
        mgr.env_manager.get_value.return_value = None

        dest = str(tmp_path / "arts")
        with patch("bsp.bsp_manager.ArtifactGatherer") as MockGatherer:
            mock_instance = MockGatherer.return_value
            mock_instance.gather.return_value = GatherResult()
            with patch("bsp.bsp_manager.create_backend") as mock_factory:
                mock_factory.return_value = MagicMock()
                mgr.gather_bsp(
                    "rpi5-scarthgap", dest_dir=dest, dry_run=True, gather_cache=True
                )

        call_kwargs = mock_instance.gather.call_args.kwargs
        assert call_kwargs["dest_dir"] == dest
        assert call_kwargs["downloads_dest"] == str(Path(dest) / "downloads")
        assert call_kwargs["sstate_dest"] == str(Path(dest) / "sstate-cache")

    def test_gather_bsp_dry_run_no_container_required(self, gather_registry_file, tmp_path):
        """Dry run should not exit even when container is not configured."""
        from bsp import BspManager
        from bsp.models import DeployConfig
        from dataclasses import replace

        mgr = BspManager(config_path=str(gather_registry_file))
        mgr.initialize()
        # Override model.deploy to omit container
        mgr.model = replace(mgr.model, deploy=DeployConfig(provider="azure", container=None))

        mock_result = GatherResult(dest_dir=tmp_path)
        with patch("bsp.bsp_manager.ArtifactGatherer") as MockGatherer:
            mock_instance = MockGatherer.return_value
            mock_instance.gather.return_value = mock_result
            with patch("bsp.bsp_manager.create_backend") as mock_factory:
                mock_factory.return_value = MagicMock()
                # dry_run=True so missing container should not cause sys.exit
                result = mgr.gather_bsp("rpi5-scarthgap", dry_run=True)

        assert isinstance(result, GatherResult)


# =============================================================================
# GatherResult cache_artifacts field tests
# =============================================================================


class TestGatherResultCacheArtifacts:
    def test_defaults_empty(self):
        result = GatherResult()
        assert result.cache_artifacts == []

    def test_total_count_excludes_cache_artifacts(self, tmp_path):
        art = tmp_path / "img.wic.gz"
        cache = tmp_path / "downloads"
        result = GatherResult(artifacts=[art], cache_artifacts=[cache])
        assert result.total_count == 1  # only artifacts, not cache


# =============================================================================
# ArtifactGatherer cache restore tests
# =============================================================================


class TestArtifactGathererCacheRestore:
    """Test Yocto cache restore logic in ArtifactGatherer."""

    def _make_gatherer(self, backend=None):
        cfg = DeployConfig(
            provider="azure",
            container="bsp-artifacts",
            prefix="{device}/{release}/{date}",
        )
        if backend is None:
            backend = _FakeBackend()
        return ArtifactGatherer(cfg, backend)

    def _make_cache_archive(self, tmp_path, name="downloads") -> bytes:
        """Create a minimal tar.gz archive for testing extraction."""
        import io
        import tarfile

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            content = f"cache file for {name}".encode()
            info = tarfile.TarInfo(name=f"{name}/cached.file")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        return buf.getvalue()

    def test_gather_cache_downloads_restored(self, tmp_path):
        backend = _FakeBackend()
        prefix = "mydev/rel/2025-01-01"
        # Put an artifact so gather() has something to download
        backend.blobs[f"{prefix}/image.wic.gz"] = b"wic"
        # Put a downloads cache archive
        backend.blobs[f"{prefix}/cache/downloads.tar.gz"] = self._make_cache_archive(tmp_path)

        gatherer = self._make_gatherer(backend=backend)
        downloads_dest = str(tmp_path / "dl_restore")
        result = gatherer.gather(
            dest_dir=str(tmp_path / "artifacts"),
            device="mydev",
            release="rel",
            date_override="2025-01-01",
            gather_cache=True,
            downloads_dest=downloads_dest,
        )

        assert len(result.cache_artifacts) == 1
        assert str(tmp_path / "dl_restore") in [str(p) for p in result.cache_artifacts]

    def test_gather_cache_sstate_restored(self, tmp_path):
        backend = _FakeBackend()
        prefix = "dev/rel/2025-01-01"
        backend.blobs[f"{prefix}/image.wic.gz"] = b"wic"
        backend.blobs[f"{prefix}/cache/sstate.tar.gz"] = self._make_cache_archive(tmp_path, "sstate")

        gatherer = self._make_gatherer(backend=backend)
        sstate_dest = str(tmp_path / "ss_restore")
        result = gatherer.gather(
            dest_dir=str(tmp_path / "arts"),
            device="dev",
            release="rel",
            date_override="2025-01-01",
            gather_cache=True,
            sstate_dest=sstate_dest,
        )

        assert len(result.cache_artifacts) == 1
        assert str(tmp_path / "ss_restore") in [str(p) for p in result.cache_artifacts]

    def test_gather_cache_soft_skip_when_missing(self, tmp_path):
        """Missing cache archive must not cause failure — just log info."""
        backend = _FakeBackend()
        prefix = "dev/rel/2025-01-01"
        backend.blobs[f"{prefix}/image.wic.gz"] = b"wic"
        # No cache archive stored

        gatherer = self._make_gatherer(backend=backend)
        # Should not raise
        result = gatherer.gather(
            dest_dir=str(tmp_path / "arts"),
            device="dev",
            release="rel",
            date_override="2025-01-01",
            gather_cache=True,
            downloads_dest=str(tmp_path / "dl"),
        )

        assert result.cache_artifacts == []
        assert len(result.artifacts) == 1  # regular artifact still downloaded

    def test_gather_without_cache_flag_no_restore(self, tmp_path):
        """Without gather_cache=True no cache restore is attempted."""
        backend = _FakeBackend()
        prefix = "dev/rel/2025-01-01"
        backend.blobs[f"{prefix}/image.wic.gz"] = b"wic"
        backend.blobs[f"{prefix}/cache/downloads.tar.gz"] = self._make_cache_archive(tmp_path)

        gatherer = self._make_gatherer(backend=backend)
        result = gatherer.gather(
            dest_dir=str(tmp_path),
            device="dev", release="rel", date_override="2025-01-01",
            gather_cache=False,
        )

        assert result.cache_artifacts == []

    def test_gather_cache_dry_run_no_download(self, tmp_path):
        backend = _FakeBackend(dry_run=True)
        gatherer = self._make_gatherer(backend=backend)
        result = gatherer.gather(
            dest_dir=str(tmp_path),
            device="dev", release="rel", date_override="2025-01-01",
            gather_cache=True,
            downloads_dest=str(tmp_path / "dl"),
        )

        # dry_run exits early — no artifacts, no cache
        assert result.cache_artifacts == []
        assert result.dry_run is True

    def test_gather_cache_from_manifest(self, tmp_path):
        """When manifest has yocto_cache section the cache archive is located correctly."""
        backend = _FakeBackend()
        prefix = "dev/rel/2025-01-01"
        manifest = {
            "schema_version": "1",
            "artifacts": [{"name": "image.wic.gz", "sha256": "x"}],
            "yocto_cache": {
                "downloads": {
                    "name": "downloads.tar.gz",
                    "remote_url": f"fake://{prefix}/cache/downloads.tar.gz",
                    "sha256": "y",
                }
            },
        }
        backend.blobs[f"{prefix}/manifest.json"] = json.dumps(manifest).encode()
        backend.blobs[f"{prefix}/image.wic.gz"] = b"wic"
        backend.blobs[f"{prefix}/cache/downloads.tar.gz"] = self._make_cache_archive(tmp_path)

        gatherer = self._make_gatherer(backend=backend)
        result = gatherer.gather(
            dest_dir=str(tmp_path / "arts"),
            device="dev", release="rel", date_override="2025-01-01",
            gather_cache=True,
            downloads_dest=str(tmp_path / "dl"),
        )

        assert len(result.cache_artifacts) == 1


# =============================================================================
# BspManager gather cache path resolution tests
# =============================================================================


class TestBspManagerGatherCachePaths:
    """Verify that BspManager wires cache flags through to ArtifactGatherer."""

    @pytest.fixture()
    def gather_registry_file2(self, tmp_path):
        yaml_content = """
specification:
  version: "2.0"
registry:
  devices:
    - slug: rpi5
      description: "Raspberry Pi 5"
      vendor: rpi
      soc_vendor: bcm
      includes:
        - kas/rpi5.yaml
  releases:
    - slug: scarthgap
      description: "Scarthgap"
      includes:
        - kas/scarthgap.yaml
  features: []
  bsp:
    - name: rpi5-scarthgap
      description: "RPi5 Scarthgap"
      device: rpi5
      release: scarthgap
deploy:
  provider: azure
  container: bsp-artifacts
"""
        reg_file = tmp_path / "bsp-registry.yaml"
        reg_file.write_text(yaml_content)
        return reg_file

    def test_gather_bsp_passes_gather_cache_to_gatherer(self, tmp_path, gather_registry_file2):
        from bsp.bsp_manager import BspManager

        mgr = BspManager(config_path=str(gather_registry_file2))
        mgr.initialize()

        with patch("bsp.bsp_manager.ArtifactGatherer") as MockGatherer:
            mock_instance = MockGatherer.return_value
            mock_instance.gather.return_value = GatherResult(dest_dir=tmp_path)
            with patch("bsp.bsp_manager.create_backend") as mock_factory:
                mock_factory.return_value = MagicMock()
                mgr.gather_bsp(
                    "rpi5-scarthgap",
                    dry_run=True,
                    gather_cache=True,
                    cache_downloads_dest="/mnt/dl",
                    cache_sstate_dest="/mnt/ss",
                )

        call_kwargs = mock_instance.gather.call_args.kwargs
        assert call_kwargs.get("gather_cache") is True
        assert call_kwargs.get("downloads_dest") == "/mnt/dl"
        assert call_kwargs.get("sstate_dest") == "/mnt/ss"

    def test_resolve_cache_restore_paths_uses_env_manager(self, tmp_path, gather_registry_file2):
        from bsp.bsp_manager import BspManager

        mgr = BspManager(config_path=str(gather_registry_file2))
        mgr.initialize()

        mock_env = MagicMock()
        mock_env.get_value.side_effect = lambda k: "/env/dl" if k == "DL_DIR" else "/env/ss"
        mgr.env_manager = mock_env

        dl, ss = mgr._resolve_cache_restore_paths()
        assert dl == "/env/dl"
        assert ss == "/env/ss"

    def test_resolve_cache_restore_paths_cli_override_wins(self, tmp_path, gather_registry_file2):
        from bsp.bsp_manager import BspManager

        mgr = BspManager(config_path=str(gather_registry_file2))
        mgr.initialize()

        mock_env = MagicMock()
        mock_env.get_value.side_effect = lambda k: "/env/dl"
        mgr.env_manager = mock_env

        dl, ss = mgr._resolve_cache_restore_paths(cache_downloads_dest="/cli/dl")
        assert dl == "/cli/dl"  # CLI wins

    def test_resolve_cache_restore_paths_falls_back_to_yocto_defaults(
        self, tmp_path, gather_registry_file2
    ):
        from bsp.bsp_manager import BspManager

        mgr = BspManager(config_path=str(gather_registry_file2))
        mgr.initialize()
        mgr.env_manager = MagicMock()
        mgr.env_manager.get_value.return_value = None

        base_dir = tmp_path / "build"
        dl, ss = mgr._resolve_cache_restore_paths(
            base_dir=str(base_dir),
            create_dirs=True,
        )
        assert dl == str(base_dir / "downloads")
        assert ss == str(base_dir / "sstate-cache")
        assert (base_dir / "downloads").is_dir()
        assert (base_dir / "sstate-cache").is_dir()

    def test_resolve_cache_restore_paths_nested_artifact_dirs(
        self, tmp_path, gather_registry_file2
    ):
        """build/ prefix in artifact_dirs → restore defaults under base_dir/build/."""
        from bsp.bsp_manager import BspManager

        mgr = BspManager(config_path=str(gather_registry_file2))
        mgr.initialize()
        mgr.env_manager = MagicMock()
        mgr.env_manager.get_value.return_value = None

        base_dir = tmp_path / "bsp-build"
        dl, ss = mgr._resolve_cache_restore_paths(
            base_dir=str(base_dir),
            artifact_dirs=["build/tmp/deploy/images", "build/tmp/deploy/sdk"],
            create_dirs=True,
        )
        assert dl == str(base_dir / "build" / "downloads")
        assert ss == str(base_dir / "build" / "sstate-cache")
        assert (base_dir / "build" / "downloads").is_dir()
        assert (base_dir / "build" / "sstate-cache").is_dir()
