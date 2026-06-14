# Distiller Agent Output

- **timestamp:** 2026-06-08T01:13:49Z
- **exit_code:** 0

---

Writing the refined spec with four changes: Podman-first/Containerfile naming, transitive deps promoted to core feature, rate limit concerns removed, and GitHub token made optional.

# Buildroot Reconstructor

## Vision

Reconstruct the complete build environment (buildroot) for a Maven artifact as a Containerfile, working only from the package's `pom.xml` and its CI workflow — enabling consumer-side build provenance reconstruction for supply chain security. No existing tool produces Containerfiles from consumer-side inference; Macaron BuildGen outputs shell-oriented buildspecs, Reproducible Central uses hand-written specs, and OSS-Rebuild doesn't support Maven yet (Research §1.7).

## Core Features

- **POM Fetching and Parsing with Full Parent Resolution**
  - **What:** Given a Maven coordinate (groupId:artifactId:version), fetch the POM from Maven Central and resolve the complete parent inheritance chain — walking from child to parent to grandparent until reaching the super POM or a POM with no parent. The merged POM is the effective POM with all inherited properties, pluginManagement, and dependencyManagement available for downstream analysis. Users provide a Maven coordinate on the CLI; the tool prints the resolved parent chain and the merged property map.
  - **How:** Fetch POMs via direct HTTP to `repo1.maven.org/maven2/{groupPath}/{artifactId}/{version}/{artifactId}-{version}.pom` (more reliable than the search API per Research §2.4). Parse with `lxml` for XPath-based extraction and `defusedxml` for safe initial parsing of untrusted XML (Research §2.1). For relative-path parents, resolve within the cloned repo; for non-relative parents, fetch from Maven Central. Cache fetched POMs in memory to avoid redundant downloads across the chain. Multi-level inheritance is common in Spring — e.g., `spring-boot-starter-web` chains through 4 levels (Research §3.2).
  - **Why:** No comprehensive Python library exists for full Maven POM resolution (Research §2.1), so this must be built from scratch. The parent chain is prerequisite to property resolution — properties resolve after inheritance, and a child POM can override a parent's property, changing the behavior of parent-defined plugin configurations (Research §3.1). Without the full chain, JDK version and Maven plugin config are often invisible.

- **Maven Property Placeholder Resolution**
  - **What:** Resolve all `${...}` placeholders in the merged POM to their concrete values. This includes `${project.*}` references, POM-defined properties, and recursive property references (`${foo}` → `${bar}` → `actual-value`). Unresolvable properties (e.g., `${env.JAVA_HOME}`, CI-friendly versions like `${revision}`) are logged as gaps rather than causing failures. The resolved properties are used by all downstream extractors.
  - **How:** Build a `PropertyResolver` class that loads the merged property map from the inheritance chain, resolves `${project.*}` references to POM elements (groupId, version, artifactId), handles recursive resolution with cycle detection, and treats CI-friendly versions (`${revision}`, `${sha1}`, `${changelist}` introduced in Maven 3.5.0) as unresolvable-from-POM since they're set via `-D` flags in CI (Research §3.1). Resolution order follows Maven's precedence: system properties > project properties > POM-defined properties (Research §3.1).
  - **Why:** Property resolution is the linchpin of accurate POM interpretation. Without it, version strings, plugin configurations, and dependency coordinates remain as opaque `${...}` tokens. Research (§3.1) identifies that properties resolve after inheritance — meaning the resolver must operate on the merged POM, not individual POMs in the chain. Getting this wrong cascades into incorrect JDK inference, wrong dependency versions, and broken Containerfiles.

