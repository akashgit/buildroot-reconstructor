---
tags:
  - factory
  - source
source: factory-archivist
date: 2026-06-07
---

# Python Library Stack for Buildroot Reconstructor

## Recommended Stack (from research)

| Need | Library | Rationale |
|------|---------|-----------|
| XML parsing | `lxml` + `defusedxml` | XPath for property extraction; defusedxml for safety on untrusted POM input |
| YAML parsing | `ruamel.yaml` | Preserves structure for CI workflow analysis (preferred over PyYAML) |
| Containerfile output | `jinja2` (templates) | Generating, not parsing — templates cleaner than programmatic construction |
| Containerfile parsing | `dockerfile-parse` | For validation/testing of generated files; maintenance inactive but functional |
| HTTP | `requests` | Maven Central API, parent POM fetching, GitHub REST API |
| CLI | `click` | Explicit decorator style, supports subcommands and option groups |
| Testing | `pytest` | Standard |

## Key Finding

No comprehensive Python library exists for full Maven POM resolution (property interpolation, parent inheritance, profile activation). Must be built from scratch — this is the largest custom component.

## Dropped

- **PyGithub**: Removed in spec refinement. Heavyweight for fetching a few files from known paths. `requests` + GitHub REST API is sufficient and already a dependency.
