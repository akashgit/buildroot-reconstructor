"""CI workflow parsing for GitHub Actions and CircleCI."""

from __future__ import annotations

import logging
import re

from ruamel.yaml import YAML

from buildroot.pipeline.models import Annotated, CIData, Source
from buildroot.utils.github_api import fetch_file_content, list_directory

logger = logging.getLogger(__name__)

_yaml = YAML()
_yaml.preserve_quotes = True

APT_RE = re.compile(r"(?:sudo\s+)?apt-get\s+install\s+(?:-[a-z]+\s+)*(.+)", re.MULTILINE)
YUM_RE = re.compile(r"(?:sudo\s+)?yum\s+install\s+(?:-[a-z]+\s+)*(.+)", re.MULTILINE)
MVN_RE = re.compile(r"(?:\.\/)?mvn[w]?\s+(.+)", re.MULTILINE)
GRADLE_RE = re.compile(r"(?:\./gradlew|gradle)\s+(.+)", re.MULTILINE)


class CIParser:
    """Parse CI workflow files to extract build environment data."""

    def parse_github_actions(self, yaml_text: str) -> CIData:
        data = _yaml.load(yaml_text)
        if not isinstance(data, dict):
            return CIData(ci_type="github")

        ci = CIData(ci_type="github")
        jobs = data.get("jobs", {})
        if not isinstance(jobs, dict):
            return ci

        for job_name, job_def in jobs.items():
            if not isinstance(job_def, dict):
                continue
            self._parse_github_job(job_def, ci)

        return ci

    def _parse_github_job(self, job_def: dict, ci: CIData) -> None:
        runs_on = job_def.get("runs-on", "")
        if isinstance(runs_on, str) and runs_on:
            ci.runner_os = runs_on

        container = job_def.get("container", None)
        if isinstance(container, str):
            ci.container_images.append(container)
        elif isinstance(container, dict):
            image = container.get("image", "")
            if image:
                ci.container_images.append(image)

        job_env = job_def.get("env", {})
        if isinstance(job_env, dict):
            for k, v in job_env.items():
                ci.env_vars[str(k)] = str(v)

        matrix = self._extract_matrix(job_def)

        steps = job_def.get("steps", [])
        if not isinstance(steps, list):
            return

        for step in steps:
            if not isinstance(step, dict):
                continue

            step_env = step.get("env", {})
            if isinstance(step_env, dict):
                for k, v in step_env.items():
                    ci.env_vars[str(k)] = str(v)

            uses = step.get("uses", "")
            if isinstance(uses, str):
                self._parse_uses_step(uses, step, ci, matrix)

            run_cmd = step.get("run", "")
            if isinstance(run_cmd, str) and run_cmd:
                self._parse_run_step(run_cmd, ci)

    def _extract_matrix(self, job_def: dict) -> dict:
        strategy = job_def.get("strategy", {})
        if not isinstance(strategy, dict):
            return {}
        matrix = strategy.get("matrix", {})
        if not isinstance(matrix, dict):
            return {}
        return dict(matrix)

    def _parse_uses_step(self, uses: str, step: dict, ci: CIData, matrix: dict) -> None:
        with_block = step.get("with", {})
        if not isinstance(with_block, dict):
            with_block = {}

        if "actions/setup-java" in uses:
            java_version = str(with_block.get("java-version", ""))
            distribution = str(with_block.get("distribution", ""))

            java_version = self._resolve_matrix_ref(java_version, matrix)
            distribution = self._resolve_matrix_ref(distribution, matrix)

            if java_version:
                ci.java_version = Annotated(
                    value=java_version,
                    source=Source.OBSERVED,
                    description=f"From setup-java action in CI ({uses})",
                )
            if distribution:
                ci.distribution = Annotated(
                    value=distribution,
                    source=Source.OBSERVED,
                    description=f"From setup-java action in CI ({uses})",
                )

        elif "graalvm/setup-graalvm" in uses:
            java_version = str(with_block.get("java-version", ""))
            java_version = self._resolve_matrix_ref(java_version, matrix)
            if java_version:
                ci.java_version = Annotated(
                    value=java_version,
                    source=Source.OBSERVED,
                    description=f"From setup-graalvm action in CI ({uses})",
                )
                ci.distribution = Annotated(
                    value="graalvm",
                    source=Source.OBSERVED,
                    description=f"From setup-graalvm action in CI ({uses})",
                )

    def _resolve_matrix_ref(self, value: str, matrix: dict) -> str:
        """Resolve ${{ matrix.* }} references against the strategy matrix."""
        if not value:
            return value

        pattern = re.compile(r"\$\{\{\s*matrix\.([a-zA-Z0-9_.-]+)\s*\}\}")
        match = pattern.search(value)
        if not match:
            return value

        ref_path = match.group(1)
        resolved = self._lookup_matrix(ref_path, matrix)
        if resolved is not None:
            return pattern.sub(str(resolved), value)
        return value

    def _lookup_matrix(self, ref_path: str, matrix: dict):
        """Look up a dotted path in the matrix dict. For arrays, take the first element."""
        if ref_path in matrix:
            val = matrix[ref_path]
            if isinstance(val, list) and val:
                return val[0]
            return val

        parts = ref_path.split(".")
        current = matrix
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and current:
                if part.isdigit():
                    idx = int(part)
                    current = current[idx] if idx < len(current) else None
                else:
                    current = current[0]
                    if isinstance(current, dict):
                        current = current.get(part)
            else:
                return None
            if current is None:
                return None

        if isinstance(current, list) and current:
            return current[0]
        return current

    def _parse_run_step(self, run_cmd: str, ci: CIData) -> None:
        for m in APT_RE.finditer(run_cmd):
            packages = m.group(1).strip().rstrip("\\").split()
            ci.system_packages.extend(
                p for p in packages if not p.startswith("-")
            )

        for m in YUM_RE.finditer(run_cmd):
            packages = m.group(1).strip().rstrip("\\").split()
            ci.system_packages.extend(
                p for p in packages if not p.startswith("-")
            )

        for m in MVN_RE.finditer(run_cmd):
            ci.build_commands.append(f"mvn {m.group(1).strip()}")

        for m in GRADLE_RE.finditer(run_cmd):
            ci.build_commands.append(f"gradle {m.group(1).strip()}")

        if "./gradlew" in run_cmd:
            for line in run_cmd.splitlines():
                line = line.strip()
                if line.startswith("./gradlew"):
                    ci.build_commands.append(line)

    def parse_circleci(self, yaml_text: str) -> CIData:
        data = _yaml.load(yaml_text)
        if not isinstance(data, dict):
            return CIData(ci_type="circleci")

        ci = CIData(ci_type="circleci")

        for job_name, job_def in data.get("jobs", {}).items():
            if not isinstance(job_def, dict):
                continue

            docker_list = job_def.get("docker", [])
            if isinstance(docker_list, list):
                for entry in docker_list:
                    if isinstance(entry, dict) and "image" in entry:
                        ci.container_images.append(entry["image"])
                    elif isinstance(entry, str):
                        ci.container_images.append(entry)

            job_env = job_def.get("environment", {})
            if isinstance(job_env, dict):
                for k, v in job_env.items():
                    ci.env_vars[str(k)] = str(v)

            steps = job_def.get("steps", [])
            if not isinstance(steps, list):
                continue
            for step in steps:
                if isinstance(step, dict) and "run" in step:
                    run_val = step["run"]
                    if isinstance(run_val, dict):
                        cmd = run_val.get("command", "")
                    else:
                        cmd = str(run_val)
                    if cmd:
                        self._parse_run_step(cmd, ci)

        executors = data.get("executors", {})
        if isinstance(executors, dict):
            for exec_name, exec_def in executors.items():
                if not isinstance(exec_def, dict):
                    continue
                docker_list = exec_def.get("docker", [])
                if isinstance(docker_list, list):
                    for entry in docker_list:
                        if isinstance(entry, dict) and "image" in entry:
                            ci.container_images.append(entry["image"])
                exec_env = exec_def.get("environment", {})
                if isinstance(exec_env, dict):
                    for k, v in exec_env.items():
                        ci.env_vars[str(k)] = str(v)

        orbs = data.get("orbs", {})
        if isinstance(orbs, dict):
            for orb_name, orb_ref in orbs.items():
                logger.info("CircleCI orb detected (not resolved): %s = %s", orb_name, orb_ref)

        return ci

    def discover_ci_type(
        self, repo_owner: str, repo_name: str
    ) -> tuple[str, list[str]]:
        """Discover CI type and fetch workflow YAML texts from a GitHub repo.

        Returns (ci_type, list_of_yaml_texts) where ci_type is
        'github', 'circleci', or 'none'.
        """
        files = list_directory(repo_owner, repo_name, ".github/workflows")
        if files:
            yaml_texts = []
            for f in files:
                name = f.get("name", "")
                if name.endswith((".yml", ".yaml")):
                    content = fetch_file_content(
                        repo_owner, repo_name,
                        f".github/workflows/{name}",
                    )
                    if content:
                        yaml_texts.append(content)
            if yaml_texts:
                return ("github", yaml_texts)

        circleci_content = fetch_file_content(
            repo_owner, repo_name, ".circleci/config.yml"
        )
        if circleci_content:
            return ("circleci", [circleci_content])

        return ("none", [])