- **CI Workflow Parsing (GitHub Actions + CircleCI)**
  - **What:** Given a GitHub repository URL, discover and parse CI workflow files to extract the build environment: runner/executor image, JDK version and distribution, Maven/Gradle version, system packages installed via `apt-get`/`yum`, environment variables, and the build command sequence. Supports both GitHub Actions YAML (`.github/workflows/*.yml`) and CircleCI config (`.circleci/config.yml`). For GitHub Actions, parse the `setup-java` action's `java-version` and `distribution` parameters. For CircleCI, extract Docker executor image tags and orb configurations.
  - **How:** Fetch workflow files via GitHub REST API (`/repos/{owner}/{repo}/contents/.github/workflows/`) using `requests` with optional `GITHUB_TOKEN` for authentication (Research §2.5). Parse YAML with `ruamel.yaml` which preserves structure (Research §2.2). For GitHub Actions: walk job definitions, find `uses: actions/setup-java@*` steps and extract `with.java-version` and `with.distribution`; scan `run:` steps for `apt-get install`, `mvn`, and `gradle` commands; extract matrix strategy entries. For CircleCI: extract `docker.image` from executor config, parse orb versions, and extract `run.command` from steps.
  - **Why:** The CI workflow is the primary source of truth for the actual build environment — the JDK used in CI takes priority over POM-declared compiler settings because `maven.compiler.source` specifies language level, not JDK version (Research §3.4). Research §3.4 establishes that a source level of 11 can compile on JDK 17, so POM properties alone are insufficient for buildroot reconstruction. The CI is where the real JDK selection happens.

- **JDK Version Inference with Priority Heuristic**
  - **What:** Determine the JDK version and distribution (vendor) used to build the artifact by checking 10+ possible source locations in a defined priority order, producing a single concrete JDK specification (e.g., "Temurin 17") with a confidence level and source citation. When multiple sources disagree, the tool reports the conflict and follows the priority order.
  - **How:** Implement a `JdkResolver` that checks sources in this order (derived from Research §3.4): (1) CI `setup-java` action's `java-version` + `distribution`, (2) CI `JAVA_HOME_*` env var references, (3) POM `<maven.compiler.release>`, (4) POM `<maven.compiler.source>/<target>`, (5) `maven-compiler-plugin` `<release>` config, (6) `maven-compiler-plugin` `<source>` config, (7) Spring Boot `<java.version>` property, (8) Maven Enforcer `requireJavaVersion`, (9) `.java-version` file, (10) `.sdkmanrc`, (11) `.tool-versions` (asdf), (12) default to JDK 17. Map the `distribution` field from `setup-java` to container image tags: Temurin → `eclipse-temurin`, Corretto → `amazoncorretto`, Zulu → `azul/zulu-openjdk` (Research §3.6).
  - **Why:** Research §3.4 documents that JDK version appears in many places with different semantics — language level vs. actual runtime. The priority heuristic ensures CI-observed behavior takes precedence over POM declarations, because the CI workflow reflects what actually ran, while the POM reflects what's minimally required. Without this heuristic, a project specifying `source=11` but building on JDK 17 would get the wrong base image.

