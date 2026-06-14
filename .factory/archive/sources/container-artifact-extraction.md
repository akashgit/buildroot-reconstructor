---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - level4
source: factory-archivist
date: 2026-06-09
---

# Container Artifact Extraction for Level 4

After `podman build` completes, the rebuilt JAR must be extracted from the container image for comparison against the Maven Central original. Three approaches researched.

## Approach A: `podman create` + `podman cp` (RECOMMENDED)
```bash
CONTAINER=$(podman create <image>)
podman cp $CONTAINER:/workspace/target/{artifactId}-{version}.jar ./local/
podman rm $CONTAINER
```
- Works with stopped containers — no need to start
- Most portable and simplest
- Supports specific file paths

## Approach B: `podman mount` (Linux rootful only)
```bash
CONTAINER=$(podman create <image>)
MNT=$(podman mount $CONTAINER)
cp $MNT/path/to/artifact.jar ./local/
podman unmount $CONTAINER && podman rm $CONTAINER
```
- Full filesystem access, allows `find` to locate artifacts
- Requires root or `podman unshare`

## Approach C: Multi-stage build with `--output`
- Cleanest for CI, but requires Containerfile template changes

## JAR Location Convention
The JAR path inside the container follows Maven convention: `target/{artifactId}-{version}.jar` relative to the WORKDIR. If unknown, `podman run <image> find / -name "*.jar" -path "*/target/*"` discovers it. For multi-module builds, the artifact may be in a submodule's `target/` directory.

## Remote Execution on rh-h100 Nodes
Parallelization plan across 3 nodes (160 cores, 1.7TB RAM each):
- Node 01: commons-lang3, micrometer-core, thymeleaf-spring5
- Node 02: spring-data-jpa, spring-cloud-config-server, spring-boot-starter-web
- Node 03: spring-security-core, spring-core, spring-context, spring-boot

SSH + tmux pattern for persistent builds:
```bash
ssh lab@rh-h100-01 "tmux new-session -d -s build-{pkg} \
  'cd /tmp/buildroot && podman build -t {pkg}-rebuild -f Containerfile . 2>&1 | tee build.log'"
```

## References
- [Podman cp documentation](https://docs.podman.io/en/v5.2.2/markdown/podman-cp.1.html)
