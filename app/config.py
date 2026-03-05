from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "postgresql://ecube:ecube@localhost/ecube"
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"


settings = Settings()
