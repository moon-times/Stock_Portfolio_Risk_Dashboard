"""api/toss_client.py 매핑 + 재시도 정책 테스트 (TDD_PLAN T-6.1, T-6.2).

httpx.MockTransport로 응답을 흉내낸다 — 실제 네트워크 호출은 하지 않는다
(COMPONENT_DESIGN §6: api/는 httpx mock으로 응답 파싱만 검증).
"""

from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from api import token_store, toss_client
from api.errors import (
    AccountNotFoundError,
    AuthenticationError,
    BrokerAPIError,
    MaintenanceError,
    PriceDataError,
)
from api.toss_client import (
    MAX_RETRY_WAIT,
    TossSecuritiesClient,
    _opt_decimal,
    _to_holding,
    candles_to_series,
    resolve_account,
)
from config import Settings


def _settings() -> Settings:
    return Settings(_env_file=None, toss_client_id="test-id", toss_client_secret="test-secret")


def _client_with_transport(handler, settings=None) -> TossSecuritiesClient:
    client = TossSecuritiesClient(settings or _settings())
    client._http = httpx.Client(
        transport=httpx.MockTransport(handler), base_url=client._settings.toss_base_url
    )
    return client


def _seed_cached_token(token: str = "cached-token") -> None:
    token_store.save_token(token, expires_in=3600)


@pytest.fixture(autouse=True)
def isolated_token_path(tmp_path, monkeypatch):
    monkeypatch.setattr(token_store, "TOKEN_PATH", tmp_path / "token.json")


@pytest.fixture(autouse=True)
def reset_token_fetch_failed_flag(monkeypatch):
    monkeypatch.setattr(toss_client, "_token_fetch_failed", False)


class TestResolveAccount:
    def test_prefers_brokerage_account(self):
        accounts = [
            {"accountNo": "1", "accountSeq": 1, "accountType": "OVERSEAS_DERIVATIVES"},
            {"accountNo": "2", "accountSeq": 2, "accountType": "BROKERAGE"},
        ]
        seq, no = resolve_account(accounts)
        assert (seq, no) == (2, "2")

    def test_falls_back_to_first_account_when_no_brokerage(self):
        accounts = [{"accountNo": "9", "accountSeq": 9, "accountType": "PENSION_SAVINGS"}]
        assert resolve_account(accounts) == (9, "9")

    def test_unknown_account_type_does_not_crash(self):
        # 스펙 명시: unknown enum을 허용해야 한다 (§3.3).
        accounts = [{"accountNo": "1", "accountSeq": 1, "accountType": "완전히-새로운-타입"}]
        assert resolve_account(accounts) == (1, "1")

    def test_empty_accounts_raises_account_not_found(self):
        with pytest.raises(AccountNotFoundError):
            resolve_account([])

    def test_malformed_account_raises_account_not_found_not_generic_exception(self):
        with pytest.raises(AccountNotFoundError):
            resolve_account([{"accountType": "BROKERAGE"}])  # accountSeq/accountNo 없음

    def test_non_dict_elements_do_not_crash(self):
        # 서버가 뒤틀린 JSON(배열 원소가 객체가 아님)을 보내도 list comprehension이
        # AttributeError('str' object has no attribute 'get')로 죽으면 안 된다.
        with pytest.raises(AccountNotFoundError):
            resolve_account(["a", "b", 123])


class TestOptDecimal:
    # W-3: Decimal("NaN")/Decimal("Infinity")는 InvalidOperation을 던지지 않고
    # 조용히 통과하는 값이라 별도로 막아야 한다.
    @pytest.mark.parametrize("bad", ["NaN", "nan", "Infinity", "-Infinity"])
    def test_non_finite_values_return_none(self, bad):
        assert _opt_decimal(bad) is None

    def test_none_returns_none(self):
        assert _opt_decimal(None) is None

    def test_valid_number_string_parses(self):
        assert _opt_decimal("1376.5") == Decimal("1376.5")


