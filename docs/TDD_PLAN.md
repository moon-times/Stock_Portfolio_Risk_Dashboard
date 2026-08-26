# TDD PLAN — Phase-Task 구현 순서표

| 항목 | 내용 |
|---|---|
| 문서 버전 | 1.0 |
| 최종 수정 | 2026-08-26 |
| 선행 문서 | `TRD.md §11`, `COMPONENT_DESIGN.md §6`, `REQUIREMENTS.md §4.3` |
| 대상 | Claude Code (구현 주체) |
| 개발 기간 | Day 1 = 2026-08-26, Day 2 = 2026-08-27 |

---

## 0. 이 문서의 역할

기존 문서가 답하는 것과 이 문서가 답하는 것을 구분한다.

| 질문 | 답하는 문서 |
|---|---|
| 무엇을 만족해야 하는가 | `REQUIREMENTS.md` (FR/NFR) |
| 지표 수식과 기댓값은 무엇인가 | `DATA_DESIGN.md §4` |
| 어떤 모듈이 어떤 책임을 지는가 | `COMPONENT_DESIGN.md` |
| **지금 어떤 테스트를 쓰고, 무엇을 구현하고, 언제 다음으로 넘어가는가** | **이 문서** |

> **원칙**: 이 문서는 **순서와 관문(Gate)**만 담당한다. 구체적 기댓값(예: `max_drawdown(100→120→90→110) ≈ -0.25`)은 `DATA_DESIGN.md §4`에 이미 있으므로 복사하지 않고 **참조**한다. 두 곳에 같은 숫자를 적으면 반드시 어긋난다.

---

## 1. TDD 사이클 규약

모든 Task는 아래 3단계를 거친다. **Red를 건너뛰지 않는다.**

```
Red   테스트를 먼저 쓰고 실행한다 → 반드시 실패해야 한다
      (통과하면 테스트가 잘못 쓰인 것이다)
Green 테스트를 통과시키는 최소 구현을 쓴다
Next  통과를 확인하고 다음 Task로 간다
```

### 1.1 계층별 TDD 강도

`TRD.md §8.1`을 그대로 따른다.

| 계층 | 강도 | 의미 |
|---|---|---|
| `analytics/` | **엄격 TDD** | 테스트를 먼저 쓴다. 순수 함수라 정답이 존재한다 |
| `models/` | **엄격 TDD** | 검증 규칙(마스킹·unknown enum)이 곧 테스트다 |
| `api/` | 테스트 동반 | `COMPONENT_DESIGN §6`이 지정한 테스트 파일은 반드시 쓰되, 구현과 동시 진행 허용 |
| `ai/` | 테스트 동반 | 프롬프트 **생성 함수만** 테스트. LLM 응답은 테스트하지 않음 |
| `ui/format.py` | 테스트 동반 | 포맷터는 정답이 명확하므로 테스트 |
| `ui/` 나머지 | **테스트 안 함** | 2일 스코프에서 비용 대비 효과 없음 |

### 1.2 Phase 관문 (Gate)

**관문을 통과하지 못하면 다음 Phase로 넘어가지 않는다.** 관문은 반드시 *실행해서 참/거짓이 나오는 명령*이어야 한다.

- ✅ 좋은 관문: `pytest tests/ --cov=analytics` 통과 + 커버리지 ≥80%
- ❌ 나쁜 관문: "분류가 잘 동작한다"

---

## 2. 전체 Phase 지도

| Phase | 이름 | 시점 | 관문 |
|---|---|---|---|
| **0** | 골격 | Day1 오전 | `pytest` 실행 시 에러 없음, 전 의존성 import 성공 |
| **S** | 🔴 실계좌 스모크 (일회성·폐기) | Day1 오전 (0 직후) | 토큰 발급 + `/accounts` 200 + BROKERAGE 계좌 확인 |
| **1** | `models/` | Day1 오전 | `pytest tests/test_models.py` 통과 |
| **2** | `config.py` | Day1 오전 | `.env` 없이 `settings` 로드 성공 |
| **3** | `analytics/` ★핵심 | Day1 오전~오후 | **커버리지 ≥80%** (AT-07) |
| **4** | 목업 클라이언트 + 샘플 데이터 | Day1 오후 | 샘플에서 **자산군 5개** 산출 |
| **5** | `api/` 인프라 | Day1 오후 | errors·token_store·throttle 테스트 통과 |
| **6** | `api/toss_client.py` | Day1 오후~저녁 | 실계좌 잔고 조회 + **2회 실행에 토큰 재발급 없음** (AT-09) |
| **7** | `services/` | Day1 저녁 | **Day 1 종료 조건** — 터미널에 실제 지표 출력 |
| **8** | `ui/` + `app.py` | Day2 오전~오후 | 브라우저에 6블록 렌더링 |
| **9** | `ai/` | Day2 오후 | AI 배너 표시 + 키 제거 시 규칙 기반 폴백 (AT-04) |
| **10** | 오프라인 + 리허설 | Day2 저녁 | AT-01~13 전수 + 시연 리허설 1회 완주 |

