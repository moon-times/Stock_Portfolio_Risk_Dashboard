# TRD — 포트폴리오 리스크 대시보드

| 항목 | 내용 |
|---|---|
| 문서 버전 | 2.0 (실제 API 스펙 반영) |
| 최종 수정 | 2026-08-26 |
| 선행 문서 | `docs/PRD.md` |
| 대상 | Claude Code (구현 주체) |

---

## 1. 아키텍처 개요

### 1.1 레이어 구조

```
┌──────────────────────────────────────────────────┐
│  Presentation Layer  (Streamlit)                 │
│  app.py + ui/                                     │
│  · 레이아웃, 위젯, Plotly 차트 렌더링             │
│  · 비즈니스 로직 없음 (표시만)                    │
└───────────────────────┬──────────────────────────┘
                        │ Portfolio, RiskMetrics, Commentary
┌───────────────────────▼──────────────────────────┐
│  Service Layer  (services/)                       │
│  · 조회 → 계산 → 진단 오케스트레이션              │
│  · 캐싱, 폴백 판단                                │
└──────┬─────────────────┬────────────────┬────────┘
       │                 │                │
┌──────▼──────┐  ┌───────▼──────┐  ┌──────▼───────┐
│ API Layer   │  │ Analytics    │  │ AI Layer     │
│ api/        │  │ analytics/   │  │ ai/          │
│ 토스증권    │  │ 리스크 지표  │  │ Claude API   │
│ (단일 소스) │  │ 순수 함수    │  │ 프롬프트     │
└─────────────┘  └──────────────┘  └──────────────┘
       │
┌──────▼──────────────────────────────────────────┐
│  Domain Models  (models/)  — Pydantic            │
│  Holding, Portfolio, RiskMetrics, Commentary     │
└─────────────────────────────────────────────────┘
```

### 1.2 핵심 설계 원칙

| 원칙 | 의미 | 구현 규칙 |
|---|---|---|
| **어댑터 격리** | 외부 API 응답 구조 변경이 앱 전체로 번지지 않는다 | 토스증권 응답은 `api/` 안에서만 다루고, 밖으로는 항상 Pydantic 모델로 나간다 |
| **계산 순수성** | 리스크 계산 함수는 네트워크·시간·전역상태에 의존하지 않는다 | `analytics/`의 모든 함수는 `pd.Series`/`pd.DataFrame`을 받아 값을 반환. I/O 금지 |
| **UI 무지성** | UI는 계산하지 않는다 | `ui/` 안에서 `numpy`/`scipy` 연산 금지. 받은 값을 포맷팅만 |
| **폴백 우선** | 어떤 외부 의존이 죽어도 화면은 뜬다 | 모든 외부 호출은 try/except + 폴백 경로 필수 |

---

## 2. 기술 스택 확정

### 2.1 런타임

| 항목 | 선택 | 사유 |
|---|---|---|
| 언어 | Python 3.11+ | Pydantic v2 성능, `match` 문법 |
| 패키지 관리 | `uv` | 설치 속도. 없으면 `venv` + `pip` 폴백 |
| 실행 방식 | 로컬 `streamlit run app.py` | PRD 비목표: 클라우드 배포 없음 |

### 2.2 의존성

```txt
# requirements.txt

# --- GUI ---
streamlit>=1.40
plotly>=5.24

# --- 데이터 조회 ---
httpx>=0.27
python-dotenv>=1.0
pyyaml>=6.0

# --- 분석 ---
pandas>=2.2
numpy>=2.0
scipy>=1.14

# --- 도메인 모델 ---
pydantic>=2.9
pydantic-settings>=2.5

# --- AI ---
anthropic>=0.40

# --- 개발 ---
pytest>=8.3
pytest-cov>=5.0
ruff>=0.7
```

### 2.3 GUI 프레임워크 결정: Streamlit

PyQt6 대비 Streamlit을 선택한 근거를 기록한다 (ADR 성격).

