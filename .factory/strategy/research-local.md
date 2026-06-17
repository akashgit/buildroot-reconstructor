# Local Architecture Analysis — Issue #27

## Executive Summary

The buildroot reconstructor has a well-structured agent pipeline (exp 9) with 10 node agents and 3 failure agents, achieving 7/31 L4 (22.6%). Issue #27 identifies 5 architectural gaps. This analysis maps each gap to specific code locations, traces the data flow through the pipeline, and identifies where each proposed fix fits.

---

## 1. Current Architecture — Data Flow

```
run_inner_loop()  [loop.py:42-201]
  │
  ├── Observer.observe()  [observer.py:21-33]
  │   └── BuildrootOrchestrator.reconstruct()  → (spec, containerfile)
  │
  ├── [if node_agents] AgentAugmentedObserver.observe()  [augmented_observer.py:40-72]
  │   ├── super().observe()  → deterministic pipeline
  │   ├── GapDetector.analyze(spec)  → gap_report
  │   ├── for agent in ALL_NODE_AGENTS:
  │   │     if agent.should_activate(gap_report):
  │   │       candidates = agent.review(spec)
  │   │       agent.apply_best(spec, candidates)  ← PICKS ONLY ONE
  │   └── re-render Containerfile from updated spec
  │
  ├── for t in range(max_iterations):          [loop.py:84-195]
  │   ├── evaluator.evaluate(containerfile)     → EvalResult
  │   │
  │   ├── [if node_agents and t==0 and failed]
  │   │   └── observer.run_failure_agents()     [augmented_observer.py:100-141]
  │   │       ├── L2/L3/L4FailureAgent.diagnose()
  │   │       └── agent.apply_fixes(spec)
  │   │       └── re-render Containerfile
  │   │
  │   ├── analyzer.analyze(eval_result)         → AnalysisResult
  │   ├── analyzer.update_dead_ends()
  │   │
  │   └── based on ProgressSignal mode:
  │       ├── exploit → builder.refine()        [builder.py:400-479]
  │       ├── explore → builder.explore()       [builder.py:481-561]
  │       └── meta_shift → builder.fresh_start()
  │
  └── return LoopResult
```

### Key Observation: Two Disconnected Fix Systems

The pipeline has TWO independent fix mechanisms that don't talk to each other:

1. **Node agents** (pre-build): `augmented_observer.py` — review spec fields, propose candidates, `apply_best()` picks one. Run ONCE before any builds.

2. **Inner loop builder** (post-build): `loop.py:84-195` — on failure, the Builder agent rewrites the entire Containerfile. Uses `analyzer.py` for error classification and dead-end tracking, but NOT the node agent system.

The Builder (inner loop iterations 1-14) operates as a standalone Containerfile rewriter. It doesn't know which node agent made which decision, can't update the spec, and can't leverage alternative candidates the node agents generated.

---

## 2. Gap Analysis — Code-Level Mapping

### Gap 1: Agents run pre-build only — no failure feedback

**Location:** `augmented_observer.py:40-72` — `observe()` is called once at the top of `loop.py:69`.

**Problem:** Node agents fire in `observe()` → build → evaluate → if build fails, the Builder (a Containerfile rewriter) handles iterations. Node agents never see build results.

**Failure agents partially address this:** `loop.py:100-122` calls `run_failure_agents()` after the FIRST evaluation (t==0 only). But:
- It only fires once (`failure_agent_used` flag at `loop.py:83`)
- It modifies the spec and re-renders, but subsequent iterations use the Builder's Containerfile rewriting, not the spec-based system
- No feedback flows back to node agents

**Where AnalyzeAgent fits:** After `evaluator.evaluate()` returns a failure, before the Builder rewrites. The AnalyzeAgent would:
1. Trace the failure to the responsible node agent's decision
2. Write playbook entries for that agent
3. Update `spec_overrides` for the next iteration
4. On the next iteration, `observe()` would re-run with playbook guidance

This requires changing the inner loop to re-run `observe()` with accumulated knowledge, not just let the Builder rewrite the raw Containerfile.

### Gap 2: `should_activate()` blocks agents from fixing OBSERVED-but-wrong values

**Location:** `base.py:93-98`

