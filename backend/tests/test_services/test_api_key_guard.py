"""回归：空 API key 时应清晰报错而非崩成 LocalProtocolError，且不被无谓重试。

现象(运行时发现): backend/.env 缺 MISTRAL_API_KEY → header 拼成 "Bearer " →
httpx 抛 LocalProtocolError(TransportError 子类)→ 被 _is_retryable_api_error 误判可重试 →
重试 3 次后抛一长串难懂堆栈。
"""
import httpx
import pytest

from app.services.mistral_service import (
    MistralService,
    _is_local_endpoint,
    _is_retryable_api_error,
)


@pytest.fixture(autouse=True)
def mock_ai_calls():
    """覆盖 conftest 的自动打桩：本模块要验证 _call_api/_call_vision_api 的真实空 key 守卫，
    不能让它们被替换成假函数。空 key + 云端会在发请求前抛错，不会产生真实外部调用。"""
    yield


def test_is_local_endpoint():
    assert _is_local_endpoint("http://localhost:11434/v1")
    assert _is_local_endpoint("http://127.0.0.1:8080")
    assert not _is_local_endpoint("https://api.mistral.ai/v1")


def test_local_protocol_error_not_retryable():
    # LocalProtocolError 是 httpx.TransportError 子类，但属于本地构造错误，重试无意义
    assert _is_retryable_api_error(httpx.LocalProtocolError("Illegal header value b'Bearer '")) is False
    # 对照：超时仍应重试
    assert _is_retryable_api_error(httpx.ConnectTimeout("timeout")) is True


@pytest.mark.asyncio
async def test_call_api_empty_key_cloud_raises_clear_error():
    svc = MistralService()
    svc.api_key = ""
    svc.base_url = "https://api.mistral.ai/v1"
    with pytest.raises(RuntimeError) as ei:
        await svc._call_api([{"role": "user", "content": "hi"}])
    assert "MISTRAL_API_KEY" in str(ei.value)


@pytest.mark.asyncio
async def test_vision_api_empty_key_cloud_raises_clear_error():
    svc = MistralService()
    svc.api_key = ""
    svc.base_url = "https://api.mistral.ai/v1"
    # 合法的 1x1 png base64
    png_b64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII=")
    with pytest.raises(RuntimeError) as ei:
        await svc._call_vision_api(png_b64, "png", "describe")
    assert "MISTRAL_API_KEY" in str(ei.value)


@pytest.mark.asyncio
async def test_call_api_empty_key_local_does_not_raise_keyerror():
    """本地端点(Ollama)空 key 不应触发 key 守卫；连接失败是另一回事(网络错误)。"""
    svc = MistralService()
    svc.api_key = ""
    svc.base_url = "http://localhost:59999/v1"  # 无人监听 → 连接错误，而非 RuntimeError(key)
    with pytest.raises(Exception) as ei:
        await svc._call_api([{"role": "user", "content": "hi"}])
    assert "MISTRAL_API_KEY" not in str(ei.value)
