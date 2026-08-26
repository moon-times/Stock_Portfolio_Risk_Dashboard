# DATA DESIGN — 데이터 및 도메인 모델 설계

| 항목 | 내용 |
|---|---|
| 문서 버전 | 2.0 (실제 API 스펙 반영) |
| 선행 문서 | `docs/TRD.md`, `docs/REQUIREMENTS.md` |
| 대응 요구사항 | FR-200, FR-300, FR-400, FR-500 |

---

## 1. 도메인 모델 개요

```
Portfolio
├── account_no: str (마스킹됨)
├── as_of: datetime
├── cash_krw: Decimal          ← buying-power KRW
├── cash_usd: Decimal          ← buying-power USD
├── fx_rate: Decimal | None    ← USD→KRW midRate
├── daily_pnl_rate: float | None
├── holdings: list[Holding]
└── is_fallback: bool

Holding
├── ticker: str                ← symbol
├── name: str
├── market_country: MarketCountry  (KR | US)
├── currency: Currency             (KRW | USD)
├── quantity: Decimal
├── avg_price: Decimal         ← 거래 통화 기준
├── current_price: Decimal     ← 거래 통화 기준
├── daily_pnl_rate: float | None
└── asset_class: AssetClass

StockMeta                      ← GET /api/v1/stocks
├── symbol: str
├── market: Market             (KOSPI|KOSDAQ|NYSE|NASDAQ|AMEX|KR_ETC|US_ETC)
├── security_type: SecurityType
├── status: str
└── leverage_factor: Decimal | None

RiskMetrics
├── risk_free_rate: float
├── risk_free_source: Literal["KR_BOND_3Y", "fallback"]
├── annualized_volatility: float | None
├── sharpe_ratio: float | None
├── max_drawdown: float | None
├── var_95: float | None
├── beta: float | None
└── hhi: float | None

AllocationBreakdown
└── items: list[AllocationItem]  ← (asset_class, market_value, weight)

CorrelationMatrix
├── labels: list[str]
└── values: list[list[float]]

Commentary
├── sentences: list[str]
├── source: Literal["llm", "fallback"]
└── generated_at: datetime
```

---

## 2. 모델 상세

### 2.1 열거형

```python
# models/holding.py
from enum import StrEnum

class AssetClass(StrEnum):
    DOMESTIC_EQUITY = "국내주식"
    FOREIGN_EQUITY  = "해외주식"
    BOND            = "채권"
    CASH            = "현금"
    COMMODITY       = "원자재"
    REIT            = "리츠"
    OTHER           = "기타"

class Currency(StrEnum):          # API enum과 1:1
    KRW = "KRW"
    USD = "USD"

class MarketCountry(StrEnum):     # API enum과 1:1
    KR = "KR"
    US = "US"
```

### API enum 미러링 (`models/stock_meta.py`)

```python
class Market(StrEnum):
    KOSPI = "KOSPI"; KOSDAQ = "KOSDAQ"; KR_ETC = "KR_ETC"
    NYSE = "NYSE"; NASDAQ = "NASDAQ"; AMEX = "AMEX"; US_ETC = "US_ETC"

class SecurityType(StrEnum):
    STOCK = "STOCK"; FOREIGN_STOCK = "FOREIGN_STOCK"
    DEPOSITARY_RECEIPT = "DEPOSITARY_RECEIPT"
    INFRASTRUCTURE_FUND = "INFRASTRUCTURE_FUND"; REIT = "REIT"
    ETF = "ETF"; FOREIGN_ETF = "FOREIGN_ETF"; ETN = "ETN"
    STOCK_WARRANTS = "STOCK_WARRANTS"

class StockMeta(BaseModel):
    symbol: str
    market: str                      # 미지의 값 허용 -> str로 보관
    security_type: str               # 미지의 값 허용
    status: str = "ACTIVE"
    leverage_factor: Decimal | None = None
```

> 🔴 **unknown enum 허용은 스펙 요구사항이다.** `market`·`security_type`을 `StrEnum`으로 강제 파싱하면 토스증권이 값을 추가하는 순간 앱이 죽는다. **모델에는 `str`로 담고, 분류 로직에서만 위 `StrEnum` 상수와 비교한다.**

> `AssetClass` 값이 곧 화면 표시 라벨이다. 별도 번역 테이블을 두지 않는다 (NFR-502).
> `OTHER`는 분류 실패의 안전한 기본값이다. 분류 실패로 예외를 던지지 않는다 (FR-303).

