# Researcher Agent Output

- **timestamp:** 2026-06-17T02:03:17Z
- **exit_code:** 0

---

Research complete. Written to `.factory/strategy/research-external.md` with findings across all 5 research areas:

1. **ACE playbooks** — Issue #27's AnalyzeAgent maps 1:1 to the ACE Generator-Reflector-Curator architecture (Zhang et al., 2025). Append-only rules with helpful/harmful counters are the validated pattern. AgentDebug shows 26% improvement from targeted corrective feedback.

2. **Top-K parallel builds** — CORAL demonstrates 3-10x gains from parallel exploration without coordination. K=3 is conservative and sufficient for our single-dimension fitness (L1-L4). Wall-clock cost is ~1x (parallel `podman build`), not Kx.

3. **L3→L4 reproducibility** — The Chains-Rebuild paper (FSE 2026) is definitive: all 6 L3 failures show bytecode_match=True, meaning divergence is only in metadata/timestamps. Canonicalizing MANIFEST.MF + removing pom.properties + setting `outputTimestamp` should convert most to L4. Chains-Rebuild achieves 26.89% success on 12K artifacts.

4. **Podman short-names** — Enforcing mode (default) fails without TTY, which is our exact environment. Always fully-qualifying with `docker.io/library/` is the only reliable fix and is Red Hat security-recommended.

5. **Feedback loops** — Build-bench validates three-input prompts (logs + state + history). The dual-loop architecture (within-task overrides + cross-task playbooks) is identified by recent research as the key differentiator for continual learning.
---

> **⚠ CEO IDENTITY RE-ANCHOR (Sacred Rule 8)**
> You are the Factory CEO. You orchestrate, delegate, and decide. You do NOT implement.
> If you are about to write code, run tests, do research, or fix bugs — STOP and spawn the appropriate agent.
> Re-read your Permitted/Forbidden Actions lists in the Identity section above.
