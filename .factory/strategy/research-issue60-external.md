# External Research — v4 Agent-as-Orchestrator Design (Issue #60)

**Research Date**: 2026-06-20  
**Target**: Issue #60 — Claude Code agent as orchestrator that runs v3 pipeline as a tool, monitors progress, and takes over when v3 stagnates

---

## Executive Summary

v4 maps cleanly to established patterns: the orchestrator agent uses Claude Code's **Workflow tool** to wrap the v3 pipeline (via `buildroot v3` CLI), monitors each iteration's output, and switches strategies when v3 stagnates. The knowledge base follows **ACE-style append-only playbooks** (already validated in this project) extended with YAML templates. Claude Code's **subprocess spawning via `claude -p`** (already used in experiments #008-#018) is the execution substrate. Domain expertise encoding follows the **three-tier architecture** (constitutional/skills/experiential) from Nurture-First Development research.

**Key validation**: Prior archive research (`claude-code-migration-*.md`, `ace-playbook-pattern.md`, `autoscientists-self-organizing-teams.md`) already established that:
- Claude Code subprocess spawning with `--bare` + `--append-system-prompt-file` reduces overhead to 10-15K tokens
- Structured output via `--json-schema` forces typed returns (validated at the tool-call layer)
- ACE's Generator-Reflector-Curator pattern maps 1:1 to v4's agent-analyzes-updates flow

This research extends with new 2026 patterns on workflow orchestration and KB design.

---

## 1. Agent Orchestration Patterns

### 1.1 Core Model: Workflows as Deterministic Orchestrators