### 2.2 Holding

```python
from decimal import Decimal
from pydantic import BaseModel, Field, computed_field

class Holding(BaseModel):
    ticker: str = Field(min_length=1, description="symbol. KR 6자리 숫자, US 티커")
    name: str
    market_country: MarketCountry = MarketCountry.KR
    currency: Currency = Currency.KRW
    quantity: Decimal = Field(ge=0)
    avg_price: Decimal = Field(ge=0, description="averagePurchasePrice, 거래 통화 기준")
    current_price: Decimal = Field(ge=0, description="lastPrice, 거래 통화 기준")
    daily_pnl_rate: float | None = None
    asset_class: AssetClass = AssetClass.OTHER

    @computed_field
    @property
    def market_value_native(self) -> Decimal:
        """거래 통화 기준 평가금액."""
        return self.quantity * self.current_price

    def market_value_krw(self, fx_rate: Decimal | None) -> Decimal | None:
        """원화 환산 평가금액. USD 종목인데 환율이 없으면 None."""
        if self.currency == Currency.KRW:
            return self.market_value_native
        if fx_rate is None:
            return None
        return self.market_value_native * fx_rate

    @computed_field
    @property
    def unrealized_pnl_pct(self) -> float:
        if self.avg_price == 0:
            return 0.0
        return float((self.current_price - self.avg_price) / self.avg_price)
```

**🔴 가격은 거래 통화 기준이다.** API의 `lastPrice`·`averagePurchasePrice`는 원화 환산값이 아니다. AAPL은 `"178.5"` (USD)로 온다. 원화 환산은 **모델이 하지 않고** 서비스 레이어가 `fx_rate`를 주입해 계산한다 — 환율은 시간에 따라 변하는 외부 값이라 모델에 고정하면 안 된다.

**금액은 `Decimal`, 비율은 `float`.** API가 모든 숫자를 문자열로 주므로 `Decimal(str(v))`로 파싱한다. `float()` 직접 변환은 금지한다 (FR-304 비중 합계 오차 방지).

### 2.3 Portfolio

```python
class Portfolio(BaseModel):
    account_no: str = Field(description="마스킹된 계좌번호")
    as_of: datetime
    cash_krw: Decimal = Field(default=Decimal(0), ge=0,
                              description="buying-power KRW cashBuyingPower")
    cash_usd: Decimal = Field(default=Decimal(0), ge=0,
                              description="buying-power USD cashBuyingPower")
    fx_rate: Decimal | None = Field(default=None, description="USD->KRW midRate")
    daily_pnl_rate: float | None = None
    holdings: list[Holding] = Field(default_factory=list)
    is_fallback: bool = False
    fallback_reason: str | None = None

    @computed_field
    @property
    def cash_total_krw(self) -> Decimal:
        """KRW + USD 현금의 원화 합산. 환율 없으면 KRW만."""
        if self.fx_rate is None:
            return self.cash_krw
        return self.cash_krw + self.cash_usd * self.fx_rate

    @computed_field
    @property
    def total_value(self) -> Decimal:
        total = self.cash_total_krw
        for h in self.holdings:
            v = h.market_value_krw(self.fx_rate)
            if v is not None:
                total += v
        return total

    @field_validator("account_no")
    @classmethod
    def _mask(cls, v: str) -> str:
        # FR-105 / NFR-303: 뒤 4자리 외 마스킹
        digits = "".join(ch for ch in v if ch.isdigit())
        if len(digits) <= 4:
            return "*" * len(digits)
        return "*" * (len(digits) - 4) + digits[-4:]
```

> `account_no`는 **모델 생성 시점에 강제 마스킹**된다. 원본 계좌번호는 `api/` 레이어의 지역 변수로만 존재하며 도메인 모델로 넘어오지 않는다. `accountSeq`(헤더용 정수)는 클라이언트 인스턴스에만 보관하고 도메인 모델에 넣지 않는다.

### 🔴 현금 의미 주의

`cash_krw`/`cash_usd`는 `GET /api/v1/buying-power`의 `cashBuyingPower`, 즉 **매수 가능 금액**이다. Open API에 예수금 조회가 없어 대체값으로 쓴다. 미결제 매수 주문이 있으면 실제 예수금보다 작다. 이 한계를 README와 화면 툴팁에 명시한다 (API_DESIGN §5.3).

### 2.4 RiskMetrics

