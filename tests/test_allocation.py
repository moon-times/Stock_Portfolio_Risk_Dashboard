from datetime import UTC, datetime
from decimal import Decimal

import pytest

from models.holding import AssetClass, Currency, Holding, MarketCountry
from models.portfolio import Portfolio

from analytics.allocation import build_allocation


def make_holding(**overrides):
    defaults = dict(
        ticker="005930",
        name="삼성전자",
        market_country=MarketCountry.KR,
        currency=Currency.KRW,
        quantity=Decimal("10"),
        avg_price=Decimal("70000"),
        current_price=Decimal("75000"),
        asset_class=AssetClass.DOMESTIC_EQUITY,
    )
    defaults.update(overrides)
    return Holding(**defaults)


class TestBuildAllocationWeightSum:
    def test_weights_sum_to_one(self):
        p = Portfolio(
            account_no="12345678901",
            as_of=datetime.now(UTC),
            cash_krw=Decimal("100000"),
            holdings=[
                make_holding(quantity=Decimal("10"), current_price=Decimal("75000")),
                make_holding(
                    ticker="132030",
                    name="KODEX 골드선물",
                    quantity=Decimal("50"),
                    current_price=Decimal("15000"),
                    asset_class=AssetClass.COMMODITY,
                ),
            ],
        )
        allocation = build_allocation(p, fx_rate=None)
        assert sum(i.weight for i in allocation.items) == pytest.approx(1.0, abs=0.001)


class TestBuildAllocationEmptyPortfolio:
    def test_no_cash_no_holdings_returns_empty_breakdown(self):
        p = Portfolio(
            account_no="12345678901",
            as_of=datetime.now(UTC),
            cash_krw=Decimal("0"),
            holdings=[],
        )
        allocation = build_allocation(p, fx_rate=None)
        assert allocation.items == []
        assert allocation.total_value == Decimal("0")


class TestBuildAllocationSorting:
    def test_items_sorted_descending_by_weight(self):
        p = Portfolio(
            account_no="12345678901",
            as_of=datetime.now(UTC),
            cash_krw=Decimal("100000"),
            holdings=[
                make_holding(quantity=Decimal("10"), current_price=Decimal("75000")),
                make_holding(
                    ticker="132030",
                    name="KODEX 골드선물",
                    quantity=Decimal("50"),
                    current_price=Decimal("15000"),
                    asset_class=AssetClass.COMMODITY,
                ),
            ],
        )
        allocation = build_allocation(p, fx_rate=None)
        weights = [i.weight for i in allocation.items]
        assert weights == sorted(weights, reverse=True)


class TestBuildAllocationUsdExclusion:
    def test_usd_holding_excluded_and_remaining_classes_renormalized(self):
        # KRW 자산군 2개(각 750,000원, fx_rate가 있었다면 USD가 훨씬 컸을 구성) +
        # USD 자산군 1개. fx_rate=None이면 USD가 빠지고, 남은 두 자산군의
        # 비중이 각각 0.5로 "재정규화"되는지(원래 비중보다 커지는지) 확인한다.
        p = Portfolio(
            account_no="12345678901",
            as_of=datetime.now(UTC),
            cash_krw=Decimal("0"),
            fx_rate=None,
            holdings=[
                make_holding(
                    quantity=Decimal("10"),
                    current_price=Decimal("75000"),
                    asset_class=AssetClass.DOMESTIC_EQUITY,
                ),
                make_holding(
                    ticker="132030",
                    name="KODEX 골드선물",
                    quantity=Decimal("50"),
                    current_price=Decimal("15000"),
                    asset_class=AssetClass.COMMODITY,
                ),
                make_holding(
                    ticker="AAPL",
                    name="Apple Inc.",
                    currency=Currency.USD,
                    market_country=MarketCountry.US,
                    quantity=Decimal("100"),
                    current_price=Decimal("2000"),  # fx_rate만 있었다면 압도적 비중
                    asset_class=AssetClass.FOREIGN_EQUITY,
                ),
            ],
        )
        allocation = build_allocation(p, fx_rate=None)

        classes = {i.asset_class for i in allocation.items}
        assert AssetClass.FOREIGN_EQUITY not in classes
        assert sum(i.weight for i in allocation.items) == pytest.approx(1.0, abs=0.001)
        # 재정규화 확인: 남은 두 자산군이 정확히 750,000 : 750,000 = 0.5 : 0.5
        weights = {i.asset_class: i.weight for i in allocation.items}
        assert weights[AssetClass.DOMESTIC_EQUITY] == pytest.approx(0.5, abs=0.001)
        assert weights[AssetClass.COMMODITY] == pytest.approx(0.5, abs=0.001)


class TestBuildAllocationFxRateSingleSource:
    def test_uses_argument_fx_rate_not_portfolio_fx_rate_for_cash(self):
        # Portfolio.fx_rate(1000)와 build_allocation에 넘긴 fx_rate(1400)가
        # 다르면, 인자로 받은 fx_rate가 유일한 출처여야 한다(이중 소스 금지).
        p = Portfolio(
            account_no="12345678901",
            as_of=datetime.now(UTC),
            cash_krw=Decimal("0"),
            cash_usd=Decimal("100"),
            fx_rate=Decimal("1000"),
            holdings=[],
        )
        allocation = build_allocation(p, fx_rate=Decimal("1400"))
        assert allocation.total_value == Decimal("140000")

    def test_fx_rate_none_excludes_usd_cash_even_if_portfolio_has_fx_rate(self):
        p = Portfolio(
            account_no="12345678901",
            as_of=datetime.now(UTC),
            cash_krw=Decimal("50000"),
            cash_usd=Decimal("100"),
            fx_rate=Decimal("1400"),
            holdings=[],
        )
        allocation = build_allocation(p, fx_rate=None)
        assert allocation.total_value == Decimal("50000")
