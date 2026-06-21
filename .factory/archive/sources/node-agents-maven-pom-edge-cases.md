---
tags:
  - factory
  - source
  - buildroot-reconstructor
  - issue-24
  - maven
source: factory-archivist
date: 2026-06-15
research-type: external
---

# Maven POM Resolution Edge Cases for Node Agents

## Finding

Maven POM resolution has several edge cases that the POM Agent (Node 1) and Parent Chain Agent (Node 2) must handle. These are currently unhandled by the deterministic pipeline and contribute to build failures.

## Property Inheritance Edge Cases

1. **Recursive property references**: `<my.version>${project.version}</my.version>` — must resolve recursively
2. **Unresolved placeholders**: If `${some.prop}` is never defined in the chain, Maven leaves the literal string. Current `GapDetector._check_unresolved_properties()` catches this.
3. **Profile-activated properties**: Properties inside `<profiles>` only active when profile is activated. Currently NOT resolved by the pipeline (listed in backlog).

## BOM Import Edge Cases

1. **Order matters**: Multiple BOMs processed in declaration order; later overrides earlier for same `groupId:artifactId`
2. **Recursive imports**: BOM X importing BOM Q → Q's managed dependencies appear in X
3. **Circular import prohibition**: POM must never import a BOM in its parent chain (Maven throws)
4. **Maven 4.0 BOM packaging**: New `<packaging>bom</packaging>` type — separate from `<packaging>pom</packaging>`

## Relocated Artifacts

- `<distributionManagement><relocation>` in stub POM at old coordinates
- Maven auto-redirects resolution to new coordinates
- **Can change groupId, artifactId, AND/OR version** — not just groupId
- **Immutable cached POMs**: Once downloaded, Maven doesn't re-download. Relocation published after caching won't be seen.
- POM Agent should check for `<relocation>` elements and follow them

## Dependency Mediation

- "Nearest definition" wins in tree
- `<dependencyManagement>` overrides mediation — pins versions regardless of depth
- **Hidden version pinning**: `dependency:tree` doesn't show where resolved version comes from
- **Exclusion inheritance**: Traced up tree; differing exclusions prevent cache reuse

## Impact on Node Agents

- **Node 1 (POM Agent)**: Check for relocation elements, validate POM completeness
- **Node 2 (Parent Chain Agent)**: Handle recursive properties, BOM imports, circular import detection
- **Node 3 (Property Agent)**: Resolve profile-activated properties, recursive references

## Sources
- [POM Reference — Apache Maven](https://maven.apache.org/pom.html)
- [Guide to Relocation — Apache Maven](https://maven.apache.org/guides/mini/guide-relocation.html)
- [Introduction to Dependency Mechanism — Apache Maven](https://maven.apache.org/guides/introduction/introduction-to-dependency-mechanism.html)
- [Maven Dependency Maze Survival Guide — Konvu](https://konvu.com/blog/maze-of-maven-dependencies)
- [eBay's Maven Dependency Resolution Algorithm](https://innovation.ebayinc.com/stories/open-source-contribution-new-maven-dependency-resolution-algorithm/)
