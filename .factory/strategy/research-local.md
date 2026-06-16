# Local Research — Node-Scoped Agents (Issue #24)

## 1. Agent Architecture (`src/buildroot/agent/`)

### Existing Agents

| File | Role | Uses Claude Code? |
|---|---|---|
| `observer.py` | Wraps `BuildrootOrchestrator.reconstruct()` to produce initial spec + Containerfile | No — pure deterministic |
| `builder.py` | Containerfile mutation (refine/explore/fresh_start/diagnose) | Yes — `spawn_claude_agent` |
| `evaluator.py` | 4-level scoring (L1 parse, L2 build, L3 command, L4 JAR match) via SSH to rh-h100-01 | No — deterministic SSH/subprocess |
| `analyzer.py` | Error classification, dead-end registry, build progress estimation, root cause extraction | No — regex-based |
| `failure_analyst.py` | Batch failure aggregation, stagnation detection | No — aggregation logic |
| `outer_researcher.py` | Web research on failure patterns | Yes — `spawn_claude_agent` |
| `outer_strategist.py` | Hypothesis generation with J(S) scoring | Yes — `spawn_claude_agent` with JSON schema |
| `loop.py` | Inner loop: Observer → [Builder → Evaluator → Analyzer]* | Orchestrator only |
| `outer_loop.py` | Intelligent self-improving cycle: batch → analyze → research → strategize → implement → guards → verdict | Orchestrator + uses `spawn_claude_agent` for OuterBuilder |
| `claude_runner.py` | Shared subprocess runner for all Claude Code invocations | Infrastructure |
| `guards.py` | Surface guards, leakage detection, monotonic enforcement | No — deterministic |
| `knowledge/knowledge_base.py` | KB read/write for cross-package patterns | No — file I/O |

### `claude_runner.py` Infrastructure (claude_runner.py:33-136)

The `spawn_claude_agent()` function is the single entry point for all Claude Code subprocess invocations:

```python
def spawn_claude_agent(
    task: str,
    system_prompt: str,
    *,
    model: str = "claude-opus-4-6",
    json_schema: dict | None = None,   # for structured output
    max_turns: int = 30,
    max_budget_usd: float = 5.0,
    timeout: int = 600,
    cwd: str | None = None,
    allowed_tools: list[str] | None = None,
) -> AgentResult
```

Key capabilities:
- **Structured output** via `--json-schema` — used by strategist for `CodeChangeHypothesis`
- **Tool scoping** via `--allowedTools` — OuterBuilder uses `["Read", "Edit"]`, Researcher uses `["Read", "WebSearch", "Bash"]`
- **System prompt injection** via `--append-system-prompt-file` (temp file, cleaned up in finally block)
- **Permission bypass** via `--dangerously-skip-permissions`
- Returns `AgentResult(text, structured_output, is_error, cost_usd, num_turns)`

**This is the foundation for all node agents.** Each node agent will call `spawn_claude_agent()` with a node-specific system prompt, scoped allowed tools, and a JSON schema for structured candidate ranking output.

## 2. The Deterministic Pipeline (`pipeline/orchestrator.py:78-229`)

`BuildrootOrchestrator.reconstruct()` runs 13 sequential steps. Each step maps to one or more node agents from issue #24:

| Step | Code | What It Does | Node Agent |
|---|---|---|---|
| 1 | `fetch_pom()` | Download POM from Maven Central | **Node 1: POM Agent** |
| 2 | `PomParser.parse()` | Parse POM XML | Node 1 |
| 3 | `resolve_parent_chain()` | Walk parent POM chain | **Node 2: Parent Chain Agent** |
| 4 | `merge_poms()` | Merge parent → child properties | Node 2 |
| 5 | `PropertyResolver.resolve()` | Resolve `${...}` placeholders | **Node 3: Property Agent** |
| 6 | `discover_repo_from_pom()` | Find source repo URL | **Node 4: Repo Agent** |
| 7 | `CIParser.discover_ci_type()` + parse | Parse CI config (GHA, CircleCI) | **Node 5: CI Agent** |
| 8 | `JdkResolver.resolve()` | Determine JDK version + vendor | **Node 6: JDK Agent** |
| 9 | `ContainerImageResolver.resolve()` | Resolve container base image | **Node 7: Image Agent** |
| 10 | `DependencyResolver.resolve()` | Dependency tree | — |
| 11 | `discover_git_tag()` | Find correct git tag | **Node 8: Tag Agent** |
| 12 | `_detect_maven_wrapper_version()` | Maven wrapper version + `_enrich_build_commands()` | **Node 9: Build Cmd Agent** |
| 13 | `GapDetector.analyze()` + `ContainerfileGenerator.generate()` | Gap detection + Containerfile rendering | **Node 10: Template Agent** |

