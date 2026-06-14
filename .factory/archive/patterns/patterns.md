---
tags:
  - factory
  - patterns
source: factory-archivist
date: 2026-06-07
updated: 2026-06-14T00:00
---

# Cross-Project Patterns

## Build-Mode Projects Should Include Type Checking in Build Phases
Discovered in buildroot-reconstructor baseline.
The baseline eval scored 0.0 on type_check (23 mypy errors) because type checking was not part of the build phases. For Python projects, add a final build phase that runs `mypy` and fixes errors before establishing baseline — this is easy to fix during build but becomes a separate experiment later.

## JDK Version Strings Need Normalization for Docker Tags
Discovered in buildroot-reconstructor Phase 11.
Maven/JDK version strings (e.g., `1.8`, `1.11`) must be normalized to Docker-compatible format (`8`, `11`) before use in image tags. This is a specific instance of a general pattern: version strings from package managers don't always match container image tag conventions. Always add a normalization layer between version inference and template rendering.

## Builder Agent Timeouts Correlate with Broad Task Descriptions
Discovered in buildroot-reconstructor build cycle.
Two builder agents timed out (900s, 300s) when given broad task descriptions. Narrowing the task to specific files and steps resolved the issue. Pattern: when a builder times out, the CEO should retry with a more specific, step-by-step task description rather than simply retrying the same prompt.

## Eval Scripts Must Exclude Integration Tests by Default
Discovered in buildroot-reconstructor baseline setup.
Projects with integration tests (e.g., podman build tests) must configure eval to exclude them from the default test run, since eval environments may not have the required runtime (podman, docker, etc.). Use `--ignore=tests/integration` or equivalent.

## Bundling Interdependent Fixes Produces Clean Code Reviews but Risks Eval Regression
Discovered in buildroot-reconstructor experiment #001.
When 6 tightly coupled fixes are bundled into a single PR (+809 lines), the code review passes cleanly but the eval score may drop due to pre-existing issues becoming visible (type_check regression, test environment differences). Pattern: bundled PRs are correct for interdependent changes, but run eval in the worktree before the CEO verdict — not after — to isolate whether regressions are caused by the PR or pre-existing.

## Dead Code in SCM/URL Parsing Is a Common Source of Silent Build Failures
Discovered in buildroot-reconstructor experiment #001 (Fix 1).
The SCM extraction loop had a `pass` statement where real logic should have been — it compiled and tested fine, but silently failed to discover source repos for 6/10 test packages. Pattern: when reviewing code that "works" but produces incomplete results, check for stub implementations (`pass`, `...`, `TODO`) in critical data extraction paths.

## Code Review Fixes Can Recover Large Score Drops
Discovered in buildroot-reconstructor experiment #001 (KEEP verdict).
Initial eval showed -0.188 regression (0.831 → 0.6433), but 3 targeted code review fixes (shell injection in tests, type guard for Optional fields, boolean flag parsing) recovered to 0.8499 (+0.2066 net). Pattern: when an experiment's code review is CLEAN but eval drops, investigate the specific failing dimensions — the root causes are often fixable without reverting the experiment.

## Advisory Issues Should Be Tracked Separately from Blocking Issues
Discovered in buildroot-reconstructor experiment #001 (KEEP verdict).
3 advisory issues (flag parsing edge case, pagination false positive, response leak) were identified during code review but did not block the KEEP verdict. Pattern: separate advisory from blocking issues in code review — advisory issues become backlog items, not revert triggers. This avoids over-reverting experiments that deliver substantial value despite minor imperfections.

## Gradle Builds in Containers Require --no-daemon and ENV-Based Memory Config
Discovered in buildroot-reconstructor experiment #002.
Gradle daemon processes cause container builds to hang or OOM. Two fixes are required: (1) always pass `--no-daemon` to Gradle invocations, (2) use `ENV GRADLE_OPTS` in Containerfiles rather than inline `-Xmx` flags. The ENV approach is cleaner because it applies to all Gradle invocations in the container, including wrapper scripts.

## JAR Manifest Created-By Is a Reliable Fallback for Build JDK Detection
Discovered in buildroot-reconstructor experiment #002 (Fix 4).
When `Build-Jdk-Spec` is absent from JAR manifests, the `Created-By` header (e.g., `Created-By: 21.0.1 (Eclipse Adoptium)`) provides a reliable fallback for inferring the actual build JDK version. Pattern: for JDK version inference, check both headers — Build-Jdk-Spec first (clean major version), then Created-By (requires parsing the version prefix).

## Real Hardware Build Verification Catches Issues That Unit Tests and Inference Logic Miss
Discovered in buildroot-reconstructor experiment #002.
Experiment #001 had 35 passing unit tests and clean code review, but only 3/10 packages actually built in containers. The remaining 7 failures required iterative debugging on real hardware (rh-h100-01). Pattern: for build-system projects, inference correctness tests are necessary but not sufficient — always verify with actual container builds on representative hardware before declaring Level 3 complete.

