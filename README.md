# Buildroot Reconstructor

Autonomous system for reconstructing Maven Central artifacts as reproducible Containerfiles. Given a Maven coordinate (`groupId:artifactId:version`), it produces a Containerfile that builds the artifact from source and matches the original JAR byte-for-byte.

## Architecture Overview

```
                          ┌─────────────────────────────────┐
                          │        buildroot agent           │
                          │     (v4 orchestrator entry)      │
                          └──────────┬──────────────────────┘
                                     │
                          ┌──────────▼──────────────────────┐
                          │          Pre-Pass                │
                          │  • Download JAR from Maven Central│
                          │  • Extract MANIFEST.MF           │
                          │  • Detect build system           │
                          │  • Identify JDK version          │
                          │  • Detect OSGI, multi-release    │
                          └──────────┬──────────────────────┘
                                     │
                          ┌──────────▼──────────────────────┐
                          │      Knowledge Base Query        │
                          │  • Match by build system + tags  │
                          │  • Retrieve templates, tips,     │
                          │    tricks ranked by relevance    │
                          └──────────┬──────────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │   Claude Code Orchestrator Agent │
                    │   (system prompt + domain KB)    │
                    └──────┬─────────────────┬────────┘
                           │                 │
                  ┌────────▼───────┐  ┌──────▼──────────────┐
                  │   v3 Pipeline   │  │   Agent Takeover     │
                  │   (fast path)   │  │   (when v3 stalls)   │
                  │                 │  │                      │
                  │ Template-based  │  │ Writes Containerfile │
                  │ Jinja2 render   │  │ directly, uses       │
                  │ + AI feedback   │  │ buildroot eval to    │
                  │ loop            │  │ iterate              │
                  └────────┬───────┘  └──────┬──────────────┘
                           │                 │
                           └────────┬────────┘
                                    │
                          ┌─────────▼───────────────────────┐
                          │      L1–L4 Evaluation            │
                          │  L1: Containerfile parses        │
                          │  L2: Image builds (Podman/SSH)   │
                          │  L3: JAR found in image          │
                          │  L4: JAR matches original        │
                          │      (structural + metadata +    │
                          │       bytecode comparison)       │
                          └──────────┬──────────────────────┘
                                     │
                          ┌──────────▼──────────────────────┐
                          │      Learning Loop               │
                          │  • Save winning Containerfile    │
                          │    as KB template entry          │
                          │  • Update usage stats on         │
                          │    matched KB entries            │
                          └─────────────────────────────────┘
```

## How It Works

### 1. Pre-Pass Analysis

Before any build attempt, the system downloads the original JAR from Maven Central and extracts metadata:

- **Build system detection** — Maven (`pom.xml`), Gradle (`build.gradle`), or Ant (`build.xml`)
- **JDK version** — from `Build-Jdk-Spec` or `Created-By` in `META-INF/MANIFEST.MF`
- **Special features** — OSGI bundle headers (`Bundle-SymbolicName`), multi-release JARs (`Multi-Release: true`)
- **Source repo discovery** — resolves the source repository URL from POM metadata and GitHub API

### 2. Knowledge Base Query

The pre-pass findings are used to query the KB for relevant context:

- Templates from previously solved packages with the same build system
- Tips for handling specific patterns (OSGI wrapping, multi-release compilation)
- Tricks for known error patterns (encoding issues, hsperfdata leaks)

All matched entries are injected into the agent's system prompt ranked by relevance score.

### 3. Orchestrator Agent (v4)

A Claude Code session is spawned with full domain expertise (Java build systems, JAR structure, bytecode matching, OSGI bundles) and access to all tools.

**The agent follows a two-phase strategy:**

#### Phase 1: v3 Fast Path

The agent runs the v3 template pipeline first — a Jinja2-based system that renders Containerfiles from templates and iterates using an AI feedback loop. For standard Maven/Gradle packages, v3 solves them in 3–5 iterations.

```
v3 Pipeline:
  Iteration 1: Render template with pre-pass values
       │
       ▼
  buildroot eval → L1? L2? L3? L4? → reward ≥ 0.98? → Done
       │                                    │
       │ no                                 │
       ▼                                    │
  AI Feedback Agent reads eval output,      │
  suggests template parameter changes       │
       │                                    │
       ▼                                    │
  Iteration 2: Re-render with new values ───┘
       │
      ... (up to max_iterations)
```

