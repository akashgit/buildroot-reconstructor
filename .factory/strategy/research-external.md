# External Research — Issue #27 Agent Architecture Fix

## Research Scope

Targeted research for issue #27's five proposed changes: AnalyzeAgent with ACE-like playbooks, Top-K parallel candidate builds, tiered recipe store, spec overrides persistence, and Podman/reproducibility fixes.

---

## 1. ACE-Like Playbook Patterns (AnalyzeAgent Design)

### ACE Framework (Zhang et al., 2025) — Generator-Reflector-Curator

The [ACE framework](https://arxiv.org/abs/2510.04618) from Stanford/SambaNova/Berkeley is the closest academic match to the proposed AnalyzeAgent design. It uses three components unified by an evolving "Context Playbook":

- **Generator**: Reads playbook rules before acting (= node agents reading `.factory/playbooks/`)
- **Reflector**: Compares output against ground truth, identifies strategic failures (= AnalyzeAgent diagnosing build failures)
- **Curator**: Decides whether to create a new "Delta Rule" or merge with existing (= AnalyzeAgent writing DO/DON'T entries)
- **Pruner**: Periodically synthesizes redundant rules into "Master Rules" (= future optimization for playbook convergence)

**Key design detail from ACE**: Playbook entries are append-only with helpful/harmful counters that increment over time — content is never rewritten, only counters change. New insights are deduplicated via cosine similarity (0.8 threshold). This directly validates issue #27's proposed format:
```
- [img-001] harmful=1 :: Do NOT emit bare Docker Hub names...
```

**Relevance**: The AnalyzeAgent IS the Reflector+Curator combined. Node agents ARE the Generator. The playbook files ARE the Context Playbook. Issue #27's design maps 1:1 to the ACE architecture, with the addition that the "ground truth" is the build outcome (L1-L4 level), not a labeled dataset.

**Source**: [ace-playbook implementation](https://github.com/jmanhype/ace-playbook) shows append-only delta rules with helpful/harmful/neutral labels and FAISS-based semantic deduplication. For our use case, exact-match dedup by agent+rule-hash is simpler and sufficient — the playbook entries are structured, not free-text.

### Self-Evolving Agents (OpenAI Cookbook)

The [Self-Evolving Agents cookbook](https://developers.openai.com/cookbook/examples/partners/self_evolving_agents/autonomous_agent_retraining) uses a four-step Generate→Evaluate→Optimize→Accept loop with versioned prompts. Key pattern: `collect_grader_feedback()` translates failures into structured reasoning that feeds the optimizer. This maps to AnalyzeAgent translating build logs into playbook entries.

Their `VersionedPrompt` class tracks full history with scores per version. For our playbooks, the equivalent is the `helpful`/`harmful` counters — they track whether a rule is working over time without storing full version history.

### AgentDebug (Sep 2025) — Failure Taxonomy

[AgentDebug](https://arxiv.org/abs/2509.25370) provides a modular failure taxonomy (memory, reflection, planning, action, system-level) and a debugging framework that "isolates root-cause failures and provides corrective feedback, enabling agents to recover with up to 26% relative improvement." This validates the AnalyzeAgent's core function: connecting build failures to the responsible node agent (root cause isolation) and writing targeted feedback.

### Build-bench — Iterative Build Repair

[Build-bench](https://arxiv.org/pdf/2511.00780) caps tool invocations at 20 per iteration and repair iterations at 3 per package. Each iteration rebuilds the prompt using (1) updated build log, (2) latest package state, (3) historical modifications. This three-input pattern directly maps to AnalyzeAgent's inputs: build logs, current spec, and accumulated playbook entries.

### Meta's Engineering Agent (July 2025)

[Meta's production repair system](https://arxiv.org/pdf/2507.18755) uses Llama with ReAct, averaging 11.8 feedback iterations for a 42.3% solve rate. Key pattern: a separate LLM-as-Judge ensures patch quality before acceptance. For issue #27, the evaluation step (L1-L4 scoring) already serves as the automated judge — no separate judge agent needed.

### LLMLOOP (ICSME 2025) — Per-Error-Type Feedback

Our archive already covers [LLMLOOP](https://arxiv.org/html/2603.23613v1): five dedicated feedback loops per error type with dynamic temperature adjustment. This validates that the AnalyzeAgent should write error-class-specific playbook entries (e.g., image resolution rules go to `image_agent.md`, build command rules go to `build_cmd_agent.md`), not generic catch-all rules.

**Synthesis for AnalyzeAgent design**:
1. Append-only rules with helpful/harmful counters (ACE pattern) — validated
2. Per-agent playbook files scoped to one decision domain (LLMLOOP pattern) — validated
3. Root cause → responsible agent mapping (AgentDebug pattern) — validated
4. Three-input prompt: build logs + current state + historical rules (Build-bench pattern) — validated
5. No separate judge needed; L1-L4 scoring IS the judge (Meta pattern) — simplification confirmed

---

## 2. Multi-Candidate Parallel Builds (Top-K Selection)

### MAP-Elites / Quality-Diversity Search

[MAP-Elites](https://arxiv.org/html/2303.06137v2) maintains a grid of elite solutions across behavioral dimensions. When a new candidate outperforms the existing occupant of a cell, it replaces it. The [MEMES algorithm](https://dl.acm.org/doi/10.1145/3638529.3654089) (GECCO 2024) runs up to 100 simultaneous evolution processes on a single GPU, demonstrating that parallel candidate evaluation at scale is tractable.

**Relevance to Top-K builds**: Issue #27's approach is simpler than MAP-Elites — it's a straightforward best-of-K selection where K candidates are evaluated in parallel and the highest-scoring one wins. MAP-Elites' behavioral dimensions aren't needed because our fitness function (L1<L2<L3<L4) is a single ordinal dimension, not a multi-dimensional quality-diversity space.

### AlphaEvolve (Google DeepMind)

Our archive covers AlphaEvolve's [MAP-Elites island model](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/). Key insight for Top-K: AlphaEvolve uses an ensemble of LLMs (Flash for throughput, Pro for quality) as mutation operators. For buildroot, node agents already produce ranked candidates — Top-K simply evaluates more of them instead of discarding all but rank-1.

### CORAL (2025) — Parallel Agent Exploration

[CORAL](https://xuquant.com/en/posts/foundation-models/coral-autonomous-multi-agent-evolution/) uses N agents exploring in parallel without message passing, with heartbeat-based interventions. It exceeds fixed evolutionary baselines by 3-10x. The key insight: parallel exploration without coordination outperforms sequential exploration with coordination when evaluation is cheap relative to generation. This applies to our case — `podman build` (evaluation) is ~2-5 minutes, while agent candidate generation is ~30 seconds. Running K=3 builds in parallel costs ~1x wall-clock time, not 3x.

**Synthesis for Top-K design**:
1. Best-of-K with parallel evaluation is the right pattern (simpler than MAP-Elites, sufficient for single-dimension fitness)
2. K=3 is a reasonable default — CORAL shows diminishing returns past 5-10 parallel candidates for constrained search spaces
3. Dead-end tracking of losing candidates (already proposed in issue #27) prevents re-exploration
4. The AnalyzeAgent gets richer signal from K outcomes than from 1 — comparative analysis ("A failed because X, B succeeded because Y") produces better playbook entries

---

## 3. Reproducible Java Builds (L3→L4 Conversion)

### Causes and Canonicalization (Sharma et al., FSE 2026)

The definitive paper is ["Causes and Canonicalization of Unreproducible Builds in Java"](https://arxiv.org/abs/2504.21679) (Sharma, Baudry, Monperrus — KTH). They identify **six root causes** of unreproducibility:

| Root Cause | Key Artifacts Affected | Canonicalization Tool |
|---|---|---|
| 1. Build manifests | MANIFEST.MF (`Built-By`, `Build-Jdk`, `Created-By`), pom.properties | Chains-Rebuild: strip env-dependent attrs |
| 2. SBOM variations | CycloneDX `serialNumber`, `timestamp` | Open problem |
| 3. Filesystem | File permissions, ordering, sizes, embedded paths | OSS-Rebuild: normalize ZIP metadata |
| 4. JVM bytecode | Constant pool ordering, lambda naming, synthetic accessors | jNorm: Jimple IR transformation |
| 5. Versioning properties | git.properties (tag counts, builder info, branch) | Chains-Rebuild: strip git.properties |
| 6. Timestamps | 10+ locations: properties, docs, scripts, MANIFEST.MF | Chains-Rebuild: strip timestamp patterns |

**Results**:
- OSS-Rebuild alone: 9.48% → reproducible
- Chains-Rebuild (enhanced): 24.72% → reproducible
- jNorm (bytecode only): 29.7% of bytecode artifacts
- **Combined**: 26.89% of all artifacts become reproducible

**Critical insight for issue #27's L3→L4 gap**: All 6 L3 failures show `bytecode_match=True, structural_match=False, metadata_match=False`. This means bytecode is already identical — the divergence is in categories 1, 3, 5, and 6 (manifests, filesystem, versioning, timestamps). These are ALL canonicalizable by Chains-Rebuild without needing jNorm.

**Actionable canonicalization steps for L3→L4**:
1. Strip `Built-By`, `Build-Jdk`, `Created-By`, `Bnd-LastModified`, `Build-Timestamp` from MANIFEST.MF
2. Remove pom.properties entirely (contains non-deterministic timestamp)
3. Strip git.properties if present
4. Normalize ZIP entry ordering and timestamps
5. Set `project.build.outputTimestamp` in Maven build command: `-Dproject.build.outputTimestamp=1980-01-01T00:00:00Z`

### Maven Reproducible Builds Guide

[Apache Maven's guide](https://maven.apache.org/guides/mini/guide-reproducible-builds.html) recommends setting `<project.build.outputTimestamp>` in the POM to fix archive entry timestamps. The [Maven Artifact Plugin](https://maven.apache.org/plugins/maven-artifact-plugin/reproducible.html) can diagnose reproducibility issues.

### Reproducible Build Maven Plugin

The [zlika/reproducible-build-maven-plugin](https://zlika.github.io/reproducible-build-maven-plugin/) strips non-deterministic data from JAR archives during the build. It handles: ZIP timestamps, MANIFEST.MF ordering, and pom.properties timestamps. This is a build-time solution (add to the Maven command) rather than a post-build canonicalization.

### Chains-Rebuild Canonicalization Detail

From the [full paper](https://arxiv.org/html/2504.21679v1), Chains-Rebuild applies these specific canonicalization steps:

- **MANIFEST.MF**: Removes `Built-By` (username), `Os-Version`, `Bnd-LastModified`. Fixes attribute value ordering (sorts `Export-Package` values alphabetically).
- **pom.properties**: Removes the entire file (non-deterministic timestamps and property ordering).
- **git.properties**: Strips files containing divergent tag counts, builder hostnames, branch names.
- **Archive-level**: Canonicalizes ZIP file metadata including entry order, modification timestamps, compression algorithms, and encoding.

**jNorm limitations** (relevant because bytecode already matches for our L3 cases):
- Cannot normalize field/method ordering, lambda naming, implicit visibility modifiers
- Cannot reconcile invokevirtual vs. invokeinterface changes across JDK versions
- Cannot handle absolute file paths or most embedded timestamps
- Success rate drops from 99% (same-machine evaluation) to 29.7% (cross-machine evaluation)

### Cross-Ecosystem Benchmarks (ICSE 2025)

[Benedetti et al.](https://nesbitt.io/2026/02/24/reproducible-builds-in-language-package-managers.html) tested 4,000 packages per ecosystem: Cargo and npm score 100% reproducible; PyPI only 12.2%; Java/Maven is in the middle. The gap is primarily timestamps and metadata, not bytecode.

**Synthesis for L3→L4 strategy**:
1. **Build-time fix**: Add `-Dproject.build.outputTimestamp=1980-01-01T00:00:00Z` to Maven commands — this is the single highest-impact change
2. **Post-build canonicalization**: Strip/normalize MANIFEST.MF and pom.properties before JAR comparison — catches what `outputTimestamp` misses
3. **Comparison pipeline enhancement**: The existing 4-layer comparison (structural → metadata → bytecode → diffoscope) should normalize timestamps BEFORE comparison, not after
4. **Expected impact**: If bytecode already matches for all 6 L3 packages, canonicalization of metadata/timestamps should convert most or all to L4

---

## 4. Podman vs Docker Runtime Differences

### Short-Name Resolution

[Podman's documentation](https://docs.podman.io/en/latest/markdown/podman-pull.1.html) and [Red Hat's blog](https://www.redhat.com/en/blog/container-image-short-names) explain the core issue:

- **Docker**: `eclipse-temurin:17-jdk` → implicitly resolves to `docker.io/library/eclipse-temurin:17-jdk`
- **Podman**: Requires either (a) explicit `docker.io/library/` prefix, (b) configured `unqualified-search-registries` in `/etc/containers/registries.conf`, or (c) a short-name alias

**Three short-name modes** ([registries.conf](https://github.com/containers/podman/discussions/25075)):
1. **Enforcing** (default): Prompts user to select registry if no alias exists. **Fails without TTY** — this is exactly our containerized build environment
2. **Permissive**: Tries all search registries in order, no alias recorded
3. **Disabled**: Tries all registries, no prompting

**The fix is definitive**: Always emit fully-qualified image names (`docker.io/library/` for Docker Hub official images, `docker.io/<user>/` for user images). This is:
- A deterministic fix in `_map_distribution_to_image()` or equivalent
- Zero-cost, no behavioral change for Docker users
- Eliminates 5 of 12 L2 failures immediately

**Security consideration**: [Red Hat warns](https://www.redhat.com/en/blog/container-image-short-names) that short names risk "hitting squatted registry namespaces" — an attacker could register the same image name on a different registry. Fully-qualifying is the security-recommended approach regardless.

### Known Podman Bugs

[Issue #13234](https://github.com/containers/podman/issues/13234) reports that even fully-qualified names sometimes fail with short-name errors in docker-compose contexts. The workaround is to ensure `registries.conf` exists with `unqualified-search-registries = ["docker.io"]`, but the proper fix is fully-qualifying in the Containerfile itself, which our pipeline controls.

### Containerfile Considerations

When generating Containerfiles for Podman:
- `FROM docker.io/library/eclipse-temurin:17-jdk` — always fully qualify in FROM
- For multi-stage builds, the alias (`AS builder`) works the same in both runtimes
- `RUN` commands that pull images (e.g., `docker pull` within a build) also need fully-qualified names
- Consider adding `unqualified-search-registries = ["docker.io"]` to the container's `/etc/containers/registries.conf` as a belt-and-suspenders approach

---

## 5. Agent Feedback Loops and Learning from Build Failures

### RepairAgent (ICSE 2024)

[RepairAgent](https://arxiv.org/pdf/2403.17134) proceeds in multiple cycles where "each cycle represents one round of interaction with the LLM agent, and the input to the model is updated based on tool calls invoked by the LLM in previous cycles." It fixes 39 bugs not fixed by any baseline. The multi-cycle structure with per-cycle prompt updates maps directly to AnalyzeAgent's per-iteration feedback loop.

### Iterative Generative Optimization (March 2026)

A [recent paper](https://arxiv.org/html/2603.23994) distinguishes two loop types:
- **Within-task loops**: Optimize one task across iterations (= our per-package iteration loop)
- **Cross-task loops**: Accumulate experience across tasks (= playbook entries persisting across packages and runs)

Issue #27's AnalyzeAgent operates at BOTH levels: within-task (spec_overrides persist across iterations for one package) AND cross-task (playbook entries persist across packages and runs). This dual-loop architecture is identified as the key differentiator for "continual learning through repeated trial and error."

### Dead-End Registries (Archive)

Our archive covers the [Reflexion/ExpeL](https://arxiv.org/abs/2309.16543) episodic memory pattern and DebounceHook for preventing repeated dead ends. The proposed `dead_ends.yaml` for losing Top-K candidates follows this pattern exactly. The 2-failure threshold before registry entry (from our existing design) balances false-positive risk against wasted iterations.

### Context Management (Mini-SWE-Agent)

Our archive notes that context selection prevents prompt growth — only relevant error lines, not full logs. The AnalyzeAgent should receive summarized build logs (key error lines), not full logs, to stay within the $2 budget. The existing `build_log_summary` field (≤500 chars) provides this.

---

## Prior Knowledge (Archive) — Key Patterns Relevant to Issue #27

| Archive Source | Key Finding | Relevance |
|---|---|---|
| node-agents-benchmark-failure-analysis | 24/27 failing packages are addressable by agents; realistic target 26-48% L4 | Sets the benchmark target for issue #27 |
| java-build-nondeterminism-taxonomy | Timestamps are dominant (rank 1-3, 5, 7); strip before comparison | Directly informs L3→L4 canonicalization |
| jar-comparison-layered-strategy | 4-layer comparison: structural → metadata → bytecode → diffoscope | Canonicalization should apply BEFORE layer 2 |
| llmloop-iterative-feedback | Per-error-type feedback loops with tailored prompts | Validates per-agent playbook scoping |
| alphaevolve-llm-mutation-operator | MAP-Elites island model, SEARCH/REPLACE diffs | Validates parallel candidate approach |
| codex-iterative-repair | Review→Repair→Validation phase separation | Validates AnalyzeAgent→NodeAgent→Build separation |
| dead-end-registries-failure-memory | Episodic memory prevents repeated dead ends; 2-failure threshold | Validates dead_ends.yaml for losing K candidates |
| maven-build-error-taxonomy | GHA expression sanitization fixes 7/10 failures as pre-flight | Pre-flight fixes are separate from agent feedback |
| adaevolve-outer-loop-hierarchy | Three-level adaptation: local/global/meta | AnalyzeAgent = Level 1 (local); playbooks = Level 2 (global) |

---

## Recommended Implementation Priorities

Based on external research and archive findings:

### P1: Podman fully-qualified image names (deterministic fix)
**Impact**: Fixes 5/12 L2 failures immediately. Zero agent cost.
**Evidence**: Podman docs confirm this is the only reliable approach. Security-recommended by Red Hat.
**Implementation**: Single function change in image resolution to always prepend `docker.io/library/`.

### P2: Top-K parallel candidate builds
**Impact**: Multiplicative improvement — each iteration explores K paths instead of 1.
**Evidence**: CORAL shows 3-10x improvement from parallel exploration. MAP-Elites/MEMES validate parallel candidate evaluation at scale.
**Implementation**: `apply_best()` → `apply_top_k()`, parallel `podman build`, pick highest L-level winner.
**Risk**: K=3 is conservative and validated; K>5 has diminishing returns in constrained spaces.

### P3: AnalyzeAgent with ACE-like playbooks
**Impact**: Closes the feedback loop — agents learn from failures they never saw.
**Evidence**: ACE framework validates Generator-Reflector-Curator with append-only playbooks. AgentDebug shows 26% improvement from targeted corrective feedback. Build-bench validates three-input prompt structure.
**Implementation**: AnalyzeAgent as Reflector+Curator, node agents as Generator, per-agent playbook files with DO/DON'T entries and helpful/harmful counters.
**Risk**: Playbook bloat over many runs. Mitigate with ACE's Pruner pattern (future optimization, not P1).

### P4: Spec overrides persistence
**Impact**: Prevents AnalyzeAgent fixes from being overwritten by deterministic pipeline.
**Evidence**: Iterative Generative Optimization paper confirms that within-task persistence is essential for convergence.
**Implementation**: `spec_overrides` dict applied after `Observer.observe()`, before node agents.

### P5: Tiered recipe store
**Impact**: 12 L2-stuck packages skip container debugging on next run. 6 L3 packages skip to JAR matching.
**Evidence**: Build-bench uses "auxiliary context offering historical insights into prior modifications" — recipes are the structured form of this.
**Implementation**: Save at every level (L2/L3/L4) with agent decisions and playbook entries used.

### P6: Reproducible build flags (L3→L4)
**Impact**: Could convert 6 L3 → L4 packages. Chains-Rebuild achieves 26.89% success with canonicalization.
**Evidence**: All 6 L3 failures have bytecode_match=True — divergence is metadata/timestamps only. Canonicalization handles exactly this class.
**Implementation**: (a) Add `-Dproject.build.outputTimestamp=1980-01-01T00:00:00Z` to Maven commands, (b) strip/normalize MANIFEST.MF and pom.properties before comparison.

---

## References

- [ACE: Agentic Context Engineering (Zhang et al., 2025)](https://arxiv.org/abs/2510.04618)
- [ACE Playbook Implementation](https://github.com/jmanhype/ace-playbook)
- [Self-Evolving Agents Cookbook (OpenAI)](https://developers.openai.com/cookbook/examples/partners/self_evolving_agents/autonomous_agent_retraining)
- [AgentDebug: Learning from Agent Failures](https://arxiv.org/abs/2509.25370)
- [Build-bench: LLM Build Repair](https://arxiv.org/pdf/2511.00780)
- [Meta Engineering Agent at Scale](https://arxiv.org/pdf/2507.18755)
- [RepairAgent: Autonomous Program Repair](https://arxiv.org/pdf/2403.17134)
- [Iterative Generative Optimization](https://arxiv.org/html/2603.23994)
- [Causes and Canonicalization of Unreproducible Builds in Java (Sharma et al., FSE 2026)](https://arxiv.org/abs/2504.21679)
- [Apache Maven Reproducible Builds Guide](https://maven.apache.org/guides/mini/guide-reproducible-builds.html)
- [Reproducible Build Maven Plugin](https://zlika.github.io/reproducible-build-maven-plugin/)
- [Maven Artifact Plugin Diagnostics](https://maven.apache.org/plugins/maven-artifact-plugin/reproducible.html)
- [Reproducible Builds in Language Package Managers (ICSE 2025)](https://nesbitt.io/2026/02/24/reproducible-builds-in-language-package-managers.html)
- [Chains-Rebuild / Reproducible Central](https://github.com/chains-project/reproducible-central)
- [Podman Short-Name Resolution (Red Hat)](https://www.redhat.com/en/blog/container-image-short-names)
- [Podman registries.conf Documentation](https://docs.podman.io/en/latest/markdown/podman-pull.1.html)
- [MEMES: MAP-Elites-Multi-ES (GECCO 2024)](https://dl.acm.org/doi/10.1145/3638529.3654089)
- [CORAL: Autonomous Multi-Agent Evolution](https://xuquant.com/en/posts/foundation-models/coral-autonomous-multi-agent-evolution/)
- [AlphaEvolve (Google DeepMind)](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/)
- [Self-Evolving Agents Survey](https://github.com/CharlesQ9/Self-Evolving-Agents)
- [LLMLOOP: Iterative Feedback Loops (ICSME 2025)](https://arxiv.org/html/2603.23613v1)
- [Java Build Nondeterminism (Reproducible Builds)](https://reproducible-builds.org/docs/jvm/)
