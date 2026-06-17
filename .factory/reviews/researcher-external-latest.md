# Researcher Agent Output

- **timestamp:** 2026-06-16T02:03:44Z
- **exit_code:** 0

---

Research report written to `.factory/strategy/research-external.md`. It covers 7 sections:

1. **Multi-agent pipeline patterns** — recommends 4-5 reviewer agents at error-prone nodes (not all 13 steps), based on Anthropic's own multi-agent architecture and production pipeline patterns
2. **Claude Code subprocess scoping** — node reviewers should use Sonnet, 5-10 turns, $0.25-0.50 budget, structured JSON output via `--json-schema`
3. **Docker Hub tag verification** — HEAD request to `/v2/<name>/manifests/<tag>` with bearer token auth; includes Python implementation
4. **Git tag discovery** — `git ls-remote --tags --refs` patterns, covering the 5 common tag naming conventions across Maven projects
5. **Maven POM edge cases** — property inheritance chains, BOM import ordering, relocated artifacts, circular import prohibition
6. **Container image tag conventions** — Temurin (`{ver}-jdk[-os]`), Liberica (OS in repo name), Corretto, Zulu patterns + a concrete bug found in `_map_distribution_to_image()` (missing `-jdk` suffix for Temurin tags)
7. **Implementation roadmap** — phased approach: deterministic verification functions first, then 4 reviewer agents, then pipeline integration. Cost estimate: ~$0.04 per package, ~$1.24 for full benchmark.
---

> **⚠ CEO IDENTITY RE-ANCHOR (Sacred Rule 8)**
> You are the Factory CEO. You orchestrate, delegate, and decide. You do NOT implement.
> If you are about to write code, run tests, do research, or fix bugs — STOP and spawn the appropriate agent.
> Re-read your Permitted/Forbidden Actions lists in the Identity section above.
