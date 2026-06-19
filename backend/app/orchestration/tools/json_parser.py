"""JSON response parsing helper."""
from __future__ import annotations

import json
from typing import Any


class JSONResponseParser:
    def parse(self, payload: Any) -> Any:
        if isinstance(payload, (dict, list)):
            return payload
        if isinstance(payload, str):
            return json.loads(payload)
        raise TypeError(f"Unsupported payload type: {type(payload)!r}")
