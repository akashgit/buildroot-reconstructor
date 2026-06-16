---
tags:
  - factory
  - source
  - critical-lesson
  - buildroot-reconstructor
source: factory-archivist
date: 2026-06-14
severity: CRITICAL
related_experiments: [8]
related_playbook: [ceo-00005, ceo-00007]
---

# CRITICAL LESSON: Infrastructure Migrations MUST Include Real E2E Execution

## The Failure

Experiment #008 (Claude Code agent migration) was tested exclusively with mocked unit tests. 430 tests passed, including 29 new tests — all mocking `spawn_claude_agent()` and never invoking a real Claude Code subprocess on a real Maven package reconstruction. The experiment was given a KEEP verdict and PR #21 was opened without a single real package ever being reconstructed through the new agent pipeline.

This is the same anti-pattern identified in CEO playbook items **ceo-00005** and **ceo-00007**: *writing code that runs pipelines is not the same as running pipelines*.

## Why This Is Unacceptable

1. **The remote nodes are available.** `rh-h100-01` was used successfully in experiments #002 and #006 for real container builds and agentic smoke tests. There is no infrastructure barrier.
2. **Token cost is not a valid excuse.** The project budget exists precisely for execution. Skipping E2E to "save tokens" defeats the entire purpose of an agentic reconstruction system.
3. **Mocked tests prove interface contracts, not functional correctness.** The mocked tests verify that `spawn_claude_agent()` is called with correct arguments and that error paths are handled. They do NOT verify that a Claude Code subprocess can actually: read a pom.xml, infer build parameters, generate a valid Containerfile, or iterate on build failures.
4. **The prior experiment (#006) ran real E2E.** commons-lang3 was solved in 1 iteration on real hardware. The regression from "real E2E" to "mocked only" in the very next experiment is a process failure.

## The Rules (Non-Negotiable)

### Rule 1: E2E After Any Agent/Pipeline Code Change
After ANY change to agent code, pipeline orchestration, or execution substrate, a real E2E run on **at least 1 package** MUST happen before the experiment can be considered complete. Mocked unit tests are necessary but NOT sufficient.

### Rule 2: Token Cost Is Never a Valid Skip Reason
The nodes are available (`rh-h100-01`). The budget exists. "Token cost" or "resource cost" is NEVER a valid reason to skip real execution. If the system can't afford to run, it can't afford to exist.

### Rule 3: Validate on the Easiest Package First
commons-lang3 is the project's known-easy case (solved in 1 iteration in exp #006). Running E2E on it costs minimal resources and provides a definitive smoke test. There is no excuse not to run it.

## Cross-References

- **ceo-00005**: "Writing code that runs pipelines is not the same as running pipelines" — this is the exact pattern. The CEO wrote claude_runner.py, builder.py migration, outer_loop.py migration, but never ran the outer loop.
- **ceo-00007**: Related anti-pattern about skipping operational validation.
- **Experiment #002**: Set the precedent — 7/10 packages failed in real builds despite all unit tests passing. Only real hardware runs caught the failures.
- **Experiment #006**: Successfully ran E2E on 3 packages. The infrastructure and process for real E2E exist and work.
- **Pattern "Real Hardware Build Verification Catches Issues That Unit Tests and Inference Logic Miss"**: Already documented from exp #002. Was ignored in exp #008.

## Remediation

Experiment #008 cannot be considered fully validated until:
1. `commons-lang3:3.14.0` is reconstructed end-to-end through the new Claude Code agent pipeline
2. The reconstruction produces a valid Containerfile and attempts a container build
3. Results are compared against the known-good exp #006 outcome (solved in 1 iteration)

Until this happens, the KEEP verdict is provisional — the code may be correct but it is unverified.
