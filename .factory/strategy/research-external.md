# External Research — Issue #45: Maven Build Reproducibility Diagnostics

## Research Scope

The project reconstructs build environments for Maven artifacts. Issue #45 wants to wire diagnostic feedback into the agent loop so agents can fix build failures faster. This research covers:

1. Maven `outputTimestamp` handling — format validation, version-specific behavior, the 1980 ZIP constraint
2. `SOURCE_DATE_EPOCH` interaction with Maven's timestamp system
3. Docker `ENV` ordering semantics — precedence when the same variable is set multiple times
4. Best practices for structured error feedback in agentic build systems

---

## 1. Maven outputTimestamp: Format, Validation, and Version Boundaries

### Accepted Formats

`project.build.outputTimestamp` accepts exactly two input formats, parsed by `MavenArchiver.parseBuildOutputTimestamp()`:

1. **ISO 8601 with offset**: `2023-01-01T00:00:00Z` or `2019-10-05T20:37:42+06:00` — parsed via `DateTimeFormatter.ISO_OFFSET_DATE_TIME`. The offset **must** use colons (`+06:00`, not `+0600`).
2. **Integer epoch seconds**: e.g., `946684800` — same semantics as `SOURCE_DATE_EPOCH`.

**Not accepted:**
- Truncated ISO 8601 (e.g., `2019-03-26T14:00.9Z`) — MJAR-301 filed, closed as won't-fix
- Timezone offsets without colons (`+0100`) — incompatible with `git-commit-id-maven-plugin`'s default `dateFormat` (`yyyy-MM-dd'T'HH:mm:ssZ`); workaround: set `<dateFormat>yyyy-MM-dd'T'HH:mm:ssXXX</dateFormat>`
- Date-only strings (no time component)

**Edge cases:**
- `null` input → `Optional.empty()` (reproducible builds disabled)
- Single-character non-numeric input → `Optional.empty()` (treated as disabled)
- Invalid format → `IllegalArgumentException`

### Version-Specific Validation Behavior

| Component | Version | Behavior |
|---|---|---|
| maven-jar-plugin | 3.2.0+ | `outputTimestamp` parameter available |
| maven-archiver | 3.6.0–3.6.3 | **Range validation enforced**: `DATE_MIN = 1980-01-01T00:00:02Z`, `DATE_MAX = 2099-12-31T23:59:59Z`. Values outside this range throw `IllegalArgumentException`: `"'<date>' is not within the valid range 1980-01-01T00:00:02Z to 2099-12-31T23:59:59Z"` |
| maven-archiver | 3.6.4 | `SOURCE_DATE_EPOCH` env var fallback added |
| maven-archiver | post-Sep 2025 | **Range validation removed entirely** (commit by Hervé Boutemy: "don't limit outputTimestamp to zip (MS DOS) range"). `DATE_MIN`/`DATE_MAX` constants deleted. Any syntactically valid timestamp now accepted. |
| Maven | 4.0.0-beta-5+ | Reproducible builds active by default (MNG-8258) |

### The 1980 ZIP Constraint — Why It Exists

ZIP files store timestamps in MS-DOS date/time format:
- **Date**: 16-bit packed — bits 9-15 = year offset from 1980 (0–127, representing 1980–2107), bits 5-8 = month, bits 0-4 = day
- **Time**: 16-bit packed — **2-second resolution** (odd seconds round down)

**Minimum representable date**: `1980-01-01 00:00:00`. Year field value `0` = 1980. No encoding exists for any year before 1980.

**Why maven-archiver used `1980-01-01T00:00:02Z` (not `00:00:00Z`)**: The 2-second resolution means `00:00:00` and `00:00:01` are ambiguous (both encode to the same DOS time value). Using `00:00:02Z` avoids this edge case.

**Behavior when violated:**
- Java's `ZipOutputStream` silently clamps timestamps to the DOS range in most implementations
- Python's `zipfile` raises `ValueError: ZIP does not support timestamps before 1980` (fixed in 3.8 with `strict_timestamps=False` that clamps to 1980-01-01)
- Some tools produce corrupt entries

### Impact on This Project

