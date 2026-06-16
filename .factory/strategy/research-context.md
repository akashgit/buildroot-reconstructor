# Research Context — Issue #24: Node-Scoped Agents

## Project State Summary

**Current score:** 0.8456 (8/8 experiments kept, zero reverts)
**Agentic solve rate:** 1/3 (33.3%) on smoke test (commons-lang3 only)
**Deterministic baseline:** 4/31 L4 match (13%) on 31-package Java benchmark

### Benchmark Baseline (31 packages, deterministic pipeline only)

| Level | Count | Rate |
|-------|-------|------|
| L1 parse | 31/31 | 100% |
| L2 build | 7/31 | 23% |
| L3 command | 5/31 | 16% |
| L4 match | 4/31 | 13% |

**L4 passes:** jackson-databind, commons-lang3, plexus-utils, jettison
**L3 only:** jackson-core (L4 mismatch)
**L2 only:** logback-classic, json-20231013 (build succeeds, Maven command fails)
**L1 only:** 24 packages (all fail at container build)

### Per-Package Baseline Levels

| Package | Level | Failure Category |
|---------|-------|------------------|
| jackson-databind:2.15.3 | L4 | PASS |
| commons-lang3:3.14.0 | L4 | PASS |
| plexus-utils:4.0.0 | L4 | PASS |
| jettison:1.5.4 | L4 | PASS |
| jackson-core:2.15.3 | L3 | L4 JAR mismatch |
| logback-classic:1.4.14 | L2 | L3 build command fails |
| json-20231013 | L2 | L3 build command fails |
| spring-boot:2.7.18 | L1 | Base image not found |
| tomcat-catalina:10.1.18 | L1 | Multi-module / wrong directory |
| netty-buffer:4.1.104.Final | L1 | Base image not found |
| nimbus-jose-jwt:9.37.3 | L1 | Multi-module / wrong directory |
| jetty-server:11.0.20 | L1 | Multi-module / wrong directory |
| avro:1.11.3 | L1 | Build command / environment |
| lz4-java:1.8.0 | L1 | Multi-module / wrong directory |
| guava:33.0.0-jre | L1 | Git tag not found |
| kafka-clients:3.6.1 | L1 | Multi-module / wrong directory |
| snakeyaml:2.2 | L1 | Multi-module / wrong directory |
| jakarta.mail:2.0.1 | L1 | Base image not found |
| hibernate-core:6.4.2.Final | L1 | Containerfile syntax (unresolved props) |
| assertj-core:3.25.1 | L1 | Base image not found |
| json-smart:2.5.0 | L1 | Build tool not found |
| jersey-common:3.1.5 | L1 | Git tag not found |
| commons-beanutils:1.9.4 | L1 | Multi-module / wrong directory |
| json-path:2.9.0 | L1 | Build tool not found |
| junit:4.13.2 | L1 | Base image not found |
| junit-jupiter-api:5.10.1 | L1 | Build command / environment |
| postgresql:42.7.1 | L1 | Containerfile syntax (unresolved props) |
| protobuf-java:3.25.2 | L1 | Multi-module / wrong directory |
| snappy-java:1.1.10.5 | L1 | Base image not found |
| commons-fileupload:1.5 | L1 | Build command / environment |
| hibernate-validator:8.0.1.Final | L1 | Build tool not found |

### Failure Breakdown (24 L2 failures)

| Category | Count | % | Affected Packages | Node Agent Fix |
|----------|-------|---|-------------------|----------------|
| Multi-module / wrong directory | 8 | 26% | tomcat-catalina, nimbus-jose-jwt, jetty-server, lz4-java, kafka-clients, snakeyaml, commons-beanutils, protobuf-java | Node 4 — Repo Agent |
| Base image not found | 6 | 19% | spring-boot, netty-buffer, jakarta.mail, assertj-core, snappy-java, junit | Node 7 — Image Agent |
| Build tool not found | 3 | 10% | json-smart, hibernate-validator, json-path | Node 9 — Build Command Agent |
| Containerfile syntax (unresolved props) | 2 | 6% | hibernate-core, postgresql | Node 3 — Property Agent |
| Git tag not found | 2 | 6% | guava, jersey-common | Node 8 — Tag Agent |
| Build command / environment issues | 3 | 10% | avro, commons-fileupload, junit-jupiter-api | Nodes 5+9 — CI + Build Command Agents |

