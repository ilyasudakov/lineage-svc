from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="LINEAGE_", extra="ignore")

    database_url: str = "postgresql+asyncpg://lineage:lineage@localhost:5432/lineage"
    log_level: str = "INFO"
    app_env: str = "local"


settings = Settings()