| 기준 | PyQt6 | Streamlit | 판정 |
|---|---|---|---|
| 2일 내 완성 가능성 | 이벤트 루프·시그널/슬롯 보일러플레이트 | 선언형, 수십 줄로 대시보드 | **Streamlit** |
| 차트 통합 | `FigureCanvas`/`pyqtgraph` 수동 배선 | `st.plotly_chart()` 한 줄 | **Streamlit** |
| 비동기 API 호출 | `qasync` 등 추가 배선 필요 | 동기 호출 + `st.cache_data` | **Streamlit** |
| 시연 편의 | PyInstaller 패키징 필요 | 브라우저 화면 공유 | **Streamlit** |
| 상태 관리 | 수동 갱신 로직 작성 | 위젯 변경 시 자동 재실행 | **Streamlit** |

> **결정**: Streamlit. 이 결정은 되돌리지 않는다. Claude Code는 PyQt 코드를 생성하지 않는다.

### 2.4 quantstats를 쓰지 않는 이유

리스크 지표 계산에 `quantstats` 사용을 검토했으나 **직접 구현**으로 결정한다.

- 라이브러리가 무거우며 matplotlib에 강하게 결합되어 Plotly 기반 UI와 충돌
- 필요한 지표는 6종뿐이고 각각 5줄 이내로 구현 가능
- 직접 구현해야 단위 테스트로 정확성을 검증할 수 있고, 발표 시 "직접 계산했다"는 설명이 가능

수식은 `docs/design/DATA_DESIGN.md` §4에 정의한다.

---

## 3. 디렉토리 구조

```
portfolio-risk-dashboard/
├── app.py                        # Streamlit 엔트리포인트 (레이아웃만)
├── config.py                     # pydantic-settings 설정 로더
├── .env.example                  # 키 템플릿 (실제 .env는 gitignore)
├── .gitignore
├── requirements.txt
├── README.md
│
├── models/                       # 도메인 모델 (Pydantic)
│   ├── __init__.py
│   ├── holding.py                # Holding, AssetClass
│   ├── portfolio.py              # Portfolio
│   ├── metrics.py                # RiskMetrics, CorrelationMatrix
│   ├── stock_meta.py             # StockMeta (market, securityType)
│   └── commentary.py             # Commentary
│
├── api/                          # 외부 데이터 조회 (어댑터)
│   ├── __init__.py
│   ├── base.py                   # BrokerClient 프로토콜
│   ├── toss_client.py            # 토스증권 Open API 구현
│   ├── token_store.py            # 토큰 디스크 영속화
│   ├── throttle.py               # 헤더 기반 적응형 스로틀
│   ├── errors.py                 # 에러코드 -> 예외 매핑
│   ├── mock_client.py            # 샘플 데이터 폴백 구현
│   └── cached_client.py          # 디스크 캐시 데코레이터
│
├── analytics/                    # 순수 계산 함수
│   ├── __init__.py
│   ├── returns.py                # 수익률 시계열 생성
│   ├── risk_metrics.py           # 변동성/샤프/MDD/VaR/베타/HHI
│   ├── allocation.py             # 자산배분 집계
│   ├── classifier.py             # 자산군 분류 (메타 + 키워드)
│   └── correlation.py            # 상관계수 행렬
│
├── ai/
│   ├── __init__.py
│   ├── commentary.py             # Claude API 호출
│   ├── prompts.py                # 프롬프트 템플릿
│   └── fallback.py               # 규칙 기반 폴백 코멘트
│
├── services/
│   ├── __init__.py
│   └── dashboard_service.py      # 조회→계산→진단 오케스트레이션
│
├── ui/
│   ├── __init__.py
│   ├── metric_cards.py           # 상단 메트릭 4개
│   ├── allocation_chart.py       # 도넛 차트
│   ├── risk_table.py             # 리스크 지표 테이블
│   ├── correlation_heatmap.py    # 히트맵
│   ├── benchmark_chart.py        # 라인 차트
│   ├── ai_banner.py              # AI 코멘트 배너
│   └── theme.py                  # 색상 상수, Plotly 공통 레이아웃
│
├── config/
│   └── asset_class_map.yaml      # 종목코드 → 자산군 매핑
│
├── data/
│   ├── cache/                    # API 응답 캐시 + token.json (gitignore)
│   └── sample_portfolio.json     # 폴백용 샘플 데이터
│
├── tests/
│   ├── test_risk_metrics.py
│   ├── test_allocation.py
│   ├── test_correlation.py
│   └── fixtures/
│       └── sample_returns.csv
│
└── docs/
    ├── PRD.md
    ├── TRD.md
    ├── REQUIREMENTS.md
    ├── assets/dashboard_mockup.png
    └── design/
        ├── DATA_DESIGN.md
        ├── API_DESIGN.md
        ├── COMPONENT_DESIGN.md
        └── USE_CASES.md
```

