---
tags:
  - factory
  - source
  - research
  - issue60
  - agent-patterns
  - workflows
  - knowledge-base
project: buildroot-reconstructor
source: factory-archivist
date: 2026-06-20
---

# External Research — v4 Agent Orchestration Patterns

**Research scope:** External patterns for agent-as-orchestrator architecture, KB design, and domain expertise encoding

## Core Pattern: Monitor-Until-Threshold-Then-Takeover

**Source:** Claude Code Workflows (alexop.dev)

**Pattern structure:**
1. Run template-based tool (v3 pipeline) iteratively
2. Monitor progress after each iteration
3. When tool stagnates → agent takes over with full autonomy
4. Agent writes solution from scratch

**For v4:** Orchestrator runs `buildroot v3 --max-iterations 1` in loop, reads workspace artifacts (score, CF, comparison report), decides: continue / take over / done.

## Orchestration Mechanism: Workflows vs Python

**Two approaches found:**

### Option A: Workflow Script (JavaScript)
- Claude Code's `Workflow` tool with `agent()` / `pipeline()` primitives
- Deterministic control flow
- Built-in progress tracking and resume support
- Better for breadth/coverage tasks

### Option B: Python Subprocess
- Python script spawning `claude -p` via subprocess
- Already validated in exp #008-#018 (`claude_runner.py`)
- Simpler for tight outer loops
- Matches issue #60's design (meta_agent.py)

**For v4:** **Use Option B** — issue #60 explicitly specifies Python orchestrator (`meta_agent.py`), and the existing `claude_runner.py` utility is already battle-tested.

## Quality Patterns from /deep-research Workflow

**Five-phase structure:**
1. **Scope** — Decompose problem (v4: read pre-pass, query KB)
2. **Search** — Parallel exploration (v4: run v3 + agent research concurrently)
3. **Fetch** — Dedupe + extract (v4: read comparison report, classify error, query KB)
4. **Verify** — Adversarial checking (v4: verify agent-written CF via `buildroot eval`)
5. **Synthesize** — Produce output (v4: return winning CF + record KB entry)

### Adversarial Verify Pattern
- Spawn N skeptics to refute each finding
- Require majority survival
- Prevents plausible-but-wrong outputs

**For v4:** After agent writes raw Containerfile, spawn 2-3 verifier agents that independently evaluate it. Only proceed if ≥2 approve.

### Loop-Until-Dry Pattern
- Continue spawning finders until K consecutive empty rounds
- **Critical:** Dedupe against everything seen, not just confirmed results

**For v4:** If agent takes over, iterate until (a) score ≥ target, (b) 3 consecutive iterations with no score improvement, or (c) budget exhausted.

## Knowledge Base Design

### YAML Frontmatter + Markdown Body

**Source:** Spring AI Agent Skills, Hermes SKILL.md pattern

**Schema:**
```yaml
---
name: osgi-bnd-wrap
type: tip
tags: [osgi, bnd, multi-release, ant]
build_systems: [ant]
trigger_patterns:
  - manifest_has: "Bundle-SymbolicName"
  - manifest_has: "Export-Package"
success_rate: 1.0
times_used: 3
---

## Tip: OSGI Headers → Bnd Wrap Stage

**Trigger:** JAR manifest contains OSGI headers

**Solution:** Add Bnd 2.2.0 wrap stage BEFORE multi-release build
```

**Entry types:**
- **Templates:** Complete Containerfile from successful build
- **Tips:** Technique with trigger context
- **Tricks:** Error→fix mapping

### Retrieval Strategy

**Query pipeline:**
1. **Metadata filtering** (fast) — Match build_system, group_id, level
2. **Pattern matching** (medium) — Regex on trigger_patterns vs manifest keys, error logs
3. **Tag co-occurrence** (slow, only if needed) — Graph-based similarity

**Ranking:**
- Exact tag match: +10
- Partial match: +5
- Group match: +3
- Text similarity: 0-5

**For v4:** Query KB at three points:
1. Start of package → load templates matching build_system + group_id
2. After v3 stagnates → load tips/tricks matching error_pattern
3. After success → update success_rate and times_used counters

## Domain Expertise Encoding: Three-Tier Architecture

**Source:** Nurture-First Agent Development (arxiv.org/html/2603.10808v1)

### Constitutional Layer (10-15% of context)
- Identity, behavioral principles, operational rules
- Loaded every session
- Example: "You are a buildroot reconstruction specialist. Target: ≥0.98 score."

### Skill Layer (loaded on-demand)
- Instructional prompts, reference knowledge
- Primary container for crystallized knowledge
- Example: Templates, tips, tricks from KB

### Experiential Layer (semantic search)
- Accumulated operational experience
- Raw material for knowledge crystallization
- Future: Log all agent decisions + outcomes to `~/.buildroot/memory/`

