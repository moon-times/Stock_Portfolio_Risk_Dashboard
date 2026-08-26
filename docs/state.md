# 세션 상태 — 2026-08-26 (기획 그릴링 + TDD 계획 수립)

## 이번 세션에서 한 일
- `docs/` 내 SDD 문서 세트(PRD, TRD, REQUIREMENTS, DATA_DESIGN, API_DESIGN, COMPONENT_DESIGN, USE_CASES) 전체 검토
- `/grill-me`로 실행 가능성 관점의 빈 칸 8개 질문, 전부 사용자 확답 확보
- 확정된 결정을 각 문서에 반영 완료 (아래 "변경 파일" 참고)
- **`docs/TDD_PLAN.md` 신규 작성** — TRD §11의 10단계를 TDD Phase-Task 11개로 전개

## 확정된 사실 / 결정

| 항목 | 내용 |
|---|---|
| 토스증권 API 키 | 발급·활성 완료 (2026-08-26, 만료 2027-08-26) |
| IP 화이트리스트 | 개발 PC IP 등록 완료 |
| Anthropic API 키 | 준비 완료 |
| 실계좌 구성 | VOO(해외 ETF) 단일종목 + 현금만 보유. 학생, 저축 목적 투자 |
| 발표 전략 | 메인 시연은 샘플 데이터(5개 자산군 + 상관관계 히트맵), 실계좌 연동은 보조 시연 |
| 우선순위 조정 | 상관관계 히트맵(FR-501~504)은 샘플 경로에서 사실상 필수. 벤치마크 비교(FR-601~603)는 P1 유지 |
| 일정 | 오늘(8/26)이 Day 1, 내일(8/27)이 Day 2, 발표는 8/27 저녁~8/28 |
| Windows 토큰 권한 | `chmod(0o600)`은 Windows에서 best-effort(무효). `.gitignore` + 단일 사용자 PC 전제로 대체 |
| TDD 범위 | docs 기준 그대로 — `analytics/`·`models/`는 엄격 TDD(테스트 먼저), `api/`·`ai/`·`ui/format`은 테스트 동반, `ui/` 컴포넌트는 테스트 없음 |
| 실계좌 스모크 | TRD §11 순서보다 앞당겨 **Phase S**로 신설 (Phase 0 직후). 위험 1·3과 T5를 15분 만에 사전 확인 |
| AI 모델 ID | `API_DESIGN §15.1`을 `claude-sonnet-4-6` → `claude-sonnet-5`로 변경 완료 |

## 변경 파일 (이번 세션)

- `docs/README.md` — 구현 시작 전 확인 표에 상태 열 추가, IP 화이트리스트 항목 추가, "발표 전략" 섹션 신설, 알려진 단순화에 Windows 토큰 권한 행 추가
- `docs/PRD.md` — §5.1에 F5 우선순위 예외 각주, §10 열린 질문에 Q7(발표 전략) 추가
- `docs/REQUIREMENTS.md` — FR-500 블록에 발표 전략 메모, §2.3 보안 뒤에 Windows 메모 추가
- `docs/TRD.md` — §5.2 보안 규칙 뒤에 Windows 토큰 권한 메모 추가
- `docs/API_DESIGN.md` — §2.4 "IP 화이트리스트" 신설, 토큰 저장 코드에 Windows try/except 반영
- `docs/USE_CASES.md` — 부록B 시연 시나리오를 샘플 중심으로 재구성 + 실계좌 보조 시연 배치, UC-07에 실계좌 사례 메모 추가
- `docs/TDD_PLAN.md` — **신규.** Phase 0~10 (+Phase S) Task별 테스트/구현/관문, 컷 라인(부록A), P0 역인덱스(부록B), 위험 3종 방어 위치(부록C)

## 아직 열려있는 것 (다음 세션에서 다룰 것)

- T5: `cashBuyingPower`와 실제 예수금 괴리 — **Phase S에서 실측 예정** (TDD_PLAN §4 확인항목 4)
- PRD Q3: 리스크 계산 기간 126 거래일 — "잠정" 표기 그대로, 확정 논의는 안 함
- 실계좌 보조 시연에 부록B 3:45~4:15로 초안 배치했으나 리허설로 시간 배분 검증 필요

## 다음 시작 지점

`docs/TDD_PLAN.md` **Phase 0 (골격)** → **Phase S (실계좌 스모크)** 순서로 시작. 아직 코드 없음 (문서만 존재하는 상태).
