# API DESIGN — 외부 연동 설계

| 항목 | 내용 |
|---|---|
| 문서 버전 | **2.0 (실제 스펙 반영)** |
| 최종 수정 | 2026-08-26 |
| 선행 문서 | `docs/TRD.md`, `docs/design/DATA_DESIGN.md` |
| 대응 요구사항 | FR-100, FR-200, FR-700, NFR-200, NFR-300 |

---

## 0. 스펙 출처

본 문서는 **토스증권 Open API OpenAPI 3.1 스펙 v1.2.14** 를 근거로 작성되었다. v1.0 문서의 추정 엔드포인트는 전부 폐기되었다.

| 항목 | 값 |
|---|---|
| Base URL | `https://openapi.tossinvest.com` |
| 인증 | OAuth 2.0 Client Credentials |
| 응답 envelope | 성공 `{"result": {...}}` / 실패 `{"error": {...}}` |
| 웹소켓 | `wss://openapi-ws.tossinvest.com/ws/v1` — **본 프로젝트 범위 밖** |

### v1.0 대비 주요 변경

| 항목 | v1.0 (추정) | v2.0 (실제) |
|---|---|---|
| 토큰 요청 | JSON, `appkey`/`appsecret` | **form-urlencoded**, `client_id`/`client_secret` |
| 계좌 지정 | URL path에 계좌번호 | `accountSeq` 조회 후 **`X-Tossinvest-Account` 헤더** |
| 보유종목 | `/accounts/{no}/holdings` | `GET /api/v1/holdings` |
| 가격 히스토리 | FinanceDataReader | **`GET /api/v1/candles`** (FDR 제거) |
| 벤치마크 | FDR `KS11` | **`GET /api/v1/market-indicators/KOSPI/candles`** |
| 무위험수익률 | 고정 3.0% | **`KR_BOND_3Y` 실시간 금리** |
| 자산군 분류 | 정규식 추정 | **`GET /api/v1/stocks`의 `market`·`securityType`** |
| 숫자 타입 | 추정 | **모든 금액·수량이 문자열** |

> ⚠️ **모든 금액·수량·가격이 JSON string으로 내려온다.** (`"quantity": "100"`, `"lastPrice": "72000"`) 반드시 `Decimal(str(v))`로 파싱한다. `float()` 직접 변환은 금지한다.

---

## 1. 증권사 클라이언트 계약

### 1.1 프로토콜

```python
# api/base.py
from typing import Protocol
import pandas as pd
from models.portfolio import Portfolio
from models.stock_meta import StockMeta

class BrokerClient(Protocol):
    def fetch_portfolio(self) -> Portfolio:
        """보유 종목 + 현금 + 일간손익을 조회해 Portfolio를 반환한다."""
        ...

    def fetch_stock_meta(self, symbols: list[str]) -> dict[str, StockMeta]:
        """종목 메타(시장·유형)를 조회한다. 자산군 분류에 사용."""
        ...

    def fetch_price_history(self, symbols: list[str], days: int) -> pd.DataFrame:
        """일봉 종가 시계열. index=날짜, columns=symbol. 실패 종목은 제외."""
        ...

    def fetch_benchmark_history(self, symbol: str, days: int) -> pd.Series:
        """벤치마크 지수 일봉 종가."""
        ...

    def fetch_risk_free_rate(self) -> float | None:
        """KR_BOND_3Y 금리를 소수비율로 반환 (3.25% -> 0.0325)."""
        ...

    def fetch_exchange_rate(self) -> Decimal | None:
        """USD -> KRW 환율."""
        ...

    @property
    def is_live(self) -> bool: ...
```

### 1.2 구현체

| 클래스 | 파일 | 역할 |
|---|---|---|
| `TossSecuritiesClient` | `api/toss_client.py` | 실계좌 연동 |
| `MockBrokerClient` | `api/mock_client.py` | `data/sample_portfolio.json` 재생 |
| `CachedBrokerClient` | `api/cached_client.py` | 디스크 캐시 데코레이터 |

### 1.3 선택 로직

```python
def create_broker_client(settings: Settings) -> BrokerClient:
    if settings.use_mock_data or not settings.has_broker_credentials:
        return MockBrokerClient(fallback_reason="자격증명 없음")
    try:
        client = TossSecuritiesClient(settings)
        client.bootstrap()          # 토큰 확보 + accountSeq 해석
        return CachedBrokerClient(client)
    except (AuthenticationError, AccountNotFoundError) as e:
        logger.warning("증권사 연동 실패, 목업 폴백: %s", type(e).__name__)
        return MockBrokerClient(fallback_reason="인증 실패")
```

---

## 2. 인증 (`POST /oauth2/token`)

### 2.1 요청

```http
POST https://openapi.tossinvest.com/oauth2/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id={CLIENT_ID}&client_secret={CLIENT_SECRET}
```

| 필드 | 필수 | 값 |
|---|---|---|
| `grant_type` | ✅ | `client_credentials` 고정 |
| `client_id` | ✅ | 발급받은 클라이언트 ID (`c_01H...`) |
| `client_secret` | ✅ | 발급받은 시크릿 |

**이 엔드포인트만 `Authorization` 헤더 없이 호출한다.** 응답도 공통 envelope이 아닌 OAuth2 표준 형식이다.

### 2.2 응답

