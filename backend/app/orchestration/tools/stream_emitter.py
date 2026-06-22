"""SSE stream bridge: nodes put events into an asyncio.Queue; FastAPI consumes it."""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict, Optional


class StreamEventEmitter:
    """
    节点调用 emit() 把事件放进队列；
    FastAPI 侧 await events() 异步迭代取出后推给前端 SSE。
    """

    def __init__(self, queue: Optional[asyncio.Queue] = None):
        self._queue: asyncio.Queue = queue or asyncio.Queue()

    # ── 节点侧 ────────────────────────────────────────────────────────────────

    async def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        await self._queue.put({"type": event_type, **data})

    def emit_sync(self, event_type: str, data: Dict[str, Any]) -> None:
        """同步节点调用（LangGraph 节点默认同步）"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(self._queue.put_nowait, {"type": event_type, **data})
            else:
                self._queue.put_nowait({"type": event_type, **data})
        except Exception:
            self._queue.put_nowait({"type": event_type, **data})

    async def close(self) -> None:
        """通知消费者流结束"""
        await self._queue.put(None)

    # ── FastAPI 侧 ────────────────────────────────────────────────────────────

    async def events(self) -> AsyncIterator[str]:
        """异步迭代，产出 SSE 格式字符串，收到 None 哨兵则停止"""
        while True:
            item = await self._queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    # ── 工具方法 ──────────────────────────────────────────────────────────────

    @staticmethod
    def format_event(event_type: str, data: Dict[str, Any]) -> str:
        """节点内部格式化（不走队列，用于测试）"""
        return f"data: {json.dumps({'type': event_type, **data}, ensure_ascii=False)}\n\n"
