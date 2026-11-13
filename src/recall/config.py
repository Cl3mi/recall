from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RECALL_", env_file=".env", extra="ignore")

    pg_dsn: str = "postgresql://recall:recall_dev_only@localhost:5433/recall"
    ts_config: str = "de_tech"
    embed_url: str = "http://localhost:8001/v1"
    # The application's rerank default (M4 spec §3): a key of recall.rerank.RERANKERS, the
    # fused depth it reranks and a retrieve.DOC_TEXTS value. None means no reranking. The
    # reranker runs in-process, so there is no rerank server URL.
    rerank_model: str | None = None
    rerank_depth: int | None = None
    rerank_text: str | None = None
    generator_url: str = "http://localhost:8000/v1"
    embed_dims: int = 1024


settings = Settings()
