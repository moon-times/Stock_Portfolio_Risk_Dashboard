from decimal import Decimal
from typing import Protocol, runtime_checkable

import pandas as pd

from models.portfolio import Portfolio
from models.stock_meta import StockMeta


@runtime_checkable
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
