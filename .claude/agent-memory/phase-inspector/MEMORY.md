# Memory Index

- [Spec doc conflicts](project-spec-doc-conflicts.md) — TDD_PLAN / TRD / DATA_DESIGN / REQUIREMENTS contradict each other in four known spots; cross-check all four.
- [Phase audit baseline](project-phase1-audit-baseline.md) — five audit techniques that each caught a real defect: clean-room gate re-run, coverage-data check, locating the Red commit, env-var isolation probe.
- [config.py vs config/ collision](project-config-name-collision.md) — safe today, but a `config/__init__.py` would silently break all settings imports; also breaks `--cov=config`.
- [Weakened-test pattern](project-weakened-test-pattern.md) — spec-mandated tests get rewritten/deleted to pass instead of escalating; diff pytest-cache nodeids to catch it.
- [except-tuple gap](project-except-tuple-gap.md) — doc-copied `except (A, B)` tuples miss TypeError/ValueError/ValidationError; run a hostile-input probe matrix.
- [Mock client network gate](project-mock-client-network-gate.md) — T-4.4 gate needs live credentials, so the FR-104 fallback can't pass its own gate; demo-day risk.
- [Windows atomic-write trap](project-windows-atomic-write-trap.md) — tempfile+os.replace crashes on Windows when the dst is open; the token-cache fix inverts its own failure mode.
- [Server-controlled sleep values](project-server-controlled-sleep.md) — raw rate-limit headers go straight to time.sleep with no clamp; fixed in throttle.py, regressed in toss_client.py.
- [Open items carried over](project-open-items-carried-over.md) — state.md's 열린 항목 list predicts the next phase's bugs; the code gets moved verbatim and the bug ships.
- [Token single validity (위험1)](project-token-single-validity.md) — 401 refresh discards the new token and re-reads a cache whose writes may silently fail → 3 issuances per request.
