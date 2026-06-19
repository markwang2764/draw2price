"""SSE stream formatting helper."""
from __future__ import annotations

import json
from typing import Any, Dict


class StreamEventEmitter:
    def format_event(self, event_type: str, data: Dict[str, Any]) -> str:
        return f"data: {json.dumps({'type': event_type, **data}, ensure_ascii=False)}\n\n"
