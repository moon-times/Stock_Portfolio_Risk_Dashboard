from decimal import Decimal

from models.holding import AssetClass
from models.metrics import AllocationBreakdown, AllocationItem
from models.portfolio import Portfolio


def build_allocation(portfolio: Portfolio, fx_rate: Decimal | None) -> AllocationBreakdown:
    """자산군별 평가금액을 집계해 비중 내림차순으로 정렬한다 (FR-304, FR-306).

    USD 종목인데 fx_rate가 없으면 원화 환산이 불가능하므로 제외되고,
    나머지 자산군끼리 비중이 재정규화된다 (합계는 여전히 1.0).

    환율은 인자로 받은 fx_rate 하나만 쓴다. `portfolio.fx_rate`(예:
    `Portfolio.cash_total_krw`)를 섞어 쓰면 같은 화면 안에서 현금과
    보유종목이 서로 다른 환율로 환산되는 불일치가 생긴다.
    """
    values: dict[AssetClass, Decimal] = {}

    if fx_rate is not None:
        cash_total = portfolio.cash_krw + portfolio.cash_usd * fx_rate
    else:
        cash_total = portfolio.cash_krw
    if cash_total > 0:
        values[AssetClass.CASH] = values.get(AssetClass.CASH, Decimal(0)) + cash_total

    for h in portfolio.holdings:
        v = h.market_value_krw(fx_rate)
        if v is None:
            continue
        values[h.asset_class] = values.get(h.asset_class, Decimal(0)) + v

    total = sum(values.values(), Decimal(0))
    if total == 0:
        return AllocationBreakdown(items=[], total_value=Decimal(0))

    items = [
        AllocationItem(asset_class=ac, market_value=v, weight=float(v / total))
        for ac, v in values.items()
    ]
    items.sort(key=lambda i: i.weight, reverse=True)

    return AllocationBreakdown(items=items, total_value=total)
