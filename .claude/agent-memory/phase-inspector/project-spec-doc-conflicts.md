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
- **`risk_free_rate` range**: §6 table says `0 <= r <= 0.2` / "범위 밖이면 단위 오류로 간주, 폴백값 사용", but §2.4 model sample has no constraint and §4.2 says the `/100` conversion "ends in the `api/` layer". Still unresolved after Phase 3; `state.md` tracks it as open item **S-5**. This is the doc section that resolves the AT-11 / FR-402a puzzle — always cite it.

Added at Phase 3 audit (2026-08-27):

- **AT-11 unit guard**: `TDD_PLAN §7 ★1` + `REQUIREMENTS` FR-402a + AT-11 all say `sharpe_ratio(returns, 3.25)` must not produce `|result| > 10`. Implementing `DATA_DESIGN §4.2` code verbatim gives `-24.3`. Only §6's range/fallback rule makes the three consistent — so this is a **missing guard**, not an impossible test.
- **Unknown-enum fallthrough**: `TDD_PLAN` T-3.4 case #10 expects `securityType="CRYPTO_ETP"` → 기타, but `DATA_DESIGN §5.3` step 6 returns 국내주식 whenever `market` is a known KR market. The two cannot both hold unless `market` is also unknown.
- **`DATA_DESIGN §4.2` negative-excess example**: `[-0.001]*252` is constant, so the same section's `vol == 0 → None` guard fires and the stated `< 0` expectation is unreachable. This one **is** a genuine doc defect (verified).
- **analytics file I/O**: `COMPONENT_DESIGN §1` module table forbids `파일` in `analytics/`, but `COMPONENT_DESIGN §5` puts `from_yaml` inside `analytics/classifier.py`. `REQUIREMENTS` NFR-401 text only forbids 네트워크·전역상태, not files — so NFR-401 is *not* violated by a YAML loader.

**Why:** the project explicitly designates TDD_PLAN as the authority on *order and scope* and DATA_DESIGN as the authority on *values/fields*, so an implementer copying DATA_DESIGN sample code verbatim can silently miss a REQUIREMENTS-level MUST.

**How to apply:** for each phase, diff the implementation against DATA_DESIGN sample code **and** the §6 validation table **and** the FR text in REQUIREMENTS. Where they disagree, report it as an item needing a user decision rather than picking a winner — CLAUDE.md says to ask when unsure. See [[project-phase1-audit-baseline]].
