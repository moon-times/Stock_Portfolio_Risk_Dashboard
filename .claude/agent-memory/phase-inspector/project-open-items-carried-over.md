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

**Why:** the open-item list is written by the auditor at the moment of deepest context, so it is the
single highest-signal defect predictor available; letting it decay to a to-do graveyard wastes it.

**How to apply:** before auditing phase N, read `docs/state.md`'s open-item list and grep the new
phase's diff for each item's code. Report any carried-over item at **Critical**, not Suggestion —
it was already known and already scoped. Also check whether the phase updated `state.md` at all;
CLAUDE.md requires it every session, and Phase 6 shipped with `state.md` still saying "Phase 5 완료".
See [[project-weakened-test-pattern]] and [[project-except-tuple-gap]].
