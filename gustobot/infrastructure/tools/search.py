import httpx
from pydantic import BaseModel, Field

from gustobot.config import settings
from gustobot.infrastructure.core import get_logger

logger = get_logger(service="tool.search")


class _OrganicResult(BaseModel):
    """Validated organic search result returned by the provider."""

    title: str = Field(min_length=1)
    link: str = Field(min_length=1)
    snippet: str = ""


class _SearchResponse(BaseModel):
    """Provider response fields used by the search tool adapter."""

    error: str | None = None
    organic_results: list[_OrganicResult] = Field(default_factory=list)


class SearchTool:
    """Wrapper around SerpAPI Google search results."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str | None = None,
        timeout: float | None = None,
        default_results: int | None = None,
    ) -> None:
        self.allow_network = settings.ENABLE_EXTERNAL_SEARCH
        self.api_key = settings.SERPAPI_KEY if api_key is None else api_key
        if self.allow_network and not self.api_key:
            raise RuntimeError("SERPAPI_KEY is not configured.")
        if not self.allow_network:
            logger.info("External search disabled; SearchTool will operate in no-op mode.")

        self.endpoint = (settings.SERPAPI_BASE_URL if endpoint is None else endpoint).rstrip("/")
        if not self.endpoint:
            raise ValueError("Search endpoint must not be empty")
        self.timeout = settings.SERPAPI_TIMEOUT if timeout is None else timeout
        self.default_results = (
            settings.SEARCH_RESULT_COUNT if default_results is None else default_results
        )

    def search(self, query: str, *, num_results: int | None = None) -> list[dict]:
        """执行搜索并返回结构化结果"""
        if not query.strip():
            raise ValueError("Search query must not be empty.")

        if not self.allow_network:
            logger.info("External search disabled via configuration; returning empty result set.")
            return []

        result_count = self.default_results if num_results is None else num_results
        if result_count < 0:
            raise ValueError("num_results cannot be negative")
        if result_count == 0:
            return []

        params = {
            "engine": "google",
            "q": query,
            "api_key": self.api_key,
            "num": result_count,
            "hl": "zh-CN",
            "gl": "cn",
        }

        with httpx.Client(timeout=self.timeout, trust_env=False) as client:
            response = client.get(self.endpoint, params=params)
            response.raise_for_status()

        payload = response.json()

        return self._parse_results(payload, limit=result_count)

    def _parse_results(self, data: dict, *, limit: int) -> list[dict]:
        """Normalize SerpAPI payload."""
        if limit <= 0:
            return []
        payload = _SearchResponse.model_validate(data)
        if payload.error is not None:
            raise RuntimeError("Search provider returned an error")
        return [
            {"title": item.title, "url": item.link, "snippet": item.snippet}
            for item in payload.organic_results[:limit]
        ]
