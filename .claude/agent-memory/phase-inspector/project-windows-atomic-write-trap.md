---
name: project-windows-atomic-write-trap
description: On this Windows dev PC, the tempfile+os.replace "atomic write" fix for token.json raises PermissionError whenever another process holds the destination open — the exact Streamlit-rerun scenario it was added for
metadata:
  type: project
---

`os.replace(tmp, dst)` is atomic on POSIX but on Windows raises `PermissionError [WinError 5]`
if any other process/handle has `dst` open. Measured directly in this repo (2026-08-27, Phase 5
audit): `api/token_store.save_token()` crashed while a second handle on `data/cache/token.json`
was open. It also leaves the `*.tmp<pid>` file behind (containing a plaintext access token)
when the replace fails.

**Why:** `state.md` W-2 (Phase 4) asked for atomic writes because Streamlit reruns the script on
every widget interaction, so two processes can save concurrently. On Windows that concurrency
turns a benign torn read into a hard crash instead — the fix inverts the failure mode on the one
platform the project actually runs on. Compounding it, the caller
(`api/mock_client._fetch_new_token`) catches `(httpx.HTTPError, KeyError, TypeError, ValueError)`,
so `OSError`/`PermissionError` escapes into the FR-104 "must never crash" fallback path.
See [[project-except-tuple-gap]].

**How to apply:** any time this repo writes a file that another process may hold open (token cache,
future response cache), check that the write is wrapped in `try/except OSError` with a
`logger.warning` + degrade, and that leftover `.tmp*` files are cleaned up in a `finally`.
Re-check when Phase 6 `api/toss_client.py` absorbs the token logic.