---

## 4. 데이터 흐름

```
[사용자] streamlit run app.py
    │
    ▼
[app.py] DashboardService.load() 호출
    │
    ├─(1)─▶ [api/token_store]  token.json 확인 → 유효하면 재사용
    │       [api/toss_client]  없으면 POST /oauth2/token          [AUTH]
    │
    ├─(2)─▶ GET /api/v1/accounts → accountSeq 해석                [ACCOUNT]
    │
    ├─(3)─▶ GET /api/v1/exchange-rate (USD→KRW midRate)      [MARKET_INFO]
    │
    ├─(4)─▶ GET /api/v1/holdings          (X-Tossinvest-Account)  [ASSET]
    │       GET /api/v1/buying-power ×2   (KRW, USD)         [ORDER_INFO]
    │           │ 실패 시 ──▶ [api/mock_client] 샘플 + 폴백 플래그
    │           ▼
    │       List[Holding] + cash → Portfolio
    │
    ├─(5)─▶ GET /api/v1/stocks?symbols=... (전 종목 1회)          [STOCK]
    │           ▼
    │       [analytics/classifier] market·securityType → AssetClass
    │
    ├─(6)─▶ GET /api/v1/market-indicators/prices?symbols=KR_BOND_3Y
    │           ▼                                        [MARKET_INDICATOR]
    │       risk_free_rate = lastPrice / 100
    │
    ├─(7)─▶ 종목별 GET /api/v1/candles (throttled)   [MARKET_DATA_CHART]
    │       GET /api/v1/market-indicators/KOSPI/candles
    │           │ USD 캔들은 midRate로 원화 환산
    │           ▼
    │       pd.DataFrame (index=date, columns=symbol)
    │
    ├─(8)─▶ [analytics/returns] 비중가중 포트폴리오 일간 수익률 시계열
    │           ▼
    │       pd.Series
    │
    ├─(9)─▶ [analytics/risk_metrics] 지표 6종 계산
    │       [analytics/allocation]   자산군별 집계
    │       [analytics/correlation]  상관계수 행렬
    │           ▼
    │       RiskMetrics, AllocationBreakdown, CorrelationMatrix
    │
    ├─(10)─▶ [ai/commentary] 지표를 JSON으로 직렬화 → Claude API
    │           │ 실패/타임아웃 시 ──▶ [ai/fallback] 규칙 기반 문장
    │           ▼
    │       Commentary
    │
    ▼
[ui/*] 각 컴포넌트가 받은 모델을 렌더링
```

**단방향 흐름이다.** UI에서 계산 레이어를 다시 호출하거나, analytics에서 API를 호출하는 역방향 의존은 금지한다.

(3)이 (4)보다 먼저인 이유: 환율이 있어야 통화별 합산과 USD 캔들 환산이 가능하다. 전체 호출 시퀀스는 `API_DESIGN.md §14`.

---

## 5. 설정 및 보안

### 5.1 `.env.example`

```bash
# 토스증권 Open API (OAuth2 Client Credentials)
TOSS_CLIENT_ID=c_01HXYZABCDEFG123456789
TOSS_CLIENT_SECRET=your_client_secret_here
# 계좌번호는 불필요. accountSeq를 GET /api/v1/accounts 로 런타임 해석한다.

# Anthropic API
ANTHROPIC_API_KEY=sk-ant-xxxxx

# 옵션
TOSS_BASE_URL=https://openapi.tossinvest.com
LOOKBACK_DAYS=126
BENCHMARK_SYMBOL=KOSPI              # 심볼 카탈로그 8종 중 하나
RISK_FREE_SYMBOL=KR_BOND_3Y         # 실시간 조회. 실패 시 아래 기본값 사용
RISK_FREE_RATE_FALLBACK=0.03
USE_MOCK_DATA=false
```

