---
name: project-except-tuple-gap
description: Recurring defect class in this repo — except-tuples copied from doc sample code miss the failure modes that actually occur (TypeError/ValueError/ValidationError), so "never crashes" fallback paths do crash
metadata:
  type: project
---

Every `try/except (A, B)` in this repo that was copied from a doc sample catches strictly fewer exception types than the code can actually raise. Probe it with a hostile-input matrix rather than reading the tuple.

Confirmed at the Phase 4 audit (2026-08-27), `api/mock_client.py`:

- `fetch_portfolio` catches `(KeyError, InvalidOperation)`. Real crashes found: `ValidationError` (음수 quantity/price), `TypeError` (`Decimal(None)`, `float(None)`), `ValueError` (`MarketCountry("JP")`, `float("n/a")`), plus `KeyError` on `exchange_rate`/`buying_power` which sit **outside** the per-item try. 9 of 16 hostile inputs crashed the *fallback* client.
- `_load_cached_token` catches `(OSError, JSONDecodeError, KeyError)` — copied verbatim from `API_DESIGN §2.3`. Any non-dict JSON top level (`[]`, `null`, `"abc"`) or a non-numeric `expires_at` raises `TypeError`. Doc sample has the same hole, so Phase 5's `api/token_store.py` will inherit it unless flagged.
- `fetch_price_history` catches `(KeyError, InvalidOperation)` but `pd.to_datetime` raises `DateParseError`; `fetch_benchmark_history` catches `(KeyError, ValueError)` but `float(None)` raises `TypeError`. The two sibling methods have *asymmetric* tuples — always diff them against each other.

The one correct reference is `API_DESIGN §4.6 _to_holding`: `(KeyError, ValidationError, InvalidOperation, TypeError)` + `logger.warning`. Cite it — it is the project's own answer.

**Why:** most of these live on FR-104 / NFR-201 paths ("앱이 절대 크래시하면 안 된다"), so a missed exception type converts a graceful-degradation requirement into a hard failure, and the happy-path gate test never notices.

**How to apply:** for every new `api/` or parsing module, write a throwaway probe that mutates each field of the fixture JSON to `None`, `""`, `"abc"`, a negative number, an unknown enum value, and a missing key, then assert no exception escapes. See [[project-phase1-audit-baseline]] and [[project-mock-client-network-gate]].
