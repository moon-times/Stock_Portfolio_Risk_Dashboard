from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

from models.holding import AssetClass


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


class CorrelationMatrix(BaseModel):
    labels: list[str]
    values: list[list[float]]

    @model_validator(mode="after")
    def _check_square(self):
        # DATA_DESIGN §6: 정방행렬, 대각 = 1.0, 값은 항상 -1~1
        n = len(self.labels)
        if len(self.values) != n or not all(len(row) == n for row in self.values):
            raise ValueError("CorrelationMatrix values must be an n x n square matrix matching labels")
        for row in self.values:
            for v in row:
                if not (-1.0 <= v <= 1.0):
                    raise ValueError("CorrelationMatrix values must be within [-1, 1]")
        for i in range(n):
            if abs(self.values[i][i] - 1.0) > 1e-9:
                raise ValueError("CorrelationMatrix diagonal must be 1.0")
        return self