### 5.2 보안 규칙 (위반 시 즉시 수정)

| 규칙 | 내용 |
|---|---|
| S1 | API 키·시크릿·계좌번호를 소스코드에 하드코딩하지 않는다 |
| S2 | `.env`, `data/cache/`는 `.gitignore`에 반드시 포함한다 |
| S3 | 화면·로그에 계좌번호를 출력할 때는 마스킹한다 (`12345678901` → `*******8901`) |
| S4 | 예외 메시지에 토큰이 포함될 수 있으므로, 외부 API 예외는 원문 대신 요약 메시지로 변환해 표시한다 |
| S5 | 주문·조건주문 엔드포인트는 클라이언트에 **구현하지 않는다** (조회 전용). 금지 목록은 API_DESIGN §13 |
| S6 | `data/cache/token.json`은 권한 `0600`, `.gitignore` 필수. access token은 자격증명과 동등하게 취급한다 |

> **Windows 메모 (2026-08-26)**: `chmod(0o600)`은 POSIX 전용 API라 Windows에서는 효과가 없다. `try/except`로 감싸 조용히 무시하고, 실질 보호는 `.gitignore` + CON-04(단일 사용자 로컬 PC 전제)에 의존한다. 상세 코드는 `API_DESIGN.md §2.3`.

### 5.3 설정 로더

```python
# config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    toss_client_id: str = ""
    toss_client_secret: str = ""
    toss_base_url: str = "https://openapi.tossinvest.com"
    anthropic_api_key: str = ""

    lookback_days: int = 126
    benchmark_symbol: str = "KOSPI"
    risk_free_symbol: str = "KR_BOND_3Y"
    risk_free_rate_fallback: float = 0.03
    use_mock_data: bool = False

    @property
    def has_broker_credentials(self) -> bool:
        return bool(self.toss_client_id and self.toss_client_secret)

settings = Settings()
```

---

## 6. 캐싱 전략

| 대상 | 방식 | TTL | 사유 |
|---|---|---|---|
| 인증 토큰 | **디스크** (`data/cache/token.json`) | `expires_in` - 60초 | **재발급이 기존 토큰을 무효화**하므로 프로세스 재시작에도 살아남아야 함 |
| accountSeq | 메모리 (클라이언트 인스턴스) | 세션 | `/accounts` 반복 호출 방지 |
| 잔고/보유종목 | `@st.cache_data` | 300초 | Streamlit 재실행마다 API 호출 방지 |
| 종목 메타 | `@st.cache_data` + 디스크 | 86400초 | 시장·유형은 거의 안 바뀜 |
| 가격 히스토리 | `@st.cache_data` + 디스크 | 3600초 | 일봉이라 자주 안 바뀜. 20콜 절약이 큼 |
| 환율 | `@st.cache_data` | 60초 | API 갱신 주기와 동일 |
| 무위험수익률 | `@st.cache_data` | 3600초 | 국채 금리는 일 단위 변동 |
| AI 코멘트 | `@st.cache_data` (지표 해시 키) | 세션 내 | 동일 지표에 중복 과금 방지 |

> Streamlit은 위젯 상호작용마다 스크립트를 **처음부터 재실행**한다. 캐싱 없이는 슬라이더 한 번 움직일 때마다 API가 호출된다. 캐싱은 선택이 아니라 필수다.

### 6.1 오프라인 모드

`data/cache/last_successful.json`에 마지막 정상 응답을 저장한다. 네트워크 장애 시 이 파일을 읽어 재생하며, UI 상단에 `⚠ 오프라인 데이터 (2026-08-26 14:32 기준)` 배지를 띄운다. 발표장 네트워크 장애(PRD R3) 대응책이다.

---

## 7. 에러 처리

### 7.1 예외 계층