```json
{
  "access_token": "eyJraWQiOiI...",
  "token_type": "Bearer",
  "expires_in": 86400
}
```

### 2.3 🔴 토큰 단일성 제약 (설계 결정 사항)

스펙 원문:

> client 당 유효한 access token 은 1 개입니다. 재발급 시 이전에 발급된 token 은 즉시 무효화됩니다.

**이것이 이 프로젝트에서 가장 위험한 제약이다.** Streamlit은 위젯 조작마다 스크립트를 처음부터 재실행한다. 매 실행마다 토큰을 재발급하면:

1. 직전 토큰이 즉시 죽는다
2. 진행 중이던 다른 요청이 401로 실패한다
3. 다른 터미널에서 돌리던 개발 세션도 같이 죽는다

**대응 규칙 (필수)**

| # | 규칙 |
|---|---|
| A1 | 토큰은 `data/cache/token.json`에 **디스크 영속화**한다. 프로세스 재시작·Streamlit 재실행에도 살아남아야 한다 |
| A2 | 만료 60초 전까지는 **절대 재발급하지 않는다** |
| A3 | 재발급은 (a) 캐시 없음 (b) 만료 임박 (c) 401 `expired-token` 수신 — 세 경우에만 |
| A4 | 401 수신 후 재발급은 **요청당 1회만** 시도한다. 재시도 루프 금지 |
| A5 | 토큰 발급 실패는 재시도하지 않는다 (`AUTH` 레이트리밋 소모) |
| A6 | `token.json`은 반드시 `.gitignore`. 파일 권한 `0600` |

```python
# api/token_store.py
TOKEN_PATH = Path("data/cache/token.json")
SAFETY_MARGIN = 60

def load_token() -> str | None:
    try:
        d = json.loads(TOKEN_PATH.read_text())
        if time.time() < d["expires_at"] - SAFETY_MARGIN:
            return d["access_token"]
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    return None

def save_token(access_token: str, expires_in: int) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps({
        "access_token": access_token,
        "expires_at": time.time() + expires_in,
    }))
    TOKEN_PATH.chmod(0o600)
```

---

## 3. 계좌 해석 (`GET /api/v1/accounts`)

### 3.1 요청

```http
GET /api/v1/accounts
Authorization: Bearer {access_token}
```

### 3.2 응답

```json
{
  "result": [
    {"accountNo": "12345678901", "accountSeq": 1, "accountType": "BROKERAGE"}
  ]
}
```

| 필드 | 타입 | 용도 |
|---|---|---|
| `accountNo` | string | 표시용 (마스킹 후) |
| `accountSeq` | integer | **모든 계좌 컨텍스트 API의 `X-Tossinvest-Account` 헤더 값** |
| `accountType` | enum | `BROKERAGE` / `OVERSEAS_DERIVATIVES` / `PENSION_SAVINGS` / `RESHORING_INVESTMENT` |

### 3.3 선택 규칙

```python
def resolve_account(accounts: list[dict]) -> tuple[int, str]:
    if not accounts:
        raise AccountNotFoundError("사용 가능한 계좌가 없습니다")
    brokerage = [a for a in accounts if a.get("accountType") == "BROKERAGE"]
    target = (brokerage or accounts)[0]
    return int(target["accountSeq"]), str(target["accountNo"])
```

- 현재 `BROKERAGE`만 노출되지만, **unknown enum을 허용해야 한다** (스펙 명시). `accountType`이 모르는 값이어도 예외를 던지지 않는다.
- 계좌가 여러 개면 첫 번째를 쓴다. 다중 계좌는 비목표(CON-04).
- `.env`에 계좌번호를 넣을 필요가 없다. **`accountSeq`는 런타임에 해석한다.**
- 해석된 `accountSeq`는 세션 동안 재사용한다.

---

## 4. 보유 종목 (`GET /api/v1/holdings`)

### 4.1 요청

```http
GET /api/v1/holdings
Authorization: Bearer {access_token}
X-Tossinvest-Account: {accountSeq}
```

`symbol` 쿼리 파라미터로 단건 필터가 가능하나, 본 프로젝트는 전체 조회만 사용한다.

### 4.2 응답 구조

```json
{
  "result": {
    "totalPurchaseAmount": {"krw": "6500000", "usd": "1553"},
    "marketValue": {
      "amount":          {"krw": "7200000", "usd": "1785"},
      "amountAfterCost": {"krw": "7050000", "usd": "1771.43"}
    },
    "profitLoss": {
      "amount": {"krw": "700000", "usd": "232"},
      "rate": "0.1179", "rateAfterCost": "0.0983"
    },
    "dailyProfitLoss": {
      "amount": {"krw": "100000", "usd": "25"},
      "rate": "0.0141"
    },
    "items": [
      {
        "symbol": "005930", "name": "삼성전자",
        "marketCountry": "KR", "currency": "KRW",
        "quantity": "100", "lastPrice": "72000",
        "averagePurchasePrice": "65000",
        "marketValue": {"purchaseAmount": "6500000", "amount": "7200000",
                        "amountAfterCost": "7050000"},
        "profitLoss": {"amount": "700000", "rate": "0.1077"},
        "dailyProfitLoss": {"amount": "100000", "rate": "0.0141"},
        "cost": {"commission": "14400", "tax": "135600"}
      }
    ]
  }
}
```

### 4.3 필드 매핑