The project currently uses:
- `REPRODUCIBLE_FLAGS = ["-Dproject.build.outputTimestamp=2000-01-01T00:00:00Z"]` in `containerfile.py:28`
- `ENV SOURCE_DATE_EPOCH=946684800` (= 2000-01-01) in all four templates

The `2000-01-01` value is safe — it's well within the ZIP range. The prior `1980-01-01T00:00:00Z` value (documented in `pipeline-shortcomings-analysis.md`) was rejected by maven-archiver 3.6.0–3.6.3 because it was 2 seconds below `DATE_MIN`.

**New error pattern needed**: The AnalyzeAgent should detect timestamp range errors specifically:
```python
("plugin/timestamp_range", re.compile(
    r"is not within the valid range 1980|"
    r"outputTimestamp.*not.*valid|"
    r"ZIP does not support timestamps before 1980",
    re.IGNORECASE
))
```

With fix suggestion: "The outputTimestamp value is outside the valid ZIP date range (1980-01-01T00:00:02Z to 2099-12-31T23:59:59Z). Use `-Dproject.build.outputTimestamp=2000-01-01T00:00:00Z` instead."

### Additional maven-jar-plugin 3.3.0 Bugs

- **MJAR-300**: Timestamps with timezone offsets were treated as local time, silently attaching the local timezone, causing an 8-hour discrepancy.
- **MJAR-301**: Certain valid ISO 8601 formats not supported (without timezone, offset without colon).

**Implication**: Always use the `Z` (UTC) suffix for `outputTimestamp` values. Never use local-time offsets.

### References

