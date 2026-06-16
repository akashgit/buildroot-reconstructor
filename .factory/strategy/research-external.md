# External Research: Node-Scoped Pipeline Agents (Issue #24)

## Context

Issue #24 proposes adding Claude Code reviewer agents at every step of the deterministic pipeline in `orchestrator.py`. The current pipeline has 13 sequential steps (POM fetch → parse → parent chain → merge → property resolution → repo discovery → CI parsing → JDK resolution → container image resolution → dependency tree → git tag → Maven wrapper → Containerfile generation). Each step currently runs deterministic Python code. The proposal is to attach an LLM-powered reviewer/improver agent at each node to catch errors, fill gaps, and improve accuracy.

This research covers: multi-agent pipeline architecture patterns, Claude Code subprocess scoping, Docker Hub tag verification API, git tag discovery patterns, Maven POM edge cases, and container base image tag naming conventions.

---

## 1. Multi-Agent Pipeline Architecture Patterns

### Sequential Pipeline with Per-Step Reviewers

The strongest emerging pattern for this type of system is the **assembly-line with quality gates**:

1. Deterministic step produces output
2. A scoped reviewer agent validates/improves that output against defined criteria
3. If approved → passes to next step; if improved → replaces output and proceeds

**Key principles from research:**

- **Separate implement and review agents.** The code that produced the output should never review its own work. Collapsing these into one step caused immediate quality drops in production multi-agent systems. ([Stephanie Jarmak, Medium](https://medium.com/@steph.jarmak/i-used-two-multi-agent-pipelines-for-everything-i-built-this-week-heres-what-happened-cf68d1b53a62))

- **Strict scoping per agent.** Each agent needs: an objective, an output format, guidance on tools/sources to use, and clear task boundaries. Without this, agents duplicate work or leave gaps. ([Anthropic Engineering Blog](https://www.anthropic.com/engineering/multi-agent-research-system))

- **Filesystem-based handoffs.** Rather than passing everything through conversation context, agents write outputs to files and pass lightweight references. This avoids information loss and reduces token overhead. ([Anthropic Engineering Blog](https://www.anthropic.com/engineering/multi-agent-research-system))

- **3-7 agents per pipeline.** Beyond 7, coordination overhead outweighs benefits. For larger pipelines, use hierarchical structures. ([DEV Community Guide](https://dev.to/eira-wexford/how-to-build-multi-agent-systems-complete-2026-guide-1io6))

- **End-state evaluation over process checking.** Judge whether the output is correct, not whether the agent followed prescribed steps. Agents legitimately find alternative paths. ([Anthropic Engineering Blog](https://www.anthropic.com/engineering/multi-agent-research-system))

### Recommended Architecture for This Project

Given the 13-step pipeline, NOT every step needs a reviewer agent. Group steps by error-prone-ness and impact:

| Priority | Pipeline Steps | Reviewer Agent | Rationale |
|----------|---------------|----------------|-----------|
| **High** | POM parsing + parent chain + merge (steps 2-4) | `pom-reviewer` | Property inheritance, relocation, BOM imports are major error sources |
| **High** | JDK resolution (step 8) | `jdk-reviewer` | Conflict resolution between 12+ signal sources; tag verification needed |
| **High** | Container image resolution (step 9) | `image-reviewer` | Tag existence verification against Docker Hub API |
| **High** | Git tag discovery (step 11) | `tag-reviewer` | Verify tag exists via `git ls-remote` |
| **Medium** | Build command enrichment (step 13b) | `build-cmd-reviewer` | Plugin flag detection has edge cases |
| **Low** | POM fetch, CI discovery, dep tree, wrapper detect | None (deterministic) | These are API calls with clear pass/fail |

This keeps the reviewer count at 4-5 (well within the 3-7 guideline) while covering the error-prone nodes.

---

## 2. Claude Code Subprocess Scoping for Node Agents

### Existing Pattern (from research-external.md — prior research)

The project already has `spawn_claude_agent()` in `claude_runner.py` using the `claude --bare -p` pattern with `--append-system-prompt-file`. This same pattern applies to node-scoped agents.

### Node Agent Configuration

Each node reviewer should be configured as a lightweight, fast subprocess:

```python
spawn_claude_agent(
    task="Review this POM merge result for property resolution errors...",
    system_prompt=NODE_SPECIFIC_PROMPT,
    model="claude-sonnet-4-6",       # Sonnet for speed/cost on review tasks
    max_turns=5,                      # Reviewers need few turns
    max_budget_usd=0.50,              # Cheap per node
    timeout=120,                      # 2 min max
)
```

**Key differences from existing builder agents:**

| Aspect | Builder Agent | Node Reviewer Agent |
|--------|--------------|-------------------|
| Model | opus-4-6 | sonnet-4-6 (cheaper, fast enough for review) |
| Max turns | 30 | 5-10 |
| Budget | $5.00 | $0.25-0.50 |
| Timeout | 600s | 60-120s |
| Output | Full Containerfile | Structured validation JSON or corrected data |
| Tools | Read, Edit, Bash, WebSearch | Read, Bash, WebSearch (no Edit — reviewers don't modify files) |

### System Prompt Structure for Node Agents

Each node agent needs a scoped system prompt containing:

1. **Role**: "You are a {step-name} reviewer for the buildroot reconstruction pipeline"
2. **Input schema**: The specific dataclass fields this step produces (e.g., `PomData` fields for pom-reviewer)
3. **Validation criteria**: What constitutes correct output for this step
4. **Tools available**: Which external checks the agent can perform (e.g., `git ls-remote`, Docker Hub API)
5. **Output format**: Structured JSON with `{valid: bool, corrections: [...], confidence: float}`

### Structured Output Schema for Node Reviewers

```json
{
  "type": "object",
  "properties": {
    "valid": {"type": "boolean"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "corrections": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "field": {"type": "string"},
          "original_value": {"type": "string"},
          "corrected_value": {"type": "string"},
          "reason": {"type": "string"}
        }
      }
    },
    "warnings": {"type": "array", "items": {"type": "string"}}
  },
  "required": ["valid", "confidence", "corrections", "warnings"]
}
```

Use `--json-schema` with this to get validated structured output from each reviewer.

---

## 3. Docker Hub Registry API for Tag Verification

### Primary Endpoint: OCI Distribution Spec HEAD Request

The fastest way to verify a container image tag exists is a HEAD request to the manifests endpoint:

```
HEAD /v2/<name>/manifests/<reference>
```

- **200 OK** → tag exists; response includes `Docker-Content-Digest` and `Content-Length`
- **404 Not Found** → tag does not exist
- **401 Unauthorized** → need to authenticate first

### Docker Hub Authentication Flow

Docker Hub requires token-based auth for registry API calls:

```bash
# Step 1: Get bearer token
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/eclipse-temurin:pull" | jq -r .token)

# Step 2: HEAD request to check tag
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
  "https://registry-1.docker.io/v2/library/eclipse-temurin/manifests/21-jdk-jammy")
```

### Python Implementation

```python
import requests

def verify_docker_tag(image: str, tag: str) -> bool:
    """Check if a Docker Hub image:tag exists via the registry v2 API."""
    # Split namespace/name
    if "/" not in image:
        namespace, name = "library", image
    else:
        namespace, name = image.split("/", 1)

    # Get auth token
    scope = f"repository:{namespace}/{name}:pull"
    token_resp = requests.get(
        "https://auth.docker.io/token",
        params={"service": "registry.docker.io", "scope": scope},
        timeout=10,
    )
    token = token_resp.json()["token"]

    # HEAD request to check manifest
    resp = requests.head(
        f"https://registry-1.docker.io/v2/{namespace}/{name}/manifests/{tag}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.docker.distribution.manifest.v2+json",
        },
        timeout=10,
    )
    return resp.status_code == 200
```

### Tag Listing Endpoint

To list all available tags (for fuzzy matching when exact tag doesn't exist):

```
GET /v2/<name>/tags/list
```

Returns: `{"name": "eclipse-temurin", "tags": ["8-jdk", "11-jdk", "17-jdk", "21-jdk", ...]}`

Paginated — follow `Link` headers for images with many tags.

### Rate Limits

- Anonymous: 100 pulls per 6 hours
- Authenticated: 200 pulls per 6 hours
- For the reviewer agent, cache token and reuse within a pipeline run

### Sources

- [Docker Registry API — Baeldung](https://www.baeldung.com/ops/docker-registry-api-list-images-tags)
- [OCI Distribution Spec](https://github.com/opencontainers/distribution-spec/blob/main/spec.md)
- [Docker Hub API Reference](https://docs.docker.com/reference/api/hub/latest/)
- [Docker v2 API Tags — Nick Janetakis](https://nickjanetakis.com/blog/using-dockers-v2-api-to-get-a-list-of-tags-with-the-help-of-jq)

---

## 4. Git Tag Discovery and Verification via `git ls-remote`

### Core Pattern

```bash
git ls-remote --tags --refs https://github.com/{owner}/{repo} 'v*'
```

- `--tags` filters to only tag refs
- `--refs` excludes peeled tag objects (the `^{}` lines for annotated tags)
- Pattern `'v*'` matches from the tail of the ref (e.g., matches `refs/tags/v1.0`)

### Version Tag Patterns Across Projects

Projects use inconsistent tag naming. The reviewer agent needs to try multiple patterns:

| Pattern | Example | Projects |
|---------|---------|----------|
| `v{version}` | `v3.14.0` | Most common (Spring, Apache Commons) |
| `{artifactId}-{version}` | `commons-lang3-3.14.0` | Apache multi-module projects |
| `rel/{artifactId}-{version}` | `rel/commons-lang3-3.14.0` | Some Apache projects |
| `{version}` | `3.14.0` | Some projects (no prefix) |
| `release-{version}` | `release-3.14.0` | Less common |

### Verification Strategy for `tag-reviewer` Agent

```bash
# Try exact match first
git ls-remote --tags --refs "$REPO_URL" "refs/tags/v$VERSION"

# If empty, try artifactId prefix
git ls-remote --tags --refs "$REPO_URL" "refs/tags/$ARTIFACT_ID-$VERSION"

# If still empty, list all tags matching version substring
git ls-remote --tags --refs "$REPO_URL" "*$VERSION*"
```

### Sorting by Version

```bash
git ls-remote --tags --refs --sort='version:refname' "$REPO_URL"
```

The `version:refname` sort treats tag names as version numbers, correctly ordering `v1.9` before `v1.10`.

### Key Edge Cases

1. **Annotated vs lightweight tags**: Without `--refs`, annotated tags show two lines (one for the tag object, one peeled `^{}`). Always use `--refs`.
2. **Tags on forks**: If repo URL points to a fork, tags may be from the parent repo or fork-specific.
3. **Release branches vs tags**: Some projects use `release/v1.0` branches instead of tags.
4. **Monorepo tags**: Projects like Spring Framework may have tags like `v5.3.18` for the entire repo, not per-module.

### Sources

- [Git ls-remote Documentation](https://git-scm.com/docs/git-ls-remote.html)
- [Getting Latest Tag on Git Repository](https://gist.github.com/rponte/fdc0724dd984088606b0)
- [How to List Git Tags — devconnected](https://devconnected.com/how-to-list-git-tags/)

---

## 5. Maven POM Resolution Edge Cases

### Property Inheritance

- Properties are inherited from parent POMs through the entire parent chain. A child POM inherits **all** properties from its parent unless explicitly overridden.
- Properties can reference other properties: `<my.version>${project.version}</my.version>` — these must be resolved recursively.
- **Unresolved placeholders**: If a property references `${some.prop}` and `some.prop` is never defined in the chain, Maven leaves the literal `${some.prop}` string. The current pipeline's `GapDetector._check_unresolved_properties()` catches this.
- **Profile-activated properties**: Properties defined inside `<profiles>` are only active when the profile is activated. These are currently NOT resolved by the pipeline (listed in backlog as "Profile-activated Maven property resolution").

### BOM Imports Edge Cases

- BOMs are imported via `<dependencyManagement>` with `<scope>import</scope>` and `<type>pom</type>`.
- **Order matters**: When multiple BOMs are imported, they are processed in declaration order. Later BOMs override earlier ones for the same `groupId:artifactId`.
- **Recursive imports**: If BOM X imports BOM Q, all of Q's managed dependencies appear as if defined in X.
- **Circular import prohibition**: A POM must never import a BOM that is also in its parent chain. Maven throws an exception.
- **Maven 4.0 BOM packaging**: New `<packaging>bom</packaging>` type introduced in Maven 4.0 — separate from `<packaging>pom</packaging>`. Backward-compatible with Maven 3.x consumers.

### Relocated Artifacts

- Relocation uses `<distributionManagement><relocation>` in a stub POM at the old coordinates.
- Maven automatically redirects resolution to new coordinates and issues a warning.
- **Edge case: immutable cached POMs.** Once Maven downloads a POM, it doesn't re-download it. If a relocation POM is published after a consumer already cached the old POM, they won't see the relocation until they fetch a new version.
- **Multi-version relocation**: Some projects (e.g., Apache POI) published relocation POMs for every new version at the old `groupId` across several releases.
- **Relocation can change groupId, artifactId, and/or version** — not just groupId.
- The `pom-reviewer` agent should check for `<relocation>` elements in any POM it parses and follow them.

### Dependency Mediation

- Maven uses "nearest definition" — the closest dependency to your project in the tree wins.
- `<dependencyManagement>` overrides mediation — it pins versions regardless of tree depth.
- **Hidden version pinning**: `dependency:tree` does NOT show where a resolved version comes from (parent POM, BOM import, or direct declaration). This makes debugging difficult.
- **Exclusion inheritance**: Maven traces exclusions up the tree; when exclusions differ between parent nodes, cached resolution results can't be reused.

### Sources

- [POM Reference — Apache Maven](https://maven.apache.org/pom.html)
- [Guide to Relocation — Apache Maven](https://maven.apache.org/guides/mini/guide-relocation.html)
- [Introduction to Dependency Mechanism — Apache Maven](https://maven.apache.org/guides/introduction/introduction-to-dependency-mechanism.html)
- [Maven Dependency Maze Survival Guide — Konvu](https://konvu.com/blog/maze-of-maven-dependencies)
- [eBay's Maven Dependency Resolution Algorithm](https://innovation.ebayinc.com/stories/open-source-contribution-new-maven-dependency-resolution-algorithm/)

---

## 6. Container Base Image Tag Naming Conventions

### Eclipse Temurin (Adoptium)

**Tag pattern**: `eclipse-temurin:<java-version>-<jdk|jre>[-<os-codename>]`

| Tag Example | Java | Type | OS |
|-------------|------|------|----|
| `eclipse-temurin:21-jdk` | 21 | JDK | Ubuntu (default, currently 26.04 Resolute) |
| `eclipse-temurin:21-jre` | 21 | JRE | Ubuntu (default) |
| `eclipse-temurin:21-jdk-noble` | 21 | JDK | Ubuntu 24.04 Noble |
| `eclipse-temurin:21-jdk-jammy` | 21 | JDK | Ubuntu 22.04 Jammy |
| `eclipse-temurin:21-jdk-alpine` | 21 | JDK | Alpine Linux (musl) |
| `eclipse-temurin:21-jdk-ubi9-minimal` | 21 | JDK | Red Hat UBI 9 |
| `eclipse-temurin:8-jdk` | 8 | JDK | Ubuntu (default) |

**Supported Java versions**: 8, 11, 17, 21, 25, 26

**Architecture**: Multi-arch manifests (amd64, arm64 auto-selected). No arch in tag.

**Key gotcha**: Default Ubuntu base changes over time. `eclipse-temurin:21-jdk` pointed to Ubuntu 24.04 Noble, now points to 26.04 Resolute. For reproducibility, always use the explicit OS codename suffix.

### BellSoft Liberica

**Tag pattern**: `bellsoft/liberica-openjdk-<os>:<java-version>[update[-build]][-arch]`

| Repository | OS |
|------------|-----|
| `bellsoft/liberica-openjdk-debian` | Debian |
| `bellsoft/liberica-openjdk-alpine` | Alpine |
| `bellsoft/liberica-openjdk-alpine-musl` | Alpine (musl) |
| `bellsoft/liberica-runtime-container` | Alpaquita Linux (BellSoft's own) |

**Key difference from Temurin**: OS variant is in the **repository name**, not the tag. Tags contain only version + optional arch: `21`, `21.0.3`, `21.0.3-10`, `21.0.3-10-aarch64`.

### Amazon Corretto

**Tag pattern**: `amazoncorretto:<java-version>[-<os>]`

| Tag Example | Notes |
|-------------|-------|
| `amazoncorretto:21` | Amazon Linux (default) |
| `amazoncorretto:21-alpine` | Alpine variant |

### Azul Zulu

**Tag pattern**: `azul/zulu-openjdk[-<os>]:<java-version>`

| Repository | OS |
|------------|-----|
| `azul/zulu-openjdk` | Ubuntu (default) |
| `azul/zulu-openjdk-alpine` | Alpine |
| `azul/zulu-openjdk-debian` | Debian |
| `azul/zulu-openjdk-centos` | CentOS |

Like Liberica, the OS variant is in the repository name.

### Current Project Gap: `_map_distribution_to_image()` in `jdk.py`

The current `DISTRIBUTION_IMAGE_MAP` produces tags like `eclipse-temurin:21` — missing the `-jdk` suffix. The correct tag is `eclipse-temurin:21-jdk`. This is a concrete bug the `jdk-reviewer` agent should catch.

```python
# Current (incorrect for Temurin):
DISTRIBUTION_IMAGE_MAP = {
    "temurin": "eclipse-temurin",      # produces eclipse-temurin:21
    ...
}

# The generated tag eclipse-temurin:21 does exist (alias for 21-jdk)
# BUT eclipse-temurin:21-jdk is the canonical form and more explicit
```

### Tag Verification Matrix for `image-reviewer` Agent

| Distribution | Registry | Auth Required | Verify Pattern |
|-------------|----------|---------------|----------------|
| Temurin | Docker Hub (`library/eclipse-temurin`) | Token | `HEAD /v2/library/eclipse-temurin/manifests/{ver}-jdk` |
| Corretto | Docker Hub (`library/amazoncorretto`) | Token | `HEAD /v2/library/amazoncorretto/manifests/{ver}` |
| Liberica | Docker Hub (`bellsoft/liberica-openjdk-debian`) | Token | `HEAD /v2/bellsoft/liberica-openjdk-debian/manifests/{ver}` |
| Zulu | Docker Hub (`azul/zulu-openjdk`) | Token | `HEAD /v2/azul/zulu-openjdk/manifests/{ver}` |
| Oracle | Oracle CR | Oracle auth | Different auth flow |
| GraalVM | GHCR | GitHub token | `HEAD /v2/graalvm/jdk/manifests/{ver}` |

### Sources

- [Eclipse Temurin Container Images — Adoptium](https://adoptium.net/installation/containers)
- [eclipse-temurin Tags — Docker Hub](https://hub.docker.com/_/eclipse-temurin/tags)
- [Liberica JDK Container Images — BellSoft](https://bell-sw.com/libericajdk-containers/)
- [Adoptium Containers GitHub](https://github.com/adoptium/containers)

---

## 7. Implementation Recommendations

### Phase 1: Add Tag Verification Functions (No LLM Required)

Before adding agent reviewers, add deterministic verification functions that the reviewers can call:

```python
# In resolvers/container_image.py
def verify_tag_exists(image: str, tag: str) -> bool:
    """HEAD request to Docker Hub registry v2 API."""

# In utils/github_api.py
def verify_git_tag(repo_url: str, tag: str) -> bool:
    """git ls-remote --tags --refs {repo_url} refs/tags/{tag}"""

# In parsers/pom.py
def check_relocation(pom_xml: str) -> dict | None:
    """Parse <distributionManagement><relocation> if present."""
```

### Phase 2: Add Reviewer Agents at High-Priority Nodes

Start with 4 reviewer agents (within the 3-7 guideline):

1. **`pom-reviewer`**: After steps 2-5 (POM parse + merge + property resolution)
   - Checks for unresolved `${...}` placeholders
   - Detects relocation elements
   - Validates parent chain completeness
   - Flags circular import risks

2. **`jdk-reviewer`**: After step 8 (JDK resolution)
   - Verifies resolved JDK version against JAR manifest
   - Validates base image tag exists via Docker Hub API
   - Checks for version conflicts between signals
   - Suggests `-jdk` suffix if missing from Temurin tags

3. **`tag-reviewer`**: After step 11 (git tag discovery)
   - Runs `git ls-remote --tags --refs` to verify tag exists
   - Tries alternative patterns if primary tag not found
   - Checks for monorepo vs per-module tagging

4. **`build-cmd-reviewer`**: After step 13b (build command enrichment)
   - Validates plugin flags are correct for the detected plugins
   - Checks wrapper usage consistency
   - Validates build command syntax

### Phase 3: Integrate into Pipeline

Add reviewer calls in `orchestrator.py` after each relevant step:

```python
# After step 8
jdk_spec = jdk_resolver.resolve(merged, ci_data, resolved_props, ...)
if self._use_reviewers:
    review = spawn_node_reviewer(
        "jdk-reviewer",
        input_data=jdk_spec_to_dict(jdk_spec),
        context={"pom_properties": resolved_props, "ci_data": ci_data_to_dict(ci_data)},
    )
    if review.corrections:
        jdk_spec = apply_corrections(jdk_spec, review.corrections)
```

### Cost Estimate

At Sonnet pricing ($3/MTok input, $15/MTok output) with ~2K tokens per reviewer call:
- 4 reviewers × ~$0.01 per call = ~$0.04 per package reconstruction
- For 31-package benchmark: ~$1.24 total
- Acceptable given the current $50/cycle budget

---

## References

- [How to Build Multi-Agent Systems: 2026 Guide — DEV Community](https://dev.to/eira-wexford/how-to-build-multi-agent-systems-complete-2026-guide-1io6)
- [Anthropic Multi-Agent Research System](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Multi-Agent Pipelines — Stephanie Jarmak](https://medium.com/@steph.jarmak/i-used-two-multi-agent-pipelines-for-everything-i-built-this-week-heres-what-happened-cf68d1b53a62)
- [Claude Code Sub-Agents — MindStudio](https://www.mindstudio.ai/blog/claude-code-sub-agents-explained)
- [Modifying System Prompts — Claude Code Docs](https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts)
- [Docker Registry API — Baeldung](https://www.baeldung.com/ops/docker-registry-api-list-images-tags)
- [OCI Distribution Specification](https://github.com/opencontainers/distribution-spec/blob/main/spec.md)
- [Docker Hub API Reference](https://docs.docker.com/reference/api/hub/latest/)
- [Git ls-remote Documentation](https://git-scm.com/docs/git-ls-remote.html)
- [POM Reference — Apache Maven](https://maven.apache.org/pom.html)
- [Guide to Relocation — Apache Maven](https://maven.apache.org/guides/mini/guide-relocation.html)
- [Introduction to Dependency Mechanism — Apache Maven](https://maven.apache.org/guides/introduction/introduction-to-dependency-mechanism.html)
- [Maven Dependency Maze Survival Guide — Konvu](https://konvu.com/blog/maze-of-maven-dependencies)
- [Eclipse Temurin Container Images — Adoptium](https://adoptium.net/installation/containers)
- [Liberica JDK Container Images — BellSoft](https://bell-sw.com/libericajdk-containers/)
- [Adoptium Containers — GitHub](https://github.com/adoptium/containers)