### Where Agents Insert

Each node agent inserts **after** its deterministic step. The agent receives:
1. The current `BuildrootSpec` (partially built, all upstream fields populated)
2. The gap classification for this node's field (OBSERVED/INFERRED/DEFAULTED)
3. Read access to upstream context (POM XML text, CI YAML, git repo data)

The agent **can modify** only the current node's contribution to the spec before the next step consumes it.

## 3. The GapDetector (`pipeline/gap_detector.py:16-199`)

`GapDetector.analyze()` checks 6 dimensions and classifies each as OBSERVED/INFERRED/DEFAULTED via the `Source` enum:

| Check Method | Field | Gap Trigger |
|---|---|---|
| `_check_jdk_confidence` | `jdk_version` | `JdkSpec.confidence.level == DEFAULTED/INFERRED` |
| `_check_ubuntu_latest` | `runner_os` | `ubuntu-latest` mapping → INFERRED |
| `_check_unresolved_properties` | `property:*` | Any `${...}` remaining → DEFAULTED |
| `_check_maven_wrapper` | `maven_version` | No wrapper found → DEFAULTED |
| `_check_build_command` | `build_command` | No CI build command → DEFAULTED |
| `_check_system_packages` | `system_packages` | No CI data → DEFAULTED |

**For issue #24:** The GapDetector currently runs post-hoc at step 13. For node-scoped agents, the approach is:
1. Run the full deterministic pipeline → produces draft `BuildrootSpec`
2. Run `GapDetector.analyze(spec)` → gap report with per-field source classifications
3. Use gap entries to determine which node agents activate and at what level:
   - **DEFAULTED** → agent always fires (highest value)
   - **INFERRED** → agent fires in standard mode (verify the inference)
   - **OBSERVED** → agent fires in light/validate-only mode (sanity check)
4. Each node agent can update the spec → re-render Containerfile

This avoids refactoring the GapDetector to run per-field during the pipeline.

## 4. The Template System (`generators/`)

Three Jinja2 templates, selected by `ContainerfileGenerator._select_template()` at `containerfile.py:116`:

| Template | Selector | FROM Source |
|---|---|---|
| `jdk_base.j2` | Default | `{{ base_image }}-jdk` (e.g., `docker.io/library/eclipse-temurin:17-jdk`) |
| `jdk_on_ubuntu.j2` | `spec.system_packages` non-empty | `ubuntu:{{ ubuntu_version }}` + manual JDK install |
| `custom_base.j2` | `spec.base_image` set | `{{ custom_image }}` (from CI container reference) |

All templates share the same structure: FROM → Maven install → ENV vars → git clone → build RUN.

**Node 10 (Template Agent)** reviews the rendered Containerfile, not the template. It validates:
- Syntax of every line (ENV, ARG, RUN)
- Unresolved `${...}` in ENV/ARG values
- Missing package installs
- Dockerfile best practices

Re-rendering after agent updates is straightforward — `ContainerfileGenerator.generate(updated_spec, output_dir)`.

## 5. The Evaluator (`evaluator.py:26-267`)

4-level pipeline, all via SSH to rh-h100-01:

| Level | Method | What It Tests | Reward Weight |
|---|---|---|---|
| L1 | `_l1_parse()` | `dockerfile_parse.DockerfileParser` structural parse | 0.05 |
| L2 | `_l2_build()` | `ssh rh-h100-01 "podman build --no-cache -t TAG -f Containerfile ."` | 0.10 |
| L3 | `_l3_command()` | `podman run --rm TAG sh -c 'ls target/*.jar && echo BUILD_SUCCESS'` | 0.35 |
| L4 | `_l4_match()` | Download original JAR from Maven Central, extract rebuilt JAR, `compare_jars()` | 0.50 |

**FIXED surface** — evaluator.py and jar_comparator.py cannot be modified.

Reward function (`models.py:86`): `reward = 0.05*L1 + 0.10*L2 + 0.35*L3 + 0.50*L4`

