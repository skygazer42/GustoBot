import os
from dataclasses import dataclass, field, replace
from typing import Dict, Optional


@dataclass
class DatabaseConfig:
    """Connection parameters for PostgreSQL with pgvector."""

    dbname: str = "vector_db"
    user: str = "postgres"
    password: str = ""
    host: str = "localhost"
    port: str = "5432"

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        return cls(
            dbname=os.getenv("PGDATABASE", os.getenv("POSTGRES_DB", cls.dbname)),
            user=os.getenv("PGUSER", os.getenv("POSTGRES_USER", cls.user)),
            password=os.getenv("PGPASSWORD", os.getenv("POSTGRES_PASSWORD", cls.password)),
            host=os.getenv("PGHOST", os.getenv("POSTGRES_HOST", cls.host)),
            port=os.getenv("PGPORT", os.getenv("POSTGRES_PORT", cls.port)),
        )

    def as_dict(self) -> Dict[str, str]:
        return {
            "dbname": self.dbname,
            "user": self.user,
            "password": self.password,
            "host": self.host,
            "port": self.port,
        }


@dataclass
class Config:
    """Global configuration shared across services."""

    # data IO
    excel_file_path: str = field(default_factory=lambda: os.getenv("EXCEL_FILE_PATH", "data.xlsx"))
    output_csv_path: str = field(
        default_factory=lambda: os.getenv("OUTPUT_CSV_PATH", "processed_data.csv")
    )
    output_txt_path: str = field(
        default_factory=lambda: os.getenv("OUTPUT_TXT_PATH", "processed_data.txt")
    )

    # rewriting
    use_llm: bool = field(default_factory=lambda: os.getenv("USE_LLM", "true").lower() != "false")
    flat_sep: str = field(default_factory=lambda: os.getenv("FLAT_SEPARATOR", " | "))
    flat_kv_sep: str = field(default_factory=lambda: os.getenv("FLAT_KV_SEPARATOR", ": "))
    flat_max_len: int = field(default_factory=lambda: int(os.getenv("FLAT_MAX_LEN", "4000")))

    # LLM settings
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openai"))
    llm_model: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL", "qwen/qwen3-next-80b-a3b-instruct")
    )
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_base_url: Optional[str] = field(default_factory=lambda: os.getenv("LLM_BASE_URL"))
    llm_temperature: float = field(
        default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.3"))
    )
    llm_fallback_to_flatten: bool = field(
        default_factory=lambda: os.getenv("LLM_FALLBACK_TO_FLATTEN", "false").lower() == "true"
    )

    # embedding settings
    embedding_provider: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_PROVIDER", "openai")
    )
    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "qwen/qwen3-embedding-8b")
    )
    embedding_api_key: str = field(default_factory=lambda: os.getenv("EMBEDDING_API_KEY", ""))
    embedding_base_url: Optional[str] = field(
        default_factory=lambda: os.getenv("EMBEDDING_BASE_URL")
    )
    embedding_dimension: int = field(
        default_factory=lambda: int(os.getenv("EMBEDDING_DIMENSION", "4096"))
    )

    # processing behaviour
    batch_size: int = field(default_factory=lambda: int(os.getenv("BATCH_SIZE", "16")))
    retry_times: int = field(default_factory=lambda: int(os.getenv("RETRY_TIMES", "3")))
    retry_delay: int = field(default_factory=lambda: int(os.getenv("RETRY_DELAY", "5")))

    # reranker configuration
    rerank_enabled: bool = field(
        default_factory=lambda: os.getenv("RERANK_ENABLED", "false").lower() == "true"
    )
    rerank_provider: str = field(default_factory=lambda: os.getenv("RERANK_PROVIDER", "cohere"))

    # Cohere API 配置
    cohere_api_key: Optional[str] = field(default_factory=lambda: os.getenv("COHERE_API_KEY"))
    cohere_rerank_model: str = field(
        default_factory=lambda: os.getenv("COHERE_RERANK_MODEL", "rerank-multilingual-v3.0")
    )
    cohere_rerank_url: str = field(
        default_factory=lambda: os.getenv("COHERE_RERANK_URL", "https://api.cohere.com/v2/rerank")
    )

    # 自建服务配置
    rerank_base_url: Optional[str] = field(default_factory=lambda: os.getenv("RERANK_BASE_URL"))
    rerank_endpoint: str = field(default_factory=lambda: os.getenv("RERANK_ENDPOINT", "/rerank"))
    rerank_api_key: Optional[str] = field(default_factory=lambda: os.getenv("RERANK_API_KEY"))
    rerank_model: Optional[str] = field(default_factory=lambda: os.getenv("RERANK_MODEL"))

    # 通用配置
    rerank_timeout: float = field(default_factory=lambda: float(os.getenv("RERANK_TIMEOUT", "30")))
    rerank_max_candidates: int = field(
        default_factory=lambda: int(os.getenv("RERANK_MAX_CANDIDATES", "20"))
    )
    rerank_top_n: int = field(default_factory=lambda: int(os.getenv("RERANK_TOP_N", "10")))
    rerank_score_fusion_alpha: Optional[float] = field(
        default_factory=lambda: (
            float(os.getenv("RERANK_SCORE_FUSION_ALPHA", "0.3"))
            if os.getenv("RERANK_SCORE_FUSION_ALPHA")
            else None
        )
    )

    db: DatabaseConfig = field(default_factory=DatabaseConfig.from_env)

    def __post_init__(self) -> None:
        for name in (
            "batch_size",
            "retry_times",
            "embedding_dimension",
            "rerank_top_n",
            "rerank_max_candidates",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.retry_delay < 0 or self.rerank_timeout <= 0:
            raise ValueError("retry_delay must be nonnegative and rerank_timeout positive")
        if self.embedding_provider.lower() == "openai" and not self.embedding_api_key:
            self.embedding_api_key = self.llm_api_key

        if self.embedding_provider.lower() == "ollama" and not self.embedding_base_url:
            self.embedding_base_url = self.llm_base_url

    @property
    def db_config(self) -> Dict[str, str]:
        return self.db.as_dict()


def load_config() -> Config:
    """Factory to create config objects; entrypoint for DI."""
    return Config()


def clone_config(config: Config) -> Config:
    """Copy configuration and its mutable database settings for one job."""
    return replace(config, db=replace(config.db))