```python
def should_activate(self, gap_report: GapReport) -> bool:
    for entry in gap_report.entries:
        if entry.field == self.field_name or entry.field.startswith(self.field_name):
            if entry.source in (Source.DEFAULTED, Source.INFERRED):
                return True
    return False
```

**Problem:** If CI data sets a field as `Source.OBSERVED`, the agent never fires. But OBSERVED doesn't mean CORRECT — CI data might say Maven when the project uses Gradle (lz4-java case).

**Fix:** The AnalyzeAgent should be able to force-activate agents by writing spec_overrides or by marking OBSERVED fields as "needs review" after a build failure traces back to that field.

### Gap 3: Fixes don't persist across iterations

**Location:** `loop.py:84-195` — each iteration of the inner loop.

**Problem:** The inner loop does NOT re-run `observe()` on iterations 2+. The Builder takes the previous Containerfile and mutates it. So failure agent fixes DO survive within the Builder's mutation chain. But if the AnalyzeAgent wants to change a spec field for a re-observation, there's no mechanism for that.

**The real persistence problem:** The inner loop has no concept of "accumulated spec overrides." Each run of the inner loop starts fresh from `observe()`.

**Fix:** Add a `spec_overrides: dict` parameter to `run_inner_loop()`. After `observe()`, apply overrides before entering the iteration loop. The AnalyzeAgent writes overrides; the recipe store persists them.

### Gap 4: `apply_best()` picks one candidate — discards alternatives

**Location:** `base.py:117-126`

```python
def apply_best(self, spec: BuildrootSpec, candidates: list[Candidate]) -> bool:
    if not candidates:
        return False
    best = sorted(candidates, key=lambda c: c.rank)[0]
    self._apply_candidate(spec, best)
    return True
```

**Problem:** Agents generate ranked lists of candidates (the schema supports arrays), but only the top-ranked one is used. If it fails at build time, the alternatives are lost.

**Fix — Top-K forking:** Replace `apply_best()` with `apply_top_k(spec, candidates, k=3)` returning K (spec, containerfile) pairs. The inner loop evaluates all K in parallel, picks the best.

**Implementation complexity:** This is the most invasive change. It requires:
1. `apply_top_k()` on `NodeAgent` base class — return K spec copies with different candidate values applied
2. `ContainerfileGenerator` called K times to produce K Containerfiles
3. `Evaluator` called K times (can be parallelized via K SSH subprocesses)
4. Picking the best result and discarding losers
5. Changes to `run_inner_loop()` to handle branching

### Gap 5: Failure agents and node agents are disconnected

**Location:** `failure_agents.py` vs `node_agents/base.py`

**Failure agents:**
- Are NOT subclasses of `NodeAgent`
- Have their own `_BaseFailureAgent` base class (`failure_agents.py:64`)
- Operate on (spec, containerfile, build_log) → structured `FailureDiagnosis` with fixes
- Apply fixes directly to spec fields via `apply_fixes()` (`failure_agents.py:91-123`)
- Called from `augmented_observer.py:run_failure_agents()` — once, after first evaluation

**Node agents:**
- Subclass `NodeAgent` (`base.py:80`)
- Operate on (spec, gap_report) → `Candidate` list
- Called from `augmented_observer.py:observe()` — once, before any build
- Have evidence hierarchy, but no knowledge of build results

**The disconnect:** A failure agent might correctly diagnose "Podman needs docker.io/library/ prefix" and fix the base_image. But the image_agent doesn't learn this. Next time the image_agent fires (on a different package), it'll make the same mistake.

**AnalyzeAgent as the bridge:** The AnalyzeAgent would:
1. See the failure agent's diagnosis
2. Attribute it to the image_agent's decision
3. Write a playbook entry: "DON'T: bare Docker Hub names without docker.io/library/ prefix"
4. On the next package (or next outer loop cycle), the image_agent reads its playbook and adjusts

---

## 3. The AnalyzeAgent — Design & Placement

The AnalyzeAgent is the **central new component** from issue #27. It's a Claude Code subprocess agent that runs after each failed evaluation cycle. It's NOT the existing `analyzer.py` (which is a regex-based error classifier).