**Post-build failure agents** fire based on evaluator results:
- L2 failure (container build failed) → **L2 Failure Agent** reads build log, proposes Containerfile fixes
- L3 failure (no JAR in target/) → **L3 Failure Agent** reads Maven/Gradle output, proposes build command fixes
- L4 failure (JAR mismatch) → **L4 Failure Agent** reads comparison report, proposes reproducibility fixes

## 6. The Benchmark Script

**No dedicated `benchmark.py` or `benchmark` CLI command exists.** Benchmarking is done via:
```bash
buildroot agent --batch results/packages_benchmark.txt --output results/benchmark-full
```

This routes through `agent_cmd.py:54` → `run_outer_loop()` → `run_batch()` in `outer_loop.py:73`.

Package lists:
- `results/packages_smoke.txt` — 3 packages (commons-lang3, micrometer-core, spring-security-core)
- `results/packages_benchmark.txt` — 31 packages (full benchmark set)

Current baseline from `results/benchmark-full/summary.json`:
```
L1: 31/31 (100%), L2: 7/31 (23%), L3: 5/31 (16%), L4: 4/31 (13%)
```

**For issue #24:** The `agent_cmd.py` CLI needs a `--node-agents` flag or similar to enable the node agent layer. The benchmark command already exists as `agent --batch`.

## 7. Current Flow vs. Target Flow

### Current Flow
```
Observer.observe(coordinate)
  └── BuildrootOrchestrator.reconstruct()  ← 13 deterministic steps, no review
       └── GapDetector runs at end (post-hoc)
       └── ContainerfileGenerator renders template
       └── returns (spec, containerfile)

[Inner Loop] (only used in agentic mode, not in benchmark):
  for t in range(max_iterations):
      Evaluator.evaluate(containerfile)
      Analyzer.classify + analyze
      Builder.refine/explore/fresh_start(containerfile)
```

### Target Flow (Issue #24)
```
Phase 1: Deterministic + Agent Augmentation
  BuildrootOrchestrator.reconstruct()  ← 13 deterministic steps (draft)
  GapDetector.analyze(spec)            ← classify each field
  For each Node Agent (1-10):
      if gap_status warrants activation:
          NodeAgent.review(spec, context) → ranked candidates
          Apply best candidate to spec
  ContainerfileGenerator.generate(updated_spec)  ← re-render with fixes

Phase 2: Evaluate + Post-Build Agents
  Evaluator.evaluate(containerfile)
  If L2 fail → L2FailureAgent.diagnose(build_log) → fix + re-evaluate
  If L3 fail → L3FailureAgent.diagnose(build_output) → fix + re-evaluate
  If L4 fail → L4FailureAgent.diagnose(comparison_report) → note for future
```

**Key insight:** The inner Builder loop from the current agentic pipeline may become unnecessary for most packages. If node agents fix upstream issues (wrong repo, wrong tag, wrong image, wrong build command), the first Containerfile should be correct. The post-build failure agents handle the remaining cases.

## 8. Integration Architecture

### Recommended: AgentAugmentedObserver

**Option C from issue analysis** — modify `observer.py` or create a new class:

```
AgentAugmentedObserver.observe(coordinate)
  1. deterministic_spec, draft_containerfile = super().observe(coordinate)
  2. gap_report = GapDetector().analyze(deterministic_spec)
  3. for node_agent in ordered_agents:
         if node_agent.should_activate(gap_report):
             candidates = node_agent.review(deterministic_spec, context)
             node_agent.apply_best(deterministic_spec, candidates)
  4. final_containerfile = ContainerfileGenerator().generate(updated_spec)
  5. return updated_spec, final_containerfile
```

This approach:
- Doesn't modify `orchestrator.py` (the deterministic pipeline stays clean)
- Drops into the existing inner loop seamlessly (the loop calls `observer.observe()`)
- Allows enabling/disabling via a flag (`--node-agents`)

### File Organization

New files:
```
src/buildroot/agent/node_agents/
├── __init__.py
├── base.py              # NodeAgent base class
├── pom_agent.py         # Node 1
├── parent_chain_agent.py # Node 2
├── property_agent.py    # Node 3
├── repo_agent.py        # Node 4
├── ci_agent.py          # Node 5
├── jdk_agent.py         # Node 6
├── image_agent.py       # Node 7
├── tag_agent.py         # Node 8
├── build_cmd_agent.py   # Node 9
├── template_agent.py    # Node 10
└── failure_agents.py    # L2, L3, L4 post-build agents

src/buildroot/agent/augmented_observer.py  # AgentAugmentedObserver
```