> **Phase S를 `TRD.md §11`의 순서보다 앞으로 당긴 이유**: 토큰 단일성 제약(위험 1)과 IP 화이트리스트는 **실제로 한 번 호출해 봐야만** 확인된다. Day 1 후반(Phase 6)에서 처음 발견하면 남은 일정을 재구성할 시간이 없다. 15분을 먼저 써서 나머지 2일을 지킨다.

---

## 3. Phase 0 — 골격

| ID | 테스트 | 구현 | 완료 조건 | 요구사항 |
|---|---|---|---|---|
| T-0.1 | — | `TRD.md §3` 디렉토리 구조 생성 (빈 `__init__.py` 포함) | `models/ api/ analytics/ ai/ services/ ui/ config/ data/ tests/` 존재 | — |
| T-0.2 | — | `requirements.txt`(TRD §2.2 그대로) · `.gitignore` · `.env.example`(TRD §5.1) | `pip install -r requirements.txt` 성공 | NFR-302 |
| T-0.3 | — | pytest 설정 (`pytest.ini` 또는 `pyproject.toml`, `testpaths=tests`) | `pytest` 실행 시 "no tests ran" (에러 아님) | — |

**`.gitignore` 필수 항목** (NFR-302, NFR-306)
```
.env
data/cache/
__pycache__/
.venv/
*.pyc
.pytest_cache/
```

### 관문 0

```bash
pip install -r requirements.txt
python -c "import streamlit, plotly, httpx, pandas, numpy, scipy, pydantic, yaml, anthropic; print('OK')"
pytest
```

---

## 4. Phase S — 실계좌 스모크 (일회성)

> 🔴 **이 Phase의 산출물은 코드가 아니라 "정보"다.** 스크립트는 스크래치패드에서 실행하고 **커밋하지 않는다.**

| ID | 내용 | 완료 조건 |
|---|---|---|
| T-S.1 | 일회성 스크립트로 4개 엔드포인트를 각 1회 호출 | 아래 확인 항목 5개 기록 |

### 호출 순서

```
1. POST /oauth2/token                       → access_token, expires_in
2. GET  /api/v1/accounts                    → accountSeq, accountType
3. GET  /api/v1/buying-power?currency=KRW   → cashBuyingPower
4. GET  /api/v1/holdings                    → VOO 실제 응답 구조
```

### 확인 항목 (기록해서 남긴다)

| # | 확인할 것 | 왜 |
|---|---|---|
| 1 | IP 화이트리스트 통과 여부 | 막히면 전 일정 재구성 필요 (`API_DESIGN §2.4`) |
| 2 | `expires_in` 실제값 | 토큰 캐시 만료 로직의 입력 (스펙 예시는 86400) |
| 3 | `accountType == "BROKERAGE"` 계좌 존재 | `resolve_account()` 전제 |
| 4 | **`cashBuyingPower` vs 실제 예수금 괴리** | `TRD §12 T5` 미해결 항목. VOO 단일종목이라 지금이 확인하기 가장 쉬움 |
| 5 | **`marketValue.amount.usd` 실제 형태** | 위험 3(`Price.usd == null` 크래시) 사전 확인. VOO 보유 계좌이므로 `usd`가 채워져 있을 것 |

> 발급된 토큰을 `data/cache/token.json` 형식(`{"access_token": ..., "expires_at": ...}`)으로 저장해두면 Phase 6에서 재발급 없이 재사용된다. **토큰은 client당 1개뿐이므로 (`API_DESIGN §2.3`) 불필요한 재발급을 지금부터 아낀다.**

### 관문 S

`/accounts`가 200을 반환하고 `accountSeq`를 얻었다.

**실패 시 분기**

| 증상 | 처리 |
|---|---|
| 401/403 (IP 관련) | 콘솔에서 현재 공인 IP 재확인 → 재등록. 해결 안 되면 **즉시 사용자에게 보고**하고 남은 일정을 목업 기준으로 재계획 |
| `account-not-found` | 계좌 개설/권한 상태 확인. 해결 안 되면 목업 기준 진행 |
| 그 외 | Phase 6까지 미룰 수 있으므로 기록만 남기고 Phase 1로 진행 |

---

## 5. Phase 1 — `models/` (엄격 TDD)

| ID | 테스트 파일 | 구현 파일 | 완료 조건 | 요구사항 |
|---|---|---|---|---|
| T-1.1 | `tests/test_models.py` **(먼저)** | — | 전부 실패 확인 (Red) | — |
| T-1.2 | — | `models/holding.py` `portfolio.py` `metrics.py` `stock_meta.py` `commentary.py` `dashboard.py` | `pytest tests/test_models.py` 통과 | FR-105, FR-106a, FR-106b, FR-703 |

### T-1.1 필수 테스트 케이스

근거: `DATA_DESIGN §2`, `§6`

