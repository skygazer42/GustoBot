import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from gustobot.infrastructure.core.logger import get_logger

logger = get_logger(service="http")


class LoggingMiddleware(BaseHTTPMiddleware):
    """Log request timing and status without changing the response contract."""

    async def dispatch(self, request: Request, call_next):
        """Measure one request and log its response status and elapsed time."""
        start_time = time.perf_counter()

        response = await call_next(request)

        # 计算处理时间
        process_time = time.perf_counter() - start_time
        client = f"{request.client.host}:{request.client.port}" if request.client else "-"

        # 记录请求日志
        logger.info(
            f"{client} - "
            f'"{request.method} {request.url.path} '
            f'HTTP/{request.scope.get("http_version", "1.1")}" '
            f"{response.status_code} - {process_time:.2f}s"
        )

        return response
