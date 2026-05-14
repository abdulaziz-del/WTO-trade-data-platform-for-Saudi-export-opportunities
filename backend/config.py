"""Application Configuration"""
from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "WTO Trade Intelligence Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/wto_platform"
    REDIS_URL: str = "redis://localhost:6379/0"
    ELASTICSEARCH_URL: str = "http://localhost:9200"
    ANTHROPIC_API_KEY: str = ""

    # ----------------------------------------------------------------
    # WTO API — Register free at https://apiportal.wto.org
    # Your key appears under Profile > Subscriptions after registration
    # ----------------------------------------------------------------
    WTO_API_KEY: str = ""   # sent as Ocp-Apim-Subscription-Key header

    # WTO reporter codes  (GET /timeseries/v1/reporters for full list)
    WTO_REPORTER_SAUDI:   str = "682"
    WTO_REPORTER_UAE:     str = "784"
    WTO_REPORTER_KUWAIT:  str = "414"
    WTO_REPORTER_BAHRAIN: str = "48"
    WTO_REPORTER_QATAR:   str = "634"
    WTO_REPORTER_OMAN:    str = "512"
    WTO_REPORTER_CHINA:   str = "156"
    WTO_REPORTER_USA:     str = "840"
    WTO_REPORTER_EU:      str = "918"
    WTO_REPORTER_INDIA:   str = "356"

    # WTO indicator codes (GET /timeseries/v1/indicators for full list)
    WTO_IND_IMPORTS:     str = "HS_M_0040"
    WTO_IND_EXPORTS:     str = "HS_X_0040"
    WTO_IND_MFN_APPLIED: str = "TRF_0010"
    WTO_IND_BOUND:       str = "TRF_0020"

    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "https://wto-platform.example.com"]
    JWT_SECRET_KEY: str = "jwt-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440
    AWS_REGION: str = "me-south-1"
    AWS_S3_BUCKET: str = "wto-platform-files"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