**For v4:**
- **Constitutional:** `meta_prompt_base.txt` with scoring rules, decision heuristics
- **Skill:** KB entries loaded via query
- **Experiential:** Not implemented in Phase 1

## Domain Knowledge for System Prompt

### JAR Structure
- META-INF/MANIFEST.MF: Build metadata, Multi-Release flag
- *.class files: Compiled bytecode (JDK version affects format)
- META-INF/maven/: pom.xml + pom.properties
- Multi-release JARs: META-INF/versions/{9,10,11,...}/

**L3→L4 gaps:** Timestamps, Created-By header, ZIP ordering, build paths

### Build Systems
- **Maven:** `mvn clean package`, reproducible via `-Dproject.build.outputTimestamp`
- **Ant:** Exact version matters (tag format: REL_X_Y or release-X.Y), build.xml targets
- **Gradle:** `--no-daemon`, ENV GRADLE_OPTS for memory

### Bytecode
- JDK 8 → bytecode 52.0
- JDK 11 → bytecode 55.0
- Multi-release JARs contain multiple bytecode versions

### OSGI
- Headers: Bundle-SymbolicName, Export-Package, Import-Package
- Generated by Bnd tool (biz.aQute.bnd:bnd:2.2.0)
- **Critical:** Bnd MUST run BEFORE multi-release packaging

## KB Seeding from Bouncy Castle

**Manually solved** (exp #018 → 0.9998 score in 4 iterations)

**Templates to seed:**
- `bouncy-castle-5-stage.md` — Full Containerfile tagged [ant, osgi, multi-release, bnd]

**Tips to seed:**
- `osgi-bnd-wrap.md` — OSGI → Bnd wrap stage
- `real-jdk9-binary.md` — Multi-release → Real JDK 9 binary
- `ant-exact-version.md` — Ant version from git tag
- `jar-uf-not-cf.md` — Multi-release update: jar uf not jar cf
- `source-date-epoch.md` — ZIP timestamps: SOURCE_DATE_EPOCH env var

**Tricks to seed:**
- `unmappable-character.md` — encoding UTF-8 error → add -encoding UTF-8
- `jdk9-jar-strict.md` — jar --release 9 fails → use jar uf instead
- `hsperfdata-suppress.md` — /tmp/hsperfdata_root → -XX:-UsePerfData

## Phased Rollout

**Phase 1: v3 as tool + monitor** (2 weeks)
- Workflow calls `buildroot v3 --max-iterations 1` per iteration
- Agent reads workspace, decides: continue / done
- No takeover yet
- **Gate:** 9 v3-solvable packages still solve in ≤ same iteration count

**Phase 2: Takeover path** (2 weeks)
- Add KB query + raw CF authoring
- Agent takes over when v3 stagnates
- **Gate:** 5+ of 22 stuck packages improve

**Phase 3: KB seeding + learning** (1 week)
- Seed KB with BC entries
- Record winning CFs as templates
- **Gate:** BC solves autonomously (≥0.99)

**Phase 4: Full benchmark** (1 week)
- Run v4 on all 31 packages
- **Gates:** No regression, 10+ stuck improved, v4 cost ≤ 1.5x v3 for easy packages

## Cross-References to Prior Knowledge

**Validated patterns from archive:**
- Claude Code subprocess spawning (exp #008-#018) — `--bare` + `--json-schema`
- ACE playbook pattern (exp #027+) — append-only entries with helpful/harmful counters
- AutoScientists stagnation detection — "No improvement in last 10 experiments"

**New patterns from 2026 research:**
- Monitor-Until-Threshold-Then-Takeover (alexop.dev)
- Adversarial Verify (/deep-research workflow)
- Loop-Until-Dry (extends exp #013 elitist gate)
- YAML frontmatter KB (Spring AI / Hermes)
- Three-tier cognitive architecture (NFD paper)

## Why This Matters

**Reason:** Establishes that v4 follows proven patterns for agent orchestration, KB design, and domain expertise encoding — reducing implementation risk.

**How to apply:** Builder should use Python subprocess approach (matches issue #60 design), implement three-tier system prompt architecture, and seed KB from Bouncy Castle learnings.

## Sources

- Claude Code Workflows: Deterministic Multi-Agent Orchestration (alexop.dev)
- Workflows in Agentic AI — Claude code workflows (Medium)
- Run Claude Code programmatically (Claude Code Docs)
- Nurture-First Agent Development (arxiv.org/html/2603.10808v1)
- Spring AI Agentic Patterns (Part 1): Agent Skills
- 6 agentic knowledge base patterns (The New Stack)
- Archive: claude-code-migration-external-research.md
- Archive: ace-playbook-pattern.md
- Archive: autoscientists-self-organizing-teams.md
