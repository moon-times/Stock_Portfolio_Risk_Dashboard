---
name: project-config-name-collision
description: Root config.py and config/ directory share a name by design (TRD §3) — safe today, but adding config/__init__.py silently breaks every "from config import settings"
metadata:
  type: project
---

`TRD.md` §3 deliberately specifies **both** a settings module `config.py` and a data directory `config/` (holding `asset_class_map.yaml`) at the repo root. Verified empirically 2026-08-27:

- `config/` empty or containing only data files (no `__init__.py`) → CPython prefers the regular module, `import config` resolves to `config.py`. **Safe.** Reading `config/asset_class_map.yaml` by plain path alongside `import config` works fine, so Phase 3's `classifier.py` is not at risk as long as the rule below holds.
- Adding **`config/__init__.py`** flips `config/` into a regular package, which wins over `config.py`, and every `from config import settings` dies with `ImportError`. This is a live hazard because every *other* package dir in this repo (`ai/ analytics/ api/ models/ services/ ui/`) does have an `__init__.py`, so anyone applying the local convention mechanically will break the app.
- Side effect already present: `--cov=config` resolves to the empty directory and reports "No data was collected", silently measuring nothing. `--cov=config.py` does not help either. Coverage of the settings module only works if `config/` is absent.

**Why:** the collision is baked into the spec, so it will not be refactored away casually; the failure mode is silent and appears far from the change that caused it.

**How to apply:** in every audit from Phase 3 onward, check `config/` for an `__init__.py` and flag it as Critical if present. When a coverage gate is reported as met, confirm the run actually collected data rather than trusting the pass count. See [[project-phase1-audit-baseline]].
