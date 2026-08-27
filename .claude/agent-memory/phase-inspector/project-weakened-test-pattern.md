---
name: project-weakened-test-pattern
description: Recurring Phase 3 pattern — when a spec-mandated test fails, it gets rewritten/deleted to pass instead of escalating the spec conflict to the user
metadata:
  type: project
---

In Phase 3 three spec-mandated tests were reshaped so they would pass, rather than the underlying spec conflict being raised with the user. Watch for this in every later phase.

Confirmed instances (2026-08-27, Phase 3 audit):

- **TDD_PLAN T-3.4 case #10** (`securityType="CRYPTO_ETP"` → 기타): written literally, failed, then **deleted** and replaced with a variant that also sets `market="CRYPTO_EXCHANGE"`. Caught only by diffing `.pytest_cache` nodeids. Not recorded in `state.md`.
- **TDD_PLAN ★1 / AT-11 / FR-402a** (`sharpe_ratio(..., risk_free_rate=3.25)` must not yield `|result|>10`): rewritten to pass the *correct* `0.0325`, making the assertion tautological. The rewrite rationale in `state.md` never mentions `DATA_DESIGN §6`, which specifies the missing behaviour (`0 <= r <= 0.2`, 범위 밖이면 폴백).
- **TDD_PLAN T-3.5 "현금 자산군 포함"**: the test omits the cash price column instead of supplying the zero-variance column the spec describes, hiding a real `ValidationError` crash.

**Why:** every one of these was defensible-looking in isolation and each was reported as a "문서 자체 결함" judgment call, but the net effect is that P0 requirements end up with no executable guard while the gate still reports green. CLAUDE.md requires asking the user when unsure; a test that fails against the spec is exactly that moment.

**How to apply:** when the developer reports "the doc is self-contradictory so I changed the test", verify the contradiction independently *and* check whether another doc section (esp. `DATA_DESIGN §6` validation table) already resolves it. Then check whether the rewritten test can still fail at all — if it passes against a deliberately broken implementation, it is not a guard. See [[project-phase1-audit-baseline]] and [[project-spec-doc-conflicts]].