### Inputs
- Build logs from all K candidates this cycle
- Containerfiles tried + level reached per candidate
- Current node agent playbooks (`.factory/playbooks/node_agents/`)
- Which pipeline node agent made which decision (from spec.gaps / agent activation log)
- Current spec_overrides

### Outputs
- Playbook entries written to `.factory/playbooks/node_agents/{agent_name}.md`
- Updated spec_overrides for next iteration
- Recipe entries for `.factory/recipes/{coordinate}.json`

### Proposed inner loop flow
```
loop.py iteration flow (proposed):
  evaluate() → EvalResult
  if success → save recipe, return
  if fail:
    AnalyzeAgent.analyze(eval_results, candidates_tried)
      → writes playbook entries
      → updates spec_overrides
      → saves recipe if L2+
    if re-observe mode:
      observe(spec_overrides, playbook_dir) → new (spec, containerfile)
      → re-run node agents with playbook guidance
    else:
      builder.refine/explore/fresh_start → mutated containerfile
```

### Relationship to existing `analyzer.py`

The existing `analyzer.py` provides:
- `classify_error()` — regex-based error classification (17 patterns at `analyzer.py:14-98`)
- `estimate_build_progress()` — Maven lifecycle phase tracking (`analyzer.py:208-221`)
- `extract_root_cause_details()` — specific entity extraction (`analyzer.py:224-243`)
- `detect_error_loop()` — oscillation detection (`analyzer.py:361-387`)
- `build_remediation_context()` — prompt section builder (`analyzer.py:390-448`)
- `analyze()` — full analysis → `AnalysisResult` (`analyzer.py:460-498`)
- Dead-end registry management (`analyzer.py:501-522`)

The existing analyzer is purely regex/heuristic. The AnalyzeAgent is an LLM-powered agent that uses these heuristic signals as inputs but performs deeper reasoning:
- Traces failures to responsible pipeline nodes
- Generates playbook instructions (natural language, not just error classes)
- Makes cross-iteration strategic decisions (when to re-observe vs. when to let Builder iterate)

**Recommendation:** Keep `analyzer.py` as the heuristic layer. Create `analyze_agent.py` as the LLM layer that wraps it.

---

## 4. Recipe / Checkpoint Mechanism

