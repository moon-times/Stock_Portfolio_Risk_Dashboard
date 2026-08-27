from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel


class Market(StrEnum):
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"
    KR_ETC = "KR_ETC"
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"
    AMEX = "AMEX"
    US_ETC = "US_ETC"


class SecurityType(StrEnum):
    STOCK = "STOCK"
    FOREIGN_STOCK = "FOREIGN_STOCK"
    DEPOSITARY_RECEIPT = "DEPOSITARY_RECEIPT"
    INFRASTRUCTURE_FUND = "INFRASTRUCTURE_FUND"
    REIT = "REIT"
    ETF = "ETF"
    FOREIGN_ETF = "FOREIGN_ETF"
    ETN = "ETN"
    STOCK_WARRANTS = "STOCK_WARRANTS"


class StockMeta(BaseModel):
    """GET /api/v1/stocks 응답 매핑.

    market·security_type은 str로 보관한다. 토스증권이 새 enum 값을
    추가해도 unknown enum을 허용해야 하므로 StrEnum으로 강제 파싱하지 않는다
    (DATA_DESIGN §5.4).
    """

    symbol: str
    market: str
    security_type: str
    status: str = "ACTIVE"
    leverage_factor: Decimal | None = None