The v3 feedback loop:
1. Renders a Containerfile from the Jinja2 template with current parameter values
2. Evaluates it via L1–L4 (build on remote host, compare JAR)
3. An AI feedback agent reads the eval output (build errors, comparison report) and suggests parameter changes
4. Re-renders with updated parameters
5. Detects stagnation (same score for 2+ iterations) and exits

#### Phase 2: Agent Takeover

When v3 stagnates or hits template limitations, the orchestrator takes over:

1. Reads v3's best Containerfile and build artifacts
2. Writes its own Containerfile directly (can express multi-stage builds, cross-compilation, custom tooling)
3. Evaluates with `buildroot eval` — gets structured JSON with L1–L4 scores and comparison report
4. Reads the comparison report to identify exactly what's failing (structural/metadata/bytecode)
5. Fixes the specific dimension and re-evaluates
6. Iterates until reward ≥ 0.98 or exhausts approaches

```
Takeover Loop:
  Read v3 best Containerfile + KB tips
       │
       ▼
  Write custom Containerfile
       │
       ▼
  buildroot eval → JSON output:
  {                                        ┌─ L2 fail: read build log,
    "l1_parse": true,                      │  fix build command
    "l2_build": true,                      │
    "l3_command": true,                    ├─ L3 fail: check JAR location,
    "l4_match": false,                     │  verify build output
    "l4_score": 0.87,                      │
    "comparison_report": {                 ├─ L4 structural: compare file
      "structural": {"match": false, ...}, │  lists, fix missing/extra
      "metadata": {"match": true, ...},    │
      "bytecode": {"match": false, ...}    └─ L4 bytecode: match JDK
    }                                         version exactly
  }
       │
       ▼
  Fix the failing dimension → re-evaluate → repeat
```

### 4. L1–L4 Evaluation

Every Containerfile is scored against a 4-level hierarchy:

| Level | Weight | What It Checks | Pass Condition |
|-------|--------|---------------|----------------|
| **L1 Parse** | 0.05 | Containerfile syntax | Valid Dockerfile parsed by `dockerfile-parse` |
| **L2 Build** | 0.10 | Container image builds | `podman build` succeeds on remote host via SSH |
| **L3 Command** | 0.35 | JAR exists in image | `find target/ build/libs/ -name '*.jar'` finds output |
| **L4 Match** | 0.50 | JAR matches original | 3-way comparison: structural + metadata + bytecode |

**Scoring formula:**
```
reward = 0.05 × L1 + 0.10 × L2 + 0.35 × L3 + 0.50 × L4_score
```

A reward ≥ 0.98 means near-perfect reproduction. The target is 1.0 (byte-identical).

#### L4 JAR Comparison

When L3 passes (JAR found), the system downloads the original JAR from Maven Central and compares:

- **Structural** — same set of file entries (classes, resources, META-INF/). Reports `missing` and `extra` files.
- **Metadata** — MANIFEST.MF headers match. Reports `manifest_diff_keys` for any header mismatches.
- **Bytecode** — class files produce identical SHA hashes. Reports `classes_divergent` listing which classes differ.

The comparator ignores signature files (`.SF`, `.DSA`, `.RSA`) since they require private keys.

### 5. Learning Loop

When a package is solved (reward ≥ 0.98):

1. The winning Containerfile is saved to the KB as a `template` entry
2. Usage counters and success rates are updated on all matched KB entries
3. Future packages with the same build system/tags benefit from the learned template

## Knowledge Base

### Storage

KB entries are YAML files stored in `~/.buildroot/kb/`. Each file is a self-contained entry.

### Entry Types

**Templates** — Complete Containerfiles from successfully solved packages:
```yaml
name: template-commons-lang3-3-14-0
type: template
description: "Winning Containerfile for org.apache.commons:commons-lang3:3.14.0 (L4=1.0000)"
tags: [maven, osgi, multi-release]
build_systems: [maven]
containerfile: "FROM eclipse-temurin:21-jdk\n..."
coordinate: "org.apache.commons:commons-lang3:3.14.0"
l4_score: 1.0
times_used: 4
success_rate: 1.0
```