## GitHub Actions Secrets and Expressions Leak into Generated Containerfiles
Discovered in buildroot-reconstructor experiment #003 (Level 4 builds).
CI workflow parsing copies `${{ secrets.GITHUB_TOKEN }}`, `${{ toJSON(github.event) }}`, and similar GitHub Actions expressions verbatim into generated Containerfile ARG/ENV instructions. These are not valid in container builds and cause 7/10 build failures. Pattern: CI workflow parsers need a sanitization pass that strips or replaces GitHub Actions expressions before template rendering. This is a Level 1 defect that surfaces only during Level 3+ verification — earlier levels don't execute the Containerfiles.

## Downstream Verification Layers Should Be Decoupled from Upstream Build Success
Discovered in buildroot-reconstructor experiment #003.
The Level 4 JAR comparison pipeline was fully implemented and tested (26 tests, CEO CLEAN), but could not produce real comparison verdicts because all 10 upstream builds failed. The pipeline code was kept despite 0/10 operational results because the comparison logic is correct — the failures are in Containerfile generation (Levels 1-3). Pattern: when building multi-layer verification systems, design each layer to be independently testable and keepable. A downstream layer that works but lacks inputs is a KEEP, not a REVERT — the fix is upstream.

## Multiple Review Rounds Catch Different Bug Classes
Discovered in buildroot-reconstructor experiment #003 (5-iteration review).
Structured code review (iterations 1-2) caught logic bugs (type guard, flag matching) and a direct security issue (shell injection). Final review (iterations 3-5) caught resource management (streaming response leak), a security vulnerability (zip-slip path traversal in JAR extraction), and correctness issues (CFR fallback tool_used reporting). Pattern: a single "CLEAN" pass is not enough — run at least two distinct review passes, ideally with different review focuses (logic/correctness vs. security/resource-management).

## Zip-Slip Path Traversal Is a Real Risk in Archive Extraction
Discovered in buildroot-reconstructor experiment #003 (final review iteration 1).
JAR files are ZIP archives. Extracting entries without validating that the resolved path stays within the target directory allows path traversal attacks (e.g., `../../etc/passwd`). Pattern: any code that extracts ZIP/JAR/tar entries must validate `os.path.realpath(target)` starts with the extraction directory. This is OWASP-listed but easy to miss in Python where `zipfile.extract()` doesn't protect against it by default.

## First-Pass CLEAN Code Reviews Correlate with Well-Scoped Strategy and Prior Art
Discovered in buildroot-reconstructor experiment #004.
Experiment #004 passed CEO code review on the first iteration with zero issues — contrasting with experiment #003 which required 5 iterations. The difference: #004 had a tightly scoped strategy (5 explicit deliverables), used an existing dependency (`dockerfile-parse`), and the Builder had seen 3 prior review rounds' worth of patterns to avoid. Pattern: when the strategy is precise and the Builder has internalized prior review feedback, first-pass CLEAN reviews become more likely. Projects that invest in archiving review patterns compound their code quality over cycles.

## 4/4 Keep Streak Signals Mature Execution — Shift to External Benchmarks
Discovered in buildroot-reconstructor experiment #004 (cycle 4).
After 4 consecutive KEEP verdicts with zero reverts across 4 cycles, the project shifted from self-referential validation (unit tests, Level 1-3 builds) to external benchmark validation (PNC ground truth). This is the right progression: once internal quality is stable, external accuracy measurements against independently known build environments reveal whether the system actually works — not just whether it passes its own tests. Pattern: when a project achieves 3+ consecutive KEEPs, consider whether the eval is still measuring something meaningful or has become a rubber stamp. Introducing an external benchmark (ground truth data, user feedback, production metrics) raises the bar.

## Build-Jdk-Spec Reflects Upstream CI, Not Build System Under Test
Discovered in buildroot-reconstructor experiment #005.
The JAR manifest's `Build-Jdk-Spec` header records which JDK the upstream CI used to build the artifact (e.g., GitHub Actions with JDK 21), not which JDK a reproducible build system (like PNC) uses. This caused a 0.325 accuracy score for commons-lang3 where PNC uses JDK 8 but the manifest says 21. Pattern: when validating build reconstruction against a known-good build system, treat manifest metadata as a hint about the upstream project's preferences, not as ground truth for the build system under test. For ground-truth validation, parse the build system's own configuration (e.g., PNC image names like `builder-rhel-7-j{JDK}`) as the authoritative JDK source.

