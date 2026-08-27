from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, computed_field, field_validator

from models.holding import Holding


class Portfolio(BaseModel):
    account_no: str = Field(description="마스킹된 계좌번호")
    as_of: datetime
    cash_krw: Decimal = Field(
        default=Decimal(0), ge=0, description="buying-power KRW cashBuyingPower"
    )
    cash_usd: Decimal = Field(
        default=Decimal(0), ge=0, description="buying-power USD cashBuyingPower"
    )
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
        # 이미 마스킹된 값(캐시 직렬화 -> 역직렬화 등)은 그대로 통과시켜
        # 재마스킹으로 뒤 4자리까지 지워지는 것을 막는다.
        if "*" in v:
            return v
        digits = "".join(ch for ch in v if ch.isdigit())
        if len(digits) <= 4:
            return "*" * len(digits)
        return "*" * (len(digits) - 4) + digits[-4:]
