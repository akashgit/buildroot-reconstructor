# Factory Configuration
<!-- This file configures the Remote Factory for your project. -->
<!-- The factory reads this during Init mode and generates .factory/config.json from it. -->
<!-- Fill in each section below. -->

## Goal
<!-- A single sentence describing what this project should achieve. -->

Reconstruct build environments (buildroots) for Maven Central artifacts as Containerfiles, working from the package's pom.xml and CI workflows — consumer-side build provenance reconstruction for supply chain security.

## Scope

### Modifiable
<!-- Files and directories the factory is allowed to create or edit. -->
<!-- One path per line. Glob patterns are supported. -->

- src/**/*.py
- src/**/*.j2
- src/**/*.md
- src/**/.gitkeep
- tests/**/*.py
- results/**
- factory.md

### Read-only
<!-- Files the factory may read but must never modify. -->

- README.md
- pyproject.toml
- eval/score.py

## Guards
<!-- Rules the factory must never violate. Checked before every commit. -->

- Do not delete or overwrite existing tests
- Do not modify files outside the declared scope
- Do not introduce secrets or credentials into the repository
- Do not modify eval/score.py or .factory/ directory

## Eval

### Command
<!-- The shell command the factory runs to score a change. -->
<!-- It must output JSON to stdout matching the EvalResult format. -->

```bash
python eval/score.py
```

### Threshold
<!-- Minimum composite score (0.0-1.0) required to keep a change. -->

0.55

## Target Branch
<!-- Branch that experiment PRs target. Default: main -->
<!-- Set to a different branch (e.g. factory/dev) to stage factory changes before merging to main -->

main

## Smoke Test
<!-- Optional shell command that must pass before any change is kept. -->
<!-- If configured, this runs as part of `factory precheck` — failure = mandatory revert. -->
<!-- Use for e2e verification: hit an endpoint, run a CLI command, check a process starts. -->

```bash
python -m buildroot reconstruct org.apache.commons:commons-lang3:3.14.0 --output-dir /tmp/buildroot-smoke-test --skip-deps
```

## Constraints
<!-- Soft rules that guide behavior but don't block commits. -->

- Prefer small, incremental changes over large rewrites
- Each change should be accompanied by at least one test
- Follow the existing code style and conventions
- Use Podman (not Docker) for container operations

## L4' Approximate Scoring

When the reference JAR is unavailable on Maven Central (returns 404), the evaluation pipeline automatically falls back to approximate L4 scoring (L4'). This is invoked transparently — no user flag is needed.

### How it works

The evaluator checks Maven Central for the reference JAR. If the download fails (404), it computes an approximate L4 score from 4 signals:

| Signal | Weight | What it checks |
|--------|--------|----------------|
| Unit test pass | 0.30 | Project's test suite passes inside the container (binary) |
| Bytecode version | 0.15 | Built .class files target the expected JDK version |
| API surface match | 0.15 | Jaccard similarity of public/protected method signatures |
| Structural match | 0.10 | Jaccard similarity between JAR .class files and source .java files |
| Manifest sanity | 0.10 | MANIFEST.MF exists, pom.properties has correct groupId/artifactId |
| Dependency graph | 0.10 | Package dependency overlap between JAR and source imports |
| Resource completeness | 0.10 | Fraction of expected resources present in JAR |

On the full L4 comparison path (96% of builds), the L4 score is composed as:
- 70% JAR equivalence (bytecode + metadata + structural comparison against reference JAR)
- 30% unit test pass (binary: 1.0 if all tests pass, 0.0 if any fail)

When no test sources exist in the project, unit tests are excluded and JAR comparison gets 100%.

Signals that cannot be computed (e.g., no tests exist, shaded JAR detected) return None and their weight is redistributed to the remaining signals.

### How to tell which scoring path was used

Check `l4_signal_source` in the eval output:
- `'full_comparison'` — normal L4: bytecode comparison against reference JAR from Maven Central
- `'fallback_signals'` — L4' approximate: multi-signal proxy score (no reference JAR available)

### CLI usage

The `buildroot eval` command reports both paths transparently:

```
buildroot eval <containerfile> <coordinate> --jdk-version 21
```

Output includes `fallback_signals` dict when L4' is active.

### Default base images

Generated Containerfiles use `registry.access.redhat.com/ubi9/openjdk-{version}` by default (no Docker Hub authentication or rate limiting required). This supports large-scale batch runs (20k+ artifacts) without hitting pull rate limits.