- [Apache Maven Reproducible Builds Guide](https://maven.apache.org/guides/mini/guide-reproducible-builds.html)
- [MavenArchiver 3.6.6 Javadoc](https://maven.apache.org/shared/maven-archiver/apidocs/org/apache/maven/archiver/MavenArchiver.html)
- [maven-archiver commit: "don't limit outputTimestamp to zip range"](https://www.mail-archive.com/commits@maven.apache.org/msg141986.html)
- [MSHARED-1445: Unix timestamps bypass boundary checks](https://www.mail-archive.com/issues@maven.apache.org/msg283058.html)
- [MJAR-300: Timezone offset handling bug](https://www.mail-archive.com/issues@maven.apache.org/msg263967.html)
- [MJAR-301: ISO 8601 format support](https://www.mail-archive.com/issues@maven.apache.org/msg264205.html)
- [SOURCE_DATE_EPOCH specification](https://reproducible-builds.org/docs/source-date-epoch/)
- [git-commit-id-maven-plugin issue #674: dateFormat incompatibility](https://github.com/git-commit-id/git-commit-id-maven-plugin/issues/674)

---

## 2. SOURCE_DATE_EPOCH and Maven Interaction

### Specification

`SOURCE_DATE_EPOCH` is an integer (decimal, base-10) representing seconds since Unix epoch (January 1, 1970 00:00:00 UTC). No timezone component. Always interpreted as UTC.

### Maven Consumption

- **Before maven-archiver 3.6.4**: Maven did NOT read `SOURCE_DATE_EPOCH`. The only way to set a reproducible timestamp was via `project.build.outputTimestamp` in the POM or `-Dproject.build.outputTimestamp=...` on the command line.
- **Since maven-archiver 3.6.4 (2025)**: `parseBuildOutputTimestamp` falls back to the `SOURCE_DATE_EPOCH` environment variable when `project.build.outputTimestamp` is not configured or is disabled.

### Precedence Order

1. `project.build.outputTimestamp` POM property (highest)
2. `-Dproject.build.outputTimestamp=...` command-line override
3. `SOURCE_DATE_EPOCH` environment variable (fallback, since maven-archiver 3.6.4)
4. Current system time (if none are set)

### Bridging

Pass the epoch value directly: `mvn -Dproject.build.outputTimestamp="$SOURCE_DATE_EPOCH" clean package`. The parser accepts integer epoch seconds natively.

### Impact on This Project

The project sets both:
1. `ENV SOURCE_DATE_EPOCH=946684800` in templates (affects non-Maven tools, filesystem operations)
2. `-Dproject.build.outputTimestamp=2000-01-01T00:00:00Z` in REPRODUCIBLE_FLAGS (affects Maven plugins)

Both resolve to 2000-01-01T00:00:00Z, which is consistent. However, the dual-setting creates a subtle issue: if a `spec_overrides.reproducibility_env` sets `SOURCE_DATE_EPOCH` to a different value, the template adds it as an additional `ENV` line *after* the hardcoded one (see Docker ENV ordering in section 3), so the override wins — but `outputTimestamp` in the build command remains `2000-01-01`, creating a mismatch.

**Recommendation**: Make `outputTimestamp` derivable from `SOURCE_DATE_EPOCH` so they stay consistent:
```python
epoch = spec.reproducibility_env.get("SOURCE_DATE_EPOCH", "946684800")
timestamp = datetime.utcfromtimestamp(int(epoch)).strftime("%Y-%m-%dT%H:%M:%SZ")
flags = [f"-Dproject.build.outputTimestamp={timestamp}"]
```

---

## 3. Docker ENV Ordering Semantics

### Within a Single Dockerfile: Last ENV Wins

When the same variable is declared multiple times with `ENV`, Docker processes the Dockerfile top-to-bottom and **the last declaration wins**. Each subsequent `ENV` instruction overwrites the previous value.

### Within-Instruction Gotcha

Variable substitution within a single `ENV` instruction uses the values as they existed *before* that instruction executes:

```dockerfile
ENV abc=hello
ENV abc=bye def=$abc
ENV ghi=$abc
```

- `def` = `hello` (NOT `bye`) — `$abc` is resolved to its pre-instruction value
- `ghi` = `bye` — by this instruction, `abc` has been updated

**Takeaway**: If variable A's new value must feed into variable B, use separate `ENV` instructions.

### ENV vs ARG with the Same Name

**ENV always shadows ARG of the same name during build.**

```dockerfile
FROM ubuntu
ARG CONT_IMG_VER
ENV CONT_IMG_VER=v1.0.0
RUN echo $CONT_IMG_VER    # prints v1.0.0, ignoring --build-arg
```

Even with `--build-arg CONT_IMG_VER=v2.0.1`, the RUN prints `v1.0.0`. The ENV completely shadows the ARG. This is confirmed as intentional (docker/cli#3344).

**The bridge pattern** for combining them:
```dockerfile
ARG CONT_IMG_VER
ENV CONT_IMG_VER=${CONT_IMG_VER:-v1.0.0}
```

### Runtime Override Precedence (Highest → Lowest)

1. `docker run -e VAR=value` / `docker compose run -e` (highest)
2. `environment` / `env_file` in Compose with shell interpolation
3. `environment` attribute in Compose file
4. `env_file` attribute in Compose file
5. `ENV` in Dockerfile (lowest)

Runtime values always override Dockerfile defaults.

### ARG Scope Resets After Every FROM

In multi-stage builds, an ARG declared before `FROM` is only usable in the `FROM` line itself. Must redeclare after `FROM` to use in the stage.

### Impact on This Project

The current template structure:
```jinja
{% if env_vars %}
ENV {{ key }}={{ value }}    {# CI-sourced env vars #}
{% endif %}
{% if reproducibility_env %}
ENV {{ key }}={{ value }}    {# spec_overrides env vars #}
{% endif %}
ENV SOURCE_DATE_EPOCH=946684800    {# hardcoded #}
```

The hardcoded `SOURCE_DATE_EPOCH=946684800` comes **after** the `reproducibility_env` block, meaning it always overwrites any agent-specified `SOURCE_DATE_EPOCH` value. This is the re-injection problem documented in `pipeline-shortcomings-analysis.md` shortcoming #2.

**Fix**: Move the hardcoded `SOURCE_DATE_EPOCH` line to render **before** the `reproducibility_env` block, or make it conditional: `{% if 'SOURCE_DATE_EPOCH' not in reproducibility_env %}ENV SOURCE_DATE_EPOCH=946684800{% endif %}`.

### References

- [Dockerfile reference — Docker Docs](https://docs.docker.com/reference/dockerfile/)
- [Environment variables precedence in Docker Compose](https://docs.docker.com/compose/how-tos/environment-variables/envvars-precedence/)
- [Docker ARG, ENV and .env — A Complete Guide](https://vsupalov.com/docker-arg-env-variable-guide/)
- [Docker Best Practices: Using ARG and ENV](https://www.docker.com/blog/docker-best-practices-using-arg-and-env-in-your-dockerfiles/)
- [docker/cli#3344: --build-args/ARG does not overwrite ENV of same name](https://github.com/docker/cli/issues/3344)

---

## 4. Structured Error Feedback in Agentic Build Systems

### 4.1 Quantitative Evidence: What Feedback Types Work Best

The [FeedbackEval benchmark](https://arxiv.org/html/2504.06939v1) tested four feedback types across five LLMs on code repair tasks:

| Feedback Type | Category | Avg Repair@1 | Repair@3 (best) |
|---|---|---|---|
| **Test feedback** (pytest output with tracebacks) | Structured | 61.0% | 93.9% (GPT-4o) |
| **Simple feedback** ("The code is wrong. Please fix it.") | Unstructured | 56.9% | 89.1% (Claude-3.5) |
| **Compiler feedback** (pylint diagnostics) | Structured | 55.8% | 85.6% (Claude-3.5) |
| **Human feedback** (natural language review) | Unstructured | 50.5% | 82.8% (Claude-3.5) |

**Critical finding**: Minimal "the code is wrong" feedback outperforms verbose compiler diagnostics and detailed human reviews. LLMs benefit more from a clear retry signal than from noisy diagnostic information. Noise hurts more than silence.

**Iteration data**: Performance stabilizes after 2-3 rounds with diminishing returns beyond that. Convergence: 49% at round 1, 58% at round 2, 63% at round 3, flat after that.

### 4.2 Optimal Prompt Structure for Build Error Feedback

The [industrial CI repair study](https://arxiv.org/html/2510.13575v1) tested seven prompt configurations:

| Prompt Config | Pass Rate |
|---|---|
| Error log only | 19-35% |
| Full source file only | 8-19% |
| Error log + code snippet (3-line context) | 45-55% |
| Error log + code snippet + historical fix example | **49-63%** |

**Optimal structure:**
```
## Error Category: {category}
## Error Log
{focused_error_output — NOT full log}

## Erroneous Code (±3 lines context)
{extracted_snippet_around_error_line}

## Similar Historical Fix
Before: {previous_buggy_pattern}
After: {previous_fixed_pattern}

## Instructions
Generate replacement. Output ONLY the fix.
```

**Design rules:**
- Include 3 lines of context around the error location — optimal balance
- Maximum 3 error snippets per prompt
- Categorize error FIRST, then select the matching historical fix example
- Raw full logs without focused extraction perform worst (8-19%)
- Focused error snippets without full file context outperform full file dumps

### 4.3 Google's Auto-Diagnose System (ICSE 2026)

[Auto-Diagnose](https://arxiv.org/html/2604.12108v1) diagnoses integration test failures at Google using Gemini 2.5 Flash. Key architectural patterns:

**Prompt construction**: Logs from multiple sources are joined and sorted by timestamp into a single stream, appended under a `<LOGS=>` section. Component metadata placed under a `<CONTEXT=>` section. Median: 16 log files, 2,801 log lines, ~110K input tokens per execution.

**Structured output**: Three mandatory sections:
- `==Conclusion==` — root cause summary
- `==Investigation Steps==` — reasoning chain
- `==Most Relevant Log Lines==` — with schema: `log-file-name`, `timestamp`, `callsite`, `**content**`

**Negative constraints** (critical for avoiding hallucination):
- "If the logs do not contain any log lines from the component that failed, you MUST NOT draw any conclusion"
- "Any conclusion must be based on log lines, you MUST NOT draw conclusions by guessing"
- Step 8 requires the model to acknowledge when "more information" is needed rather than fabricating a diagnosis

**Results**: 90.14% accuracy on manual evaluation, 62.96% helpfulness rate in production (gap attributed to negativity bias), median 56 seconds to post findings. Ranked #14 of 370 tools (top 3.78%) in helpfulness.

**Key prompt design choices:**
- 8-step mandatory investigation process (model cannot skip steps)
- Steps 6-7 create a verify gate — reach a conclusion, then verify sufficient evidence exists
- Step 8: escalate over fabricate — identify missing information rather than guess
- Temperature 0.1 for near-deterministic outputs
- Zero-shot prompting only (no fine-tuning)

### 4.4 Iterative Repair Loop Patterns

From the [APR survey](https://arxiv.org/html/2506.23749v1):

**Pattern A: Generate-Test-Feed** (simplest, most proven)
```
build error → LLM generates patch → run build → success? done : feed error back
```
Cap at 3 rounds. Used by ChatRepair (5 rounds), industrial CI systems (3 rounds optimal).

**Pattern B: Analyze-Diagnose-Feed** (richer feedback)
```
build error → static analysis → categorize → LLM generates patch with category-matched
historical fix → run build → freeze successful portions → iterate on remaining errors
```
Key innovation: **freeze fixed portions** to prevent regression (PredicateFix system).

**Pattern C: Bandit-Guided Search** (cost-efficient)
From REx: treats each partial patch as a multi-armed bandit arm. Reward = proportion of checks passing. Reduces LLM calls 2-5x compared to naive iteration.

### 4.5 Error Categorization Schema for Maven Builds

Based on [industrial CI data](https://arxiv.org/html/2510.13575v1), the optimal categorization:

| Category | Frequency | Subcategories |
|---|---|---|
| DEPENDENCY_RESOLUTION | ~76% | MISSING_ARTIFACT, VERSION_CONFLICT, MISSING_VERSION, REPOSITORY_UNREACHABLE |
| COMPILATION | ~10% | SYMBOL_NOT_FOUND, TYPE_MISMATCH, MISSING_IMPORT, JAVA_VERSION |
| PLUGIN_EXECUTION | ~5% | PLUGIN_NOT_FOUND, GOAL_FAILURE, CONFIGURATION_ERROR |
| POM_STRUCTURE | ~3% | NON_PARSEABLE, INVALID_ELEMENT, ENCODING_MISMATCH |
| TEST_FAILURE | ~6% | ASSERTION_FAILED, TEST_ERROR, COMPILATION_IN_TEST |

### 4.6 Error Propagation in Multi-Agent Systems

The [MAST taxonomy](https://arxiv.org/html/2503.13657v3) analyzed 1,600+ execution traces:

- **Error propagation is the #1 bottleneck** — early mistakes cascade into subsequent steps
- **41.8% of failures** are specification/system design issues (not model capability)
- **37% of failures** are inter-agent misalignment (format mismatches, conflicting objectives)
- Memory and reflection errors are the most common cascade sources

Control-theory analysis models error growth as E(t) = Σ(Aᵏ), showing exponential amplification without negative feedback.

### 4.7 Actionable Recommendations for This Project

Based on the research synthesis:

**R1. Structure build error feedback as typed records, not raw logs.**
The current `build_remediation_context()` at `analyzer.py:430-488` already computes rich structured context (progress delta, root causes, fix direction, relaxation flags, error trajectory). This function is never called (shortcoming #5 in pipeline-shortcomings-analysis.md). Wiring it up is the single highest-impact change.

**R2. Limit feedback verbosity — focused extraction beats raw dump.**
The FeedbackEval result showing "the code is wrong" outperforming verbose compiler diagnostics is a strong signal: noise hurts. The current 5000→3000 char tail truncation (shortcoming #4) is the worst approach. Replace with the existing `extract_build_log_excerpt()` function, which already does smart error-line extraction with ±2 lines of context.

**R3. Cap iterations at 3 for any single error class.**
Every study converges on this: rounds 1-2 produce the biggest gains, round 3 adds marginally, rounds 4+ are wasted tokens. The project's `detect_error_loop()` already catches 3+ repetitions — but only if `build_remediation_context()` is wired up.

**R4. Categorize error BEFORE prompting the AnalyzeAgent.**
The local `classify_error()` already produces an error class. Use this to select a category-specific prompt section with the matching historical fix pattern, rather than giving the AnalyzeAgent a generic prompt and hoping it classifies correctly.

**R5. Add negative constraints to the AnalyzeAgent prompt.**
Following Auto-Diagnose's pattern, add explicit constraints:
- "If the build log does not contain evidence for a specific root cause, state that evidence is insufficient — do NOT guess"
- "Every spec_override you suggest MUST be traceable to a specific error line in the build log"
- "If you previously suggested a spec_override that was applied but the same error recurs, the override mechanism may not control this value — flag it as systemic"

**R6. Freeze successful fixes across iterations.**
When a build progresses further (e.g., from compilation to testing), the fixes that got it past compilation should be locked. The `BuildProgress` tracking at `analyzer.py:193-209` already computes this — use it to mark successful overrides as non-removable.

**R7. Pass iteration diffs to the AnalyzeAgent.**
Auto-Diagnose's success comes partly from consolidating information across sources. The AnalyzeAgent should see: previous Containerfile, current Containerfile, diff between them, previous error class, current error class, what spec_overrides were applied. This is shortcoming #6.

### References

- [FeedbackEval: Benchmarking Feedback-Driven Code Repair (2025)](https://arxiv.org/html/2504.06939v1)
- [Auto-Diagnose: LLM-Based Automated Diagnosis at Google (ICSE 2026)](https://arxiv.org/html/2604.12108v1)
- [Survey of LLM-based Automated Program Repair (2025)](https://arxiv.org/html/2506.23749v1)
- [Auto-repair of Compilation Errors in Industrial CI (2025)](https://arxiv.org/html/2510.13575v1)
- [RepairAgent: Autonomous LLM-Based Program Repair (ICSE 2025)](https://software-lab.org/publications/icse2025_RepairAgent.pdf)
- [DrRepair: Program-Feedback Graph for Code Repair (Stanford)](http://ai.stanford.edu/blog/DrRepair/)
- [MAST: Multi-Agent System Failure Taxonomy (2025)](https://arxiv.org/html/2503.13657v3)
- [HarnessFix: Diagnosing Agent Failures (2026)](https://arxiv.org/html/2606.06324v1)
- [Insights Generator: Corpus-Level Trace Diagnostics (2026)](https://arxiv.org/html/2605.21347v1)
- [LLM-Driven CI Failure Diagnosis and Repair (2025)](https://www.researchgate.net/publication/401215124)

---

## 5. Synthesis: What This Means for Issue #45

### The Core Problem

The pipeline has rich diagnostic infrastructure (`classify_error()`, `estimate_build_progress()`, `extract_root_cause_details()`, `build_remediation_context()`, `detect_error_loop()`) that is computed but never reaches the agents that need it. The AnalyzeAgent gets raw truncated logs. The node agents get nothing.

### Priority Actions (from research evidence)

| Priority | Action | Evidence | Impact |
|---|---|---|---|
| P0 | Wire `build_remediation_context()` into AnalyzeAgent prompt | Auto-Diagnose: structured context → 90% accuracy; FeedbackEval: structured > raw | AnalyzeAgent gets error class, progress delta, root causes, loop detection |
| P0 | Replace tail truncation with `extract_build_log_excerpt()` output | FeedbackEval: focused extraction > verbose dump; Industrial CI: 3-line context optimal | Key error lines preserved instead of lost to truncation |
| P1 | Add negative constraints to AnalyzeAgent system prompt | Auto-Diagnose: negative constraints prevent hallucination; 90% accuracy | Stops the "guess wrong" failure mode (commons-lang3 case) |
| P1 | Pass build error context to node agents on re-observation | MAST: 37% of multi-agent failures are inter-agent misalignment | Node agents can diagnose domain-specific issues with their expertise |
| P1 | Add `plugin/timestamp_range` error pattern | Direct from maven-archiver version analysis | Catches the specific commons-lang3 failure class |
| P2 | Fix template ENV ordering for SOURCE_DATE_EPOCH overridability | Docker ENV: last declaration wins; current template puts hardcoded value last | Agent-specified SOURCE_DATE_EPOCH values actually take effect |
| P2 | Cap same-error iterations at 3 (hard limit) | Every APR study: rounds 4+ produce zero marginal gain | Saves $6+/package in wasted AnalyzeAgent calls |
| P2 | Derive outputTimestamp from SOURCE_DATE_EPOCH | Consistency between the two timestamp systems | Eliminates mismatch when agents override one but not the other |
| P3 | Add category-specific historical fix examples to AnalyzeAgent prompt | Industrial CI: historical examples boost pass rate from 45-55% to 49-63% | AnalyzeAgent produces more targeted fixes |
| P3 | Freeze successful overrides when build progresses | PredicateFix: freezing prevents regression | Stops oscillation between error classes |
