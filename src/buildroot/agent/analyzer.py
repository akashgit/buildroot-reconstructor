"""Analyzer agent — error classification, dead-end registry, and G_t progress signal."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from buildroot.agent.models import DeadEndEntry, EvalResult

logger = logging.getLogger(__name__)


ERROR_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("build_tool/multi_module", re.compile(
        r"Could not find artifact .* in reactor|"
        r"Non-resolvable parent POM", re.IGNORECASE
    )),
    ("dependency_resolution/missing_artifact", re.compile(
        r"Could not (resolve|find) (artifact|dependencies)", re.IGNORECASE
    )),
    ("dependency_resolution/version_conflict", re.compile(
        r"version conflict|Dependency convergence error", re.IGNORECASE
    )),
    ("compilation/jdk_mismatch", re.compile(
        r"(source|target) (option|release) \d+ is not supported|"
        r"invalid (source|target) release|"
        r"class file has wrong version", re.IGNORECASE
    )),
    ("compilation/syntax_error", re.compile(
        r"\[ERROR\].*\.java:\[\d+,\d+\]|"
        r"error: cannot find symbol|"
        r"error: package .* does not exist", re.IGNORECASE
    )),
    ("plugin/configuration_error", re.compile(
        r"Failed to execute goal .* on project|"
        r"Plugin .* or one of its dependencies could not be resolved", re.IGNORECASE
    )),
    ("plugin/gpg_error", re.compile(
        r"gpg: signing failed|Cannot run program \"gpg\"", re.IGNORECASE
    )),
    ("environment/gha_secrets", re.compile(
        r"\$\{\{\s*secrets\.", re.IGNORECASE
    )),
    ("environment/gha_expressions", re.compile(
        r"\$\{\{.*\}\}", re.IGNORECASE
    )),
    ("environment/image_resolution", re.compile(
        r"short-name .* did not resolve|"
        r"Failed to resolve image|"
        r"manifest unknown", re.IGNORECASE
    )),
    ("source/wrong_tag", re.compile(
        r"fatal: Remote branch .* not found|"
        r"fatal: couldn't find remote ref|"
        r"error: pathspec .* did not match", re.IGNORECASE
    )),
    ("source/clone_failed", re.compile(
        r"fatal: repository .* not found|"
        r"fatal: could not read from remote", re.IGNORECASE
    )),
    ("build_tool/maven_wrapper", re.compile(
        r"mvnw: No such file|"
        r"./mvnw: Permission denied|"
        r"Error: Could not find or load main class", re.IGNORECASE
    )),
    ("resource/oom", re.compile(
        r"java\.lang\.OutOfMemoryError|"
        r"GC overhead limit exceeded|"
        r"insufficient memory", re.IGNORECASE
    )),
    ("resource/disk_space", re.compile(
        r"No space left on device|"
        r"ENOSPC", re.IGNORECASE
    )),
    ("environment/credentials", re.compile(
        r"401 Unauthorized|"
        r"403 Forbidden|"
        r"authentication required", re.IGNORECASE
    )),
]

FUNDAMENTAL_BLOCKERS = frozenset({
    "environment/credentials",
    "source/clone_failed",
})


@dataclass
class AnalysisResult:
    error_class: str
    error_summary: str
    fix_suggestion: str
    is_fundamental_blocker: bool = False


def classify_error(error_summary: str, build_log: str = "") -> str:
    """Classify a build error using regex patterns. Returns the error class string."""
    combined = f"{error_summary}\n{build_log}"
    for error_class, pattern in ERROR_PATTERNS:
        if pattern.search(combined):
            return error_class
    return "unknown"


def analyze(eval_result: EvalResult, dead_ends: list[DeadEndEntry]) -> AnalysisResult:
    """Full analysis: classify error, check dead-ends, suggest fix."""
    error_class = classify_error(
        eval_result.error_summary, eval_result.build_log
    )

    fix_suggestion = _suggest_fix(error_class, eval_result.error_summary)

    is_blocker = error_class in FUNDAMENTAL_BLOCKERS

    return AnalysisResult(
        error_class=error_class,
        error_summary=eval_result.error_summary,
        fix_suggestion=fix_suggestion,
        is_fundamental_blocker=is_blocker,
    )


def update_dead_ends(
    dead_ends: list[DeadEndEntry],
    error_class: str,
    approach: str,
    log_summary: str,
) -> None:
    """Record a failure in the dead-end registry. Creates entry if needed."""
    key = f"{error_class}::{approach}"
    for entry in dead_ends:
        if f"{entry.error_class}::{entry.approach}" == key:
            entry.record_failure(log_summary)
            return
    entry = DeadEndEntry(error_class=error_class, approach=approach)
    entry.record_failure(log_summary)
    dead_ends.append(entry)


def all_exhausted(dead_ends: list[DeadEndEntry]) -> bool:
    """Check if all registered approaches are exhausted."""
    if not dead_ends:
        return False
    return all(de.is_exhausted for de in dead_ends)


def _suggest_fix(error_class: str, error_summary: str) -> str:
    """Suggest a fix direction based on the error class."""
    suggestions = {
        "dependency_resolution/missing_artifact": (
            "Try a different Maven repository or check if the dependency version exists. "
            "Consider adding -U to force snapshot updates."
        ),
        "dependency_resolution/version_conflict": (
            "Check dependency management section. Try using -Denforcer.skip=true."
        ),
        "compilation/jdk_mismatch": (
            "Switch to the correct JDK version. Check the pom.xml for "
            "maven.compiler.source/target properties."
        ),
        "compilation/syntax_error": (
            "This may indicate a generated-source issue. Check if annotation "
            "processors need to run first."
        ),
        "plugin/configuration_error": (
            "Try skipping the failing plugin with -Dplugin.skip=true or "
            "updating the plugin version."
        ),
        "plugin/gpg_error": "Add -Dgpg.skip=true to the build command.",
        "environment/gha_secrets": (
            "Remove ${{ secrets.* }} expressions from ARG/ENV lines."
        ),
        "environment/gha_expressions": (
            "Remove all ${{ }} expressions — they are GitHub Actions syntax, "
            "not valid in Containerfiles."
        ),
        "environment/image_resolution": (
            "Use fully-qualified image names with docker.io/ prefix."
        ),
        "source/wrong_tag": (
            "Try alternate tag formats: remove 'v' prefix, try 'rel/' prefix, "
            "or use the branch name."
        ),
        "source/clone_failed": "The repository may be private or have moved.",
        "build_tool/multi_module": (
            "Add '-pl <module>' flag to build only the target module, "
            "or 'mvn install -N' to install parent first."
        ),
        "build_tool/maven_wrapper": (
            "Use 'mvn' instead of './mvnw', or ensure mvnw is executable "
            "(chmod +x mvnw)."
        ),
        "resource/oom": (
            "Increase Java heap: ENV MAVEN_OPTS='-Xmx2g' or use -Dmaven.compiler.fork=false."
        ),
        "resource/disk_space": "Use a smaller base image or multi-stage build.",
        "environment/credentials": "This package requires authentication — likely a private repo.",
    }
    return suggestions.get(error_class, "Analyze the build log for specific failure details.")
