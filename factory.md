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

## Research Target

- objective: Maximize solve rate of agentic Containerfile reconstruction across Maven packages
- metric: solve_rate
- target: 0.80
- run_command: python -m buildroot agent --batch results/packages_smoke.txt --host rh-h100-01 --output results/agent-smoke/ --max-iterations 15
- result_path: results/agent-smoke/summary.json
- result_parser: json
- timeout: 7200

## Mutable Surfaces

- src/buildroot/agent/builder.py
- src/buildroot/agent/analyzer.py
- src/buildroot/agent/loop.py
- src/buildroot/agent/observer.py
- src/buildroot/agent/outer_loop.py
- src/buildroot/agent/models.py
- src/buildroot/templates/*.j2

## Fixed Surfaces

- src/buildroot/agent/evaluator.py
- eval/score.py
- results/packages_smoke.txt
- src/buildroot/utils/jar_comparator.py
- src/buildroot/utils/maven_central.py

## Research Constraints

- Do not change the 4-level scoring formula (L1=0.05, L2=0.10, L3=0.35, L4=0.50)
- Do not modify the JAR comparison logic
- Do not hardcode package-specific fixes — changes must generalize across packages
- Do not change the evaluation host or SSH configuration
- Builder prompts must remain grounded in error classification, not memorized solutions

## Cost Budget

- max_per_cycle: 50.00
