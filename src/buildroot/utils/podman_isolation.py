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


@dataclass
class PodmanIsolation:
    """Fully isolated podman storage environment."""

    graphroot: Path
    runroot: Path
    tmpdir: Path
    storage_conf: Path
    containers_conf: Path

    @classmethod
    def create(cls, worker_id: str | None = None) -> PodmanIsolation:
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
