---
name: project-server-controlled-sleep
description: This repo sleeps on raw values from rate-limit response headers (X-RateLimit-Reset, Retry-After) with no clamp — negative raises ValueError, a large/epoch value hangs the app
metadata:
  type: project
---

Both `API_DESIGN §11.2` (`AdaptiveThrottle.before`) and `§11.3` (429 `Retry-After`) call
`time.sleep(<value parsed straight from a response header>)`. Neither doc sample clamps it.
Measured 2026-08-27 (Phase 5 audit): `time.sleep(-5.0)` raises
`ValueError: sleep length must be non-negative`, and a header carrying an epoch timestamp instead
of a delta makes `before()` sleep ~56 years — repeatedly, because `before()` never clears
`_remaining` after waiting, so every later call sleeps again until an `after()` updates it.

**Why:** FR-201b / NFR-105 make the throttle a P0 path (20 candle calls in a row). An uncaught
`ValueError` there kills the whole price-history fetch, and an unbounded sleep is an
indistinguishable hang on demo day. The spec explicitly says the numbers are *not* in the spec —
they come only from the server — so treating them as trusted input is the wrong default.

**How to apply:** whenever a phase touches throttle/retry code, check for
`max(0.0, min(value, CAP))` around every sleep argument, and check that `before()` invalidates its
cached `remaining` after waiting. Also verify `after()` is reached on the error path — in
`§12.3 _request`, a `ConnectError` `continue`s without calling `after()`.
See [[project-except-tuple-gap]] and [[project-phase1-audit-baseline]].
