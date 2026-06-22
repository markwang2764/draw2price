"""A 模块（横切准确度改进）测试：
1. _call_api / _call_vision_api 默认开启 JSON 结构化输出，可关闭以回退。
2. analyze_drawing 解析失败时返回低置信标记，而非静默假数据。
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def mock_ai_calls():
    """覆盖 conftest 的全局 mock：本模块要测真实的 _call_api/_call_vision_api 行为。"""
    yield


class _FakeResponse:
    def __init__(self, content):
        self.status_code = 200
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}

    def raise_for_status(self):
        pass


class _CapturingClient:
    """捕获 httpx.AsyncClient.post 的 payload，避免真实网络调用。"""

    captured_payload = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None):
        _CapturingClient.captured_payload = json
        return _FakeResponse('{"ok": true}')


@pytest.fixture
def real_service(monkeypatch):
    """绕过 conftest 对 _call_api/_call_vision_api 的 mock，用真方法 + 假 httpx。"""
    import app.services.mistral_service as ms

    monkeypatch.setattr(ms.httpx, "AsyncClient", _CapturingClient)
    _CapturingClient.captured_payload = None
    svc = ms.MistralService()
    svc.api_key = "test-key"  # 非空 key 以通过空 key 守卫，进入请求构造路径
    return svc


@pytest.mark.asyncio
async def test_call_api_enables_json_mode_by_default(real_service):
    await real_service._call_api([{"role": "user", "content": "hi"}])
    payload = _CapturingClient.captured_payload
    assert payload["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_call_api_json_mode_can_be_disabled(real_service):
    await real_service._call_api([{"role": "user", "content": "hi"}], json_mode=False)
    payload = _CapturingClient.captured_payload
    assert "response_format" not in payload


@pytest.mark.asyncio
async def test_vision_api_cloud_enables_json_mode(real_service):
    real_service.is_cloud_api = True
    # 1x1 png base64
    img = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC"
    )
    await real_service._call_vision_api(img, "png", "describe")
    payload = _CapturingClient.captured_payload
    assert payload["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_analyze_drawing_parse_failure_returns_low_confidence(real_service, monkeypatch):
    async def fake_vision(*args, **kwargs):
        return "this is not json at all <<<"

    monkeypatch.setattr(real_service, "_call_vision_api", fake_vision)
    img = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC"
    result = await real_service.analyze_drawing(img, "png")

    assert result["confidence"] == "low"
    assert result["part_name"] == "识别失败-待人工确认"
    # 关键：不再返回写死的 45 钢假零件
    material = result.get("material", {})
    assert material.get("name") != "45钢"
    assert result["features"] == []
