## Strategy — 2026-06-20

### Observations
- Current composite score: 0.608
- Weakest eval dimension: capability_surface (0.411)
- Last 3 experiments: #16 [keep], #17 [keep], #18 [keep] — all kept, strong momentum
- Pattern: v3 pipeline is mature and stable (9/31 packages solved at L4). The ceiling is structural — template-bound pipeline can't express multi-stage builds, custom tooling, or OSGI wrapping. 22 packages are L3-stuck with no path forward under v3. Issue #60 is the architectural breakthrough needed to unlock them.
- The codebase is ~85% ready for v4 (local research confirms). Missing pieces are cleanly isolated: 6 new files, no breaking changes to v3.
- Bouncy Castle proved the concept: a human (Claude Code session) reached 0.9998 in 4 iterations by writing raw Containerfiles and using eval directly — exactly what the orchestrator agent will do autonomously.
- CEO review explicitly requires Python subprocess approach (not Workflow), matching existing `claude_runner.py` patterns from experiments #008-#018.
- Targeted mode: single hypothesis for issue #60 (v4 agent-as-orchestrator).

### Hypotheses

#### H1: Implement v4 agent-as-orchestrator — all 4 phases (issue #60)
- **Category:** EXPLORE
- **Type:** code
- **Backlog item:** solve issue 60, read it carefully and make sure you implement it in full and test it as the issue describes, dont allow any agent to take shortcuts
- **Growth dimension:** capability_surface
- **Addresses:** #60
- **What:** Implement all 4 phases of issue #60 in a single PR. The v3 pipeline becomes a tool the orchestrator uses — v3 is not replaced, it is wrapped.

  **Phase 1 — Expose v3 as callable tool + standalone eval CLI:**
  - Add `buildroot eval <containerfile> <coordinate> --host <host>` CLI command in `src/buildroot/cli/commands/eval_cmd.py` (~80-100 lines). Wraps `Evaluator.evaluate()` to return JSON: `{l1_parse, l2_build, l3_command, l4_score, comparison_report, reward}`. The orchestrator agent calls this to evaluate raw Containerfiles it writes directly.
  - Ensure v3 pipeline supports per-iteration calling via `buildroot v3 <coord> --max-iterations 1 --workspace <path>`. Verify existing `pipeline_v3.py` already supports `max_iterations` + `workspace` parameters (research confirms it does). Add workspace artifact output (score, CF, comparison report as files) if not already present, so the orchestrator can read results after each iteration.

  **Phase 2 — Orchestrator agent (`meta_agent.py` + `meta_prompt.py`):**
  - Create `src/buildroot/agent/meta_agent.py` (~200-300 lines): Orchestrator outer loop.
    - `run_orchestrator(coordinate, host, workspace, target_score=0.98, max_budget_usd=15.0)` — main entry point.
    - Spawns a Claude Code agent via `claude_runner.spawn_claude_agent()` with the system prompt from `meta_prompt.py`.
    - Before spawning, gathers context: runs `prepass.run_prepass(coordinate, workspace)` for pre-pass findings, queries KB via `retrieval.query_kb()` for relevant entries.
    - The spawned agent drives the entire loop — it decides when to use v3 (via `buildroot v3 <coord> --max-iterations 1 --workspace <path>`), when to take over and write raw Containerfiles (evaluating via `buildroot eval <cf> <coord>`), and when it's done (score ≥ target).
    - Agent has full tool access: Bash (for CLI commands, SSH, file operations), Read (workspace artifacts), WebSearch/WebFetch (package research), Edit/Write (Containerfile authoring).
    - Termination conditions: score ≥ target, budget exhausted, agent decides it's stuck (3 consecutive iterations with no score improvement).
    - After success: triggers learning loop (Phase 4) to record winning approach to KB.
  - Create `src/buildroot/agent/meta_prompt.py` (~300-400 lines): Domain expert system prompt builder.
    - `build_meta_prompt(coordinate, prepass_findings, kb_entries, workspace)` — returns the complete system prompt string.
    - Domain expertise sections: JAR structure and bytecode versioning, build systems (Maven/Gradle/Ant — flags, plugins, profiles), OSGI bundles (Bnd wrapping, Export-Package, Bundle-SymbolicName), code signing, multi-release JARs, Apache reproducibility flags (project.build.outputTimestamp, SOURCE_DATE_EPOCH=0).
    - v3 template knowledge: what the template can express (build commands, system packages, env vars, config files, post-build commands), what it CAN'T express (multi-stage builds, external tool downloads, cross-stage artifacts, custom JDK binaries, Bnd wrap steps). This tells the agent when to let v3 handle it vs when to take over.
    - Tool documentation: `buildroot v3 <coord> --max-iterations 1 --workspace <path>` (runs one v3 iteration, reads workspace for results), `buildroot eval <cf> <coord> --host <host>` (evaluates any Containerfile, returns JSON score), `buildroot kb search <query>` / `buildroot kb list` (query knowledge base).
    - Eval infrastructure: L1 (parse) → L2 (build) → L3 (command runs) → L4 (comparison score). Scoring formula. Comparison report format (structural, metadata, bytecode sections). What each level failure means and how to fix it.
    - Dynamic context injection: pre-pass findings formatted via `PrePassFindings.to_prompt()`, KB entries formatted with their full content, workspace state (if warm-starting from prior attempt).
    - Strategy guidance: "Start with v3 for standard Maven/Gradle builds. Monitor score after each iteration. If score improves, let v3 continue. If stagnated (same score 2+ iterations) or template can't express what's needed (multi-stage, OSGI, custom tools), take over: write a Containerfile directly, evaluate via `buildroot eval`, iterate. Use KB tips/tricks for known patterns."
  - CLI entry point: `buildroot agent <coord>` spawns the orchestrator. `buildroot agent <coord> --v3-only` runs v3 pipeline directly (backward compat). Add to `src/buildroot/cli/commands/agent_cmd.py` (modify existing file — it already has agent command scaffolding).

  **Phase 3 — Knowledge Base (YAML templates/tips/tricks + retrieval):**
  - Create `src/buildroot/agent/knowledge/schema.py` (~100-150 lines): YAML schema for 3 entry types.
    - `KBEntry` dataclass with fields: `name` (unique kebab-case), `type` (template|tip|trick), `tags` (list), `build_systems` (list), `trigger_patterns` (list of dicts: `{manifest_has: str}` or `{error_matches: str}`), `success_rate` (float), `times_used` (int), `coordinate` (optional dict with `group_id`, `artifact_id`), `content` (markdown body).
    - `TemplateEntry(KBEntry)`: adds `containerfile` (full Containerfile text), `stages` (int), `characteristics` (list: osgi, multi-release, signing, etc.).
    - `TipEntry(KBEntry)`: adds `trigger` (when to apply), `solution` (what to do), `caveats` (list of warnings).
    - `TrickEntry(KBEntry)`: adds `error_pattern` (regex), `fix` (what to change), `root_cause` (why it happens).
    - `load_entry(path)` and `save_entry(entry, directory)` — parse/write YAML frontmatter + markdown body files.
  - Create `src/buildroot/agent/knowledge/retrieval.py` (~150-200 lines): Query function with ranked retrieval.
    - `query_kb(kb_dir, build_system=None, manifest_keys=None, error_pattern=None, group_id=None)` — scans `*.md` files in `kb_dir`, filters by build_system, matches trigger_patterns against manifest_keys and error_pattern, matches group_id for coordinate similarity.
    - Scoring: exact tag match (+10), partial tag match (+5), group_id match (+3), trigger_pattern regex match (+8), text keyword match (0-5). Returns entries sorted by score descending, capped at top 10.
    - `format_kb_results(entries)` — formats matched entries for injection into system prompt.
  - Create `src/buildroot/cli/commands/kb_cmd.py` (~120-150 lines): CLI commands.
    - `buildroot kb list` — lists all KB entries with name, type, tags, success_rate.
    - `buildroot kb search <query> [--build-system maven] [--error <pattern>]` — runs query_kb and displays results.
    - `buildroot kb add <path>` — validates and copies a KB entry file into the KB directory.
  - Seed KB directory (`~/.buildroot/kb/`) with 10 Bouncy Castle entries as `.md` files:
    - `ant-exact-version.md` (tip: use Ant 1.10.x, not latest)
    - `bnd-osgi-wrap.md` (tip: Bnd 2.2.0 wrap stage for OSGI headers)
    - `bnd-before-multirelease.md` (tip: Bnd must run BEFORE multi-release packaging)
    - `real-jdk9-binary.md` (tip: download real JDK 9 binary for multi-release, not just JDK 17)
    - `jdk9-jar-strict.md` (trick: JDK 9 jar tool is stricter about duplicate entries)
    - `encoding-utf8.md` (trick: `-encoding UTF-8` flag for JDK 9 javac)
    - `jar-uf-not-cf.md` (trick: use `jar uf` to update, not `jar cf` to recreate)
    - `signing-irreducible.md` (tip: signed JAR metadata diffs are irreducible — don't chase them)
    - `hsperfdata-suppress.md` (trick: suppress hsperfdata via `-XX:-UsePerfData` or exclude from JAR)
    - `source-date-epoch.md` (tip: `SOURCE_DATE_EPOCH=0` for reproducible timestamps)
  - KB also feeds v3 pipeline: inject relevant KB entries into v3's analysis agent prompt via pre-pass context. A tip like "for OSGI headers, add Bnd wrap stage" helps v3 even within template constraints.

  **Phase 4 — Learning Loop:**
  - Add to `meta_agent.py` post-success path (~100 lines):
    - After orchestrator achieves score ≥ target: extract winning Containerfile, classify novel techniques, record to KB.
    - `record_template(containerfile, coordinate, tags, characteristics)` — saves winning CF as a TemplateEntry.
    - `extract_tips(orchestrator_log, coordinate)` — parses the orchestrator's reasoning to identify reusable techniques. Uses a small Claude agent call with schema to extract structured tips.
    - `extract_tricks(build_logs, coordinate)` — identifies error→fix mappings from the build iteration history.
    - Update `times_used` and `success_rate` on any KB entries that were retrieved and contributed to the solution (tracked by the orchestrator's query log).
  - Knowledge transfer validation: after solving one OSGI package, the KB entries should be retrieved when processing a second OSGI package, reducing iterations needed.

  **Files created/modified:**
  | File | Action | Lines |
  |------|--------|-------|
  | `src/buildroot/agent/meta_agent.py` | NEW | ~250 |
  | `src/buildroot/agent/meta_prompt.py` | NEW | ~350 |
  | `src/buildroot/cli/commands/eval_cmd.py` | NEW | ~90 |
  | `src/buildroot/cli/commands/kb_cmd.py` | NEW | ~130 |
  | `src/buildroot/agent/knowledge/schema.py` | NEW | ~130 |
  | `src/buildroot/agent/knowledge/retrieval.py` | NEW | ~180 |
  | `~/.buildroot/kb/*.md` | NEW | 10 seed entries |
  | `src/buildroot/cli/commands/agent_cmd.py` | MODIFY | +30 (add orchestrator mode) |
  | `src/buildroot/cli/main.py` | MODIFY | +15 (register eval, kb commands) |
  | KEEP unchanged | — | `pipeline_v3.py`, `evaluator.py`, `prepass.py`, `claude_runner.py`, `jar_comparator.py`, `feedback.py`, `scorer.py` |

  **Estimated total:** ~1500 new lines across 8 new + 2 modified files.

- **Why:** This is the project's highest-leverage change. The v3 pipeline is structurally capped — 22/31 packages are L3-stuck because templates can't express multi-stage builds, custom tooling, or OSGI wrapping. Issue #60's architecture (agent monitors v3, takes over when stagnated, uses KB for cross-package learning) is validated by the Bouncy Castle proof-of-concept where a human reached 0.9998 in 4 iterations using exactly this approach. The codebase is 85% ready — existing `claude_runner.py`, `evaluator.py`, `prepass.py`, and `pipeline_v3.py` are directly reusable as tools. Capability_surface is the weakest eval dimension (0.411) and this adds massive new capability: orchestrator agent, KB system with retrieval, learning loop, 5 new CLI entry points (`buildroot agent`, `buildroot eval`, `buildroot kb list/search/add`). Research confirms the Python subprocess approach via `spawn_claude_agent()` is the right execution substrate (not Workflow), consistent with experiments #008-#018 and the CEO's review.
- **Expected impact:** capability_surface 0.411 → 0.75+ (5 new CLI commands, orchestrator agent, KB system, learning loop — major new feature surface). Composite 0.608 → 0.70+. Unlocks path to 50%+ solve rate on 31-package benchmark by enabling the agent to write arbitrary Containerfiles for the 22 stuck packages.
- **Priority:** high

### Anti-patterns to Avoid
- **Don't use Workflow tool for orchestration** — issue #60 and CEO review both specify Python subprocess via `claude_runner.py`. The Workflow tool is for factory internals, not project orchestration.
- **Don't implement partial phases** — the backlog item explicitly says "implement it in full and test it as the issue describes, dont allow any agent to take shortcuts." All 4 phases must be implemented and functional. Scaffolding without execution gets reverted.
- **Don't break v3 backward compatibility** — the 9 solved packages must still work. v3 becomes a tool the orchestrator uses. `--v3-only` flag preserves the old path. Gate 1 requires no regression.
- **Don't skip KB seeding** — an empty KB is useless. The 10 Bouncy Castle entries must be created as seed data so the orchestrator has actionable knowledge from day one.
- **Don't over-engineer KB retrieval** — start with metadata filtering + regex pattern matching. No vector embeddings or ML-based retrieval. The ACE-style append-only playbook pattern (already validated in this project via experiments #027+) is the right model.
- **Don't mock E2E testing** — per project memory (2 separate entries), real E2E on rh-h100-01 is mandatory after ANY agent/pipeline code change. Mocked tests are necessary but not sufficient. Token cost is never a valid skip reason. SSH as `lab` (not `akasriva`).
- **Don't repeat raw information dump anti-pattern (exp #10, -19.4pp)** — the orchestrator's system prompt must use structured sections, not raw dumps of build logs or comparison reports.
