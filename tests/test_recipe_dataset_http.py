"""菜谱快照下载器的缓存、请求范围及资源关闭边界。"""

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from scripts.recipe_dataset_http import DownloadCache


URL = "https://www.themealdb.com/api/json/v1/1/search.php?s=Arrabiata"


def test_download_and_offline_rebuild_share_the_same_verified_receipt(tmp_path):
    """离线读取应保留首次回执，不伪造新的采集时间。"""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, content=b'{"meals": []}', headers={"Content-Type": "application/json"}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with DownloadCache(tmp_path, client=client) as cache:
            content, receipt = cache.get(URL)
        assert not client.is_closed
        with DownloadCache(tmp_path, offline=True, client=client) as cache:
            assert cache.get(URL) == (content, receipt)
    assert len(calls) == 1
    assert receipt["sha256"] == hashlib.sha256(content).hexdigest()
    assert calls[0].headers["User-Agent"] == "GustoBotRecipeDataset/1.0"
    assert calls[0].extensions["timeout"]["connect"] == 10.0
    assert calls[0].extensions["timeout"]["read"] == 30.0


def test_owned_client_closes_when_context_raises(tmp_path):
    """上下文退出必须释放自有客户端，同时保持原异常。"""
    cache = DownloadCache(tmp_path)
    with pytest.raises(RuntimeError, match="fixture"):
        with cache:
            raise RuntimeError("fixture")
    assert cache._client.is_closed


def test_offline_cache_miss_does_not_make_a_request(tmp_path):
    """无快照时明确报缺失，不能在离线模式请求网络。"""
    with DownloadCache(tmp_path, offline=True) as cache:
        with pytest.raises(FileNotFoundError, match="Offline recipe cache miss"):
            cache.get(URL)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "url",
    [
        "http://www.themealdb.com/data",
        "https://example.com/data",
        "https://127.0.0.1/data",
        "https://user:password@www.themealdb.com/data",
        "https://www.themealdb.com:8443/data",
        "https://www.themealdb.com.evil.test/data",
        "https://www.themealdb.com/data#fragment",
    ],
)
def test_unknown_hosts_credentials_and_nonstandard_ports_are_rejected(tmp_path, url):
    """来源白名单同时约束源 URL，防止将通用 URL 当作可下载图片。"""
    with DownloadCache(tmp_path) as cache:
        with pytest.raises(ValueError, match="approved HTTPS"):
            cache.get(url)


def test_redirect_to_unapproved_host_is_rejected_before_following(tmp_path):
    """响应重定向不能绕过来源白名单。"""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://example.com/image.jpg"})

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with DownloadCache(tmp_path, client=client) as cache:
            with pytest.raises(ValueError, match="approved HTTPS"):
                cache.get(URL)
    assert len(calls) == 1
    assert not list(tmp_path.iterdir())


def test_redirects_allow_relative_paths_but_stop_after_three(tmp_path):
    """受信主机上的相对路径可解析，循环跳转有明确次数上限。"""
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "/redirected"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with DownloadCache(tmp_path, client=client) as cache:
            with pytest.raises(ValueError, match="three redirects"):
                cache.get(URL)
    assert len(calls) == 4
    assert calls[1] == "https://www.themealdb.com/redirected"


@pytest.mark.parametrize("damage", ["body", "receipt", "missing-body", "missing-receipt"])
def test_damaged_cache_never_falls_back_to_silent_success(tmp_path, damage):
    """摘要错误或半写入文件应要求显式恢复，而非当作有效快照。"""
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"ok"))
    ) as client:
        with DownloadCache(tmp_path, client=client) as cache:
            cache.get(URL)
    key = hashlib.sha256(URL.encode()).hexdigest()
    body_path = tmp_path / f"{key}.body"
    receipt_path = tmp_path / f"{key}.json"
    if damage == "body":
        body_path.write_bytes(b"bad")
    elif damage == "receipt":
        receipt_path.write_text(json.dumps({"url": URL}), encoding="utf-8")
    elif damage == "missing-body":
        body_path.unlink()
    else:
        receipt_path.unlink()
    with DownloadCache(tmp_path, offline=True) as cache:
        with pytest.raises(ValueError, match="cache|receipt"):
            cache.get(URL)