**Source**: [Claude Code Workflows: Deterministic Multi-Agent Orchestration](https://alexop.dev/posts/claude-code-workflows-deterministic-orchestration/)

**Key Insight**: Workflows invert control flow — "You write the control flow as plain code, and each individual step is delegated to a fresh subagent." This is exactly what v4 needs:

```javascript
// Pseudo-workflow for v4
const result = await pipeline(
  iterations,
  // Stage 1: Run v3 one iteration
  iter => agent(`Run v3 pipeline iteration ${iter}`, {
    schema: V3_RESULT_SCHEMA,  // {score, level, cf_path, comparison_report}
  }),
  // Stage 2: Decide strategy
  (v3_result, iter) => {
    if (v3_result.score >= TARGET) return {action: 'done', result: v3_result};
    if (stagnated(v3_result, history)) return {action: 'takeover', iter};
    return {action: 'continue'};
  },
  // Stage 3: Execute action
  action => action.action === 'takeover' 
    ? agent(`Write Containerfile from scratch for ${coord}`, {schema: CF_SCHEMA})
    : null
);
```

**Pattern name**: **Monitor-Until-Threshold-Then-Takeover**

**Critical primitives**:
- `agent(prompt, {schema})`: Spawns subagent, forces validated JSON output, retries on mismatch
- `pipeline(items, ...stages)`: NO barrier between stages (unlike `parallel()`) — "Item A in stage 3 while B in stage 1"
- `phase(title)`: Progress grouping for UI

**When to use workflows vs agents**:
- **Workflows**: Repeatable structure, deterministic control flow, breadth/coverage needed, confidence-critical
- **Agents (subagents)**: Open-ended exploration, mid-run human input, single-task execution

**For v4**: Use workflow for the outer loop (deterministic: iterate until solved or budget exhausted), use agent for the takeover step (open-ended: "write the best Containerfile you can").

### 1.2 Quality Patterns from /deep-research Production Workflow

**Source**: [Claude Code Workflows: Deterministic Multi-Agent Orchestration](https://alexop.dev/posts/claude-code-workflows-deterministic-orchestration/)

Five-phase structure directly applicable to v4:

1. **Scope**: Decompose the problem (v4: read pre-pass, query KB, identify build system)
2. **Search**: Parallel exploration (v4: run v3 + agent's own research concurrently)
3. **Fetch**: Dedupe + extract (v4: read comparison report, classify error, query KB for tricks)
4. **Verify**: Adversarial checking (v4: if agent writes raw CF, verify via `buildroot eval`)
5. **Synthesize**: Produce output (v4: return winning CF + record KB entry)

**Adversarial Verify** pattern:
- Spawn N skeptics to refute each finding
- Require majority survival
- "Prevents plausible-but-wrong outputs"

**For v4**: After agent writes a raw Containerfile, spawn 2-3 verifier agents that independently evaluate it (check syntax, predict build success, flag obvious errors). Only proceed if ≥2 approve.

**Loop-Until-Dry** pattern:
- Continue spawning finders until K consecutive empty rounds
- **Critical**: "dedupe against everything seen, not just confirmed results" — same issue discovered in exp #013's elitist gate

**For v4**: If v3 stagnates and agent takes over, the agent iterates until either (a) score ≥ target, (b) 3 consecutive iterations with no score improvement, or (c) budget exhausted.

### 1.3 Practical Execution Loop

**Source**: [Workflows in Agentic AI — Claude code workflows](https://medium.com/@danushidk507/workflows-in-agentic-ai-claude-code-workflows-8cac80792dd8)

The tool-calling loop for iteration-based work:

```python
for turn in range(1, MAX_TURNS + 1):
    response = client.messages.create(model=MODEL, tools=TOOLS)
    tool_calls = [b for b in assistant_blocks if b.get("type") == "tool_use"]
    if not tool_calls:
        return final_text  # Exit when no more tools needed
    
    for call in tool_calls:
        result = execute_tool(tool_name, tool_input)
        tool_results.append({"type": "tool_result", "content": json.dumps(result)})
    
    messages.append({"role": "user", "content": tool_results})
```

**For v4**: The orchestrator agent's system prompt includes a tool `run_v3_iteration()` that wraps `buildroot v3 <coord> --max-iterations 1 --workspace <path>`. After each tool call, the agent reads workspace artifacts (score, CF, comparison report) and decides: continue, take over, or done.

**Strategy Switching via Subagents**:
- Main Agent → Research Agent, Test Agent, Security Agent → Each performs independent work → Returns: Summary only
- This prevents context pollution

**For v4**: The orchestrator can spawn a Research sub-agent when stuck: "Find web examples of building ${package_name} from source" → agent returns summary → orchestrator incorporates findings into next CF attempt.

---

## 2. Claude Code Subprocess Management

### 2.1 CLI Invocation Pattern (Already Validated in This Project)

**Source**: Archive file `.factory/archive/sources/claude-code-migration-external-research.md`

**Validated pattern** from experiments #008-#018:

```python
def spawn_claude_agent(prompt, system_prompt_file, schema=None, max_turns=30, timeout=600):
    cmd = [
        "claude", "--bare",
        "-p", prompt,
        "--append-system-prompt-file", system_prompt_file,
        "--output-format", "json",
        "--model", "claude-opus-4-6",
        "--max-turns", str(max_turns),
        "--max-budget-usd", "5.00",
        "--dangerously-skip-permissions"
    ]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return json.loads(result.stdout)
```

**Key flags**:
- `--bare`: Skips hooks, skills, plugins, MCP, CLAUDE.md — makes invocations deterministic
- `--append-system-prompt-file`: Preserves default tool guidance while adding domain context
- `--json-schema`: Forces validated structured output (post-hoc validation with retries)
- `--dangerously-skip-permissions`: Required for headless; guards/allowlists are the safety layer

**For v4**: Reuse the existing `claude_runner.py` utility (created in exp #008) with two new system prompt files:
- `meta_prompt_monitor.txt`: Domain expertise for monitoring v3 progress
- `meta_prompt_takeover.txt`: Domain expertise for writing raw Containerfiles

### 2.2 Structured Output for Tool Wrapping

**Source**: [Run Claude Code programmatically - Claude Code Docs](https://code.claude.com/docs/en/headless)

When wrapping v3 as a tool, the agent needs structured output:

```json
{
  "v3_iteration_result": {
    "iteration": 3,
    "score": 0.50,
    "level": "L3",
    "containerfile_path": "/workspace/Containerfile.v3",
    "comparison_report": {...},
    "build_log": "...",
    "converging": false
  }
}
```

**Validation**: `--json-schema` forces this schema. If v3 crashes or returns malformed output, the agent's tool call fails with a validation error, and the agent can retry or switch strategies.

**For v4**: Define `V3_RESULT_SCHEMA` as a JSON Schema with required fields `[score, level, containerfile_path]` and optional fields `[comparison_report, build_log, error_summary]`. The orchestrator agent reads this structured output after each v3 iteration.

### 2.3 Subprocess Safety (Already Implemented)

**Source**: Archive patterns + [Workflows in Agentic AI — Claude code workflows](https://medium.com/@danushidk507/workflows-in-agentic-ai-claude-code-workflows-8cac80792dd8)

Existing buildroot guards already enforce:
- Path validation: All file access constrained to workspace
- Command allowlisting: Only safe commands (`podman`, `git`, `maven`, etc.)
- No shell expansion: Uses `shlex.split()` without `shell=True`
- Timeouts on subprocess execution
- JSONL audit logs for all tool calls

**For v4**: No new safety layer needed — the existing guards from exp #007 (mutable surfaces, fixed surfaces, CLAUDE.md scope) apply to the orchestrator agent just like any other agent.

---

## 3. Knowledge Base Design

### 3.1 ACE-Style Append-Only Playbooks (Already Validated)

**Source**: Archive file `.factory/archive/sources/ace-playbook-pattern.md`

**Already implemented** in this project (exp #027 onward): Agent playbook files with helpful/harmful/neutral counters.

**ACE pattern**:
- **Generator**: Reads playbook rules before acting (node agents reading `.factory/playbooks/`)
- **Reflector**: Compares output against ground truth (AnalyzeAgent diagnosing build failures)
- **Curator**: Decides whether to create a new "Delta Rule" or merge with existing (AnalyzeAgent writing DO/DON'T entries)

**For v4 KB**: Extend this pattern with three entry types (Templates, Tips, Tricks) instead of just Delta Rules.

### 3.2 YAML-Based Agent Skills with Frontmatter

**Source**: [Spring AI Agentic Patterns (Part 1): Agent Skills](https://spring.io/blog/2026/01/13/spring-ai-generic-agent-skills/)

**Pattern**: Markdown files with YAML frontmatter + markdown body:

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

**Trigger**: JAR manifest contains OSGI headers (`Bundle-SymbolicName`, `Export-Package`, etc.)

**Solution**: Add a Bnd 2.2.0 wrap stage BEFORE the multi-release JAR build stage:

\```dockerfile
# Stage: Bnd OSGI wrapping
FROM eclipse-temurin:8-jdk AS bnd-wrap
RUN wget https://repo1.maven.org/maven2/biz/aQute/bnd/bnd/2.2.0/bnd-2.2.0.jar
COPY --from=build-stage /output/pre-osgi.jar .
RUN java -jar bnd-2.2.0.jar wrap pre-osgi.jar output.jar
\```

**Caveats**:
- Bnd must run BEFORE multi-release packaging (order matters)
- Use exact version 2.2.0 (later versions change CLI syntax)
- Ensure intermediate JAR is available from prior build stage
```

**Key fields**:
- `name`: Unique identifier (kebab-case)
- `type`: template | tip | trick
- `tags`: List for keyword matching
- `build_systems`: Filters by build system
- `trigger_patterns`: Conditions for activation (regex on manifest, error logs, etc.)
- `success_rate`, `times_used`: ACE-style counters

**For v4**: Store KB entries in `~/.buildroot/kb/*.md` files with this schema. The retrieval function queries by: `build_system IN tags`, `manifest_keys MATCH trigger_patterns`, `error_pattern MATCH trigger_patterns`.

### 3.3 KB Retrieval Strategy

**Source**: [6 agentic knowledge base patterns emerging in the wild](https://thenewstack.io/agentic-knowledge-base-patterns/) + [Hermes Agent Skill Authoring — SKILL.md Structure](https://dev.to/rosgluk/hermes-agent-skill-authoring-skillmd-structure-and-best-practices-44n9)

**Pattern**: Tag co-occurrence graph + metadata filtering:

1. **Metadata filtering** (fast): Match `build_system`, `coordinate.group_id`, `level` (L2/L3/L4)
2. **Pattern matching** (medium): Regex match on `trigger_patterns` against manifest keys, error logs
3. **Tag co-occurrence** (slow, only if needed): "the more pages they share, the thicker and shorter the edge"

**For v4 KB query**:

```python
def query_kb(build_system=None, manifest_keys=None, error_pattern=None, group_id=None):
    entries = []
    for kb_file in Path("~/.buildroot/kb/").glob("*.md"):
        metadata = parse_yaml_frontmatter(kb_file)
        
        # Filter 1: Build system
        if build_system and build_system not in metadata.get("build_systems", []):
            continue
        
        # Filter 2: Trigger patterns
        if manifest_keys and any(
            pattern_matches(p, manifest_keys) 
            for p in metadata.get("trigger_patterns", [])
        ):
            entries.append((kb_file, metadata, "manifest_match"))
        
        # Filter 3: Error pattern
        if error_pattern and any(
            re.search(p, error_pattern) 
            for p in metadata.get("error_patterns", [])
        ):
            entries.append((kb_file, metadata, "error_match"))
        
        # Filter 4: Group ID (for templates from similar packages)
        if group_id and metadata.get("coordinate", {}).get("group_id") == group_id:
            entries.append((kb_file, metadata, "group_match"))
    
    # Sort by success_rate DESC, times_used DESC
    return sorted(entries, key=lambda e: (e[1].get("success_rate", 0), e[1].get("times_used", 0)), reverse=True)
```

**For v4**: Query KB at three points:
1. **Start of package**: Load templates matching `build_system` + `group_id`
2. **After v3 stagnates**: Load tips/tricks matching `error_pattern` from latest failure
3. **After success**: Update `success_rate` and `times_used` counters on used entries

### 3.4 Template vs Tip vs Trick Distinction

**Templates** (complete Containerfile):
- Used when v3 stagnates and agent needs a starting point
- Example: Bouncy Castle 5-stage CF tagged `[ant, osgi, multi-release, bnd]`
- Trigger: `build_system=ant AND manifest_has("Bundle-SymbolicName") AND multi_release_entries > 0`

**Tips** (technique with context):
- Used when v3 is converging but missing a specific capability
- Example: "OSGI headers → Bnd wrap stage" (from above)
- Trigger: Manifest contains OSGI headers but build output lacks them

**Tricks** (error→fix mapping):
- Used when v3 hits a known error class
- Example: `unmappable character for encoding UTF-8 → add -encoding UTF-8 to javac args`
- Trigger: Build log matches `unmappable character for encoding`

**For v4**: Agent system prompt includes KB entry types and when to query each.

---

## 4. Domain Expertise Encoding in System Prompts

### 4.1 Three-Tier Cognitive Architecture

**Source**: [Nurture-First Agent Development: Building Domain-Expert AI Agents](https://arxiv.org/html/2603.10808v1)

**Architecture** (from paper):

1. **Constitutional Layer** (10-15% of context):
   - "Identity, behavioral principles, and operational rules"
   - "Should contain indices and principles, not detailed knowledge"
   - Loaded every session

2. **Skill Layer** (loaded on-demand):
   - "Instructional prompts, reference knowledge, optional scripts"
   - "Primary container for crystallized knowledge assets"
   - Follow Single Responsibility Principle

3. **Experiential Layer** (semantic search):
   - "Accumulated operational experience: interaction logs, case memories"
   - Raw material for knowledge crystallization

**For v4 orchestrator agent**:

**Constitutional Layer** (`meta_prompt_base.txt`):
```
You are a buildroot reconstruction specialist. Your goal is to produce a Containerfile that 
builds a JAR artifact matching the original from Maven Central.

You have two strategies:
1. Fast path: Run the v3 template-based pipeline via `run_v3_iteration()` tool
2. Takeover path: Write a raw Containerfile when v3 stagnates

SCORING:
- L1 (0.00-0.05): Containerfile parses
- L2 (0.05-0.15): Container builds
- L3 (0.15-0.50): JAR is produced
- L4 (0.50-1.00): JAR matches original (bytecode + metadata)

TARGET: ≥ 0.98 score

DECISION RULES:
- v3 converging (score improving) → let it continue
- v3 stagnated (same score 2+ iterations) → take over
- v3 solved (score ≥ 0.98) → done
```

**Skill Layer** (loaded via KB query):
- Templates: Full Containerfiles from prior successful builds
- Tips: Techniques with trigger conditions (OSGI → Bnd, etc.)
- Tricks: Error→fix mappings

**Experiential Layer** (not implemented in v4 Phase 1):
- Future: Log all agent decisions + outcomes to `~/.buildroot/memory/` for cross-package learning

### 4.2 Domain Knowledge: JAR Structure, Build Systems, Bytecode, OSGI

**Source**: Archive patterns + [Anthropic Research: Domain Expertise Beats Coding Background](https://explainx.ai/blog/anthropic-claude-code-expertise-research-agentic-coding-2026)

**Key finding**: "Domain expertise is substantially tacit" — the agent needs operational knowledge encoded as procedures, not just facts.

**For v4 system prompt sections**:

**JAR Structure**:
```
JAR ANATOMY:
- META-INF/MANIFEST.MF: Build metadata (Build-Jdk-Spec, Created-By, Multi-Release)
- *.class files: Compiled bytecode (target JDK version affects bytecode format)
- META-INF/maven/: pom.xml + pom.properties (build paths, timestamps)
- Multi-release JARs: META-INF/versions/{9,10,11,...}/ with JDK-specific classes

REPRODUCIBILITY GAPS (L3→L4):
- Timestamps in MANIFEST.MF, pom.properties
- Created-By header (JDK vendor string)
- ZIP entry ordering (deterministic with jar -D)
- Build paths in debug info (strip with -g:none or canonicalize)
```

**Build Systems**:
```
MAVEN:
- Standard: mvn clean package
- Reproducible flags: -Dproject.build.outputTimestamp=<timestamp>
- Common issues: Missing system dependencies, parent POM not resolved

ANT:
- Exact version matters (tag format: REL_<version> or release-<version>)
- Build file: build.xml (targets: jar, dist, release)
- OSGI builds often use Ant + Bnd

GRADLE:
- Daemon must be disabled: --no-daemon
- ENV GRADLE_OPTS for memory config (not inline -Xmx)
- Shadow plugin: tasks.shadowJar { mergeServiceFiles() }
```

**Bytecode**:
```
BYTECODE COMPATIBILITY:
- JDK 8 produces bytecode version 52.0
- JDK 11 produces bytecode version 55.0
- Multi-release JARs contain MULTIPLE bytecode versions

VERIFICATION:
- Use javap -v to inspect bytecode version
- Bytecode match but metadata mismatch → L3 failure (canonicalization needed)
```

**OSGI**:
```
OSGI HEADERS:
- Bundle-SymbolicName, Export-Package, Import-Package
- Generated by Bnd tool (biz.aQute.bnd:bnd:2.2.0)

OSGI BUILD PATTERN:
1. Compile source → pre-osgi.jar
2. Run Bnd wrap → adds OSGI headers
3. (Optional) Multi-release packaging

CRITICAL: Bnd MUST run BEFORE multi-release packaging (order matters)
```

### 4.3 Procedural Knowledge Encoding

**Source**: [Nurture-First Agent Development](https://arxiv.org/html/2603.10808v1)

**Pattern**: "Instructional prompts" with verification checkpoints:

```
WHEN V3 STAGNATES:
1. Read the latest comparison report
2. Classify the gap: structural (missing classes), metadata (timestamps), bytecode (version mismatch)
3. Query KB for tips/tricks matching the error class
4. If KB returns a template: Use it as starting point
5. If KB returns a tip: Apply the technique incrementally
6. If KB returns a trick: Apply the fix directly
7. Write the Containerfile
8. Evaluate via `buildroot eval <cf> <coord>`
9. If score improved: Iterate from step 1
10. If score stagnated 3x: Report to user
```

**For v4**: Each decision point in the orchestrator's loop is encoded as a numbered procedure with explicit conditionals.

---

## 5. Recommendations for v4 Implementation

### 5.1 Orchestrator Agent Design

**Workflow script** (`meta_agent_workflow.js`):

```javascript
export const meta = {
  name: 'buildroot-v4-orchestrator',
  description: 'Run v3 pipeline, monitor progress, take over when needed',
  phases: [
    {title: 'Research', detail: 'Load pre-pass + KB context'},
    {title: 'V3 Loop', detail: 'Run v3 iterations, monitor progress'},
    {title: 'Takeover', detail: 'Write raw Containerfile when v3 stagnates'},
    {title: 'Verify', detail: 'Evaluate final result'}
  ]
};

phase('Research');
const prepass = await agent('Read pre-pass findings', {schema: PREPASS_SCHEMA});
const kb_entries = await agent(`Query KB for ${coord}`, {schema: KB_SCHEMA});

phase('V3 Loop');
let history = [];
for (let i = 0; i < MAX_V3_ITERATIONS; i++) {
  const result = await agent(`Run v3 iteration ${i}`, {schema: V3_RESULT_SCHEMA});
  history.push(result);
  
  if (result.score >= TARGET) {
    return {winner: 'v3', result};
  }
  
  if (stagnated(history)) {
    phase('Takeover');
    const cf = await agent('Write raw Containerfile from scratch', {
      schema: CF_SCHEMA,
      context: {prepass, kb_entries, v3_best: best(history)}
    });
    
    const eval_result = await agent(`Evaluate ${cf.path}`, {schema: EVAL_SCHEMA});
    if (eval_result.score >= TARGET) {
      return {winner: 'agent', result: eval_result};
    }
  }
}

return {winner: 'none', best: best(history)};
```

**Key design points**:
- Workflow provides deterministic outer loop
- Each `agent()` call spawns a fresh Claude Code session with domain expertise
- Structured schemas force typed returns
- Stagnation detector is pure JavaScript (no LLM needed)

### 5.2 KB Seeding from Bouncy Castle

**Already solved** (manually, exp #018 → 0.9998 score in 4 iterations):

**Templates** to seed:
- `bouncy-castle-5-stage.md`: Full Containerfile tagged `[ant, osgi, multi-release, bnd]`

**Tips** to seed (extracted from BC manual session):
- `osgi-bnd-wrap.md`: OSGI → Bnd wrap stage (shown above)
- `real-jdk9-binary.md`: Multi-release → Real JDK 9 binary (not Docker image)
- `ant-exact-version.md`: Ant version from git tag (REL_1_70 → 1.70)
- `jar-uf-not-cf.md`: Multi-release update: `jar uf` not `jar cf`
- `source-date-epoch.md`: ZIP timestamps: `SOURCE_DATE_EPOCH` env var

**Tricks** to seed:
- `unmappable-character.md`: `unmappable character for encoding UTF-8` → add `-encoding UTF-8`
- `jdk9-jar-strict.md`: `jar --release 9` fails → use `jar uf` instead
- `hsperfdata-suppress.md`: `/tmp/hsperfdata_root` nondeterminism → `-XX:-UsePerfData`

**Validation**: After seeding, run v4 on a second OSGI package (e.g., `org.apache.felix:org.apache.felix.framework:7.0.5`) and verify it retrieves the BC-learned entries.

### 5.3 Phased Rollout

**Phase 1: v3 as tool + monitor** (2 weeks)
- Implement workflow script that calls `buildroot v3 --max-iterations 1` per iteration
- Agent reads workspace artifacts, decides: continue / done
- No takeover path yet — if v3 stagnates, agent reports to user
- **Gate 1**: 9 v3-solvable packages still solve in ≤ same iteration count

**Phase 2: Takeover path** (2 weeks)
- Add KB query + raw Containerfile authoring
- Agent takes over when v3 stagnates
- **Gate 2**: At least 5 of 22 stuck packages improve beyond v3 ceiling

**Phase 3: KB seeding + learning loop** (1 week)
- Seed KB with Bouncy Castle entries
- After each success, record winning CF as template
- **Gate 3**: Bouncy Castle solves autonomously (≥ 0.99)

**Phase 4: Full benchmark** (1 week)
- Run v4 on all 31 packages
- **Gate 4**: No regression on v3-solvable, ≥10 stuck packages improved
- **Gate 5**: v4 cost for easy packages ≤ 1.5x v3 cost

---

## 6. Cross-References to Prior Knowledge

### 6.1 Validated Patterns from Archive

**Claude Code subprocess spawning** (`.factory/archive/sources/claude-code-migration-*.md`):
- `--bare` + `--append-system-prompt-file` reduces overhead to 10-15K tokens
- `--json-schema` forces typed returns with post-hoc validation
- Per-agent tool restrictions (`allowed_tools`) bound blast radius
- Already implemented in exp #008, validated through exp #018

**ACE playbook pattern** (`.factory/archive/sources/ace-playbook-pattern.md`):
- Generator-Reflector-Curator maps 1:1 to agent-analyzes-updates flow
- Append-only entries with helpful/harmful counters
- Already implemented in this project (exp #027 onward)

**AutoScientists stagnation detection** (`.factory/archive/sources/autoscientists-self-organizing-teams.md`):
- "No improvement in last 10 experiments" triggers reorganization
- Dead-end registries per-team
- Cross-team visibility (strategy archive)
- Directly inspired this project's outer loop design

### 6.2 New Patterns from 2026 Research

**Workflow orchestration**:
- Monitor-Until-Threshold-Then-Takeover (new, from alexop.dev)
- Adversarial Verify (new, from /deep-research)
- Loop-Until-Dry (new, extends exp #013 elitist gate pattern)

**KB design**:
- YAML frontmatter + markdown body (new, from Spring AI / Hermes)
- Tag co-occurrence graphs (new, from The New Stack — not needed for Phase 1)
- Three-tier cognitive architecture (new, from NFD paper)

**Domain expertise encoding**:
- Constitutional/Skill/Experiential layers (new, from NFD paper)
- Procedural knowledge with verification checkpoints (new, from NFD paper)
- Progressive disclosure (new, from agent skills research)

---

## 7. Open Questions for CEO / User

1. **Workflow vs Python orchestrator**: Issue #60 assumes Python outer loop (`meta_agent.py`). Research shows workflows are better for deterministic orchestration. Should v4 use:
   - **Option A**: Workflow script (`.js` file) with `agent()` / `pipeline()` primitives
   - **Option B**: Python script that spawns `claude -p` subprocesses
   - **Recommendation**: Option A (more deterministic, better progress tracking, resume support)

2. **KB storage location**: `~/.buildroot/kb/` (global, shared across projects) or `.factory/kb/` (project-local)? Research suggests global for cross-project learning.

3. **Interactive vs autonomous**: Should v4 run fully autonomously (agent makes all decisions) or interactively (user approves takeover)? Research shows both are viable.

4. **Token budget**: Issue #60 doesn't specify budget. Based on research:
   - v3 fast path: ~10-15K tokens per iteration (same as current)
   - Takeover path: ~50-100K tokens (agent research + CF authoring + eval)
   - Suggested budget: $10-20 per package (comparable to v3 cost for easy packages, allows takeover for hard ones)

---

## Sources

- [Claude Code Workflows: Deterministic Multi-Agent Orchestration | alexop.dev](https://alexop.dev/posts/claude-code-workflows-deterministic-orchestration/)
- [Workflows in Agentic AI — Claude code workflows | Medium](https://medium.com/@danushidk507/workflows-in-agentic-ai-claude-code-workflows-8cac80792dd8)
- [Run Claude Code programmatically - Claude Code Docs](https://code.claude.com/docs/en/headless)
- [Nurture-First Agent Development: Building Domain-Expert AI Agents](https://arxiv.org/html/2603.10808v1)
- [Spring AI Agentic Patterns (Part 1): Agent Skills](https://spring.io/blog/2026/01/13/spring-ai-generic-agent-skills/)
- [6 agentic knowledge base patterns emerging in the wild - The New Stack](https://thenewstack.io/agentic-knowledge-base-patterns/)
- [Anthropic Research: Domain Expertise Beats Coding Background in Agentic Programming (2026)](https://explainx.ai/blog/anthropic-claude-code-expertise-research-agentic-coding-2026)
- [Agentic coding and persistent returns to expertise - Anthropic](https://www.anthropic.com/research/claude-code-expertise)
- [The Anatomy of an Agent Loop | Steve Kinney](https://stevekinney.com/writing/agent-loops)
- [LLM Agents vs. Workflows — and How Google ADK Gives You Both | Medium](https://medium.com/google-cloud/llm-agents-vs-workflows-and-how-google-adk-gives-you-both-7301d6fb1c4c)

**Archive sources** (internal):
- `.factory/archive/sources/claude-code-migration-external-research.md`
- `.factory/archive/sources/claude-code-migration-context-analysis.md`
- `.factory/archive/sources/ace-playbook-pattern.md`
- `.factory/archive/sources/autoscientists-self-organizing-teams.md`
- `.factory/archive/patterns/patterns.md` (patterns #120-#230)
