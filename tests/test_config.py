import pytest

from config import Settings

# .env 없음 상태를 온전히 재현하려면 dotenv 파일(_env_file=None)뿐 아니라
# pydantic-settings가 읽는 OS 환경변수도 함께 지워야 한다.
# 이 프로젝트 루트에는 Phase S에서 만든 실제 .env가 있어서 값이 새어들 수 있다.
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


@pytest.fixture
def no_settings_env(monkeypatch):
    for key in _SETTINGS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class TestSettingsWithoutEnvFile:
    def test_loads_without_env_file_with_defaults(self, no_settings_env):
        s = Settings(_env_file=None)
        assert s.toss_client_id == ""
        assert s.toss_client_secret.get_secret_value() == ""
        assert s.anthropic_api_key.get_secret_value() == ""

    def test_has_broker_credentials_false_by_default(self, no_settings_env):
        s = Settings(_env_file=None)
        assert s.has_broker_credentials is False

    def test_has_broker_credentials_true_when_both_present(self, no_settings_env):
        s = Settings(_env_file=None, toss_client_id="x", toss_client_secret="y")
        assert s.has_broker_credentials is True

    def test_has_broker_credentials_false_when_only_id_present(self, no_settings_env):
        s = Settings(_env_file=None, toss_client_id="x", toss_client_secret="")
        assert s.has_broker_credentials is False

    def test_default_values(self, no_settings_env):
        s = Settings(_env_file=None)
        assert s.lookback_days == 126
        assert s.benchmark_symbol == "KOSPI"
        assert s.risk_free_symbol == "KR_BOND_3Y"
        assert s.risk_free_rate_fallback == 0.03
        assert s.use_mock_data is False