```python
class DashboardError(Exception): ...

class BrokerAPIError(DashboardError):        # 증권사 API 실패
    ...
class AuthenticationError(BrokerAPIError):   # 토큰 발급/검증 실패
    ...
class AccountNotFoundError(BrokerAPIError):  # 사용 가능 계좌 없음
    ...
class RateLimitError(BrokerAPIError):        # 429 호출 한도 초과
    ...
class MaintenanceError(BrokerAPIError):      # 500 maintenance (재시도 금지)
    ...
class ExchangeRateError(DashboardError):     # 환율 조회 실패
    ...
class PriceDataError(DashboardError):        # 가격 히스토리 조회 실패
    ...
class InsufficientDataError(DashboardError): # 계산에 필요한 데이터 부족
    ...
class AICommentaryError(DashboardError):     # LLM 호출 실패
    ...
```

### 7.2 처리 정책

| 예외 | 사용자에게 보이는 것 | 앱 동작 |
|---|---|---|
| `AuthenticationError` | "증권사 인증에 실패했습니다. 샘플 데이터로 표시합니다." | 목업 데이터로 계속 진행 |
| `RateLimitError` | "API 호출 한도에 도달했습니다. 캐시된 데이터를 표시합니다." | 캐시 재생 |
| `PriceDataError` | 해당 종목만 제외하고 경고 표시 | 나머지 종목으로 계산 |
| `InsufficientDataError` | 해당 지표만 `N/A` | 다른 지표는 정상 표시 |
| `AICommentaryError` | 규칙 기반 코멘트 표시 (배지로 구분) | 화면 유지 |

**어떤 예외도 앱을 죽이지 않는다.** `app.py` 최상단에 전역 try/except를 두어 예상치 못한 예외도 에러 카드로 렌더링한다.

### 7.3 재시도

외부 HTTP 호출은 최대 3회 재시도한다. 상세 정책은 `API_DESIGN.md §11.3, §12.3`.

| 상황 | 재시도 | 대기 |
|---|---|---|
| 401 (`invalid-token`/`expired-token`) | 토큰 재발급 후 **1회만** | 없음 |
| 429 `rate-limit-exceeded` | ✅ | **`Retry-After` 헤더 값** |
| 500 `internal-error` | ✅ | 지수 백오프 0.5s → 1s → 2s |
| 500 `maintenance` | ❌ | 캐시 폴백 |
| 400/404 계열 | ❌ | 해당 항목만 제외 |
| 연결 실패·타임아웃 | ✅ | 지수 백오프 |

### 7.4 레이트리밋 스로틀링

스펙에 구체적 한도 수치가 없고 응답 헤더(`X-RateLimit-*`, `Retry-After`)로만 통지된다. 하드코딩 sleep 대신 **헤더 기반 적응형 스로틀**(`api/throttle.py`)을 그룹별로 적용한다.

초기 로딩 시 `MARKET_DATA_CHART` 그룹에 종목 수만큼 호출이 몰리는 것이 유일한 병목이다 (20종목 = 20콜).

---

## 8. 테스트 전략

### 8.1 TDD 적용 범위

| 레이어 | 테스트 | 방식 |
|---|---|---|
| `analytics/` | **필수 (TDD)** | 순수 함수 → 알려진 입력/출력으로 검증. **먼저 테스트를 쓰고 구현한다** |
| `models/` | 필수 | Pydantic 검증 규칙 테스트 |
| `api/` | 선택 | httpx mock으로 응답 파싱만 검증. 실제 네트워크 호출 테스트 금지 |
| `ai/` | 선택 | 프롬프트 생성 함수만 테스트. LLM 응답은 테스트 안 함 |
| `ui/` | 안 함 | 2일 스코프에서 비용 대비 효과 없음 |

### 8.2 analytics 테스트 원칙

리스크 지표는 **검증 가능한 정답이 존재한다.** 예를 들어:

```python
def test_max_drawdown_known_series():
    # 100 → 120 → 90 → 110
    prices = pd.Series([100, 120, 90, 110])
    # 최대 낙폭 = (90 - 120) / 120 = -25%
    assert max_drawdown(prices) == pytest.approx(-0.25)

def test_annualized_volatility_zero_variance():
    returns = pd.Series([0.0] * 100)
    assert annualized_volatility(returns) == pytest.approx(0.0)

def test_sharpe_ratio_negative_excess_return():
    returns = pd.Series([-0.001] * 252)
    assert sharpe_ratio(returns, risk_free_rate=0.03) < 0
```