**Tips** — Techniques with trigger conditions and solutions:
```yaml
name: bnd-osgi-wrap
type: tip
description: "Use Bnd tool to generate correct OSGI bundle headers"
tags: [osgi, bnd, manifest]
build_systems: [ant, maven, gradle]
trigger: "JAR manifest requires OSGI headers (Bundle-SymbolicName, ...)"
solution: "Use Bnd 2.2.0 to wrap the JAR with correct OSGI headers..."
caveats: "Bnd version must match exactly — different versions produce different formatting"
```

**Tricks** — Error-to-fix mappings:
```yaml
name: encoding-utf8
type: trick
description: "Add -encoding UTF-8 to javac for non-ASCII source files"
tags: [javac, encoding, utf8]
build_systems: [ant, maven, gradle]
error_pattern: "unmappable character"
fix: "Add -encoding UTF-8 to javac invocations..."
example_log: "error: unmappable character (0xC2) for encoding ASCII"
```

### Retrieval

Entries are ranked by a weighted scoring function:

| Signal | Weight | Condition |
|--------|--------|-----------|
| Build system match | +3.0 | Entry's `build_systems` contains the query build system |
| Tag match | +2.0 per tag | Entry's `tags` overlap with query tags |
| Error pattern match | +5.0 | Trick's `error_pattern` found in query (exact match) |
| Group ID match | +4.0 | Template's `coordinate` starts with query group ID |
| Free-text match | +1.0 per word | Query words found in entry's searchable fields |
| Usage boost | ×1.1 | Entries with `times_used > 0` and high `success_rate` get a multiplier |

### Seeding

The KB ships with 10 seed entries derived from the Bouncy Castle proof-of-concept — tips for Ant version pinning, Bnd OSGI wrapping, multi-release JDK 9 compilation, encoding, hsperfdata suppression, and more. Run `buildroot kb seed` to populate them.

## Installation

```bash
pip install -e .
```

**Requirements:**
- Python ≥ 3.11
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude` on PATH) — for the orchestrator agent
- SSH access to a build host with Podman installed
- Network access to Maven Central and GitHub

## Usage

### Quick Start

```bash
# Reconstruct a single package (v4 orchestrator — autonomous)
buildroot agent org.apache.commons:commons-lang3:3.14.0

# Interactive mode — launches a live Claude session with full context
buildroot agent org.apache.commons:commons-lang3:3.14.0 --interactive

