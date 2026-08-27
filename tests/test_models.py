from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from models.commentary import Commentary
from models.holding import AssetClass, Currency, Holding, MarketCountry
from models.metrics import AllocationBreakdown, AllocationItem, CorrelationMatrix, RiskMetrics
from models.portfolio import Portfolio
from models.stock_meta import StockMeta


def make_holding(**overrides):
    defaults = dict(
        ticker="005930",
        name="삼성전자",
        market_country=MarketCountry.KR,
        currency=Currency.KRW,
        quantity=Decimal("10"),
        avg_price=Decimal("70000"),
        current_price=Decimal("75000"),
    )
    defaults.update(overrides)
    return Holding(**defaults)


class TestPortfolioAccountMasking:
    def test_masks_long_account_number(self):
        p = Portfolio(account_no="12345678901", as_of=datetime.now(UTC))
        assert p.account_no == "*******8901"

    def test_masks_short_account_number_boundary(self):
        p = Portfolio(account_no="123", as_of=datetime.now(UTC))
        assert p.account_no == "***"

    def test_masking_is_idempotent_on_roundtrip(self):
        p = Portfolio(account_no="12345678901", as_of=datetime.now(UTC))
        p2 = Portfolio(**p.model_dump())
        assert p2.account_no == "*******8901"


class TestStockMetaUnknownEnum:
    def test_unknown_security_type_does_not_raise(self):
        meta = StockMeta(symbol="XYZ", market="KOSPI", security_type="CRYPTO_ETP")
        assert meta.security_type == "CRYPTO_ETP"


class TestHoldingMarketValueKrw:
    def test_usd_holding_without_fx_rate_returns_none(self):
        h = make_holding(
            ticker="AAPL", currency=Currency.USD, market_country=MarketCountry.US,
            quantity=Decimal("10"), current_price=Decimal("200"),
        )
        assert h.market_value_krw(None) is None

    def test_krw_holding_without_fx_rate_returns_amount(self):
        h = make_holding(quantity=Decimal("10"), current_price=Decimal("75000"))
        assert h.market_value_krw(None) == Decimal("750000")


class TestHoldingUnrealizedPnlPct:
    def test_zero_avg_price_returns_zero_not_zerodivision(self):
        h = make_holding(avg_price=Decimal("0"), current_price=Decimal("100"))
        assert h.unrealized_pnl_pct == 0.0


class TestHoldingQuantityValidation:
    def test_negative_quantity_raises(self):
        with pytest.raises(ValidationError):
            make_holding(quantity=Decimal("-1"))


class TestPortfolioCashTotalKrw:
    def test_no_fx_rate_returns_krw_cash_only(self):
        p = Portfolio(
            account_no="12345678901", as_of=datetime.now(UTC),
            cash_krw=Decimal("1000000"), cash_usd=Decimal("100"), fx_rate=None,
        )
        assert p.cash_total_krw == Decimal("1000000")


class TestPortfolioTotalValue:
    def test_usd_holding_excluded_when_fx_rate_none(self):
        krw_holding = make_holding(quantity=Decimal("10"), current_price=Decimal("75000"))
        usd_holding = make_holding(
            ticker="AAPL", currency=Currency.USD, market_country=MarketCountry.US,
            quantity=Decimal("10"), current_price=Decimal("200"),
        )
        p = Portfolio(
            account_no="12345678901", as_of=datetime.now(UTC),
            cash_krw=Decimal("0"), fx_rate=None,
            holdings=[krw_holding, usd_holding],
        )
        assert p.total_value == Decimal("750000")


class TestCommentarySentenceLimit:
    def test_more_than_four_sentences_raises(self):
        with pytest.raises(ValidationError):
            Commentary(
                sentences=["a", "b", "c", "d", "e"],
                source="llm",
                generated_at=datetime.now(UTC),
            )

    def test_fewer_than_two_sentences_raises(self):
        # FR-703: 코멘트는 2~4문장이어야 한다
        with pytest.raises(ValidationError):
            Commentary(
                sentences=["a"],
                source="llm",
                generated_at=datetime.now(UTC),
            )


class TestCorrelationMatrixSquare:
    def test_non_square_matrix_raises(self):
        with pytest.raises(ValidationError):
            CorrelationMatrix(labels=["A", "B"], values=[[1.0, 0.5]])

    def test_diagonal_not_one_raises(self):
        # DATA_DESIGN §6: 정방행렬, 대각 = 1.0
        with pytest.raises(ValidationError):
            CorrelationMatrix(labels=["A", "B"], values=[[0.9, 0.5], [0.5, 1.0]])

    def test_value_outside_range_raises(self):
        # 상관계수는 항상 -1~1
        with pytest.raises(ValidationError):
            CorrelationMatrix(labels=["A", "B"], values=[[1.0, 1.5], [1.5, 1.0]])

    def test_valid_square_matrix_succeeds(self):
        m = CorrelationMatrix(labels=["A", "B"], values=[[1.0, 0.5], [0.5, 1.0]])
        assert m.labels == ["A", "B"]


class TestAllocationItemWeight:
    def test_weight_above_one_raises(self):
        with pytest.raises(ValidationError):
            AllocationItem(
                asset_class=AssetClass.DOMESTIC_EQUITY,
                market_value=Decimal("1000"),
                weight=1.5,
            )

    def test_weight_below_zero_raises(self):
        with pytest.raises(ValidationError):
            AllocationItem(
                asset_class=AssetClass.DOMESTIC_EQUITY,
                market_value=Decimal("1000"),
                weight=-0.1,
            )


class TestAllocationBreakdownWeightSum:
    def test_weight_sum_reflects_items(self):
        items = [
            AllocationItem(
                asset_class=AssetClass.DOMESTIC_EQUITY,
                market_value=Decimal("600"),
                weight=0.6,
            ),
            AllocationItem(
                asset_class=AssetClass.CASH,
                market_value=Decimal("400"),
                weight=0.4,
            ),
        ]
        breakdown = AllocationBreakdown(items=items, total_value=Decimal("1000"))
        assert breakdown.weight_sum == pytest.approx(1.0)


class TestRiskMetricsAllNone:
    def test_optional_metrics_default_to_none(self):
        m = RiskMetrics(lookback_days=126)
        assert m.annualized_volatility is None
        assert m.sharpe_ratio is None
        assert m.max_drawdown is None
        assert m.var_95 is None
        assert m.beta is None
        assert m.hhi is None
