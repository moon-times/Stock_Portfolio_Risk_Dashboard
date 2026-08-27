import json
from pathlib import Path

import pytest

from analytics.allocation import build_allocation
from analytics.classifier import classify, load_classifier_config
from analytics.correlation import asset_class_correlation
from api.mock_client import MockBrokerClient
from config import settings
from models.holding import AssetClass

ASSET_CLASS_MAP_PATH = "config/asset_class_map.yaml"


@pytest.fixture(scope="module")
def client() -> MockBrokerClient:
    return MockBrokerClient(fallback_reason="테스트")


@pytest.fixture(scope="module")
def classified_portfolio(client: MockBrokerClient):
    """UC-06 흐름: fetch_portfolio + fetch_stock_meta + classify()를 조합한다.

    이 조합은 실제로는 Phase 7 services/dashboard_service.py의 책임이지만,
    아직 만들어지지 않았으므로 Phase 4 관문 검증을 위해 테스트에서 직접 수행한다.
    """
    portfolio = client.fetch_portfolio()
    tickers = [h.ticker for h in portfolio.holdings]
    meta = client.fetch_stock_meta(tickers)
    cfg = load_classifier_config(ASSET_CLASS_MAP_PATH)

    for h in portfolio.holdings:
        holding_row = {
            "symbol": h.ticker,
            "name": h.name,
            "marketCountry": h.market_country.value,
        }
        h.asset_class = classify(holding_row, meta.get(h.ticker), cfg)
    return portfolio


def test_fetch_portfolio_returns_fallback_portfolio(client):
    portfolio = client.fetch_portfolio()
    assert portfolio.is_fallback is True
    assert len(portfolio.holdings) == 6


def test_etf_subclassification(classified_portfolio):
    by_ticker = {h.ticker: h.asset_class for h in classified_portfolio.holdings}
    assert by_ticker["148070"] == AssetClass.BOND       # KOSEF 국고채10년
    assert by_ticker["132030"] == AssetClass.COMMODITY  # KODEX 골드선물


def test_allocation_covers_five_asset_classes(classified_portfolio):
    allocation = build_allocation(classified_portfolio, classified_portfolio.fx_rate)
    classes = {item.asset_class for item in allocation.items}
    assert classes == {
        AssetClass.DOMESTIC_EQUITY,
        AssetClass.FOREIGN_EQUITY,
        AssetClass.BOND,
        AssetClass.CASH,
        AssetClass.COMMODITY,
    }


def test_allocation_weight_sum(classified_portfolio):
    allocation = build_allocation(classified_portfolio, classified_portfolio.fx_rate)
    assert abs(allocation.weight_sum - 1.0) <= 0.001


def test_is_live_is_false(client):
    assert client.is_live is False


def test_fetch_risk_free_rate_converts_percent_to_decimal(client):
    """API_DESIGN §9 단위 함정: lastPrice="3.25"는 3.25%이므로 100으로 나눠야 한다.

    Phase 3에서 sharpe_ratio가 실제로 이 단위 실수로 사고를 낸 적이 있다
    (AT-11). 목업의 고정 샘플값 경로에서도 같은 실수를 반복하지 않도록 고정한다.
    """
    rate = client.fetch_risk_free_rate()
    assert rate == pytest.approx(0.0325)


def test_fetch_exchange_rate_returns_mid_rate(client):
    assert client.fetch_exchange_rate() == pytest.approx(1376.0)


def test_malformed_holding_is_skipped_not_crashed(tmp_path: Path):
    """C-1 회귀 테스트: 종목 하나가 깨져도 fetch_portfolio()는 예외 없이

    나머지 종목만으로 Portfolio를 반환해야 한다 (FR-204).
    """
    sample = json.loads(Path("data/sample_portfolio.json").read_text(encoding="utf-8"))
    sample["holdings"]["result"]["items"][0]["quantity"] = None  # 파싱 불가
    sample_path = tmp_path / "broken_sample.json"
    sample_path.write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")

    broken_client = MockBrokerClient(fallback_reason="테스트", sample_path=sample_path)
    portfolio = broken_client.fetch_portfolio()

    assert portfolio.is_fallback is True
    assert len(portfolio.holdings) == 5  # 6개 중 깨진 1개만 스킵


@pytest.mark.network
@pytest.mark.skipif(
    not settings.has_broker_credentials,
    reason="토스증권 자격증명 없음 - 네트워크 테스트 스킵",
)
def test_correlation_matrix_at_least_2x2(client, classified_portfolio):
    """실제 /candles 호출이 필요하다 (DATA_DESIGN §7 — 목업도 가격은 실조회).

    IP 화이트리스트 미등록 등 네트워크 실패 시에는 스킵이 아니라 아래
    assert 메시지로 실패한다 — 조용히 넘어가면 재등록을 잊기 쉽다.
    """
    tickers = [h.ticker for h in classified_portfolio.holdings]
    prices = client.fetch_price_history(tickers, days=60)
    assert not prices.empty, "가격 히스토리를 하나도 못 가져왔습니다 (네트워크/토큰 확인 필요)"

    ticker_to_class = {h.ticker: h.asset_class for h in classified_portfolio.holdings}
    weights = {
        h.ticker: float(h.market_value_krw(classified_portfolio.fx_rate) or 0)
        for h in classified_portfolio.holdings
    }

    matrix = asset_class_correlation(prices, ticker_to_class, weights)
    assert matrix is not None
    assert len(matrix.labels) >= 2