| # | 대상 | 케이스 | 기대 |
|---|---|---|---|
| 1 | `Portfolio.account_no` | `"12345678901"` | `"*******8901"` (FR-105) |
| 2 | `Portfolio.account_no` | `"123"` (4자리 이하 경계) | `"***"` |
| 3 | **`StockMeta`** | `security_type="CRYPTO_ETP"` (미지의 값) | **ValidationError 없이 통과** (FR-106b) ★ |
| 4 | `Holding.market_value_krw` | USD 종목 + `fx_rate=None` | `None` (예외 아님) |
| 5 | `Holding.market_value_krw` | KRW 종목 + `fx_rate=None` | 정상 금액 |
| 6 | `Holding.unrealized_pnl_pct` | `avg_price=0` | `0.0` (ZeroDivision 아님) |
| 7 | `Holding.quantity` | 음수 | ValidationError |
| 8 | `Portfolio.cash_total_krw` | `fx_rate=None` | KRW 현금만 반환 |
| 9 | `Portfolio.total_value` | USD 종목 + `fx_rate=None` | 해당 종목 제외하고 합산 |
| 10 | `Commentary` | 5문장 | ValidationError (`max_length=4`, FR-703) |
| 11 | `CorrelationMatrix` | 비정방 행렬 | ValidationError |
| 12 | `RiskMetrics` | 전 필드 미지정 | 전부 `None`으로 생성 성공 (FR-407) |

> ★ 3번이 가장 중요하다. `market`·`security_type`을 `StrEnum`으로 파싱하면 토스증권이 값을 하나 추가하는 순간 앱 전체가 죽는다. **모델에는 `str`로 담는다** (`DATA_DESIGN §5.4`).

### 관문 1

```bash
pytest tests/test_models.py -v
```

---

## 6. Phase 2 — `config.py`

| ID | 테스트 파일 | 구현 파일 | 완료 조건 | 요구사항 |
|---|---|---|---|---|
| T-2.1 | `tests/test_config.py` | — | Red | — |
| T-2.2 | — | `config.py` (TRD §5.3 그대로) | 통과 | NFR-301 |

### 필수 테스트

| # | 케이스 | 기대 |
|---|---|---|
| 1 | `.env` 없이 `Settings()` | 예외 없이 생성 (기본값 사용) |
| 2 | 자격증명 없을 때 `has_broker_credentials` | `False` |
| 3 | 기본값 | `lookback_days=126`, `benchmark_symbol="KOSPI"`, `risk_free_symbol="KR_BOND_3Y"`, `risk_free_rate_fallback=0.03`, `use_mock_data=False` |

### 관문 2

`.env`가 없는 상태에서 `python -c "from config import settings; print(settings.has_broker_credentials)"` → `False` 출력

---

## 7. Phase 3 — `analytics/` (엄격 TDD, 핵심) ★

> **이 프로젝트에서 가장 중요한 Phase다.** 순수 함수라 정답이 존재하고, 발표에서 "직접 계산했다"고 말할 근거가 여기서 나온다 (`TRD §2.4`).

각 Task는 **테스트 → 구현** 쌍이다.

| ID | 테스트 파일 | 구현 파일 | 기댓값 출처 | 요구사항 |
|---|---|---|---|---|
| T-3.1 | `tests/test_risk_metrics.py` | `analytics/risk_metrics.py` | `DATA_DESIGN §4.1~4.6` | FR-401~406 |
| T-3.2 | `tests/test_returns.py` | `analytics/returns.py` | `DATA_DESIGN §4.7` | FR-205 |
| T-3.3 | `tests/test_allocation.py` | `analytics/allocation.py` | `DATA_DESIGN §2.5`, `§6` | FR-304 |
| T-3.4 | `tests/test_classifier.py` | `analytics/classifier.py` | `DATA_DESIGN §5.3` | FR-301~303 |
| T-3.5 | `tests/test_correlation.py` | `analytics/correlation.py` | `DATA_DESIGN §4.8` | FR-501, FR-504 |

### T-3.1 — 지표 6종

`DATA_DESIGN §4.1~4.6`의 "테스트 케이스" 표를 **그대로** 테스트로 옮긴다. 추가로 아래를 반드시 포함한다.

| # | 테스트 | 이유 |
|---|---|---|
| ★1 | **AT-11 단위 가드** — `sharpe_ratio(returns, risk_free_rate=3.25)` 호출 시 `abs(결과) > 10`이면 **테스트 실패** | 위험 2. 무위험수익률을 `/100` 안 하면 샤프가 `-17` 같은 값이 된다 (FR-402a) |
| 2 | 공통 경계 — 빈 시계열 `[]` | 전 함수 `None` 반환 (예외 아님) |
| 3 | 공통 경계 — 단일 데이터포인트 | 전 함수 `None` |
| 4 | 공통 경계 — 분산 0 (`[0.0]*100`) | 변동성 `0.0`, 샤프 `None` (0으로 나누지 않음) |
| 5 | 공통 경계 — 전부 NaN | `None` |
| 6 | 공통 경계 — 결측치 포함 | `dropna()` 후 정상 계산 |
| 7 | `historical_var` — 19개 데이터 | `None` (최소 20개 요건) |
| 8 | `beta` — 벤치마크 무변동 | `None` (0으로 나누지 않음) |