---

## Issue #24 Architecture (from current.md)

### Core Concept

Attach a scoped Claude Code agent at every node of the deterministic pipeline. Each agent reviews and improves the node's output before passing it downstream. The pipeline produces a draft; agents gate and refine it. This replaces the current approach where failures are only detected after the full pipeline runs.

### 10 Node Agents + 3 Post-Build Failure Agents

| Node | Reviews | Key Benchmark Impact |
|------|---------|---------------------|
| 1 — POM Agent | Fetched POM XML | Relocated/sparse POM detection |
| 2 — Parent Chain Agent | Resolved parent chain | Missing parents, BOM imports |
| 3 — Property Agent | Unresolved `${...}` placeholders | **2 packages:** hibernate-core, postgresql |
| 4 — Repo Agent | Source repository URL | **8 packages:** the biggest failure category |
| 5 — CI Agent | CI configuration | Alternative CI systems, workflow selection |
| 6 — JDK Agent | JDK version and vendor | Conflicting signals resolution |
| 7 — Image Agent | Container base image | **6 packages:** base image not found |
| 8 — Tag Agent | Git tag | **2 packages:** guava, jersey |
| 9 — Build Command Agent | Build command and tool | **3 packages:** json-smart, hibernate-validator, json-path |
| 10 — Template Agent | Rendered Containerfile | Last gate, syntax validation |
| L2 Failure Agent | Container build log | Post-build diagnosis |
| L3 Failure Agent | Maven/Gradle output | Build command diagnosis |
| L4 Failure Agent | JAR diff | Reproducibility issues |

### Evidence Ranking (NOT confidence)

Agents rank proposals by evidence type: direct observation > CI inference > cross-reference > historical pattern > ecosystem heuristic > default.

### Gap-Status Activation

- **DEFAULTED**: agent always fires (highest value)
- **INFERRED**: agent fires in standard mode (verify)
- **OBSERVED**: agent fires in validate-only mode (sanity check)

---

## Current Pipeline Architecture (orchestrator.py)

The deterministic pipeline in `BuildrootOrchestrator.reconstruct()` (orchestrator.py:78-229) has 13 sequential steps that map directly to the node agents:

```
Step 1.  Fetch POM             → POM Agent (Node 1)
Step 2.  Parse POM             → POM Agent (Node 1)
Step 3.  Resolve parent chain  → Parent Chain Agent (Node 2)
Step 4.  Merge POMs            → Parent Chain Agent (Node 2)
Step 5.  Resolve properties    → Property Agent (Node 3)
Step 6.  Discover source repo  → Repo Agent (Node 4)
Step 7.  Discover/parse CI     → CI Agent (Node 5)
Step 8.  Resolve JDK           → JDK Agent (Node 6)
Step 9.  Resolve container image → Image Agent (Node 7)
Step 10. Resolve dependency tree → (no agent needed)
Step 11. Discover git tag      → Tag Agent (Node 8)
Step 12. Build spec + enrich commands → Build Command Agent (Node 9)
Step 13. Gap detection + generate Containerfile → Template Agent (Node 10)
```

### Key Orchestrator Details

- `pom_data` is the parsed POM after step 2
- `merged` is the fully-resolved POM after step 4 (parent chain merged)
- `resolved_props` and `prop_gaps` come from step 5
- `source_repo`, `repo_owner`, `repo_name` from step 6
- `ci_data` from step 7 (GitHub Actions or CircleCI)
- `jdk_spec` from step 8
- `container_result` from step 9
- `git_tag` from step 11
- `spec` is the final `BuildrootSpec` assembled in step 12-13
- `gap_report` from `GapDetector` classifies each field as OBSERVED/INFERRED/DEFAULTED

---

## Agent Infrastructure (from experiments 6-8)

### Available Infrastructure

1. **`claude_runner.py`** — Shared utility for spawning Claude Code subprocesses
   - `spawn_claude_agent(task, system_prompt, *, model, json_schema, max_turns, max_budget_usd, timeout, cwd, allowed_tools) → AgentResult`
   - Flags: `--bare`, `--output-format json`, `--dangerously-skip-permissions`, `--append-system-prompt-file`
   - Error handling: timeout, CLI not found, JSON parse failure
   - 12 unit tests covering all error paths

