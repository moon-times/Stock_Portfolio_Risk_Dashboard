import pandas as pd
import pytest

from models.holding import AssetClass

from analytics.correlation import asset_class_correlation


def _sample_prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "A": [100, 102, 101, 105, 103, 107, 108, 110],
            "B": [50, 49, 51, 50, 52, 51, 53, 54],
        }
    )


class TestAssetClassCorrelationDiagonal:
    def test_diagonal_is_one(self):
        prices = _sample_prices()
        ticker_to_class = {"A": AssetClass.DOMESTIC_EQUITY, "B": AssetClass.BOND}
        weights = {"A": 1.0, "B": 1.0}

        result = asset_class_correlation(prices, ticker_to_class, weights)

        assert result is not None
        for i, row in enumerate(result.values):
            assert row[i] == pytest.approx(1.0, abs=0.01)


class TestAssetClassCorrelationSingleClass:
    def test_single_asset_class_returns_none(self):
        prices = _sample_prices()
        ticker_to_class = {
            "A": AssetClass.DOMESTIC_EQUITY,
            "B": AssetClass.DOMESTIC_EQUITY,
        }
        weights = {"A": 1.0, "B": 1.0}

        result = asset_class_correlation(prices, ticker_to_class, weights)

        assert result is None


class TestAssetClassCorrelationZeroWeightClass:
    def test_class_with_all_zero_weights_is_excluded(self):
        prices = _sample_prices()
        ticker_to_class = {"A": AssetClass.DOMESTIC_EQUITY, "B": AssetClass.BOND}
        weights = {"A": 1.0, "B": 0.0}  # B의 비중 합이 0 -> 제외

        result = asset_class_correlation(prices, ticker_to_class, weights)

        assert result is None  # 남는 자산군이 1개뿐이라 FR-504


class TestAssetClassCorrelationExcludesCash:
    def test_cash_with_zero_variance_price_is_excluded_not_crash(self):
        # 현금은 실제로 가격이 고정된(분산 0) 시계열로 들어올 수 있다
        # (예: 캐시 계층이 현금도 종목처럼 취급하는 경우). 그래도 예외 없이
        # 제외되어야 한다 (FR-303/FR-504 계열 원칙).
        prices = _sample_prices()
        prices["CASH"] = [1.0] * len(prices)
        ticker_to_class = {
            "A": AssetClass.DOMESTIC_EQUITY,
            "B": AssetClass.BOND,
            "CASH": AssetClass.CASH,
        }
        weights = {"A": 1.0, "B": 1.0, "CASH": 1.0}

        result = asset_class_correlation(prices, ticker_to_class, weights)

        assert result is not None
        assert AssetClass.CASH.value not in result.labels
        assert len(result.labels) == 2

    def test_cash_ticker_without_price_data_is_also_excluded(self):
        prices = _sample_prices()  # "CASH" 컬럼 없음 (가격 시계열이 없음)
        ticker_to_class = {
            "A": AssetClass.DOMESTIC_EQUITY,
            "B": AssetClass.BOND,
            "CASH": AssetClass.CASH,
        }
        weights = {"A": 1.0, "B": 1.0, "CASH": 1.0}

        result = asset_class_correlation(prices, ticker_to_class, weights)

        assert result is not None
        assert AssetClass.CASH.value not in result.labels
        assert len(result.labels) == 2


class TestAssetClassCorrelationDeterministicOrder:
    def test_label_order_is_stable_across_calls(self):
        prices = _sample_prices()
        prices["C"] = [10, 11, 10.5, 12, 11.5, 13, 12.5, 14]
        ticker_to_class = {
            "A": AssetClass.DOMESTIC_EQUITY,
            "B": AssetClass.BOND,
            "C": AssetClass.COMMODITY,
        }
        weights = {"A": 1.0, "B": 1.0, "C": 1.0}

        first = asset_class_correlation(prices, ticker_to_class, weights)
        second = asset_class_correlation(prices, ticker_to_class, weights)

        assert first is not None
        assert first.labels == second.labels
        assert first.labels == sorted(first.labels)
