import numpy as np
import pandas as pd
import pytest

from analytics.risk_metrics import (
    annualized_volatility,
    beta,
    herfindahl_index,
    historical_var,
    max_drawdown,
    sharpe_ratio,
)


class TestAnnualizedVolatility:
    def test_zero_variance_returns_zero(self):
        r = pd.Series([0.0] * 100)
        assert annualized_volatility(r) == pytest.approx(0.0)

    def test_insufficient_data_returns_none(self):
        assert annualized_volatility(pd.Series([0.01])) is None

    def test_empty_series_returns_none(self):
        assert annualized_volatility(pd.Series([], dtype=float)) is None

    def test_all_nan_returns_none(self):
        assert annualized_volatility(pd.Series([np.nan] * 10)) is None

    def test_dropna_ignores_missing_values(self):
        clean = pd.Series([0.01, -0.02, 0.03, -0.01, 0.02])
        with_nans = pd.Series([0.01, np.nan, -0.02, np.nan, 0.03, -0.01, 0.02])
        assert annualized_volatility(with_nans) == pytest.approx(
            annualized_volatility(clean)
        )


class TestSharpeRatio:
    def test_zero_variance_returns_none(self):
        r = pd.Series([0.0] * 100)
        assert sharpe_ratio(r, risk_free_rate=0.03) is None

    def test_negative_excess_return_is_negative(self):
        # DATA_DESIGN 예시([-0.001]*252)는 분산이 0이라 실제로는 None이 나오므로
        # (§4.2 "변동성 0" 규칙과 충돌) 분산이 0이 아닌 음의 초과수익 시계열로 검증한다.
        r = pd.Series([-0.001, -0.0015] * 126)
        result = sharpe_ratio(r, risk_free_rate=0.03)
        assert result is not None
        assert result < 0

    def test_unit_guard_at11_realistic_rate_stays_bounded(self):
        # AT-11 / 위험 2: risk_free_rate는 항상 소수비율(예: 3.25% -> 0.0325)로
        # 들어와야 한다. 올바른 단위를 쓰면 샤프지수 절댓값이 10을 넘지 않는다.
        rng = np.random.default_rng(7)
        r = pd.Series(rng.normal(0.0005, 0.01, 252))
        result = sharpe_ratio(r, risk_free_rate=0.0325)
        assert result is not None
        assert abs(result) <= 10

    def test_unit_guard_at11_out_of_range_rate_falls_back(self):
        # TDD_PLAN T-3.1 ★1 원문: risk_free_rate=3.25(단위 오입력)를 그대로
        # 넣어도 DATA_DESIGN §6("0<=r<=0.2 범위 밖이면 단위 오류로 간주,
        # 폴백값 사용")에 따라 내부적으로 폴백돼 |result|<=10을 유지해야 한다.
        rng = np.random.default_rng(7)
        r = pd.Series(rng.normal(0.0005, 0.01, 252))
        result = sharpe_ratio(r, risk_free_rate=3.25)
        assert result is not None
        assert abs(result) <= 10

    def test_negative_risk_free_rate_falls_back(self):
        rng = np.random.default_rng(7)
        r = pd.Series(rng.normal(0.0005, 0.01, 252))
        result = sharpe_ratio(r, risk_free_rate=-5.0)
        assert result is not None
        assert abs(result) <= 10

    def test_fallback_rate_is_actually_used(self):
        # risk_free_rate가 범위 밖일 때, 지정한 fallback_rate로 계산한 것과
        # 동일한 결과가 나오는지 직접 비교한다 (가드가 "그냥 통과"가 아니라
        # 실제로 폴백값을 대입하는지 검증).
        rng = np.random.default_rng(7)
        r = pd.Series(rng.normal(0.0005, 0.01, 252))
        out_of_range = sharpe_ratio(r, risk_free_rate=3.25, fallback_rate=0.05)
        with_fallback_directly = sharpe_ratio(r, risk_free_rate=0.05)
        assert out_of_range == pytest.approx(with_fallback_directly)

    def test_empty_series_returns_none(self):
        assert sharpe_ratio(pd.Series([], dtype=float), risk_free_rate=0.03) is None

    def test_single_point_returns_none(self):
        assert sharpe_ratio(pd.Series([0.01]), risk_free_rate=0.03) is None

    def test_all_nan_returns_none(self):
        assert sharpe_ratio(pd.Series([np.nan] * 10), risk_free_rate=0.03) is None


class TestMaxDrawdown:
    def test_known_drawdown(self):
        prices = pd.Series([100, 120, 90, 110])
        r = prices.pct_change().dropna()
        assert max_drawdown(r) == pytest.approx(-0.25)

    def test_monotonic_increase_returns_zero(self):
        prices = pd.Series([100, 110, 120])
        r = prices.pct_change().dropna()
        assert max_drawdown(r) == pytest.approx(0.0)

    def test_empty_series_returns_none(self):
        assert max_drawdown(pd.Series([], dtype=float)) is None

    def test_single_point_returns_none(self):
        assert max_drawdown(pd.Series([0.01])) is None

    def test_all_nan_returns_none(self):
        assert max_drawdown(pd.Series([np.nan] * 10)) is None


class TestHistoricalVar:
    def test_below_minimum_sample_size_returns_none(self):
        r = pd.Series([0.01] * 19)
        assert historical_var(r) is None

    def test_matches_pandas_quantile_at_minimum_sample_size(self):
        rng = np.random.default_rng(3)
        r = pd.Series(rng.normal(0.0, 0.02, 20))
        assert historical_var(r) == pytest.approx(float(r.quantile(0.05)))

    def test_empty_series_returns_none(self):
        assert historical_var(pd.Series([], dtype=float)) is None

    def test_all_nan_returns_none(self):
        assert historical_var(pd.Series([np.nan] * 25)) is None


class TestBeta:
    def _series(self, n=30, seed=1):
        rng = np.random.default_rng(seed)
        return pd.Series(rng.normal(0.0, 0.01, n))

    def test_self_beta_is_one(self):
        r = self._series()
        assert beta(r, r) == pytest.approx(1.0)

    def test_double_leverage_beta_is_two(self):
        r = self._series()
        assert beta(2 * r, r) == pytest.approx(2.0)

    def test_zero_variance_benchmark_returns_none(self):
        r = self._series()
        benchmark = pd.Series([0.0] * len(r))
        assert beta(r, benchmark) is None

    def test_empty_series_returns_none(self):
        empty = pd.Series([], dtype=float)
        assert beta(empty, empty) is None

    def test_below_minimum_overlap_returns_none(self):
        r = self._series(n=10)
        assert beta(r, r) is None


class TestHerfindahlIndex:
    def test_complete_concentration(self):
        assert herfindahl_index([1.0]) == pytest.approx(1.0)

    def test_five_equal_weights(self):
        assert herfindahl_index([0.2] * 5) == pytest.approx(0.2)

    def test_empty_input_returns_none(self):
        assert herfindahl_index([]) is None