경계 조건을 반드시 테스트한다: 빈 시계열, 단일 데이터포인트, 분산 0, 전부 NaN, 결측치 포함.

### 8.3 실행

```bash
pytest tests/ -v --cov=analytics --cov-report=term-missing
```

`analytics/` 커버리지 목표 80% 이상. 다른 레이어는 목표 없음.

---

## 9. 성능 요구사항

| 항목 | 목표 | 측정 방법 |
|---|---|---|
| 초기 로딩 (캐시 미스) | 15초 이내 | 실행 → 전체 렌더링 완료. 캔들 20콜 + 스로틀 포함 |
| 재실행 (캐시 히트) | 2초 이내 | 위젯 조작 후 재렌더링 |
| AI 코멘트 생성 | 10초 타임아웃 | 초과 시 폴백 |
| 지원 종목 수 | 최대 50개 | 초과 시 평가금액 상위 50개만 계산하고 경고. 캔들이 종목당 1콜이라 상한이 필수 |
| 전체 API 호출 수 | 20종목 기준 약 28콜 | API_DESIGN §14 시퀀스 |

---

## 10. 개발 환경 세팅

```bash
# 1. 가상환경
uv venv && source .venv/bin/activate
# 또는: python -m venv .venv && source .venv/bin/activate

# 2. 의존성
uv pip install -r requirements.txt
# 또는: pip install -r requirements.txt

# 3. 환경변수
cp .env.example .env
# .env를 열어 실제 키 입력

# 4. 테스트
pytest tests/ -v

# 5. 실행
streamlit run app.py
```

---

## 11. 구현 순서 (Claude Code 작업 지시)

의존성 순서대로 진행한다. 각 단계는 다음 단계의 선행조건이다.

| 순서 | 작업 | 완료 조건 |
|---|---|---|
| 1 | `models/` 도메인 모델 정의 | Pydantic 모델 임포트 성공 |
| 2 | `config.py` + `.env.example` | `settings` 로드 성공 |
| 3 | `analytics/` **테스트 먼저 작성** → 구현 | `pytest tests/` 전부 통과 |
| 4 | `api/mock_client.py` + `data/sample_portfolio.json` | 샘플 `Portfolio` 반환 |
| 5 | `api/token_store.py` + `throttle.py` + `errors.py` | 토큰 캐시·스로틀 동작 |
| 6 | `api/toss_client.py` (인증 → accounts → holdings → buying-power) | 실계좌 잔고 조회 성공 |
| 6b | `toss_client` 캔들·벤치마크·국채·종목메타 | 히스토리 DataFrame 반환 |
| 7 | `services/dashboard_service.py` | 모든 모델을 채운 결과 객체 반환 |
| 8 | `ui/` + `app.py` | 브라우저 렌더링 |
| 9 | `ai/` 코멘트 + 폴백 | 코멘트 배너 표시 |
| 10 | 오프라인 모드 + 리허설 | 네트워크 끊고도 화면 정상 |

> **4번을 5번보다 먼저 하는 이유**: 목업 클라이언트를 먼저 만들면 실제 API 스펙 확인을 기다리지 않고 3~8번을 병행할 수 있다. 토스증권 API 응답 구조 확인에서 막혀도 전체 진행이 멈추지 않는다.

---

## 12. 미확정 사항

| # | 항목 | 대응 |
|---|---|---|
| ~~T1~~ | ~~엔드포인트·필드명~~ | ✅ **해결.** OpenAPI 3.1 스펙 v1.2.14 반영 완료 (`API_DESIGN.md` v2.0) |
| ~~T2~~ | ~~해외주식 티커 표기~~ | ✅ **해결.** `holdings.items[].symbol`을 `/candles`에 그대로 사용 |
| ~~T3~~ | ~~토큰 만료 시간~~ | ✅ **해결.** `expires_in` 필수 필드 (예시 86400) |
| T4 | 레이트리밋 구체 수치 | 스펙에 없음. 응답 헤더 기반 적응형 스로틀로 대응 (§7.4) |
| T5 | `cashBuyingPower`와 실제 예수금의 괴리 폭 | 실계좌로 확인. 괴리가 크면 README에 수치를 명시 |
