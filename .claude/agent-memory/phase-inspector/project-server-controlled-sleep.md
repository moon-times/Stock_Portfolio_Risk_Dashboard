---
name: project-server-controlled-sleep
description: This repo sleeps on raw values from rate-limit response headers (X-RateLimit-Reset, Retry-After) with no clamp — negative raises ValueError, a large/epoch value hangs the app. Fixed in throttle.py (Phase 5), REGRESSED in toss_client.py (Phase 6)
metadata:
  type: project
---

Both `API_DESIGN §11.2` (`AdaptiveThrottle.before`) and `§11.3`/`§12.3` (429 `Retry-After`) call
`time.sleep(<value parsed straight from a response header>)`. Neither doc sample clamps it.
Measured 2026-08-27 (Phase 5 audit): `time.sleep(-5.0)` raises
`ValueError: sleep length must be non-negative`, and a header carrying an epoch timestamp instead
of a delta makes the app sleep ~56 years.

**Status: this defect has now occurred twice in two different files.**

- Phase 5 fixed it in `api/throttle.py` (`MAX_THROTTLE_WAIT = 10.0`, `max(0.0, min(...))`, plus
  `_remaining.pop()` after waiting).
- Phase 6 **reintroduced the identical bug** in `api/toss_client.py::_request`:
  `wait = _opt_float(resp.headers.get("Retry-After")) or 1.0` then `time.sleep(wait)`. Verified by
  probe: `Retry-After: -5` → uncaught `ValueError`; `Retry-After: 1785000000` → 56-year sleep.
  The Phase 5 fix was not reused because the clamp lives inside `AdaptiveThrottle`, not in a shared
  helper.

**Why:** FR-201b / NFR-105 make the throttle a P0 path (20 candle calls in a row). An uncaught
`ValueError` there kills the whole price-history fetch, and an unbounded sleep is an
indistinguishable hang on demo day. The spec explicitly says the numbers are *not* in the spec —
they come only from the server — so treating them as trusted input is the wrong default.

**How to apply:** whenever a phase touches throttle/retry/backoff code, grep the *whole repo* for
`time.sleep(` and check each argument for `max(0.0, min(value, CAP))`. A fix applied in one module
does not protect a sibling module — recommend a single shared `_safe_sleep()` helper. Also verify
`after()` is reached on the error path — in `§12.3 _request`, a transport error `continue`s without
calling `after()`, and `throttle.before()` is called once per `_request` rather than once per retry
attempt, so retries bypass rate limiting entirely.
See [[project-except-tuple-gap]] and [[project-phase1-audit-baseline]].
