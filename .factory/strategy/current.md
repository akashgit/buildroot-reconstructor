## Strategy — 2026-06-16

### Design Space
| Dimension | Score | Notes |
|---|---|---|
| Features | 4 | 9 kept experiments building pipeline from L1→L4, inner/outer loops, node agents |
| Bug fixes | 3 | Podman prefix, JDK suffix doubling, ENV syntax — addressed incrementally |
| Instrumentation | 2 | 60.6% observability score but only 19% function coverage; node agents uninstrumented |
| Flow changes | 4 | Major arch rewrites: inner loop (exp 6), outer loop (exp 7), Claude Code migration (exp 8), node agents (exp 9) |
| New agents | 5 | 13 agents now (10 node + 3 failure); heavily explored |
| Prompt engineering | 2 | Agent prompts written once, not systematically tuned from failure data |
| Eval improvements | 2 | L1-L4 scoring exists but error classifier produces only "unknown" classes |
| Knowledge management | 1 | No playbooks, no recipe store, no cross-run learning persistence |
| Infrastructure | 3 | rh-h100 multi-node benchmark infra works; SSH key issues on some nodes |
| Operational execution | 3 | 31-package benchmark ran once (exp 9); need re-run after architecture changes |
| Self-evolution | 1 | No feedback loops — agents can't learn from build outcomes |

**Underserved:** Knowledge management, Self-evolution, Prompt engineering