**Current state:** No recipe/checkpoint mechanism exists. Each `run_inner_loop()` starts fresh from `observe()`. The outer loop (`outer_loop.py:167-399`) runs batch → analyze → research → strategize → implement → guards → verdict, but at the code-change level (modifying the pipeline's Python code), not the per-package level.

**What issue #27 proposes:** A per-package recipe store at `.factory/recipes/{coordinate}.json`:
```json
{
  "coordinate": "org.json:json:20231013",
  "level_reached": 4,
  "containerfile": "FROM docker.io/library/eclipse-temurin:17-jdk ...",
  "spec_overrides": {"base_image": "docker.io/library/eclipse-temurin:17-jdk"},
  "agent_decisions": {"image_agent": "...", "build_cmd_agent": "..."},
  "iterations_to_solve": 2
}
```

Tiered reuse:
- L4 recipe exists → skip entirely
- L3 recipe → start from L3 config, focus on JAR matching flags
- L2 recipe → start from L2 config, skip container debugging

This is entirely new infrastructure. Needs:
1. A recipe data model (in `models.py`)
2. Save logic after each evaluation in the inner loop
3. Load logic at the start of `run_inner_loop()` — check recipe store, start from checkpoint

---

## 5. Node Agent Specific Issues

### Agents with known failure-traced issues

**`image_agent.py`** — Gap 1 manifestation. Validates Docker Hub tag existence but doesn't know Podman needs `docker.io/library/` prefix. Caused 5 L2 failures (kafka-clients, assertj-core, json-smart, protobuf-java, hibernate-validator). Fix needs both:
1. Deterministic: always prefix `docker.io/library/` in `generators/containerfile.py`
2. Agent: AnalyzeAgent writes playbook entry after Podman short-name failure

**`build_cmd_agent.py`** — Gap 2 manifestation. Trusts OBSERVED CI data even when wrong (lz4-java: CI says Maven, project uses Gradle). Fix: AnalyzeAgent force-activates after build failure shows wrong build system.

**`template_agent.py`** — Gap 1 manifestation. Validates Containerfile syntax pre-build but can't catch runtime issues. hibernate-core: `ENV JAVA_OPTS -Xmx4g` instead of `ENV JAVA_OPTS="-Xmx4g"` — generated by failure agent, not caught by template_agent on re-render.

**`tag_agent.py`** — Works well for tag discovery, but alternatives discarded by `apply_best()`. Top-K would let it try multiple tag formats.

---

## 6. Implementation Impact Assessment

### P1: Top-K parallel candidate builds (Gap 4)
**Files to change:**
- `node_agents/base.py` — add `apply_top_k()` method
- `augmented_observer.py` — return K (spec, containerfile) pairs
- `loop.py` — handle K candidates per iteration, evaluate all, pick best
- `models.py` — add fields to track which candidate was used

**Complexity:** High. Changes the observer↔loop contract fundamentally.

### P2: AnalyzeAgent + playbooks (Gaps 1, 2, 5)
**Files to create:**
- `src/buildroot/agent/analyze_agent.py` — new Claude Code subprocess agent
- `.factory/playbooks/node_agents/` directory

**Files to change:**
- `loop.py` — call AnalyzeAgent after failed evaluation
- `augmented_observer.py` — pass playbook_dir to node agents
- `node_agents/base.py` — read playbook in `_build_task()`

**Complexity:** Medium. New agent follows established `spawn_claude_agent()` pattern.

### P3: Tiered recipe store
**Files to create/change:**
- `models.py` — `Recipe` dataclass
- `loop.py` — load/save recipes

**Complexity:** Low-Medium.

### P4: Spec overrides persistence (Gap 3)
**Files to change:**
- `loop.py` — add spec_overrides parameter
- `augmented_observer.py` — accept and apply overrides

**Complexity:** Low.

### P5: Podman registry prefix (deterministic)
**Files to change:**
- `src/buildroot/generators/containerfile.py` — prefix `docker.io/library/`

**Complexity:** Very low.

### P6: Reproducible build flags
**Files to change:**
- `src/buildroot/generators/containerfile.py` — add `-Dproject.build.outputTimestamp`
- Possibly `src/buildroot/utils/jar_comparator.py` — normalize MANIFEST.MF

**Complexity:** Low.

---

## 7. Recommended Implementation Order

Issue #27 proposes P1→P6 priority. Based on code analysis, recommended order for maximum impact:

1. **P5** (Podman prefix) — trivial fix, unblocks 5 L2-stuck packages immediately
2. **P4** (spec overrides) — required infrastructure for P2
3. **P2** (AnalyzeAgent + playbooks) — the core learning loop, bridges gaps 1/2/5
4. **P3** (recipe store) — checkpointing, prevents re-solving
5. **P6** (reproducible build flags) — unblocks L3→L4 conversion for 6 packages
6. **P1** (Top-K) — highest complexity, highest potential, needs P2 to be maximally effective

P5+P4+P6 alone could push from 7/31 to ~15/31 L4 (5 Podman fixes + ~3-4 L3→L4 conversions). P2+P3 then enable iterative learning.

---

## 8. Key Code Patterns to Preserve

- **Claude Code subprocess pattern:** All agents use `spawn_claude_agent()` from `claude_runner.py`. The AnalyzeAgent must follow this.
- **Structured output via JSON schema:** Node agents return `CANDIDATE_SCHEMA` (`base.py:23-48`), failure agents return `FAILURE_FIX_SCHEMA` (`failure_agents.py:19-46`). The AnalyzeAgent needs its own schema for playbook entries + spec overrides.
- **Spec mutation pattern:** Changes flow through `BuildrootSpec` → `ContainerfileGenerator.generate()` → Containerfile text. The Builder bypasses this (rewrites raw Containerfile) — that's the source of Gap 3.
- **GapReport/GapEntry pattern:** Activation uses `GapReport`. Force-activation should add synthetic gap entries, not bypass `should_activate()`.
- **Evidence hierarchy:** `EVIDENCE_HIERARCHY` at `base.py:14-21` — used for candidate ranking. The AnalyzeAgent's playbook entries should note which evidence type failed.
