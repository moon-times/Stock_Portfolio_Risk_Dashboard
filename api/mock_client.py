import json
import logging
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
from pydantic import ValidationError

from config import Settings
from config import settings as default_settings
from models.holding import Holding
from models.portfolio import Portfolio
from models.stock_meta import StockMeta

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_PATH = Path("data/sample_portfolio.json")
TOKEN_PATH = Path("data/cache/token.json")
SAFETY_MARGIN = 60
MIN_VALID_PRICE_ROWS = 30
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_KST = ZoneInfo("Asia/Seoul")

# API_DESIGN §2.3 A5: 토큰 발급 실패는 프로세스 내에서 재시도하지 않는다
# (AUTH 레이트리밋 소모 방지). 종목별로 개별 재시도하면 20종목 조회 시
# 발급 실패 하나가 20번의 낭비 호출로 증폭된다.
_token_fetch_failed = False


def _load_cached_token() -> str | None:
    try:
        d = json.loads(TOKEN_PATH.read_text())
        if not isinstance(d, dict):
            return None
        if time.time() < float(d["expires_at"]) - SAFETY_MARGIN:
            return d["access_token"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        pass
    return None


def _save_token(access_token: str, expires_in: float) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps({
        "access_token": access_token,
        "expires_at": time.time() + float(expires_in),
    }))
    try:
        TOKEN_PATH.chmod(0o600)
    except (NotImplementedError, OSError):
        pass  # Windows: POSIX 권한 미지원


def _fetch_new_token(cfg: Settings) -> str | None:
    global _token_fetch_failed
    if _token_fetch_failed:
        return None
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
        _save_token(body["access_token"], body["expires_in"])
        return body["access_token"]
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as e:
        logger.warning("토큰 발급 실패, 이번 프로세스에서는 재시도하지 않음: %s", type(e).__name__)
        _token_fetch_failed = True
        return None


def _get_token(cfg: Settings) -> str | None:
    return _load_cached_token() or _fetch_new_token(cfg)


def _get_market_data(cfg: Settings, path: str, params: dict) -> dict | None:
    """읽기 전용 시세 엔드포인트 GET (계좌 컨텍스트 불필요).

    401 수신 시 토큰을 1회만 재발급해 재시도한다 (API_DESIGN §2.3 A4).
    스로틀링·지수 백오프 등 전체 재시도 정책은 Phase 5/6(api/errors.py,
    api/toss_client.py)에서 다룬다 — 여기서는 실패하면 조용히 None을
    반환해 목업 클라이언트가 절대 예외로 죽지 않도록만 한다.
    """
    token = _get_token(cfg)
    if token is None:
        return None

    def _call(bearer: str) -> httpx.Response:
        return httpx.get(
            f"{cfg.toss_base_url}{path}",
            params=params,
            headers={"Authorization": f"Bearer {bearer}"},
            timeout=_TIMEOUT,
        )

    try:
        resp = _call(token)
        if resp.status_code == 401:
            token = _fetch_new_token(cfg)
            if token is None:
                return None
            resp = _call(token)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("시세 조회 실패(%s): %s", path, type(e).__name__)
        return None


def _opt_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _candles_to_series(candles: list[dict], fx: Decimal) -> pd.Series:
    """캔들 응답 -> (날짜: 종가) Series. USD면 fx로 원화 환산.

    한 종목의 캔들 파싱 실패는 이 함수 호출부에서 통째로 스킵 처리한다
    (FR-204 — 종목 하나의 이상 데이터가 나머지를 죽이면 안 된다).
    """
    s = pd.Series(
        {pd.to_datetime(c["timestamp"]).date():
             Decimal(str(c["closePrice"])) for c in candles},
        dtype=object,
    ).sort_index()
    if candles[0].get("currency") == "USD":
        s = s.map(lambda v: v * fx)
    return s.map(float)


