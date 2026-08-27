from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field


class AssetClass(StrEnum):
    DOMESTIC_EQUITY = "국내주식"
    FOREIGN_EQUITY = "해외주식"
    BOND = "채권"
    CASH = "현금"
    COMMODITY = "원자재"
    REIT = "리츠"
    OTHER = "기타"


class Currency(StrEnum):
    KRW = "KRW"
    USD = "USD"


class MarketCountry(StrEnum):
    KR = "KR"
    US = "US"


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