class TestCandlesToSeries:
    def test_krw_candles_are_not_converted(self):
        candles = [{"timestamp": "2026-03-25T09:00:00+09:00", "closePrice": "72000", "currency": "KRW"}]
        s = candles_to_series(candles, fx=Decimal(1376))
        assert s.iloc[0] == pytest.approx(72000.0)

    def test_usd_candles_are_converted_by_fx_rate(self):
        candles = [{"timestamp": "2026-03-25T09:00:00+09:00", "closePrice": "10", "currency": "USD"}]
        s = candles_to_series(candles, fx=Decimal(1376))
        assert s.iloc[0] == pytest.approx(13760.0)

    def test_usd_detected_even_when_first_candle_lacks_currency_key(self):
        # W-4: 첫 원소만 보고 판정하면 이 케이스에서 환산이 통째로 생략된다.
        candles = [
            {"timestamp": "2026-03-24T09:00:00+09:00", "closePrice": "9"},
            {"timestamp": "2026-03-25T09:00:00+09:00", "closePrice": "10", "currency": "USD"},
        ]
        s = candles_to_series(candles, fx=Decimal(1376))
        assert s.iloc[0] == pytest.approx(9 * 1376.0)
        assert s.iloc[1] == pytest.approx(10 * 1376.0)


class TestToHolding:
    # T-6.1 #1: 문자열 수량이 Decimal로 파싱된다 (float() 금지, FR-106a).
    def test_string_quantity_becomes_decimal(self):
        row = {
            "symbol": "005930", "name": "삼성전자", "marketCountry": "KR", "currency": "KRW",
            "quantity": "100", "averagePurchasePrice": "65000", "lastPrice": "72000",
        }
        h = _to_holding(row)
        assert h is not None
        assert h.quantity == Decimal(100)
        assert isinstance(h.quantity, Decimal)

    # T-6.1 #4: 필수 키가 없는 종목은 예외 대신 None (해당 종목만 제외).
    def test_missing_required_key_returns_none_not_raises(self):
        assert _to_holding({"symbol": "005930"}) is None

    # T-6.1 #5: lastPrice가 파싱 불가 문자열이면 예외 대신 None.
    def test_unparseable_last_price_returns_none_not_raises(self):
        row = {
            "symbol": "005930", "name": "삼성전자", "marketCountry": "KR", "currency": "KRW",
            "quantity": "100", "averagePurchasePrice": "65000", "lastPrice": "not-a-number",
        }
        assert _to_holding(row) is None

    def test_missing_daily_pnl_defaults_to_none_not_raises(self):
        row = {
            "symbol": "AAPL", "name": "Apple", "marketCountry": "US", "currency": "USD",
            "quantity": "10", "averagePurchasePrice": "200", "lastPrice": "210",
        }
        h = _to_holding(row)
        assert h is not None
        assert h.daily_pnl_rate is None


class TestFetchPortfolio:
    def test_one_malformed_item_is_skipped_others_kept(self):
        _seed_cached_token()

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/api/v1/exchange-rate":
                return httpx.Response(200, json={"result": {"midRate": "1376.0"}}, request=request)
            if path == "/api/v1/holdings":
                return httpx.Response(200, json={"result": {
                    "dailyProfitLoss": {"rate": "0.01"},
                    "items": [
                        {"symbol": "005930", "name": "삼성전자", "marketCountry": "KR",
                         "currency": "KRW", "quantity": "100",
                         "averagePurchasePrice": "65000", "lastPrice": "72000"},
                        {"symbol": "BROKEN"},  # 필수 필드 누락 -> 이 종목만 제외돼야 함
                    ],
                }}, request=request)
            if path == "/api/v1/buying-power":
                return httpx.Response(200, json={"result": {"cashBuyingPower": "1000000"}}, request=request)
            raise AssertionError(f"unexpected path: {path}")

        client = _client_with_transport(handler)
        client.account_seq, client.account_no = 1, "12345678901"

        portfolio = client.fetch_portfolio()
        assert len(portfolio.holdings) == 1
        assert portfolio.holdings[0].ticker == "005930"
        assert portfolio.account_no == "*******8901"  # FR-105: Portfolio가 자동 마스킹