class MockBrokerClient:
    """`data/sample_portfolio.json`을 재생하는 폴백 클라이언트 (FR-104).

    보유종목·현금·환율·무위험수익률은 고정 샘플값을 쓰지만, 가격 히스토리는
    실존 종목이므로 실제 `/candles`를 호출한다 (DATA_DESIGN §7).
    """

    def __init__(
        self,
        fallback_reason: str,
        sample_path: Path | str = DEFAULT_SAMPLE_PATH,
        settings: Settings | None = None,
    ):
        self.fallback_reason = fallback_reason
        self._settings = settings or default_settings
        self._sample = json.loads(Path(sample_path).read_text(encoding="utf-8"))

    @property
    def is_live(self) -> bool:
        return False

    def fetch_portfolio(self) -> Portfolio:
        result = self._sample.get("holdings", {}).get("result", {})
        holdings = []
        for item in result.get("items", []):
            try:
                holdings.append(Holding(
                    ticker=str(item["symbol"]),
                    name=str(item.get("name") or item["symbol"]),
                    market_country=item.get("marketCountry", "KR"),
                    currency=item.get("currency", "KRW"),
                    quantity=Decimal(str(item["quantity"])),
                    avg_price=Decimal(str(item["averagePurchasePrice"])),
                    current_price=Decimal(str(item["lastPrice"])),
                    daily_pnl_rate=_opt_float(item.get("dailyProfitLoss", {}).get("rate")),
                ))
            except (KeyError, ValidationError, InvalidOperation, TypeError) as e:
                logger.warning(
                    "샘플 종목 파싱 실패, 건너뜀: %s symbol=%s",
                    type(e).__name__, item.get("symbol"),
                )

        buying_power = self._sample.get("buying_power", {})
        try:
            cash_krw = Decimal(str(buying_power.get("KRW") or 0))
        except InvalidOperation:
            cash_krw = Decimal(0)
        try:
            cash_usd = Decimal(str(buying_power.get("USD") or 0))
        except InvalidOperation:
            cash_usd = Decimal(0)

        daily_pnl_rate = _opt_float(result.get("dailyProfitLoss", {}).get("rate"))
        as_of = datetime.now(_KST)

        try:
            return Portfolio(
                account_no="00000000000",
                as_of=as_of,
                cash_krw=cash_krw,
                cash_usd=cash_usd,
                fx_rate=self.fetch_exchange_rate(),
                daily_pnl_rate=daily_pnl_rate,
                holdings=holdings,
                is_fallback=True,
                fallback_reason=self.fallback_reason,
            )
        except ValidationError as e:
            logger.warning("샘플 포트폴리오 전역 필드 검증 실패, 현금 0으로 폴백: %s", e)
            return Portfolio(
                account_no="00000000000",
                as_of=as_of,
                holdings=holdings,
                is_fallback=True,
                fallback_reason=self.fallback_reason,
            )

    def fetch_stock_meta(self, symbols: list[str]) -> dict[str, StockMeta]:
        wanted = set(symbols)
        meta: dict[str, StockMeta] = {}
        for s in self._sample.get("stocks", []):
            try:
                symbol = s["symbol"]
                if symbol not in wanted:
                    continue
                meta[symbol] = StockMeta(
                    symbol=symbol,
                    market=s["market"],
                    security_type=s["securityType"],
                    status=s.get("status", "ACTIVE"),
                )
            except (KeyError, ValidationError) as e:
                logger.warning("종목 메타 파싱 실패, 건너뜀: %s", type(e).__name__)
        return meta

    def fetch_price_history(self, symbols: list[str], days: int) -> pd.DataFrame:
        fx = self.fetch_exchange_rate() or Decimal(1)
        frames: dict[str, pd.Series] = {}

        for sym in symbols:
            data = _get_market_data(self._settings, "/api/v1/candles", {
                "symbol": sym, "interval": "1d",
                "count": min(200, max(days + 40, 60)), "adjusted": "true",
            })
            candles = ((data or {}).get("result") or {}).get("candles") or []
            if not candles:
                logger.warning("가격 히스토리 없음, 종목 제외: %s", sym)
                continue
            try:
                series = _candles_to_series(candles, fx)
            except (KeyError, TypeError, ValueError, InvalidOperation) as e:
                logger.warning("가격 파싱 실패, 종목 제외: %s (%s)", sym, type(e).__name__)
                continue
            if len(series) < MIN_VALID_PRICE_ROWS:
                # DATA_DESIGN §6: 유효 행 < 30이면 제외. ffill로 섞으면
                # 다른 종목의 유효 기간까지 이 종목의 짧은 구간에 맞춰
                # 잘려나가거나, 반대로 상수 시계열이 표준편차 0으로 살아남는다.
                logger.warning(
                    "유효 가격 데이터 부족(<%d일), 종목 제외: %s (%d일)",
                    MIN_VALID_PRICE_ROWS, sym, len(series),
                )
                continue
            frames[sym] = series

        if not frames:
            return pd.DataFrame()
        prices = pd.DataFrame(frames).sort_index().ffill().dropna()
        return prices.tail(days)

    def fetch_benchmark_history(self, symbol: str, days: int) -> pd.Series:
        data = _get_market_data(
            self._settings, f"/api/v1/market-indicators/{symbol}/candles",
            {"interval": "1d", "count": min(200, max(days + 40, 60))},
        )
        candles = ((data or {}).get("result") or {}).get("candles") or []
        if not candles:
            return pd.Series(dtype=float)
        try:
            s = pd.Series(
                {pd.to_datetime(c["timestamp"]).date():
                     float(Decimal(str(c["closePrice"]))) for c in candles},
            ).sort_index()
        except (KeyError, TypeError, ValueError, InvalidOperation) as e:
            logger.warning("벤치마크 파싱 실패: %s (%s)", symbol, type(e).__name__)
            return pd.Series(dtype=float)
        return s.tail(days)

    def fetch_risk_free_rate(self) -> float | None:
        try:
            return float(Decimal(str(self._sample["risk_free"]["lastPrice"])) / 100)
        except (KeyError, InvalidOperation, TypeError):
            return None

    def fetch_exchange_rate(self) -> Decimal | None:
        try:
            return Decimal(str(self._sample["exchange_rate"]["midRate"]))
        except (KeyError, InvalidOperation, TypeError):
            return None
