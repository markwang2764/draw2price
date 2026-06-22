"""验收测试：限流 + 并发信号量 + LLM 重试(tenacity)。

对照大白话验收标准逐条覆盖：
  1. from slowapi import Limiter 能 import
  2. from tenacity import retry 能 import
  3. /api/analysis/stream/v2 超过 10 次/分钟 → 429
  4. _call_api 方法带 @retry 装饰器（且只对 429/5xx 重试，401/422 不重试）
  5. _ANALYSIS_SEM 把并发限到 4
  6. 全部测试通过（由整套 pytest 运行体现）

注意：tests/conftest.py 有 autouse fixture 在“测试执行时”用假函数 monkeypatch
掉 MistralService._call_api / _call_vision_api。为拿到真实(被 tenacity 装饰的)
方法对象，本模块在 **导入期**(fixture 尚未生效) 就抓取原始引用。
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

# —— 导入期抓取真实(被装饰)方法，绕过 conftest 的运行期 mock ——
from app.services.mistral_service import MistralService

_ORIG_CALL_API = MistralService.__dict__["_call_api"]
_ORIG_CALL_VISION = MistralService.__dict__["_call_vision_api"]


@pytest.fixture(autouse=True)
def mock_ai_calls():
    """同名覆盖 conftest 的 autouse `mock_ai_calls`：本模块要测真实方法/装饰器行为，
    不能让 _call_api/_call_vision_api 被全局假函数替换。"""
    yield


# ───────────────────────── 验收 1 & 2：依赖可 import ─────────────────────────

def test_slowapi_limiter_importable():
    from slowapi import Limiter  # noqa: F401
    from slowapi.util import get_remote_address  # noqa: F401
    from slowapi.errors import RateLimitExceeded  # noqa: F401
    assert Limiter is not None


def test_tenacity_retry_importable():
    from tenacity import retry, stop_after_attempt, wait_exponential  # noqa: F401
    assert retry is not None


# ───────────────────────── 验收 4：_call_api 带 @retry ─────────────────────────

def test_call_api_has_retry_decorator():
    """tenacity 装饰后的函数带 .retry 属性，且 stop=3 次。"""
    assert hasattr(_ORIG_CALL_API, "retry"), "_call_api 缺少 @retry 装饰器"
    assert hasattr(_ORIG_CALL_API, "__wrapped__")
    # stop_after_attempt(3)
    assert _ORIG_CALL_API.retry.stop.max_attempt_number == 3


def test_call_vision_api_has_retry_decorator():
    assert hasattr(_ORIG_CALL_VISION, "retry"), "_call_vision_api 缺少 @retry 装饰器"
    assert _ORIG_CALL_VISION.retry.stop.max_attempt_number == 3


def _make_client(responses):
    """构造假 httpx.AsyncClient：每次 post() 依次吐 responses 里的一个对象。

    responses 元素是 (status_code) ；用真实 httpx.Response 以便 raise_for_status
    抛真正的 HTTPStatusError，命中重试谓词。
    """
    calls = {"n": 0}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            i = min(calls["n"], len(responses) - 1)
            status = responses[calls["n"]] if calls["n"] < len(responses) else responses[-1]
            calls["n"] += 1
            req = httpx.Request("POST", url)
            return httpx.Response(
                status,
                request=req,
                json={"choices": [{"message": {"content": '{"ok": true}'}}]},
            )

    return _FakeClient, calls


@pytest.mark.asyncio
async def test_call_api_no_retry_on_401(monkeypatch):
    """401(鉴权失败) 不重试 —— post 只被调用一次，然后直接抛出。"""
    import app.services.mistral_service as ms

    FakeClient, calls = _make_client([401])
    monkeypatch.setattr(ms.httpx, "AsyncClient", FakeClient)

    svc = ms.MistralService()
    with pytest.raises(httpx.HTTPStatusError):
        await svc._call_api([{"role": "user", "content": "hi"}])
    assert calls["n"] == 1, f"401 不应重试，但 post 调用了 {calls['n']} 次"


@pytest.mark.asyncio
async def test_call_api_retries_on_429_then_succeeds(monkeypatch):
    """429(限流) 可重试：第 1 次 429、第 2 次 200 → 共调用 2 次并最终成功。"""
    import app.services.mistral_service as ms

    FakeClient, calls = _make_client([429, 200])
    monkeypatch.setattr(ms.httpx, "AsyncClient", FakeClient)

    svc = ms.MistralService()
    result = await svc._call_api([{"role": "user", "content": "hi"}])
    assert result == '{"ok": true}'
    assert calls["n"] == 2, f"429 应触发重试，期望 2 次 post，实际 {calls['n']} 次"


@pytest.mark.asyncio
async def test_call_api_retries_5xx_up_to_three_attempts(monkeypatch):
    """500 持续失败 → 重试到 stop_after_attempt(3) 上限后 reraise，共 3 次。"""
    import app.services.mistral_service as ms

    FakeClient, calls = _make_client([500, 500, 500, 500])
    monkeypatch.setattr(ms.httpx, "AsyncClient", FakeClient)

    svc = ms.MistralService()
    with pytest.raises(httpx.HTTPStatusError):
        await svc._call_api([{"role": "user", "content": "hi"}])
    assert calls["n"] == 3, f"5xx 应重试到 3 次上限，实际 {calls['n']} 次"


# ───────────────────────── 验收 5：并发信号量限到 4 ─────────────────────────

def test_analysis_semaphore_limits_to_four():
    # 先导入 app.main（它按正确顺序装配 limiter 再 include analysis_stream），
    # 避免直接导入子模块触发 `from app.main import limiter` 的循环导入。
    import app.main  # noqa: F401
    import app.routers.analysis_stream as a_s

    assert isinstance(a_s._ANALYSIS_SEM, asyncio.Semaphore)
    # 未使用过的 Semaphore，_value 即初始许可数
    assert a_s._ANALYSIS_SEM._value == 4


# ───────────────────────── 验收 3：/stream/v2 限流 10/min → 429 ─────────────────────────

def test_stream_v2_rate_limited_after_ten_requests():
    """对 /api/analysis/stream/v2 连发 11 次：前 10 次 < 429，第 11 次 == 429。"""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    statuses = []
    for _ in range(11):
        # 不带 file/description → 端点早退回错误流，不触发昂贵编排；
        # slowapi 的限流在路由层先计数，足以触发 429。
        resp = client.post("/api/analysis/stream/v2", data={"description": ""})
        statuses.append(resp.status_code)

    assert all(s != 429 for s in statuses[:10]), f"前 10 次不应被限流: {statuses[:10]}"
    assert statuses[10] == 429, f"第 11 次应返回 429，实际 {statuses}"
