"""为已知菜谱来源下载小型快照，并保留可离线校验的 HTTP 回执。"""

import hashlib
import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import TracebackType
from urllib.parse import urlsplit

import httpx


_ALLOWED_HOSTS = frozenset(
    {"api.github.com", "raw.githubusercontent.com", "www.themealdb.com", "themealdb.com"}
)
_RETRY_STATUSES = frozenset({429, 502, 503, 504})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=30.0)
_USER_AGENT = "GustoBotRecipeDataset/1.0"


def _validate_url(url: str) -> None:
    """限制请求及每次跳转的协议、主机和端口，拒绝带凭据的 URL。"""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError("Download URL must use an approved HTTPS recipe source")


def _retry_delay(attempt: int, response: httpx.Response | None) -> float:
    """尊重有效 Retry-After，并把单次等待限制在 30 秒内。"""
    if response is not None:
        value = response.headers.get("Retry-After")
        if value is not None:
            if value.isdecimal():
                return float(min(int(value), 30))
            try:
                deadline = parsedate_to_datetime(value)
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                return float(
                    min(30.0, max(0.0, (deadline - datetime.now(timezone.utc)).total_seconds()))
                )
            except (TypeError, ValueError, OverflowError):
                pass
    return float(0.25 * (2**attempt))


class DownloadCache:
    """管理菜谱 GET 缓存；仅关闭自身创建的客户端，不接管借入客户端。"""

    def __init__(
        self,
        root: Path,
        *,
        offline: bool = False,
        client: httpx.Client | None = None,
    ) -> None:
        self.root = root
        self.offline = offline
        self._owns_client = client is None
        self._client = (
            httpx.Client(timeout=_TIMEOUT, follow_redirects=False, trust_env=True)
            if client is None
            else client
        )

    def __enter__(self) -> "DownloadCache":
        """返回本缓存，供调用方显式限定 HTTP 客户端生命周期。"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """退出时释放自有客户端；异常继续传播。"""
        if self._owns_client:
            self._client.close()

    def get(self, url: str, *, max_bytes: int = 8 * 1024 * 1024) -> tuple[bytes, dict]:
        """读取有效缓存或下载内容；损坏、超限与离线缺失均显式失败。"""
        _validate_url(url)
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        body_path = self.root / f"{key}.body"
        receipt_path = self.root / f"{key}.json"
        if body_path.exists() or receipt_path.exists():
            return self._read_cache(url, body_path, receipt_path, max_bytes)
        if self.offline:
            raise FileNotFoundError(f"Offline recipe cache miss: {url}")

        body, receipt = self._fetch(url, max_bytes)
        self.root.mkdir(parents=True, exist_ok=True)
        body_temporary = body_path.with_suffix(".body.tmp")
        receipt_temporary = receipt_path.with_suffix(".json.tmp")
        try:
            body_temporary.write_bytes(body)
            receipt_temporary.write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            body_temporary.replace(body_path)
            receipt_temporary.replace(receipt_path)
        finally:
            body_temporary.unlink(missing_ok=True)
            receipt_temporary.unlink(missing_ok=True)
        return body, receipt

    def _read_cache(
        self, url: str, body_path: Path, receipt_path: Path, max_bytes: int
    ) -> tuple[bytes, dict]:
        """同时核对原始 URL、最终 URL、内容摘要与当前调用的大小限制。"""
        if not body_path.is_file() or not receipt_path.is_file():
            raise ValueError(f"Incomplete recipe cache entry: {body_path.stem}")
        if body_path.stat().st_size > max_bytes:
            raise ValueError("Cached recipe response exceeds max_bytes")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        required = {"url", "final_url", "sha256", "content_type", "retrieved_at"}
        if (
            not isinstance(receipt, dict)
            or not required.issubset(receipt)
            or any(not isinstance(receipt[field], str) for field in required)
            or receipt["url"] != url
        ):
            raise ValueError("Invalid recipe cache receipt")
        _validate_url(receipt["final_url"])
        body = body_path.read_bytes()
        if len(body) > max_bytes or hashlib.sha256(body).hexdigest() != receipt["sha256"]:
            raise ValueError("Recipe cache integrity check failed")
        return body, receipt

    def _fetch(self, url: str, max_bytes: int) -> tuple[bytes, dict]:
        """最多发起三轮 GET，只重试临时状态码及连接、读取故障。"""
        for attempt in range(3):
            try:
                return self._fetch_once(url, max_bytes)
            except httpx.HTTPStatusError as error:
                if error.response.status_code not in _RETRY_STATUSES or attempt == 2:
                    raise
                time.sleep(_retry_delay(attempt, error.response))
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError, httpx.ReadError):
                if attempt == 2:
                    raise
                time.sleep(_retry_delay(attempt, None))
        raise RuntimeError("Recipe download exhausted its attempt budget")

    def _fetch_once(self, url: str, max_bytes: int) -> tuple[bytes, dict]:
        """手动跟随最多三次跳转，流式读取并确保所有响应都被关闭。"""
        current_url = url
        for redirect_count in range(4):
            _validate_url(current_url)
            with self._client.stream(
                "GET",
                current_url,
                timeout=_TIMEOUT,
                headers={"User-Agent": _USER_AGENT},
                follow_redirects=False,
            ) as response:
                if response.status_code in _REDIRECT_STATUSES:
                    if redirect_count == 3:
                        raise ValueError("Recipe download exceeded three redirects")
                    location = response.headers.get("Location")
                    if location is None:
                        raise ValueError("Recipe redirect did not include Location")
                    current_url = str(response.url.join(location))
                    _validate_url(current_url)
                    continue
                response.raise_for_status()
                content_length = response.headers.get("Content-Length")
                if content_length is not None and content_length.isdecimal():
                    if int(content_length) > max_bytes:
                        raise ValueError("Recipe response exceeds max_bytes")
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > max_bytes:
                        raise ValueError("Recipe response exceeds max_bytes")
                    body.extend(chunk)
                result = bytes(body)
                receipt = {
                    "url": url,
                    "final_url": str(response.url),
                    "sha256": hashlib.sha256(result).hexdigest(),
                    "content_type": response.headers.get("Content-Type", ""),
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
                return result, receipt
        raise RuntimeError("Recipe redirect loop exceeded its budget")
