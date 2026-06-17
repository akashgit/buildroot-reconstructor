# Research Context — Issue #27: Agent Architecture Fix

## Project Summary

Buildroot-reconstructor is a pipeline that reconstructs container build environments for Java/Maven artifacts from Maven Central, verifying reproducibility across 4 levels:
- **L1**: Containerfile parses (syntax valid)
- **L2**: Container builds (podman build succeeds)
- **L3**: Source compiles (mvn/gradle inside container produces artifacts)
- **L4**: JAR matches (rebuilt artifact matches Maven Central original)

The system has evolved through 9 experiments (all KEPT, zero reverts), building up from core pipeline → agentic inner loop → outer loop intelligence → node-scoped agents. Current architecture: 13 Claude Code agents (10 node-scoped reviewers + 3 failure diagnosis agents) integrated into a deterministic pipeline via `AgentAugmentedObserver`.

---

## Experiment 9 Results — 31-Package Benchmark

**Headline: 7/31 L4 (22.6%), up from 4/31 (12.9%) deterministic baseline**

### Level Distribution
| Level | Count | Packages |
|-------|-------|----------|
| L4 (solved) | 7 | jackson-databind, avro, jettison, plexus-utils, json, snappy-java, snakeyaml |
| L3 (source OK, JAR mismatch) | 6 | jackson-core, nimbus-jose-jwt, jakarta.mail, commons-beanutils, commons-fileupload, jersey-common |
| L2 (container OK, source fails) | 12 | guava, protobuf-java, netty-buffer, json-smart, kafka-clients, assertj-core, jetty-server, hibernate-validator, junit-jupiter-api, lz4-java, postgresql, spring-boot |
| L1 (container fails) | 6 | logback-classic, json-path, junit, commons-lang3, tomcat-catalina, hibernate-core |

### Solved Package Characteristics
- **Easy packages solve fast**: jackson-databind and plexus-utils solved in 1 iteration; jettison and json in 2
- **Hard packages need iteration**: snappy-java took 8 iterations, snakeyaml took 5
- **Total wall-clock**: 20.6 hours across 9 rh-h100 nodes

### Critical Operational Finding
- ALL error classes in dead_ends are `unknown` — the error classifier (`analyzer.py`) isn't categorizing errors properly, which means the dead-end system and mode switching (exploit/explore/meta-shift) are operating blind
- Every L1-stuck package exhausted 15 iterations without improving — no learning across iterations

---

## Root Cause Analysis from Benchmark Data

### L1 Failures (6 packages) — Three Distinct Root Causes

1. **SSH authentication failure** (logback-classic, json-path, junit, commons-lang3, tomcat-catalina): `Permission denied (publickey)` — infrastructure issue, not code. These packages ran on nodes where SSH keys weren't configured. Not fixable by agent code changes.

2. **Containerfile syntax error** (hibernate-core): `ENV JAVA_OPTS -Xmx4g` instead of `ENV JAVA_OPTS="-Xmx4g"` — failure agent should catch this but fix doesn't persist across iterations (Gap 3).

3. **First-iteration Podman short-name** (some L1 packages): First attempt uses bare `eclipse-temurin:8-jdk` → Podman rejects → error classified as L1.

### L2 Failures (12 packages) — Four Distinct Root Causes

| Root Cause | Packages | Why Agent Missed It |
|-----------|----------|---------------------|
| **Podman short-name resolution** | kafka-clients, assertj-core, json-smart, protobuf-java, hibernate-validator | `JdkResolver._map_distribution_to_image()` at `jdk.py:299-304` returns `eclipse-temurin:17-jdk` without `docker.io/library/` prefix. Image_agent may fix it, but `Observer.observe()` regenerates spec next iteration, overwriting the fix (Gap 3). |
| **`./mvnw` not found** | guava, netty-buffer | build_cmd_agent suggests `./mvnw` when wrapper exists in repo, but wrapper isn't executable in container |
| **Wrong build system** | lz4-java | CI data says Maven (OBSERVED), so build_cmd_agent's `should_activate()` skips it (Gap 2) |
| **Multi-module missing deps** | jetty-server, postgresql, spring-boot, junit-jupiter-api | Unpublished internal modules not on Maven Central |

### L3 Failures (6 packages) — One Root Cause

ALL 6 show `bytecode_match=True` but `structural_match=False, metadata_match=False`:
- MANIFEST.MF timestamps and `Created-By` headers
- `pom.properties` build paths and timestamp comments
- Missing/extra LICENSE files

**Fix**: Add `-Dproject.build.outputTimestamp` Maven flag + normalize comparison by stripping non-semantic metadata.

