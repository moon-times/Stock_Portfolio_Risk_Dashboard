"""Phase 7 관문: services/dashboard_service.py (TDD_PLAN §11 T-7.1/T-7.2).

TDD_PLAN이 지정한 검증 규약("해당 호출을 예외로 monkeypatch -> 앱 진행
확인")을 FakeBroker로 각 단계별로 재현한다. 모든 테스트는 Settings(_env_file=None,
use_mock_data=True)로 .env의 실제 토스 자격증명이 새어들지 않도록 격리한다
(tests/test_config.py와 동일한 안전장치).
"""

from datetime import datetime, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from api.errors import (
    AccountNotFoundError,
    AuthenticationError,
    BrokerAPIError,
    DashboardError,
    MaintenanceError,
    PriceDataError,
    RateLimitError,
)
from api.mock_client import MockBrokerClient
from api.toss_client import TossSecuritiesClient
from config import Settings
from config import settings as live_settings
from models.holding import AssetClass, Currency, Holding, MarketCountry
from models.portfolio import Portfolio
from models.stock_meta import StockMeta
from services.dashboard_service import DashboardService, create_broker_client

_SETTINGS_ENV_KEYS = [
    "TOSS_CLIENT_ID",
    "TOSS_CLIENT_SECRET",
    "TOSS_BASE_URL",
    "ANTHROPIC_API_KEY",
    "LOOKBACK_DAYS",
    "BENCHMARK_SYMBOL",
    "RISK_FREE_SYMBOL",
    "RISK_FREE_RATE_FALLBACK",
    "USE_MOCK_DATA",
]


@pytest.fixture(autouse=True)
def _isolated_settings_env(monkeypatch):
    for key in _SETTINGS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


# ----------------------------------------------------------------------
# 테스트 더블 / 픽스처 헬퍼
# ----------------------------------------------------------------------


class FakeBroker:
    """BrokerClient 프로토콜 테스트 더블. 각 메서드를 값 또는 예외로 개별 제어한다."""

    def __init__(
        self,
        *,
        portfolio=None,
        portfolio_exc=None,
        meta=None,
        meta_exc=None,
        prices=None,
        prices_exc=None,
        benchmark=None,
        benchmark_exc=None,
        rf=0.032,
        rf_exc=None,
        fx=Decimal(1300),
        fx_exc=None,
        is_live=True,
    ):
        self._portfolio = portfolio
        self._portfolio_exc = portfolio_exc
        self._meta = {} if meta is None else meta
        self._meta_exc = meta_exc
        self._prices = pd.DataFrame() if prices is None else prices
        self._prices_exc = prices_exc
        self._benchmark = pd.Series(dtype=float) if benchmark is None else benchmark
        self._benchmark_exc = benchmark_exc
        self._rf = rf
        self._rf_exc = rf_exc
        self._fx = fx
        self._fx_exc = fx_exc
        self._is_live = is_live

    @property
    def is_live(self) -> bool:
        return self._is_live

    def fetch_portfolio(self) -> Portfolio:
        if self._portfolio_exc:
            raise self._portfolio_exc
        return self._portfolio

    def fetch_stock_meta(self, symbols):
        if self._meta_exc:
            raise self._meta_exc
        return self._meta

    def fetch_price_history(self, symbols, days):
        if self._prices_exc:
            raise self._prices_exc
        return self._prices

    def fetch_benchmark_history(self, symbol, days):
        if self._benchmark_exc:
            raise self._benchmark_exc
        return self._benchmark

    def fetch_risk_free_rate(self):
        if self._rf_exc:
            raise self._rf_exc
        return self._rf

    def fetch_exchange_rate(self):
        if self._fx_exc:
            raise self._fx_exc
        return self._fx


def _holding(
    ticker,
    *,
    name="테스트종목",
    market_country=MarketCountry.KR,
    currency=Currency.KRW,
    quantity="10",
    avg_price="100",
    current_price="110",
    asset_class=AssetClass.OTHER,
) -> Holding:
    return Holding(
        ticker=ticker,
        name=name,
        market_country=market_country,
        currency=currency,
        quantity=Decimal(quantity),
        avg_price=Decimal(avg_price),
        current_price=Decimal(current_price),
        asset_class=asset_class,
    )


