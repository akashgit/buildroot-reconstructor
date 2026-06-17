## Strategy — 2026-06-15

### Observations
- Current composite score: 0.5651
- Weakest eval dimension: type_check (0.0), lint (0.3), capability_surface (0.41)
- Last 3 experiments: #6 keep (inner loop MVP), #7 keep (outer loop intelligence), #8 keep (Claude Code migration)
- Pattern: 8/8 experiments kept, zero reverts — strong execution track record. Agentic solve rate stagnated at 33.3% (1/3 smoke packages). Deterministic baseline is 4/31 L4 (13%). The inner loop approach is fundamentally limited by giving the LLM full Containerfile control — prose contamination caused 90% of wasted iterations. Node-scoped agents attack the root cause by reviewing structured data at each pipeline step instead of rewriting entire Containerfiles.
- Benchmark failure categories are well-characterized: multi-module (8), base image (6), build tool (3), unresolved props (2), git tag (2), build command/env (3). Each maps to a specific pipeline node.
- Infrastructure ready: `spawn_claude_agent()` from exp 8, SSH evaluator to rh-h100-01, GapDetector with OBSERVED/INFERRED/DEFAULTED classification.

### Hypotheses

#### H1: Node-scoped agents — Claude Code reviewer at every pipeline step
- **Category:** EXPLORE
- **Type:** mixed
- **Backlog item:** Node-scoped agents: Claude Code reviewer at every pipeline step (issue #24)
- **Addresses:** #24
- **What:** Implement 13 Claude Code reviewer agents (10 node agents + 3 post-build failure agents) integrated into the deterministic pipeline, plus a full benchmark run on all 31 packages.

  **Code deliverables:**
  1. `NodeAgent` base class (`src/buildroot/agent/node_agents/base.py`) — system prompt templating, context injection, candidate ranking with evidence hierarchy (direct observation > CI inference > cross-reference > historical pattern > ecosystem heuristic > default), structured output via `spawn_claude_agent()` with JSON schema
  2. 10 node agent implementations (`src/buildroot/agent/node_agents/`):
     - **Node 1 — POM Agent**: relocation detection, sparse POM detection
     - **Node 2 — Parent Chain Agent**: missing parents, BOM import validation
     - **Node 3 — Property Agent**: resolve remaining `${...}` via CI env vars, profiles, docs (fixes hibernate-core, postgresql)
     - **Node 4 — Repo Agent**: URL validation, multi-module subdirectory detection, GitHub API search (fixes 8 packages — highest impact)
     - **Node 5 — CI Agent**: correct workflow selection, alternative CI systems (Jenkins, Makefile, BUILDING.md)
     - **Node 6 — JDK Agent**: cross-reference POM compiler settings, CI matrix, .java-version, JAR manifest
     - **Node 7 — Image Agent**: Docker Hub registry API tag verification, alternative tag search (fixes 6 packages)
     - **Node 8 — Tag Agent**: `git ls-remote --tags` verification, tag naming convention detection (fixes guava, jersey-common)
     - **Node 9 — Build Command Agent**: build tool detection (mvnw/mvn/gradle/gradlew), flag validation (fixes json-smart, hibernate-validator, json-path)
     - **Node 10 — Template Agent**: rendered Containerfile syntax validation, unresolved placeholder detection, last gate before emission
  3. 3 post-build failure agents (`src/buildroot/agent/node_agents/failure_agents.py`):
     - **L2 Failure Agent**: container build log diagnosis → Containerfile fix proposals
     - **L3 Failure Agent**: Maven/Gradle output diagnosis → build command fixes
     - **L4 Failure Agent**: JAR diff analysis → reproducibility issue identification
  4. `AgentAugmentedObserver` (`src/buildroot/agent/augmented_observer.py`) — wraps existing `Observer`, runs deterministic pipeline → GapDetector → fires node agents per gap status → re-renders Containerfile with updated spec
  5. CLI integration: `--node-agents` flag on the existing `agent` CLI command to enable the agent-augmented pipeline
  6. Candidate ranking JSON schema using evidence-type-based hierarchy (not self-assessed confidence)
  7. Cost-conscious agent configuration: Sonnet model for node reviewers (~$0.25-0.50/agent), 5-10 max turns, 120s timeout. Opus reserved for failure agents that need deeper reasoning.

  **Operational deliverable:**
  - Full benchmark run on all 31 packages on rh-h100-01 with L1-L4 evaluation
  - Results stored in `results/benchmark-agents/summary.json`
  - Comparison table: baseline (4/31 L4) vs post-agents for every package

- **Execution step:** After code implementation and unit tests pass, run on rh-h100-01:
  ```
  python -m buildroot agent --batch results/packages_benchmark.txt --host rh-h100-01 --output results/benchmark-agents/ --node-agents --max-iterations 15
  ```
  Then generate comparison report against `results/benchmark-full/summary.json` baseline.

- **Expected output:** `results/benchmark-agents/summary.json` with per-package L1-L4 results. Comparison table showing delta from baseline (4/31 L4 = 13%).

- **Why:** The deterministic pipeline fails on 24/27 packages at L2 due to well-characterized error categories that map 1:1 to specific pipeline nodes. The inner loop approach (experiments 6-8) hit a ceiling at 33.3% because it gives the LLM full Containerfile control, causing prose contamination in 90% of iterations. Node-scoped agents attack the root cause: each agent reviews structured data (repo URL, JDK version, git tag) at its pipeline step, not entire Containerfiles. The infrastructure is ready — `spawn_claude_agent()`, SSH evaluator, GapDetector — and the failure mapping is precise (Repo Agent addresses 8 packages, Image Agent addresses 6, Build Cmd Agent addresses 3). This is the highest-leverage single change available.

- **Expected impact:**
  - capability_surface: 0.41 → 0.50+ (13 new agent modules + augmented observer + CLI flag = ~30+ new public functions)
  - L2 build rate: 7/31 (23%) → 18-23/31 (58-74%) — if node agents fix most multi-module (6/8), base image (5/6), build tool (2/3), property (2/2), and tag (1/2) failures
  - L4 match rate: 4/31 (13%) → 8-15/31 (26-48%) — after L3/L4 attrition from post-build issues
  - observability: 0.61 → 0.65+ (agents log their activations, evidence citations, and corrections via structlog)

- **Priority:** high

### Anti-patterns to Avoid
- **Prose-wrapped Containerfile output** — the dominant failure mode from experiments 6-8. Node agents avoid this entirely by reviewing structured data fields, not generating Containerfiles from scratch.
- **Framework-first delivery** — issue #24 explicitly prohibits phased delivery. "Framework without agents" or "agents without benchmark" is incomplete. All 13 agents + benchmark must ship together.
- **Mocked E2E tests** — per user feedback (feedback-e2e-mandatory.md, feedback-mandatory-e2e.md), real E2E on rh-h100-01 is mandatory after any pipeline change. Token cost is never a valid skip reason.
- **Self-assessed confidence** — agents must rank by evidence type (direct observation > CI inference > ... > default), not output a "confidence: 0.85" score. The issue spec is explicit about this.
- **Expensive agent configuration** — node reviewers should use Sonnet (~$0.25-0.50 each), not Opus. Total benchmark cost should stay under $400-600 for 31 packages. Only failure agents warrant higher budgets.
- **Regression on passing packages** — the 4 L4-passing packages (jackson-databind, commons-lang3, plexus-utils, jettison) must continue to pass. Agent augmentation must not corrupt working Containerfiles.