def test_cached_body_obeys_smaller_request_limit(tmp_path):
    """同一个快照在更严格的调用限制下不能超限返回。"""
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"1234"))
    ) as client:
        with DownloadCache(tmp_path, client=client) as cache:
            cache.get(URL, max_bytes=4)
            with pytest.raises(ValueError, match="max_bytes"):
                cache.get(URL, max_bytes=3)


class RecordingStream(httpx.SyncByteStream):
    """测试提前停止下载后，流是否仍被关闭。"""

    def __init__(self):
        self.closed = False

    def __iter__(self):
        yield b"123"
        yield b"456"

    def close(self):
        self.closed = True


def test_oversized_stream_is_closed_and_not_cached(tmp_path):
    """没有 Content-Length 的超大内容同样必须中止并关闭。"""
    stream = RecordingStream()
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    ) as client:
        with DownloadCache(tmp_path, client=client) as cache:
            with pytest.raises(ValueError, match="max_bytes"):
                cache.get(URL, max_bytes=4)
    assert stream.closed
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_permanent_http_errors_propagate_without_retry(tmp_path, status):
    """不在临时错误列表内的状态码不应重试或被保存成空内容。"""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with DownloadCache(tmp_path, client=client) as cache:
            with pytest.raises(httpx.HTTPStatusError):
                cache.get(URL)
    assert len(calls) == 1
    assert not list(tmp_path.iterdir())


def test_transient_status_retries_are_bounded_and_retry_after_is_capped(tmp_path, monkeypatch):
    """第三次仍被限流时保留失败，并限制 Retry-After 等待。"""
    waits = []
    calls = []
    monkeypatch.setattr("scripts.recipe_dataset_http.time.sleep", waits.append)

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "1000"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with DownloadCache(tmp_path, client=client) as cache:
            with pytest.raises(httpx.HTTPStatusError):
                cache.get(URL)
    assert len(calls) == 3
    assert waits == [30.0, 30.0]
    assert not list(tmp_path.iterdir())


def test_read_timeout_can_retry_then_cache_complete_response(tmp_path, monkeypatch):
    """暂时读取超时后，只缓存最终完整的响应。"""
    calls = []
    monkeypatch.setattr("scripts.recipe_dataset_http.time.sleep", lambda delay: None)

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ReadTimeout("fixture", request=request)
        return httpx.Response(200, content=b"complete")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with DownloadCache(tmp_path, client=client) as cache:
            body, receipt = cache.get(URL)
    assert len(calls) == 3
    assert body == b"complete"
    assert receipt["sha256"] == hashlib.sha256(body).hexdigest()


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadError])
def test_temporary_connection_reset_can_recover_then_cache(tmp_path, monkeypatch, failure):
    """网络重置可在预算内恢复，缓存中只保留成功响应。"""
    calls = []
    monkeypatch.setattr("scripts.recipe_dataset_http.time.sleep", lambda delay: None)

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise failure("connection reset fixture", request=request)
        return httpx.Response(200, content=b"complete")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with DownloadCache(tmp_path, client=client) as cache:
            body, receipt = cache.get(URL)
            assert cache.get(URL) == (body, receipt)
    assert len(calls) == 2
    assert body == b"complete"


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadError])
def test_persistent_connection_error_exhausts_three_attempts(tmp_path, monkeypatch, failure):
    """持续连接故障必须显式失败，不能无限重试或生成无效缓存。"""
    calls = []
    monkeypatch.setattr("scripts.recipe_dataset_http.time.sleep", lambda delay: None)

    def handler(request):
        calls.append(request)
        raise failure("connection reset fixture", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with DownloadCache(tmp_path, client=client) as cache:
            with pytest.raises(failure):
                cache.get(URL)
    assert len(calls) == 3
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("max_bytes", [0, -1, True, 1.5])
def test_invalid_size_limit_is_rejected(tmp_path: Path, max_bytes):
    """无效限额不能进入缓存或 HTTP 路径。"""
    with DownloadCache(tmp_path) as cache:
        with pytest.raises(ValueError, match="positive integer"):
            cache.get(URL, max_bytes=max_bytes)
