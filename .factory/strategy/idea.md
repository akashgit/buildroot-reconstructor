# Buildroot Reconstructor

## Vision

Reconstruct the complete build environment (buildroot) for a Maven artifact as a Dockerfile, working only from the package's `pom.xml` and its CI workflow — enabling consumer-side build provenance reconstruction for supply chain security. No existing tool produces Dockerfiles from consumer-side inference; Macaron BuildGen outputs shell-oriented buildspecs, Reproducible Central uses hand-written specs, and OSS-Rebuild doesn't support Maven yet (Research §1.7).

## Core Features

- **POM Fetching and Parsing with Full Parent Resolution**
  - **What:** Given a Maven coordinate (groupId:artifactId:version), fetch the POM from Maven Central and resolve the complete parent inheritance chain — walking from child to parent to grandparent until reaching the super POM or a POM with no parent. The merged POM is the effective POM with all inherited properties, pluginManagement, and dependencyManagement available for downstream analysis. Users provide a Maven coordinate on the CLI; the tool prints the resolved parent chain and the merged property map.
  - **How:** Fetch POMs via direct HTTP to `repo1.maven.org/maven2/{groupPath}/{artifactId}/{version}/{artifactId}-{version}.pom` (more reliable than the search API per Research §2.4). Parse with `lxml` for XPath-based extraction and `defusedxml` for safe initial parsing of untrusted XML (Research §2.1). For relative-path parents, resolve within the cloned repo; for non-relative parents, fetch from Maven Central. Cache fetched POMs in memory to avoid redundant downloads across the chain. Multi-level inheritance is common in Spring — e.g., `spring-boot-starter-web` chains through 4 levels (Research §3.2).
  - **Why:** No comprehensive Python library exists for full Maven POM resolution (Research §2.1), so this must be built from scratch. The parent chain is prerequisite to property resolution — properties resolve after inheritance, and a child POM can override a parent's property, changing the behavior of parent-defined plugin configurations (Research §3.1). Without the full chain, JDK version and Maven plugin config are often invisible.

- **Maven Property Placeholder Resolution**
  - **What:** Resolve all `${...}` placeholders in the merged POM to their concrete values. This includes `${project.*}` references, POM-defined properties, and recursive property references (`${foo}` → `${bar}` → `actual-value`). Unresolvable properties (e.g., `${env.JAVA_HOME}`, CI-friendly versions like `${revision}`) are logged as gaps rather than causing failures. The resolved properties are used by all downstream extractors.
  - **How:** Build a `PropertyResolver` class that loads the merged property map from the inheritance chain, resolves `${project.*}` references to POM elements (groupId, version, artifactId), handles recursive resolution with cycle detection, and treats CI-friendly versions (`${revision}`, `${sha1}`, `${changelist}` introduced in Maven 3.5.0) as unresolvable-from-POM since they're set via `-D` flags in CI (Research §3.1). Resolution order follows Maven's precedence: system properties > project properties > POM-defined properties (Research §3.1).
  - **Why:** Property resolution is the linchpin of accurate POM interpretation. Without it, version strings, plugin configurations, and dependency coordinates remain as opaque `${...}` tokens. Research (§3.1) identifies that properties resolve after inheritance — meaning the resolver must operate on the merged POM, not individual POMs in the chain. Getting this wrong cascades into incorrect JDK inference, wrong dependency versions, and broken Dockerfiles.

