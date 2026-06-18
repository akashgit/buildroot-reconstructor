---
tags:
  - factory
  - patterns
source: factory-archivist
date: 2026-06-07
updated: 2026-06-17T23:30
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

## Node-Scoped Agent Pipelines: Constrain LLM to Structured Data, Not Free-Form Output
Discovered in buildroot-reconstructor experiment #009 (KEEP, 13 agents).
When an LLM agent has full control over a complex artifact (e.g., an entire Containerfile), prose contamination and hallucination degrade output quality — the 33.3% solve rate ceiling. Decomposing the pipeline into node-scoped agents that each review ONE structured field (JDK version, repo URL, git tag) with evidence-ranked candidates produces more reliable results than a single agent rewriting the whole artifact. Each agent uses a JSON schema for structured output and ranks candidates by evidence type (`direct_observation > ci_inference > cross_reference > historical_pattern > ecosystem_heuristic > default`). Pattern: for pipelines where an LLM augments a deterministic process, scope each agent to one decision point with structured output rather than giving it broad generative control. This is analogous to tool-use decomposition in agentic systems — many small, constrained tool calls outperform one large generative step.

## Failure Recovery Agents Should Be Tiered by Build Verification Level
Discovered in buildroot-reconstructor experiment #009 (3 failure agents: L2/L3/L4).
Post-build failure diagnosis requires different reasoning depth depending on which verification level failed. L2 failures (container build) are usually syntax/dependency issues diagnosable from build logs. L3 failures (source compilation) require understanding build tool configuration. L4 failures (artifact comparison) require deep bytecode/metadata analysis. Using a single failure agent for all levels wastes tokens on easy failures and lacks depth for hard ones. Pattern: tier failure recovery agents by severity/complexity level. Use cheaper models (Sonnet) for L2 failures where build logs are sufficient, and more capable models (Opus) for L3/L4 failures requiring cross-referencing multiple sources. Fire failure agents conservatively (iteration 0 only) to avoid cascading diagnosis loops.

## Multi-Round Code Review Catches Subtle Interaction Bugs That Single-Pass Misses
Discovered in buildroot-reconstructor experiment #009 (5 bugs across 3 review iterations).
The 5 bugs caught across 3 review rounds fell into distinct categories: (1) state bugs (stale reward signal, mutable class variable) caught in round 1, (2) output corruption (WORKDIR duplication, image tag doubling) caught in round 2 via partial benchmark, (3) control flow bugs (failure agent loop re-entry, false-positive logging) caught in round 3. No single review pass would have caught all 5 because rounds 2-3 were informed by running the code. Pattern: for agent-heavy code changes, plan at least 3 review iterations: (1) static code review for logic/state bugs, (2) run partial benchmark to surface output corruption, (3) re-review with runtime observations to catch control flow issues. The image agent `-jdk-jdk` suffix bug exemplifies defects only visible in actual agent output.

