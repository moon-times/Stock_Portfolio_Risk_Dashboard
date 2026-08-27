import json
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import ValidationError

from api.errors import DashboardError
from api.toss_client import TossSecuritiesClient
from config import Settings
from config import settings as default_settings
from models.holding import Holding
from models.portfolio import Portfolio
from models.stock_meta import StockMeta

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_PATH = Path("data/sample_portfolio.json")
_KST = ZoneInfo("Asia/Seoul")


def _opt_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class MockBrokerClient:
    """`data/sample_portfolio.json`을 재생하는 폴백 클라이언트 (FR-104).

    보유종목·현금·환율·무위험수익률은 고정 샘플값을 쓰지만, 가격 히스토리는
    실존 종목이므로 실제 `/candles`를 호출한다 (DATA_DESIGN §7). 그 조회는
    `TossSecuritiesClient`에 위임한다 — 토큰/스로틀/재시도 정책을 이중으로
    구현하지 않기 위함이다 (Phase 4 결정: "최소 클라이언트를 임시로 만들고
    Phase 6에서 toss_client.py로 흡수한다"). candles·market-indicators
    엔드포인트는 계좌 컨텍스트가 필요 없어 `bootstrap()` 없이도 호출 가능하다.
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
        self._toss = TossSecuritiesClient(self._settings)

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
        fx_rate = self.fetch_exchange_rate()

        try:
            return Portfolio(
                account_no="00000000000",
                as_of=as_of,
                cash_krw=cash_krw,
                cash_usd=cash_usd,
                fx_rate=fx_rate,
                daily_pnl_rate=daily_pnl_rate,
                holdings=holdings,
                is_fallback=True,
                fallback_reason=self.fallback_reason,
            )
        except ValidationError as e:
            # fx_rate/daily_pnl_rate는 현금과 무관하므로 유지한다 — 통째로
            # 버리면 USD 보유종목이 market_value_krw(fx_rate=None)에서
            # 조용히 빠져 총자산이 실제보다 작게 표시된다 (toss_client.py의
            # 동일 패턴 버그와 같은 이유로 수정).
            logger.warning("샘플 포트폴리오 현금 필드 검증 실패, 현금 0으로 폴백: %s", type(e).__name__)
            return Portfolio(
                account_no="00000000000",
                as_of=as_of,
                fx_rate=fx_rate,
                daily_pnl_rate=daily_pnl_rate,
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
        """DATA_DESIGN §7: 목업도 가격은 실조회. TossSecuritiesClient에 위임한다.

        위임 대상은 실제 네트워크·서버 응답을 다루므로 정상적으로 예외를
        던질 수 있다(PriceDataError는 종목 전부 실패 시 §7.4, 그 외에도
        예상 밖 응답 형태면 KeyError/TypeError/ValueError 계열이 날 수
        있다). 목업 클라이언트는 "실 API가 흔들려도 화면은 뜬다"는 FR-104
        폴백 계약을 지켜야 하므로 여기서 최종적으로 흡수한다.
        """
        try:
            return self._toss.fetch_price_history(symbols, days)
        except (DashboardError, KeyError, TypeError, ValueError, InvalidOperation) as e:
            logger.warning("가격 히스토리 조회 실패, 빈 결과로 대체: %s", type(e).__name__)
            return pd.DataFrame()

    def fetch_benchmark_history(self, symbol: str, days: int) -> pd.Series:
        try:
            return self._toss.fetch_benchmark_history(symbol, days)
        except (DashboardError, KeyError, TypeError, ValueError, InvalidOperation) as e:
            logger.warning("벤치마크 조회 실패, 빈 결과로 대체: %s (%s)", symbol, type(e).__name__)
            return pd.Series(dtype=float)

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
