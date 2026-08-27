import pandas as pd
import pytest

from analytics.returns import portfolio_returns


class TestPortfolioReturns:
    def test_weighted_return_matches_manual_calculation(self):
        prices = pd.DataFrame(
            {
                "A": [100, 110, 121],
                "B": [200, 190, 209],
            }
        )
        weights = {"A": 0.6, "B": 0.4}
        result = portfolio_returns(prices, weights)

        rets = prices.pct_change().dropna(how="all")
        expected = rets["A"] * 0.6 + rets["B"] * 0.4
        pd.testing.assert_series_equal(result, expected, check_names=False)

    def test_renormalizes_when_weights_do_not_sum_to_one(self):
        prices = pd.DataFrame(
            {
                "A": [100, 110, 121],
                "B": [200, 190, 209],
            }
        )
        unnormalized = {"A": 3.0, "B": 2.0}  # 합 5.0, 하지만 비율은 0.6/0.4와 동일
        normalized = {"A": 0.6, "B": 0.4}

        result_unnormalized = portfolio_returns(prices, unnormalized)
        result_normalized = portfolio_returns(prices, normalized)

        pd.testing.assert_series_equal(
            result_unnormalized, result_normalized, check_names=False
        )

    def test_no_common_tickers_returns_empty_series(self):
        prices = pd.DataFrame({"A": [100, 110, 121]})
        weights = {"Z": 1.0}

        result = portfolio_returns(prices, weights)

        assert isinstance(result, pd.Series)
        assert result.empty
