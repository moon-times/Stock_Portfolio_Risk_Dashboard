"""조회 -> 계산 -> 진단 오케스트레이션 (TRD 1.1, COMPONENT_DESIGN §2).

어떤 외부 실패도 위로 전파하지 않는다 (NFR-201). 각 단계는 자체
try/except를 갖고 실패 시 None 또는 부분값을 반환하며, 예외는
API_DESIGN §16 표 기준 사용자 메시지로 변환해 warnings에 담는다.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd

from analytics.allocation import build_allocation
from analytics.classifier import classify, load_classifier_config
from analytics.correlation import asset_class_correlation
from analytics.returns import portfolio_returns
from analytics.risk_metrics import (
    annualized_volatility,
    beta,
    herfindahl_index,
    historical_var,
    max_drawdown,
    sharpe_ratio,
)
from api.base import BrokerClient
from api.errors import (
    AccountNotFoundError,
    AuthenticationError,
    BrokerAPIError,
    DashboardError,
    ExchangeRateError,
    InsufficientDataError,
    MaintenanceError,
    PriceDataError,
    RateLimitError,
)
from api.mock_client import MockBrokerClient
from api.toss_client import TossSecuritiesClient
from config import Settings
from models.commentary import Commentary
from models.dashboard import DashboardData
from models.metrics import AllocationBreakdown, CorrelationMatrix, RiskMetrics
from models.portfolio import Portfolio
from models.stock_meta import StockMeta

logger = logging.getLogger(__name__)

ASSET_CLASS_MAP_PATH = "config/asset_class_map.yaml"

# API_DESIGN §16. 구체적 서브클래스가 먼저, 베이스 BrokerAPIError가 마지막
# (isinstance 순서 매칭이므로 상속 구조와 반대로 좁은 것부터 나열해야 한다).
_ERROR_MESSAGES: list[tuple[type[Exception], str]] = [
    (AuthenticationError, "증권사 인증에 실패했습니다. 샘플 데이터로 표시합니다."),
    (AccountNotFoundError, "사용 가능한 계좌를 찾을 수 없습니다."),
    (RateLimitError, "API 호출 한도에 도달했습니다. 캐시된 데이터를 표시합니다."),
    (MaintenanceError, "증권사 시스템 점검 중입니다. 캐시된 데이터를 표시합니다."),
    (PriceDataError, "가격 데이터를 가져오지 못했습니다. 일부 지표가 표시되지 않습니다."),
    (InsufficientDataError, "계산에 필요한 데이터가 부족합니다."),
    (ExchangeRateError, "환율을 가져오지 못해 해외 자산을 원화로 환산하지 못했습니다."),
    (BrokerAPIError, "증권사 서버 응답에 문제가 있습니다."),
]


def _message_for(exc: Exception) -> str:
    """NFR-304: 원본 예외 메시지를 그대로 노출하지 않고 §16 표 문구로 치환한다."""
    for exc_type, msg in _ERROR_MESSAGES:
        if isinstance(exc, exc_type):
            return msg
    return "알 수 없는 오류가 발생했습니다."


def create_broker_client(settings: Settings) -> BrokerClient:
    """T-7.2 / API_DESIGN §1.3 선택 로직.

    디스크 캐시 데코레이터(CachedBrokerClient)는 이번 Phase에서 만들지
    않는다 — 서비스 레벨 st.cache_data(ttl=300)가 캐싱을 담당한다(Phase 8).
    """
    if settings.use_mock_data or not settings.has_broker_credentials:
        return MockBrokerClient(fallback_reason="자격증명 없음", settings=settings)
    try:
        client = TossSecuritiesClient(settings)
        client.bootstrap()
        return client
    except BrokerAPIError as e:
        # AuthenticationError/AccountNotFoundError뿐 아니라 RateLimitError,
        # MaintenanceError, 미매핑 코드의 일반 BrokerAPIError, 연결 재시도
        # 소진 시의 BrokerAPIError까지 bootstrap()이 던질 수 있는 모든
        # 경로를 여기서 잡아야 한다 (한 번 좁게 잡았다가 인증 외 실패에서
        # 앱이 그대로 죽는 회귀가 있었다).
        logger.warning("증권사 연동 실패, 목업 폴백: %s", type(e).__name__)
        return MockBrokerClient(fallback_reason="인증 실패", settings=settings)


class DashboardService:
    """앱 전체에서 유일하게 "일을 시키는" 곳 (COMPONENT_DESIGN §2.1)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.broker = create_broker_client(settings)
        self.classifier_cfg = load_classifier_config(ASSET_CLASS_MAP_PATH)

    def load(self) -> DashboardData:
        """조회 -> 계산 -> 진단. 어떤 단계가 실패해도 부분 결과를 반환한다."""
        warnings: list[str] = []

        fx_rate = self._load_fx_rate()
        portfolio = self._load_portfolio(warnings)
        # C-2: fetch_portfolio()도 내부적으로 fetch_exchange_rate()를 따로
        # 호출해 portfolio.fx_rate를 채운다. 이 값과 위 fx_rate가 서로
        # 다르면 total_value(portfolio.fx_rate 기반)와 allocation(fx_rate
        # 기반)이 서로 다른 환율로 계산되어 같은 화면에서 숫자가 어긋난다
        # (analytics/allocation.py의 "환율은 인자 하나만 쓴다" 경고가 바로
        # 이 상황을 가리킨다). 둘을 단일 값으로 통일한다.
        if fx_rate is None:
            fx_rate = portfolio.fx_rate
        else:
            portfolio.fx_rate = fx_rate
        if fx_rate is None:
            warnings.append(_message_for(ExchangeRateError()))
        meta = self._load_stock_meta(portfolio)
        portfolio = self._classify(portfolio, meta)
        allocation = build_allocation(portfolio, fx_rate)
        rf, rf_source = self._load_risk_free_rate()
        prices, excluded = self._load_prices(portfolio, warnings)
        benchmark_prices = self._load_benchmark_prices(warnings)
        metrics = self._compute_metrics(
            portfolio, allocation, prices, benchmark_prices, rf, rf_source, excluded, fx_rate
        )
        correlation = self._compute_correlation(portfolio, prices, fx_rate)
        bench_series, bench_dates = self._load_benchmark(prices, benchmark_prices, portfolio, fx_rate)
        commentary = self._generate_commentary(allocation, metrics, correlation)

        return DashboardData(
            portfolio=portfolio,
            allocation=allocation,
            metrics=metrics,
            correlation=correlation,
            benchmark_series=bench_series,
            benchmark_dates=bench_dates,
            commentary=commentary,
            daily_pnl_pct=portfolio.daily_pnl_rate,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # 단계 1: 환율
    # ------------------------------------------------------------------
    def _load_fx_rate(self) -> Decimal | None:
        # fetch_exchange_rate()는 두 구현체(TossSecuritiesClient/MockBrokerClient)
        # 모두 내부에서 실패를 흡수하고 None을 반환하며 절대 밖으로 던지지
        # 않는다. DashboardError로 잡는 건 Protocol 계약을 지키지 않는
        # 구현체가 붙는 경우에 대한 방어다 (BrokerAPIError로 좁히면 이
        # 프로젝트 자신의 ExchangeRateError조차 못 잡는다).
        # 경고 append는 load()에서 portfolio.fx_rate와 통합 판정한 뒤 한다.
        try:
            return self.broker.fetch_exchange_rate()
        except DashboardError as e:
            logger.warning("환율 조회 실패: %s", type(e).__name__)
            return None

    # ------------------------------------------------------------------
    # 단계 2: 포트폴리오
    # ------------------------------------------------------------------
    def _load_portfolio(self, warnings: list[str]) -> Portfolio:
        # MockBrokerClient.fetch_portfolio()는 절대 raise하지 않지만,
        # TossSecuritiesClient.fetch_portfolio()는 bootstrap()/holdings 조회가
        # 실패 시 예외를 던질 수 있다 (예: 세션 중 토큰 재발급 실패).
        try:
            return self.broker.fetch_portfolio()
        except DashboardError as e:
            logger.warning("포트폴리오 조회 실패, 목업 폴백: %s", type(e).__name__)
            warnings.append(_message_for(e))
            try:
                fallback = MockBrokerClient(fallback_reason="포트폴리오 조회 실패", settings=self.settings)
                return fallback.fetch_portfolio()
            except (OSError, ValueError):
                # 목업 폴백조차 만들 수 없는 경우(샘플 데이터 파일 손상/부재).
                # 최후의 안전망이 스스로 죽으면 안 되므로 빈 포트폴리오를
                # 직접 반환한다 (NFR-201).
                logger.exception("목업 폴백 클라이언트 생성 실패, 빈 포트폴리오로 대체")
                return Portfolio(
                    account_no="00000000000",
                    as_of=datetime.now(timezone.utc),
                    is_fallback=True,
                    fallback_reason="포트폴리오 조회 실패",
                )

    # ------------------------------------------------------------------
    # 단계 3: 종목 메타 + 분류
    # ------------------------------------------------------------------
    def _load_stock_meta(self, portfolio: Portfolio) -> dict[str, StockMeta]:
        tickers = list(dict.fromkeys(h.ticker for h in portfolio.holdings))
        if not tickers:
            return {}
        try:
            return self.broker.fetch_stock_meta(tickers)
        except DashboardError as e:
            logger.warning("종목 메타 조회 실패, marketCountry 축약 분류로 대체: %s", type(e).__name__)
            return {}

    def _classify(self, portfolio: Portfolio, meta: dict[str, StockMeta]) -> Portfolio:
        # classify()는 절대 예외를 던지지 않는다 (FR-303) -> try/except 불필요.
        for h in portfolio.holdings:
            holding_row = {"symbol": h.ticker, "name": h.name, "marketCountry": h.market_country.value}
            h.asset_class = classify(holding_row, meta.get(h.ticker), self.classifier_cfg)
        return portfolio

    # ------------------------------------------------------------------
    # 단계 5: 무위험수익률
    # ------------------------------------------------------------------
    def _load_risk_free_rate(self) -> tuple[float, str]:
        try:
            rf = self.broker.fetch_risk_free_rate()
        except DashboardError as e:
            logger.warning("무위험수익률 조회 실패: %s", type(e).__name__)
            rf = None
        if rf is None:
            return self.settings.risk_free_rate_fallback, "fallback"
        return rf, "KR_BOND_3Y"

    # ------------------------------------------------------------------
    # 단계 6: 가격 히스토리
    # ------------------------------------------------------------------
    def _load_prices(self, portfolio: Portfolio, warnings: list[str]) -> tuple[pd.DataFrame | None, list[str]]:
        all_tickers = list(dict.fromkeys(h.ticker for h in portfolio.holdings))
        if not all_tickers:
            return None, []
        # MockBrokerClient.fetch_price_history()는 위임 대상(TossSecuritiesClient)의
        # 실패까지 전부 흡수해 절대 raise하지 않는다. TossSecuritiesClient는 전
        # 종목이 실패했을 때만 PriceDataError를 던진다(부분 실패는 컬럼 누락으로
        # 표현). DashboardError로 잡아 Protocol 계약을 지키지 않는 구현체까지
        # 방어한다.
        try:
            prices = self.broker.fetch_price_history(all_tickers, self.settings.lookback_days)
        except DashboardError as e:
            warnings.append(_message_for(e))
            return None, all_tickers

        # W-4: 종목별 거래일이 서로 겹치지 않으면 ffill/dropna 후 컬럼은
        # 전부 남아있는데 행이 0개인 경우가 있다 (toss_client.py의
        # `.ffill().dropna()`). 이때 컬럼 존재만으로 excluded를 계산하면
        # "제외된 종목 없음"으로 잘못 표시되므로 empty 여부를 먼저 본다.
        if prices.empty:
            warnings.append(_message_for(PriceDataError()))
            return None, all_tickers

        # S-1: fetch_price_history가 부분 실패한 종목 목록을 직접 반환하지
        # 않으므로, 요청 티커 대비 반환 컬럼 diff로 서비스 레이어가 계산한다.
        excluded = [t for t in all_tickers if t not in prices.columns]
        return prices, excluded

    def _load_benchmark_prices(self, warnings: list[str]) -> pd.Series | None:
        try:
            series = self.broker.fetch_benchmark_history(self.settings.benchmark_symbol, self.settings.lookback_days)
        except DashboardError as e:
            logger.warning("벤치마크 히스토리 조회 실패: %s", type(e).__name__)
            warnings.append(_message_for(PriceDataError()))
            return None
        if series is None or series.empty:
            warnings.append(_message_for(PriceDataError()))
            return None
        return series

    # ------------------------------------------------------------------
    # 가중치 (지표/상관관계 공유)
    # ------------------------------------------------------------------
    def _weights_for(self, portfolio: Portfolio, fx_rate: Decimal | None) -> dict[str, float]:
        weights: dict[str, float] = {}
        for h in portfolio.holdings:
            v = h.market_value_krw(fx_rate)
            if v is None or v <= 0:
                continue
            weights[h.ticker] = weights.get(h.ticker, 0.0) + float(v)
        return weights

    # ------------------------------------------------------------------
    # 단계 7: 지표
    # ------------------------------------------------------------------
    def _compute_metrics(
        self,
        portfolio: Portfolio,
        allocation: AllocationBreakdown,
        prices: pd.DataFrame | None,
        benchmark_prices: pd.Series | None,
        rf: float,
        rf_source: str,
        excluded: list[str],
        fx_rate: Decimal | None,
    ) -> RiskMetrics:
        # HHI는 자산군 비중(가격 데이터 무관)에 대해 계산하므로 prices가
        # None이어도 항상 채울 수 있다 (FR-406, DATA_DESIGN §4.6).
        hhi = herfindahl_index([item.weight for item in allocation.items])

        vol = sharpe = mdd = var95 = beta_val = None
        if prices is not None and not prices.empty:
            try:
                weights = self._weights_for(portfolio, fx_rate)
                port_returns = portfolio_returns(prices, weights)
                if not port_returns.empty:
                    vol = annualized_volatility(port_returns)
                    sharpe = sharpe_ratio(port_returns, rf, fallback_rate=self.settings.risk_free_rate_fallback)
                    mdd = max_drawdown(port_returns)
                    var95 = historical_var(port_returns)
                    if benchmark_prices is not None and not benchmark_prices.empty:
                        bench_returns = benchmark_prices.pct_change().dropna()
                        beta_val = beta(port_returns, bench_returns)
            except Exception:
                logger.exception("지표 계산 중 예상치 못한 오류")

        return RiskMetrics(
            risk_free_rate=rf,
            risk_free_source=rf_source,
            annualized_volatility=vol,
            sharpe_ratio=sharpe,
            max_drawdown=mdd,
            var_95=var95,
            beta=beta_val,
            hhi=hhi,
            lookback_days=self.settings.lookback_days,
            benchmark_symbol=self.settings.benchmark_symbol,
            fx_rate_applied=fx_rate,
            excluded_tickers=excluded,
        )

    # ------------------------------------------------------------------
    # 단계 8: 상관관계 (P1)
    # ------------------------------------------------------------------
    def _compute_correlation(
        self, portfolio: Portfolio, prices: pd.DataFrame | None, fx_rate: Decimal | None
    ) -> CorrelationMatrix | None:
        if prices is None or prices.empty:
            return None
        try:
            ticker_to_class = {h.ticker: h.asset_class for h in portfolio.holdings}
            weights = self._weights_for(portfolio, fx_rate)
            return asset_class_correlation(prices, ticker_to_class, weights)
        except Exception:
            logger.exception("상관관계 계산 중 예상치 못한 오류")
            return None

    # ------------------------------------------------------------------
    # 단계 9: 벤치마크 비교 (P1, FR-601 시작점 100 지수화)
    # ------------------------------------------------------------------
    def _load_benchmark(
        self,
        prices: pd.DataFrame | None,
        benchmark_prices: pd.Series | None,
        portfolio: Portfolio,
        fx_rate: Decimal | None,
    ) -> tuple[dict[str, list[float]] | None, list[str] | None]:
        if prices is None or prices.empty or benchmark_prices is None or benchmark_prices.empty:
            return None, None
        try:
            weights = self._weights_for(portfolio, fx_rate)
            port_returns = portfolio_returns(prices, weights)
            if port_returns.empty:
                return None, None
            bench_returns = benchmark_prices.pct_change().dropna()
            combined = pd.concat(
                [port_returns.rename("portfolio"), bench_returns.rename("benchmark")], axis=1
            ).dropna()
            if combined.empty:
                return None, None
            # FR-601: 두 시계열 모두 시작점 100. combined는 이미 수익률
            # 시계열(pct_change로 첫 행이 소실됨)이라 단순 cumprod*100은
            # 첫 값이 100*(1+r1)이 되어 정확히 100에서 시작하지 못한다.
            # 첫 행 기준으로 재정규화해 두 컬럼 모두 첫 값을 정확히
            # 100으로 고정한다 (상대적 변화율은 그대로 보존됨).
            cum = (1 + combined).cumprod()
            indexed = cum / cum.iloc[0] * 100.0
            series = {
                "portfolio": indexed["portfolio"].tolist(),
                self.settings.benchmark_symbol: indexed["benchmark"].tolist(),
            }
            dates = [d.date().isoformat() if hasattr(d, "date") else str(d) for d in indexed.index]
            return series, dates
        except Exception:
            logger.exception("벤치마크 비교 데이터 생성 중 예상치 못한 오류")
            return None, None

    # ------------------------------------------------------------------
    # 단계 10: AI 코멘트 -- Phase 9(ai/)에서 구현 예정. 지금은 항상 None.
    # ------------------------------------------------------------------
    def _generate_commentary(
        self,
        allocation: AllocationBreakdown,
        metrics: RiskMetrics,
        correlation: CorrelationMatrix | None,
    ) -> Commentary | None:
        return None
