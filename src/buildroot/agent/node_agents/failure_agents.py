"""Post-build failure agents — L2, L3, L4 diagnosis and fix proposals."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from buildroot.agent.claude_runner import AgentResult, spawn_claude_agent
from buildroot.pipeline.models import BuildrootSpec

logger = logging.getLogger(__name__)

FAILURE_MODEL = "claude-opus-4-6"
FAILURE_MAX_TURNS = 10
FAILURE_BUDGET_USD = 3.0
FAILURE_TIMEOUT = 300

FAILURE_FIX_SCHEMA = {
    "type": "object",
    "properties": {
        "diagnosis": {"type": "string"},
        "root_cause": {"type": "string"},
        "fixes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fix_type": {
                        "type": "string",
                        "enum": [
                            "base_image", "build_command", "env_var",
                            "system_package", "workdir", "git_tag",
                            "containerfile_line", "source_repo",
                        ],
                    },
                    "current_value": {"type": "string"},
                    "proposed_value": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
                "required": ["fix_type", "proposed_value", "reasoning"],
            },
        },
    },
    "required": ["diagnosis", "root_cause", "fixes"],
}


@dataclass
class FailureFix:
    fix_type: str
    current_value: str
    proposed_value: str
    reasoning: str


@dataclass
class FailureDiagnosis:
    diagnosis: str
    root_cause: str
    fixes: list[FailureFix]


class _BaseFailureAgent:
    """Common infrastructure for post-build failure agents."""

    agent_name: str = ""
    system_prompt: str = ""

    def diagnose(
        self, spec: BuildrootSpec, containerfile: str, log: str, **kwargs: Any
    ) -> FailureDiagnosis | None:
        task = self._build_task(spec, containerfile, log, **kwargs)
        result = spawn_claude_agent(
            task=task,
            system_prompt=self.system_prompt,
            model=FAILURE_MODEL,
            json_schema=FAILURE_FIX_SCHEMA,
            max_turns=FAILURE_MAX_TURNS,
            max_budget_usd=FAILURE_BUDGET_USD,
            timeout=FAILURE_TIMEOUT,
            allowed_tools=["Read", "Bash", "WebSearch"],
        )
        if result.is_error:
            logger.warning(
                "Failure agent %s failed: %s", self.agent_name, result.error_message
            )
            return None
        return self._parse_diagnosis(result)

    def apply_fixes(self, spec: BuildrootSpec, diagnosis: FailureDiagnosis) -> str | None:
        applied = []
        for fix in diagnosis.fixes:
            if fix.fix_type == "base_image":
                spec.jdk_spec.base_image = fix.proposed_value
                applied.append(f"base_image → {fix.proposed_value}")
            elif fix.fix_type == "build_command":
                spec.build_commands = [fix.proposed_value]
                applied.append(f"build_command → {fix.proposed_value}")
            elif fix.fix_type == "env_var":
                if "=" in fix.proposed_value:
                    key, _, val = fix.proposed_value.partition("=")
                    if spec.ci_data:
                        spec.ci_data.env_vars[key.strip()] = val.strip()
                applied.append(f"env_var → {fix.proposed_value}")
            elif fix.fix_type == "system_package":
                spec.system_packages.append(fix.proposed_value)
                applied.append(f"system_package → {fix.proposed_value}")
            elif fix.fix_type == "workdir":
                spec.pom_data.properties["_buildroot_subdir"] = fix.proposed_value
                applied.append(f"workdir → {fix.proposed_value}")
            elif fix.fix_type == "git_tag":
                spec.git_tag = fix.proposed_value
                applied.append(f"git_tag → {fix.proposed_value}")
            elif fix.fix_type == "source_repo":
                spec.source_repo = fix.proposed_value
                applied.append(f"source_repo → {fix.proposed_value}")
        if applied:
            logger.info(
                "Failure agent %s applied fixes: %s", self.agent_name, "; ".join(applied)
            )
            return "; ".join(applied)
        return None

    def _build_task(
        self, spec: BuildrootSpec, containerfile: str, log: str, **kwargs: Any
    ) -> str:
        raise NotImplementedError

    def _parse_diagnosis(self, result: AgentResult) -> FailureDiagnosis | None:
        output = result.structured_output
        if not output:
            return None
        fixes = []
        for fix_data in output.get("fixes", []):
            fixes.append(FailureFix(
                fix_type=fix_data.get("fix_type", ""),
                current_value=fix_data.get("current_value", ""),
                proposed_value=fix_data.get("proposed_value", ""),
                reasoning=fix_data.get("reasoning", ""),
            ))
        return FailureDiagnosis(
            diagnosis=output.get("diagnosis", ""),
            root_cause=output.get("root_cause", ""),
            fixes=fixes,
        )


L2_SYSTEM_PROMPT = """\
You are an L2 failure diagnosis agent for the buildroot reconstruction pipeline.

The container build (podman build) FAILED. Your job is to diagnose the root cause \
from the build log and propose Containerfile-level fixes.

Common L2 failure causes:
1. Base image tag doesn't exist on Docker Hub → fix: change base image
2. Package installation fails → fix: add/change system packages
3. Git clone fails (wrong repo URL or tag) → fix: correct repo URL or tag
4. Missing dependencies or tools → fix: add apt-get install commands
5. Syntax errors in Containerfile → fix: correct the syntax