- **Container Image Resolution**
  - **What:** When a CI workflow references a container image (e.g., CircleCI's `docker: [{image: springcloud/pipeline-base}]`), locate the image's Dockerfile/Containerfile on GitHub or a container registry, parse it, and extract the environment layer: base image, installed JDKs, system packages, and pre-installed tools. This provides ground truth for the build environment when available, superseding inference from CI steps.
  - **How:** Extract image references from CI workflow parser output. For images hosted on GitHub (common for org-specific build images like `springcloud/pipeline-base`), search the org's repos for a Dockerfile or Containerfile matching the image name. For registry-hosted images, query the registry API for the image's source repo link. Parse discovered Containerfiles with `dockerfile-parse` (Research §2.3) to extract `FROM`, `RUN apt-get install`, `ENV JAVA_HOME`, and `COPY` instructions. Fall back to registry image inspect API for layer metadata when no Containerfile is found.
  - **Why:** Research §1.2 and the test set (spring-cloud-config-server uses `springcloud/pipeline-base`) show that some projects define their build environment as a container image rather than inline CI steps. When this exists, it's the highest-fidelity source of buildroot information — it's literally the environment specification. Ignoring it would mean inferring what's already explicitly stated.

- **Transitive Dependency Tree Resolution**
  - **What:** Produce the full transitive dependency tree for the Maven artifact, capturing every direct and transitive dependency with its resolved version, scope, and origin (which POM pulled it in). The tree is emitted as a structured `dependency-tree.json` sidecar alongside the Containerfile, and optionally embedded as a build step in the generated Containerfile itself. This is critical for supply chain auditing — knowing only direct dependencies leaves the vast majority of the dependency surface invisible.
  - **How:** Do not reimplement Maven's dependency mediation in Python — it is a complex algorithm (nearest-definition-wins, scope narrowing, exclusions, optional deps, BOMs via `<dependencyManagement>` import scope) and reimplementing it would be a source of bugs. Instead, use Maven itself via two strategies: (1) **Local Maven available**: shell out to `mvn dependency:tree -DoutputType=text -DoutputFile=deps.txt` against the cloned source repo, parse the output into a structured tree. Detect Maven availability via `shutil.which('mvn')` or presence of `./mvnw`. (2) **Inside the generated Containerfile**: add a `RUN mvn dependency:tree -DoutputType=text -DoutputFile=/buildroot/dependency-tree.txt` step after the source copy, so the dependency tree is captured as part of the build environment reconstruction. The `dependency-tree.json` output uses a nested format: each node has `groupId`, `artifactId`, `version`, `scope`, and `children[]`.
  - **Why:** Java's transitive dependency graph is deep — a typical Spring Boot starter pulls 50-100 transitive dependencies. For supply chain security, the entire graph matters: a compromised transitive dependency is just as dangerous as a compromised direct one (cf. Log4Shell, which was a transitive dep for most affected projects). Delegating to Maven itself avoids the impossible task of correctly reimplementing dependency mediation, version conflict resolution, and scope narrowing in Python — Maven has 20 years of edge-case handling that we should not attempt to replicate.

- **Containerfile Generation from Buildroot Specification**
  - **What:** Produce a complete, runnable Containerfile that captures the reconstructed build environment. The Containerfile starts from the appropriate JDK base image, installs the correct Maven version, adds any system packages found in CI, copies the source, and runs the build command. The output includes inline comments citing where each piece of information was inferred from, and a companion `buildroot.json` metadata file in a structured format compatible with Reproducible Central buildspecs (Research §1.2). The file is named `Containerfile` (Podman's native name, also read by Docker and Buildah).
  - **How:** Use Jinja2 templates (Research §2.3 — recommended over `dockerfile-parse` for generation since we're producing, not modifying Containerfiles). Maintain templates for common patterns: JDK-base-image-only, JDK-on-Ubuntu (when system packages are needed), and custom-base-image (when CI references a container). Map `ubuntu-latest` to a concrete version using a lookup table maintained per GitHub's runner image migration schedule — currently `ubuntu:24.04` post-January 2025 (Research §3.3). The `buildroot.json` sidecar captures the same fields as a Reproducible Central buildspec (source repo, git tag, JDK version, build command, expected artifacts) for interoperability. Build commands in the Containerfile use `mvn` (not wrapper-specific `./mvnw`) since the Containerfile installs a known Maven version.
  - **Why:** Containerfile output is the key differentiator — no existing tool produces this (Research §1.7). Buildspecs and SLSA attestations are metadata; a Containerfile is an executable environment specification that can actually be used to perform a rebuild. Jinja2 templates are cleaner than programmatic construction because the output is inherently text with conditional blocks, not a data structure. The `buildroot.json` sidecar enables integration with the Reproducible Central ecosystem. Using the name `Containerfile` is the OCI-standard convention and works with Podman, Docker, and Buildah — there is no loss of compatibility.

- **Gap Detection and Confidence Reporting**
  - **What:** For every piece of information in the generated buildroot, report whether it was directly observed (high confidence), inferred via heuristic (medium confidence), or defaulted (low confidence). Produce a structured gap report listing what's missing or uncertain: unresolved properties, `ubuntu-latest` used instead of a pinned version, no Maven wrapper found, JDK version inferred from compiler settings rather than CI, missing system package detection. The gap report is both human-readable (printed to stderr) and machine-readable (included in `buildroot.json`).
  - **How:** Each extractor (POM parser, CI parser, JDK resolver) attaches a `Source` annotation to every extracted value — an enum of `OBSERVED` (directly found in CI/Containerfile), `INFERRED` (derived via heuristic), or `DEFAULTED` (used a fallback). The gap reporter aggregates these annotations and flags anything below `OBSERVED`. For `ubuntu-latest`, flag that the concrete version mapping may be stale (Research §3.3). For CI-friendly Maven versions (`${revision}`), flag that the version is set at build time and may not match the POM.
  - **Why:** Consumer-side reconstruction is inherently probabilistic — unlike producer-side attestations where the builder knows exactly what ran, we're reconstructing from indirect evidence. Research §3.1, §3.3, and §3.4 all identify cases where information is ambiguous or missing. Without explicit confidence reporting, a consumer of the buildroot has no way to judge its reliability. This is what separates a useful security tool from a guessing machine.

- **Test Harness and Verification Suite**
  - **What:** A test suite covering the 10 Spring ecosystem packages in the test set, with three verification strategies: (1) structured diff against known container images where available (spring-cloud-config-server), (2) cross-reference against GitHub runner image specs and JAR manifest `Build-Jdk-Spec`, (3) end-to-end rebuild comparison (optional, gated behind a flag due to time cost). Each test case is a fixture containing the expected buildroot fields for a specific package version.
  - **How:** Use `pytest` with fixtures for each test package. For strategy (1), parse the known Containerfile and compare base image, JDK version, system packages against the generated Containerfile. For strategy (2), fetch the published JAR from Maven Central, read `META-INF/MANIFEST.MF` for `Build-Jdk-Spec`, and compare against the tool's JDK inference. For strategy (3), run `podman build` on the generated Containerfile and `podman run` the build command, then compare output JAR checksums. Include integration tests that exercise the full pipeline (coordinate → Containerfile) and unit tests for property resolution, JDK inference, and CI parsing.
  - **Why:** The test set was chosen to cover varying build complexity: multi-module monorepos (spring-framework), explicit container images (spring-cloud-config), no CI at all (thymeleaf-spring5), and matrix builds (spring-boot). Research §1.2 shows Reproducible Central validates with actual rebuilds, but this is expensive; the tiered verification strategy lets fast checks run in CI while rebuilds run on demand.

## Architecture

- **Language/Runtime**: Python 3.11+ — the research stack is entirely Python (lxml, ruamel.yaml, jinja2), and this is a CLI tool with no performance-critical paths; XML parsing and HTTP fetching dominate runtime.
- **Framework**: `click` for CLI — mature, well-documented, supports subcommands and option groups. Preferred over typer for its explicit decorator style which suits a tool with multiple distinct commands.
- **Data Storage**: Filesystem only — no database. Fetched POMs cached in `~/.cache/buildroot/poms/`, generated Containerfiles written to the working directory. Cache keyed by `groupId:artifactId:version` for deduplication.
- **Container Runtime**: Podman (default). The tool uses `podman build` and `podman run` for rebuild verification. Docker and Buildah are also supported — any OCI-compliant runtime that reads `Containerfile` works. On macOS, Colima is a supported backend for running Podman or Docker. The `--runtime` flag overrides the default (e.g., `--runtime docker`).
- **Key Libraries**:
  - `lxml` — XPath-based POM element extraction (Research §2.1)
  - `defusedxml` — safe XML parsing for untrusted POM input (Research §2.1)
  - `ruamel.yaml` — CI workflow YAML parsing with structure preservation (Research §2.2)
  - `jinja2` — Containerfile template rendering (Research §2.3)
  - `dockerfile-parse` — parsing discovered container Dockerfiles/Containerfiles for environment extraction (Research §2.3)
  - `requests` — Maven Central HTTP access, direct POM fetching, GitHub API (Research §2.4)
  - `pytest` — test framework for the verification suite

## User Interface

CLI tool invoked as `buildroot` with three primary commands:

**`buildroot reconstruct <groupId>:<artifactId>:<version>`**
- Fetches POM, discovers CI workflow, runs the full inference pipeline
- Outputs `Containerfile`, `buildroot.json`, and `dependency-tree.json` to the current directory (or `--output-dir`)
- Prints gap report to stderr
- Flags: `--repo-url` (override source repo URL), `--ci-type github|circleci` (hint CI type), `--no-cache` (skip POM cache), `--skip-deps` (skip transitive dependency resolution), `--runtime podman|docker` (container runtime for any build steps, default: podman)

**`buildroot verify <groupId>:<artifactId>:<version>`**
- Runs verification checks against a previously generated buildroot
- Checks: JAR manifest `Build-Jdk-Spec` match, runner image spec cross-reference
- Flag: `--rebuild` (attempt actual `podman build` and artifact comparison — slow), `--runtime podman|docker`

**`buildroot inspect <groupId>:<artifactId>:<version>`**
- Diagnostic mode: prints the resolved parent chain, merged properties, inferred JDK, detected CI config, dependency tree summary
- Useful for debugging inference without generating a Containerfile

Primary user flow: `buildroot reconstruct org.springframework.boot:spring-boot:2.7.18` → generates `Containerfile`, `buildroot.json`, `dependency-tree.json`, prints gap report → user reviews and optionally runs `buildroot verify` to check against published artifact metadata.

## Non-Goals (v1)

- **Gradle support** — Gradle builds use a fundamentally different model (Groovy/Kotlin DSL, wrapper-based versioning, custom tasks). Maven-only for v1.
- **npm/pip/Cargo support** — each ecosystem has its own manifest and CI patterns. Maven is the focus.
- **Producer-side integration** — this is a consumer-side tool. It doesn't generate SLSA attestations or sign anything.
- **Automated CI pipeline for continuous monitoring** — v1 is a batch CLI tool, not a service.
- **Private Maven repository support** — v1 assumes Maven Central. Private repos (Artifactory, Nexus) require auth configuration.
- **GitLab CI / Jenkins / Travis CI** — v1 supports GitHub Actions and CircleCI only, covering the Spring ecosystem test set.

## Open Questions

- **Multi-module buildroot granularity**: For monorepo projects like spring-framework (30+ modules, one CI), the tool generates one Containerfile for the whole reactor (since that's how CI builds it), with the build command targeting the specific module (`mvn -pl spring-core -am`). If users need per-module Containerfiles, this can be revisited in v2.

## Changes from Prior Draft

- **Containerfile instead of Dockerfile**: All output files, templates, CLI flags, and documentation now use `Containerfile` (OCI-standard name). Podman is the default container runtime for rebuild verification; Docker and Buildah are supported alternatives via `--runtime`. Colima noted as a supported macOS backend. This is a surface-level rename with no architectural impact — `Containerfile` and `Dockerfile` are identical in syntax, and all major runtimes read both.
- **Transitive dependency resolution promoted to core feature**: Moved from Non-Goals to a full Core Feature. Uses Maven itself (`mvn dependency:tree`) rather than reimplementing dependency mediation in Python. Two strategies: shell out to local Maven when available, or embed the resolution as a step in the generated Containerfile. Produces `dependency-tree.json` sidecar for supply chain auditing.
- **GitHub token made optional**: Removed from Open Questions. `GITHUB_TOKEN` env var is used when set; unauthenticated access (60 req/hr) is the default and sufficient for the 10-package test set. 403 responses trigger exponential backoff with a user-friendly message suggesting token setup for heavier use.
- **Docker Hub rate limit concern removed**: Removed from Open Questions. Volume is low (~50 API calls for the full test set), aggressive caching is sufficient, and no token is required upfront.
- **PyGithub removed from dependencies**: Replaced with direct `requests` calls to the GitHub REST API. PyGithub is heavyweight for what we need (fetching a few files from known paths). `requests` is already a dependency for Maven Central access, so this removes an unnecessary dep.
---

> **⚠ CEO IDENTITY RE-ANCHOR (Sacred Rule 8)**
> You are the Factory CEO. You orchestrate, delegate, and decide. You do NOT implement.
> If you are about to write code, run tests, do research, or fix bugs — STOP and spawn the appropriate agent.
> Re-read your Permitted/Forbidden Actions lists in the Identity section above.
