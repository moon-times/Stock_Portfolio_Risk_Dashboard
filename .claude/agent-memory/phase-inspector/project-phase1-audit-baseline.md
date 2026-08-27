---
name: project-phase1-audit-baseline
description: Reusable phase-audit techniques for this repo (gate command, coverage, Red-commit location, env-var isolation, name-collision probe) and which past defects each one caught
metadata:
  type: project
---

Audit techniques that have each caught a real defect in this repo. Run all of them every phase. Last revised after the Phase 2 (`config.py`) audit, 2026-08-27.

1. **Run the gate command *literally as written*, and also re-run it in a clean scratch dir.** Gates in TDD_PLAN assume a pristine environment that no longer exists locally. Phase 2's gate assumes no `.env`, but a real `.env` from Phase S sits in the repo root, so the literal command prints `True` instead of `False`; copying `config.py` to an empty scratch dir and re-running printed `False` and proved the implementation correct. Always separate "gate text is stale" from "implementation is wrong".
   - *Resolved*: the Phase 1 finding that bare `pytest tests/...` failed with `ModuleNotFoundError` is **fixed** — `pytest.ini` now has `pythonpath = .`. Bare `pytest` works. Do not re-report it.

2. **Always run `--cov=<target> --cov-report=term-missing`, and verify coverage actually collected data.** Phase 1: 12/12 green hid that only guard branches were covered. Phase 2: `--cov=config` silently reported "No data was collected" rather than failing. A "no data" warning is not a failure — treat it as an audit finding, not noise.

3. **Check whether the phase's Red step exists in git at all.** Both Phase 1 and Phase 2 shipped with the test + implementation entirely untracked, so Red→Green was unverifiable from history and had to be inferred from file mtimes (test file mtime earlier than impl file mtime) and `.pytest_cache/v/cache/nodeids`. This is a recurring pattern, not a one-off.
   - Caution: `.pytest_cache/v/cache/lastfailed` is overwritten by *your own* audit runs. Read it before running anything, or you will misattribute your own failure to the developer's Red step.

4. **Probe env-var isolation on any test that asserts a "nothing configured" default.** `Settings(_env_file=None)` disables the dotenv file but *not* OS environment variables. Re-running the suite with the relevant vars exported (`TOSS_CLIENT_ID=... pytest`) flipped a passing test to failing, which is how the plaintext-secret-in-assertion-repr issue was found. See [[project-config-name-collision]] and [[project-spec-doc-conflicts]].

**Why:** the project mandates 엄격 TDD for `models/` and `analytics/`, and gates are defined as "명령을 실행해서 참/거짓이 나와야 한다" — a gate that only passes under a non-canonical invocation, or in one particular developer's working directory, defeats that definition.

**How to apply:** open every audit with (a) the literal gate command plus a clean-room re-run, (b) a coverage run whose data collection you confirm, (c) `git log`/`git status` to locate the Red commit, (d) hostile-environment re-runs of default-value tests.