2. **`evaluator.py`** — 4-level evaluation via SSH to rh-h100-01
   - L1: Containerfile parse (local, via dockerfile-parse)
   - L2: `podman build` on rh-h100-01 via SSH
   - L3: `podman run` to check for target/*.jar
   - L4: JAR comparison via jar_comparator

3. **`builder.py`** — Claude Code subprocess-driven Containerfile mutation (3 modes: refine, explore, fresh_start)
   - Already uses `spawn_claude_agent()` with system prompts
   - `_extract_containerfile()` for stripping markdown fences from agent output
   - `_validate_containerfile()` for structural validation

4. **`observer.py`** — Wraps deterministic `BuildrootOrchestrator.reconstruct()` to produce initial spec + Containerfile

### rh-h100-01 Access Pattern

SSH with BatchMode and no host key checking:
```python
subprocess.run(
    ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
     self._host, build_cmd],
    capture_output=True, text=True, timeout=self._timeout,
)
```

Default host: `rh-h100-01` (160 cores, 1.7TB RAM). Always available per memory feedback.

---

## Key Lessons from Experiments 6-8

### Experiment 6 (Inner Loop MVP) — Solve rate 33.3%

- commons-lang3 solved in 1 iteration (easy packages work immediately)
- micrometer-core stuck at L2 (Gradle project misidentified as Maven)
- spring-security-core stuck at L1 (persistent "stage 1 requires FROM" parse errors)
- **90% of wasted iterations** were caused by Claude returning prose-wrapped Containerfiles
- Dead-end registry (2-failure threshold) prevents cycling

### Experiment 7 (Outer Loop Intelligence)

- Failure analyst, knowledge base, guards, J(S) strategy scoring
- Outer loop ran 3 cycles on 3 packages, stagnated at 33.3% solve rate
- Dominant failure: "unknown" error class masking three real root causes:
  1. Containerfile parse corruption (prose leaking from LLM output)
  2. Wrong build system detection (Gradle identified as Maven)
  3. Multi-module project directory issues

### Experiment 8 (Claude Code Migration)

- All 3 agents migrated from raw `AnthropicVertex` API → Claude Code subprocess
- New Outer Researcher agent added
- Score: 0.8442 → 0.8456 (+0.0014)
- Infrastructure enabler — agents now have tool access (Read, Edit, Bash, WebSearch)

### Critical Observation from Interaction Logs

The interaction study (observations.md) shows **overwhelming** evidence that the biggest single problem with the inner loop approach was the LLM's Containerfile output being contaminated with prose/markdown. The `_extract_containerfile()` function has 3 strategies but still fails frequently. 

In the node-scoped agent approach, this problem is largely eliminated because agents review and improve individual pipeline node outputs (structured data like repo URLs, JDK versions, git tags), not full Containerfiles.

---

## What Node Agents Replace vs. Complement

### Replaces (partially)
- The **inner loop** (`loop.py`) did iterative Containerfile repair after the full pipeline ran. Node agents catch and fix errors at each step before they cascade.
- The **observer** (`observer.py`) currently runs the full deterministic pipeline as-is. With node agents, the orchestrator becomes the augmented pipeline.

### Complements
- The **evaluator** (`evaluator.py`) remains unchanged — it's the L1-L4 scoring mechanism
- The **outer loop** (`outer_loop.py`) can still run on top for cross-package learning
- The **claude_runner** is the foundation all node agents will use

### Key Difference from Inner Loop Approach

The inner loop gives the LLM full control over the Containerfile and asks it to fix failures after the fact. Node agents are scoped: each one reviews a single pipeline step's output and can only modify that step's output. This prevents:
1. **Regression on solved packages** (issue #22: spring-security-core was EQUIVALENT with deterministic template but the agentic Builder corrupted it)
2. **Prose contamination** (agents review structured data like repo URLs, JDK versions, git tags — not full Containerfiles)
3. **Cascading errors** (a wrong repo URL discovered early is fixed before it causes a wrong git tag → wrong clone → build failure)

---

## Implementation Considerations

### Integration Point

Node agents hook into `BuildrootOrchestrator.reconstruct()` (orchestrator.py:78-229). After each deterministic step, the corresponding node agent runs. The orchestrator currently has 13 sequential steps — node agents interleave between them.

**Design options:**
1. Modify `BuildrootOrchestrator.reconstruct()` directly to call node agents inline
2. Create a new `AgenticOrchestrator` that wraps `BuildrootOrchestrator` and adds agent review steps
3. Add a flag like `--agents` to the existing orchestrator

Option 2 is cleanest: it keeps the deterministic pipeline unchanged (regression safety) and adds the agent layer on top.

### Agent Budget per Package

With 10 node agents + up to 3 post-build agents, each package could spawn 10-13 Claude Code subprocesses. Budget considerations:
- **Light agents** (POM, Parent Chain, Property): few turns, small budget (~$0.50-1.00 each)
- **Medium agents** (Repo, CI, JDK, Image, Tag, Build Command): moderate research (~$1-3 each)
- **Heavy agents** (Template, L2/L3/L4 Failure): may need tool use, iteration (~$3-5 each)
- **Gap-status activation** reduces cost: OBSERVED fields get light validate-only agents

### Acceptance Criteria (from issue #24)

1. `NodeAgent` base class with system prompt templating, context injection, candidate ranking, evidence citation
2. All 10 node agent implementations integrated into orchestrator
3. All 3 post-build failure agents (L2, L3, L4)
4. Orchestrator integration: after each deterministic step, node agent runs
5. Updated benchmark script with agent-augmented pipeline mode
6. **Full benchmark run on all 31 packages on rh-h100-01 with results stored** — PRIMARY acceptance criterion

### Testing Requirements (CRITICAL — from memory)

Per feedback memories `feedback-e2e-mandatory.md` and `feedback-mandatory-e2e.md`:
- Real E2E on rh-h100-01 for ≥1 package MUST happen after any pipeline change
- Mocked tests are NOT sufficient
- Token cost is NEVER a valid skip reason
- rh-h100-01 nodes are always available

---

## Benchmark Package Analysis by Expected Agent Impact

### Tier 1: High-Impact — Node 4 Repo Agent (8 packages)

These fail because the pipeline produces a wrong source repo URL or doesn't handle multi-module project subdirectories. The Repo Agent can:
- Verify URL validity (HTTP HEAD)
- Search GitHub API for correct repo
- Identify correct subdirectory for multi-module projects
- Adjust clone + build strategy

**Packages:** tomcat-catalina, nimbus-jose-jwt, jetty-server, lz4-java, kafka-clients, snakeyaml, commons-beanutils, protobuf-java

### Tier 2: High-Impact — Node 7 Image Agent (6 packages)

These fail because the chosen container base image tag doesn't exist on Docker Hub. The Image Agent can:
- Check tag existence via Docker Hub registry API
- Search alternative tags from the same vendor
- Fall back to different vendors

**Packages:** spring-boot, netty-buffer, jakarta.mail, assertj-core, snappy-java, junit

### Tier 3: Medium-Impact — Nodes 3, 8, 9 (7 packages)

- **Node 3 Property Agent** (2): hibernate-core, postgresql — unresolved Maven properties
- **Node 8 Tag Agent** (2): guava, jersey-common — wrong git tag format
- **Node 9 Build Command Agent** (3): json-smart, hibernate-validator, json-path — wrong build tool detected

### Already Passing (must NOT regress)

- **L4:** jackson-databind, commons-lang3, plexus-utils, jettison
- **L3:** jackson-core
- **L2:** logback-classic, json-20231013

---

## Realistic Impact Estimate

If node agents fix:
- 6/8 multi-module issues (Repo Agent) → +6 to L2+
- 5/6 base image issues (Image Agent) → +5 to L2+
- 2/3 build tool issues (Build Command Agent) → +2 to L2+
- 2/2 property issues (Property Agent) → +2 to L2+
- 1/2 tag issues (Tag Agent) → +1 to L2+

**Optimistic L2+ rate:** 7 (current) + 16 = 23/31 (74%)
**Realistic L4 rate after L3/L4 attrition:** 8-15/31 (26-48%)

The target from issue #24 is "significantly improve beyond 4/31 L4 (13%) baseline."

---

## Summary

Issue #24 is the highest-leverage improvement available. The deterministic pipeline gets the right answer for only 4/31 packages, with well-characterized failure categories that map cleanly to specific pipeline nodes. The agent infrastructure (claude_runner, evaluator, SSH to rh-h100-01) is already in place from experiments 6-8.

The implementation is a **single deliverable** — all 13 agents + orchestrator integration + benchmark run — with the full benchmark run on rh-h100-01 as the primary acceptance criterion. The issue explicitly states: no phasing, no "framework first," no deferring agents to future cycles.