```python
class RiskMetrics(BaseModel):
    risk_free_rate: float = 0.03
    risk_free_source: Literal["KR_BOND_3Y", "fallback"] = "fallback"
    annualized_volatility: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown: float | None = None
    var_95: float | None = None
    beta: float | None = None
    hhi: float | None = None

    lookback_days: int
    benchmark_symbol: str | None = None
    fx_rate_applied: Decimal | None = None
    excluded_tickers: list[str] = Field(default_factory=list)
```

`risk_free_source`가 `"fallback"`이면 화면의 샤프지수 옆에 `(기본금리)` 표기를 남긴다. 실시간 국채 금리가 반영됐는지 사용자가 알 수 있어야 한다.

**모든 지표가 `| None`이다.** 데이터 부족 시 예외 대신 `None`을 반환하고, UI는 `None`을 `N/A`로 표시한다 (FR-407). `excluded_tickers`는 가격 조회 실패로 계산에서 빠진 종목을 기록해 사용자에게 경고를 띄우는 데 쓴다 (FR-204).

### 2.5 AllocationBreakdown

```python
class AllocationItem(BaseModel):
    asset_class: AssetClass
    market_value: Decimal
    weight: float = Field(ge=0, le=1)

class AllocationBreakdown(BaseModel):
    items: list[AllocationItem]
    total_value: Decimal

    @computed_field
    @property
    def weight_sum(self) -> float:
        return sum(i.weight for i in self.items)
```

`items`는 **비중 내림차순 정렬**해서 생성한다. 차트 슬라이스와 범례 순서가 일치해야 한다 (FR-306).

### 2.6 CorrelationMatrix

```python
class CorrelationMatrix(BaseModel):
    labels: list[str]
    values: list[list[float]]

    @model_validator(mode="after")
    def _check_square(self):
        n = len(self.labels)
        assert len(self.values) == n and all(len(r) == n for r in self.values)
        return self
```

### 2.7 Commentary

```python
class Commentary(BaseModel):
    sentences: list[str] = Field(min_length=1, max_length=4)
    source: Literal["llm", "fallback"]
    generated_at: datetime
```

`max_length=4`가 FR-703(2~4문장)을 모델 레벨에서 강제한다. LLM이 더 많이 반환하면 파싱 단계에서 앞 4문장만 취한다.

### 2.8 DashboardData (최종 조립 객체)

```python
class DashboardData(BaseModel):
    portfolio: Portfolio
    allocation: AllocationBreakdown
    metrics: RiskMetrics
    correlation: CorrelationMatrix | None = None
    benchmark_series: dict[str, list[float]] | None = None
    benchmark_dates: list[str] | None = None
    commentary: Commentary | None = None
    daily_pnl_pct: float | None = None
    warnings: list[str] = Field(default_factory=list)
```

`app.py`는 이 객체 하나만 받아 각 `ui/` 컴포넌트에 나눠준다. P1 항목(`correlation`, `benchmark_series`)이 `None`이면 해당 블록을 렌더링하지 않는다 — **P1 미완이어도 데모가 성립하는 구조**다 (PRD §5.1).

---

## 3. 가격 시계열 데이터 구조

### 3.1 형태

```python
# pd.DataFrame
#              005930   000660     AAPL
# 2026-02-26   73_500   128_000  231_400
# 2026-02-27   74_100   127_500  233_100
# ...
# index: DatetimeIndex (거래일)
# columns: ticker
# values: 종가 (원화 환산)
```

### 3.2 정합 규칙 (FR-205)

| 상황 | 처리 |
|---|---|
| 종목마다 거래일이 다름 | 전체 종목의 거래일 **합집합**으로 인덱스 구성 |
| 특정 날짜 결측 | 전일 종가로 전진 채움 (`ffill`) |
| 시계열 앞부분 결측 (신규 상장 등) | 해당 행 제거 (`dropna()` 후 공통 구간만 사용) |
| 유효 데이터 30일 미만 | `InsufficientDataError` → 해당 종목 제외 |
| 해외 종목 (`candle.currency == "USD"`) | 조회 시점 `midRate`로 전 구간 환산 후 저장 |
| 환율 조회 실패 | USD 종목을 시계열에서 **제외**하고 경고. KRW 종목만으로 계산 |

### 캔들 API 반영 사항

