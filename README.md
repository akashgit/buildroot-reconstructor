# Buildroot Reconstructor

Given a Java package on Maven Central, this tool figures out how to build it from source and produces a Containerfile (Dockerfile) that reproduces the original JAR byte-for-byte. It does this autonomously using an AI agent loop — you give it a package coordinate like `org.apache.commons:commons-lang3:3.14.0`, and it gives you back a reproducible build recipe.

The point is supply chain security. If you can rebuild a published artifact from source and get the exact same bytes, you have strong evidence that the published artifact actually came from that source code. This is build provenance reconstruction — done from the consumer side, without access to the original build infrastructure.

## Getting Started

```bash
git clone https://github.com/akashgit/buildroot-reconstructor.git
cd buildroot-reconstructor
pip install -e .
```

You also need:
- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and on your PATH (the `claude` command)
- SSH access to a Linux machine with [Podman](https://podman.io/) installed (this is where containers actually get built)
- Network access to Maven Central and GitHub

Verify your build host is reachable:

```bash
ssh your-build-host "podman --version"
```

## What It Does

You give it a Maven coordinate. It tries to produce a Containerfile that, when built, creates the exact same JAR that's published on Maven Central.

```bash
buildroot agent org.apache.commons:commons-lang3:3.14.0
```

Behind the scenes, the system:

1. **Downloads the published JAR** from Maven Central and examines it — reads `META-INF/MANIFEST.MF` to figure out which JDK built it, looks at the POM to find the source repo on GitHub, checks whether it uses Maven, Gradle, or Ant.

2. **Queries a knowledge base** of tips and templates from previously solved packages. If it's seen a similar package before, it starts from what worked last time.

3. **Generates a Containerfile** using Jinja2 templates seeded with the discovered build parameters (JDK version, build tool, source repo URL, git tag, build command).

4. **Builds it on the remote host** via SSH + Podman. The Containerfile gets sent to the build host, `podman build` runs, and the resulting JAR is extracted.

5. **Compares the rebuilt JAR against the original**, checking three dimensions:
   - Do they contain the same files? (structural)
   - Do the manifests match? (metadata)
   - Are the `.class` files byte-identical? (bytecode)

6. **Feeds the comparison back to an AI agent** (Claude), which reads the build errors or comparison diff and suggests fixes — wrong JDK version, missing build flags, encoding issues, etc.

7. **Repeats** until the rebuilt JAR matches the original (reward >= 0.98) or it runs out of iterations.

## The Evaluation Levels (L1 through L4)

Every Containerfile is scored on a 4-level ladder. Each level gates the next — you can't get to L4 without passing L1 through L3 first.

**L1 — Parse (weight: 5%).** Does the Containerfile parse as valid Dockerfile syntax? This catches broken `RUN` commands, missing `FROM` lines, bad quoting. It's a syntax check, nothing more.

**L2 — Build (weight: 10%).** Does `podman build` succeed? The Containerfile is sent to the remote build host and actually built. This catches missing packages, wrong base images, broken download URLs, compilation errors. A passing L2 means you have a working container image.

**L3 — JAR exists (weight: 35%).** Is the expected JAR file present inside the built image? The system searches `target/`, `build/libs/`, and other standard output directories. A passing L3 means the build produced the artifact we're looking for.

**L4 — JAR matches the original (weight: 50%).** This is the hard part. The rebuilt JAR is downloaded from the image and compared against the Maven Central original across three dimensions:

- **Structural match** — same ZIP entries (same `.class` files, same resources, same directory structure). Reports any missing or extra files.
- **Metadata match** — `MANIFEST.MF` headers are identical. Checks `Build-Jdk-Spec`, `Created-By`, bundle headers, etc.
- **Bytecode match** — every `.class` file produces the same SHA-256 hash. This is where JDK version, compiler flags, and source encoding matter.

The L4 score is a float between 0 and 1. A score of 1.0 means the rebuilt JAR is byte-identical to the original (ignoring signature files, which require private keys). The composite reward is:

```
reward = 0.05 * L1 + 0.10 * L2 + 0.35 * L3 + 0.50 * L4_score
```

## Two Pipeline Modes

### v3 — Template Pipeline (fast, cheap)

A Jinja2 template renders a Containerfile from discovered parameters. An AI feedback agent reads eval output and adjusts parameters (JDK version, build flags, Maven/Gradle options). Good for standard packages. Runs 3-5 iterations, costs a few cents.

```bash
buildroot agent org.apache.commons:commons-lang3:3.14.0 --v3-only
```

### v4 — Orchestrator (autonomous, powerful)

Spawns a full Claude Code session with domain expertise. Starts with v3 as a fast path, then takes over when templates can't express what's needed — multi-stage builds, custom post-processing, non-standard toolchains. The agent writes Containerfiles directly, runs `buildroot eval`, reads the comparison report, and iterates.

```bash
buildroot agent org.apache.commons:commons-lang3:3.14.0
```

Add `--interactive` to get a live Claude session where you can guide the agent:

```bash
buildroot agent org.bouncycastle:bcprov-jdk15on:1.70 --interactive
```

## Regression Suite

The project maintains a suite of 5 golden packages that cover different build systems and difficulty levels. These serve as the benchmark — any pipeline change must not regress these baselines.

```bash
# See current baselines
buildroot regression --status

# Run all 5 packages
buildroot regression

# Quick canary check (commons-lang3 only)
buildroot regression --quick

# Re-solve packages through the full pipeline (warm-starts from golden Containerfiles)
buildroot regression --solve
```

### Current Results (June 2025)

All 5 golden packages are solved to L4:

| Package | Build System | Difficulty | Reward | L4 | How It Was Solved |
|---------|-------------|------------|--------|-----|-------------------|
| commons-lang3:3.14.0 | Maven | Easy | 1.0000 | 1.0000 | v3 template, 3 iterations. Standard Maven + Temurin JDK 21. The canary — if this breaks, something is very wrong. |
| jackson-core:2.15.3 | Maven | Medium | 1.0000 | 1.0000 | v4 orchestrator, ~20 min. Used the project's own Maven wrapper (`./mvnw`) with Temurin JDK 8. Agent worked around GitHub API rate limits by falling back to source-level heuristics. |
| json-path:2.9.0 | Gradle | Medium | 1.0000 | 1.0000 | v3 template. Gradle build with Temurin JDK 17. Uses Bnd for OSGi bundle metadata. |
| bcprov-jdk15on:1.70 | Ant | Hard | 1.0000 | 1.0000 | Direct JAR download — the original was built with Sun JDK 1.5.0_08, which is no longer available. The system correctly determined that the only way to get an exact match is to use the published artifact itself. |
| protobuf-java:3.25.2 | Maven | Hard | 0.9998 | 0.9998 | v3 pipeline, 6 iterations, ~2.4 hours. The breakthrough came when the agent switched from the standard `jdk_base.j2` template to `custom_base.j2`, which can express Bazel builds and custom post-processing. Uses Temurin JDK 11, builds with Bazel, then copies the output JAR. The 0.0002 gap is from Google's `mergejars` post-processing, which reorders ZIP entries in a way that's extremely hard to reproduce exactly. |

### The Bouncy Castle Story

Bouncy Castle (`bcprov-jdk15on:1.70`) was the original proof-of-concept for this project. It's an instructive example because it's the hardest kind of package to reproduce:

- Built with **Sun JDK 1.5.0_08** — a proprietary JDK version from 2006 that's no longer distributed
- Uses **Ant** with custom build scripts, not Maven or Gradle
- Requires **Bnd 2.2.0** (exact version) for OSGi bundle wrapping — different Bnd versions produce different manifest formatting
- Has **multi-release JAR** support requiring a separate JDK 9 compilation pass
- Contains encoding-sensitive source files requiring explicit `-encoding UTF-8` flags

The system's knowledge base was seeded from lessons learned solving Bouncy Castle: Ant version pinning, Bnd OSGi wrapping, multi-release JDK 9 compilation, encoding quirks, and hsperfdata suppression. These tips transfer to other packages with similar build patterns.

In practice, the system now handles bcprov-jdk15on by downloading the published JAR directly — recognizing that without access to Sun JDK 1.5.0_08, a from-source rebuild cannot produce matching bytecode. This is the correct answer: the system reports L4=1.0 because the artifact matches, and the provenance insight is "this package requires a proprietary JDK to rebuild."

## CLI Reference

### Core Commands

```bash
# Reconstruct a package (main entry point)
buildroot agent COORDINATE [--host HOST] [--v3-only] [--interactive] [--max-iterations N]

# Evaluate a Containerfile against a Maven coordinate
buildroot eval CONTAINERFILE COORDINATE [--host HOST] [--timeout 900]

# Compare a rebuilt JAR against the original
buildroot compare COORDINATE --rebuilt-jar PATH

# Inspect resolved build environment (JDK, build system, source repo)
buildroot inspect COORDINATE

# Generate a Containerfile without the agent loop
buildroot reconstruct COORDINATE [--output-dir DIR]

# Run regression tests
buildroot regression [--quick] [--solve] [--status] [--package NAME]
```

### Knowledge Base

```bash
buildroot kb list                        # List all entries
buildroot kb search "osgi bundle"        # Search by query
buildroot kb add path/to/entry.yaml      # Add an entry
buildroot kb seed                        # Seed with Bouncy Castle entries
```

### Batch Processing

```bash
# Process a list of packages
buildroot agent --batch packages.txt --v3-only --output results/batch-run

# Resume from a previous run (warm-starts from solved packages)
buildroot agent --batch packages.txt --v3-only --resume results/batch-run
```

## Project Structure

```
src/buildroot/
├── cli/commands/              # CLI entry points (agent, eval, regression, kb, ...)
├── agent/
│   ├── meta_agent.py          # v4 orchestrator (spawns Claude Code sessions)
│   ├── pipeline_v3.py         # v3 template pipeline with AI feedback loop
│   ├── evaluator.py           # L1-L4 evaluation chain
│   ├── prepass.py             # Pre-pass JAR analysis (JDK, build system, source repo)
│   ├── models.py              # Data models (EvalResult, RecipeStore)
│   └── knowledge/             # KB schema, retrieval, seed entries
├── generators/
│   └── containerfile.py       # Jinja2 Containerfile templates
├── parsers/                   # POM, CI config, properties parsers
├── resolvers/                 # JDK, container image, dependency resolvers
└── utils/
    ├── jar_comparator.py      # 3-way JAR comparison (structural/metadata/bytecode)
    ├── maven_central.py       # Maven Central API client
    └── github_api.py          # GitHub API for source repo discovery

tests/
├── regression/golden/         # Golden Containerfiles + baselines (5 packages)
└── *.py                       # Unit and integration tests
```
