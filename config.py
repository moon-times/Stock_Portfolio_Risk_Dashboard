from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    toss_client_id: str = ""
    # SecretStr: S4(예외 메시지에 토큰이 포함될 수 있으므로 원문 노출 금지) 대응.
    # TRD §5.3 샘플 코드는 평문 str이지만, repr/로그 노출 방지를 위해 격상함.
    toss_client_secret: SecretStr = SecretStr("")
    toss_base_url: str = "https://openapi.tossinvest.com"
    anthropic_api_key: SecretStr = SecretStr("")

    lookback_days: int = 126
    benchmark_symbol: str = "KOSPI"
    risk_free_symbol: str = "KR_BOND_3Y"
    risk_free_rate_fallback: float = 0.03
    use_mock_data: bool = False

    @property
    def has_broker_credentials(self) -> bool:
        return bool(self.toss_client_id and self.toss_client_secret.get_secret_value())


settings = Settings()