| 항목 | 내용 |
|---|---|
| 출처 | `GET /api/v1/candles?symbol=&interval=1d&count=&adjusted=true` |
| **수정주가** | `adjusted=true` 고정. 액면분할·배당 미반영 시 가짜 급락이 MDD·변동성을 오염시킨다 |
| 페이지 크기 | 최대 200봉. 126 거래일 목표면 `count=166` 정도로 **1회 호출이면 충분** |
| 호출 단위 | **종목당 1회.** 다건 조회 불가 → 스로틀링 필요 (API_DESIGN §11) |
| timestamp | tz-aware ISO 8601 (`+09:00`). `pd.to_datetime(...).date()`로 날짜만 취해 정합 |
| 값 타입 | 전부 문자열. `Decimal(str(c["closePrice"]))` |

> **환율 단순화**: `dateTime` 파라미터로 일별 환율 조회가 가능하지만 126일이면 126콜이라 레이트리밋 리스크가 이득보다 크다. **조회 시점 `midRate` 하나로 전체 시계열을 환산**한다. 이 경우 환율 변동 리스크가 지표에서 빠지며, 해외 비중이 높은 포트폴리오는 실제 원화 기준 변동성이 계산값보다 높을 수 있다. 이 한계를 README에 명시한다.
>
> `rate`(매수환율) 대신 `midRate`(매매기준율)를 쓰는 이유: `rate`에는 스프레드가 섞여 있어 평가 목적에는 mid가 중립적이다.

---

## 4. 리스크 지표 계산 정의

모든 함수는 `analytics/risk_metrics.py`의 **순수 함수**다 (NFR-401). 아래 정의가 `tests/test_risk_metrics.py`의 명세가 된다.

### 4.0 공통 상수

```python
TRADING_DAYS_PER_YEAR = 252
```

### 4.1 연환산 변동성 (FR-401)

일간 수익률 표준편차에 √252를 곱한다.

```
σ_annual = std(r_daily, ddof=1) × √252
```

```python
def annualized_volatility(returns: pd.Series) -> float | None:
    r = returns.dropna()
    if len(r) < 2:
        return None
    return float(r.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))
```

| 테스트 케이스 | 입력 | 기대 |
|---|---|---|
| 분산 0 | `[0.0] * 100` | `0.0` |
| 데이터 부족 | `[0.01]` | `None` |
| 빈 시계열 | `[]` | `None` |

### 4.2 샤프지수 (FR-402)

초과수익의 연환산 평균을 연환산 변동성으로 나눈다.

```
Sharpe = (mean(r_daily) × 252 − r_f) / σ_annual
```

`risk_free_rate`는 `KR_BOND_3Y` 실시간 금리를 소수비율로 변환한 값이다 (API_DESIGN §9).

> 🔴 **단위 함정**: API의 `lastPrice`가 `"3.25"`면 3.25%다. **반드시 `/100`** 해서 `0.0325`로 넘긴다. 나누지 않으면 샤프지수가 `(0.08 - 3.25) / 0.18 ≈ -17.6`처럼 무의미한 값이 된다. 이 변환은 `api/` 레이어에서 끝내고, `analytics/`는 항상 소수비율만 받는다.

```python
def sharpe_ratio(returns: pd.Series, risk_free_rate: float) -> float | None:
    r = returns.dropna()
    if len(r) < 2:
        return None
    vol = annualized_volatility(r)
    if vol is None or vol == 0:
        return None
    annual_return = float(r.mean() * TRADING_DAYS_PER_YEAR)
    return (annual_return - risk_free_rate) / vol
```

| 테스트 케이스 | 입력 | 기대 |
|---|---|---|
| 변동성 0 (0으로 나눔) | `[0.0] * 100` | `None` (예외 아님) |
| 음의 초과수익 | `[-0.001] * 252` | `< 0` |
| 금리 단위 오입력 방지 | `risk_free_rate=3.25` | 테스트에서 `abs(result) > 10`이면 실패 처리 |

### 4.3 최대낙폭 MDD (FR-403)

누적 수익 곡선의 고점 대비 최대 하락률. **음수**로 반환한다.

```
cum_t = Π(1 + r_i)  for i ≤ t
peak_t = max(cum_i) for i ≤ t
MDD = min((cum_t − peak_t) / peak_t)
```

```python
def max_drawdown(returns: pd.Series) -> float | None:
    r = returns.dropna()
    if len(r) < 2:
        return None
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    return float(((cum - peak) / peak).min())
```