# v3 template pipeline only (faster, cheaper, limited to template-expressible builds)
buildroot agent org.apache.commons:commons-lang3:3.14.0 --v3-only
```

### CLI Reference

#### `buildroot agent` — Run the agentic reconstruction loop

```
buildroot agent COORDINATE [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `COORDINATE` | *(required unless `--batch`)* | Maven coordinate: `groupId:artifactId:version` |
| `--host` | `rh-h100-01` | SSH host for remote Podman builds |
| `--max-iterations` | `15` | Max inner-loop iterations (v3 pipeline) |
| `--batch FILE` | — | File with one coordinate per line for batch processing |
| `--output DIR` | `results/batch-v3` | Output directory for batch results |
| `--resume DIR` | — | Resume from prior results directory (warm-starts RecipeStore) |
| `--v3-only` | `false` | Use v3 template pipeline only (no orchestrator) |
| `--interactive` | `false` | Launch interactive Claude session with orchestrator context |
| `--max-budget` | `0` | Max budget in USD (`0` = unlimited) |
| `--max-turns` | `0` | Max agent turns (`0` = unlimited) |
| `-v, --verbose` | `false` | Enable debug logging |

**Modes:**

- **Default (v4 orchestrator):** Spawns a headless Claude Code agent with domain expertise. The agent runs v3 as its fast path, takes over when v3 stagnates, and iterates with `buildroot eval` until solved. No timeout, no budget limit.

- **`--interactive`:** Same orchestrator context (pre-pass, KB, domain expertise) but launches a live Claude Code TUI session. You can guide the agent, ask questions, or let it run autonomously.

- **`--v3-only`:** Runs the template-based pipeline directly. Faster and cheaper for standard packages, but limited to what Jinja2 templates can express. Cannot handle multi-stage builds, OSGI wrapping, or custom tooling.

- **`--batch`:** Processes multiple coordinates sequentially. Always uses v3. Writes per-package JSON results and a summary.

#### `buildroot eval` — Evaluate a Containerfile

```
buildroot eval CONTAINERFILE COORDINATE [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `CONTAINERFILE` | *(required)* | Path to the Containerfile to evaluate |
| `COORDINATE` | *(required)* | Maven coordinate to compare against |
| `--host` | `rh-h100-01` | SSH host for remote builds |
| `--timeout` | `900` | Build timeout in seconds |
| `--pretty / --no-pretty` | `true` | Pretty-print JSON output |

Returns JSON with L1–L4 scores, comparison report, and reward:

```json
{
  "l1_parse": true,
  "l2_build": true,
  "l3_command": true,
  "l4_match": false,
  "l4_score": 0.8734,
  "reward": 0.9367,
  "level_reached": 3,
  "comparison_verdict": "DIVERGENT",
  "comparison_report": {
    "verdict": "DIVERGENT",
    "equivalence_score": 0.8734,
    "structural_match": true,
    "metadata_match": false,
    "bytecode_match": false
  }
}
```

#### `buildroot compare` — Compare a rebuilt JAR against the original

```
buildroot compare COORDINATE --rebuilt-jar PATH [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--rebuilt-jar` | *(required)* | Path to the rebuilt JAR file |
| `--output-dir` | `.` | Output directory for the comparison report |
| `--original-jar` | — | Path to original JAR (downloads from Maven Central if omitted) |

#### `buildroot inspect` — Inspect resolved build environment

```
buildroot inspect COORDINATE [--no-cache]
```

Shows the resolved build configuration for a Maven coordinate: JDK version, build system, source repo, CI configuration.

#### `buildroot reconstruct` — Generate a Containerfile (non-agentic)

```
buildroot reconstruct COORDINATE [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--repo-url` | — | Override source repository URL |
| `--ci-type` | — | Hint CI system type (`github`, `circleci`) |
| `--no-cache` | `false` | Skip POM cache |
| `--skip-deps` | `false` | Skip transitive dependency resolution |
| `--output-dir` | `.` | Output directory for generated files |
| `--runtime` | `podman` | Container runtime (`podman`, `docker`) |

#### `buildroot verify` — Verify a generated Containerfile

```
buildroot verify COORDINATE [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--rebuild` | `false` | Attempt full rebuild and artifact comparison |
| `--runtime` | `podman` | Container runtime |
| `--output-dir` | `.` | Directory containing generated buildroot files |

#### `buildroot validate` — Validate against PNC ground truth

```
buildroot validate COORDINATE --builders-image-dir DIR --pnc-image IMAGE [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--builders-image-dir` | *(required)* | Path to PNC builders-image repo |
| `--pnc-image` | *(required)* | PNC builder image name |
| `--output-dir` | `results/pnc-validation` | Output directory |
| `--skip-deps` | `false` | Skip dependency resolution |

#### `buildroot regression` — Run regression tests against golden Containerfiles

```
buildroot regression [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--quick` | `false` | Run only the canary package (commons-lang3) |
| `--package TEXT` | — | Run a single package by short name |
| `--host` | `rh-h100-01` | SSH host for remote builds |
| `--report` | `false` | Write detailed results to `results/regression/<timestamp>/` |
| `--status` | `false` | Show suite status and baselines |
| `--timeout` | `900` | Eval timeout per package in seconds |
| `--e2e` | `false` | Run end-to-end pipeline test on the canary (commons-lang3) |

The regression suite validates that pipeline changes don't break what already works. It re-evaluates golden Containerfiles (checked into `tests/regression/golden/`) against their established baselines. Exit code 0 means all clear; exit code 1 means a regression was detected.

**Golden packages:**

| Package | Build System | Baseline | Challenge |
|---------|-------------|----------|-----------|
| commons-lang3:3.14.0 | Maven | 1.0 | Canary — simplest, must always pass |
| jackson-core:2.15.3 | Maven | 0.5 | Multi-module Maven, L3 match |
| json-path:2.9.0 | Gradle | 0.5 | Gradle + Bnd/OSGi, L3 match |
| bcprov-jdk15on:1.70 | Ant | 1.0 | Proprietary toolchain, JAR download |
| protobuf-java:3.25.2 | Maven | 0.15 | Google mergejars post-processing |

```bash
# Quick smoke test (canary only — fast)
buildroot regression --quick

# Full suite — all 5 packages
buildroot regression

# Check which packages are ready
buildroot regression --status

# Full pipeline E2E — runs buildroot agent on the canary from scratch
buildroot regression --e2e

# Write detailed JSON report
buildroot regression --report
```

**Adding new golden packages:** When a package reaches a stable score and covers a distinct challenge type, save its Containerfile to `tests/regression/golden/<name>.Containerfile` with a companion `<name>.json` metadata file containing `coordinate`, `baseline_reward`, `baseline_l4_score`, `build_system`, `difficulty`, and `has_golden_containerfile: true`. Run `buildroot regression --package <name>` to verify, then commit both files.

#### `buildroot kb` — Manage the knowledge base

```bash
# List all entries
buildroot kb list [--type template|tip|trick] [--json-output]

# Search by query
buildroot kb search "osgi bundle" [--build-system maven] [--limit 10] [--json-output]

# Add an entry from YAML
buildroot kb add path/to/entry.yaml

# Seed with Bouncy Castle entries (10 entries)
buildroot kb seed
```

### Examples

```bash
# Reconstruct a simple Maven package (v4 orchestrator, autonomous)
buildroot agent org.json:json:20231013

# Reconstruct a complex OSGI bundle interactively
buildroot agent org.bouncycastle:bcprov-jdk15on:1.70 --interactive

# Use v3 only for a standard package
buildroot agent org.yaml:snakeyaml:2.2 --v3-only --max-iterations 10

# Batch process a list of packages
buildroot agent --batch packages.txt --v3-only --output results/batch-run

# Resume from a previous batch (warm-starts from solved packages)
buildroot agent --batch packages.txt --v3-only --resume results/batch-run

# Evaluate a hand-written Containerfile
buildroot eval ./Containerfile com.google.protobuf:protobuf-java:3.25.2

# Compare a rebuilt JAR directly
buildroot compare org.apache.commons:commons-lang3:3.14.0 --rebuilt-jar target/commons-lang3-3.14.0.jar

# Search KB for OSGI-related tips
buildroot kb search "osgi manifest bnd"
```

### Build Host Setup

The eval system builds containers on a remote host via SSH. The host needs:

- **Podman** installed and accessible to the SSH user
- **SSH key-based auth** configured (no password prompts)
- Sufficient disk space for container images

```bash
# Verify connectivity
ssh rh-h100-01 "podman --version"
```

## Project Structure

```
src/buildroot/
├── cli/                    # CLI entry points
│   ├── main.py             # Click command group
│   └── commands/
│       ├── agent_cmd.py    # buildroot agent
│       ├── eval_cmd.py     # buildroot eval
│       ├── kb_cmd.py       # buildroot kb
│       ├── compare.py      # buildroot compare
│       ├── inspect_cmd.py  # buildroot inspect
│       ├── reconstruct.py     # buildroot reconstruct
│       ├── regression_cmd.py  # buildroot regression
│       ├── validate.py        # buildroot validate
│       └── verify.py          # buildroot verify
├── agent/
│   ├── meta_agent.py       # v4 orchestrator (interactive + headless)
│   ├── meta_prompt.py      # Domain expert system prompt builder
│   ├── claude_runner.py    # Claude Code subprocess runner
│   ├── pipeline_v3.py      # v3 template pipeline with feedback loop
│   ├── evaluator.py        # L1–L4 evaluation chain
│   ├── prepass.py           # Pre-pass JAR analysis
│   ├── feedback.py          # AI feedback agent for v3
│   ├── analyzer.py          # Source code analysis
│   ├── models.py            # Data models (EvalResult, RecipeStore)
│   ├── scorer.py            # Scoring utilities
│   └── knowledge/
│       ├── schema.py        # KB entry types (Template, Tip, Trick)
│       ├── retrieval.py     # Ranked KB query engine
│       ├── seed.py          # Bouncy Castle seed entries
│       └── knowledge_base.py
├── pipeline/
│   ├── orchestrator.py     # GAV parsing, build orchestration
│   └── models.py
├── generators/
│   └── containerfile.py    # Jinja2 Containerfile template
├── parsers/                # POM, CI config, properties parsers
├── resolvers/              # JDK, container image, dependency resolvers
└── utils/
    ├── jar_comparator.py   # 3-way JAR comparison (structural/metadata/bytecode)
    ├── maven_central.py    # Maven Central API client
    ├── github_api.py       # GitHub API for source repo discovery
    └── accuracy_scorer.py  # Accuracy scoring utilities
```

## Benchmark Results

*Pending — full v4 benchmark run on 31 packages + Bouncy Castle.*
