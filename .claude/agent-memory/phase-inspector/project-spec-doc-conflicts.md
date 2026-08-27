---
name: project-spec-doc-conflicts
description: Known contradictions between docs/TDD_PLAN.md, docs/TRD.md, docs/DATA_DESIGN.md and docs/REQUIREMENTS.md that recur during phase inspections
metadata:
  type: project
---

The four spec docs contradict each other in specific, recurring spots. When auditing a phase, never treat a single doc as authoritative — cross-check all four before calling something "out of scope" or "matches spec".

Conflicts confirmed as of Phase 1 audit (2026-08-27):

- **`models/` file list**: `TDD_PLAN.md:158` (T-1.2) lists **six** files including `models/dashboard.py`; `TRD.md` §3 directory tree lists only five (no `dashboard.py`). Phase 1 shipped five.
- **`Commentary.sentences` lower bound**: `REQUIREMENTS.md:120` FR-703 says 2~4 sentences (MUST); `DATA_DESIGN.md` §2.7 sample code says `min_length=1`. Implementation copied the doc sample, so the FR lower bound is unenforced.
- **`CorrelationMatrix` validation**: `DATA_DESIGN.md` §2.6 sample code checks square only; `DATA_DESIGN.md` §6 validation table says "정방행렬, **대각 = 1.0**". Only the square check exists.
- **`risk_free_rate` range**: §6 table says `0 <= r <= 0.2`, but §2.4 model sample has no constraint and never says which layer enforces it.

**Why:** the project explicitly designates TDD_PLAN as the authority on *order and scope* and DATA_DESIGN as the authority on *values/fields*, so an implementer copying DATA_DESIGN sample code verbatim can silently miss a REQUIREMENTS-level MUST.

**How to apply:** for each phase, diff the implementation against DATA_DESIGN sample code **and** the §6 validation table **and** the FR text in REQUIREMENTS. Where they disagree, report it as an item needing a user decision rather than picking a winner — CLAUDE.md says to ask when unsure. See [[project-phase1-audit-baseline]].
