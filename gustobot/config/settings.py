"""
Centralised application settings for GustoBot.
"""

from typing import List, Literal, Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application wide configuration loaded from environment variables."""

    # Application metadata
    APP_NAME: str = "GustoBot"
    APP_VERSION: str = "0.1.2"
    DEBUG: bool = True
    KNOWLEDGE_DOMAIN_FILE: str = "gustobot/config/domains/recipes.json"

    # API configuration
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    SECRET_KEY: Optional[str] = None
    ALGORITHM: str = "HS256"

    # LLM configuration
    LLM_PROVIDER: str = Field(default="openai", description="LLM provider: openai, anthropic, etc.")
    LLM_MODEL: str = Field(
        default="gpt-5.4",
        description="LLM model name",
        validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL"),
    )
    LLM_API_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"),
    )
    LLM_BASE_URL: Optional[str] = Field(
        default=None,
        description="LLM API base URL",
        validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_API_BASE"),
    )

    # OpenAI compatibility (使用 LLM 配置)
    @property
    def OPENAI_API_KEY(self) -> Optional[str]:
        return self.LLM_API_KEY

    @property
    def OPENAI_API_BASE(self) -> Optional[str]:
        return self.LLM_BASE_URL

    @property
    def OPENAI_MODEL(self) -> str:
        return self.LLM_MODEL

    # Anthropic models
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-opus-5-5"

    # Vision models (for image analysis)
    VISION_API_KEY: Optional[str] = None
    VISION_BASE_URL: Optional[str] = None
    VISION_MODEL: str = "gpt-5.5"

    # Image generation models (for creating images)
    IMAGE_GENERATION_API_KEY: Optional[str] = None
    IMAGE_GENERATION_BASE_URL: Optional[str] = Field(
        default="https://open.bigmodel.cn/api/paas/v4", description="Image generation API base URL"
    )
    IMAGE_GENERATION_MODEL: str = Field(
        default="glm-image", description="Image generation model name"
    )
    IMAGE_GENERATION_SIZE: str = Field(
        default="1024x1024", description="Default image generation size"
    )

    # Milvus vector database
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_COLLECTION: str = "recipes"
    MILVUS_INDEX_TYPE: str = "IVF_FLAT"
    MILVUS_METRIC_TYPE: str = "IP"

    # Embeddings
    EMBEDDING_PROVIDER: str = Field(default="openai", description="Embedding provider")
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_API_KEY: Optional[str] = None
    EMBEDDING_BASE_URL: Optional[str] = Field(default=None, description="Embedding API base URL")
    EMBEDDING_DIMENSION: int = 1536

    # Reranker configuration
    RERANK_ENABLED: bool = Field(default=True, description="Enable reranking")
    RERANK_PROVIDER: str = Field(
        default="custom", description="Rerank provider: cohere, jina, voyage, custom"
    )
    RERANK_BASE_URL: Optional[str] = Field(default=None, description="Rerank API base URL")
    RERANK_ENDPOINT: str = Field(default="/rerank", description="Rerank endpoint path")
    RERANK_MODEL: str = Field(default="bge-reranker-large", description="Rerank model name")
    RERANK_API_KEY: Optional[str] = None
    RERANK_MAX_CANDIDATES: int = Field(default=20, description="Max candidates for reranking")
    RERANK_TOP_N: int = Field(default=6, description="Top N results after reranking")
    RERANK_TIMEOUT: int = Field(default=30, description="Rerank API timeout in seconds")
    RERANK_SCORE_FUSION_ALPHA: Optional[float] = Field(
        default=None, description="Score fusion alpha parameter"
    )

    # Legacy reranker compatibility
    @property
    def RERANKER_PROVIDER(self) -> str:
        return self.RERANK_PROVIDER

    @property
    def RERANKER_API_KEY(self) -> Optional[str]:
        return self.RERANK_API_KEY

    @property
    def RERANKER_MODEL(self) -> Optional[str]:
        return self.RERANK_MODEL

    @property
    def RERANKER_API_URL(self) -> Optional[str]:
        return self.RERANK_BASE_URL

    @property
    def RERANKER_TOP_K(self) -> int:
        return self.RERANK_TOP_N

    # Web search tooling
    SERPAPI_KEY: Optional[str] = None
    SERPAPI_BASE_URL: str = Field(
        default="https://serpapi.com/search",
        description="Base URL for SerpAPI requests",
    )
    SERPAPI_TIMEOUT: float = Field(
        default=15.0,
        description="SerpAPI request timeout in seconds",
    )
    SEARCH_RESULT_COUNT: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Default number of search results to return",
    )

    # Redis cache
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URI",
    )
    REDIS_CACHE_EXPIRE: int = Field(
        default=60 * 60 * 12,
        description="Redis cache expiry in seconds",
    )
    REDIS_CACHE_THRESHOLD: float = Field(
        default=0.92,
        description="Semantic cache similarity threshold",
    )
    REDIS_CACHE_MAX_SIZE: int = Field(
        default=1000,
        description="Maximum number of cached items per namespace",
    )

    # Relational database
    DATABASE_URL: str = "sqlite:///./data/gustobot.db"
    SQL_DATABASE_URL: Optional[str] = None

    # LightRAG configuration
    LIGHTRAG_WORKING_DIR: str = Field(
        default="./data/lightrag", description="LightRAG 工作目录，用于存储索引和缓存"
    )
    LIGHTRAG_RETRIEVAL_MODE: Literal["naive", "local", "global", "hybrid", "mix", "bypass"] = Field(
        default="hybrid", description="LightRAG 检索模式: local, global, hybrid, naive, mix, bypass"
    )
    LIGHTRAG_TOP_K: int = Field(default=10, description="LightRAG 检索返回的top-k结果数量")
    LIGHTRAG_MAX_TOKEN_SIZE: int = Field(
        default=4096, description="LightRAG 文本单元的最大token数量"
    )
    INIT_LIGHTRAG_ON_BUILD: bool = Field(default=True, description="Docker构建时是否初始化LightRAG")
    LIGHTRAG_INIT_LIMIT: Optional[int] = Field(
        default=None, description="LightRAG初始化时的菜谱数量限制，None为全部"
    )

    # Agent behaviour
    MAX_ITERATIONS: int = 10
    AGENT_TIMEOUT: int = 300

    # Knowledge base retrieval
    KB_TOP_K: int = 5
    KB_SIMILARITY_THRESHOLD: float = 0.2
    KB_CHUNK_SIZE: int = Field(
        default=512,
        description="Chunk size used when splitting documents for the knowledge base",
    )
    KB_CHUNK_OVERLAP: int = Field(
        default=80,
        description="Chunk overlap used when splitting documents",
    )
    KB_LLM_PROVIDER: str = Field(default="openai", description="LLM provider used by kb_ingest")
    KB_LLM_MODEL: Optional[str] = Field(default=None, description="LLM model used by kb_ingest")
    KB_LLM_API_KEY: Optional[str] = Field(default=None, description="LLM API key for kb_ingest")
    KB_LLM_BASE_URL: Optional[str] = Field(default=None, description="LLM base URL for kb_ingest")
    KB_LLM_TEMPERATURE: float = Field(default=0.3, description="LLM temperature for kb_ingest")
    KB_USE_LLM: bool = Field(default=True, description="Whether kb_ingest uses an LLM pipeline")
    KB_EMBEDDING_PROVIDER: str = Field(
        default="openai", description="Embedding provider for kb_ingest"
    )
    KB_EMBEDDING_MODEL: Optional[str] = Field(
        default=None, description="Embedding model for kb_ingest"
    )
    KB_EMBEDDING_API_KEY: Optional[str] = Field(
        default=None, description="Embedding API key for kb_ingest"
    )
    KB_EMBEDDING_BASE_URL: Optional[str] = Field(
        default=None, description="Embedding base URL for kb_ingest"
    )
    KB_EMBEDDING_DIMENSION: int = Field(
        default=1024, description="Embedding dimension for kb_ingest"
    )
    KB_RERANK_ENABLED: bool = Field(
        default=False, description="Whether kb_ingest uses a reranker service"
    )
    KB_RERANK_PROVIDER: Optional[str] = Field(
        default=None, description="Reranker provider for kb_ingest"
    )
    KB_RERANK_BASE_URL: Optional[str] = Field(
        default=None, description="Reranker base URL for kb_ingest"
    )
    KB_RERANK_ENDPOINT: Optional[str] = Field(
        default=None, description="Reranker endpoint for kb_ingest"
    )
    KB_RERANK_API_KEY: Optional[str] = Field(
        default=None, description="Reranker API key for kb_ingest"
    )
    KB_RERANK_MODEL: Optional[str] = Field(default=None, description="Reranker model for kb_ingest")
    KB_RERANK_MAX_CANDIDATES: int = Field(
        default=20, description="Max candidates for kb_ingest reranker when enabled"
    )
    KB_RERANK_TOP_N: int = Field(
        default=6, description="Top N results returned by kb_ingest reranker"
    )
    KB_RERANK_TIMEOUT: int = Field(
        default=30, description="Timeout for kb_ingest reranker requests"
    )
    KB_RERANK_SCORE_FUSION_ALPHA: float = Field(
        default=0.5, description="Score fusion alpha for kb_ingest reranker"
    )
    KB_POSTGRES_SIMILARITY_THRESHOLD: float = Field(
        default=0.5,
        description="Minimum similarity required for PostgreSQL KB results after rerank",
    )
    KB_POSTGRES_RERANK_THRESHOLD: float = Field(
        default=0.8,
        description="Minimum rerank score required for PostgreSQL KB results",
    )
    KB_RERANK_SCORE_THRESHOLD: float = Field(
        default=0.8,
        description="Minimum rerank score required for vector results (e.g., Milvus)",
    )

    # External ingestion service (test folder FastAPI) configuration
    INGEST_SERVICE_URL: Optional[str] = Field(
        default=None,
        description="Base URL for external ingestion service (e.g., http://localhost:8000)",
    )
    INGEST_INCREMENTAL_DEFAULT: bool = Field(
        default=True,
        description="Whether external Excel ingestion should default to incremental updates",
    )
    FILE_UPLOAD_MAX_MB: int = Field(
        default=2,
        ge=1,
        description="Maximum accepted upload file size in MB for local ingestion",
    )
    ENABLE_EXTERNAL_SEARCH: bool = Field(
        default=False,
        description="Whether tools are allowed to perform external network search",
    )
    KB_ENABLE_EXTERNAL_SEARCH: bool = Field(
        default=False,
        description="Augment KB answers with optional external web search",
    )
    KB_EXTERNAL_SEARCH_URL: Optional[str] = Field(
        default=None,
        description=(
            "External HTTP endpoint for KB fallback search "
            "(e.g., http://localhost:8000/api/search)"
        ),
    )
    KB_EXTERNAL_SEARCH_TIMEOUT: float = Field(
        default=20.0,
        description="Timeout in seconds for external KB search requests.",
    )

    # Conversation history retention
    CONVERSATION_HISTORY_TTL: int = Field(
        default=60 * 60 * 24 * 3,
        description="How long to retain chat history in seconds",
    )
    CONVERSATION_HISTORY_MAX_MESSAGES: int = Field(
        default=200,
        description="Maximum number of messages retained per conversation",
    )

    # CORS
    CORS_ORIGINS: str = Field(
        default="http://localhost:3000,http://localhost:5173",
        description="Comma-separated list of CORS origins",
    )

    # Ollama configuration
    OLLAMA_BASE_URL: str = Field(
        default="http://localhost:11434", description="Ollama service base URL"
    )
    OLLAMA_EMBEDDING_MODEL: str = Field(
        default="nomic-embed-text", description="Ollama embedding model for semantic caching"
    )

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS_ORIGINS string to list"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    model_config = {"env_file": ".env", "case_sensitive": True, "extra": "ignore"}


settings = Settings()