class TestBuyingPowerNullGuard:
    """위험3(Price.usd == null)의 실제 발현 지점.

    우리 도메인 모델은 top-level marketValue.amount(krw/usd dict)를 전혀 소비하지
    않는다 (Portfolio.total_value는 holdings에서 bottom-up으로 계산됨, Holding의
    market_value_native는 computed_field라 API 값을 받지도 않는다). 대신 동일한
    "널 가능 금액 필드" 패턴이 실제로 발현하는 곳은 buying-power다 — USD 서브계좌가
    없는 계좌는 cashBuyingPower가 null이거나 필드 자체가 없을 수 있다 (API_DESIGN §5.4).
    """

    def test_null_cash_buying_power_returns_zero_not_crash(self):
        _seed_cached_token()

        def handler(request):
            return httpx.Response(200, json={"result": {"currency": "USD", "cashBuyingPower": None}}, request=request)

        client = _client_with_transport(handler)
        client.account_seq = 1
        assert client._fetch_buying_power("USD") == Decimal(0)

    def test_missing_cash_buying_power_field_returns_zero_not_crash(self):
        _seed_cached_token()

        def handler(request):
            return httpx.Response(200, json={"result": {"currency": "USD"}}, request=request)

        client = _client_with_transport(handler)
        client.account_seq = 1
        assert client._fetch_buying_power("USD") == Decimal(0)


class TestFetchExchangeRate:
    def test_null_mid_rate_returns_none_not_crash(self):
        _seed_cached_token()

        def handler(request):
            return httpx.Response(200, json={"result": {"midRate": None}}, request=request)

        client = _client_with_transport(handler)
        assert client.fetch_exchange_rate() is None


class TestFetchRiskFreeRate:
    # T-6.1 #6: lastPrice="3.25" (3.25%) -> 0.0325 (위험2, /100 변환).
    def test_converts_percent_string_to_decimal_ratio(self):
        _seed_cached_token()

        def handler(request):
            return httpx.Response(200, json={"result": [{"symbol": "KR_BOND_3Y", "lastPrice": "3.25"}]}, request=request)

        client = _client_with_transport(handler)
        assert client.fetch_risk_free_rate() == pytest.approx(0.0325)

    # T-6.1 #7: 빈 배열 -> None.
    def test_empty_result_returns_none(self):
        _seed_cached_token()

        def handler(request):
            return httpx.Response(200, json={"result": []}, request=request)

        client = _client_with_transport(handler)
        assert client.fetch_risk_free_rate() is None


class TestFetchStockMeta:
    def test_maps_symbols_to_stock_meta(self):
        _seed_cached_token()

        def handler(request):
            return httpx.Response(200, json={"result": [
                {"symbol": "005930", "market": "KOSPI", "securityType": "STOCK", "status": "ACTIVE"},
            ]}, request=request)

        client = _client_with_transport(handler)
        meta = client.fetch_stock_meta(["005930"])
        assert meta["005930"].market == "KOSPI"
        assert meta["005930"].security_type == "STOCK"

    def test_empty_symbols_returns_empty_dict_without_calling_api(self):
        def handler(request):
            raise AssertionError("빈 심볼 목록이면 API를 호출하면 안 된다")

        client = _client_with_transport(handler)
        assert client.fetch_stock_meta([]) == {}

    def test_unknown_market_or_security_type_does_not_crash(self):
        # DATA_DESIGN §5.4: unknown enum 허용. StockMeta.market/security_type은 str.
        _seed_cached_token()

        def handler(request):
            return httpx.Response(200, json={"result": [
                {"symbol": "XYZ", "market": "CRYPTO_EXCHANGE", "securityType": "CRYPTO_ETP"},
            ]}, request=request)

        client = _client_with_transport(handler)
        meta = client.fetch_stock_meta(["XYZ"])
        assert meta["XYZ"].market == "CRYPTO_EXCHANGE"

    def test_non_dict_result_element_is_skipped_not_crashed(self):
        # C-2: 형제 함수(_to_holding)와 동일하게, 원소가 dict가 아니어도
        # TypeError로 죽지 않고 그 원소만 건너뛴다.
        _seed_cached_token()

        def handler(request):
            return httpx.Response(200, json={"result": [
                "not-an-object",
                {"symbol": "005930", "market": "KOSPI", "securityType": "STOCK"},
            ]}, request=request)

        client = _client_with_transport(handler)
        meta = client.fetch_stock_meta(["005930"])
        assert list(meta.keys()) == ["005930"]