## Pre-Flight Sanitization Beats Iterative Repair for Known Error Classes
Discovered in buildroot-reconstructor agentic research (issue #13).
When research identifies a dominant failure class with a deterministic fix (e.g., GHA `${{ }}` expressions causing 7/10 build failures), that fix should be applied as a pre-flight sanitization step BEFORE entering the iterative repair loop — not as something the agent "discovers" each time. Iterative LLM-based repair has an 18.9% single-shot success rate (CI-Repair-Bench); a regex strip has ~100% success rate for known patterns. Pattern: classify errors into "deterministic fix" (apply pre-flight) vs "requires exploration" (enter agent loop). This reduces the agent's search space and saves iteration budget for genuinely novel failures.

## OS Family Is Underspecified in Both Reconstruction and Ground Truth
Discovered in buildroot-reconstructor experiment #005.
PNC Containerfile parser returns empty string for `os_family` across all 3 tested packages, while buildroot reconstruction returns "unknown". Neither side extracts OS family reliably. Pattern: when building multi-dimension accuracy scorers, verify that BOTH the reconstruction AND the ground truth actually populate each dimension before weighting it. Scoring a dimension where both sides are empty/unknown inflates or deflates the score without measuring anything real.

## Easy Packages Solve Instantly — Iteration Budget Should Target the Hard Tail
Discovered in buildroot-reconstructor experiment #006 (agentic smoke test).
commons-lang3 solved in 1 iteration (reward=1.0) while micrometer-core and spring-security-core exhausted all 15 iterations without solving. The distribution is bimodal: packages where existing inference + pre-flight sanitization is sufficient solve immediately, while packages requiring novel repair strategies barely progress even with 15 iterations. Pattern: for agentic repair loops, don't set uniform iteration budgets. Instead, use early termination for easy packages (solved or plateau detected) and reallocate saved budget to harder packages. A "solve-or-plateau" check at iteration 3 would have saved 28 iterations across the 2 unsolved packages.

## G_t Progress Signal Needs Warm-Start to Avoid Cold-Start Mode Thrashing
Discovered in buildroot-reconstructor experiment #006 (security fix #3).
The AdaEvolve G_t progress signal initialized at 0.0, which is below the meta-shift threshold τ_S=0.02. On the first iteration, any tiny improvement triggered exploit mode, then the signal dropped back below τ_S causing immediate meta-shift. Pattern: exponential moving average signals used for mode switching must be warm-started at or above the lowest mode threshold to prevent oscillation before the signal has enough history to be meaningful. Warm-start at τ_M (the highest threshold) to begin in exploit mode and let the signal naturally decay to explore/meta-shift as needed.

## Security Review of Agent-Generated Shell Commands Is Non-Negotiable
Discovered in buildroot-reconstructor experiment #006 (security fixes #1 and #2).
The agentic reconstructor generates shell commands from user-controlled inputs (Maven coordinates like `org.apache.commons:commons-lang3:3.14.0` and file paths). Two injection vectors were found: (1) heredoc injection via unsanitized coordinates embedded in shell heredocs sent to remote SSH, (2) path traversal via user-controlled output paths escaping the working directory. Pattern: any agent that constructs shell commands from external inputs MUST have input validation at the boundary — validate coordinates against a strict regex, canonicalize and chroot-check all paths. This applies doubly when commands execute on remote hosts via SSH, where the blast radius of injection is larger.

## Major Architecture Experiments May Show Small Eval Score Deltas — That's Expected
Discovered in buildroot-reconstructor experiment #006 (KEEP, +0.0038).
This experiment added 8 new modules, 1703 lines, and a complete agentic repair loop — yet the eval score delta was only +0.0038. The eval rubric weights capability_surface at 12.5% and the new modules are primarily infrastructure (not directly growing the scored capability surface). Pattern: architecture-laying experiments that build new subsystems will show small eval deltas because the eval measures operational output, not architectural investment. The KEEP/REVERT decision should weight operational validation results (1/3 packages solved, end-to-end validated on real infra) alongside the eval score. Eval deltas become meaningful in follow-up experiments that leverage the new architecture to improve scored dimensions.

## CEO Review Scope Violations Often Involve Misplaced Files, Not Wrong Code
Discovered in buildroot-reconstructor experiment #007.
The CEO review found a root-level `packages_smoke.txt` duplicate that existed at both `./packages_smoke.txt` and `results/packages_smoke.txt`. The code was correct but the file placement violated the declared scope. Similarly, `guards.py` FIXED_SURFACES referenced the wrong path (`packages_smoke.txt` vs `results/packages_smoke.txt`). Pattern: when adding guard/allowlist systems that reference file paths, verify that the paths in the code match the project's actual file layout — especially when the same logical file could exist at multiple locations. A grep for the filename across the codebase during review catches these quickly.

## Knowledge Base Injection Should Be Additive, Not Replacement
Discovered in buildroot-reconstructor experiment #007 (builder.py meta_guidance threading).
The outer loop injects knowledge base patterns into the Builder's system prompt by PREPENDING `meta_guidance` before the existing `SYSTEM_PROMPT`. This additive approach preserves all existing Builder behavior while augmenting it with cross-package learning. Pattern: when an outer loop modifies an inner loop's behavior, prefer additive injection (prepend/append to prompts, add to context) over replacement (overwriting prompts). Replacement is fragile and can break established inner loop behaviors. The injection point should be clearly documented (in this case: `Builder.__init__(meta_guidance=...)` → `Builder._call_llm()` prepends to system prompt).

## 7/7 Keep Streak with Consistent Score Growth Validates Incremental Architecture Layering
Discovered in buildroot-reconstructor experiment #007 (KEEP, +0.0427, 7/7 streak).
The project followed a strict layering progression: core pipeline (#001-#003) → external validation (#004-#005) → agentic inner loop (#006) → intelligent outer loop (#007). Each layer built on the previous, and every experiment was kept with zero reverts. Score trajectory: 0.6433 → 0.8499 → 0.2662 → 0.5700 → 0.8012 → 0.8439. The dips (after #003) reflect eval rubric changes and scope expansion, not regressions. Pattern: for projects that build complex multi-layer systems (inference → verification → agentic repair → autonomous improvement), commit to one layer per experiment. Each layer may produce a small eval delta individually, but the compound effect across 7 experiments (+0.2006 net from baseline) validates the approach. The zero-revert streak suggests the 4-guard safety chain and CEO code review together are effective quality gates.

## Claude Code Subprocess Spawning: Use --bare + --append-system-prompt-file for Deterministic Agent Invocations
Discovered in buildroot-reconstructor issue #19 research (2026-06-13).
When spawning Claude Code agents as subprocesses in automated pipelines, use `--bare` (skips hooks, plugins, MCP servers, CLAUDE.md) combined with `--append-system-prompt-file` (preserves default tool guidance while adding domain context). This combination reduces per-invocation token overhead from ~50K to ~10-15K and makes invocations deterministic (no ambient state). For structured output (e.g., returning a typed hypothesis object), use `--json-schema` which provides post-hoc validation. Always use `--dangerously-skip-permissions` for headless pipelines, but pair with guards/allowlists as the safety layer rather than permission prompts.

## Parallel Research with Complementary Scopes Eliminates Overlap Waste
Discovered in buildroot-reconstructor issue #19 research (2026-06-13).
Running 3 researchers in parallel with distinct scopes (local codebase analysis, external CLI/API reference, architectural context mapping) produced 1102 lines of complementary analysis with zero overlap. Each researcher contributed findings the others couldn't: local traced specific call sites and data flows, external found CLI flags and implementation patterns, context mapped risks and phasing. Pattern: when researching a migration or architectural change, scope parallel researchers by information source (codebase internals, external docs, architecture/risk) rather than by topic area. Source-scoped researchers naturally avoid duplication because their inputs don't overlap.

## Infrastructure Migration Experiments Show Small Eval Deltas — Use Capability Unlock as the KEEP Signal
Discovered in buildroot-reconstructor experiment #008 (KEEP, +0.0014).
Migrating from raw API calls to Claude Code subprocess agents produced a +0.0014 score delta — nearly flat. This is expected: the migration doesn't change functional output, it changes the execution substrate. The KEEP decision was justified by capability unlock (agents now have tool access, iteration, structured output) rather than score improvement. Pattern: when evaluating infrastructure migrations (API → subprocess, monolith → modular, sync → async), don't require a significant eval delta. Instead, assess: (1) does the migration preserve existing behavior (no regression)? (2) does it unlock new capabilities that future experiments can exploit? A +0.00 delta with clean code review and new capabilities is a clear KEEP.

## 8/8 Keep Streak with Tool Restriction Guards Validates the Guard-Chain Safety Model
Discovered in buildroot-reconstructor experiment #008 (8th consecutive KEEP, zero reverts).
The project added `allowed_tools` restrictions to subprocess agents (e.g., Inner Builder gets Read/Edit/Bash but not WebSearch; Outer Researcher gets WebSearch but not Edit) alongside the existing 4-guard safety chain. After 8 experiments with zero reverts, the evidence strongly supports that the combination of (1) per-agent tool restrictions, (2) mutable surface guards, (3) CEO code review, and (4) eval scoring produces reliable quality gating. Pattern: for agentic systems that spawn sub-agents, restrict each agent's tool surface to the minimum needed for its task. This is defense-in-depth — even if the agent's prompt is wrong, tool restrictions bound the blast radius. Combined with file-level guards and code review, this produces a keep streak that validates the safety model.