---

## Five Architectural Gaps — Confirmed by Data

### Gap 1: Agents Run Pre-Build Only — No Failure Feedback

**Code**: Node agents fire in `augmented_observer.observe()` BEFORE any build. Failure agents fire only on iteration 0 (`loop.py:102-106`, gated by `failure_agent_used` flag).

**Evidence**: kafka-clients' image_agent verifies a Docker Hub tag exists but can't know Podman will reject the bare name at build time. The failure agent fires once, produces a fix, but the fix is overwritten on the next iteration.

### Gap 2: `should_activate()` Blocks Agents from Fixing OBSERVED Values

**Code**: `base.py:93-98` only activates agents when fields are DEFAULTED or INFERRED. OBSERVED fields are never reviewed.

**Evidence**: lz4-java's CI data provides Maven as the build system (OBSERVED), so build_cmd_agent never fires to correct it to Gradle. The package is stuck at L2 for all 15 iterations.

### Gap 3: Fixes Don't Persist Across Iterations

**Code**: Every iteration calls `Observer.observe()` → deterministic pipeline regenerates spec from scratch. No `spec_overrides` mechanism exists.

**Evidence**: kafka-clients attempts show the SAME short-name error repeating: `eclipse-temurin:8-jdk` → `eclipse-temurin:17-jdk-jammy` → `eclipse-temurin:11-jdk-focal`. Different images but same bare-name bug — the docker.io/library/ prefix never sticks.

### Gap 4: `apply_best()` Picks One Candidate — Discards Alternatives

**Code**: `base.py:117-126` sorts by evidence rank and picks rank-0. All other candidates are lost.

**Evidence**: jackson-core dead_ends show 3 different image approaches tried sequentially over 15 iterations. With top-K parallel builds, all 3 could have been tried in iteration 1.

### Gap 5: Failure Agents and Node Agents Are Disconnected

**Code**: Failure agents (`failure_agents.py`) diagnose build errors and write fixes directly to spec. Node agents read their own system prompts. There's no mechanism for cross-communication.

**Evidence**: No shared playbook or knowledge transfer between failure diagnosis and node agent activation.

---

## Key Source Code References

| File | Lines | Role | Issue #27 Impact |
|------|-------|------|-----------------|
| `agent/node_agents/base.py` | 162 | NodeAgent base class, `apply_best()`, `should_activate()` | `apply_best()` → `apply_top_k()`, relax `should_activate()` for OBSERVED |
| `agent/loop.py` | 215 | Inner loop orchestrator | Add AnalyzeAgent call after each failed iteration; add top-K forking |
| `agent/augmented_observer.py` | 141 | Agent-augmented observer | Add playbook reading for node agents; support spec_overrides |
| `agent/node_agents/failure_agents.py` | 270 | L2/L3/L4 failure diagnosis | Connect to AnalyzeAgent via playbook system |
| `agent/claude_runner.py` | 136 | Subprocess spawner | Already sufficient, no changes needed |
| `resolvers/jdk.py:299-304` | `_map_distribution_to_image()` | Image name resolution | Add `docker.io/library/` prefix (P5 deterministic fix) |

---

## Prior Experiment Patterns — Relevant to Issue #27

### Score Trajectory
| Exp | Focus | Δ | Insight |
|-----|-------|---|---------|
| Baseline | Core pipeline | 0.586 | 201 tests, 10 packages |
| 1-3 | Pipeline fixes, L3/L4 | +0.264 | Code review catches real bugs |
| 4-5 | PNC validation | +0.231 | External benchmark reveals gaps |
| 6 | Agentic inner loop | +0.004 | 1/3 solved; easy packages instant |
| 7 | Outer loop intelligence | +0.043 | Knowledge base, failure analyst, guards |
| 8 | Claude Code migration | +0.001 | Infrastructure enabler, tool access |
| 9 | Node-scoped agents | -0.001 | 7/31 L4 (22.6%) on full benchmark |

### Archive Pattern: Infrastructure experiments show small deltas; capability unlock justifies KEEP
Experiments 6, 8, 9 all showed near-zero eval deltas but were KEPT because they laid architectural groundwork.

### Archive Pattern: Easy packages solve instantly, hard packages need feedback loops
Bimodal distribution: 7 solved in ≤8 iterations vs. 24 stuck at 15 iterations. Iteration budget is wasted on packages that aren't improving.

