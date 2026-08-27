---
name: project-token-single-validity
description: 위험1 (token invalidation loop) — Toss issues one valid token per client, and this repo's refresh path discards the freshly issued token and re-reads it from a cache whose writes are silently allowed to fail
metadata:
  type: project
---

Toss Open API invalidates the previous token whenever a new one is issued (`API_DESIGN §2.3`), so
每 extra issuance kills the token another Streamlit rerun may be holding. TDD_PLAN names this
**위험 1** and makes T-6.2 #2 + 관문 6 its defence.

The structural weakness found at the Phase 6 audit (2026-08-27), `api/toss_client.py`:

- `_token()` is `token_store.load_token() or _fetch_new_token(...)`, and `_request`'s 401 branch
  calls `_fetch_new_token(self._settings)` **discarding the return value**, relying on the next
  loop iteration re-reading it from disk.
- Phase 5 deliberately made `token_store.save_token` swallow `OSError` (its C-1 fix, for a real
  Windows `os.replace` `PermissionError`). So a silent cache-write failure makes `load_token()`
  return `None` and the loop issues *another* token. Measured: **3 token issuances for one
  `_request` that made 2 HTTP calls.**
- `_fetch_new_token` returns `body["access_token"]` with no `isinstance(str)` check. Phase 5's W-2
  fix added that guard to `load_token` only. A non-str `access_token` produces a
  `Bearer {'a': 1}` header *and* poisons the cache so that `load_token()` returns `None` forever
  after — i.e. every subsequent call re-issues. Both halves of the loop in one bug.
- The unit test `test_401_then_success_refreshes_token_exactly_once` passes because `save_token`
  succeeds under `tmp_path`. It cannot detect the loop.

**Why:** the loop burns the AUTH rate limit and can leave the demo unable to authenticate at all;
관문 6's "2회 실행 시 재발급 없음" check runs on a healthy disk and will not surface it.

**How to apply:** when auditing token/auth code, (1) check that a forced refresh **uses the returned
token directly** rather than round-tripping through a best-effort cache, (2) run the refresh path
with `save_token` stubbed to a no-op and count `/oauth2/token` calls, (3) check the issuance path
validates the token's type, not just the load path.
See [[project-except-tuple-gap]] and [[project-windows-atomic-write-trap]].