### T-3.4 — 분류기 (경로가 많아 테스트가 가장 많다)

`DATA_DESIGN §5.3`의 7단계 알고리즘. 각 단계마다 최소 1개.

| # | 입력 | 기대 자산군 | 검증하는 단계 |
|---|---|---|---|
| 1 | `overrides`에 있는 종목코드 | 오버라이드 값 | 1단계 (최우선) |
| 2 | `meta=None` + `marketCountry="KR"` | 국내주식 | 2단계 축약 (FR-301c) |
| 3 | `meta=None` + `marketCountry="US"` | 해외주식 | 2단계 축약 |
| 4 | `securityType="REIT"` | 리츠 | 3단계 |
| 5 | `securityType="ETF"` + 이름 `"KOSEF 국고채10년"` | **채권** | 4단계 키워드 ★ |
| 6 | `securityType="ETF"` + 이름 `"KODEX 골드선물"` | **원자재** | 4단계 키워드 ★ |
| 7 | `securityType="ETF"` + 키워드 미매치 + `market="KOSPI"` | 국내주식 | 4단계 폴백 |
| 8 | `securityType="FOREIGN_STOCK"` | 해외주식 | 5단계 |
| 9 | `market="KOSPI"`, `securityType="STOCK"` | 국내주식 | 6단계 |
| 10 | **`securityType="CRYPTO_ETP"` (미지의 값)** | **기타** (예외 없음) | 7단계 (FR-303) |
| 11 | `asset_class_map.yaml` 파일 없음 | 기본 분류기 동작, 예외 없음 | UC-06 흐름 C |
| 12 | YAML 문법 오류 | 동일 | UC-06 흐름 C |

> ★ 5·6번이 발표 서사를 지탱한다. 샘플 포트폴리오의 ETF 2종이 채권·원자재로 갈라져야 자산군이 5개가 되고, 그래야 히트맵이 의미를 갖는다.

### T-3.3 / T-3.5 추가 필수 케이스

| 대상 | 케이스 | 기대 |
|---|---|---|
| `allocation` | 비중 합계 | `1.0 ± 0.001` (FR-304) |
| `allocation` | 정렬 | 비중 **내림차순** (범례 순서 일치, FR-306) |
| `allocation` | `fx_rate=None` + USD 종목 | USD 제외 후 **재정규화**, 합계 여전히 1.0 (UC-11) |
| `correlation` | 대각 원소 | `1.00` |
| `correlation` | 자산군 1개 | `None` 반환 (예외 아님, FR-504) |
| `correlation` | **현금 자산군 포함** | 현금은 **제외**됨 (분산 0 → NaN 방지) |
| `returns` | 비중 딕셔너리 합이 1이 아님 | 재정규화 후 계산 |
| `returns` | 교집합 종목 없음 | 빈 `Series` (예외 아님) |

### 관문 3 ★

```bash
pytest tests/ -v --cov=analytics --cov-report=term-missing
```

**커버리지 ≥ 80%** (NFR-402, AT-07). 미달이면 Phase 4로 넘어가지 않는다.

---

## 8. Phase 4 — 목업 클라이언트 + 샘플 데이터

> `TRD §11`이 이 Phase를 실제 API보다 먼저 두는 이유: 실계좌 연동이 막혀도 Phase 7·8이 진행된다.

| ID | 테스트 파일 | 구현 파일 | 완료 조건 | 요구사항 |
|---|---|---|---|---|
| T-4.1 | — | `data/sample_portfolio.json` | `DATA_DESIGN §7` 구조 그대로 | FR-104 |
| T-4.2 | — | `api/base.py` (`BrokerClient` Protocol) | `API_DESIGN §1.1` 6개 메서드 | NFR-404 |
| T-4.3 | — | `api/mock_client.py` | `Portfolio(is_fallback=True)` 반환 | FR-104 |
| T-4.4 | `tests/test_mock_client.py` | — | **아래 관문 통과** | — |

### T-4.4 — 발표 서사 보증 관문 ★

이 테스트가 통과해야 발표가 성립한다.

| # | 검증 | 기대 |
|---|---|---|
| 1 | 샘플 → `Portfolio` 변환 | 성공, `is_fallback=True` |
| 2 | **자산군 개수** | **5개** (국내주식·해외주식·채권·현금·원자재) |
| 3 | 상관행렬 크기 | **2×2 이상** (히트맵이 그려질 수 있음) |
| 4 | 비중 합계 | `1.0 ± 0.001` |
| 5 | ETF 하위분류 | `148070` → 채권, `132030` → 원자재 |

> **가격 히스토리는 샘플에 넣지 않는다.** 목업 클라이언트도 `/candles`는 실제로 호출한다 (샘플 종목이 실존). 네트워크까지 끊긴 경우는 Phase 10의 캐시가 처리한다 (`DATA_DESIGN §7`).