- **CI Workflow Parsing (GitHub Actions + CircleCI)**
  - **What:** Given a GitHub repository URL, discover and parse CI workflow files to extract the build environment: runner/executor image, JDK version and distribution, Maven/Gradle version, system packages installed via `apt-get`/`yum`, environment variables, and the build command sequence. Supports both GitHub Actions YAML (`.github/workflows/*.yml`) and CircleCI config (`.circleci/config.yml`). For GitHub Actions, parse the `setup-java` action's `java-version` and `distribution` parameters. For CircleCI, extract Docker executor image tags and orb configurations.
  - **How:** Fetch workflow files via GitHub REST API (`/repos/{owner}/{repo}/contents/.github/workflows/`) using `PyGithub` or raw `requests` (Research §2.5). Parse YAML with `ruamel.yaml` which preserves structure (Research §2.2). For GitHub Actions: walk job definitions, find `uses: actions/setup-java@*` steps and extract `with.java-version` and `with.distribution`; scan `run:` steps for `apt-get install`, `mvn`, and `gradle` commands; extract matrix strategy entries. For CircleCI: extract `docker.image` from executor config, parse orb versions, and extract `run.command` from steps.
  - **Why:** The CI workflow is the primary source of truth for the actual build environment — the JDK used in CI takes priority over POM-declared compiler settings because `maven.compiler.source` specifies language level, not JDK version (Research §3.4). Research §3.4 establishes that a source level of 11 can compile on JDK 17, so POM properties alone are insufficient for buildroot reconstruction. The CI is where the real JDK selection happens.

- **JDK Version Inference with Priority Heuristic**
  - **What:** Determine the JDK version and distribution (vendor) used to build the artifact by checking 10+ possible source locations in a defined priority order, producing a single concrete JDK specification (e.g., "Temurin 17") with a confidence level and source citation. When multiple sources disagree, the tool reports the conflict and follows the priority order.
  - **How:** Implement a `JdkResolver` that checks sources in this order (derived from Research §3.4): (1) CI `setup-java` action's `java-version` + `distribution`, (2) CI `JAVA_HOME_*` env var references, (3) POM `<maven.compiler.release>`, (4) POM `<maven.compiler.source>/<target>`, (5) `maven-compiler-plugin` `<release>` config, (6) `maven-compiler-plugin` `<source>` config, (7) Spring Boot `<java.version>` property, (8) Maven Enforcer `requireJavaVersion`, (9) `.java-version` file, (10) `.sdkmanrc`, (11) `.tool-versions` (asdf), (12) default to JDK 17. Map the `distribution` field from `setup-java` to Docker image tags: Temurin → `eclipse-temurin`, Corretto → `amazoncorretto`, Zulu → `azul/zulu-openjdk` (Research §3.6).
  - **Why:** Research §3.4 documents that JDK version appears in many places with different semantics — language level vs. actual runtime. The priority heuristic ensures CI-observed behavior takes precedence over POM declarations, because the CI workflow reflects what actually ran, while the POM reflects what's minimally required. Without this heuristic, a project specifying `source=11` but building on JDK 17 would get the wrong base image.

