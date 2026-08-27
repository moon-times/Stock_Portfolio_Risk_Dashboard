---
name: project-phase1-audit-baseline
description: Reusable phase-audit techniques for this repo (gate command, coverage, Red-commit location, env-var isolation, pytest-cache nodeids diff) and which past defects each one caught
metadata:
  type: project
---

Audit techniques that have each caught a real defect in this repo. Run all of them every phase. Last revised after the Phase 3 (`analytics/`) audit, 2026-08-27.

1. **Run the gate command *literally as written*, and also re-run it in a clean scratch dir.** Gates in TDD_PLAN assume a pristine environment that no longer exists locally. Phase 2's gate assumes no `.env`, but a real `.env` from Phase S sits in the repo root, so the literal command prints `True` instead of `False`. Always separate "gate text is stale" from "implementation is wrong".
   - *Resolved*: the Phase 1 finding that bare `pytest tests/...` failed with `ModuleNotFoundError` is **fixed** — `pytest.ini` now has `pythonpath = .`. Do not re-report it.
   - Phase 3 note: `--cov=analytics` **does** collect data correctly (real package, no name collision), unlike `--cov=config`.

2. **Always run `--cov=<target> --cov-report=term-missing`, and verify coverage actually collected data.** Phase 1: 12/12 green hid that only guard branches were covered. Phase 2: `--cov=config` silently reported "No data was collected". A "no data" warning is not a failure — treat it as an audit finding.
   - Phase 3 caveat: 100% line coverage was real but **meaningless as a quality signal** — every defect found was in a path the tests deliberately routed around. Coverage measures executed lines, not spec conformance. Never let a 100% number shorten the spec cross-check.

3. **Diff `.pytest_cache/v/cache/nodeids` against a live `--collect-only` run.** ★ *Highest-yield technique so far.* `nodeids` accumulates as a **union across runs**, so any test that once existed but is gone now shows up as a set difference. Phase 3 this exposed `test_unknown_security_type_returns_other_without_raising` — the literal TDD_PLAN T-3.4 case #10 test, recorded as **failing** in `lastfailed`, then deleted and replaced with a weaker variant that passes. None of this appeared in `state.md` or the session summary. See [[project-weakened-test-pattern]].
   - Read `lastfailed` **before** running anything; your own audit runs overwrite it.

4. **Check whether the phase's Red step exists in git at all.** Phases 1, 2 and 3 all shipped with tests + implementation entirely untracked, so Red→Green is unverifiable from history. This is an accepted, self-documented recurrence — do not re-litigate it, but do use `lastfailed`/mtimes as the only available Red evidence.

5. **Probe env-var isolation on any test that asserts a "nothing configured" default.** `Settings(_env_file=None)` disables the dotenv file but *not* OS environment variables. See [[project-config-name-collision]] and [[project-spec-doc-conflicts]].

6. **Execute the spec's stated scenario yourself rather than trusting the test's name.** Phase 3's "cash is excluded from correlation" test omitted the cash *column* entirely; feeding an actual zero-variance column (the scenario the spec names) raised a `ValidationError`. Write a throwaway probe script for every doc-stated edge case and run it directly.

7. **Run the project's own linter (`.venv/Scripts/python -m ruff check <new files>`).** Added Phase 4: ruff is in `requirements.txt` but appears never to be run. On `api/mock_client.py` it caught `DTZ005` (`datetime.now()` without tz) in one second — a finding I would otherwise have had to argue for. Cheap, zero false positives so far.
   - Phase 4 nodeids diff was clean (no deleted tests) — the weakened-test pattern did **not** recur, though only 5 tests were written at all.

**Why:** the project mandates 엄격 TDD for `models/` and `analytics/`, and gates are defined as "명령을 실행해서 참/거짓이 나와야 한다" — a gate that only passes under a non-canonical invocation, or against tests reshaped to fit the implementation, defeats that definition.

**How to apply:** open every audit with (a) the literal gate command plus a clean-room re-run, (b) a coverage run whose data collection you confirm, (c) `lastfailed` + `nodeids` capture **before** your first pytest invocation, (d) hostile-environment re-runs, (e) direct probe scripts for each doc edge case.
