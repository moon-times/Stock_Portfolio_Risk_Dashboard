import pytest

from api.errors import (
    AccountNotFoundError,
    AuthenticationError,
    BrokerAPIError,
    DashboardError,
    MaintenanceError,
    RateLimitError,
    error_for_code,
)


class TestExceptionHierarchy:
    def test_broker_api_error_is_dashboard_error(self):
        assert issubclass(BrokerAPIError, DashboardError)

    def test_specific_errors_are_broker_api_errors(self):
        assert issubclass(AuthenticationError, BrokerAPIError)
        assert issubclass(AccountNotFoundError, BrokerAPIError)
        assert issubclass(RateLimitError, BrokerAPIError)
        assert issubclass(MaintenanceError, BrokerAPIError)


class TestErrorForCode:
    def test_expired_token_maps_to_authentication_error(self):
        assert isinstance(error_for_code("expired-token"), AuthenticationError)

    def test_rate_limit_exceeded_maps_to_rate_limit_error(self):
        assert isinstance(error_for_code("rate-limit-exceeded"), RateLimitError)

    def test_maintenance_maps_to_maintenance_error(self):
        assert isinstance(error_for_code("maintenance"), MaintenanceError)

    def test_account_not_found_maps_to_account_not_found_error(self):
        assert isinstance(error_for_code("account-not-found"), AccountNotFoundError)

    def test_unknown_code_maps_to_generic_broker_api_error_without_crashing(self):
        # API_DESIGN §12.2: 클라이언트는 unknown code를 허용해야 한다.
        err = error_for_code("완전히-새로운-코드")
        assert isinstance(err, BrokerAPIError)
        assert not isinstance(err, (AuthenticationError, AccountNotFoundError, RateLimitError, MaintenanceError))

    def test_none_code_does_not_crash(self):
        err = error_for_code(None)
        assert isinstance(err, BrokerAPIError)

    def test_error_code_is_retained_for_logging(self):
        err = error_for_code("expired-token")
        assert err.code == "expired-token"

    @pytest.mark.parametrize("code", ["invalid-token", "expired-token", "login-user-not-found"])
    def test_all_401_codes_map_to_authentication_error(self, code):
        assert isinstance(error_for_code(code), AuthenticationError)

    @pytest.mark.parametrize("bad_code", [["not", "a", "string"], {"nested": "code"}, 12345, 3.14])
    def test_non_string_code_does_not_crash(self, bad_code):
        # 서버가 뒤틀린 JSON({"code": {...}} 등)을 보내도 매핑 조회 자체가
        # TypeError(unhashable type)로 죽으면 안 된다 (NFR-206).
        err = error_for_code(bad_code)
        assert isinstance(err, BrokerAPIError)


class TestBrokerAPIErrorConstruction:
    def test_accepts_message_positionally_per_api_design_usage(self):
        # API_DESIGN §11.3/§12.3: RateLimitError("메시지"), BrokerAPIError("메시지")
        err = BrokerAPIError("요청이 반복 실패했습니다")
        assert str(err) == "요청이 반복 실패했습니다"
        assert err.code is None

    def test_code_is_keyword_only_and_does_not_leak_into_message(self):
        err = BrokerAPIError("사람이 읽을 메시지", code="internal-error")
        assert str(err) == "사람이 읽을 메시지"
        assert err.code == "internal-error"