| 도메인 (`Holding`) | API 경로 | 비고 |
|---|---|---|
| `ticker` | `items[].symbol` | KR 6자리 / US 티커 |
| `name` | `items[].name` | |
| `market_country` | `items[].marketCountry` | `KR` / `US` |
| `currency` | `items[].currency` | `KRW` / `USD` |
| `quantity` | `items[].quantity` | 문자열 → Decimal |
| `current_price` | `items[].lastPrice` | **거래 통화 기준** |
| `avg_price` | `items[].averagePurchasePrice` | **거래 통화 기준** |
| `market_value_native` | `items[].marketValue.amount` | 거래 통화 기준 |
| `daily_pnl_rate` | `items[].dailyProfitLoss.rate` | 소수비율 |

### 4.4 🔴 통화 합산 함정

`Price` 스키마 원문:

> 각 통화 필드는 해당 통화로 거래된 종목의 합만 포함합니다 (환율 환산을 통한 통화 간 합산 미포함).

즉 `marketValue.amount = {"krw": "7200000", "usd": "1785"}`에서 **`krw + usd`는 서로 다른 통화의 별개 합계다.** 총 자산가치를 구하려면 직접 환산해야 한다.

```python
total_krw = Decimal(overview["marketValue"]["amount"]["krw"] or 0)
usd_raw   = overview["marketValue"]["amount"].get("usd")
total_usd = Decimal(usd_raw) if usd_raw else Decimal(0)
total_value = total_krw + total_usd * fx_rate
```

`usd` 필드는 **해외 종목이 없으면 `null`** 이다. `Decimal(None)`은 터진다. 반드시 널 가드를 둔다.

### 4.5 예수금은 여기 없다

`holdings` 응답에 예수금·현금 필드가 없다. §5의 `buying-power`로 별도 조회한다.

### 4.6 파싱 구현

```python
def _to_holding(row: dict, meta: StockMeta | None) -> Holding | None:
    """1행 → Holding. 실패 시 None (예외 아님)."""
    try:
        return Holding(
            ticker=str(row["symbol"]),
            name=str(row.get("name") or row["symbol"]),
            market_country=row.get("marketCountry", "KR"),
            currency=row.get("currency", "KRW"),
            quantity=Decimal(str(row["quantity"])),
            avg_price=Decimal(str(row["averagePurchasePrice"])),
            current_price=Decimal(str(row["lastPrice"])),
            daily_pnl_rate=_opt_float(row.get("dailyProfitLoss", {}).get("rate")),
            asset_class=classify(row, meta),
        )
    except (KeyError, ValidationError, InvalidOperation, TypeError) as e:
        logger.warning("종목 파싱 실패, 건너뜀: %s", type(e).__name__)
        return None
```

---

## 5. 현금 (`GET /api/v1/buying-power`)

### 5.1 요청 — **통화별로 2회 호출**

```http
GET /api/v1/buying-power?currency=KRW
GET /api/v1/buying-power?currency=USD
Authorization: Bearer {access_token}
X-Tossinvest-Account: {accountSeq}
```

### 5.2 응답

```json
{"result": {"currency": "KRW", "cashBuyingPower": "5000000"}}
```

### 5.3 ⚠️ 의미상 한계 (README 명시 대상)

`cashBuyingPower`는 **매수 가능 금액(미수 미발생 기준)** 이지 예수금(deposit)이 아니다. 미결제 매수 주문이 있거나 출금 제한 금액이 있으면 실제 예수금보다 작게 나온다.

Open API에 예수금 조회 엔드포인트가 없으므로 **가장 근접한 대체값**으로 사용한다. 이 한계를 README와 화면 툴팁에 명시한다.

### 5.4 합산

```python
krw_cash = fetch_buying_power("KRW")                  # Decimal
usd_cash = fetch_buying_power("USD")                  # Decimal
cash_krw = krw_cash + usd_cash * fx_rate
```

USD 계좌가 없으면 `0` 또는 404가 올 수 있다. 두 경우 모두 `Decimal(0)`으로 처리하고 예외를 던지지 않는다.

---

## 6. 환율 (`GET /api/v1/exchange-rate`)

### 6.1 요청

```http
GET /api/v1/exchange-rate?baseCurrency=USD&quoteCurrency=KRW
Authorization: Bearer {access_token}
```

### 6.2 응답

```json
{
  "result": {
    "baseCurrency": "USD", "quoteCurrency": "KRW",
    "rate": "1380.5", "midRate": "1375", "basisPoint": "40",
    "rateChangeType": "UP",
    "validFrom": "2026-03-25T09:30:00+09:00",
    "validUntil": "2026-03-25T09:31:00+09:00"
  }
}
```

### 6.3 설계 결정

| 항목 | 결정 | 사유 |
|---|---|---|
| 사용 필드 | **`midRate`** (매매기준율) | `rate`는 매수 환율이라 스프레드가 섞인다. 평가 목적에는 mid가 중립적 |
| 적용 방식 | **조회 시점 단일 환율을 전 기간에 적용** | `dateTime` 파라미터로 일별 환율 조회가 가능하지만 126일치면 126콜. 2일 스코프에서 레이트리밋 리스크가 이득보다 큼 |
| 갱신 주기 | 1분 (참고용 표시 환율) | 실제 거래 환율과 다를 수 있음 |
| 실패 시 | `fx_rate = None` → 해외 종목을 원화 환산에서 제외하고 경고 | |

