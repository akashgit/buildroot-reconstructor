---
tags:
  - factory
  - source
  - buildroot-reconstructor
source: factory-archivist
date: 2026-06-07
---

# macOS Installation Prerequisites

## Finding

Install order matters on macOS. Maven requires a JDK installed first — it will fail otherwise.

## Install Order

1. Python: `brew install python@3.11` (may need PATH update to `/opt/homebrew/opt/python@3.11/libexec/bin`)
2. JDK: `brew install --cask temurin@21` — cask method preferred (auto-configures `JAVA_HOME` and symlinks)
3. Maven: `brew install maven` — does NOT auto-pull a JDK
4. Podman: `brew install podman && podman machine init && podman machine start`

## Key Notes

- **JDK cask vs formula**: `brew install --cask temurin@21` preferred over `brew install openjdk@21` because cask handles JAVA_HOME and symlinks automatically
- **Podman machine**: Downloads ~1GB VM on first `podman machine init`. Machine must be running before any `podman build`/`podman run`
- **Apple Silicon**: All tools have native ARM builds, no Rosetta needed
- **Alternative**: `brew install --cask podman-desktop` includes engine + GUI

## README Template

```
Prerequisites: Python 3.11+, JDK 17+, Maven 3.8+, Podman (or Docker)
Quick setup (macOS): brew install python@3.11 && brew install --cask temurin@21 && brew install maven && brew install podman && podman machine init && podman machine start
```

## Relevance

Builder must install these in Phase 1 (per CEO verdict — not deferred). The Podman machine init time (~1GB download) should be accounted for in build phase planning.
