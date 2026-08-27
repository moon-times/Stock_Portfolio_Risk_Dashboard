"""토스증권 Open API 실계좌 연동 클라이언트 (API_DESIGN.md §1~14).

`MockBrokerClient`도 가격 히스토리(`/candles`, `/market-indicators/{symbol}/candles`)는
이 클라이언트에 위임한다 (DATA_DESIGN §7 — 목업도 가격은 실조회). 그 두 엔드포인트는
계좌 컨텍스트(`X-Tossinvest-Account`)가 필요 없어 `bootstrap()` 없이도 호출 가능하다.
"""

import logging
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
from pydantic import ValidationError

from api import token_store
from api.errors import (
    AccountNotFoundError,
    AuthenticationError,
    BrokerAPIError,
    PriceDataError,
    error_for_code,
)
from api.throttle import AdaptiveThrottle
from config import Settings
from config import settings as default_settings
from models.holding import Holding
from models.portfolio import Portfolio
from models.stock_meta import StockMeta

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_KST = ZoneInfo("Asia/Seoul")

MAX_RETRIES = 3
MIN_VALID_PRICE_ROWS = 30
RETRYABLE_STATUS = {500, 502, 503, 504}
# 429 Retry-After / 500 재시도 대기가 서버 오응답(음수·에포크 타임스탬프 등)에
# 그대로 노출되지 않도록 하는 상한. api/throttle.py의 MAX_THROTTLE_WAIT와 같은
# 값·같은 이유(Phase 5 C-2에서 이미 한 번 겪은 결함)지만, 이쪽은 개별 요청의
# 재시도 대기이고 스로틀은 그룹 전체의 소진 대기라 책임이 달라 상수를 분리한다.
MAX_RETRY_WAIT = 10.0
# API_DESIGN §12.2: 이 코드들은 재시도해도 결과가 바뀌지 않으므로 즉시 예외로 던진다.
NON_RETRYABLE_CODES = {
    "maintenance",
    "account-not-found",
    "unsupported-symbol",
    "stock-not-found",
    "invalid-request",
}

# API_DESIGN §2.3 A5: 토큰 "발급 실패"(자격증명 오류 등 4xx)는 이 프로세스
# 안에서 재시도하지 않는다 (AUTH 레이트리밋 소모 방지). 일시적 연결 단절은
# 이 플래그를 세우지 않는다 — 유동 IP 환경(state.md 기록)에서 순간 단절
# 한 번으로 프로세스 수명 내내 실계좌 연동이 막히면 안 된다.
_token_fetch_failed = False


def _opt_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _opt_decimal(v) -> Decimal | None:
    """문자열 숫자를 Decimal로 안전하게 파싱한다. null·빈문자열·파싱불가·비유한값은 None.

    DATA_DESIGN §6 "Price.usd는 null 가능, 널 가드 필수"의 일반형 — 어떤
    금액 필드든 값이 없거나 깨져도 `Decimal(None)`/`InvalidOperation`으로
    죽지 않는다. `Decimal("NaN")`/`Decimal("Infinity")`는 예외를 던지지
    않고 조용히 통과하는 값이라 `is_finite()`로 별도 차단한다.
    """
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _as_dict(v) -> dict:
    """서버가 준 값이 예상과 달리 dict가 아니어도(list/str/None 등) 안전하게 빈 dict로."""
    return v if isinstance(v, dict) else {}


def _as_list(v) -> list:
    return v if isinstance(v, list) else []


def _error_code(resp: httpx.Response) -> str | None:
    try:
        return _as_dict(resp.json().get("error")).get("code")
    except (ValueError, AttributeError):
        return None


def resolve_account(accounts: list) -> tuple[int, str]:
    """API_DESIGN §3.3. BROKERAGE 계좌 우선, 없으면 첫 계좌를 쓴다.

    accountType이 미지의 값이어도(unknown enum 허용, §3.3) 예외를 던지지 않는다.
    원소가 dict가 아닌 경우도 (list 컴프리헨션 안에서) 방어한다.
    """
    if not accounts:
        raise AccountNotFoundError("사용 가능한 계좌가 없습니다")
    try:
        brokerage = [
            a for a in accounts if isinstance(a, dict) and a.get("accountType") == "BROKERAGE"
        ]
        target = (brokerage or accounts)[0]
        return int(target["accountSeq"]), str(target["accountNo"])
    except (KeyError, TypeError, ValueError) as e:
        raise AccountNotFoundError("계좌 정보 형식이 올바르지 않습니다") from e