**한계 명시 (README)**: 단일 환율 적용으로 인해 **환율 변동 리스크가 지표에서 빠진다.** 해외 비중이 높은 포트폴리오는 실제 원화 기준 변동성이 계산값보다 높을 수 있다.

---

## 7. 가격 히스토리 (`GET /api/v1/candles`)

**FinanceDataReader를 완전히 대체한다.**

### 7.1 요청

```http
GET /api/v1/candles?symbol=005930&interval=1d&count=200&adjusted=true
Authorization: Bearer {access_token}
```

| 파라미터 | 필수 | 값 | 비고 |
|---|---|---|---|
| `symbol` | ✅ | `005930`, `AAPL` | **단건만.** 다건 조회 불가 |
| `interval` | ✅ | `1d` | `1m`도 있으나 미사용 |
| `count` | | `200` | **최대 200** |
| `before` | | ISO 8601 | 페이지네이션 |
| `adjusted` | | `true` (기본) | **수정주가 — 반드시 true 유지** |

### 7.2 응답

```json
{
  "result": {
    "candles": [
      {"timestamp": "2026-03-25T09:00:00+09:00",
       "openPrice": "71600", "highPrice": "72300", "lowPrice": "71500",
       "closePrice": "72000", "volume": "3521000", "currency": "KRW"}
    ],
    "nextBefore": null
  }
}
```

### 7.3 설계 함의

| 항목 | 내용 |
|---|---|
| **한 종목 = 한 호출** | 20종목이면 `MARKET_DATA_CHART` 그룹에 20콜. 스로틀링 필수 (§10) |
| **126일 = 1페이지** | `count=200`이면 목표 126 거래일이 한 번에 들어온다. **페이지네이션 불필요** |
| **`adjusted=true` 필수** | 액면분할·배당 미반영 시 가짜 급락이 MDD·변동성을 오염시킨다 |
| **통화 혼재** | US 종목은 `currency: "USD"`. 원화 환산 후 시계열에 넣는다 |
| **timestamp가 tz-aware** | `+09:00` 포함. `pd.to_datetime(...).dt.date`로 날짜만 취해 정합 |

### 7.4 구현

```python
def fetch_price_history(self, symbols: list[str], days: int
                        ) -> tuple[pd.DataFrame, list[str]]:
    fx = self.fetch_exchange_rate() or Decimal(1)
    frames, failed = {}, []

    for sym in symbols:
        try:
            r = self._get("/api/v1/candles", params={
                "symbol": sym, "interval": "1d",
                "count": min(200, max(days + 40, 60)), "adjusted": "true",
            })
            candles = r["result"]["candles"]
            if not candles:
                failed.append(sym); continue

            s = pd.Series(
                {pd.to_datetime(c["timestamp"]).date():
                     Decimal(str(c["closePrice"])) for c in candles},
                dtype=object,
            ).sort_index()

            if candles[0].get("currency") == "USD":
                s = s.map(lambda v: v * fx)

            frames[sym] = s.map(float)
        except (BrokerAPIError, KeyError, InvalidOperation):
            failed.append(sym)                      # FR-204

    if not frames:
        raise PriceDataError("가격 데이터를 하나도 가져오지 못했습니다")

    prices = pd.DataFrame(frames).sort_index().ffill().dropna()
    return prices.tail(days), failed
```

`count`에 `days + 40`을 요청하는 이유: 휴장일 여유. 126일 목표면 166봉을 받아 뒤 126개를 자른다.

---

## 8. 벤치마크 (`GET /api/v1/market-indicators/{symbol}/candles`)

```http
GET /api/v1/market-indicators/KOSPI/candles?interval=1d&count=200
Authorization: Bearer {access_token}
```

응답은 §7과 동일한 캔들 구조이나 **`currency` 필드가 없다** (지수는 포인트 단위).

### 심볼 카탈로그 (8종 고정)

| 심볼 | 명칭 | 단위 |
|---|---|---|
| `KOSPI` | 코스피 | 포인트 |
| `KOSDAQ` | 코스닥 | 포인트 |
| `KR_BOND_2Y` ~ `KR_BOND_30Y` | 한국 국채 2/3/5/10/20/30년 | **%** |

카탈로그에 없는 심볼은 400 `unsupported-symbol`. 국채는 **일봉(`1d`)만 지원**하며 분봉 요청 시 400 `invalid-request`.

> 개별 종목 캔들은 이 엔드포인트가 아니라 `/api/v1/candles`를 쓴다. 혼동 주의.

---

## 9. 무위험수익률 (`GET /api/v1/market-indicators/prices`)

```http
GET /api/v1/market-indicators/prices?symbols=KR_BOND_3Y
Authorization: Bearer {access_token}
```

```json
{"result": [{"symbol": "KR_BOND_3Y",
             "timestamp": "2026-06-11T15:30:00+09:00",
             "lastPrice": "3.25"}]}
```

### 변환

```python
def fetch_risk_free_rate(self) -> float | None:
    """KR_BOND_3Y 금리를 소수비율로 반환. 3.25% -> 0.0325"""
    try:
        r = self._get("/api/v1/market-indicators/prices",
                      params={"symbols": "KR_BOND_3Y"})
        items = r["result"]
        if not items:
            return None
        return float(Decimal(str(items[0]["lastPrice"])) / 100)
    except (BrokerAPIError, KeyError, IndexError, InvalidOperation):
        return None
```