def _portfolio(holdings=None, *, cash_krw="100000", cash_usd="0", fx_rate="1300") -> Portfolio:
    return Portfolio(
        account_no="12345678901",
        as_of=datetime.now(timezone.utc),
        cash_krw=Decimal(cash_krw),
        cash_usd=Decimal(cash_usd),
        fx_rate=Decimal(fx_rate) if fx_rate is not None else None,
        holdings=holdings or [],
    )


def _prices(tickers, n=40, seed=42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    data = {t: 100 + np.cumsum(rng.normal(0, 1, n)) + i * 10 for i, t in enumerate(tickers)}
    return pd.DataFrame(data, index=dates)


def _benchmark_series(n=40, seed=7) -> pd.Series:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series(2500 + np.cumsum(rng.normal(0, 5, n)), index=dates)


def _default_broker(*, portfolio=None, meta=None, prices=None, benchmark=None, **kwargs) -> FakeBroker:
    """모든 단계가 성공하는 기본값을 채운 뒤, kwargs로 특정 단계만 실패시킨다."""
    portfolio = portfolio if portfolio is not None else _portfolio([_holding("005930")])
    if prices is None:
        tickers = [h.ticker for h in portfolio.holdings]
        prices = _prices(tickers) if tickers else pd.DataFrame()
    if benchmark is None:
        benchmark = _benchmark_series()
    if meta is None:
        meta = {}
    return FakeBroker(portfolio=portfolio, meta=meta, prices=prices, benchmark=benchmark, **kwargs)


def _service(broker: FakeBroker) -> DashboardService:
    svc = DashboardService(Settings(_env_file=None, use_mock_data=True))
    svc.broker = broker
    return svc


# ----------------------------------------------------------------------
# 단계 1: 환율
# ----------------------------------------------------------------------


class TestLoadFxRate:
    def test_success_sets_fx_rate_applied_and_no_warning(self):
        svc = _service(_default_broker(fx=Decimal(1300)))
        d = svc.load()
        assert d.metrics.fx_rate_applied == Decimal(1300)
        assert d.warnings == []

    @pytest.mark.parametrize("fx_exc,fx", [(BrokerAPIError("환율 API 다운"), None), (None, None)])
    def test_failure_or_none_warns_and_excludes_usd_assets(self, fx_exc, fx):
        # fetch_portfolio() 내부에서도 별도로 환율을 조회하므로(C-2), 이
        # 시나리오가 "환율을 아예 못 구했다"를 뜻하려면 portfolio.fx_rate도
        # 함께 None이어야 한다. 그렇지 않으면 서비스가 portfolio.fx_rate로
        # 정상 복구해 이 테스트의 전제가 깨진다.
        holdings = [
            _holding("005930", market_country=MarketCountry.KR, currency=Currency.KRW),
            _holding("AAPL", market_country=MarketCountry.US, currency=Currency.USD),
        ]
        portfolio = _portfolio(holdings, fx_rate=None)
        broker = _default_broker(portfolio=portfolio, fx=fx, fx_exc=fx_exc)
        svc = _service(broker)
        d = svc.load()

        assert d.metrics.fx_rate_applied is None
        assert d.portfolio.fx_rate is None
        assert any("환율" in w for w in d.warnings)
        classes = {item.asset_class for item in d.allocation.items}
        assert AssetClass.FOREIGN_EQUITY not in classes

    def test_recovers_fx_rate_from_portfolio_when_standalone_call_fails(self):
        # C-2 회귀 방지: 단독 fetch_exchange_rate()는 실패했지만
        # fetch_portfolio() 내부 조회가 성공한 경우, 서비스는 그 값으로
        # 복구해야 하고 총자산(portfolio.fx_rate)과 자산배분(fx_rate_applied)이
        # 서로 다른 환율을 쓰는 일이 없어야 한다.
        portfolio = _portfolio([_holding("005930")], fx_rate="1300")
        broker = _default_broker(portfolio=portfolio, fx=None)
        svc = _service(broker)
        d = svc.load()

        assert d.metrics.fx_rate_applied == Decimal(1300)
        assert d.portfolio.fx_rate == Decimal(1300)
        assert not any("환율" in w for w in d.warnings)

    def test_portfolio_and_allocation_use_single_unified_fx_rate(self):
        # C-2가 재현했던 정확한 실패 시나리오: 서비스 단독 fx 조회 실패 +
        # portfolio.fx_rate는 성공. total_value(암묵적으로 portfolio.fx_rate
        # 사용)와 allocation.total_value(fx_rate_applied 사용)가 같은 값을
        # 반영해야 한다.
        holdings = [
            _holding("005930", quantity="10", current_price="1000"),
            _holding("AAPL", market_country=MarketCountry.US, currency=Currency.USD, quantity="10", current_price="10"),
        ]
        portfolio = _portfolio(holdings, cash_krw="0", cash_usd="0", fx_rate="1300")
        broker = _default_broker(portfolio=portfolio, fx=None)
        svc = _service(broker)
        d = svc.load()

        assert d.portfolio.total_value == d.allocation.total_value


# ----------------------------------------------------------------------
# 단계 2: 포트폴리오
# ----------------------------------------------------------------------


class TestLoadPortfolio:
    def test_success_returns_holdings_as_is(self):
        portfolio = _portfolio([_holding("005930")])
        svc = _service(_default_broker(portfolio=portfolio))
        d = svc.load()
        assert len(d.portfolio.holdings) == 1
        assert d.portfolio.is_fallback is False

    @pytest.mark.parametrize("exc", [AuthenticationError("인증 실패"), AccountNotFoundError("계좌 없음")])
    def test_failure_falls_back_to_mock_portfolio(self, exc):
        svc = _service(_default_broker(portfolio_exc=exc))
        d = svc.load()
        assert d.portfolio.is_fallback is True

    def test_mock_fallback_construction_failure_returns_empty_portfolio(self, monkeypatch):
        # W-2: 최후의 안전망(목업 폴백 생성 자체)이 실패해도(샘플 데이터
        # 파일 손상/부재) NFR-201에 따라 앱은 죽지 않고 빈 포트폴리오를
        # 반환해야 한다.
        svc = _service(_default_broker(portfolio_exc=BrokerAPIError("primary broker down")))

        def _broken_init(self, *args, **kwargs):
            raise FileNotFoundError("sample file missing")

        monkeypatch.setattr(MockBrokerClient, "__init__", _broken_init)
        d = svc.load()
        assert d.portfolio.is_fallback is True
        assert d.portfolio.holdings == []
        assert len(d.warnings) >= 1


# ----------------------------------------------------------------------
# 단계 3: 종목 메타 + 분류
# ----------------------------------------------------------------------


class TestClassify:
    def test_success_meta_drives_classification(self):
        ticker = "999001"
        holding = _holding(ticker, name="테스트 리츠", market_country=MarketCountry.KR)
        portfolio = _portfolio([holding])
        meta = {ticker: StockMeta(symbol=ticker, market="KOSPI", security_type="REIT")}
        svc = _service(_default_broker(portfolio=portfolio, meta=meta))
        d = svc.load()
        by_ticker = {h.ticker: h.asset_class for h in d.portfolio.holdings}
        assert by_ticker[ticker] == AssetClass.REIT

    def test_meta_failure_falls_back_to_market_country(self):
        ticker = "005930"
        holding = _holding(ticker, market_country=MarketCountry.KR)
        portfolio = _portfolio([holding])
        svc = _service(_default_broker(portfolio=portfolio, meta_exc=BrokerAPIError("meta down")))
        d = svc.load()
        by_ticker = {h.ticker: h.asset_class for h in d.portfolio.holdings}
        assert by_ticker[ticker] == AssetClass.DOMESTIC_EQUITY


# ----------------------------------------------------------------------
# 단계 4: 자산배분
# ----------------------------------------------------------------------


class TestAllocation:
    def test_weights_sum_to_one(self):
        portfolio = _portfolio([_holding("005930"), _holding("000660")])
        svc = _service(_default_broker(portfolio=portfolio))
        d = svc.load()
        assert d.allocation.weight_sum == pytest.approx(1.0, abs=0.001)

    def test_empty_portfolio_no_crash(self):
        portfolio = _portfolio([], cash_krw="0", cash_usd="0")
        broker = _default_broker(portfolio=portfolio, prices=pd.DataFrame(), benchmark=pd.Series(dtype=float))
        svc = _service(broker)
        d = svc.load()
        assert d.allocation.items == []


# ----------------------------------------------------------------------
# 단계 5: 무위험수익률
# ----------------------------------------------------------------------


class TestRiskFreeRate:
    def test_success_uses_kr_bond_source(self):
        svc = _service(_default_broker(rf=0.032))
        d = svc.load()
        assert d.metrics.risk_free_rate == pytest.approx(0.032)
        assert d.metrics.risk_free_source == "KR_BOND_3Y"

    def test_none_falls_back_to_settings_default(self):
        svc = _service(_default_broker(rf=None))
        d = svc.load()
        assert d.metrics.risk_free_rate == pytest.approx(svc.settings.risk_free_rate_fallback)
        assert d.metrics.risk_free_source == "fallback"


# ----------------------------------------------------------------------
# 단계 6: 가격 히스토리 (+ excluded_tickers diff, S-1)
# ----------------------------------------------------------------------


class TestLoadPrices:
    def test_success_no_exclusions(self):
        portfolio = _portfolio([_holding("005930")])
        svc = _service(_default_broker(portfolio=portfolio))
        d = svc.load()
        assert d.metrics.excluded_tickers == []

    def test_total_failure_excludes_all_but_keeps_hhi(self):
        portfolio = _portfolio([_holding("005930")])
        broker = _default_broker(portfolio=portfolio, prices_exc=PriceDataError("network down"))
        svc = _service(broker)
        d = svc.load()
        assert d.metrics.excluded_tickers == ["005930"]
        assert d.metrics.hhi is not None
        assert d.metrics.annualized_volatility is None
        assert any("가격 데이터" in w for w in d.warnings)

    def test_partial_exclusion_via_column_diff(self):
        portfolio = _portfolio([_holding("005930"), _holding("000660")])
        prices = _prices(["005930"])  # "000660" 컬럼이 응답에서 빠짐
        svc = _service(_default_broker(portfolio=portfolio, prices=prices))
        d = svc.load()
        assert d.metrics.excluded_tickers == ["000660"]

    def test_columns_present_but_zero_rows_excludes_all(self):
        # W-4: 종목별 거래일이 겹치지 않아 ffill/dropna 후 컬럼은 남고
        # 행만 0개가 되는 경우, 컬럼 존재만으로 diff하면 "제외 없음"으로
        # 잘못 판정된다. empty 여부를 먼저 확인해야 한다.
        portfolio = _portfolio([_holding("005930"), _holding("000660")])
        prices = pd.DataFrame(columns=["005930", "000660"])
        svc = _service(_default_broker(portfolio=portfolio, prices=prices))
        d = svc.load()
        assert set(d.metrics.excluded_tickers) == {"005930", "000660"}
        assert d.metrics.annualized_volatility is None


# ----------------------------------------------------------------------
# 단계 7: 지표 (AT-11)
# ----------------------------------------------------------------------


class TestMetrics:
    def test_sharpe_ratio_within_at11_bound(self):
        # 가격 데이터가 항상 존재하는 결정론적 조건이므로 sharpe_ratio가
        # None이 아님을 먼저 단언한다 (W-6: 조건부 assert는 아무것도
        # 검증하지 않는 것과 같다).
        portfolio = _portfolio([_holding("005930")])
        svc = _service(_default_broker(portfolio=portfolio, rf=0.032))
        d = svc.load()
        assert d.metrics.sharpe_ratio is not None
        assert abs(d.metrics.sharpe_ratio) < 10


# ----------------------------------------------------------------------
# 단계 8: 상관관계 (P1)
# ----------------------------------------------------------------------


class TestCorrelation:
    def test_two_asset_classes_produces_matrix(self):
        h1 = _holding("999001", name="국고채10년 ETF")
        h2 = _holding("999002", name="골드선물 ETF")
        portfolio = _portfolio([h1, h2])
        meta = {
            "999001": StockMeta(symbol="999001", market="KOSPI", security_type="ETF"),
            "999002": StockMeta(symbol="999002", market="KOSPI", security_type="ETF"),
        }
        prices = _prices(["999001", "999002"])
        svc = _service(_default_broker(portfolio=portfolio, meta=meta, prices=prices))
        d = svc.load()
        assert d.correlation is not None
        assert len(d.correlation.labels) == len(d.correlation.values)

    def test_single_asset_class_returns_none(self):
        portfolio = _portfolio([_holding("005930"), _holding("000660")])
        svc = _service(_default_broker(portfolio=portfolio))
        d = svc.load()
        assert d.correlation is None


# ----------------------------------------------------------------------
# 단계 9: 벤치마크 비교 (P1, FR-601 시작점 100 지수화)
# ----------------------------------------------------------------------


class TestBenchmark:
    def test_success_produces_indexed_series(self):
        portfolio = _portfolio([_holding("005930")])
        svc = _service(_default_broker(portfolio=portfolio))
        d = svc.load()
        assert d.benchmark_series is not None
        assert d.benchmark_dates is not None
        assert "portfolio" in d.benchmark_series
        assert svc.settings.benchmark_symbol in d.benchmark_series
        assert len(d.benchmark_series["portfolio"]) == len(d.benchmark_dates)

    def test_both_series_start_at_100(self):
        # C-3 / FR-601 수용기준: "두 시계열 모두 첫값 100".
        portfolio = _portfolio([_holding("005930")])
        svc = _service(_default_broker(portfolio=portfolio))
        d = svc.load()
        assert d.benchmark_series["portfolio"][0] == pytest.approx(100.0)
        assert d.benchmark_series[svc.settings.benchmark_symbol][0] == pytest.approx(100.0)

    def test_failure_clears_series_and_beta(self):
        portfolio = _portfolio([_holding("005930")])
        broker = _default_broker(portfolio=portfolio, benchmark_exc=BrokerAPIError("bench down"))
        svc = _service(broker)
        d = svc.load()
        assert d.benchmark_series is None
        assert d.benchmark_dates is None
        assert d.metrics.beta is None


# ----------------------------------------------------------------------
# 단계 10: AI 코멘트 -- Phase 9 이전까지 항상 None
# ----------------------------------------------------------------------


class TestCommentaryStub:
    def test_always_none(self):
        svc = _service(_default_broker())
        d = svc.load()
        assert d.commentary is None


# ----------------------------------------------------------------------
# 교차 테스트: NFR-201 종합 스모크
# ----------------------------------------------------------------------


class TestNfr201Smoke:
    def test_all_broker_calls_failing_does_not_crash(self):
        # 서비스 레이어가 실제로 잡는 예외 타입 그대로 구성한다 (BrokerAPIError
        # 계열 + fetch_price_history만 PriceDataError). 두 구현체 모두 이 외의
        # 타입은 던지지 않는 게 확인된 계약이므로, 임의의 RuntimeError가 아니라
        # 이 계약을 그대로 재현해야 "예외를 못 잡는" 실제 회귀를 검출할 수 있다.
        boom = BrokerAPIError("boom")
        broker = FakeBroker(
            portfolio_exc=boom,
            meta_exc=boom,
            prices_exc=PriceDataError("boom"),
            benchmark_exc=boom,
            rf_exc=boom,
            fx_exc=boom,
        )
        svc = _service(broker)
        d = svc.load()  # 예외가 여기까지 전파되면 이 테스트 자체가 실패한다 (NFR-201)
        assert d.portfolio.is_fallback is True
        assert len(d.warnings) > 0


# ----------------------------------------------------------------------
# 교차 테스트: create_broker_client (T-7.2)
# ----------------------------------------------------------------------


class TestCreateBrokerClient:
    def test_use_mock_data_true_returns_mock(self):
        s = Settings(_env_file=None, use_mock_data=True)
        client = create_broker_client(s)
        assert isinstance(client, MockBrokerClient)

    def test_no_credentials_returns_mock(self):
        s = Settings(_env_file=None, use_mock_data=False, toss_client_id="", toss_client_secret="")
        client = create_broker_client(s)
        assert isinstance(client, MockBrokerClient)

    @pytest.mark.parametrize(
        "exc",
        [
            AuthenticationError("token invalid"),
            AccountNotFoundError("no account"),
            # C-1 회귀 방지: bootstrap()은 인증 실패 외에도 _request()를 거쳐
            # RateLimitError/MaintenanceError/미매핑 코드의 일반 BrokerAPIError를
            # 던질 수 있다(예: 네트워크 단절, IP 미등록). 좁은 except 튜플로
            # 인증 계열만 잡으면 이 경로들에서 앱이 그대로 죽는다.
            RateLimitError("429"),
            MaintenanceError("점검 중"),
            BrokerAPIError("ip-not-allowed"),
        ],
    )
    def test_bootstrap_failure_falls_back_to_mock(self, monkeypatch, exc):
        s = Settings(_env_file=None, use_mock_data=False, toss_client_id="x", toss_client_secret="y")

        def _fail(self):
            raise exc

        monkeypatch.setattr(TossSecuritiesClient, "bootstrap", _fail)
        client = create_broker_client(s)
        assert isinstance(client, MockBrokerClient)
        assert client.fallback_reason == "인증 실패"

    def test_bootstrap_success_returns_bare_toss_client(self, monkeypatch):
        """결정 1 회귀 방지: CachedBrokerClient로 감싸지 않는다."""
        s = Settings(_env_file=None, use_mock_data=False, toss_client_id="x", toss_client_secret="y")
        monkeypatch.setattr(TossSecuritiesClient, "bootstrap", lambda self: None)
        client = create_broker_client(s)
        assert type(client) is TossSecuritiesClient


# ----------------------------------------------------------------------
# 교차 테스트: 관문 7 자동화판 (실제 MockBrokerClient로 엔드투엔드)
# ----------------------------------------------------------------------


class TestEndToEndSmoke:
    # W-5: MockBrokerClient는 use_mock_data=True여도 가격/벤치마크 히스토리는
    # TossSecuritiesClient에 위임해 실제 네트워크를 탄다(DATA_DESIGN §7).
    # 자격증명이 없으면 조회가 조용히 실패해 sharpe_ratio가 None이 되고,
    # 그러면 AT-11 단언이 무엇도 검증하지 않는 채로 통과해버린다. 기존
    # tests/test_mock_client.py의 network 마커 관례를 그대로 따른다.
    @pytest.mark.network
    @pytest.mark.skipif(
        not live_settings.has_broker_credentials,
        reason="토스증권 자격증명 없음 - 네트워크 테스트 스킵",
    )
    def test_mock_broker_end_to_end(self):
        s = Settings(_env_file=None, use_mock_data=True)
        d = DashboardService(s).load()
        assert d.allocation.weight_sum == pytest.approx(1.0, abs=0.001)
        assert d.metrics.hhi is not None
        assert d.metrics.sharpe_ratio is not None
        assert abs(d.metrics.sharpe_ratio) < 10


# ----------------------------------------------------------------------
# 교차 테스트: §16 예외 -> 사용자 메시지 매핑 (NFR-304, W-7)
# ----------------------------------------------------------------------


class TestErrorMessageMapping:
    @pytest.mark.parametrize(
        "exc,expected_substring",
        [
            (AuthenticationError("x"), "인증"),
            (AccountNotFoundError("x"), "계좌를 찾을 수 없"),
            (RateLimitError("x"), "호출 한도"),
            (MaintenanceError("x"), "점검"),
            (PriceDataError("x"), "가격 데이터"),
            (BrokerAPIError("x"), "증권사 서버 응답"),
        ],
    )
    def test_known_exceptions_map_to_documented_message(self, exc, expected_substring):
        from services.dashboard_service import _message_for

        assert expected_substring in _message_for(exc)

    def test_unknown_dashboard_error_falls_back_to_generic_message(self):
        from services.dashboard_service import _message_for

        class _UnmappedError(DashboardError):
            pass

        assert _message_for(_UnmappedError("x")) == "알 수 없는 오류가 발생했습니다."

    def test_original_exception_message_never_leaks(self):
        """NFR-304: 원본 예외 메시지가 화면 문구에 그대로 섞여 나오면 안 된다."""
        from services.dashboard_service import _message_for

        secret = "액세스토큰=abcd1234"
        assert secret not in _message_for(AuthenticationError(secret))