### 관문 4

```bash
pytest tests/test_mock_client.py -v
```

---

## 9. Phase 5 — `api/` 인프라

| ID | 테스트 파일 | 구현 파일 | 완료 조건 | 요구사항 |
|---|---|---|---|---|
| T-5.1 | `tests/test_errors.py` | `api/errors.py` | 예외 계층 + 코드 매핑 | NFR-206, NFR-304 |
| T-5.2 | `tests/test_token_store.py` | `api/token_store.py` | 만료 판정 + 손상 복원 | FR-101a, NFR-306 |
| T-5.3 | `tests/test_throttle.py` | `api/throttle.py` | 헤더 파싱 + 대기 | FR-201b, NFR-105 |

### 필수 테스트

**T-5.1 `errors`** (`TRD §7.1`, `API_DESIGN §12.2`)

| 케이스 | 기대 |
|---|---|
| `"expired-token"` | `AuthenticationError` |
| `"rate-limit-exceeded"` | `RateLimitError` |
| `"maintenance"` | `MaintenanceError` |
| `"account-not-found"` | `AccountNotFoundError` |
| **`"완전히-새로운-코드"`** | **`BrokerAPIError`** (예외 없이 처리, NFR-206) ★ |

**T-5.2 `token_store`** (`API_DESIGN §2.3`)

| 케이스 | 기대 |
|---|---|
| 파일 없음 | `None` |
| 만료 60초 이상 남음 | 토큰 반환 |
| 만료 30초 남음 (`SAFETY_MARGIN=60`) | `None` (재발급 유도) |
| JSON 손상 | `None` (예외 아님) |
| 키 누락 | `None` |
| **Windows에서 `save_token`** | **`chmod` 실패해도 저장 성공** ★ |

> ★ `chmod(0o600)`은 POSIX 전용이다. `try/except (NotImplementedError, OSError)`로 감싸 조용히 스킵한다 (`README.md` 알려진 단순화).

**T-5.3 `throttle`**

| 케이스 | 기대 |
|---|---|
| `X-RateLimit-Remaining: 5` 파싱 | 내부 상태 갱신 |
| 헤더 없음 | 예외 없이 무시 |
| 헤더 값이 숫자가 아님 | 예외 없이 무시 |
| `remaining <= 1` | `before()`가 대기 |

### 관문 5

```bash
pytest tests/test_errors.py tests/test_token_store.py tests/test_throttle.py -v
```

---

## 10. Phase 6 — `api/toss_client.py`

| ID | 테스트 파일 | 구현 | 완료 조건 | 요구사항 |
|---|---|---|---|---|
| T-6.1 | `tests/test_toss_mapping.py` | 응답 → 모델 매핑 함수 | mock 응답으로 통과 | FR-106a, FR-102b |
| T-6.2 | (mock 확장) | `_request` 래퍼 | 재시도 정책 검증 | FR-101b, NFR-202 |
| T-6.3 | — | `bootstrap()` + `fetch_portfolio()` | **실계좌 잔고 조회 성공** | FR-101~103 |
| T-6.4 | — | candles · benchmark · 국채 · 종목메타 | DataFrame 반환 | FR-201~207, FR-301a |

### T-6.1 필수 테스트 (mock 응답 사용, 네트워크 금지)

| # | 케이스 | 기대 |
|---|---|---|
| 1 | `"quantity": "100"` (문자열) | `Decimal("100")` — `float()` 사용 금지 (FR-106a) |
| 2 | **`marketValue.amount.usd == null`** | **예외 없이 `Decimal(0)`** ★ 위험 3 |
| 3 | `marketValue.amount.usd` 필드 자체 없음 | 동일 |
| 4 | 필수 키 누락된 종목 1건 | 해당 종목만 `None` 반환, 나머지 정상 |
| 5 | `lastPrice`가 파싱 불가 문자열 | 해당 종목만 스킵 + 경고 |
| 6 | `fetch_risk_free_rate` — `lastPrice="3.25"` | **`0.0325`** ★ 위험 2 (`/100`) |
| 7 | `fetch_risk_free_rate` — 빈 배열 | `None` |

### T-6.2 필수 테스트 (`API_DESIGN §12.3`)

| # | 케이스 | 기대 |
|---|---|---|
| 1 | 401 → 재발급 → 성공 | 토큰 재발급 **1회만** (FR-101b) |
| 2 | **401 → 재발급 → 또 401** | **재발급 안 하고 `AuthenticationError`** ★ (UC-12 5a) |
| 3 | 429 + `Retry-After: 2` | 2초 대기 후 재시도 |
| 4 | 500 `maintenance` | 재시도 **없이** 즉시 예외 |
| 5 | 400 `unsupported-symbol` | 재시도 없이 예외 |
| 6 | 500 `internal-error` | 지수 백오프 재시도 |
| 7 | 실패 시 로그 | `X-Request-Id` 포함 (NFR-205) |

