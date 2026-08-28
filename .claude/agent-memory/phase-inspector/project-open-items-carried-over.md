---
name: project-open-items-carried-over
description: state.md's "열린 항목" list predicts the next phase's defects — the code is usually moved verbatim and the predicted bug ships. Always diff the new phase against the open-item list first.
metadata:
  type: project
---

`docs/state.md` keeps an "아직 열려있는 것" section listing defects a previous audit found but
chose not to fix. When the owning code is later moved/absorbed into a new module, it is moved
**verbatim** and the predicted defect ships in the new phase.

Confirmed instances:

- **W-8 (Phase 4)** said, in writing: "`fetch_price_history`에서 환율 조회 실패 시 `fx = Decimal(1)`로
  폴백해 USD 가격을 원화인 것처럼 시계열에 넣음 … 이 코드가 Phase 6 `toss_client.py`로 흡수되면 실제로
  문제될 수 있음." Phase 6 copied `fx = self.fetch_exchange_rate() or Decimal(1)` unchanged.
  Verified by probe: a USD candle of 500 lands in the KRW price frame as `500.0`. This violates
  **FR-202a (P0 MUST)** and `DATA_DESIGN §3.2` ("환율 조회 실패 → USD 종목 시계열에서 제외 + 경고").
- **W-11 (Phase 4)** ("`TossSecuritiesClient` 추가 시 Protocol 준수 확인") — the class does satisfy
  `api/base.py::BrokerClient` structurally, but no test or type-checker asserts it. Still open.
- **S-3 (Phase 5)** (`internal-error` etc. unmapped in `_CODE_TO_EXCEPTION`) — Phase 6 relies on raw
  `.code` string comparison, so it works, but the open item was never closed or restated.
- **Phase 7 (2026-08-28)**: S-1 (excluded tickers) and W-6 (§16 message mapping location) *were* both
  closed properly. But three items recurred: (a) the whole phase was again untracked at review time —
  same as Phase 6's own C-9, which had promised "이번 세션에서 커밋"; (b) `state.md` again still said
  "Phase 6 완료 / 다음 시작 지점 Phase 7"; (c) `tests/test_mock_client.py`'s `classified_portfolio`
  fixture, flagged since Phase 4 as "Phase 7에서 서비스 호출로 교체할 정리 대상", was untouched.
  W-5/W-6 (retry vs throttle architecture), which state.md said needed a user decision *before*
  Phase 7 started, was neither decided nor mentioned.

**Why:** the open-item list is written by the auditor at the moment of deepest context, so it is the
single highest-signal defect predictor available; letting it decay to a to-do graveyard wastes it.

**How to apply:** before auditing phase N, read `docs/state.md`'s open-item list and grep the new
phase's diff for each item's code. Report any carried-over item at **Critical**, not Suggestion —
it was already known and already scoped. Also check whether the phase updated `state.md` at all;
CLAUDE.md requires it every session, and Phase 6 shipped with `state.md` still saying "Phase 5 완료".
See [[project-weakened-test-pattern]] and [[project-except-tuple-gap]].