def _candles_response(request, n=35, currency="KRW"):
    base = date(2026, 1, 1)
    candles = [
        {
            "timestamp": (base + timedelta(days=i)).strftime("%Y-%m-%dT09:00:00+09:00"),
            "closePrice": "100",
            "currency": currency,
        }
        for i in range(n)
    ]
    return httpx.Response(200, json={"result": {"candles": candles}}, request=request)


class TestFetchPriceHistory:
    def test_excludes_symbol_with_insufficient_rows(self):
        _seed_cached_token()

        def handler(request):
            if request.url.path == "/api/v1/exchange-rate":
                return httpx.Response(200, json={"result": {"midRate": "1376.0"}}, request=request)
            candles = [
                {"timestamp": f"2026-01-{i:02d}T09:00:00+09:00", "closePrice": "100", "currency": "KRW"}
                for i in range(1, 6)  # 5개 < MIN_VALID_PRICE_ROWS(30)
            ]
            return httpx.Response(200, json={"result": {"candles": candles}}, request=request)

        client = _client_with_transport(handler)
        with pytest.raises(PriceDataError):
            client.fetch_price_history(["005930"], days=60)

    # T-6.4: 정상 경로에서 DataFrame이 실제로 조립되는지 (지금까지 이 경로가 한 번도
    # 실행된 적이 없었다 — insufficient-rows 케이스만 있으면 happy path가 안 잡힌다).
    def test_happy_path_returns_dataframe_with_symbol_columns(self):
        _seed_cached_token()

        def handler(request):
            if request.url.path == "/api/v1/exchange-rate":
                return httpx.Response(200, json={"result": {"midRate": "1376.0"}}, request=request)
            return _candles_response(request, n=35, currency="KRW")

        client = _client_with_transport(handler)
        prices = client.fetch_price_history(["005930", "000660"], days=30)
        assert list(prices.columns) == ["005930", "000660"]
        assert len(prices) == 30

    # C-4 / FR-202a(P0): 환율 조회가 실패하면 USD 종목은 fx=1로 넘어가는 게
    # 아니라 제외되어야 한다. KRW 종목은 환율과 무관하므로 계속 포함된다.
    def test_usd_symbol_excluded_when_exchange_rate_unavailable(self):
        _seed_cached_token()

        def handler(request):
            if request.url.path == "/api/v1/exchange-rate":
                return httpx.Response(500, json={"error": {"code": "internal-error"}}, request=request)
            if request.url.params.get("symbol") == "AAPL":
                return _candles_response(request, n=35, currency="USD")
            return _candles_response(request, n=35, currency="KRW")

        client = _client_with_transport(handler)
        prices = client.fetch_price_history(["005930", "AAPL"], days=30)
        assert list(prices.columns) == ["005930"]


class TestFetchBenchmarkHistory:
    def test_returns_empty_series_on_repeated_failure(self, monkeypatch):
        _seed_cached_token()
        monkeypatch.setattr(toss_client.time, "sleep", lambda s: None)

        def handler(request):
            return httpx.Response(500, json={"error": {"code": "internal-error"}}, request=request)

        client = _client_with_transport(handler)
        s = client.fetch_benchmark_history("KOSPI", days=60)
        assert s.empty

    def test_happy_path_returns_series(self):
        _seed_cached_token()

        def handler(request):
            return _candles_response(request, n=35, currency=None)

        client = _client_with_transport(handler)
        s = client.fetch_benchmark_history("KOSPI", days=30)
        assert len(s) == 30
        assert s.iloc[0] == pytest.approx(100.0)