### NodeAgent Base Class Shape

```python
@dataclass
class Candidate:
    value: Any                    # The proposed value for this field
    evidence_type: str            # From the ranking hierarchy
    evidence_citations: list[str] # Specific citations
    reasoning: str                # Why this candidate

class NodeAgent:
    node_name: str
    field_name: str               # Maps to GapEntry.field
    system_prompt: str

    def should_activate(self, gap_report: GapReport) -> bool:
        entry = next((e for e in gap_report.entries if e.field == self.field_name), None)
        if entry is None:
            return False  # No gap → OBSERVED → light mode or skip
        if entry.source == Source.DEFAULTED:
            return True   # Always fire
        if entry.source == Source.INFERRED:
            return True   # Standard mode
        return False      # OBSERVED → skip

    def review(self, spec: BuildrootSpec, context: dict) -> list[Candidate]:
        result = spawn_claude_agent(
            task=self._build_task(spec, context),
            system_prompt=self.system_prompt,
            json_schema=CANDIDATE_RANKING_SCHEMA,
            allowed_tools=self._allowed_tools(),
            max_turns=10,
            max_budget_usd=2.0,
            timeout=300,
        )
        return self._parse_candidates(result)

    def apply_best(self, spec: BuildrootSpec, candidates: list[Candidate]) -> None:
        if candidates:
            self._update_spec(spec, candidates[0])
```

### Evidence Ranking Schema

From issue #24, agents rank proposals by evidence type (NOT self-assessed "confidence"):
1. **Direct observation** — file exists, API returns value, tag found in git ls-remote
2. **CI inference** — value from GitHub Actions / Jenkins / CircleCI
3. **Cross-reference** — multiple independent sources agree
4. **Historical pattern** — project's own conventions
5. **Ecosystem heuristic** — common practice
6. **Default** — last resort

```python
CANDIDATE_RANKING_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "value": {"type": "string"},
                    "evidence_type": {"type": "string", "enum": [
                        "direct_observation", "ci_inference", "cross_reference",
                        "historical_pattern", "ecosystem_heuristic", "default"
                    ]},
                    "evidence_citations": {"type": "array", "items": {"type": "string"}},
                    "reasoning": {"type": "string"},
                },
                "required": ["value", "evidence_type"]
            }
        },
        "field_updated": {"type": "string"},
    },
    "required": ["candidates", "field_updated"]
}
```

## 9. Benchmark Failure Category → Node Agent Mapping

From the issue spec's failure breakdown:

| Category | Count | % | Primary Agent | How Agent Fixes It |
|---|---|---|---|---|
| Multi-module / wrong directory | 8 | 26% | **Node 4: Repo Agent** | Identifies correct subdir for multi-module repos, adjusts clone + build |
| Base image not found | 6 | 19% | **Node 7: Image Agent** | Checks Docker Hub registry API for tag existence, finds alternatives |
| Build tool not found | 3 | 10% | **Node 9: Build Cmd Agent** | Detects gradlew vs mvn vs gradle, checks for mvnw presence |
| Containerfile syntax (unresolved props) | 2 | 6% | **Node 3: Property Agent** | Resolves remaining `${...}` from CI env vars, profiles, docs |
| Git tag not found | 2 | 6% | **Node 8: Tag Agent** | `git ls-remote --tags`, checks tag naming conventions |
| Build command / environment | 3 | 10% | **Node 9: Build Cmd Agent** | Cross-references CI config with detected build tool |
| L3 build failures | 2 | 6% | **L3 Failure Agent** | Reads Maven/Gradle build output, diagnoses compile/dep issues |
| L4 JAR mismatch | 1 | 3% | **L4 Failure Agent** | Diffs JAR contents, identifies timestamp/JDK/plugin issues |
| L4 pass (baseline) | 4 | 13% | — | No action needed |

**Total addressable: 24/27 failing packages (89%)** if all agents work correctly.

## 10. Specific Failure Details (from benchmark)

### Multi-module failures (8 packages) — Repo Agent target
Packages: tomcat-catalina, nimbus-jose-jwt, jetty-server, lz4-java, kafka-clients, snakeyaml, commons-beanutils, protobuf-java