Analyze the build log carefully. Propose specific, actionable fixes that modify \
the BuildrootSpec fields (base_image, build_command, system_package, git_tag, etc.).
"""


class L2FailureAgent(_BaseFailureAgent):
    """Diagnoses container build failures (L2) from build logs."""

    agent_name = "l2_failure_agent"
    system_prompt = L2_SYSTEM_PROMPT

    def _build_task(
        self, spec: BuildrootSpec, containerfile: str, log: str, **kwargs: Any
    ) -> str:
        return (
            f"The container build FAILED for {spec.pom_data.group_id}:{spec.pom_data.artifact_id}:{spec.pom_data.version}.\n\n"
            f"Source repo: {spec.source_repo}\n"
            f"Git tag: {spec.git_tag}\n"
            f"Base image: {spec.jdk_spec.base_image}\n"
            f"Build commands: {spec.build_commands}\n\n"
            f"--- Containerfile ---\n{containerfile}\n--- End Containerfile ---\n\n"
            f"--- Build log (last 3000 chars) ---\n{log[-3000:]}\n--- End Build Log ---\n\n"
            f"Diagnose the failure and propose fixes."
        )


L3_SYSTEM_PROMPT = """\
You are an L3 failure diagnosis agent for the buildroot reconstruction pipeline.

The container built successfully (L2 pass) but no JAR was found in target/ (L3 fail). \
Your job is to diagnose why the Maven/Gradle build produced no output JAR.

Common L3 failure causes:
1. Wrong build command (Maven vs Gradle) → fix: switch to correct build tool
2. Multi-module project needs -pl flag or WORKDIR change → fix: add -pl or fix workdir
3. Build succeeded but output is in different location → fix: adjust build command
4. Compilation failure during build → fix: adjust compiler flags or dependencies
5. Wrong source directory structure → fix: correct WORKDIR

Analyze the build output and propose specific fixes.
"""


class L3FailureAgent(_BaseFailureAgent):
    """Diagnoses build command failures (L3) from Maven/Gradle output."""

    agent_name = "l3_failure_agent"
    system_prompt = L3_SYSTEM_PROMPT

    def _build_task(
        self, spec: BuildrootSpec, containerfile: str, log: str, **kwargs: Any
    ) -> str:
        return (
            f"The container built but no JAR found in target/ for "
            f"{spec.pom_data.group_id}:{spec.pom_data.artifact_id}:{spec.pom_data.version}.\n\n"
            f"Source repo: {spec.source_repo}\n"
            f"Git tag: {spec.git_tag}\n"
            f"Build commands: {spec.build_commands}\n"
            f"Maven version: {spec.maven_version}\n"
            f"Modules: {spec.pom_data.modules}\n"
            f"Subdirectory: {spec.pom_data.properties.get('_buildroot_subdir', '')}\n\n"
            f"--- Containerfile ---\n{containerfile}\n--- End Containerfile ---\n\n"
            f"--- Build output (last 3000 chars) ---\n{log[-3000:]}\n--- End Build Output ---\n\n"
            f"Diagnose why no JAR was produced and propose fixes."
        )


L4_SYSTEM_PROMPT = """\
You are an L4 failure diagnosis agent for the buildroot reconstruction pipeline.

The build succeeded and a JAR was produced (L3 pass) but it does NOT match the \
original JAR from Maven Central (L4 fail). Your job is to analyze the JAR diff \
and identify reproducibility issues.

Common L4 failure causes:
1. Timestamps in META-INF/MANIFEST.MF → fix: add -Dproject.build.outputTimestamp
2. Different JDK version → fix: change JDK version
3. Different compiler flags → fix: adjust build command
4. Missing reproducible-build Maven extension → informational note
5. Different dependency versions → fix: pin dependencies

Analyze the comparison report and propose fixes where possible.
"""


class L4FailureAgent(_BaseFailureAgent):
    """Diagnoses JAR mismatch issues (L4) from comparison reports."""

    agent_name = "l4_failure_agent"
    system_prompt = L4_SYSTEM_PROMPT

    def _build_task(
        self, spec: BuildrootSpec, containerfile: str, log: str, **kwargs: Any
    ) -> str:
        diff_summary = kwargs.get("diff_summary", "")
        comparison_verdict = kwargs.get("comparison_verdict", "")
        return (
            f"The rebuilt JAR does NOT match the original for "
            f"{spec.pom_data.group_id}:{spec.pom_data.artifact_id}:{spec.pom_data.version}.\n\n"
            f"Source repo: {spec.source_repo}\n"
            f"Git tag: {spec.git_tag}\n"
            f"JDK version: {spec.jdk_spec.version}\n"
            f"Build commands: {spec.build_commands}\n\n"
            f"Comparison verdict: {comparison_verdict}\n"
            f"Diff summary: {diff_summary}\n\n"
            f"--- Containerfile ---\n{containerfile}\n--- End Containerfile ---\n\n"
            f"--- Build log excerpt ---\n{log[-2000:]}\n--- End ---\n\n"
            f"Identify the root cause of the mismatch and propose fixes."
        )
