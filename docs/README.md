# 포트폴리오 리스크 대시보드 — SDD 문서 세트

Claude Code가 이 프로젝트를 구현하기 위한 명세 문서 모음이다.

---

## 읽는 순서

| # | 문서 | 무엇이 들어있나 |
|---|---|---|
| 1 | [PRD.md](PRD.md) | 왜 만드는가. 범위, 사용자 스토리, 마일스톤, 비목표 |
| 2 | [TRD.md](TRD.md) | 어떻게 만드는가. 아키텍처, 스택, 디렉토리, 구현 순서 |
| 3 | [REQUIREMENTS.md](REQUIREMENTS.md) | 무엇을 만족해야 하는가. FR/NFR 식별자, 추적성, 수용 테스트 |
| 4 | [design/DATA_DESIGN.md](design/DATA_DESIGN.md) | 도메인 모델, 지표 수식, 자산군 분류 |
| 5 | [design/API_DESIGN.md](design/API_DESIGN.md) | 외부 API 계약, 어댑터, 재시도, LLM 프롬프트 |
| 6 | [design/COMPONENT_DESIGN.md](design/COMPONENT_DESIGN.md) | 모듈 책임, 함수 시그니처, UI 컴포넌트 |
| 7 | [design/USE_CASES.md](design/USE_CASES.md) | 시나리오별 흐름, 예외 경로, 시연 시나리오 |

UI 레퍼런스: [assets/dashboard_mockup.png](assets/dashboard_mockup.png)

---

## 프로젝트 한 줄 요약

토스증권 Open API로 실계좌 보유 자산을 가져와 리스크 지표를 계산하고, LLM이 그 숫자를 자연어 진단으로 번역해주는 **로컬 Streamlit 대시보드**. 2일 스코프.

---

## API 스펙 상태

✅ **토스증권 Open API OpenAPI 3.1 스펙 v1.2.14 반영 완료.** 전 엔드포인트·필드명이 확정되어 있다. 추정으로 남은 부분은 없다.

| 항목 | 값 |
|---|---|
| Base URL | `https://openapi.tossinvest.com` |
| 인증 | OAuth2 Client Credentials, form-urlencoded |
| 계좌 지정 | `X-Tossinvest-Account: {accountSeq}` 헤더 |
| 응답 envelope | 성공 `{"result": ...}` / 실패 `{"error": {code, message, requestId}}` |

## 구현 시작 전 확인

| # | 확인 사항 | 상태 | 문서 |
|---|---|---|---|
| 1 | `.env` 생성 및 `TOSS_CLIENT_ID` / `TOSS_CLIENT_SECRET` 입력 | ✅ 발급 완료 (2026-08-26, 활성) | TRD §5.1 |
| 2 | 토스증권 콘솔 IP 화이트리스트에 개발 PC IP 등록 | ✅ 등록 완료 | API_DESIGN §2.4 |
| 3 | `ANTHROPIC_API_KEY` 준비 | ✅ 준비 완료 | TRD §5.1 |
| 4 | Python 3.11+ 환경 확인 | 확인 필요 | TRD §2.1 |
| 5 | `API_DESIGN.md §2.3` (토큰 단일성 제약) 숙지 — 가장 중요 | 필독 | API_DESIGN §2.3 |

---

## 구현 순서 (요약)

`TRD.md §11`의 10단계를 따른다. 요점:

1. `models/` → 2. `config.py` → 3. **`analytics/` 테스트 먼저 작성 후 구현** → 4. `api/mock_client.py` → 5. `api/` 인프라(`token_store`, `throttle`, `errors`) → 6. `api/toss_client.py` → 7. `services/` → 8. `ui/` + `app.py` → 9. `ai/` → 10. 오프라인 모드 + 리허설

> 4번(목업 클라이언트)을 6번(실제 API)보다 먼저 만든다. 실계좌 연동에서 막혀도 나머지 진행이 멈추지 않는다.

---

## 절대 규칙

| # | 규칙 | 근거 |
|---|---|---|
| 1 | 매매 주문·이체 기능을 구현하지 않는다 | FR-106, CON-05 |
| 2 | API 키를 코드에 하드코딩하지 않는다 | NFR-301 |
| 3 | 계좌번호는 항상 마스킹한다 | FR-105 |
| 4 | PyQt를 쓰지 않는다 (Streamlit 확정) | CON-01 |
| 4b | FinanceDataReader를 쓰지 않는다 (`/api/v1/candles` 사용) | CON-09 |
| 5 | `analytics/`는 순수 함수만 (I/O 금지) | NFR-401 |
| 6 | `ui/`에서 계산하지 않는다 | NFR-403 |
| 7 | 어떤 외부 실패도 앱을 죽이지 않는다 | NFR-201 |
| 8 | 모든 표시 숫자는 포맷터를 거친다 | FR-806 |
| 9 | API의 문자열 숫자는 `Decimal(str(v))`로 파싱한다. `float()` 금지 | FR-106a |
| 10 | 미지의 enum 값을 `StrEnum`으로 강제 파싱하지 않는다 | FR-106b |
| 11 | 토큰은 디스크 캐시하고 만료 임박·401 외에는 재발급하지 않는다 | FR-101a/b |
| 12 | 무위험수익률은 `/100` 변환 후 사용한다 (`"3.25"` → `0.0325`) | FR-402a |