**🔴 단위 함정**: `lastPrice`가 `"3.25"`면 이는 3.25%다. **반드시 100으로 나눈다.** 나누지 않으면 샤프지수가 `(0.08 - 3.25) / 0.18 ≈ -17.6`처럼 터무니없는 값이 된다.

실패 시 `settings.risk_free_rate` (기본 0.03)로 폴백하고 화면에 `(기본값)` 표기를 남긴다.

---

## 10. 종목 메타 — 자산군 분류 (`GET /api/v1/stocks`)

### 10.1 요청 — 다건 조회 지원

```http
GET /api/v1/stocks?symbols=005930,000660,AAPL
Authorization: Bearer {access_token}
```

**최대 200건을 콤마로 구분.** 보유 종목 전체를 **1회 호출**로 처리한다.

### 10.2 응답 (분류에 쓰는 필드만)

```json
{"result": [{
  "symbol": "005930", "name": "삼성전자",
  "market": "KOSPI",
  "securityType": "STOCK",
  "isCommonShare": true,
  "status": "ACTIVE",
  "currency": "KRW",
  "leverageFactor": null
}]}
```

| 필드 | enum |
|---|---|
| `market` | `KOSPI` `KOSDAQ` `NYSE` `NASDAQ` `AMEX` `KR_ETC` `US_ETC` |
| `securityType` | `STOCK` `FOREIGN_STOCK` `DEPOSITARY_RECEIPT` `INFRASTRUCTURE_FUND` `REIT` `ETF` `FOREIGN_ETF` `ETN` `STOCK_WARRANTS` |
| `status` | `SCHEDULED` `ACTIVE` `DELISTED` |
| `leverageFactor` | ETF/ETN만. `"2.0"`, `"-1.0"` 등 |

### 10.3 분류 알고리즘 (하이브리드)

`securityType`이 ETF 계열이면 **무엇에 투자하는 ETF인지는 알 수 없다.** KODEX 골드선물과 KOSEF 국고채10년이 둘 다 `ETF`다. 따라서 메타데이터 + 종목명 키워드 하이브리드로 간다.

```
1. securityType == REIT | INFRASTRUCTURE_FUND        → 리츠
2. securityType in (ETF, ETN, FOREIGN_ETF):
     종목명 키워드 검사 (config/asset_class_map.yaml)
       채권 키워드 (국고채/회사채/단기채/종합채권)     → 채권
       원자재 키워드 (골드/은선물/원유/구리/농산물)     → 원자재
       해외 키워드 (미국/나스닥/S&P/차이나/일본/유로)   → 해외주식
       그 외 → market이 KR 계열이면 국내주식, 아니면 해외주식
3. securityType in (FOREIGN_STOCK, DEPOSITARY_RECEIPT) → 해외주식
4. market in (NYSE, NASDAQ, AMEX, US_ETC)              → 해외주식
5. market in (KOSPI, KOSDAQ, KR_ETC)                   → 국내주식
6. 그 외 / 메타 조회 실패                               → 기타
```

**메타 조회가 실패해도 분류는 계속된다.** `marketCountry`(holdings 응답에 이미 있음)로 KR/US만 구분해 3~5단계 축약본을 적용한다. 절대 예외를 던지지 않는다 (FR-303).

### 10.4 `config/asset_class_map.yaml` (축소됨)

메타데이터가 시장·유형을 알려주므로 YAML은 **ETF 하위 분류 키워드**와 **수동 오버라이드**만 담는다.

```yaml
# 수동 오버라이드 (최우선). 자동 분류가 틀렸을 때만 추가
overrides:
  "132030": 원자재      # KODEX 골드선물

# ETF/ETN 하위 분류 키워드
etf_keywords:
  채권:   ["국고채", "회사채", "단기채", "종합채권", "크레딧", "TREASURY", "BOND"]
  원자재: ["골드", "금현물", "은선물", "원유", "구리", "농산물", "GOLD", "OIL"]
  해외주식: ["미국", "나스닥", "S&P", "차이나", "일본", "유로", "인도", "베트남"]

default: 기타
```

---

## 11. 레이트리밋

### 11.1 그룹

엔드포인트마다 별도 버킷을 쓴다. 각 엔드포인트 설명의 `Rate Limits Group`이 소속을 나타낸다.

| 그룹 | 본 프로젝트에서 쓰는 엔드포인트 | 호출 횟수 (20종목 기준) |
|---|---|---|
| `AUTH` | `/oauth2/token` | 0~1 |
| `ACCOUNT` | `/accounts` | 1 |
| `ASSET` | `/holdings` | 1 |
| `ORDER_INFO` | `/buying-power` | 2 |
| `MARKET_INFO` | `/exchange-rate` | 1 |
| `STOCK` | `/stocks` | 1 |
| `MARKET_DATA_CHART` | `/candles` | **20** ← 병목 |
| `MARKET_INDICATOR` | `/market-indicators/prices` | 1 |
| `MARKET_INDICATOR_CHART` | `/market-indicators/KOSPI/candles` | 1 |

**전체 초기 로딩 ≈ 28콜.** 대부분이 `MARKET_DATA_CHART`에 몰린다.

### 11.2 수치는 스펙에 없다

