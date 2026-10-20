from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RECALL_", env_file=".env", extra="ignore")

    pg_dsn: str = "postgresql://recall:recall_dev_only@localhost:5433/recall"
    ts_config: str = "de_tech"
    embed_url: str = "http://localhost:8001/v1"
    rerank_url: str = "http://localhost:8002/v1"
    generator_url: str = "http://localhost:8000/v1"
    embed_dims: int = 1024


settings = Settings()