### Observations
- Current composite score: 0.530
- Weakest eval dimension: type_check (0.0, 61 errors)
- Last 3 experiments: #7 keep (outer loop), #8 keep (Claude Code migration), #9 keep (node agents)
- Pattern: All 9 experiments kept, zero reverts — steady architecture buildout. But the benchmark plateau at 22.6% L4 reveals that the agent system lacks learning: node agents fire once pre-build, fixes don't persist across iterations, and the error classifier is blind (all `unknown`). The 5 architectural gaps from issue #27 are confirmed by code-level analysis and validated by external research (ACE playbooks, CORAL parallel search, Chains-Rebuild reproducibility).
- The 6 L3 packages (bytecode matches, metadata doesn't) are low-hanging fruit — reproducible build flags could convert them all to L4.
- The 5 Podman short-name packages are a deterministic one-line fix in `jdk.py:299-304`.
- The AnalyzeAgent/playbook system is the centerpiece: it closes Gaps 1, 2, 3, and 5 by creating a feedback channel from build outcomes back to node agents.

### Hypotheses

#### H1: Agent architecture overhaul — feedback loops, multi-candidate builds, and runtime awareness
- **Category:** EXPLORE
- **Type:** mixed
- **Backlog item:** Agent architecture: fix feedback loops, multi-candidate builds, and runtime awareness (issue #27)
- **Addresses:** #27
- **What:** Implement all 6 priorities from the issue spec as one coherent architectural change:

  **P1 — Top-K parallel candidate builds (Gap 4):** Replace `apply_best()` in `base.py:117-126` with `apply_top_k(spec, candidates, k=3)` returning K (spec, containerfile) pairs. Fork the spec K times, render K Containerfiles, run K parallel `podman build` subprocesses, evaluate each, keep the winner, store losers in dead_ends. The AnalyzeAgent sees all K outcomes for comparative analysis.

  **P2 — Per-cycle AnalyzeAgent with ACE-like playbooks (Gaps 1, 2, 5):** New `AnalyzeAgent` class as a Claude Code subprocess (`spawn_claude_agent()`, budget $2, timeout 300s). Runs after each failed iteration cycle — receives build logs from all K candidates, current Containerfiles, eval output, and node agent decision log. Diagnoses root cause, traces it to the responsible node agent, writes append-only DO/DON'T playbook entries to `.factory/playbooks/node_agents/{agent_name}.md` with helpful/harmful counters (ACE pattern from Zhang 2025). Node agents read their playbook file on each activation. Structured output schema: `{ root_cause, responsible_agent, playbook_updates[], spec_overrides{}, is_systemic }`.

  **P3 — Tiered recipe store:** Save recipes at every successful level to `.factory/recipes/{coordinate}.json` containing the Containerfile, spec_overrides, agent decisions, and iterations count. Future runs check for existing recipes: L4 → skip, L3 → focus on JAR matching flags, L2 → skip container debugging. The 12 L2-stuck packages get a checkpoint.

  **P4 — Spec overrides persistence (Gap 3):** Add `spec_overrides: dict[str, Any]` that persists across iterations within a package's build loop. After `Observer.observe()` regenerates the spec deterministically, overrides are applied before node agents fire. Managed by the AnalyzeAgent — ensures fixes survive the deterministic pipeline reset. This directly fixes the kafka-clients smoking gun (same Podman short-name error repeating 15 times).

  **P5 — Podman registry prefix:** In `JdkResolver._map_distribution_to_image()` at `jdk.py:299-304`, always emit `docker.io/library/` prefix for Docker Hub images. One-line deterministic fix that immediately unblocks kafka-clients, assertj-core, json-smart, protobuf-java, hibernate-validator (5 packages).

  **P6 — Reproducible build flags:** Add `-Dproject.build.outputTimestamp` to Maven build commands for L3+ packages. Normalize JAR comparison by stripping non-semantic metadata (MANIFEST.MF `Built-By`/`Created-By`/timestamps, pom.properties build path comments). Targets conversion of 6 L3 packages (jackson-core, nimbus-jose-jwt, jakarta.mail, commons-beanutils, commons-fileupload, jersey-common) to L4.

  **Inner loop restructure:** Modify `loop.py` to re-run `observe()` with accumulated spec_overrides on each iteration (currently only runs once). Remove the `failure_agent_used` single-fire gate at `loop.py:83` — failure diagnosis is now handled by the AnalyzeAgent which runs every cycle. Update `should_activate()` in `base.py:93-98` to also activate on fields where `spec_overrides` exist or the AnalyzeAgent has flagged for review, not just DEFAULTED/INFERRED.

- **Execution step:** After code changes are implemented and eval passes, deploy to rh-h100 nodes via rsync, run the full 31-package benchmark (`buildroot agent --batch` split across rh-h100-01 through rh-h100-06+), collect results, merge best-per-package, generate `results/benchmark-agents-merged/summary.json`. Compare L4 solve rate against exp 9 baseline (7/31 = 22.6%).
- **Expected output:** `results/benchmark-agents-merged/summary.json` with L4 solve rate measured. Target: ≥35% (11/31). Playbook files at `.factory/playbooks/node_agents/`. Recipe store at `.factory/recipes/`.
- **Why:** The exp 9 benchmark proved node agents add value (+10pp over deterministic baseline) but revealed that agents can't learn from build failures (Gap 1), can't fix OBSERVED-but-wrong data (Gap 2), lose fixes across iterations (Gap 3), discard alternative candidates (Gap 4), and have no knowledge transfer between failure diagnosis and node activation (Gap 5). External research validates: ACE playbooks (Zhang 2025) show append-only rules with helpful/harmful counters converge over time; CORAL shows parallel exploration without coordination outperforms sequential when evaluation is cheap relative to generation; Chains-Rebuild (Sharma FSE 2026) identifies the exact 6 root causes of Java unreproducibility and their canonicalization fixes. The 5 Podman prefix packages and 6 L3→L4 metadata packages are deterministic fixes worth +11 packages alone if they land.
- **Expected impact:** capability_surface +0.1 (new AnalyzeAgent, recipe store, playbook system = new modules/functions), L4 solve rate 22.6% → ≥35%, observability indirectly improves (AnalyzeAgent writes structured diagnosis logs). Fixes type_check and lint regressions as part of the PR cleanup. P5 alone fixes 5 packages; P6 targets 6 more; P1+P2+P4 close the learning gaps for the remaining hard packages.
- **Priority:** high

### Anti-patterns to Avoid
- **Don't let Builder rewrite entire Containerfiles** — exp 9 showed the Builder's whole-file rewriting causes regressions on solved packages (issue #22). The AnalyzeAgent + spec_overrides approach surgically updates specific fields instead.
- **Don't mock E2E runs** — experiments 8 taught this lesson. The 31-package benchmark on rh-h100 nodes is mandatory. Code-only completion is not acceptable.
- **Don't fire AnalyzeAgent without early termination** — at $2/call × 15 iterations × 31 packages = $930 worst case. Must implement stagnation detection: if ≥3 consecutive iterations produce no level improvement, stop iterating on that package and move on.
- **Don't repeat the error classifier blindness** — analyzer.py currently classifies all errors as `unknown`. The AnalyzeAgent's structured diagnosis replaces this, but don't delete the existing classifier — extend it so non-agent mode still works.
- **Don't break non-agent mode** — the `--node-agents` flag gates agent behavior. All P1-P4 changes must be behind this flag. P5 and P6 apply universally (they're deterministic fixes).

### New Backlog Items
(none — targeted mode, no new items)