| 테스트 케이스 | 입력 (가격) | 기대 |
|---|---|---|
| 알려진 낙폭 | `100 → 120 → 90 → 110` | `≈ -0.25` |
| 단조 상승 | `100 → 110 → 120` | `0.0` |

> 가격 시계열을 직접 받는 오버로드도 제공하면 테스트가 쉬워진다. 내부적으로 `pct_change()` 후 위 함수에 위임한다.

### 4.4 VaR 95% 1일 (FR-404)

히스토리컬 방식. 일간 수익률 분포의 5% 분위수.

```
VaR_95 = quantile(r_daily, 0.05)
```

```python
def historical_var(returns: pd.Series, confidence: float = 0.95) -> float | None:
    r = returns.dropna()
    if len(r) < 20:
        return None
    return float(r.quantile(1 - confidence))
```

**음수로 반환한다.** "VaR -2.3%"는 "95% 신뢰수준에서 하루 최대 예상 손실 2.3%"를 뜻한다. 최소 20개 데이터포인트를 요구하는 이유는 그 미만에서 분위수가 의미를 갖지 않기 때문이다.

### 4.5 베타 (FR-405)

벤치마크 대비 민감도.

```
β = Cov(r_p, r_b) / Var(r_b)
```

```python
def beta(returns: pd.Series, benchmark_returns: pd.Series) -> float | None:
    df = pd.concat([returns, benchmark_returns], axis=1).dropna()
    if len(df) < 20:
        return None
    p, b = df.iloc[:, 0], df.iloc[:, 1]
    var_b = b.var(ddof=1)
    if var_b == 0:
        return None
    return float(p.cov(b) / var_b)
```

두 시계열은 **거래일 기준으로 정렬 후 교집합**만 사용한다 (`concat` + `dropna`).

| 테스트 케이스 | 입력 | 기대 |
|---|---|---|
| 자기 자신 | `beta(r, r)` | `≈ 1.0` |
| 2배 레버리지 | `beta(2*r, r)` | `≈ 2.0` |
| 벤치마크 무변동 | `beta(r, [0]*100)` | `None` |

### 4.6 집중도 HHI (FR-406)

허핀달-허시만 지수. 자산군 비중의 제곱합.

```
HHI = Σ w_i²
```

```python
def herfindahl_index(weights: list[float]) -> float | None:
    w = [x for x in weights if x is not None]
    if not w:
        return None
    return float(sum(x ** 2 for x in w))
```

해석: 1.0이면 완전 집중(자산군 하나), 자산군 n개가 균등하면 1/n. 5개 균등 = 0.20.

| 테스트 케이스 | 입력 | 기대 |
|---|---|---|
| 완전 집중 | `[1.0]` | `1.0` |
| 5개 균등 | `[0.2]*5` | `≈ 0.2` |
| 빈 입력 | `[]` | `None` |

### 4.7 포트폴리오 수익률 시계열 (`analytics/returns.py`)

개별 종목 수익률을 현재 비중으로 가중 합산한다.

```python
def portfolio_returns(
    prices: pd.DataFrame,
    weights: dict[str, float],
) -> pd.Series:
    """
    prices: index=날짜, columns=ticker, values=종가
    weights: ticker -> 비중 (합 1.0)
    """
    rets = prices.pct_change().dropna(how="all")
    common = [t for t in rets.columns if t in weights]
    if not common:
        return pd.Series(dtype=float)
    w = pd.Series({t: weights[t] for t in common})
    w = w / w.sum()          # 재정규화
    return (rets[common] * w).sum(axis=1)
```

> **단순화**: 현재 비중을 과거 전 기간에 고정 적용한다 (buy-and-hold 가정). 실제로는 기간 중 매매가 있었을 수 있다. `GET /api/v1/orders`로 거래내역 조회가 가능하지만 MVP 범위 밖이다 (CON-05). 이 가정을 README에 명시한다.
>
> 비중(`weights`)은 **원화 환산 평가금액 기준**으로 계산한다. 거래 통화 기준으로 계산하면 USD 종목의 비중이 1/1375로 축소된다.

### 4.8 상관계수 행렬 (FR-501, `analytics/correlation.py`)

자산군별 수익률 시계열을 만든 뒤 피어슨 상관계수를 계산한다.

