"""
Centralised application settings for GustoBot.
"""

from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application wide configuration loaded from environment variables."""

    # Application metadata
    APP_NAME: str = "GustoBot"
    APP_VERSION: str = "0.2.0"
    DEBUG: bool = False
    KNOWLEDGE_DOMAIN_FILE: str = "gustobot/config/domains/recipes.yaml"
    RECIPE_DATASET_PATH: str = "data/recipes/recipes.open-license.jsonl"

    # API configuration
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    SECRET_KEY: str | None = None
    GUSTOBOT_ADMIN_PASSWORD: SecretStr | None = Field(default=None, min_length=1, max_length=256)
    ALGORITHM: str = "HS256"

    @field_validator("GUSTOBOT_ADMIN_PASSWORD", mode="before")
    @classmethod
    def optional_admin_password(cls, value: Any) -> Any:
        """Treat an empty environment value as an unconfigured password."""
        return None if value == "" else value

    # LLM configuration
    LLM_MODEL: str = Field(
        default="gpt-6.1",
        description="LLM model name",
        validation_alias=AliasChoices("LLM_MODEL", "OPENAI_MODEL"),
    )
    LLM_API_KEY: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"),
    )
    LLM_BASE_URL: str | None = Field(
        default=None,
        description="LLM API base URL",
        validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_API_BASE"),
    )
    LLM_EXTRA_BODY: dict[str, Any] | None = Field(
        default=None,
        description="Optional JSON request extensions for the configured chat endpoint",
    )

    # OpenAI compatibility (使用 LLM 配置)
    @property
    def OPENAI_API_KEY(self) -> str | None:
        """Expose the legacy OpenAI key name as an alias for the chat key."""
        return self.LLM_API_KEY

    @property
    def OPENAI_API_BASE(self) -> str | None:
        """Expose the legacy OpenAI base URL as an alias for the chat endpoint."""
        return self.LLM_BASE_URL

    @property
    def OPENAI_MODEL(self) -> str:
        """Expose the legacy model name as an alias for the configured chat model."""
        return self.LLM_MODEL

    # Vision models (for image analysis)
    VISION_API_KEY: str | None = None
    VISION_BASE_URL: str | None = None
    VISION_MODEL: str = "gpt-6.1"

    # Image generation models (for creating images)
    IMAGE_GENERATION_API_KEY: str | None = None
    IMAGE_GENERATION_BASE_URL: str | None = Field(
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
    MILVUS_COLLECTION: str = "gustobot_documents_v1"
    MILVUS_INDEX_TYPE: str = "IVF_FLAT"
    MILVUS_METRIC_TYPE: str = "IP"

    # Embeddings
    EMBEDDING_PROVIDER: str = Field(
        default="openai",
        description="Embedding protocol label for index fingerprints; no vendor selection is needed",
    )
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_API_KEY: str | None = None
    EMBEDDING_BASE_URL: str | None = Field(default=None, description="Embedding API base URL")
    EMBEDDING_DIMENSION: int = 1536
    DOCUMENT_EMBEDDING_TIMEOUT: float = Field(default=60.0, gt=0)
    BUILD_EMBEDDING_TIMEOUT: float = Field(default=60.0, gt=0)
    EMBEDDING_BATCH_SIZE: int = Field(default=64, ge=1, le=1000)

    # Candidate indices are derived projections, independent of document chunks.
    SEMANTIC_LINKING_MODE: Literal["off", "shadow", "on"] = "off"
    SEMANTIC_EMBEDDING_REVISION: str = ""
    SEMANTIC_CONCEPT_TOP_K: int = Field(default=8, ge=1, le=40)
    SEMANTIC_ENTITY_TOP_K: int = Field(default=10, ge=1, le=40)
    SEMANTIC_FAMILY_LIMIT: int = Field(default=20, ge=1, le=100)
    SEMANTIC_EMBEDDING_TIMEOUT: float = Field(default=3.0, gt=0)
    SEMANTIC_ANN_TIMEOUT: float = Field(default=1.0, gt=0)
    SEMANTIC_BUILD_OPERATION_TIMEOUT: float = Field(default=30.0, gt=0)
    SEMANTIC_INITIALIZATION_TIMEOUT: float = Field(default=30.0, gt=0)
    SEMANTIC_RETRIEVAL_DEADLINE: float = Field(default=5.0, gt=0)
    SEMANTIC_INDEX_POLL_SECONDS: float = Field(default=5.0, gt=0)
    SEMANTIC_INDEX_BATCH_SIZE: int = Field(default=512, ge=1, le=1000)
    SEMANTIC_INDEX_QUIET_SECONDS: float = Field(default=5.0, ge=0)

    # Reranker configuration
    RERANK_ENABLED: bool = Field(default=True, description="Enable reranking")
    RERANK_PROVIDER: str = Field(
        default="custom", description="Rerank provider: cohere, jina, voyage, custom"
    )
    RERANK_API_FORMAT: Literal["standard", "dashscope"] = Field(
        default="dashscope", description="Wire format used by the custom rerank endpoint"
    )
    RERANK_BASE_URL: str | None = Field(default=None, description="Rerank API base URL")
    RERANK_ENDPOINT: str = Field(default="/rerank", description="Rerank endpoint path")
    RERANK_MODEL: str = Field(default="bge-reranker-large", description="Rerank model name")
    RERANK_API_KEY: str | None = None
    RERANK_MAX_CANDIDATES: int = Field(default=20, description="Max candidates for reranking")
    RERANK_TOP_N: int = Field(default=6, description="Top N results after reranking")
    RERANK_TIMEOUT: int = Field(default=30, description="Rerank API timeout in seconds")
    RERANK_SCORE_FUSION_ALPHA: float | None = Field(
        default=None, description="Score fusion alpha parameter"
    )

    # Web search tooling
    SERPAPI_KEY: str | None = None
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
    REDIS_PASSWORD: str | None = None
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
    DATABASE_URL: str = "mysql+pymysql://gustobot@localhost:3306/gustobot?charset=utf8mb4"
    SQL_DATABASE_URL: str | None = None

    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str | None = None
    NEO4J_DATABASE: str = "neo4j"
    KNOWLEDGE_QUERY_LIMIT: int = Field(default=20, ge=1, le=100)
    KNOWLEDGE_MAX_HOPS: int = Field(default=2, ge=1, le=3)
    KNOWLEDGE_ANSWER_STREAM: bool = True

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
    KB_RERANK_SCORE_THRESHOLD: float = Field(
        default=0.8,
        description="Minimum rerank score required for vector results (e.g., Milvus)",
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
    KB_EXTERNAL_SEARCH_URL: str | None = Field(
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

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS_ORIGINS string to list"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    model_config = {"env_file": ".env", "case_sensitive": True, "extra": "ignore"}


settings = Settings()
