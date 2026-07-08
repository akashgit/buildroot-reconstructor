"""Submit builds to PNC staging via the bacon CLI."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

_environment_cache: list[dict] | None = None

BACON_PATH = os.path.expanduser("~/bin/bacon")


@dataclass
class PncBuildParams:
    git_url: str
    git_tag: str
    build_command: str
    build_type: str  # "MVN" or "GRADLE"
    jdk_version: str
    maven_version: str | None = None
    extra_flags: str = ""


@dataclass
class PncBuildResult:
    build_id: str
    status: str  # "SUCCESS", "FAILED", "SYSTEM_ERROR"
    artifacts: list[dict] = field(default_factory=list)
    environment_id: str = ""
    scm_repo_id: str = ""
    build_config_id: str = ""


def parse_containerfile_for_pnc(containerfile: str) -> PncBuildParams:
    raw_lines = containerfile.strip().splitlines()
    lines: list[str] = []
    for raw in raw_lines:
        if lines and lines[-1].endswith("\\"):
            lines[-1] = lines[-1][:-1] + " " + raw.strip()
        else:
            lines.append(raw)

    git_url = ""
    git_tag = ""
    build_command = ""
    build_type = ""
    jdk_version = ""
    maven_version: str | None = None

    for line in lines:
        stripped = line.strip()

        if re.match(r"^ENV\s+JAVA_HOME\s*=\s*", stripped):
            m = re.search(r"jdk[_-]?(\d+)", stripped)
            if m:
                jdk_version = m.group(1)

        if stripped.startswith("FROM ") and not jdk_version:
            m = re.search(r"temurin[:\-](\d+)", stripped)
            if m:
                jdk_version = m.group(1)

        if "git clone" in stripped:
            url_match = re.search(r"(https?://\S+\.git|git@\S+\.git)", stripped)
            if url_match:
                git_url = url_match.group(1)
            branch_match = re.search(r"--branch\s+(\S+)", stripped)
            if branch_match:
                git_tag = branch_match.group(1)

        if re.match(r"^RUN\s+(mvn|\.?/?\s*gradlew|gradle)\s", stripped):
            cmd = re.sub(r"^RUN\s+", "", stripped)
            if cmd.startswith("mvn"):
                build_type = "MVN"
                cmd = re.sub(r"\binstall\b", "deploy", cmd, count=1)
            else:
                build_type = "GRADLE"
            build_command = cmd

    if not git_url:
        raise ValueError("No git clone command found in Containerfile")

    return PncBuildParams(
        git_url=git_url,
        git_tag=git_tag,
        build_command=build_command,
        build_type=build_type,
        jdk_version=jdk_version,
        maven_version=maven_version,
    )


def _is_auth_error(stderr: str) -> bool:
    lower = stderr.lower()
    return "keycloak authentication failed" in lower or "401" in stderr


def _run_bacon(args: list[str], *, profile: str = "stage", timeout: int = 300) -> str:
    if not os.path.exists(BACON_PATH):
        raise FileNotFoundError(
            f"bacon not found at {BACON_PATH}. "
            "Install PNC bacon: https://github.com/project-ncl/bacon"
        )

    cmd = [BACON_PATH, f"--profile={profile}"] + args
    logger.debug("Running: %s", " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    if result.returncode != 0 and _is_auth_error(result.stderr):
        import sys
        logger.info("Auth token expired — retrying with interactive login")
        print("\n--- PNC authentication required ---", file=sys.stderr)
        print("Bacon will open a login URL. Paste the code when prompted.\n", file=sys.stderr)
        result = subprocess.run(cmd, stdin=sys.stdin, stdout=subprocess.PIPE,
                                stderr=sys.stderr, text=True, timeout=timeout)

    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        raise RuntimeError(f"bacon command failed (rc={result.returncode}): {stderr}")

    return result.stdout


def _parse_bacon_json(raw: str) -> dict | list:
    """Parse JSON from bacon output, skipping log/color lines."""
    for line in raw.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith(("{", "[")):
            return json.loads(stripped)
    return json.loads(raw)


def match_pnc_environment(
    jdk_version: str, maven_version: str | None = None, *, profile: str = "stage"
) -> str:
    global _environment_cache

    if _environment_cache is None:
        raw = _run_bacon(
            ["pnc", "environment", "list", "--query=deprecated==false", "-o"],
            profile=profile,
        )
        data = _parse_bacon_json(raw)
        _environment_cache = data if isinstance(data, list) else [data]

    candidates = []
    for env in _environment_cache:
        attrs = env.get("attributes", {})
        env_jdk = attrs.get("JDK", "")
        if env_jdk and jdk_version == env_jdk:
            candidates.append(env)

    if not candidates:
        for env in _environment_cache:
            name = env.get("name", "")
            if f"JDK {jdk_version}" in name or f"j{jdk_version}" in name.lower():
                candidates.append(env)

    if not candidates:
        raise ValueError(f"No PNC environment found for JDK {jdk_version}")

    if maven_version:
        for env in candidates:
            attrs = env.get("attributes", {})
            env_maven = attrs.get("MAVEN", "") or env.get("name", "")
            if maven_version in env_maven:
                return str(env["id"])

    return str(candidates[0]["id"])


def submit_pnc_build(
    params: PncBuildParams,
    *,
    profile: str = "stage",
    project_id: str = "4249",
    timeout: int = 20,
) -> PncBuildResult:
    # a. Create/sync SCM repo
    scm_raw = _run_bacon(
        ["pnc", "scm-repository", "create-and-sync", params.git_url, "-o"],
        profile=profile,
    )
    scm_data = _parse_bacon_json(scm_raw)
    if isinstance(scm_data, list):
        scm_data = scm_data[0]
    scm_repo_id = str(scm_data.get("id", ""))

    # b. Match environment
    env_id = match_pnc_environment(
        params.jdk_version, params.maven_version, profile=profile
    )

    # c. Create build config
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    artifact_name = params.git_url.rstrip("/").rsplit("/", 1)[-1].replace(".git", "")
    config_name = f"{artifact_name}-{params.git_tag}-repro-{timestamp}"

    bc_raw = _run_bacon(
        [
            "pnc", "build-config", "create",
            f"--environment-id={env_id}",
            f"--project-id={project_id}",
            f"--build-script={params.build_command}",
            f"--scm-repository-id={scm_repo_id}",
            f"--scm-revision={params.git_tag}",
            f"--build-type={params.build_type}",
            config_name,
            "-o",
        ],
        profile=profile,
    )
    bc_data = _parse_bacon_json(bc_raw)
    build_config_id = str(bc_data.get("id", ""))

    # d. Start build
    build_raw = _run_bacon(
        [
            "pnc", "build", "start",
            "--temporary-build", "--wait",
            "--rebuild-mode=FORCE", "--no-build-dependencies",
            f"--timeout={timeout}",
            build_config_id,
            "-o",
        ],
        profile=profile,
        timeout=timeout * 60 + 120,
    )
    build_data = _parse_bacon_json(build_raw)
    build_id = str(build_data.get("id", ""))
    status = build_data.get("status", "UNKNOWN")

    # e. List artifacts if successful
    artifacts: list[dict] = []
    if status == "SUCCESS":
        art_raw = _run_bacon(
            ["pnc", "build", "list-built-artifacts", build_id, "-o"],
            profile=profile,
        )
        art_data = _parse_bacon_json(art_raw)
        artifacts = art_data if isinstance(art_data, list) else [art_data]

    return PncBuildResult(
        build_id=build_id,
        status=status,
        artifacts=artifacts,
        environment_id=env_id,
        scm_repo_id=scm_repo_id,
        build_config_id=build_config_id,
    )
