"""
Image flasher: discovers Yocto image artifacts and flashes them using
bmap-tools (bmaptool), dd, or uuu (NXP mfgtools).

``bmaptool copy`` is the preferred backend because it:
* Reads the accompanying ``.bmap`` block-map file to skip empty blocks,
  making flashing 2–10× faster than a raw ``dd`` copy.
* Verifies data integrity using the SHA-256 checksums stored in the .bmap.
* Supports compressed images (``.wic.bz2``, ``.wic.gz``, ``.wic.xz``)
  directly, without requiring a prior decompression step.

bmap-tools installation: ``sudo apt install bmap-tools``
Project page: https://github.com/intel/bmap-tools
"""

import logging
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .models import FlashConfig


# =============================================================================
# Result dataclass
# =============================================================================


@dataclass
class FlashResult:
    """Result of a single flash operation."""
    image_path: Path
    target_device: str
    bmap_path: Optional[Path] = None
    dry_run: bool = False
    success: bool = False
    elapsed_seconds: float = 0.0


# =============================================================================
# ImageFlasher
# =============================================================================


class ImageFlasher:
    """
    Discovers a Yocto image artifact and flashes it to a block device.

    Provider-agnostic: the flash tool (``bmaptool``, ``dd``, or ``uuu``) is selected
    via ``flash_config.tool``.

    Args:
        flash_config: Flashing configuration (patterns, dirs, tool, extra args).
    """

    def __init__(self, flash_config: FlashConfig):
        self.config = flash_config
        self.logger = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def flash(
        self,
        build_path: str,
        target_device: str,
        image_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> FlashResult:
        """
        Flash an image to *target_device*.

        When *image_path* is provided it is used directly.  Otherwise the
        method discovers the image automatically via :meth:`_find_image`.

        Args:
            build_path: Top-level build output directory used for
                        auto-discovery when *image_path* is ``None``.
            target_device: Block device path (e.g. ``/dev/sdb``).
            image_path: Explicit path to the image file.  Overrides
                        auto-discovery when provided.
            dry_run: When ``True``, print what would be flashed without
                     actually writing anything to the device.

        Returns:
            :class:`FlashResult` describing the outcome of the operation.

        Raises:
            SystemExit: When no image is found, the flash tool is missing, or
                        the flash command fails.
        """
        # ------------------------------------------------------------------
        # 1. Resolve image path
        # ------------------------------------------------------------------
        if image_path is not None:
            resolved_image = Path(image_path)
            if not resolved_image.exists():
                self.logger.error("Explicit image path not found: %s", resolved_image)
                sys.exit(1)
        else:
            resolved_image = self._find_image(build_path)
            if resolved_image is None:
                self.logger.error(
                    "No flashable image found under '%s'. "
                    "Check image_patterns and artifact_dirs in the flash config.",
                    build_path,
                )
                sys.exit(1)

        bmap = self._find_bmap(resolved_image)

        # ------------------------------------------------------------------
        # 2. Dry-run: print what would be done and exit early
        # ------------------------------------------------------------------
        if dry_run:
            print(f"\n[dry-run] Would flash:")
            print(f"  image : {resolved_image}")
            if bmap:
                print(f"  bmap  : {bmap}")
            if target_device:
                print(f"  target: {target_device}")
            return FlashResult(
                image_path=resolved_image,
                target_device=target_device,
                bmap_path=bmap,
                dry_run=True,
                success=True,
            )

        # ------------------------------------------------------------------
        # 3. Validate required target + check tool availability
        # ------------------------------------------------------------------
        if self.config.tool != "uuu" and not target_device:
            self.logger.error(
                "Flash tool '%s' requires a target device path. "
                "Use --target /dev/sdX.",
                self.config.tool,
            )
            sys.exit(1)

        self._check_tool_availability()

        # ------------------------------------------------------------------
        # 4. Warn when target device does not exist (but continue)
        # ------------------------------------------------------------------
        if self.config.tool != "uuu" and not Path(target_device).exists():
            self.logger.warning(
                "Target device '%s' does not exist. "
                "Make sure the SD card / USB drive is connected.",
                target_device,
            )

        # ------------------------------------------------------------------
        # 5. Build flash command
        # ------------------------------------------------------------------
        cmd = self._build_command(resolved_image, target_device, bmap)
        self.logger.info("Flashing image: %s", " ".join(cmd))
        if self.config.tool == "uuu":
            print(f"\nFlashing {resolved_image.name} via uuu …")
        else:
            print(f"\nFlashing {resolved_image.name} → {target_device} …")
        if bmap:
            print(f"  Using bmap file: {bmap.name}")

        # ------------------------------------------------------------------
        # 6. Run
        # ------------------------------------------------------------------
        start = time.monotonic()
        try:
            proc = subprocess.run(cmd, check=False)
            elapsed = time.monotonic() - start
            success = proc.returncode == 0
            if not success:
                self.logger.error(
                    "Flash command exited with code %d.", proc.returncode
                )
            else:
                print(f"Flash completed in {elapsed:.1f}s.")
        except (OSError, subprocess.SubprocessError) as exc:
            elapsed = time.monotonic() - start
            self.logger.error("Failed to run flash tool: %s", exc)
            success = False

        return FlashResult(
            image_path=resolved_image,
            target_device=target_device,
            bmap_path=bmap,
            dry_run=False,
            success=success,
            elapsed_seconds=elapsed,
        )

    # ------------------------------------------------------------------
    # Image discovery
    # ------------------------------------------------------------------

    def _find_image(self, build_path: str) -> Optional[Path]:
        """
        Find the first matching flashable image under *build_path*.

        Artifact directories are searched in order; within each directory
        the configured patterns are tried in order (most-compressed variant
        first).  The first match is returned.  A warning is logged when
        more than one candidate exists.

        Args:
            build_path: Top-level build output directory.

        Returns:
            Path to the discovered image, or ``None`` when nothing matches.
        """
        base = Path(build_path)
        all_matches: List[Path] = []
        selected_pattern: Optional[str] = None
        selected_search_dir: Optional[Path] = None

        self.logger.debug(
            "Searching flashable image under '%s' with artifact_dirs=%s and image_patterns=%s",
            base,
            self.config.artifact_dirs,
            self.config.image_patterns,
        )

        for artifact_dir in self.config.artifact_dirs:
            search_dir = base / artifact_dir
            if not search_dir.is_dir():
                self.logger.debug("Artifact dir not found, skipping: %s", search_dir)
                continue
            for pattern in self.config.image_patterns:
                self.logger.debug(
                    "Searching for flash image with pattern '%s' in '%s'.",
                    pattern,
                    search_dir,
                )
                matches = sorted(search_dir.glob(pattern))
                file_matches = [m for m in matches if m.is_file() and m not in all_matches]
                if file_matches:
                    self.logger.debug(
                        "Pattern '%s' matched %d candidate image(s).",
                        pattern,
                        len(file_matches),
                    )
                for m in file_matches:
                    all_matches.append(m)
                if all_matches:
                    # Return the first match for this pattern; lower-indexed
                    # patterns (more-compressed variants) win.
                    if selected_pattern is None:
                        selected_pattern = pattern
                        selected_search_dir = search_dir
                    break

        if len(all_matches) > 1:
            self.logger.warning(
                "Multiple flashable images found; using the first one: %s. "
                "Use --image-path to select a specific image.",
                all_matches[0],
            )

        if all_matches:
            self.logger.debug(
                "Selected flash image '%s' (pattern='%s', search_dir='%s').",
                all_matches[0],
                selected_pattern,
                selected_search_dir,
            )
        else:
            self.logger.debug(
                "No flashable image matched configured patterns: %s",
                self.config.image_patterns,
            )

        return all_matches[0] if all_matches else None

    # ------------------------------------------------------------------
    # Bmap discovery
    # ------------------------------------------------------------------

    def _find_bmap(self, image_path: Path) -> Optional[Path]:
        """
        Look for a ``.bmap`` block-map file alongside *image_path*.

        ``bmaptool`` automatically locates ``.bmap`` files when they reside
        next to the image, but we detect them here so we can log which file
        is being used and include it in :class:`FlashResult`.

        Args:
            image_path: Path to the image file.

        Returns:
            Path to the ``.bmap`` file if it exists, otherwise ``None``.
        """
        bmap_path = image_path.parent / (image_path.name + ".bmap")
        if bmap_path.exists():
            self.logger.debug("Found bmap file: %s", bmap_path)
            return bmap_path

        # Some builds name the bmap after the uncompressed image stem, e.g.
        # ``core-image-minimal.wic.bmap`` alongside ``core-image-minimal.wic.bz2``.
        # Strip one compression suffix and try again.
        for ext in (".bz2", ".gz", ".xz"):
            if image_path.name.endswith(ext):
                stem_name = image_path.name[: -len(ext)]
                alt_bmap = image_path.parent / (stem_name + ".bmap")
                if alt_bmap.exists():
                    self.logger.debug("Found bmap file (alt): %s", alt_bmap)
                    return alt_bmap

        return None

    # ------------------------------------------------------------------
    # Tool availability
    # ------------------------------------------------------------------

    def _check_tool_availability(self) -> None:
        """
        Verify that required flash executables are available on ``$PATH``.

        Exits with a descriptive install hint when the tool is missing.
        """
        if not self._is_running_as_root() and shutil.which("sudo") is None:
            self.logger.error(
                "Flashing requires superuser rights, but 'sudo' is not installed. "
                "Install sudo or run the command as root."
            )
            sys.exit(1)

        tool = self.config.tool
        if shutil.which(tool) is None:
            install_hints = {
                "bmaptool": (
                    "sudo apt install bmap-tools\n"
                    "  or see https://github.com/intel/bmap-tools"
                ),
                "dd": "dd is part of GNU coreutils and should already be installed.",
                "uuu": (
                    "Install uuu (mfgtools) from https://github.com/nxp-imx/mfgtools "
                    "or your distro package manager."
                ),
            }
            hint = install_hints.get(tool, f"Please install '{tool}' manually.")
            self.logger.error(
                "Required flash tool '%s' is not installed or not on PATH.\n"
                "Install it with: %s",
                tool,
                hint,
            )
            sys.exit(1)

    def _is_running_as_root(self) -> bool:
        """
        Return ``True`` when running as root/superuser.
        """
        geteuid = getattr(os, "geteuid", None)
        return bool(callable(geteuid) and geteuid() == 0)

    def _with_superuser_prefix(self, cmd: List[str]) -> List[str]:
        """
        Ensure the command executes with superuser rights.
        """
        if self._is_running_as_root():
            return cmd
        return ["sudo"] + cmd

    # ------------------------------------------------------------------
    # Command builder
    # ------------------------------------------------------------------

    def _build_command(
        self,
        image_path: Path,
        target_device: str,
        bmap_path: Optional[Path],
    ) -> List[str]:
        """
        Build the flash command list.

        For ``bmaptool`` the command is::

            bmaptool copy [--bmap <bmap>] [extra_args …] <image> <device>

        For ``dd`` the command is::

            dd if=<image> of=<device> bs=4M [extra_args …]

        For ``uuu`` the command is::

            uuu [extra_args …] -b emmc_all <image>

        The ``-b emmc_all`` burn script is added automatically unless the
        extra args already contain a ``-b``/``-d`` option or a script path,
        because invoking ``uuu <image>`` without a burn script makes uuu
        treat the image file as a uuu script and crash.  The image path is
        passed as an absolute path since uuu fails to resolve bare file
        names without a directory component.

        Args:
            image_path: Path to the image file to flash.
            target_device: Destination block device.
            bmap_path: Optional path to the ``.bmap`` file.

        Returns:
            Command as a list of strings ready for :func:`subprocess.run`.
        """
        tool = self.config.tool
        extra: List[str] = shlex.split(self.config.extra_args) if self.config.extra_args else []

        if tool == "bmaptool":
            cmd: List[str] = ["bmaptool", "copy"]
            if bmap_path:
                cmd += ["--bmap", str(bmap_path)]
            cmd += extra
            cmd += [str(image_path), target_device]
        elif tool == "dd":
            cmd = ["dd", f"if={image_path}", f"of={target_device}", "bs=4M"]
            cmd += extra
        elif tool == "uuu":
            cmd = ["uuu"] + extra
            if not any(arg in ("-b", "-d") for arg in extra):
                # Without a burn script uuu interprets the image file as a
                # uuu script and aborts; default to the eMMC burn flow.
                cmd += ["-b", "emmc_all"]
            # uuu cannot resolve bare file names without a directory
            # component ("can't find ext name in path"), so always pass
            # an absolute path.
            cmd += [str(Path(image_path).resolve())]
        else:
            # Generic: just call the tool with the image and device as args.
            cmd = [tool] + extra + [str(image_path), target_device]

        return self._with_superuser_prefix(cmd)
