"""
Centralized application configuration via Pydantic Settings.
All values are loaded from environment variables with sensible defaults.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ---- App ----
    APP_ENV: str = "development"
    APP_NAME: str = "AI Trader"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # ---- Auth / JWT ----
    SECRET_KEY: str = "CHANGE-ME-IN-PRODUCTION"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ---- Rate Limiting ----
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10  # stricter for login/register

    # ---- Database (PostgreSQL) ----
    DB_HOST: str = "db"
    DB_PORT: int = 5432
    DB_USER: str = "admin"
    DB_PASS: str = "secretpassword"
    DB_NAME: str = "trading_log"

    @property
    def DATABASE_URL_ASYNC(self) -> str:
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASS}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:
        return (
            f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASS}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    # ---- Redis ----
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    @property
    def REDIS_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ---- CORS ----
    CORS_ORIGINS: str = "http://localhost:3100"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    # ---- Encryption (for API keys stored in DB) ----
    ENCRYPTION_KEY: str = "CHANGE-ME-32-BYTES-LONG-KEY!!!!!"

    # ---- MT5 Bridge (legacy, will move to platform config) ----
    WINDOWS_IP: str = ""
    SYMBOL: str = "XAUUSD"

    # ---- Risk Defaults ----
    ACCOUNT_BALANCE: float = 1000.0
    RISK_PERCENT: float = 1.0
    SL_POINTS: float = 300.0
    TP_POINTS: float = 600.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