> ★ 2번이 위험 1(토큰 무효화 루프)의 방어선이다. 루프가 생기면 자기 토큰을 계속 죽이며 `AUTH` 레이트리밋만 소모한다.

### 관문 6 ★★

```bash
# 1회차
python -c "from api.toss_client import ...; print(client.fetch_portfolio())"
# 2회차 — 로그에 POST /oauth2/token 이 없어야 한다
python -c "from api.toss_client import ...; print(client.fetch_portfolio())"
```

- [ ] 실계좌(VOO) 잔고가 조회된다
- [ ] **2회차에 토큰 재발급이 없다** (AT-09)
- [ ] 계좌번호가 마스킹되어 출력된다 (AT-08)

---

## 11. Phase 7 — `services/`

| ID | 구현 파일 | 완료 조건 | 요구사항 |
|---|---|---|---|
| T-7.1 | `services/dashboard_service.py` | `COMPONENT_DESIGN §2.1` 10단계 | 전체 |
| T-7.2 | `create_broker_client()` 선택 로직 | `API_DESIGN §1.3` | FR-104 |

### T-7.1 — 단계별 실패 격리

`COMPONENT_DESIGN §2.2`의 표를 **각 `_load_*` 메서드의 완료 조건**으로 삼는다. 각 메서드는 **자체 try/except를 갖고 `None` 또는 부분값을 반환한다. 예외를 상위로 전파하지 않는다** (NFR-201).

| 단계 | 실패 시 반환 | 검증 방법 |
|---|---|---|
| 1 환율 | `None` | 해당 호출을 예외로 monkeypatch → 앱 진행 확인 |
| 2 포트폴리오 | 목업 폴백 | `.env` 제거 후 실행 |
| 3 종목 메타 | `{}` | 동일 |
| 4 자산배분 | (실패 불가) | — |
| 5 무위험수익률 | 기본값 + `source="fallback"` | 동일 |
| 6 가격 히스토리 | `None` | 동일 |
| 7~10 | 개별 `None` | 동일 |

### 관문 7 ★★★ — **Day 1 종료 조건**

```bash
python -c "from services.dashboard_service import DashboardService; from config import settings; d = DashboardService(settings).load(); print(d.metrics); print(d.allocation)"
```

- [ ] 실제 리스크 지표가 숫자로 출력된다
- [ ] **샤프지수 절댓값이 10 미만이다** (AT-11 — 위험 2 최종 검증)
- [ ] 자산배분 비중 합계가 100% ± 0.1%p
- [ ] 어떤 예외도 위로 전파되지 않는다

> 여기까지 오면 **UI 없이도 프로젝트의 본질이 완성**된 것이다. Day 2는 이것을 보여주는 작업이다.

---

## 12. Phase 8 — `ui/` + `app.py` (Day 2)

| ID | 테스트 파일 | 구현 파일 | 우선순위 | 요구사항 |
|---|---|---|---|---|
| T-8.1 | `tests/test_format.py` **(TDD)** | `ui/format.py` | P0 | FR-806 |
| T-8.2 | — | `ui/theme.py` + `ui/styles.css` | P0 | — |
| T-8.3 | — | `metric_cards.py` · `allocation_chart.py` · `risk_table.py` | P0 | FR-305~306, FR-408~409 |
| T-8.4 | — | **`correlation_heatmap.py`** | **필수** ★ | FR-502~504 |
| T-8.5 | — | `app.py` 조립 | P0 | FR-801~803 |
| T-8.6 | — | `benchmark_chart.py` | P1 (**컷 1순위**) | FR-601~603 |

### T-8.1 필수 테스트

| 케이스 | 기대 |
|---|---|
| `fmt_krw(None)` / `fmt_pct(None)` / `fmt_num(None)` | 전부 `"N/A"` (FR-407) |
| `fmt_krw(Decimal("1234567.89"))` | `"₩1,234,568"` (반올림, 콤마) |
| `fmt_pct(0.30000000000000004)` | `"30.0%"` — 부동소수점 잔여값 노출 금지 |
| `fmt_pct(-0.124)` | `"-12.4%"` |

### 구현 시 함정

| 파일 | 주의 |
|---|---|
| `allocation_chart.py` | **`sort=False`** — Plotly 기본 정렬이 켜지면 범례와 슬라이스 순서가 어긋난다 |
| `correlation_heatmap.py` | **`zmin=-1, zmax=1` 고정** — 자동 스케일이면 포트폴리오 간 비교가 불가능 |
| `benchmark_chart.py` | 색상만이 아닌 **실선/점선**으로도 구분 (FR-603, NFR-503) |
| `metric_cards.py` | `delta_color="inverse"` — 손실=빨강 (FR-805) |
| `app.py` | **80줄 내외.** 넘으면 로직이 샌 것이므로 `services/`나 `ui/`로 옮긴다 |
| 전 컴포넌트 | 숫자는 **반드시 `ui/format.py` 3함수를 거친다.** f-string 직접 포맷 금지 |

