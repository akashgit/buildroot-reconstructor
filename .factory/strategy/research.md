# Research Report

## Project Summary

The buildroot-reconstructor is a Maven Central artifact build environment reconstructor that infers and generates Containerfiles from package metadata (POM, CI workflows, JAR manifests). It has a working **inner loop** (PR #15) — an agentic Observer→Builder→Evaluator→Analyzer cycle that iterates on a single Containerfile for one package — and a **dumb outer loop** that simply runs the inner loop per package and aggregates results.

**Current state:**
- Baseline solve_rate: 0.33 (1/3 on smoke test), 0.50 (5/10 on full L4 suite)
- commons-lang3 solves in 1 iteration; micrometer-core reaches L2 (reward=0.15); spring-security-core stuck at L1 (reward=0.05)
- The batch harness (`outer_loop.py`) is a sequential for-loop with no cross-package learning
- No knowledge base, no failure taxonomy aggregation, no strategy evolution

**Target:** Build an intelligent outer loop that iterates on the inner loop's *code* (prompts, error taxonomy, build strategies, templates) to increase solve_rate across many packages, borrowing patterns from AdaEvolve, AutoScientists, EvoX, and the factory's own review gates.

## Current Codebase Architecture

### What Exists (Inner Loop — 8 modules)

| Module | Role | Lines | Key Details |
|--------|------|-------|-------------|
| `agent/models.py` | Data models | ~140 | `BuildAttempt`, `DeadEndEntry`, `EvalResult`, `ProgressSignal` (AdaEvolve G_t) |
| `agent/observer.py` | Initial Containerfile | ~30 | Wraps existing `BuildrootOrchestrator.reconstruct()` |
| `agent/builder.py` | LLM mutation | ~190 | 3 modes: `refine` (exploit), `explore`, `fresh_start` (meta-shift). Uses `AnthropicVertex` with `claude-opus-4-6` |
| `agent/evaluator.py` | 4-level scoring | ~270 | L1 parse → L2 podman build → L3 JAR exists → L4 JAR match. Remote SSH to `rh-h100-01` |
| `agent/analyzer.py` | Error classification | ~200 | 18 regex-based error patterns, dead-end registry, fix suggestions. `FUNDAMENTAL_BLOCKERS` set |
| `agent/loop.py` | Inner loop orchestrator | ~180 | `run_inner_loop()`: G_t-driven mode switching (exploit/explore/meta_shift), max 15 iterations, confirmation build on reward≥0.98 |
| `agent/outer_loop.py` | Batch harness (dumb) | ~120 | `run_outer_loop()`: sequential for-loop, per-package results, summary.json |
| `cli/commands/agent_cmd.py` | CLI entry | ~55 | `buildroot agent <coord>` or `--batch packages.txt` |

### What's Missing (Outer Loop — spec requires 8 components)

1. **Failure Analyst** (`failure_analyst.py`) — aggregate failures across packages into a taxonomy with frequency counts, distinguish "exhausted" vs "under-explored"
2. **Knowledge Base** (`knowledge/`) — `patterns.md`, `failure_taxonomy.md`, `package_clusters.md`
3. **Outer Researcher** (`outer_researcher.py`) — web search for solutions to dominant failure modes
4. **Outer Strategist** (`outer_strategist.py`) — generate code-change hypotheses with J(S) tracking
5. **Outer Loop Orchestrator** — replace dumb for-loop with analyze→research→fix→re-evaluate cycle
6. **Guards & Gates** — mutable/fixed surface enforcement, test gate, monotonic improvement, leakage scan
7. **CLI extension** — `--outer-loop`, `--target-solve-rate`, `--max-cycles` flags
8. **Strategy Archive** (`knowledge/strategy_archive/`) — per-cycle YAML recording outcomes

### Key Integration Points

- **Inner loop receives knowledge injection:** The Builder's `SYSTEM_PROMPT` needs to accept an optional `meta_guidance` parameter containing relevant patterns from the knowledge base. Currently the system prompt is a module-level constant.
- **Inner loop results feed the Failure Analyst:** `LoopResult` already contains `attempts`, `dead_ends`, `status`, `best_reward` — sufficient for failure aggregation.
- **Evaluator is a fixed surface:** `evaluator.py` and `jar_comparator.py` must not be modified by the outer loop, preserving scoring integrity.

## External Research Findings

### AdaEvolve (arXiv:2602.20133) — Hierarchical Adaptive Optimization

**Key mechanism adopted in spec:** The G_t exponential-decay progress signal, already implemented in the inner loop's `ProgressSignal` class.

**New findings for the outer loop:**

1. **J(S) strategy scoring formula:** `J = (s_end - s_start) · log(1 + s_start) / √W` — the log term upweights improvements from higher baselines (harder to improve when already good). W is window size. This is directly specified in the current.md spec.

2. **Three-level adaptation hierarchy:**
   - Level 1 (local): exploration intensity modulation per iteration — **already implemented** as G_t exploit/explore/meta_shift in the inner loop
   - Level 2 (global): UCB bandit for resource allocation across populations — maps to **package scheduling** in the outer loop (which packages get more inner-loop budget)
   - Level 3 (meta): when G_t ≤ τ_M for ALL populations, trigger strategy-level changes — maps to the **Outer Strategist** proposing code changes to the reconstructor itself

3. **Stagnation thresholds (fixed across 185 problems):** τ_M = 0.12 (meta-guidance trigger), τ_S = 0.02 (spawn new populations). Our inner loop already uses these (τ_m=0.12, τ_s=0.02). The outer loop should apply analogous thresholds on solve_rate stagnation.

4. **Dynamic island spawning:** When all islands stagnate, spawn a new island with a random seed from the archive. Applicable to the outer loop: if all package-solving strategies stagnate, try an entirely different approach (e.g., switch from per-package repair to template-based generation).

**Implementation relevance:** The J(S) formula is straightforward to compute. The three-level hierarchy maps cleanly: Level 1 = inner loop (exists), Level 2 = package scheduling (out of scope per spec), Level 3 = outer loop code changes (the main deliverable).

Source: [AdaEvolve: Adaptive LLM Driven Zeroth-Order Optimization](https://arxiv.org/abs/2602.20133)

### AutoScientists (arXiv:2605.28655) — Self-Organizing Agent Teams

**Key mechanisms for the outer loop:**

1. **Stagnation detection:** "No improvement in the last 10 experiments" triggers team reorganization. For our outer loop: if ≥3 cycles produce J(S) < threshold, trigger a meta-shift from fixing individual error classes to proposing architectural changes.

2. **Dead-end registries per-team:** Teams maintain `D_k` with "failed experimental directions together with the tested axis, research direction, performance change, and rejection reason." Maps directly to our **strategy archive** — each cycle records what was tried, whether it worked, and why it failed.

3. **Cross-team visibility:** "All results, including failures, are visible to every agent across all teams." For our outer loop: the Failure Analyst and Outer Strategist should see all prior cycle outcomes, not just the most recent.

4. **Noise-aware validation:** Improvements within the "empirically measured noise band" require confirmation on a second seed. For our outer loop: improvements within a small delta (e.g., solve_rate +0.05 = one extra package on a 20-package suite) should be confirmed by re-running the batch to rule out flaky builds.

5. **Analyst-driven coverage audits:** Periodically check which research directions have never been tested. The Outer Strategist should consider which error classes have never been targeted by a code change.

**Implementation relevance:** The stagnation trigger (≥8 package failures concentrated in ≤3 error classes) from the spec is directly inspired by AutoScientists' "saturated search direction" concept. The dead-end registry pattern is already proven in the inner loop; extending it to the outer loop's strategy archive is natural.

Source: [AutoScientists: Self-Organizing Agent Teams for Long-Running Scientific Experimentation](https://arxiv.org/abs/2605.28655)

### EvoX (arXiv:2602.23413) — Meta-Evolution for Automated Discovery

**Key mechanisms for the outer loop:**

1. **Dual-loop architecture:** Inner loop evolves solutions under a fixed strategy; outer loop evolves the strategy itself when the inner loop stagnates. This is exactly our architecture: inner loop evolves Containerfiles (fixed code), outer loop evolves the inner loop's code.

2. **Strategy archive contents:** Tuples of `(strategy_code, population_state_descriptor, J_score)`. Maps to our strategy archive: `(code_diff, failure_taxonomy_snapshot, j_score)`.

3. **Demand-driven strategy switching:** "Strategy switching is demand-driven rather than periodic." The outer loop should not evolve code on a fixed schedule — it should trigger only when solve_rate stagnates.

4. **Strategy as code:** EvoX represents strategies as Python classes with `add` and `sample` methods, mutated by LLMs. Our outer loop similarly modifies Python code in `builder.py`, `analyzer.py`, etc. The LLM acts as the mutation operator on the reconstructor's source code.

5. **J(S) formula:** `J = (s_end - s_start) · log(1 + s_start) / √W` — identical to what the spec prescribes. The log term prevents strategies that improve from a low baseline from dominating the archive over strategies that improve from a higher baseline.

6. **Never reset the solution population on strategy switch:** This is critical — when the outer loop changes the reconstructor code, it should not discard prior knowledge base entries. Strategy evolution is additive.

**Implementation relevance:** The demand-driven (stagnation-triggered) model is more practical than periodic cycles for our case, since each inner-loop batch run is expensive (~40 minutes for 3 packages on rh-h100-01). The strategy-as-code pattern validates our approach of having the LLM modify Python source files directly.

Source: [EvoX: Meta-Evolution for Automated Discovery](https://arxiv.org/abs/2602.23413)

### AlphaEvolve (Google DeepMind) — LLM as Mutation Operator

**Key pattern:** Uses an ensemble of LLMs (Flash for throughput, Pro for quality) as mutation operators within an evolutionary loop. The program database uses MAP-elites island model. Code changes are expressed as SEARCH/REPLACE diffs.

**Relevance:** Our outer loop Builder should generate targeted diffs (not full file rewrites) to minimize blast radius. The ensemble pattern is less relevant since we're targeting one model (claude-opus-4-6), but the SEARCH/REPLACE diff format is a good output contract for the code-change LLM.

Source: [AlphaEvolve: A Gemini-powered coding agent for designing advanced algorithms](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/)

### Meta-Harness (arXiv:2603.28052) — Optimizing LLM Harnesses

**Key insight:** The performance of LLM systems depends not only on the model but on the *harness* (the code that determines what information to store, retrieve, and present). Meta-Harness optimizes harness code via end-to-end search, exposing full history through a filesystem.

**Relevance:** Our outer loop is literally optimizing a harness — the Builder's system prompt, the Analyzer's error patterns, the Observer's metadata extraction. Meta-Harness validates that this is a tractable optimization target and that full history exposure (via the strategy archive) is superior to compressed summaries.

Source: [Meta-Harness: End-to-End Optimization of Model Harnesses](https://arxiv.org/abs/2603.28052)

### LLMLOOP (ICSME 2025) — Iterative Feedback Loops

**Key pattern:** Five dedicated feedback loops for different error types (compilation, static analysis, test failures, etc.), each with its own prompt template. Dynamic temperature adjustment.

**Relevance:** Our Failure Analyst's taxonomy naturally creates per-error-class prompt templates for the Builder. Different failure modes may benefit from different prompts (e.g., JDK mismatch gets a version-focused prompt, multi-module gets a reactor-focused prompt).

Source: [LLMLOOP: Improving LLM-Generated Code and Tests](https://arxiv.org/html/2603.23613v1)

## Prior Knowledge (Archive)

The archive contains 42 source notes and extensive patterns. Key findings relevant to the outer loop:

1. **GHA expression sanitization fixes 7/10 failures** (maven-build-error-taxonomy.md) — the inner loop's Builder already has `sanitize_gha_expressions()`, but the pre-flight sanitization insight suggests the Failure Analyst should distinguish "known deterministic fix" from "requires LLM exploration."

2. **Dead-end registries are essential** (dead-end-registries-failure-memory.md) — 2-failure threshold, memory pointer pattern, context poisoning risk. Already implemented in inner loop; needs to be extended to outer loop strategy archive.

3. **Easy packages solve instantly** (patterns.md) — "commons-lang3 solved in 1 iteration." The outer loop should not waste cycles analyzing already-solved packages. Early termination + budget reallocation is a proven pattern.

4. **Pre-flight sanitization beats iterative repair** (patterns.md) — for known error classes with deterministic fixes, apply pre-flight rather than letting the agent discover the fix each time. The Failure Analyst should classify which failures are "deterministic-fixable" vs "exploration-required."

5. **Build-Jdk-Spec reflects upstream CI, not PNC** (patterns.md) — JDK version inference is a known weakness. The Outer Researcher should specifically investigate JDK version resolution for packages that fail with compilation/jdk_mismatch errors.

6. **G_t needs warm-start** (patterns.md) — cold-start at 0.0 causes mode thrashing. Already fixed in the inner loop; the outer loop should similarly warm-start any analogous progress tracking.

## Recommended Focus Areas

### 1. Failure Analyst as the Foundation (highest impact, lowest risk)

The Failure Analyst is the single highest-leverage component — without it, the outer loop has no signal to guide code changes. It's also the simplest to implement: read batch results, aggregate error classes, compute frequencies. No LLM calls needed.

**Expected impact:** Enables all downstream components (Researcher, Strategist, Builder). Without it, nothing else works.

### 2. Knowledge Base with Inner Loop Injection (second-highest impact)

The knowledge base is the cross-trial learning mechanism. Even without the full outer loop, injecting learned patterns into the Builder's prompts should improve solve_rate on the next batch run.

**Expected impact:** If micrometer-core fails with a consistent error class across iterations, and the knowledge base captures that "micrometer uses JDK 11 + spring-boot-maven-plugin," the Builder starts with better context on the next run.

### 3. Guards & Gates Before Code Mutation (safety prerequisite)

This must be in place before the outer loop modifies any code. The surface guard, test gate, monotonic check, and leakage scan are all deterministic — no LLM calls, no ambiguity.

**Expected impact:** Prevents regressions, protects fixed surfaces, ensures code quality.

### 4. Outer Strategist with J(S) Tracking (the intelligence)

The Strategist generates hypotheses — this is where the cross-paper patterns (AdaEvolve J(S), EvoX strategy archive, AutoScientists stagnation triggers) converge. The J(S) formula from AdaEvolve/EvoX provides a principled way to score strategies across cycles.

**Expected impact:** Targets the dominant failure mode with a specific code change hypothesis, preventing the outer loop from random-walking through the code.

### 5. Outer Researcher (optional enhancement)

The Outer Researcher adds depth but isn't strictly necessary for the first few cycles. The LLM's built-in knowledge of Maven build patterns is sufficient for the most common failure modes (JDK mismatch, multi-module, missing plugins).

**Expected impact:** Becomes important when the outer loop exhausts the LLM's built-in knowledge and needs external sources (Maven plugin docs, JDK compatibility tables).

## Recommended Implementation Approach

### Phase 1: Failure Analyst + Knowledge Base (foundation)

Build bottom-up — the Failure Analyst and Knowledge Base are prerequisites for everything else.

1. **`failure_analyst.py`**: Read all per-package results from a batch run, aggregate error classes with frequency counts, classify as "exhausted" vs "under-explored" based on dead-end registry state and iteration count.

2. **Knowledge base directory** (`knowledge/`): Create `patterns.md`, `failure_taxonomy.md`, `package_clusters.md` as Markdown files. The Failure Analyst writes to `failure_taxonomy.md`; the outer loop's knowledge updater writes to `patterns.md` after successful cycles.

3. **Inner loop integration point**: Add an optional `meta_guidance: str` parameter to `Builder.__init__()` or to the `_call_llm()` method that gets prepended to the system prompt. This is the injection vector for knowledge base content.

### Phase 2: Guards & Gates (safety rails before code mutation)

Before allowing the outer loop to modify code, establish the safety infrastructure.

1. **Surface guard**: A function that takes a git diff and returns True/False based on whether only mutable surfaces were touched. Simple: parse `git diff --name-only` against allowlist.

2. **Test gate**: Run `pytest tests/test_agent*.py` and `ruff check`. Return pass/fail.

3. **Monotonic check**: Compare solve_rate_after vs solve_rate_before and historical best. Reject if regression.

4. **Leakage scan**: Grep the diff for specific Maven coordinates, hardcoded version numbers, or package-specific conditionals. Heuristic but effective.

### Phase 3: Outer Researcher + Outer Strategist (the intelligence layer)

1. **`outer_researcher.py`**: Takes the dominant failure mode from the Failure Analyst, uses LLM knowledge + archive to research solutions. Outputs a structured research report with specific, actionable recommendations.

2. **`outer_strategist.py`**: Takes the Failure Analyst's taxonomy + Researcher's findings, generates hypotheses. Each hypothesis names specific files to modify, estimates impact, and is scoped to one coherent change. J(S) tracking across cycles.

### Phase 4: Builder (code mutation) + Orchestrator (main loop)

1. **Outer loop Builder**: An LLM call that takes a hypothesis + the current source code of the target files and produces modified source code. Uses the same `AnthropicVertex` client.

2. **Outer loop Orchestrator** (replace `outer_loop.py`): The main cycle:
   - Run batch → Failure Analyst → Researcher → Strategist → Builder → apply changes → Guards → re-run batch → Verdict → update KB → loop

### Phase 5: CLI + Strategy Archive

1. Extend CLI with `--outer-loop`, `--target-solve-rate`, `--max-cycles` flags.
2. Per-cycle YAML in `knowledge/strategy_archive/`.

## Key Technical Decisions and Tradeoffs

### 1. LLM-driven code mutation vs. manual patch templates

**Decision:** Use LLM to generate code changes to the reconstructor's source files, guided by the Outer Strategist's hypothesis.

**Tradeoff:** LLM mutation is flexible but unpredictable. Manual patch templates are reliable but can't discover novel improvements. The guards and gates (surface check, test gate, monotonic check) provide the safety net that makes LLM mutation acceptable.

**Recommendation:** LLM mutation with strict guards. This is the approach validated by EvoX, AlphaEvolve, and Meta-Harness.

### 2. Full file rewrite vs. targeted diffs

**Decision:** Have the outer loop Builder produce full file content (easier for the LLM) and validate via `git diff` against the original.

**Rationale:** The mutable files (builder.py=190 lines, analyzer.py=200 lines, loop.py=180 lines) are small enough for full-file rewrite. Targeted diffs (SEARCH/REPLACE blocks) require more complex prompt engineering and output parsing. AlphaEvolve uses diffs, but our files are much smaller than their targets.

**Recommendation:** Start with full file content for simplicity. Validate via `git diff` against the pre-change version. If the diff touches fixed surfaces or introduces leakage, revert.

### 3. Serial vs. parallel batch runs

**Decision:** Keep sequential for now.

**Rationale:** The 3-package smoke test takes ~40 minutes. Parallelism adds complexity (SSH connection limits, podman image conflicts) without changing the core algorithm. Parallel execution is explicitly out of scope (Phase 4 UCB1 bandit scheduling).

### 4. Knowledge base injection granularity

**Decision:** Selective injection based on package type.

**Rationale:** The Observer identifies package characteristics (Spring Boot, multi-module, standalone JAR, etc.), and only the matching patterns.md section is injected into the Builder's system prompt. This follows AdaEvolve Level 3 — external knowledge injection when progress drops — without polluting the context window.

### 5. Outer Researcher: LLM knowledge + archive first

**Decision:** Start with LLM's training knowledge + the archive. No live web search initially.

**Rationale:** The dominant failure modes (JDK mismatch, multi-module, missing plugin) are well-known Maven build issues within the LLM's training data. The archive has 42 source notes covering Maven build patterns. Live web search adds latency and complexity without proportional benefit for the first few cycles.

### 6. Stagnation detection: dual triggers

**Decision:** Use both J(S) < threshold for 3 consecutive cycles AND ≥8 failures concentrated in ≤3 error classes.

**Rationale:** These are complementary signals. J(S) catches slow stagnation (small improvements each cycle but no breakthrough). Concentrated failures catch systemic issues early (most packages failing the same way). Both trigger the Strategist to shift from error-class fixes to architectural changes.

### 7. Noise-aware validation threshold

**Decision:** Require confirmation re-run when improvement is ≤1 package on the test suite.

**Rationale:** On a 3-package suite, any improvement is ≥33% — noise is unlikely. On a 10+ package suite, a single package flip could be a flaky build. Confirm by re-running just the affected package(s), not the entire batch.

## Potential Pitfalls to Avoid

### 1. Ground truth leakage in code changes

The outer loop must not embed package-specific answers (e.g., `if "micrometer" in coordinate: jdk = 11`). This won't generalize.

**Mitigation:** Leakage scan greps the diff for Maven coordinate strings, specific artifact names, or hardcoded version numbers. Test on a held-out package set.

### 2. Evaluator modification (forbidden)

If the outer loop accidentally modifies `evaluator.py` or `jar_comparator.py`, scoring integrity is lost.

**Mitigation:** Surface guard + explicit `git diff` check on fixed surface files after every code change.

### 3. Context window limits in the outer loop Builder

The Builder needs hypothesis + source code + failure taxonomy + strategy archive history. This can exceed context limits.

**Mitigation:** Memory pointer pattern. Pass only the target file(s), top-3 error classes, and last 3 archive entries. Don't pass the entire codebase.

### 4. Oscillating code changes

Fix A breaks B, fix B breaks A → loop oscillates.

**Mitigation:** Monotonic improvement gate. Strategy archive records both changes and outcomes, so the Strategist avoids generating the inverse of a previously reverted change.

### 5. Expensive feedback loop

Each outer cycle = 2 full batch runs (before + after). On the smoke test, that's ~80 minutes per cycle.

**Mitigation:** Start with 3-package smoke test. Use early termination for solved packages. Consider targeted re-runs (only re-run packages in the affected error class).

### 6. Strategy archive growing unboundedly

**Mitigation:** Cap at 20 cycles. Older entries are summarized (keep hypothesis, J score, verdict; drop the full diff). Strategist receives last 5 entries in full + summary table of older entries.

### 7. Builder prompt injection via error logs

Build error logs may contain adversarial content.

**Mitigation:** Error summaries already truncated to 500 chars. Failure Analyst and Researcher use structured data (error class strings, frequency counts) rather than raw log content.

## References

- [AdaEvolve: Adaptive LLM Driven Zeroth-Order Optimization](https://arxiv.org/abs/2602.20133) — J(S) formula, G_t signal, three-level hierarchy, stagnation thresholds
- [AutoScientists: Self-Organizing Agent Teams](https://arxiv.org/abs/2605.28655) — Stagnation detection, dead-end registries, cross-team visibility, noise-aware validation
- [EvoX: Meta-Evolution for Automated Discovery](https://arxiv.org/abs/2602.23413) — Dual-loop architecture, strategy archive, demand-driven switching, J(S) formula
- [AlphaEvolve (Google DeepMind)](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/) — LLM as mutation operator, SEARCH/REPLACE diffs, MAP-elites population
- [Meta-Harness: End-to-End Optimization of Model Harnesses](https://arxiv.org/abs/2603.28052) — Harness-as-optimization-target, full history exposure via filesystem
- [LLMLOOP: Improving LLM-Generated Code and Tests](https://arxiv.org/html/2603.23613v1) — Per-error-type feedback loops, dynamic temperature
- [OpenEvolve (HuggingFace)](https://huggingface.co/blog/codelion/openevolve) — Open-source AlphaEvolve implementation
- [AutoScientists GitHub](https://github.com/mims-harvard/AutoScientists) — Reference implementation