```python
def asset_class_correlation(
    prices: pd.DataFrame,
    ticker_to_class: dict[str, AssetClass],
    weights: dict[str, float],
) -> CorrelationMatrix | None:
    rets = prices.pct_change().dropna(how="all")
    by_class: dict[str, pd.Series] = {}
    for cls in set(ticker_to_class.values()):
        cols = [t for t, c in ticker_to_class.items()
                if c == cls and t in rets.columns]
        if not cols:
            continue
        w = pd.Series({t: weights.get(t, 0) for t in cols})
        if w.sum() == 0:
            continue
        by_class[str(cls)] = (rets[cols] * (w / w.sum())).sum(axis=1)

    if len(by_class) < 2:
        return None          # FR-504
    df = pd.DataFrame(by_class).dropna()
    corr = df.corr(method="pearson").round(2)
    return CorrelationMatrix(
        labels=list(corr.columns),
        values=corr.values.tolist(),
    )
```

**현금 자산군은 상관계수 계산에서 제외한다.** 가격 변동이 없어 분산이 0이고, 상관계수가 `NaN`이 된다.

---

## 5. 자산군 분류 (FR-301, FR-302)

### 5.1 근거 데이터

`GET /api/v1/stocks?symbols=...` (최대 200건, **전 종목 1회 호출**)이 주는 메타데이터를 1차 근거로 쓴다.

| 필드 | 값 | 분류 기여 |
|---|---|---|
| `market` | `KOSPI` `KOSDAQ` `KR_ETC` `NYSE` `NASDAQ` `AMEX` `US_ETC` | 국내/해외 판별 |
| `securityType` | `STOCK` `FOREIGN_STOCK` `DEPOSITARY_RECEIPT` `ETF` `FOREIGN_ETF` `ETN` `REIT` `INFRASTRUCTURE_FUND` `STOCK_WARRANTS` | 자산 유형 판별 |

**메타데이터만으로는 부족한 지점**: `securityType == "ETF"`는 ETF라는 사실만 알려줄 뿐 **무엇에 투자하는 ETF인지는 알려주지 않는다.** KODEX 골드선물(원자재)과 KOSEF 국고채10년(채권)이 둘 다 `ETF` / `KOSPI`다. 따라서 ETF 계열만 종목명 키워드로 하위 분류하는 **하이브리드**로 간다.

### 5.2 매핑 파일 (축소됨)

```yaml
# config/asset_class_map.yaml

# 1) 수동 오버라이드 (최우선). 자동 분류가 틀렸을 때만 추가
overrides:
  "132030": 원자재      # KODEX 골드선물

# 2) ETF/ETN 하위 분류 키워드 (종목명 부분일치)
etf_keywords:
  채권:     ["국고채", "회사채", "단기채", "종합채권", "크레딧", "TREASURY", "BOND"]
  원자재:   ["골드", "금현물", "은선물", "원유", "구리", "농산물", "GOLD", "OIL"]
  해외주식: ["미국", "나스닥", "S&P", "차이나", "일본", "유로", "인도", "베트남"]

default: 기타
```

v1.0의 `tickers` 전수 매핑과 `patterns` 정규식은 **폐기한다.** 메타데이터가 더 정확하고, 수동 유지보수 부담이 사라진다.

### 5.3 분류 알고리즘

```python
KR_MARKETS = {"KOSPI", "KOSDAQ", "KR_ETC"}
US_MARKETS = {"NYSE", "NASDAQ", "AMEX", "US_ETC"}
ETF_TYPES  = {"ETF", "FOREIGN_ETF", "ETN"}

def classify(holding_row: dict, meta: StockMeta | None,
             cfg: ClassifierConfig) -> AssetClass:
    symbol = holding_row["symbol"]
    name   = holding_row.get("name", "")

    # 1. 수동 오버라이드
    if symbol in cfg.overrides:
        return cfg.overrides[symbol]

    # 2. 메타 조회 실패 -> marketCountry 축약 분류
    if meta is None:
        return (AssetClass.DOMESTIC_EQUITY
                if holding_row.get("marketCountry") == "KR"
                else AssetClass.FOREIGN_EQUITY)

    st, mk = meta.security_type, meta.market

    # 3. 리츠 / 인프라펀드
    if st in ("REIT", "INFRASTRUCTURE_FUND"):
        return AssetClass.REIT

    # 4. ETF 계열 -> 종목명 키워드 하위 분류
    if st in ETF_TYPES:
        for asset_class, keywords in cfg.etf_keywords.items():
            if any(k.upper() in name.upper() for k in keywords):
                return asset_class
        return (AssetClass.DOMESTIC_EQUITY if mk in KR_MARKETS
                else AssetClass.FOREIGN_EQUITY)

    # 5. 해외 주식
    if st in ("FOREIGN_STOCK", "DEPOSITARY_RECEIPT") or mk in US_MARKETS:
        return AssetClass.FOREIGN_EQUITY

    # 6. 국내 주식
    if mk in KR_MARKETS:
        return AssetClass.DOMESTIC_EQUITY

    # 7. 미지의 enum 값 등
    return AssetClass.OTHER
```

