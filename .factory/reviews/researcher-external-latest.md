# Researcher Agent Output

- **timestamp:** 2026-06-21T03:17:07Z
- **exit_code:** 0

---

Perfect! Research report complete. Let me provide a summary to the user:

## Research Complete

I've completed external research for issue #60 (v4 agent-as-orchestrator design) and written findings to `.factory/strategy/research-issue60-external.md`.

### Key Findings

**1. Agent Orchestration Patterns**
- **Workflows vs Agents**: Claude Code Workflows are the right tool — they provide deterministic control flow while delegating individual steps to fresh subagents
- **Monitor-Until-Threshold-Then-Takeover** pattern: Run v3 via `agent()` calls in a loop, check structured output each iteration, switch to direct Containerfile authoring when v3 stagnates
- **Quality patterns**: Adversarial Verify (spawn skeptics to refute findings), Loop-Until-Dry (iterate until K consecutive empty rounds), pipeline() over parallel() (no barrier between stages)

**2. Claude Code Subprocess Management** (Already Validated in This Project)
- Archive shows experiments #008-#018 already use `claude --bare -p` with `--append-system-prompt-file` and `--json-schema`
- Reduces overhead from ~50K to 10-15K tokens per invocation
- Structured output forces typed returns with post-hoc validation
- Can reuse existing `claude_runner.py` utility

**3. Knowledge Base Design**
- **YAML frontmatter + markdown body** pattern from Spring AI / Hermes
- Three entry types: Templates (complete Containerfiles), Tips (techniques with triggers), Tricks (error→fix mappings)
- Retrieval: metadata filtering → pattern matching → tag co-occurrence
- **ACE pattern already validated** in this project — extend with templates instead of just playbook rules

**4. Domain Expertise Encoding**
- **Three-tier architecture** (Nurture-First Development paper):
  - Constitutional Layer (10-15% of context): identity, principles, decision rules
  - Skill Layer (on-demand): KB entries, procedural knowledge
  - Experiential Layer (future): cross-package learning logs
- Encode JAR structure, build systems, bytecode, OSGI as procedural steps with checkpoints

**5. Recommended Implementation**
- **Option A** (recommended): Use Workflow script (`.js`) with `agent()` / `pipeline()` primitives for deterministic orchestration
- **Option B**: Python script spawning `claude -p` subprocesses (less deterministic, no resume support)
- **Phased rollout**: v3 as tool + monitor → takeover path → KB seeding → full benchmark
- **Validation gates**: No regression on 9 easy packages, ≥5 of 22 stuck packages improve

### Cross-References to Prior Knowledge

The research validated several patterns already in the archive:
- Claude Code subprocess spawning (migration research, experiments #008-#018)
- ACE playbook pattern (exp #027 onward)
- AutoScientists stagnation detection (outer loop design)

And discovered new 2026 patterns:
- Workflow orchestration (Monitor-Until-Threshold-Then-Takeover)
- YAML KB design (frontmatter + retrieval strategies)
- Three-tier cognitive architecture (constitutional/skill/experiential)

### Open Questions

1. **Workflow vs Python orchestrator**: Research recommends Workflow (Option A) for determinism and resume support
2. **KB location**: `~/.buildroot/kb/` (global) vs `.factory/kb/` (project-local)?
3. **Autonomous vs interactive**: Should v4 run fully autonomously or require user approval for takeover?
4. **Token budget**: Suggested $10-20/package (v3 fast path ~10-15K tokens, takeover ~50-100K)

**Sources**: 10 external web sources + 4 internal archive sources cited throughout the report.
---

> **⚠ CEO IDENTITY RE-ANCHOR (Sacred Rule 8)**
> You are the Factory CEO. You orchestrate, delegate, and decide. You do NOT implement.
> If you are about to write code, run tests, do research, or fix bugs — STOP and spawn the appropriate agent.
> Re-read your Permitted/Forbidden Actions lists in the Identity section above.