---

## 데모 통과 조건

`REQUIREMENTS.md §4.3`의 P0 체크리스트 전체 + 아래 3개 시나리오 통과:

- [ ] AT-01 유효한 `.env`로 실행 → 실계좌 데이터 렌더링
- [ ] AT-02 `.env` 삭제 후 실행 → 샘플 데이터 + 배지
- [ ] AT-03 Wi-Fi 끄고 실행 → 캐시 데이터 + 오프라인 배지
- [ ] AT-09 2회 연속 실행 → 토큰 재발급 없음
- [ ] AT-11 샤프지수 절댓값 10 미만 (무위험수익률 단위 검증)

---

## 발표 전략 (2026-08-26 확정)

실계좌는 VOO(해외 ETF) 단일 종목 + 현금만 보유 — 자산군이 사실상 1개라 상관관계 히트맵(발표 핵심 장면)을 실계좌로는 재현할 수 없다.

| 항목 | 결정 | 근거 |
|---|---|---|
| 발표 메인 시연 | **샘플 데이터**(`data/sample_portfolio.json`) 기준으로 진행. 국내/해외/채권/현금/원자재 5개 자산군 + 상관관계 히트맵으로 "종목 수 ≠ 분산" 서사 전달 | 실계좌로는 다중 자산군 서사 재현 불가 |
| 실계좌 연동 | 보조 시연. "실제 내 계좌에도 붙는다"는 것만 짧게 보여줌 (`USE_CASES.md` 부록B 3:45~4:15) | 기술적 완성도 어필. 투자 결정을 발표용으로 왜곡하지 않음 |
| 우선순위 조정 | 상관관계 히트맵(FR-501~504, 문서상 P1)은 샘플 데이터 경로에서 **사실상 필수**로 취급. 벤치마크 비교 차트(FR-601~603)는 원래대로 P1 유지 | 시간이 부족해지면 벤치마크 차트부터 드롭 |

---

## 알려진 단순화

구현 시 README에 명시할 것.

| 항목 | 단순화 내용 | 문서 |
|---|---|---|
| 환율 | 일별 환율(`dateTime` 파라미터로 가능) 대신 조회 시점 `midRate` 단일값으로 전체 시계열 환산. **환율 변동 리스크가 지표에서 빠진다** | API_DESIGN §6.3 |
| 현금 | `cashBuyingPower`(매수가능금액)를 예수금 대신 사용. Open API에 예수금 조회가 없음. 미결제 매수 주문이 있으면 실제 예수금보다 작음 | API_DESIGN §5.3 |
| 비중 | 현재 비중을 과거 전 기간에 고정 (buy-and-hold 가정). 거래내역 조회는 범위 밖 | DATA_DESIGN §4.7 |
| ETF 분류 | `securityType`이 ETF의 기초자산을 알려주지 않아 종목명 키워드로 하위 분류 | DATA_DESIGN §5.1 |
| 계산 기간 | 최근 126 거래일 고정 (캔들 1회 호출로 커버) | PRD Q3 |
| 토큰 파일 권한 | Windows에서는 `chmod(0o600)`이 강제되지 않는다 (POSIX 전용 API). `try/except`로 감싸 조용히 스킵하고, 보안은 `.gitignore` + 단일 사용자 PC 전제에 의존한다 | API_DESIGN §2.3, NFR-306 |

---

## 위험 지점 3가지

구현 중 가장 사고가 나기 쉬운 곳.

| # | 위험 | 증상 | 방어 |
|---|---|---|---|
| 1 | **토큰 재발급이 이전 토큰을 무효화** | Streamlit 재실행마다 401이 번갈아 발생, 개발 세션이 서로를 죽임 | 디스크 영속 캐시 + 401 시 요청당 1회만 재발급 (API_DESIGN §2.3) |
| 2 | **무위험수익률 단위** | 샤프지수가 -17 같은 값 | `api/` 경계에서 `/100`. 테스트에서 절댓값 10 초과 시 실패 처리 |
| 3 | **`Price.usd`가 `null`** | `Decimal(None)` 예외로 앱 크래시 | 해외 종목 미보유 계좌에서 발생. 널 가드 필수 (API_DESIGN §4.4) |