**절대 예외를 던지지 않는다** (FR-303). 매핑 파일이 없거나 손상되어도, `stocks` 호출이 실패해도, 미지의 enum이 와도 동작한다.

예수금(`cash_krw`/`cash_usd`)은 분류 없이 항상 `AssetClass.CASH`다.

### 5.4 왜 unknown enum을 허용해야 하는가

스펙이 명시적으로 요구한다:

> 클라이언트는 unknown enum 값을 허용하도록 구현해야 합니다.

`market`·`securityType`·`accountType`을 Pydantic `StrEnum`으로 강제 파싱하면 토스증권이 값을 하나 추가하는 순간 `ValidationError`로 앱 전체가 죽는다. **모델에는 `str`로 담고 분류 로직에서만 상수와 비교한다.**

## 6. 데이터 검증 규칙

| 대상 | 규칙 | 위반 시 |
|---|---|---|
| `Holding.quantity` | `>= 0` | Pydantic ValidationError → 해당 종목 스킵 + 경고 |
| `Holding.current_price` | `>= 0` | 동일 |
| API string decimal | `Decimal(str(v))` 파싱 성공 | `InvalidOperation` → 해당 종목 스킵 + 경고 |
| `Price.usd` | `null` 가능 | 널 가드 필수. `Decimal(None)`은 예외 |
| `risk_free_rate` | `0 <= r <= 0.2` | 범위 밖이면 단위 오류로 간주, 폴백값 사용 |
| `market` / `securityType` | 미지의 값 허용 | `AssetClass.OTHER`로 분류, 예외 금지 |
| `AllocationItem.weight` | `0 <= w <= 1` | 동일 |
| 비중 합계 | `1.0 ± 0.001` | 경고 로그, 재정규화 후 진행 |
| `CorrelationMatrix` | 정방행렬, 대각 = 1.0 | ValidationError → 히트맵 미표시 |
| 가격 시계열 | 유효 행 ≥ 30 | 해당 종목 `excluded_tickers`에 추가 |

---

## 7. 샘플 데이터 (`data/sample_portfolio.json`)

폴백용 고정 데이터 (FR-104). **실제 API 응답 구조를 그대로 흉내낸다** — 목업 클라이언트와 실제 클라이언트가 동일한 파싱 코드를 태울 수 있어야 한다.

