from pydantic import BaseModel, Field

from models.commentary import Commentary
from models.metrics import AllocationBreakdown, CorrelationMatrix, RiskMetrics
from models.portfolio import Portfolio


class DashboardData(BaseModel):
    """DashboardService.load()의 반환 타입 (DATA_DESIGN §2.8)."""

    portfolio: Portfolio
    allocation: AllocationBreakdown
    metrics: RiskMetrics
    correlation: CorrelationMatrix | None = None
    benchmark_series: dict[str, list[float]] | None = None
    benchmark_dates: list[str] | None = None
    commentary: Commentary | None = None
    daily_pnl_pct: float | None = None
    warnings: list[str] = Field(default_factory=list)