스펙은 구체적 한도를 명시하지 않고 **응답 헤더로만 통지**한다.

| 헤더 | 의미 |
|---|---|
| `X-RateLimit-Limit` | 현재 허용 초당 요청 수 (burst capacity) |
| `X-RateLimit-Remaining` | 버킷 잔여 토큰. 429 시 0 |
| `X-RateLimit-Reset` | 토큰 1개 재충전까지 예상 초 |
| `Retry-After` | 재시도 권장 초 |

따라서 **하드코딩된 sleep 대신 헤더 기반 적응형 스로틀링**을 구현한다.

```python
# api/throttle.py
class AdaptiveThrottle:
    """그룹별 잔여 토큰을 추적해 소진 직전에 선제적으로 쉰다."""

    def __init__(self, min_interval: float = 0.12):
        self._remaining: dict[str, int] = {}
        self._reset: dict[str, float] = {}
        self._min_interval = min_interval
        self._last: dict[str, float] = {}

    def before(self, group: str) -> None:
        # 잔여 1개 이하면 재충전까지 대기
        if self._remaining.get(group, 99) <= 1:
            time.sleep(self._reset.get(group, 1.0))
        # 기본 간격 유지
        gap = time.monotonic() - self._last.get(group, 0)
        if gap < self._min_interval:
            time.sleep(self._min_interval - gap)
        self._last[group] = time.monotonic()

    def after(self, group: str, resp: httpx.Response) -> None:
        try:
            self._remaining[group] = int(resp.headers["X-RateLimit-Remaining"])
            self._reset[group] = float(resp.headers.get("X-RateLimit-Reset", 1))
        except (KeyError, ValueError):
            pass
```

캔들 루프에서 `throttle.before("MARKET_DATA_CHART")`를 매 반복 호출한다.

### 11.3 429 처리

```python
if resp.status_code == 429:
    wait = float(resp.headers.get("Retry-After", 1))
    if attempt < MAX_RETRIES:
        time.sleep(wait)
        continue                     # Retry-After를 따르는 재시도는 허용
    raise RateLimitError("API 호출 한도를 초과했습니다")
```

> v1.0 문서는 "429는 재시도 금지"였으나, 실제 스펙이 `Retry-After`를 제공하므로 **그 값을 존중하는 재시도는 허용**한다. 임의 백오프 재시도는 여전히 금지다.

---

## 12. 공통 HTTP 레이어

### 12.1 응답 envelope

| 상황 | 형태 |
|---|---|
| 성공 (2xx) | `{"result": ...}` |
| 실패 (4xx/5xx) | `{"error": {"requestId": "...", "code": "...", "message": "...", "data": {...}}}` |

`result`와 `error`는 **동시에 나타나지 않는다.**
`/oauth2/token`만 예외로 OAuth2 표준 형식을 쓴다.

### 12.2 에러 코드 (flat string)

| HTTP | code | 의미 | 처리 |
|---|---|---|---|
| 401 | `invalid-token` | 토큰 무효 | 재발급 1회 후 재시도 |
| 401 | `expired-token` | 토큰 만료 | 재발급 1회 후 재시도 |
| 401 | `login-user-not-found` | 로그인 정보 없음 | 목업 폴백 |
| 400 | `account-header-required` | `X-Tossinvest-Account` 누락 | **구현 버그.** 로그 남기고 폴백 |
| 400 | `account-not-found` | 계좌 없음 | 목업 폴백 |
| 400 | `unsupported-symbol` | 미지원 심볼 | 해당 종목만 제외 |
| 400 | `invalid-request` | 파라미터 오류 | 해당 호출만 포기 |
| 404 | `stock-not-found` | 종목 없음 | 해당 종목만 제외 |
| 429 | `rate-limit-exceeded` | 한도 초과 | `Retry-After` 대기 후 재시도 |
| 500 | `internal-error` | 서버 오류 | 백오프 재시도 |
| 500 | `maintenance` | 점검 중 | **재시도 금지.** 캐시 폴백 |

**클라이언트는 unknown code를 허용해야 한다** (스펙 명시). 매핑에 없는 코드는 일반 `BrokerAPIError`로 처리한다.

### 12.3 요청 래퍼

```python
_client = httpx.Client(
    base_url="https://openapi.tossinvest.com",
    timeout=httpx.Timeout(10.0, connect=5.0),
)

RETRYABLE_STATUS = {500, 502, 503, 504}
NON_RETRYABLE_CODES = {"maintenance", "account-not-found",
                       "unsupported-symbol", "stock-not-found",
                       "invalid-request"}
MAX_RETRIES = 3

def _request(self, method: str, path: str, group: str,
             account_ctx: bool = False, **kw) -> dict:
    self.throttle.before(group)
    refreshed = False

    for attempt in range(MAX_RETRIES):
        headers = {"Authorization": f"Bearer {self._token()}"}
        if account_ctx:
            headers["X-Tossinvest-Account"] = str(self.account_seq)

        try:
            resp = _client.request(method, path, headers=headers, **kw)
        except (httpx.ConnectError, httpx.ReadTimeout):
            time.sleep(0.5 * 2 ** attempt)
            continue

        self.throttle.after(group, resp)

        if resp.status_code == 200:
            return resp.json()

        code = self._error_code(resp)

        if resp.status_code == 401 and not refreshed:
            self._force_refresh_token()        # A4: 요청당 1회만
            refreshed = True
            continue
        if resp.status_code == 429:
            time.sleep(float(resp.headers.get("Retry-After", 1)))
            continue
        if code in NON_RETRYABLE_CODES:
            raise BrokerAPIError(code)
        if resp.status_code in RETRYABLE_STATUS:
            time.sleep(0.5 * 2 ** attempt)
            continue
        raise BrokerAPIError(code or f"HTTP {resp.status_code}")

    raise BrokerAPIError("요청이 반복 실패했습니다")

@staticmethod
def _error_code(resp: httpx.Response) -> str | None:
    try:
        return resp.json().get("error", {}).get("code")
    except Exception:
        return None
```