```json
{
  "holdings": {
    "result": {
      "totalPurchaseAmount": {"krw": "58200000", "usd": "17800"},
      "marketValue": {
        "amount":          {"krw": "63400000", "usd": "18620"},
        "amountAfterCost": {"krw": "62100000", "usd": "18450"}
      },
      "profitLoss": {
        "amount": {"krw": "5200000", "usd": "820"},
        "rate": "0.0912", "rateAfterCost": "0.0790"
      },
      "dailyProfitLoss": {
        "amount": {"krw": "-1140000", "usd": "-210"},
        "rate": "-0.0180"
      },
      "items": [
        {"symbol": "005930", "name": "삼성전자", "marketCountry": "KR", "currency": "KRW",
         "quantity": "150", "lastPrice": "73500", "averagePurchasePrice": "68000",
         "dailyProfitLoss": {"amount": "-165000", "rate": "-0.0147"}},
        {"symbol": "000660", "name": "SK하이닉스", "marketCountry": "KR", "currency": "KRW",
         "quantity": "60", "lastPrice": "128000", "averagePurchasePrice": "115000",
         "dailyProfitLoss": {"amount": "-153000", "rate": "-0.0195"}},
        {"symbol": "148070", "name": "KOSEF 국고채10년", "marketCountry": "KR", "currency": "KRW",
         "quantity": "200", "lastPrice": "63200", "averagePurchasePrice": "62000",
         "dailyProfitLoss": {"amount": "12000", "rate": "0.0009"}},
        {"symbol": "132030", "name": "KODEX 골드선물", "marketCountry": "KR", "currency": "KRW",
         "quantity": "550", "lastPrice": "15300", "averagePurchasePrice": "14800",
         "dailyProfitLoss": {"amount": "27500", "rate": "0.0033"}},
        {"symbol": "AAPL", "name": "Apple Inc.", "marketCountry": "US", "currency": "USD",
         "quantity": "45", "lastPrice": "231.4", "averagePurchasePrice": "205.0",
         "dailyProfitLoss": {"amount": "-140", "rate": "-0.0132"}},
        {"symbol": "MSFT", "name": "Microsoft", "marketCountry": "US", "currency": "USD",
         "quantity": "22", "lastPrice": "398.2", "averagePurchasePrice": "372.5",
         "dailyProfitLoss": {"amount": "-95", "rate": "-0.0108"}}
      ]
    }
  },
  "buying_power": {"KRW": "6800000", "USD": "1200"},
  "exchange_rate": {"rate": "1382.4", "midRate": "1376.0"},
  "risk_free": {"symbol": "KR_BOND_3Y", "lastPrice": "3.25"},
  "stocks": [
    {"symbol": "005930", "market": "KOSPI",  "securityType": "STOCK", "status": "ACTIVE"},
    {"symbol": "000660", "market": "KOSPI",  "securityType": "STOCK", "status": "ACTIVE"},
    {"symbol": "148070", "market": "KOSPI",  "securityType": "ETF",   "status": "ACTIVE"},
    {"symbol": "132030", "market": "KOSPI",  "securityType": "ETF",   "status": "ACTIVE"},
    {"symbol": "AAPL",   "market": "NASDAQ", "securityType": "FOREIGN_STOCK", "status": "ACTIVE"},
    {"symbol": "MSFT",   "market": "NASDAQ", "securityType": "FOREIGN_STOCK", "status": "ACTIVE"}
  ]
}
```

목표 비중은 목업 PNG와 근사하게: 국내주식 ~35% / 해외주식 ~30% / 채권 ~15% / 현금 ~10% / 원자재 ~10%. 구현 시 실제 계산 결과를 보고 수량을 조정한다.

**샘플에 ETF 2종을 넣은 이유**: `securityType == "ETF"`인 종목이 종목명 키워드로 채권·원자재로 갈라지는 경로(§5.3 4단계)를 폴백 모드에서도 검증할 수 있다.

**가격 히스토리는 샘플에 넣지 않는다.** 목업 클라이언트도 `/candles`는 실제로 호출한다 — 샘플 종목이 실존하므로 가능하며, 지표 계산 경로가 실데이터로 검증된다. 네트워크까지 끊긴 경우는 §8의 캐시가 처리한다.

## 8. 캐시 파일 스키마

```json
// data/cache/last_successful.json
{
  "schema_version": 2,
  "cached_at": "2026-08-26T14:32:00+09:00",
  "portfolio": { /* Portfolio 직렬화 */ },
  "stock_meta": { "005930": {"market": "KOSPI", "securityType": "STOCK"} },
  "fx_rate": "1376.0",
  "risk_free_rate": 0.0325,
  "prices": {
    "index": ["2026-02-26", "2026-02-27"],
    "columns": ["005930", "000660"],
    "data": [[73500, 128000], [74100, 127500]]
  },
  "benchmark": {"symbol": "KOSPI", "index": ["2026-02-26"], "data": [2812.45]}
}
```

토큰 캐시는 **별도 파일**(`data/cache/token.json`)로 분리한다. 수명 주기가 다르고, 권한을 `0600`으로 따로 걸어야 한다 (API_DESIGN §2.3).

`schema_version`이 현재 버전과 다르면 캐시를 무시하고 샘플 데이터로 폴백한다. 스키마 변경 시 옛 캐시가 크래시를 유발하는 것을 막는다.

---

## 9. 갱신 기록

| 날짜 | 버전 | 변경 내용 |
|---|---|---|
| 2026-08-26 | 1.0 | 초안 |
| 2026-08-26 | **2.0** | 실제 API 스펙 반영. `Holding`에 `market_country` 추가·가격을 거래통화 기준으로 변경, `Portfolio` 현금을 KRW/USD 분리, `StockMeta` 신설, 자산군 분류를 메타데이터 하이브리드로 전환, `AssetClass.REIT` 추가, 무위험수익률 실시간화, 캔들 API 제약 반영, 샘플 데이터를 API 응답 구조로 재작성 |
