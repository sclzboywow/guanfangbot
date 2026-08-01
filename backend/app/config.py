from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    cors_origins: str = "http://localhost:5173"
    # Global QQ API endpoints only. Per-bot AppID/AppSecret are managed in the admin UI.
    qqbot_api_base: str = "https://api.bot.qq.com"
    qqbot_token_url: str = "https://api.bot.qq.com/app/getAppAccessToken"
    qqbot_request_timeout: float = 15.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
