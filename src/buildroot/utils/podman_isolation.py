"""Podman storage isolation for concurrent builds.

When many podman processes share the same storage root, they contend on
containers/storage locks (graphroot), libpod runtime state (runroot/tmpdir),
and base image pulls. This module creates fully isolated podman environments
so 60+ concurrent builds can run without contention.

Usage in evaluator (direct podman calls):
    iso = PodmanIsolation.create()
    cmd = iso.wrap_command(["podman", "build", ...])
    subprocess.run(cmd)
    iso.cleanup()

Usage for agent subprocesses (all podman calls via env var):
    iso = PodmanIsolation.create()
    env = iso.get_env()
    subprocess.run(["claude", ...], env=env)
    iso.cleanup()
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


def _find_writable_base() -> Path:
    for candidate in [Path("/workspace"), Path(tempfile.gettempdir())]:
        if candidate.exists() and os.access(candidate, os.W_OK):
            return candidate
    return Path(tempfile.gettempdir())


DEFAULT_BASE_IMAGES = [
    # Generic temurin tags (79% of builds)
    "docker.io/eclipse-temurin:8-jdk",
    "docker.io/eclipse-temurin:11-jdk",
    "docker.io/eclipse-temurin:17-jdk",
    "docker.io/eclipse-temurin:21-jdk",
    "docker.io/eclipse-temurin:17-jdk-focal",
    "docker.io/eclipse-temurin:8-jdk-focal",
    "docker.io/eclipse-temurin:22-jdk",
    "docker.io/eclipse-temurin:23-jdk",
    # Maven images
    "docker.io/library/maven:3.9.9-eclipse-temurin-8-focal",
    "docker.io/library/maven:3.9.6-eclipse-temurin-11",
    "docker.io/library/maven:3.9.6-eclipse-temurin-17",
    "docker.io/library/maven:3.8.6-eclipse-temurin-11",
]

_BASE_IMAGES_TARBALL: Path | None = None


def save_base_images(
    images: list[str] | None = None,
    output: str | Path | None = None,
) -> Path:
    """Pull and save base images to a tarball for pre-warming isolated roots.

    Call once before spawning workers. The tarball is reused across all workers.
    """
    global _BASE_IMAGES_TARBALL
    images = images or DEFAULT_BASE_IMAGES
    base = _find_writable_base()
    output = Path(output) if output else base / "podman-base-images.tar"

    if output.exists() and output.stat().st_size > 0:
        logger.info("Base images tarball already exists: %s", output)
        _BASE_IMAGES_TARBALL = output
        return output

    # Lock to prevent concurrent workers from racing on the same tarball
    lock_path = Path(str(output) + ".lock")
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        logger.info("Another worker is saving base images, waiting...")
        for _ in range(120):
            import time
            time.sleep(5)
            if output.exists() and output.stat().st_size > 0:
                _BASE_IMAGES_TARBALL = output
                return output
        raise RuntimeError("Timed out waiting for base images tarball")

    try:
        available = []
        for img in images:
            proc = subprocess.run(
                ["podman", "image", "exists", img],
                capture_output=True, timeout=10,
            )
            if proc.returncode == 0:
                available.append(img)
            else:
                logger.info("Pulling %s...", img)
                pull = subprocess.run(
                    ["podman", "pull", img],
                    capture_output=True, text=True, timeout=600,
                )
                if pull.returncode == 0:
                    available.append(img)
                else:
                    logger.warning("Failed to pull %s: %s", img, pull.stderr[:200])

        if not available:
            logger.warning("No base images available to save — skipping prewarm")
            _BASE_IMAGES_TARBALL = None
            return output

        # Save to temp file, then atomic rename. Retry on failure
        # (podman save can fail under storage contention).
        tmp_output = Path(str(output) + f".tmp.{os.getpid()}")
        logger.info("Saving %d base images to %s", len(available), output)
        last_err = ""
        for attempt in range(3):
            proc = subprocess.run(
                ["podman", "save", "-o", str(tmp_output)] + available,
                capture_output=True, text=True, timeout=600,
            )
            if proc.returncode == 0:
                break
            last_err = proc.stderr[:300]
            tmp_output.unlink(missing_ok=True)
            logger.warning("podman save attempt %d failed: %s", attempt + 1, last_err[:100])
            import time
            time.sleep(5)
        else:
            logger.warning("podman save failed after 3 attempts (storage contention?) — skipping prewarm")
            _BASE_IMAGES_TARBALL = None
            return output

        tmp_output.rename(output)
        _BASE_IMAGES_TARBALL = output
        logger.info("Saved %d images (%.1f MB)", len(available), output.stat().st_size / 1e6)
        return output
    finally:
        lock_path.unlink(missing_ok=True)


def get_base_images_tarball() -> Path | None:
    """Return the cached tarball path, or None if not yet saved."""
    return _BASE_IMAGES_TARBALL


@dataclass
class PodmanIsolation:
    """Fully isolated podman storage environment."""

    graphroot: Path
    runroot: Path
    tmpdir: Path
    storage_conf: Path
    containers_conf: Path

    @classmethod
    def create(cls, worker_id: str | None = None, prewarm_tarball: str | Path | None = None) -> PodmanIsolation:
        slug = worker_id or uuid.uuid4().hex
        base = _find_writable_base()

        graphroot = base / "containers-storage-isolated" / slug
        runroot = base / "containers-run-isolated" / slug
        tmpdir = base / "containers-tmp-isolated" / slug

        for d in [graphroot, runroot, tmpdir]:
            d.mkdir(parents=True, exist_ok=True)

        storage_conf = graphroot / "storage.conf"
        storage_conf.write_text(
            f"[storage]\n"
            f'driver = "overlay"\n'
            f'graphroot = "{graphroot}"\n'
            f'runroot = "{runroot}"\n'
            f"\n"
            f"[storage.options.overlay]\n"
            f'mount_program = "/usr/bin/fuse-overlayfs"\n'
        )

        # containers.conf controls libpod's tmp_dir (alive.lck, state)
        containers_conf = graphroot / "containers.conf"
        containers_conf.write_text(
            f"[engine]\n"
            f'tmp_dir = "{tmpdir}"\n'
        )

        instance = cls(
            graphroot=graphroot,
            runroot=runroot,
            tmpdir=tmpdir,
            storage_conf=storage_conf,
            containers_conf=containers_conf,
        )

        tarball = prewarm_tarball or get_base_images_tarball()
        if tarball:
            instance.prewarm(tarball)

        return instance

    @classmethod
    def from_env(cls) -> PodmanIsolation | None:
        """Reconstruct a PodmanIsolation from inherited CONTAINERS_STORAGE_CONF env var.

        Returns None if the env var is not set or the config file doesn't exist.
        """
        conf_path = os.environ.get("CONTAINERS_STORAGE_CONF")
        if not conf_path:
            return None
        storage_conf = Path(conf_path)
        if not storage_conf.exists():
            return None
        graphroot = storage_conf.parent
        containers_conf_path = os.environ.get("CONTAINERS_CONF", "")
        containers_conf = Path(containers_conf_path) if containers_conf_path else graphroot / "containers.conf"
        runroot = graphroot.parent.parent / "containers-run-isolated" / graphroot.name
        tmpdir = graphroot.parent.parent / "containers-tmp-isolated" / graphroot.name
        return cls(
            graphroot=graphroot,
            runroot=runroot,
            tmpdir=tmpdir,
            storage_conf=storage_conf,
            containers_conf=containers_conf,
        )

    def wrap_command(self, cmd: list[str]) -> list[str]:
        """Inject --root/--runroot/--tmpdir into a podman command list."""
        if cmd and cmd[0] == "podman":
            return [
                "podman",
                "--root", str(self.graphroot),
                "--runroot", str(self.runroot),
                "--tmpdir", str(self.tmpdir),
            ] + cmd[1:]
        return cmd

    def wrap_shell_command(self, shell_cmd: str) -> str:
        """Inject isolation flags into a podman shell command string."""
        if "podman " in shell_cmd:
            flags = (
                f"--root {shlex.quote(str(self.graphroot))} "
                f"--runroot {shlex.quote(str(self.runroot))} "
                f"--tmpdir {shlex.quote(str(self.tmpdir))}"
            )
            return shell_cmd.replace("podman", f"podman {flags}", 1)
        return shell_cmd

    def prewarm(self, tarball: str | Path) -> bool:
        """Load pre-saved base images into this isolated root.

        Use ``save_base_images()`` to create the tarball once, then
        call ``prewarm()`` on each worker's isolation before builds start.
        """
        tarball = Path(tarball)
        if not tarball.exists():
            logger.warning("Prewarm tarball not found: %s", tarball)
            return False
        try:
            proc = subprocess.run(
                self.wrap_command(["podman", "load", "-i", str(tarball)]),
                capture_output=True, text=True, timeout=120,
            )
            if proc.returncode == 0:
                logger.info("Pre-warmed images from %s into %s", tarball, self.graphroot)
                return True
            logger.warning("Prewarm failed (exit %d): %s", proc.returncode, proc.stderr[:200])
            return False
        except Exception as e:
            logger.warning("Prewarm error: %s", e)
            return False

    def get_env(self) -> dict[str, str]:
        """Return env dict with CONTAINERS_STORAGE_CONF set.

        This makes ALL podman commands in the subprocess use isolated
        storage automatically — including direct bash calls from agents.
        """
        env = dict(os.environ)
        env["CONTAINERS_STORAGE_CONF"] = str(self.storage_conf)
        env["CONTAINERS_CONF"] = str(self.containers_conf)
        return env

    def cleanup(self) -> None:
        """Remove all isolated storage directories."""
        try:
            subprocess.run(
                self.wrap_command(["podman", "system", "reset", "--force"]),
                capture_output=True, timeout=60,
            )
        except Exception:
            pass
        for d in [self.graphroot, self.runroot, self.tmpdir]:
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass
