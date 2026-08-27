---
name: project-phase1-audit-baseline
description: Phase 1 (models/) audit outcome and the reusable audit techniques that surfaced real defects — pytest pythonpath gate failure, coverage-of-guard-branches-only, uncommitted Red step
metadata:
  type: project
---

Phase 1 (`models/`) audited 2026-08-27. Result: CONDITIONAL PASS. The three techniques below each found a defect that reading the code alone did not, so reuse them every phase.

1. **Run the gate command *literally as written*, not via `python -m pytest`.** `pytest.ini` has no `pythonpath` and there is no root `conftest.py`, so `pytest tests/test_models.py` fails with `ModuleNotFoundError: No module named 'models'`; only `python -m pytest` (which injects cwd) passes. Every phase gate in TDD_PLAN is written in the bare form, so this will keep producing false "gate passed" claims until fixed.

2. **Always run `--cov=<pkg> --cov-report=term-missing`, not just the pass count.** Phase 1's 12/12 green hid that every uncovered line was the *success* branch (FX conversion, non-zero P&L, valid square matrix). The required-test table in TDD_PLAN §5 only enumerates guard/None cases, so a spec-complete test suite can still leave the happy path unverified.

3. **Check whether the phase's Red step exists in git at all.** Phase 1's `tests/` and `models/` were entirely untracked at audit time, while commit `5d3d846 "phase_1_over"` contained only Phase 0 scaffolding — so Red→Green was unverifiable from history and had to be inferred from file mtimes and `.pytest_cache/v/cache/nodeids`.

**Why:** the project mandates 엄격 TDD for `models/` and `analytics/`, and gates are defined as "명령을 실행해서 참/거짓이 나와야 한다" — a gate that only passes under a non-canonical invocation defeats that definition.

**How to apply:** open every audit with (a) the literal gate command, (b) a coverage run, (c) `git log`/`git status` to locate the Red commit. Related doc-level traps in [[project-spec-doc-conflicts]].
