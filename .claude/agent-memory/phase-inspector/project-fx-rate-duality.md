---
name: project-fx-rate-duality
description: Two independent USD→KRW sources exist (service-level fetch_exchange_rate vs Portfolio.fx_rate); when they disagree, 총자산 and 자산배분 합계 render different numbers on the same screen
metadata:
  type: project
---

This repo has **two** USD→KRW rates in flight per page load, fetched independently:

1. `DashboardService._load_fx_rate()` → passed to `build_allocation()` / `market_value_krw()` / weights.
2. `Portfolio.fx_rate`, set inside `TossSecuritiesClient.fetch_portfolio()` / `MockBrokerClient.fetch_portfolio()` by their *own* `fetch_exchange_rate()` call — and consumed by the `@computed_field`s `Portfolio.cash_total_krw` and `Portfolio.total_value`.

`DashboardData` carries both (`portfolio` and `allocation`), so if one fetch succeeds and the other returns `None` the UI shows two contradictory totals. Measured at the Phase 7 audit (2026-08-28) with service-fx `None` and `portfolio.fx_rate=1300`: `portfolio.total_value=4,600,000` vs `allocation.total_value=700,000` — 6.5x, with only a generic 환율 warning. `analytics/allocation.py`'s own docstring warns against exactly this mixing, one layer down.

Live path also calls `fetch_exchange_rate()` up to 3x per `load()` (service + `fetch_portfolio` + `fetch_price_history`), which spends NFR-105 rate budget and makes divergence more likely, not less.

**Why:** a risk dashboard silently displaying a wrong headline 총자산 is worse than crashing; the failure only appears in the degraded fx path, which is also the demo-without-credentials path.

**How to apply:** when auditing Phase 8 (`ui/`, `app.py`) or anything touching money, check which of the two rates each rendered figure descends from. The single-source fix is to reconcile in `DashboardService.load()` (`fx_rate = fx_rate or portfolio.fx_rate`, or overwrite `portfolio.fx_rate` with the service value) before assembling `DashboardData`. Related: [[project-except-tuple-gap]], [[project-open-items-carried-over]].