### 12.4 `X-Request-Id`

모든 응답(성공·실패)에 포함되며 `error.requestId`와 동일하다. **실패 시 이 값을 로그에 남긴다.** 토스증권 CS 문의 시 필요하다.

```python
logger.warning("API 실패 code=%s requestId=%s",
               code, resp.headers.get("X-Request-Id"))
```

`message`는 정책상 빈 문자열일 수 있으므로 **`code` 기반으로 자체 메시지를 매핑한다** (스펙 권장, NFR-304와도 부합).

---

## 13. 🔴 구현 금지 엔드포인트 (FR-106)

스펙에 존재하지만 **클라이언트에 구현하지 않는다.** 조회 전용 앱이다.

```
POST   /api/v1/orders                                   주문 생성
POST   /api/v1/orders/{orderId}/modify                  주문 정정
POST   /api/v1/orders/{orderId}/cancel                  주문 취소
POST   /api/v1/conditional-orders                       조건주문 생성
POST   /api/v1/conditional-orders/{id}/modify           조건주문 수정
DELETE /api/v1/conditional-orders/{id}                  조건주문 취소
```

**Claude Code 지시**: 위 경로 문자열이 코드베이스에 등장해서는 안 된다. 실수로도 자금이 움직이지 않게 하는 최선의 방법은 코드가 아예 존재하지 않는 것이다.

조회 계열(`GET /api/v1/orders`, `/order-history`)도 MVP 범위 밖이므로 구현하지 않는다.

---

## 14. 호출 시퀀스 (초기 로딩)

```
1.  토큰 캐시 확인 → 없거나 만료 임박 시 POST /oauth2/token      [AUTH]
2.  GET /api/v1/accounts → accountSeq 해석                      [ACCOUNT]
3.  GET /api/v1/exchange-rate (USD→KRW, midRate)                [MARKET_INFO]
4.  GET /api/v1/holdings (X-Tossinvest-Account)                 [ASSET]
5.  GET /api/v1/buying-power?currency=KRW                       [ORDER_INFO]
6.  GET /api/v1/buying-power?currency=USD                       [ORDER_INFO]
7.  GET /api/v1/stocks?symbols=... (전 종목 1회)                 [STOCK]
    └ 자산군 분류 → AllocationBreakdown 확정
8.  GET /api/v1/market-indicators/prices?symbols=KR_BOND_3Y     [MARKET_INDICATOR]
9.  종목별 GET /api/v1/candles (throttled 루프)                  [MARKET_DATA_CHART]
10. GET /api/v1/market-indicators/KOSPI/candles                 [MARKET_IND_CHART]
    └ 지표 계산 (순수 함수, 네트워크 없음)
11. Claude API → 진단 코멘트
```

3번을 4번보다 먼저 하는 이유: 환율이 있어야 §4.4의 통화 합산과 §7의 캔들 원화 환산이 가능하다.

**7번이 실패해도 4번 결과의 `marketCountry`로 축약 분류가 가능하다** (§10.3). 자산배분 차트가 비지 않는다.

---

## 15. Claude API (AI 진단 코멘트)

### 15.1 호출 계약

```python
MODEL = "claude-sonnet-4-6"
TIMEOUT_SECONDS = 10
MAX_TOKENS = 500

def generate_commentary(allocation, metrics, correlation, api_key) -> Commentary:
    """실패·타임아웃 시 예외 없이 fallback Commentary를 반환한다."""
```

### 15.2 입력 페이로드 (NFR-305)

**집계 지표만 보낸다.** 계좌번호·종목명·개별 수량은 제외한다.

```json
{
  "allocation": [
    {"asset_class": "국내주식", "weight_pct": 35.0},
    {"asset_class": "해외주식", "weight_pct": 30.0},
    {"asset_class": "채권", "weight_pct": 15.0},
    {"asset_class": "현금", "weight_pct": 10.0},
    {"asset_class": "원자재", "weight_pct": 10.0}
  ],
  "metrics": {
    "annualized_volatility_pct": 18.2,
    "sharpe_ratio": 1.42,
    "max_drawdown_pct": -12.4,
    "var_95_pct": -2.3,
    "beta": 1.15,
    "hhi": 0.28,
    "risk_free_rate_pct": 3.25,
    "risk_free_source": "KR_BOND_3Y"
  },
  "correlations": [
    {"pair": ["국내주식", "해외주식"], "value": 0.62}
  ],
  "lookback_days": 126,
  "fx_note": "해외 자산은 조회 시점 단일 환율로 환산됨"
}
```

`fx_note`를 넣는 이유: LLM이 해외 비중 관련 코멘트를 낼 때 환율 리스크가 미반영이라는 점을 인지하게 한다.