class TestMalformedTopLevelResponse:
    """C-1: 200 응답이지만 본문이 dict가 아니거나(list/문자열), `result`가
    기대한 타입(dict/list)이 아닌 경우 — 서버 이상 응답이 AttributeError로
    escape하지 않아야 한다."""

    def test_request_rejects_non_dict_200_body(self):
        _seed_cached_token()

        def handler(request):
            return httpx.Response(200, json=["not", "a", "dict"], request=request)

        client = _client_with_transport(handler)
        with pytest.raises(BrokerAPIError):
            client._request("GET", "/api/v1/accounts", group="ACCOUNT")

    def test_bootstrap_result_as_dict_instead_of_list_does_not_crash(self):
        _seed_cached_token()

        def handler(request):
            return httpx.Response(200, json={"result": {"unexpected": "shape"}}, request=request)

        client = _client_with_transport(handler)
        with pytest.raises(AccountNotFoundError):
            client.bootstrap()

    def test_fetch_exchange_rate_result_as_list_returns_none(self):
        _seed_cached_token()

        def handler(request):
            return httpx.Response(200, json={"result": ["unexpected"]}, request=request)

        client = _client_with_transport(handler)
        assert client.fetch_exchange_rate() is None

    def test_fetch_portfolio_items_as_dict_instead_of_list_does_not_crash(self):
        _seed_cached_token()

        def handler(request):
            path = request.url.path
            if path == "/api/v1/exchange-rate":
                return httpx.Response(200, json={"result": {"midRate": "1376.0"}}, request=request)
            if path == "/api/v1/holdings":
                # items가 list가 아니라 dict -> _as_list가 빈 리스트로 흡수해야 함
                return httpx.Response(200, json={"result": {"items": {"oops": "not-a-list"}}}, request=request)
            if path == "/api/v1/buying-power":
                return httpx.Response(200, json={"result": {"cashBuyingPower": "0"}}, request=request)
            raise AssertionError(f"unexpected path: {path}")

        client = _client_with_transport(handler)
        client.account_seq, client.account_no = 1, "1"
        portfolio = client.fetch_portfolio()
        assert portfolio.holdings == []


class TestBuyingPowerNormalization:
    # _fetch_buying_power 자신도 음수를 0으로 정규화한다 — 이렇게 해야 Portfolio
    # 생성이 ge=0 검증에 걸려 fx_rate까지 통째로 버리는 폴백 분기(C-8)를
    # 애초에 밟지 않는다.
    def test_negative_cash_buying_power_normalized_to_zero(self):
        _seed_cached_token()

        def handler(request):
            return httpx.Response(200, json={"result": {"cashBuyingPower": "-500"}}, request=request)

        client = _client_with_transport(handler)
        client.account_seq = 1
        assert client._fetch_buying_power("KRW") == Decimal(0)


class TestFetchPortfolioValidationFallback:
    # C-8: Portfolio 생성이 ValidationError로 실패해도(예: 향후 스키마 변경 등)
    # fx_rate/daily_pnl_rate/holdings는 유지돼야 한다. 통째로 버리면 USD
    # 보유종목이 market_value_krw(fx_rate=None)에서 조용히 빠져 총자산이
    # 실제보다 훨씬 작게(극단적으로는 0으로) 표시된다. `_fetch_buying_power`가
    # 이제 스스로 음수를 막으므로(위 클래스), 그 방어를 우회해 fetch_portfolio()
    # 자체의 except 분기를 직접 검증한다.
    def test_validation_failure_falls_back_to_zero_cash_but_keeps_fx_rate_and_holdings(self, monkeypatch):
        _seed_cached_token()

        def handler(request):
            path = request.url.path
            if path == "/api/v1/exchange-rate":
                return httpx.Response(200, json={"result": {"midRate": "1376.0"}}, request=request)
            if path == "/api/v1/holdings":
                return httpx.Response(200, json={"result": {"items": [
                    {"symbol": "AAPL", "name": "Apple", "marketCountry": "US", "currency": "USD",
                     "quantity": "10", "averagePurchasePrice": "150", "lastPrice": "200"},
                ]}}, request=request)
            raise AssertionError(f"unexpected path: {path}")

        client = _client_with_transport(handler)
        client.account_seq, client.account_no = 1, "1"
        monkeypatch.setattr(client, "_fetch_buying_power", lambda currency: Decimal(-500))

        portfolio = client.fetch_portfolio()

        assert portfolio.cash_krw == Decimal(0)
        assert portfolio.fx_rate == Decimal("1376.0")
        assert len(portfolio.holdings) == 1
        # fx_rate가 살아있어야 USD 종목이 total_value에 반영된다 (10 * 200 * 1376).
        assert portfolio.total_value == pytest.approx(2752000)


