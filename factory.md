# Factory Configuration

## Goal

Remediate CVE NV-001052 (CWE-400: Uncontrolled Resource Consumption) in `com.liferay:org.springframework.orm:5.3.33.LIFERAY-PATCHED-1`.

## Scope

- Containerfile-based build pipeline for patching Spring ORM JAR
- CVE remediation artifacts (research, fix plan, archive)
- Evaluation scripts for automated quality assessment

## Guards

- Do not modify files outside the declared scope
- Do not delete or overwrite existing tests
- Do not introduce secrets or credentials
- Do not lower the eval threshold
- Do not skip the eval step
- Do not merge PRs — leave open for human review
- Patches must preserve all non-vulnerable Liferay modifications (LPD-15177 logger field change)
- The fix must align with upstream Spring Framework 5.3.33 behavior — no novel logic

## Eval

- **eval_command**: `python eval/score.py`
- **eval_threshold**: 0.7