### Archive Pattern: Deterministic fixes beat iterative LLM repair for known error classes
From `pre-flight-sanitization-beats-iterative-repair`: when a dominant failure class has a deterministic fix, apply it as pre-flight sanitization. The Podman `docker.io/library/` prefix is exactly this class.

### Archive Pattern: Per-error-type feedback loops outperform generic repair
From `llmloop-iterative-feedback`: different failure modes benefit from different prompt templates. The AnalyzeAgent's playbook DO/DON'T entries are error-class-specific instructions.

### Archive Pattern: Multi-round code review catches distinct bug classes
Exp 9 found 5 bugs across 3 review rounds. Plan for at least 3 review iterations for this experiment.

---

## Implementation Priority Analysis

### P5 FIRST (Deterministic Fix): Podman Registry Prefix
- **Why first**: 5 packages immediately unblocked. Zero agent cost. One-line fix in `_map_distribution_to_image()`.
- **Code change**: `jdk.py:304` — prepend `docker.io/library/` to images from DISTRIBUTION_IMAGE_MAP when the image name has no registry prefix.
- **Expected impact**: 5 packages move from L1/L2 → L2+ immediately.

### P1 NEXT: Top-K Parallel Candidate Builds
- **Why second**: User's core design intent. Every iteration tries K paths instead of 1.
- **Code change**: `base.py:117-126` → new `apply_top_k()` returning K (spec, containerfile) pairs. `loop.py` forks into K parallel podman builds per iteration.
- **Key constraint**: Cap total variants per iteration (max 5 parallel builds) to avoid K^N combinatorial explosion across N node agents.
- **Expected impact**: Unlocks alternatives agents already generate but currently discard.

### P2+P4 TOGETHER: AnalyzeAgent + Spec Overrides
- **Why together**: Codependent — spec_overrides need AnalyzeAgent to set them, AnalyzeAgent needs overrides to persist fixes.
- **Code changes**:
  - New `AnalyzeAgent` class — Claude Code subprocess, runs after each failed iteration
  - Playbook files at `.factory/playbooks/node_agents/{agent}.md` — ACE-style DO/DON'T rules
  - `spec_overrides: dict` applied after `Observer.observe()`, before node agents
  - Node agents read their playbook file at the start of each `review()` call
- **Budget concern**: $2/call × 15 iterations × 31 packages = $930 worst case. Need early termination for stagnant packages.
- **Expected impact**: Closes Gaps 1, 2, 3, 5. Node agents learn from build failures.

### P3 LATER: Tiered Recipe Store
- **Why later**: Depends on P1 and P2 producing higher-level results to store.
- **Code change**: Save recipes at `.factory/recipes/{coordinate}.json` at every level. Load on future runs to start from checkpoint.
- **Expected impact**: 12 L2-stuck packages get a head start on next run.

### P6 WITH P3: Reproducible Build Flags
- **Why with P3**: 6 L3 packages need comparison-side normalization + build-side `-Dproject.build.outputTimestamp` flag.
- **Expected impact**: Could convert 6 L3 → L4.

---

## Key Risks

1. **Agent cost explosion**: AnalyzeAgent at $2/call × 15 iterations × 31 packages = $930. Mitigate with early termination for stagnant packages (plateau detection after 3 iterations of no improvement).

2. **Top-K combinatorial explosion**: K candidates per node × N nodes = K^N specs. Mitigate by capping total variants per iteration (max 5) and only forking on the most impactful node agents.

3. **Playbook contradiction**: If AnalyzeAgent writes conflicting DO/DON'T rules, node agents get confused. Need dedup and conflict detection.

4. **SSH infrastructure**: 5/6 L1 failures were SSH permission errors. Must ensure SSH access to ALL rh-h100 nodes before benchmark.

5. **Error classifier**: Current classifier returns `unknown` for almost all errors. AnalyzeAgent helps, but `analyzer.py`'s regex patterns should also be improved.

---

## Success Criteria (from issue spec)

- L4 solve rate ≥ 35% (11/31) on same 31-package benchmark
- Zero L1 packages due to Containerfile syntax errors
- Zero L2 packages due to Podman short-name resolution
- Agent fixes persist across iterations (verified via logging)
- AnalyzeAgent writes playbook entries; node agents consume them
- Playbook files grow across packages (visible in `.factory/playbooks/node_agents/`)
- Recipe store populated for all packages reaching L2+

## Benchmark Execution Requirement

The full 31-package benchmark MUST be run on rh-h100 nodes. Same setup as exp 9: split packages across rh-h100-01 through rh-h100-09, deploy code via rsync, run `buildroot agent`, collect and merge results. Compare against exp 9 baseline (7/31 L4 = 22.6%).