def _to_holding(row: dict) -> Holding | None:
    """API_DESIGN §4.6. 1행 파싱 실패는 예외가 아니라 None (해당 종목만 제외).

    asset_class는 채우지 않는다 — 분류(classify())는 services 레이어의
    책임이라는 Phase 3/4 결정을 그대로 따른다 (state.md 참고). 그 결정에
    따라 이 함수는 종목 메타를 받지 않는다.
    """
    try:
        return Holding(
            ticker=str(row["symbol"]),
            name=str(row.get("name") or row["symbol"]),
            market_country=row.get("marketCountry", "KR"),
            currency=row.get("currency", "KRW"),
            quantity=Decimal(str(row["quantity"])),
            avg_price=Decimal(str(row["averagePurchasePrice"])),
            current_price=Decimal(str(row["lastPrice"])),
            daily_pnl_rate=_opt_float(_as_dict(row.get("dailyProfitLoss")).get("rate")),
        )
    except (KeyError, ValidationError, InvalidOperation, TypeError) as e:
        logger.warning("종목 파싱 실패, 건너뜀: %s", type(e).__name__)
        return None


def candles_to_series(candles: list[dict], fx: Decimal) -> pd.Series:
    """캔들 응답 -> (날짜: 종가) Series. USD 캔들이면 fx로 원화 환산.

    통화 판정은 캔들 전체를 훑어 하나라도 USD면 환산한다 — 첫 원소만 보면
    그 원소에 `currency` 키가 없을 때 나머지가 USD여도 환산이 통째로
    생략된다.

    호출부가 (KeyError, TypeError, ValueError, InvalidOperation)로 감싸
    종목 1개의 이상 데이터가 나머지를 죽이지 않도록 한다 (FR-204).
    """
    is_usd = any(_as_dict(c).get("currency") == "USD" for c in candles)
    s = pd.Series(
        {pd.to_datetime(c["timestamp"]).date():
             Decimal(str(c["closePrice"])) for c in candles},
        dtype=object,
    ).sort_index()
    if is_usd:
        s = s.map(lambda v: v * fx)
    return s.map(float)


