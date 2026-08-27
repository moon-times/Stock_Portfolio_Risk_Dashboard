---
name: project-mock-client-network-gate
description: The Phase 4 "발표 서사 보증 관문" (T-4.4) needs live network + valid Toss credentials + a whitelisted IP, so the fallback client's own gate cannot pass in the FR-104 scenario it exists for
metadata:
  type: project
---

`MockBrokerClient` is the FR-104 fallback ("API 키 없이 실행해도 화면 렌더링"), but `DATA_DESIGN §7` / `TDD_PLAN §8` require it to fetch `/candles` live. Measured 2026-08-27 with empty credentials: `fetch_price_history` returns an **empty DataFrame** in 5.7s after 7 wasted `/oauth2/token` POSTs, so volatility·Sharpe·MDD·VaR·beta·correlation·benchmark are all `None`. Gate item 3 (상관행렬 2×2 이상) is unreachable without credentials.

Consequences to re-check every later phase:

- `tests/test_mock_client.py::test_correlation_matrix_at_least_2x2` is a live-network test with no marker/skip. It breaks whenever the 공인 IP changes (API_DESIGN §2.4 A8) — this already happened twice in this project.
- Demo-day risk: presenting from a venue whose IP is not whitelisted degrades the demo to allocation-only. Docs answer "Phase 10 캐시가 처리한다", but a cold cache at the venue does not help.
- Toss normalizes US candle timestamps to KST (`AAPL` → `...T13:00:00+09:00`), so the KR/US `.date()` alignment worry from `DATA_DESIGN §3.2` is **not** a real problem. Do not re-report it.
- `fetch_price_history` returns an object-dtype `Index` of `datetime.date`, not the `DatetimeIndex` that `DATA_DESIGN §3.1` specifies.

**Why:** the gate is defined as "이 테스트가 통과해야 발표가 성립한다", so a gate that depends on the very network the fallback exists to survive gives false assurance.

**How to apply:** when auditing Phase 6/7/10, verify the price path was split into an offline-deterministic part and a network-marked part, and that `RiskMetrics.excluded_tickers` + the `유효 행 ≥ 30` rule (`DATA_DESIGN §6`) finally got implemented. See [[project-except-tuple-gap]].
