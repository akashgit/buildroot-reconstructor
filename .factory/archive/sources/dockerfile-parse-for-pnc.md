---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - pnc
  - tooling
source: factory-archivist
date: 2026-06-12
---

# dockerfile-parse for PNC Containerfile Extraction

## Library Selection
Two Python libraries exist for Containerfile/Dockerfile parsing:

| Library | Approach | Modify? | Dependencies |
|---------|----------|---------|-------------|
| **`dockerfile-parse`** | Pure Python | Yes (read/write) | None extra |
| `dockerfile` | Go wrapper | No (read-only) | Requires Go compiler |

**Decision**: Use `dockerfile-parse` — already in `pyproject.toml` as a project dependency. No new dependency required.

## Key APIs for PNC Extraction
```python
from dockerfile_parse import DockerfileParser
dfp = DockerfileParser(path='/path/to/Containerfile')
dfp.baseimage    # FROM base image string
dfp.envs         # dict of all ENV variables (e.g., {'MAVEN_VERSION': '3.3.9'})
dfp.structure    # list of instruction dicts with 'instruction' and 'value' keys
```

## Parsing Strategy for 2-Layer PNC Images
1. Parse tool-layer Containerfile → extract `FROM` (base image), `ENV MAVEN_VERSION`, Gradle download URLs
2. Derive base-layer directory from `FROM` image name (strip tag + registry prefix)
3. Parse base-layer Containerfile → extract RHEL base, JDK RPM version, `JAVA_HOME`
4. Combine into `PNCGroundTruth` dataclass

## Handles Correctly
- Multi-line RUN instructions
- Comments and escape characters
- Works identically for Containerfiles (same syntax as Dockerfiles)

## Sources
- [dockerfile-parse on PyPI](https://pypi.org/project/dockerfile-parse/)
- [dockerfile-parse on GitHub](https://github.com/containerbuildsystem/dockerfile-parse)