class TestRequestRetryPolicy:
    """API_DESIGN §12.3. httpx.post(/oauth2/token)만 별도로 monkeypatch한다 —
    self._http(MockTransport)는 base_url 이하 경로만 다루고 토큰 발급은
    api/toss_client.py의 모듈 레벨 httpx.post를 직접 호출하기 때문이다."""

    @staticmethod
    def _mock_token_refresh(monkeypatch, token="fresh-token"):
        calls = []

        def fake_post(url, data=None, timeout=None):
            calls.append(data)
            return httpx.Response(
                200, json={"access_token": token, "expires_in": 3600},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(toss_client.httpx, "post", fake_post)
        return calls

    def test_401_then_success_refreshes_token_exactly_once(self, monkeypatch):
        _seed_cached_token()
        refresh_calls = self._mock_token_refresh(monkeypatch)

        auth_headers = []

        def handler(request: httpx.Request) -> httpx.Response:
            auth_headers.append(request.headers["Authorization"])
            if len(auth_headers) == 1:
                return httpx.Response(401, json={"error": {"code": "expired-token"}}, request=request)
            return httpx.Response(200, json={"result": "ok"}, request=request)

        client = _client_with_transport(handler)
        result = client._request("GET", "/api/v1/accounts", group="ACCOUNT")

        assert result == {"result": "ok"}
        assert len(refresh_calls) == 1
        assert auth_headers == ["Bearer cached-token", "Bearer fresh-token"]

    def test_401_twice_raises_authentication_error_without_second_refresh(self, monkeypatch):
        _seed_cached_token()
        refresh_calls = self._mock_token_refresh(monkeypatch)

        def handler(request):
            return httpx.Response(401, json={"error": {"code": "expired-token"}}, request=request)

        client = _client_with_transport(handler)
        with pytest.raises(AuthenticationError):
            client._request("GET", "/api/v1/accounts", group="ACCOUNT")

        assert len(refresh_calls) == 1  # A4: 요청당 1회만

    def test_429_waits_retry_after_seconds_then_retries(self, monkeypatch):
        _seed_cached_token()
        slept = []
        monkeypatch.setattr(toss_client.time, "sleep", lambda s: slept.append(s))

        call_log = []

        def handler(request):
            call_log.append(request)
            if len(call_log) == 1:
                return httpx.Response(429, headers={"Retry-After": "2"},
                                       json={"error": {"code": "rate-limit-exceeded"}}, request=request)
            return httpx.Response(200, json={"result": "ok"}, request=request)

        client = _client_with_transport(handler)
        result = client._request("GET", "/api/v1/holdings", group="ASSET")

        assert result == {"result": "ok"}
        assert 2.0 in slept
        assert len(call_log) == 2

    def test_maintenance_does_not_retry_raises_immediately(self):
        _seed_cached_token()
        call_log = []

        def handler(request):
            call_log.append(request)
            return httpx.Response(500, json={"error": {"code": "maintenance"}}, request=request)

        client = _client_with_transport(handler)
        with pytest.raises(MaintenanceError):
            client._request("GET", "/api/v1/holdings", group="ASSET")

        assert len(call_log) == 1

    def test_unsupported_symbol_does_not_retry_raises_immediately(self):
        _seed_cached_token()
        call_log = []

        def handler(request):
            call_log.append(request)
            return httpx.Response(400, json={"error": {"code": "unsupported-symbol"}}, request=request)

        client = _client_with_transport(handler)
        with pytest.raises(BrokerAPIError):
            client._request("GET", "/api/v1/candles", group="MARKET_DATA_CHART")

        assert len(call_log) == 1

    def test_internal_error_retries_with_exponential_backoff(self, monkeypatch):
        _seed_cached_token()
        slept = []
        monkeypatch.setattr(toss_client.time, "sleep", lambda s: slept.append(s))

        call_log = []

        def handler(request):
            call_log.append(request)
            if len(call_log) < 3:
                return httpx.Response(500, json={"error": {"code": "internal-error"}}, request=request)
            return httpx.Response(200, json={"result": "ok"}, request=request)

        client = _client_with_transport(handler)
        result = client._request("GET", "/api/v1/holdings", group="ASSET")

        assert result == {"result": "ok"}
        assert len(call_log) == 3
        assert slept[0] == pytest.approx(0.5)
        assert slept[1] == pytest.approx(1.0)

    def test_failure_is_logged_with_request_id(self, monkeypatch, caplog):
        _seed_cached_token()

        def handler(request):
            return httpx.Response(
                400, headers={"X-Request-Id": "req-abc-123"},
                json={"error": {"code": "invalid-request"}}, request=request,
            )

        client = _client_with_transport(handler)
        with caplog.at_level("WARNING"), pytest.raises(BrokerAPIError):
            client._request("GET", "/api/v1/candles", group="MARKET_DATA_CHART")

        assert "req-abc-123" in caplog.text

    # C-3 (Phase 5 C-2와 동일한 결함의 재발): 서버가 보낸 Retry-After가
    # 음수거나 에포크 타임스탬프급으로 크면 clamp 없이 time.sleep에 그대로
    # 전달되어 각각 ValueError·사실상 영구 정지가 된다.
    def test_negative_retry_after_is_clamped_not_crash(self, monkeypatch):
        _seed_cached_token()
        slept = []
        monkeypatch.setattr(toss_client.time, "sleep", lambda s: slept.append(s))

        call_log = []

        def handler(request):
            call_log.append(request)
            if len(call_log) == 1:
                return httpx.Response(429, headers={"Retry-After": "-5"},
                                       json={"error": {"code": "rate-limit-exceeded"}}, request=request)
            return httpx.Response(200, json={"result": "ok"}, request=request)

        client = _client_with_transport(handler)
        client._request("GET", "/api/v1/holdings", group="ASSET")  # must not raise

        assert all(s >= 0 for s in slept)

    def test_huge_retry_after_is_clamped_to_max_wait(self, monkeypatch):
        _seed_cached_token()
        slept = []
        monkeypatch.setattr(toss_client.time, "sleep", lambda s: slept.append(s))

        call_log = []

        def handler(request):
            call_log.append(request)
            if len(call_log) == 1:
                return httpx.Response(429, headers={"Retry-After": "1787654321"},
                                       json={"error": {"code": "rate-limit-exceeded"}}, request=request)
            return httpx.Response(200, json={"result": "ok"}, request=request)

        client = _client_with_transport(handler)
        client._request("GET", "/api/v1/holdings", group="ASSET")

        assert max(slept) <= MAX_RETRY_WAIT


class TestTokenReissueLoop:
    """C-5 (위험1): save_token()이 조용히 실패해도(Windows에서 다른 프로세스가
    파일을 잠근 경우 등, api/token_store.py의 정상적인 방어) 1회의 논리적
    요청 안에서 토큰이 여러 번 발급되면 안 된다. 발급 즉시 이전 토큰이
    무효화되므로(API_DESIGN §2.3), 저장 실패와 무관하게 방금 발급받은
    토큰을 그 자리에서 재사용해야 한다."""

    def test_single_401_issues_token_exactly_once_even_when_save_fails(self, monkeypatch):
        _seed_cached_token()
        monkeypatch.setattr(token_store, "save_token", lambda *a, **kw: None)  # 저장 실패 시뮬레이션

        issued_tokens = []

        def fake_post(url, data=None, timeout=None):
            issued_tokens.append(f"tok{len(issued_tokens) + 1}")
            return httpx.Response(
                200, json={"access_token": issued_tokens[-1], "expires_in": 3600},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(toss_client.httpx, "post", fake_post)

        auth_headers = []

        def handler(request):
            auth_headers.append(request.headers["Authorization"])
            if len(auth_headers) == 1:
                return httpx.Response(401, json={"error": {"code": "expired-token"}}, request=request)
            return httpx.Response(200, json={"result": "ok"}, request=request)

        client = _client_with_transport(handler)
        client._request("GET", "/api/v1/accounts", group="ACCOUNT")

        assert len(issued_tokens) == 1
        assert auth_headers[1] == f"Bearer {issued_tokens[0]}"


class TestTokenFetchFailureGuard:
    def test_not_retried_after_failure_in_same_process(self, monkeypatch):
        monkeypatch.setattr(toss_client, "_token_fetch_failed", True)
        with pytest.raises(AuthenticationError):
            toss_client._fetch_new_token(_settings())

    # C-6: 서버가 access_token 자리에 문자열이 아닌 값을 주면(뒤틀린 응답),
    # 그 값을 그대로 반환/저장하면 이후 모든 요청이 `Bearer {'a': 1}` 같은
    # 깨진 헤더를 만든다.
    def test_non_string_access_token_raises_authentication_error(self, monkeypatch):
        def fake_post(url, data=None, timeout=None):
            return httpx.Response(
                200, json={"access_token": {"nested": "token"}, "expires_in": 3600},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(toss_client.httpx, "post", fake_post)
        with pytest.raises(AuthenticationError):
            toss_client._fetch_new_token(_settings())

    # S-3: 서버 4xx(자격증명 오류 등)는 프로세스 내 재시도를 영구히 막지만,
    # 일시적 연결 단절은 다음 호출에서 다시 시도할 수 있어야 한다 — 유동 IP
    # 환경(docs/state.md 기록)에서 한 번의 순간 단절로 실계좌 연동이 프로세스
    # 수명 내내 막히면 안 된다.
    def test_transport_error_does_not_set_permanent_failure_flag(self, monkeypatch):
        def fake_post(url, data=None, timeout=None):
            raise httpx.ConnectError("simulated network drop")

        monkeypatch.setattr(toss_client.httpx, "post", fake_post)
        with pytest.raises(AuthenticationError):
            toss_client._fetch_new_token(_settings())
        assert toss_client._token_fetch_failed is False

    def test_http_status_error_sets_permanent_failure_flag(self, monkeypatch):
        def fake_post(url, data=None, timeout=None):
            return httpx.Response(401, json={"error": "invalid_client"}, request=httpx.Request("POST", url))

        monkeypatch.setattr(toss_client.httpx, "post", fake_post)
        with pytest.raises(AuthenticationError):
            toss_client._fetch_new_token(_settings())
        assert toss_client._token_fetch_failed is True


class TestBootstrap:
    def test_resolves_account_seq_and_no(self):
        _seed_cached_token()

        def handler(request):
            return httpx.Response(200, json={"result": [
                {"accountNo": "12345678901", "accountSeq": 2, "accountType": "BROKERAGE"},
            ]}, request=request)

        client = _client_with_transport(handler)
        client.bootstrap()
        assert client.account_seq == 2
        assert client.account_no == "12345678901"

    # FR-102a 방어선: bootstrap 없이 계좌 컨텍스트가 필요한 호출을 하면
    # AccountNotFoundError로 명확히 실패해야 한다(원인 불명의 401이 아니라).
    def test_account_ctx_request_without_bootstrap_raises_account_not_found(self):
        def handler(request):
            raise AssertionError("계좌 컨텍스트 검사가 먼저 실패해야 하므로 호출되면 안 된다")

        client = _client_with_transport(handler)
        with pytest.raises(AccountNotFoundError):
            client._request("GET", "/api/v1/buying-power", group="ORDER_INFO", account_ctx=True)
