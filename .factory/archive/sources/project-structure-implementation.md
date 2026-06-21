---
tags:
  - factory
  - source
  - buildroot-reconstructor
source: factory-archivist
date: 2026-06-07
---

# Project Structure — src Layout with Click Multi-Command CLI

## Finding

Recommended project structure: `src/` layout with `pyproject.toml` (no `setup.py`). Package name `buildroot` under `src/buildroot/`.

## Key Architecture

- **CLI layer**: Click multi-command group in `cli/main.py` with subcommands (`reconstruct`, `verify`, `inspect`) registered via `cli.add_command()`
- **Pipeline layer**: `pipeline/orchestrator.py` orchestrating fetch → parse → resolve → generate
- **Parsers**: Separate modules for POM XML (`parsers/pom.py`), property resolution (`parsers/properties.py`), and CI workflows (`parsers/ci.py`)
- **Resolvers**: JDK version inference heuristic in `resolvers/jdk.py`
- **Generators**: Jinja2 template rendering in `generators/containerfile.py` with `.j2` templates
- **Utils**: Maven Central HTTP client and GitHub API helpers

## Pipeline Data Flow

Three dataclasses flow through the pipeline:
1. `PomData` — parsed POM with parent chain, properties, GAV coordinates
2. `CIData` — extracted CI config (java version, distribution, build commands, system packages)
3. `BuildrootSpec` — final resolved spec with confidence annotations per field (`OBSERVED` / `INFERRED` / `DEFAULTED`)

## Entry Point

```toml
[project.scripts]
buildroot = "buildroot.cli.main:cli"
```

Templates included via `[tool.setuptools.package-data]`.

## Relevance

Defines the full skeleton the Builder must scaffold in Phase 1. The confidence annotation pattern (`OBSERVED`/`INFERRED`/`DEFAULTED`) is a key differentiator for user trust.
