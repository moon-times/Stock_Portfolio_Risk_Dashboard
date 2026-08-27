---
name: project-except-tuple-gap
description: Recurring defect class in this repo — except-tuples copied from doc sample code miss the failure modes that actually occur (TypeError/ValueError/ValidationError/AttributeError/httpx.TransportError), so "never crashes" fallback paths do crash
metadata:
  type: project
---

Every `try/except (A, B)` in this repo that was copied from a doc sample catches strictly fewer exception types than the code can actually raise. Probe it with a hostile-input matrix rather than reading the tuple.

Confirmed at the Phase 4 audit (2026-08-27), `api/mock_client.py`:

- `fetch_portfolio` caught `(KeyError, InvalidOperation)`. Real crashes: `ValidationError`, `TypeError`, `ValueError`, plus `KeyError` outside the per-item try. 9 of 16 hostile inputs crashed the *fallback* client.
- `_load_cached_token` caught `(OSError, JSONDecodeError, KeyError)` — verbatim from `API_DESIGN §2.3`. Non-dict JSON top level raises `TypeError`.
- `fetch_price_history` / `fetch_benchmark_history` had **asymmetric** tuples — always diff sibling methods against each other.

Re-confirmed and extended at the Phase 6 audit (2026-08-27), `api/toss_client.py` — 16 of 50 hostile inputs crashed:

- **`AttributeError` appears in ZERO except-tuples in the whole module**, yet every parse site is `(data.get("result") or {}).get(...)`. Any server response where `result` is a list/str/number (or the top-level JSON is a list) raises `AttributeError` and escapes. This alone accounted for 9 of the 16 crashes. Grep the module for `AttributeError` — if the count is 0 while `.get()` chains exist, it is broken.
- **`json.JSONDecodeError` on the *success* path**: `_request` returns `resp.json()` for HTTP 200 with no guard. An HTML error page served with status 200 crashes `bootstrap`/`fetch_portfolio`. `_error_code` guards the *failure* path only — the asymmetry is easy to miss.
- **httpx transport-error tuple**: `(httpx.ConnectError, httpx.ReadTimeout, httpx.TimeoutException)` misses `ReadError`, `WriteError`, `RemoteProtocolError`, `ProxyError`, `ProtocolError`. `RemoteProtocolError` (server closes connection mid-response) is common in production. The correct catch is the base class `httpx.TransportError` (or `httpx.HTTPError`).
- **`fetch_stock_meta`** catches `(KeyError, ValidationError)` but non-dict rows raise `TypeError` — the sibling `_to_holding` has the right 4-tuple. Asymmetry again.
- `Decimal(str(v))` **never raises** for `"NaN"`/`"Infinity"` — it returns `Decimal('NaN')`/`Decimal('Infinity')`. So `_opt_decimal`-style helpers that only catch `InvalidOperation` let NaN through into money fields and risk-free rates. Pydantic then rejects it downstream with `finite_number`, which can silently trigger a lossy fallback branch.

The one correct reference is `API_DESIGN §4.6 _to_holding`: `(KeyError, ValidationError, InvalidOperation, TypeError)` + `logger.warning`. Cite it — it is the project's own answer — but note it still lacks `AttributeError`.

**Why:** most of these live on FR-104 / NFR-201 / NFR-204 paths ("앱이 절대 크래시하면 안 된다"), so a missed exception type converts a graceful-degradation requirement into a hard failure, and the happy-path gate test never notices.

**How to apply:** for every new `api/` or parsing module, write a throwaway probe that mutates each field of the fixture JSON to `None`, `""`, `"abc"`, `"NaN"`, a negative number, an unknown enum, a missing key — **and separately replaces each container (`result`, `items`, `candles`, top-level body) with a list, a string, and a number**. Then assert no non-`DashboardError` escapes. See [[project-phase1-audit-baseline]] and [[project-mock-client-network-gate]].