### 15.3 시스템 프롬프트

```python
SYSTEM_PROMPT = """당신은 포트폴리오 리스크 분석가입니다.
주어진 지표를 근거로 포트폴리오의 리스크 특성을 진단합니다.

규칙:
1. 반드시 주어진 수치를 인용해 설명합니다. 수치 없는 일반론은 쓰지 않습니다.
2. 2~4개 문장으로 작성합니다.
3. 특정 종목의 매수·매도를 권유하지 않습니다.
4. 자산군 수준의 비중 조정 방향은 제시할 수 있습니다.
5. 확정적 예측 대신 조건부 표현("~할 여지가 있습니다")을 씁니다.
6. 한국어로 작성합니다.
7. 데이터에 없는 수치를 만들어내지 않습니다.

출력 형식:
JSON만 출력합니다. 마크다운 코드펜스나 설명을 붙이지 않습니다.
{"sentences": ["문장1", "문장2", "문장3"]}
"""
```

### 15.4 응답 파싱 (FR-704)

```python
def _parse(raw: str) -> list[str] | None:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        sentences = data.get("sentences")
        if not isinstance(sentences, list) or not sentences:
            return None
        return [str(s) for s in sentences][:4]
    except json.JSONDecodeError:
        return None
```

파싱 실패 시 재시도 없이 즉시 폴백한다.

### 15.5 폴백 (FR-705)

```python
def rule_based_commentary(allocation, metrics, correlation) -> Commentary:
    s = []
    top = max(allocation.items, key=lambda x: x.weight)
    if top.weight > 0.4:
        s.append(f"{top.asset_class} 비중이 {top.weight*100:.0f}%로 "
                 f"포트폴리오의 상당 부분을 차지합니다.")
    if metrics.annualized_volatility is not None:
        v = metrics.annualized_volatility * 100
        level = "높은" if v > 20 else "보통" if v > 12 else "낮은"
        s.append(f"연환산 변동성은 {v:.1f}%로 {level} 수준입니다.")
    if metrics.sharpe_ratio is not None:
        s.append(f"샤프지수는 {metrics.sharpe_ratio:.2f}로, 감수한 위험 대비 "
                 f"{'양호한' if metrics.sharpe_ratio > 1 else '아쉬운'} 성과를 보였습니다.")
    if correlation is not None:
        pair, val = _max_offdiag(correlation)
        if val > 0.5:
            s.append(f"{pair[0]}와 {pair[1]}의 상관계수가 {val:.2f}로 높아 "
                     f"분산 효과가 제한적입니다.")
    if not s:
        s.append("리스크 지표를 계산하기에 데이터가 충분하지 않습니다.")
    return Commentary(sentences=s[:4], source="fallback",
                      generated_at=datetime.now())
```

### 15.6 캐싱 (FR-709)

```python
@st.cache_data(ttl=3600, show_spinner=False)
def cached_commentary(payload_hash: str, payload_json: str, api_key: str):
    return generate_commentary(...)
```

지표 해시를 캐시 키로 써서 동일 지표에 중복 과금하지 않는다.

### 15.7 고지 (FR-708)

```
이 대시보드는 학습·분석 목적의 참고 자료이며 투자 자문이 아닙니다.
투자 판단과 그 결과에 대한 책임은 본인에게 있습니다.
```

---

## 16. 예외 → 사용자 메시지 매핑

| 예외 | 화면 메시지 | 앱 동작 |
|---|---|---|
| `AuthenticationError` | 증권사 인증에 실패했습니다. 샘플 데이터로 표시합니다. | 목업 폴백 |
| `AccountNotFoundError` | 사용 가능한 계좌를 찾을 수 없습니다. | 목업 폴백 |
| `RateLimitError` | API 호출 한도에 도달했습니다. 캐시된 데이터를 표시합니다. | 캐시 재생 |
| `MaintenanceError` | 증권사 시스템 점검 중입니다. 캐시된 데이터를 표시합니다. | 캐시 재생, 재시도 안 함 |
| `BrokerAPIError` | 증권사 서버 응답에 문제가 있습니다. | 캐시 → 목업 |
| `PriceDataError` | 가격 데이터를 가져오지 못했습니다. 일부 지표가 표시되지 않습니다. | 지표 `N/A` |
| `InsufficientDataError` | 계산에 필요한 데이터가 부족합니다. | 해당 지표만 `N/A` |
| `ExchangeRateError` | 환율을 가져오지 못해 해외 자산을 원화로 환산하지 못했습니다. | 해외 종목 제외 + 경고 |
| `AICommentaryError` | (미표시) | 규칙 기반 코멘트 |

원본 예외 메시지를 화면에 노출하지 않는다 (NFR-304). 위 표의 문구로 치환한다.

---

## 17. 갱신 기록

| 날짜 | 버전 | 변경 내용 |
|---|---|---|
| 2026-08-26 | 1.0 | 초안. 토스증권 스펙 미검증 |
| 2026-08-26 | **2.0** | **OpenAPI 3.1 스펙 v1.2.14 반영.** 전 엔드포인트·필드명 확정. FinanceDataReader 제거. 토큰 단일성 제약 대응. 헤더 기반 적응형 스로틀링. 자산군 분류를 `stocks` 메타 기반으로 전환. 무위험수익률 `KR_BOND_3Y` 실시간 조회. 현금 KRW+USD 합산 |
