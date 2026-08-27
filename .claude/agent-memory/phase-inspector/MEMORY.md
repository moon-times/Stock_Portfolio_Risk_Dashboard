# Memory Index

- [Spec doc conflicts](project-spec-doc-conflicts.md) — TDD_PLAN / TRD / DATA_DESIGN / REQUIREMENTS contradict each other in four known spots; cross-check all four.
- [Phase audit baseline](project-phase1-audit-baseline.md) — five audit techniques that each caught a real defect: clean-room gate re-run, coverage-data check, locating the Red commit, env-var isolation probe.
- [config.py vs config/ collision](project-config-name-collision.md) — safe today, but a `config/__init__.py` would silently break all settings imports; also breaks `--cov=config`.
- [Weakened-test pattern](project-weakened-test-pattern.md) — spec-mandated tests get rewritten/deleted to pass instead of escalating; diff pytest-cache nodeids to catch it.
- [except-tuple gap](project-except-tuple-gap.md) — doc-copied `except (A, B)` tuples miss TypeError/ValueError/ValidationError; run a hostile-input probe matrix.
- [Mock client network gate](project-mock-client-network-gate.md) — T-4.4 gate needs live credentials, so the FR-104 fallback can't pass its own gate; demo-day risk.