Root cause: `discover_repo_from_pom()` finds the repo, but the POM is in a subdirectory. The generated Containerfile clones at root and runs `mvn clean install` at root, which fails because the target module's POM is in a subdirectory.

Repo Agent fix: Detect multi-module structure, identify the correct subdirectory, set `WORKDIR /build/<subdir>` in the Containerfile or add `-pl <module>` to the build command.

### Base image failures (6 packages) — Image Agent target
Packages: spring-boot, netty-buffer, jakarta.mail, assertj-core, snappy-java, junit

Root cause: The `JdkSpec.base_image` resolves to a tag that doesn't exist on Docker Hub (e.g., `eclipse-temurin:17-jdk` without OS suffix, or a version that was never published).

Image Agent fix: HTTP HEAD or Docker Hub registry API (`/v2/<image>/tags/list`) to verify tag existence. If missing, try alternative tags (same JDK, different OS suffix or vendor).

### Build tool failures (3 packages) — Build Cmd Agent target
Packages: json-smart, hibernate-validator, json-path

Root cause: Project uses Gradle (has `build.gradle`, `gradlew`) but the pipeline defaults to `mvn clean install -B`.

Build Cmd Agent fix: Check repo for `build.gradle`, `gradlew`, `settings.gradle`. If found, switch to `./gradlew build` or `gradle build`.

## 11. Cost & Performance Estimates

Current agent costs per invocation:
| Agent | Budget | Turns | Timeout | Typical Cost |
|---|---|---|---|---|
| Inner Builder (refine) | $5 | 10 | 600s | $1-3 |
| Inner Builder (diagnose) | $1 | 3 | 180s | $0.30 |
| Outer Researcher | $3 | 20 | 600s | $1-2 |
| Outer Strategist | $2 | 10 | 300s | $0.50 |

Node agents should be lightweight — most do simple lookups:
| Agent | Budget | Turns | Timeout | Expected Cost |
|---|---|---|---|---|
| Node agents (1-10) | $2 | 5-10 | 300s | $0.50-1.50 |
| Failure agents (L2/L3/L4) | $3 | 10 | 300s | $1-2 |

Full benchmark run:
- 31 packages × ~10 node agents × ~$1 each = ~$310 for node agents
- Plus ~5-10 failure agent calls per failing package = ~$150
- **Total estimated cost for full 31-package benchmark: $400-600**

Optimization: Only fire agents for DEFAULTED/INFERRED fields. The 4 L4-passing packages likely have mostly OBSERVED fields → fewer agent calls.

## 12. Critical Dependencies & Risks

| Dependency | Status | Risk |
|---|---|---|
| `spawn_claude_agent()` infrastructure | ✅ Proven, used by 4 agents | None |
| `GapDetector` field classification | ✅ Works, 6 checks | May need more checks for full coverage |
| `BuildrootSpec` mutability | ✅ Mutable dataclass | Fields like `source_repo`, `git_tag` are simple strings — easy to update |
| `ContainerfileGenerator` re-rendering | ✅ Can re-render from updated spec | Works |
| SSH to rh-h100-01 | ✅ Evaluator handles this | Must be reachable during benchmark |
| `--dangerously-skip-permissions` | ✅ Set in spawn_claude_agent | No change needed |
| Docker Hub API for Image Agent | New dependency | May have rate limits |
| `git ls-remote` for Tag Agent | Available via Bash tool | Requires network access |
| `MUTABLE_SURFACES` in guards.py | Needs update | Add new files to the set |

## 13. Summary of Gaps

| Gap | Severity | Resolution |
|---|---|---|
| No `NodeAgent` base class or implementations | **Critical** | Implement all 13 agents (10 node + 3 failure) |
| No `AgentAugmentedObserver` | **Critical** | New class wrapping Observer with agent layer |
| No benchmark CLI flag for agent mode | Medium | Add `--node-agents` flag to `agent_cmd.py` |
| `GapDetector` missing checks for repo, tag, image | Medium | Add `_check_source_repo`, `_check_git_tag`, `_check_base_image` |
| `MUTABLE_SURFACES` doesn't include new files | Low | Update `guards.py` after implementation |
| No per-node agent cost tracking | Low | Log cost from `AgentResult.cost_usd` |
| Template re-rendering path not exposed | Low | `ContainerfileGenerator` already supports this |
| No benchmark storage for agent-augmented results | Low | Use `results/benchmark-agents/` directory |