> ★ T-8.4는 문서상 P1이지만 **발표 핵심 장면**이라 컷하지 않는다 (`PRD §10 Q7`, `USE_CASES` 부록B 2:00~3:00).

### 관문 8

```bash
streamlit run app.py
```

- [ ] 6개 블록이 목업 순서대로 렌더링된다 (FR-801)
- [ ] 데이터 기준 시각이 헤더에 있다 (FR-802)
- [ ] 샘플 데이터일 때 폴백 배지가 보인다 (FR-803)
- [ ] `N/A`가 아닌 숫자가 리스크표에 채워진다

---

## 13. Phase 9 — `ai/`

| ID | 테스트 파일 | 구현 파일 | 완료 조건 | 요구사항 |
|---|---|---|---|---|
| T-9.1 | `tests/test_prompts.py` | `ai/prompts.py` | 페이로드 생성 검증 | NFR-305 |
| T-9.2 | `tests/test_fallback.py` | `ai/fallback.py` | 규칙 기반 문장 생성 | FR-705 |
| T-9.3 | — | `ai/commentary.py` | Claude API 호출 + 폴백 | FR-701~709 |
| T-9.4 | — | `ui/ai_banner.py` | 배너 + 고지문 | FR-706, FR-708 |

### T-9.1 필수 테스트 ★

| # | 검증 | 기대 |
|---|---|---|
| 1 | **페이로드에 계좌번호 없음** | 문자열 어디에도 미포함 (NFR-305) ★ |
| 2 | **페이로드에 개별 종목명 없음** | 집계된 자산군 비중만 |
| 3 | 페이로드에 개별 수량 없음 | 동일 |
| 4 | `fx_note` 포함 | 환율 단순화 고지 |
| 5 | `risk_free_source` 포함 | LLM이 기본금리 여부를 인지 |

### T-9.2 필수 테스트 (`USE_CASES` UC-04 표)

| 조건 | 기대 문장 |
|---|---|
| 최대 비중 > 40% | 집중도 언급 문장 생성 |
| 변동성 계산 가능 | 수치 인용 문장 |
| 지표가 전부 `None` | `"리스크 지표를 계산하기에 데이터가 충분하지 않습니다."` |
| 결과 | 항상 1~4문장, `source="fallback"` |

### T-9.3 구현 요건

| 항목 | 값 | 근거 |
|---|---|---|
| 타임아웃 | **10초** | NFR-104 |
| 실패 시 | 재시도 **없이** 즉시 폴백 | FR-705, UC-04 |
| JSON 파싱 | 마크다운 코드펜스 제거 후 파싱, 실패 시 폴백 | FR-704 |
| 문장 수 | 4문장 초과 시 앞 4개만 | FR-703 |
| 캐싱 | 지표 해시 키 | FR-709 |

> **모델 ID (2026-08-26 확정)**: `API_DESIGN §15.1`을 `MODEL = "claude-sonnet-5"`로 변경 완료. 3문장 생성이라는 단순 작업에 더 저렴한($2/$10 vs $3/$15 per MTok) 최신 모델을 쓴다.

### 관문 9

- [ ] AI 코멘트가 **실제 계산값을 인용**한다 (FR-702)
- [ ] 고지문이 화면에 있다 (FR-708)
- [ ] `ANTHROPIC_API_KEY` 제거 후 실행 → **규칙 기반 코멘트 표시 + 배지 구분** (AT-04)

---

## 14. Phase 10 — 오프라인 + 리허설

| ID | 구현 | 완료 조건 | 요구사항 |
|---|---|---|---|
| T-10.1 | `api/cached_client.py` + `last_successful.json` | `schema_version` 불일치 시 캐시 무시 | FR-107, NFR-203 |
| T-10.2 | 루트 `README.md` | **알려진 단순화 5종 명시** | `docs/README.md` 참조 |
| T-10.3 | AT-01~AT-13 전수 실행 | 전부 통과 | REQUIREMENTS §5 |
| T-10.4 | 시연 리허설 | 1회 완주 | USE_CASES 부록B |

### T-10.2 — 루트 README에 반드시 적을 5가지

1. 환율: 조회 시점 `midRate` 단일값 → **환율 변동 리스크 미반영**
2. 현금: `cashBuyingPower`는 예수금이 아닌 **매수가능금액**
3. 비중: 현재 비중을 과거 전 기간에 고정 (**buy-and-hold 가정**)
4. ETF 분류: 종목명 키워드 기반 (오분류 시 `config/asset_class_map.yaml` 수정 안내)
5. 계산 기간: 최근 126 거래일 고정

### 관문 10 — 최종

`REQUIREMENTS §4.3` P0 체크리스트 전체 + 아래

- [ ] AT-01 유효 `.env` → 실계좌 렌더링
- [ ] AT-02 `.env` 삭제 → 샘플 + 배지
- [ ] AT-03 **Wi-Fi 끄고 실행** → 캐시 + 오프라인 배지
- [ ] AT-09 2회 연속 실행 → 토큰 재발급 없음
- [ ] AT-11 샤프지수 절댓값 10 미만
- [ ] 시연 리허설 1회 완주 (샘플 메인 → 실계좌 보조 → 오프라인)