## 9/9 Keep Streak Validates Incremental Agent Layering as a Development Strategy
Discovered in buildroot-reconstructor experiment #009 (9th consecutive KEEP, zero reverts).
The project has maintained a perfect keep streak across 9 experiments spanning: core pipeline (#001-#003) → external validation (#004-#005) → agentic inner loop (#006) → intelligent outer loop (#007) → agent subprocess migration (#008) → node-scoped agents (#009). Each layer builds on the previous. The compound score trajectory (0.6433 → 0.845) with zero reverts validates that the combination of: (1) one-layer-per-experiment discipline, (2) 4-guard safety chain, (3) multi-round CEO code review, and (4) real E2E validation before verdict produces reliable quality gating at scale. The -0.001 noise in #009 demonstrates that KEEP decisions can correctly be made on code quality + partial validation even when full benchmark is incomplete.

## ACE-Style Append-Only Playbooks for Agent Learning Across Tasks
Discovered in buildroot-reconstructor issue #27 research (2026-06-16).
When agents make decisions that can fail at runtime (e.g., choosing a Docker image tag that Podman rejects), the pattern of append-only playbook entries with helpful/harmful counters (ACE framework, Zhang et al. 2025) provides persistent cross-task learning without retraining. Each agent reads its own scoped playbook file before acting. A separate AnalyzeAgent writes entries after failures, mapping build outcomes to the responsible agent's decision. This is the Generator-Reflector-Curator pattern applied to build pipelines. Pattern: for multi-agent pipelines where individual agents make decisions validated only by downstream execution, add an "analyst" agent that traces failures to responsible agents and writes scoped, append-only feedback. This closes the feedback loop without modifying the agents' core logic.

## Deterministic Fixes Should Be Applied Before Entering Agent Loops
Discovered in buildroot-reconstructor issue #27 research — Podman short-name resolution (2026-06-16).
Five of 12 L2 failures in the 31-package benchmark were caused by Podman rejecting bare Docker Hub image names (e.g., `eclipse-temurin:17-jdk` without `docker.io/library/` prefix). This is a deterministic bug with a one-line fix in `_map_distribution_to_image()`. The agent loop spent 15 iterations × 5 packages = 75 iterations trying to fix something that never needed LLM reasoning. Pattern: when post-mortem reveals a dominant failure class with a deterministic fix, apply it as infrastructure before the next agent experiment. Never let agents waste iteration budget rediscovering known fixes. This extends the earlier "Pre-Flight Sanitization" pattern to infrastructure-level fixes.

## Parallel Candidate Evaluation Beats Sequential When Evaluation Is Cheap Relative to Generation
Discovered in buildroot-reconstructor issue #27 research — CORAL paper (2026-06-16).
Node agents already generate ranked candidate lists (e.g., 3 possible Docker image tags), but `apply_best()` picks only the top-ranked one and discards the rest. CORAL (2025) shows that parallel exploration without coordination outperforms sequential when evaluation cost ≪ generation cost. For buildroot: agent candidate generation = ~30s, `podman build` evaluation = ~2-5 min. Running K=3 candidates in parallel costs ~1x wall-clock (not 3x) with 3x information gain. Pattern: when agents generate multiple candidates and evaluation is cheap (containerized builds, test runs, compilation), evaluate Top-K in parallel rather than picking the best by heuristic. The AnalyzeAgent gets richer comparative signal from K outcomes.

## L3→L4 Java Reproducibility Gaps Are Canonicalizable Metadata, Not Bytecode
Discovered in buildroot-reconstructor issue #27 research — Chains-Rebuild FSE 2026 (2026-06-16).
All 6 L3 failures in the 31-package benchmark show `bytecode_match=True` but `metadata_match=False`. The divergence is in MANIFEST.MF timestamps, `Created-By` headers, pom.properties build paths, and ZIP entry ordering. Sharma et al. (FSE 2026) show that Chains-Rebuild canonicalization converts 26.89% of artifacts to reproducible by stripping exactly these categories. Pattern: before investing in bytecode normalization (jNorm), check whether L3 failures are metadata-only — if `bytecode_match=True`, the fix is build-flag + comparison-side canonicalization (`-Dproject.build.outputTimestamp` + MANIFEST.MF stripping), not deeper analysis.

## E2E Benchmark Can Substitute for Unit Tests When Architecture Is Exploratory
Discovered in buildroot-reconstructor experiment #010 (CEO PROCEEDING despite missing tests, 2026-06-16).
The Builder implemented 5 new classes (AnalyzeAgent, RecipeStore, observe_top_k, _run_agent_loop, _evaluate_candidates) with zero unit tests. The CEO proceeded because: (1) the 31-package benchmark IS the integration test for all new code, (2) re-invoking the Builder for test additions risked another timeout, (3) the architecture is experimental and may change significantly after benchmark results. Pattern: for exploratory agent architecture experiments where the code path only executes inside an end-to-end pipeline, the full benchmark is a more meaningful validation than unit tests of individual components. However, this is a calculated trade-off — missing unit tests should be tracked as follow-up work once the architecture stabilizes. Do not generalize this to non-exploratory code where unit test coverage is standard.

## Early Termination Thresholds Must Be Calibrated Against Baseline Iteration Counts
Discovered in buildroot-reconstructor experiment #010 (REVERT, -19.4pp L4 rate, 2026-06-17).
An early termination threshold of `consecutive_no_improvement >= 3` caused 14/31 packages to regress by cutting iteration budget from 15 to ~4. Packages that previously reached L4 in 8-12 iterations were terminated at iteration 4. The threshold was set based on intuition, not empirical calibration against the baseline's iteration-to-solve distribution. Pattern: before adding early termination to an iterative optimization loop, analyze how many iterations successful solutions actually need. Set the threshold at or above the 75th percentile of successful iteration counts. If most successes happen at iteration 8-12, a threshold of 3 is catastrophically low. When in doubt, don't terminate — the baseline's "run all iterations" approach is a safer default than premature cutoff.

## Level-Based Improvement Tracking Is Too Coarse for Early Termination Decisions
Discovered in buildroot-reconstructor experiment #010 (REVERT, 2026-06-17).
The early termination counter tracked level changes (L1→L2→L3→L4) but not reward improvement within a level. A package improving from reward 0.05 to 0.14 within L1 registered as "no improvement" and was terminated. This is a 3x reward improvement being invisible to the termination logic. Pattern: when implementing early termination for multi-level optimization, track the FINEST-GRAINED progress signal available (reward, not level). A continuous improvement signal (reward) catches within-level progress that a discrete signal (level) misses. If reward is improving, the agent may be approaching a level transition — terminating at that point wastes the most valuable iterations.

## First Revert After Long Keep Streak Reveals Hidden Assumptions
Discovered in buildroot-reconstructor experiment #010 (first REVERT after 9 consecutive KEEPs, 2026-06-17).
Nine consecutive KEEPs created an assumption that the guard chain (code review + eval scoring + E2E) catches all regressions. Experiment #010's catastrophic -19.4pp regression was only visible via the full 31-package benchmark — the code review was CLEAN, the eval score was not yet computed, and the CEO proceeded based on code quality alone. Pattern: long keep streaks can foster overconfidence in quality gates. When the gates do not include a COMPARISON against the baseline's operational metrics (not just code quality), architectural changes that shift runtime behavior (like early termination) can pass code review but fail operationally. The lesson: for changes that alter loop control flow or iteration behavior, the benchmark IS the gate — code review alone is insufficient.

## Self-Referential Precheck False Positives
Discovered in buildroot-reconstructor experiment #012 (KEEP, force-kept, 2026-06-17).
The factory precheck system writes to `.factory/events.jsonl` during its own execution. When the precheck then scans for unexpected file modifications, it detects its OWN writes as a scope violation. Similarly, if `fixed_surfaces` is checked against an empty violation list, the check triggers vacuously. These are systemic false positives inherent to the precheck architecture, not experiment-specific issues. Pattern: when a quality gate system modifies state as part of its checking process, exclude its own artifacts from the check. Self-referential detection (the guard detecting its own traces) is a class of false positive that will recur on every experiment until the guard excludes its own write paths from the violation scan.

## Checkpoint-and-Restore Validated: Elitist Gate Produces +0.025 After Early Termination Catastrophe
Discovered in buildroot-reconstructor experiment #012 (KEEP, +0.025, 2026-06-17).
Experiment #010 showed that early termination (`consecutive_no_improvement >= 3`) causes catastrophic regression (-19.4pp). Experiment #012 validated the alternative: an elitist gate with patience counter that RESTORES from the best-known state instead of TERMINATING the run. The +0.025 score improvement confirms the hypothesis. Pattern: when an iterative optimization loop regresses, the correct response is checkpoint-restore (preserve best state, continue exploring from it), NOT early termination (kill the run entirely). Termination assumes the optimizer is stuck; restore assumes it just needs a better starting point. For stochastic LLM-based optimizers where each iteration is non-deterministic, restore is almost always correct because the same prompt can produce different (and better) output on retry from a good checkpoint.