def _fetch_new_token(cfg: Settings) -> str:
    """POST /oauth2/token. 캐시를 거치지 않고 항상 새로 발급한다.

    401 재발급(A4)과 캐시 미스 재발급(A3) 양쪽에서 호출된다. 실패 시
    AuthenticationError를 던진다.

    실패를 두 종류로 구분한다: 자격증명 오류 등 서버가 명시적으로 거부한
    경우만 `_token_fetch_failed`를 세워 이 프로세스에서 재시도를 막는다
    (A5). 일시적 연결 단절(`httpx.TransportError`)은 다음 호출에서 다시
    시도할 수 있게 플래그를 세우지 않는다.
    """
    global _token_fetch_failed
    if _token_fetch_failed:
        raise AuthenticationError("토큰 발급이 이전에 실패하여 이번 프로세스에서는 재시도하지 않습니다")
    try:
        resp = httpx.post(
            f"{cfg.toss_base_url}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": cfg.toss_client_id,
                "client_secret": cfg.toss_client_secret.get_secret_value(),
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json()
        token = body["access_token"]
        if not isinstance(token, str) or not token:
            raise AuthenticationError("발급된 토큰 형식이 올바르지 않습니다")
        token_store.save_token(token, body["expires_in"])
        return token
    except httpx.TransportError as e:
        logger.warning("토큰 발급 네트워크 오류, 다음 호출에서 재시도 가능: %s", type(e).__name__)
        raise AuthenticationError("증권사 인증에 실패했습니다") from e
    except (httpx.HTTPStatusError, KeyError, TypeError, ValueError) as e:
        logger.warning("토큰 발급 실패, 이번 프로세스에서는 재시도하지 않음: %s", type(e).__name__)
        _token_fetch_failed = True
        raise AuthenticationError("증권사 인증에 실패했습니다") from e


class TossSecuritiesClient:
    """토스증권 Open API 실계좌 연동 (`api/base.py`의 `BrokerClient` 계약 구현)."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or default_settings
        self.throttle = AdaptiveThrottle()
        self.account_seq: int | None = None
        self.account_no: str | None = None
        self.__http: httpx.Client | None = None

    @property
    def _http(self) -> httpx.Client:
        # 지연 생성: MockBrokerClient가 내부적으로 이 클래스를 항상 들고
        # 있지만(가격 히스토리 위임용) 실제로 호출하기 전까지는 소켓을
        # 열지 않는다.
        if self.__http is None:
            self.__http = httpx.Client(base_url=self._settings.toss_base_url, timeout=_TIMEOUT)
        return self.__http

    @_http.setter
    def _http(self, client: httpx.Client) -> None:
        self.__http = client

    @property
    def is_live(self) -> bool:
        return True

    def _token(self) -> str:
        # A2/A3: 만료 60초 전까지는 캐시를 그대로 쓰고, 캐시가 없을 때만 발급한다.
        return token_store.load_token() or _fetch_new_token(self._settings)

    def bootstrap(self) -> None:
        """토큰 확보 + accountSeq 해석 (API_DESIGN §14 1~2단계)."""
        data = self._request("GET", "/api/v1/accounts", group="ACCOUNT")
        self.account_seq, self.account_no = resolve_account(_as_list(data.get("result")))

    def _request(
        self, method: str, path: str, group: str, account_ctx: bool = False, **kw
    ) -> dict:
        """API_DESIGN §12.3 공통 요청 래퍼. 실패 시 BrokerAPIError 계열을 던진다.

        200 응답이라도 본문이 JSON object가 아니면(점검 페이지 HTML, 배열
        등) BrokerAPIError로 변환한다 — 호출부가 항상 dict를 받는다고
        가정할 수 있어야 하위의 `.get()` 체인이 AttributeError로 죽지
        않는다.
        """
        self.throttle.before(group)
        refreshed = False
        # 401 이후 강제로 새로 발급한 토큰은 디스크 캐시 저장이 실패해도
        # (예: Windows에서 다른 프로세스가 파일을 잠금, token_store.py 참고)
        # 이 요청의 나머지 시도에서는 그대로 재사용한다. token_store.load_token()에
        # 의존하면 저장 실패 시 매 시도마다 새로 발급하게 되어 토큰이
        # 즉시 서로를 무효화하는 루프가 생긴다 (위험 1).
        forced_token: str | None = None

        for attempt in range(MAX_RETRIES):
            if account_ctx and self.account_seq is None:
                # 토큰을 발급받기 전에 먼저 확인한다 — 실패가 예정된 요청을 위해
                # 불필요한 토큰 발급(네트워크 호출)을 하지 않는다.
                raise AccountNotFoundError("계좌가 아직 해석되지 않았습니다 (bootstrap 필요)")

            token = forced_token or self._token()
            headers = {"Authorization": f"Bearer {token}"}
            if account_ctx:
                headers["X-Tossinvest-Account"] = str(self.account_seq)

            try:
                resp = self._http.request(method, path, headers=headers, **kw)
            except httpx.TransportError:
                time.sleep(0.5 * 2**attempt)
                continue

            self.throttle.after(group, resp)

            if resp.status_code == 200:
                try:
                    body = resp.json()
                except ValueError as e:
                    raise BrokerAPIError("응답 형식이 올바르지 않습니다") from e
                if not isinstance(body, dict):
                    raise BrokerAPIError("응답 형식이 올바르지 않습니다")
                return body

            code = _error_code(resp)
            logger.warning(
                "API 실패 status=%s code=%s requestId=%s",
                resp.status_code, code, resp.headers.get("X-Request-Id"),
            )

            if resp.status_code == 401 and not refreshed:
                # A4: 401 수신 후 재발급은 요청당 1회만. 캐시를 무시하고 강제 발급.
                forced_token = _fetch_new_token(self._settings)
                refreshed = True
                continue
            if resp.status_code == 429:
                wait = _opt_float(resp.headers.get("Retry-After")) or 1.0
                time.sleep(max(0.0, min(wait, MAX_RETRY_WAIT)))
                continue
            if code in NON_RETRYABLE_CODES:
                raise error_for_code(code)
            if resp.status_code in RETRYABLE_STATUS:
                time.sleep(0.5 * 2**attempt)
                continue
            raise error_for_code(code or f"HTTP {resp.status_code}")

        raise BrokerAPIError("요청이 반복 실패했습니다")

    def fetch_exchange_rate(self) -> Decimal | None:
        try:
            data = self._request(
                "GET", "/api/v1/exchange-rate", group="MARKET_INFO",
                params={"baseCurrency": "USD", "quoteCurrency": "KRW"},
            )
            return _opt_decimal(_as_dict(data.get("result")).get("midRate"))
        except BrokerAPIError as e:
            logger.warning("환율 조회 실패: %s", type(e).__name__)
            return None

    def _fetch_buying_power(self, currency: str) -> Decimal:
        """USD 계좌가 없으면 0 또는 404가 올 수 있다 (§5.4). 둘 다 Decimal(0).

        음수·NaN 등 비정상 값도 여기서 0으로 정규화한다 — 이 값이 그대로
        `Portfolio(cash_krw=...)`에 들어가면 `ge=0`/`finite` 검증에 걸려
        `fetch_portfolio()`가 fx_rate까지 통째로 버리는 폴백 경로를 탄다.
        """
        try:
            data = self._request(
                "GET", "/api/v1/buying-power", group="ORDER_INFO",
                account_ctx=True, params={"currency": currency},
            )
            value = _opt_decimal(_as_dict(data.get("result")).get("cashBuyingPower"))
            return value if value is not None and value >= 0 else Decimal(0)
        except BrokerAPIError as e:
            logger.warning("현금(%s) 조회 실패, 0으로 처리: %s", currency, type(e).__name__)
            return Decimal(0)

    def fetch_portfolio(self) -> Portfolio:
        if self.account_seq is None:
            self.bootstrap()

        fx_rate = self.fetch_exchange_rate()

        data = self._request("GET", "/api/v1/holdings", group="ASSET", account_ctx=True)
        result = _as_dict(data.get("result"))

        holdings = []
        for row in _as_list(result.get("items")):
            h = _to_holding(row) if isinstance(row, dict) else None
            if h is not None:
                holdings.append(h)

        cash_krw = self._fetch_buying_power("KRW")
        cash_usd = self._fetch_buying_power("USD")
        daily_pnl_rate = _opt_float(_as_dict(result.get("dailyProfitLoss")).get("rate"))
        as_of = datetime.now(_KST)

        try:
            return Portfolio(
                account_no=self.account_no or "",
                as_of=as_of,
                cash_krw=cash_krw,
                cash_usd=cash_usd,
                fx_rate=fx_rate,
                daily_pnl_rate=daily_pnl_rate,
                holdings=holdings,
            )
        except ValidationError as e:
            # 현금 필드만 실패 원인일 가능성이 높으므로(수량·가격은 이미
            # _to_holding에서 개별 검증됨) fx_rate·daily_pnl_rate는 유지하고
            # 현금만 0으로 재시도한다. 여기서 통째로 버리면 USD 보유종목이
            # Holding.market_value_krw(fx_rate=None)에서 조용히 제외되어
            # 총자산이 실제보다 훨씬 작게(극단적으로는 0으로) 표시된다.
            logger.warning("포트폴리오 현금 필드 검증 실패, 현금 0으로 폴백: %s", type(e).__name__)
            return Portfolio(
                account_no=self.account_no or "",
                as_of=as_of,
                fx_rate=fx_rate,
                daily_pnl_rate=daily_pnl_rate,
                holdings=holdings,
            )

    def fetch_stock_meta(self, symbols: list[str]) -> dict[str, StockMeta]:
        if not symbols:
            return {}
        try:
            data = self._request(
                "GET", "/api/v1/stocks", group="STOCK",
                params={"symbols": ",".join(symbols)},
            )
        except BrokerAPIError as e:
            logger.warning("종목 메타 조회 실패: %s", type(e).__name__)
            return {}

        meta: dict[str, StockMeta] = {}
        for row in _as_list(data.get("result")):
            if not isinstance(row, dict):
                logger.warning("종목 메타 파싱 실패, 건너뜀: 응답 원소가 객체가 아님")
                continue
            try:
                symbol = row["symbol"]
                meta[symbol] = StockMeta(
                    symbol=symbol,
                    market=row.get("market", ""),
                    security_type=row.get("securityType", ""),
                    status=row.get("status", "ACTIVE"),
                    leverage_factor=_opt_decimal(row.get("leverageFactor")),
                )
            except (KeyError, ValidationError) as e:
                logger.warning("종목 메타 파싱 실패, 건너뜀: %s", type(e).__name__)
        return meta

    def fetch_price_history(self, symbols: list[str], days: int) -> pd.DataFrame:
        fx = self.fetch_exchange_rate()
        frames: dict[str, pd.Series] = {}

        for sym in symbols:
            try:
                data = self._request(
                    "GET", "/api/v1/candles", group="MARKET_DATA_CHART",
                    params={
                        "symbol": sym, "interval": "1d",
                        "count": min(200, max(days + 40, 60)), "adjusted": "true",
                    },
                )
                candles = _as_list(_as_dict(data.get("result")).get("candles"))
                if not candles:
                    logger.warning("가격 히스토리 없음, 종목 제외: %s", sym)
                    continue
                is_usd = any(_as_dict(c).get("currency") == "USD" for c in candles)
                if is_usd and fx is None:
                    # DATA_DESIGN §3.2 / FR-202a(P0): 환율 조회 실패 시 USD
                    # 종목을 원화 환산 없이 섞으면 안 된다 — 제외하고 경고.
                    logger.warning("환율 조회 실패로 USD 종목 제외 (FR-202a): %s", sym)
                    continue
                series = candles_to_series(candles, fx or Decimal(1))
            except (BrokerAPIError, KeyError, TypeError, ValueError, InvalidOperation) as e:
                logger.warning("가격 조회/파싱 실패, 종목 제외: %s (%s)", sym, type(e).__name__)
                continue
            if len(series) < MIN_VALID_PRICE_ROWS:
                # DATA_DESIGN §6: 유효 행 30 미만이면 제외. ffill로 섞으면
                # 다른 종목의 유효 기간까지 이 종목의 짧은 구간에 맞춰
                # 잘려나가거나, 반대로 상수 시계열이 표준편차 0으로 살아남는다.
                logger.warning(
                    "유효 가격 데이터 부족(<%d일), 종목 제외: %s (%d일)",
                    MIN_VALID_PRICE_ROWS, sym, len(series),
                )
                continue
            frames[sym] = series

        if not frames:
            raise PriceDataError("가격 데이터를 하나도 가져오지 못했습니다")
        prices = pd.DataFrame(frames).sort_index().ffill().dropna()
        return prices.tail(days)

    def fetch_benchmark_history(self, symbol: str, days: int) -> pd.Series:
        try:
            data = self._request(
                "GET", f"/api/v1/market-indicators/{symbol}/candles",
                group="MARKET_INDICATOR_CHART",
                params={"interval": "1d", "count": min(200, max(days + 40, 60))},
            )
            candles = _as_list(_as_dict(data.get("result")).get("candles"))
            if not candles:
                return pd.Series(dtype=float)
            s = pd.Series(
                {pd.to_datetime(c["timestamp"]).date():
                     float(Decimal(str(c["closePrice"]))) for c in candles},
            ).sort_index()
        except (BrokerAPIError, KeyError, TypeError, ValueError, InvalidOperation) as e:
            logger.warning("벤치마크 조회 실패: %s (%s)", symbol, type(e).__name__)
            return pd.Series(dtype=float)
        return s.tail(days)

    def fetch_risk_free_rate(self) -> float | None:
        """KR_BOND_3Y 금리를 소수비율로 변환한다 (위험 2, /100).

        DATA_DESIGN §6 검증표: `0 <= risk_free_rate <= 0.2`를 벗어나면
        단위 오류로 간주해 None을 반환한다(호출부가 설정 기본값으로
        폴백하고 `source="fallback"` 표기를 남길 수 있도록). 이 가드는
        `analytics/risk_metrics.sharpe_ratio`가 이미 갖고 있는 폴백(Phase
        3에서 analytics 내부에 두기로 결정된 것)과 다른 관심사를 지킨다 —
        화면에 표시되는 "무위험수익률" 원값과 그 출처(FR-207) 자체가
        오염되지 않게 하는 것이다.
        """
        try:
            data = self._request(
                "GET", "/api/v1/market-indicators/prices", group="MARKET_INDICATOR",
                params={"symbols": self._settings.risk_free_symbol},
            )
            items = _as_list(data.get("result"))
            if not items or not isinstance(items[0], dict):
                return None
            rate = _opt_decimal(items[0].get("lastPrice"))
            if rate is None:
                return None
            ratio = float(rate / 100)
            if not (0 <= ratio <= 0.2):
                logger.warning("무위험수익률이 유효 범위를 벗어남(단위 오류로 간주): %s", ratio)
                return None
            return ratio
        except (BrokerAPIError, KeyError, IndexError, TypeError):
            return None