---

## 부록 A. 컷 라인 (시간 부족 시 버리는 순서)

일정이 촉박하므로 **미리 정해둔다.** 실시간으로 판단하면 반드시 잘못된 것을 버린다.

| 순위 | 버리는 것 | 잃는 것 | 대체 |
|---|---|---|---|
| **1** | T-8.6 벤치마크 라인차트 + FR-405 베타 | 시연 대본에 없는 보조 시각자료 | 리스크표에 베타 `N/A` 표시 |
| **2** | FR-804 새로고침 버튼 | UC-08만 소실 | 브라우저 새로고침으로 대체 |
| **3** | T-10.1 오프라인 캐시 (UC-03) | 시연 마무리 45초 | AT-02(샘플 폴백) 시연으로 대체 — **같은 "안 죽는다" 메시지**를 전달 |

### 🔴 절대 컷 불가

| 항목 | 이유 |
|---|---|
| P0 요구사항 전체 | 데모 성립 조건 |
| **FR-501~504 히트맵** | 발표 핵심 장면 (`PRD §10 Q7`) |
| **AT-09** (토큰 재발급 없음) | 위험 1 검증 |
| **AT-11** (샤프 단위) | 위험 2 검증 |
| **T-6.1 #2** (`Price.usd` 널 가드) | 위험 3 검증 |
| Phase 3 커버리지 80% | AT-07, 발표 시 "직접 계산했다"의 근거 |

---

## 부록 B. P0 요구사항 → Phase-Task 역인덱스

`REQUIREMENTS §4.3` P0 체크리스트를 Phase-Task에 매핑한다. **구현 후 빠뜨린 P0를 기계적으로 찾기 위한 표다.**

| 요구사항 | Phase-Task |
|---|---|
| FR-101, FR-101a, FR-101b | T-5.2, T-6.2, T-6.3 |
| FR-102, FR-102a, FR-102b | T-6.3 |
| FR-103, FR-103a | T-6.3 |
| FR-104 | T-4.1, T-4.3, T-7.2 |
| FR-105 | T-1.1 #1·#2, T-1.2 |
| FR-106 | (구현 금지 — 코드베이스에 경로 문자열 부재로 검증) |
| FR-106a | T-1.1 #1, T-6.1 #1 |
| FR-106b | T-1.1 #3, T-3.4 #10 |
| FR-201, FR-201a, FR-201b | T-6.4 |
| FR-202, FR-202a | T-6.4, T-3.3 (fx=None 재정규화) |
| FR-204 | T-6.4, T-7.1 |
| FR-205 | T-3.2, T-6.4 |
| FR-206, FR-207 | T-6.1 #6·#7, T-7.1 단계5 |
| FR-301, FR-301a, FR-301b, FR-301c | T-3.4, T-6.4 |
| FR-302, FR-303 | T-3.4 #1·#10·#11·#12 |
| FR-304 | T-3.3 |
| FR-305, FR-306 | T-8.3 |
| FR-401~404 | T-3.1 |
| FR-402a | **T-3.1 ★1**, 관문 7 |
| FR-407 | T-1.1 #12, T-8.1 |
| FR-408, FR-409 | T-8.3 |
| FR-501~504 | T-3.5, T-8.4 |
| FR-701~705, FR-707 | T-9.1~9.3 |
| FR-708, FR-709 | T-9.3, T-9.4 |
| FR-801~803, FR-806 | T-8.1, T-8.5 |
| NFR-101, NFR-105 | T-5.3, T-6.4, 관문 7 |
| NFR-201 | T-7.1 (전 단계 try/except) |
| NFR-202 | T-6.2 |
| NFR-301, NFR-302 | T-0.2 |
| NFR-306 | T-5.2 (Windows 완화) |
| NFR-401 | T-3.1~3.5 (I/O 없음) |
| NFR-501 | 관문 8 |

---

## 부록 C. 위험 3종의 방어 위치

`docs/README.md`의 "위험 지점 3가지"가 어느 Task에서 방어되는지.

| 위험 | 방어 Task | 검증 관문 |
|---|---|---|
| 1. 토큰 재발급이 이전 토큰 무효화 | T-5.2, **T-6.2 #2** | **관문 6** (2회 실행) |
| 2. 무위험수익률 단위 | T-6.1 #6, **T-3.1 ★1** | **관문 7** (샤프 절댓값<10) |
| 3. `Price.usd`가 `null` | **T-6.1 #2·#3** | Phase S #5 (실응답 사전 확인) |

---

## 부록 D. 갱신 기록

| 날짜 | 버전 | 변경 내용 |
|---|---|---|
| 2026-08-26 | 1.0 | 초안. `TRD §11` 10단계를 TDD Phase-Task 11개로 전개. Phase S(실계좌 스모크) 신설, 컷 라인·역인덱스 부록 추가 |