- **Container Image Resolution**
  - **What:** When a CI workflow references a Docker container image (e.g., CircleCI's `docker: [{image: springcloud/pipeline-base}]`), locate the image's Dockerfile on GitHub or Docker Hub, parse it, and extract the environment layer: base image, installed JDKs, system packages, and pre-installed tools. This provides ground truth for the build environment when available, superseding inference from CI steps.
  - **How:** Extract image references from CI workflow parser output. For images hosted on GitHub (common for org-specific build images like `springcloud/pipeline-base`), search the org's repos for a Dockerfile matching the image name. For Docker Hub images, query the Docker Hub API for the image's source repo link. Parse discovered Dockerfiles with `dockerfile-parse` (Research §2.3) to extract `FROM`, `RUN apt-get install`, `ENV JAVA_HOME`, and `COPY` instructions. Fall back to Docker Hub image inspect API for layer metadata when no Dockerfile is found.
  - **Why:** Research §1.2 and the test set (spring-cloud-config-server uses `springcloud/pipeline-base`) show that some projects define their build environment as a container image rather than inline CI steps. When this exists, it's the highest-fidelity source of buildroot information — it's literally the environment specification. Ignoring it would mean inferring what's already explicitly stated.

- **Dockerfile Generation from Buildroot Specification**
  - **What:** Produce a complete, runnable Dockerfile that captures the reconstructed build environment. The Dockerfile starts from the appropriate JDK base image, installs the correct Maven version, adds any system packages found in CI, copies the source, and runs the build command. The output includes inline comments citing where each piece of information was inferred from, and a companion `buildroot.json` metadata file in a structured format compatible with Reproducible Central buildspecs (Research §1.2).
  - **How:** Use Jinja2 templates (Research §2.3 — recommended over `dockerfile-parse` for generation since we're producing, not modifying Dockerfiles). Maintain templates for common patterns: JDK-base-image-only, JDK-on-Ubuntu (when system packages are needed), and custom-base-image (when CI references a container). Map `ubuntu-latest` to a concrete version using a lookup table maintained per GitHub's runner image migration schedule — currently `ubuntu:24.04` post-January 2025 (Research §3.3). The `buildroot.json` sidecar captures the same fields as a Reproducible Central buildspec (source repo, git tag, JDK version, build command, expected artifacts) for interoperability.
  - **Why:** Dockerfile output is the key differentiator — no existing tool produces this (Research §1.7). Buildspecs and SLSA attestations are metadata; a Dockerfile is an executable environment specification that can actually be used to perform a rebuild. Jinja2 templates are cleaner than programmatic Dockerfile construction because the output is inherently text with conditional blocks, not a data structure. The `buildroot.json` sidecar enables integration with the Reproducible Central ecosystem.

- **Gap Detection and Confidence Reporting**
  - **What:** For every piece of information in the generated buildroot, report whether it was directly observed (high confidence), inferred via heuristic (medium confidence), or defaulted (low confidence). Produce a structured gap report listing what's missing or uncertain: unresolved properties, `ubuntu-latest` used instead of a pinned version, no Maven wrapper found, JDK version inferred from compiler settings rather than CI, missing system package detection. The gap report is both human-readable (printed to stderr) and machine-readable (included in `buildroot.json`).
  - **How:** Each extractor (POM parser, CI parser, JDK resolver) attaches a `Source` annotation to every extracted value — an enum of `OBSERVED` (directly found in CI/Dockerfile), `INFERRED` (derived via heuristic), or `DEFAULTED` (used a fallback). The gap reporter aggregates these annotations and flags anything below `OBSERVED`. For `ubuntu-latest`, flag that the concrete version mapping may be stale (Research §3.3). For CI-friendly Maven versions (`${revision}`), flag that the version is set at build time and may not match the POM.
  - **Why:** Consumer-side reconstruction is inherently probabilistic — unlike producer-side attestations where the builder knows exactly what ran, we're reconstructing from indirect evidence. Research §3.1, §3.3, and §3.4 all identify cases where information is ambiguous or missing. Without explicit confidence reporting, a consumer of the buildroot has no way to judge its reliability. This is what separates a useful security tool from a guessing machine.

- **Test Harness and Verification Suite**
  - **What:** A test suite covering the 10 Spring ecosystem packages in the test set, with three verification strategies: (1) structured diff against known container Dockerfiles where available (spring-cloud-config-server), (2) cross-reference against GitHub runner image specs and JAR manifest `Build-Jdk-Spec`, (3) end-to-end rebuild comparison (optional, gated behind a flag due to time cost). Each test case is a fixture containing the expected buildroot fields for a specific package version.
  - **How:** Use `pytest` with fixtures for each test package. For strategy (1), parse the known Dockerfile and compare base image, JDK version, system packages against the generated Dockerfile. For strategy (2), fetch the published JAR from Maven Central, read `META-INF/MANIFEST.MF` for `Build-Jdk-Spec`, and compare against the tool's JDK inference. For strategy (3), run `docker build` on the generated Dockerfile and `docker run` the build command, then compare output JAR checksums. Include integration tests that exercise the full pipeline (coordinate → Dockerfile) and unit tests for property resolution, JDK inference, and CI parsing.
  - **Why:** The test set was chosen to cover varying build complexity: multi-module monorepos (spring-framework), explicit container images (spring-cloud-config), no CI at all (thymeleaf-spring5), and matrix builds (spring-boot). Research §1.2 shows Reproducible Central validates with actual rebuilds, but this is expensive; the tiered verification strategy lets fast checks run in CI while rebuilds run on demand.

## Architecture

- **Language/Runtime**: Python 3.11+ — the research stack is entirely Python (lxml, ruamel.yaml, jinja2, PyGithub), and this is a CLI tool with no performance-critical paths; XML parsing and HTTP fetching dominate runtime.
- **Framework**: `click` for CLI — mature, well-documented, supports subcommands and option groups. Preferred over typer for its explicit decorator style which suits a tool with multiple distinct commands.
- **Data Storage**: Filesystem only — no database. Fetched POMs cached in `~/.cache/buildroot/poms/`, generated Dockerfiles written to the working directory. Cache keyed by `groupId:artifactId:version` for deduplication.
- **Key Libraries**:
  - `lxml` — XPath-based POM element extraction (Research §2.1)
  - `defusedxml` — safe XML parsing for untrusted POM input (Research §2.1)
  - `ruamel.yaml` — CI workflow YAML parsing with structure preservation (Research §2.2)
  - `jinja2` — Dockerfile template rendering (Research §2.3)
  - `dockerfile-parse` — parsing discovered container Dockerfiles for environment extraction (Research §2.3)
  - `requests` — Maven Central HTTP access, direct POM fetching (Research §2.4)
  - `PyGithub` — GitHub API for workflow file discovery and repo search (Research §2.5)
  - `pytest` — test framework for the verification suite

## User Interface

CLI tool invoked as `buildroot` with two primary commands:

**`buildroot reconstruct <groupId>:<artifactId>:<version>`**
- Fetches POM, discovers CI workflow, runs the full inference pipeline
- Outputs `Dockerfile` and `buildroot.json` to the current directory (or `--output-dir`)
- Prints gap report to stderr
- Flags: `--repo-url` (override source repo URL), `--ci-type github|circleci` (hint CI type), `--no-cache` (skip POM cache)

**`buildroot verify <groupId>:<artifactId>:<version>`**
- Runs verification checks against a previously generated buildroot
- Checks: JAR manifest `Build-Jdk-Spec` match, runner image spec cross-reference
- Flag: `--rebuild` (attempt actual Docker build and artifact comparison — slow)

**`buildroot inspect <groupId>:<artifactId>:<version>`**
- Diagnostic mode: prints the resolved parent chain, merged properties, inferred JDK, detected CI config
- Useful for debugging inference without generating a Dockerfile

Primary user flow: `buildroot reconstruct org.springframework.boot:spring-boot:2.7.18` → generates `Dockerfile`, `buildroot.json`, prints gap report → user reviews and optionally runs `buildroot verify` to check against published artifact metadata.

## Non-Goals (v1)

- **Gradle support** — Gradle builds use a fundamentally different model (Groovy/Kotlin DSL, wrapper-based versioning, custom tasks). Maven-only for v1.
- **npm/pip/Cargo support** — each ecosystem has its own manifest and CI patterns. Maven is the focus.
- **Transitive dependency resolution** — the Dockerfile includes Maven which resolves transitive deps at build time. We extract direct deps from the POM for the buildroot spec but don't attempt a full dependency tree resolution.
- **Producer-side integration** — this is a consumer-side tool. It doesn't generate SLSA attestations or sign anything.
- **Automated CI pipeline for continuous monitoring** — v1 is a batch CLI tool, not a service.
- **Private Maven repository support** — v1 assumes Maven Central. Private repos (Artifactory, Nexus) require auth configuration.
- **GitLab CI / Jenkins / Travis CI** — v1 supports GitHub Actions and CircleCI only, covering the Spring ecosystem test set.

## Open Questions

- **GitHub API token**: Required for workflow file access and to avoid rate limiting. Should be provided via `GITHUB_TOKEN` env var or `--token` flag. Users need a personal access token with `repo` (or `public_repo`) scope.
- **Docker Hub rate limits**: Container image resolution may hit Docker Hub's anonymous pull rate limit (100 pulls/6hr). Should we require a Docker Hub token, or cache aggressively?
- **Multi-module buildroot granularity**: For monorepo projects like spring-framework (30+ modules, one CI), should the tool generate one Dockerfile for the whole reactor or per-module? Recommendation: one Dockerfile for the reactor root (since that's how CI builds it), with the build command targeting the specific module (`mvn -pl spring-core -am`).
