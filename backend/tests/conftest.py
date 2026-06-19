"""Shared pytest fixtures for backend tests."""
from __future__ import annotations

from typing import Any, Dict

import pytest


@pytest.fixture(autouse=True)
def mock_ai_calls(monkeypatch):
    async def fake_call_api(*args, **kwargs):
        return '{"part_name":"Mock Part","features":[{"name":"mock"}],"complexity_level":"中等"}'

    async def fake_call_vision_api(*args, **kwargs):
        return '{"part_name":"Mock Part","features":[{"name":"mock"}],"complexity_level":"中等"}'

    from app.services.mistral_service import MistralService

    monkeypatch.setattr(MistralService, "_call_api", fake_call_api)
    monkeypatch.setattr(MistralService, "_call_vision_api", fake_call_vision_api)
    yield


@pytest.fixture
def sample_input() -> Dict[str, Any]:
    return {
        "description": "测试零件",
        "equipment": [
            {"id": "EQ-1", "name": "CNC车床1", "type": "CNC_LATHE", "status": "available"},
            {"id": "EQ-2", "name": "CNC铣床1", "type": "CNC_MILL", "status": "available"},
        ],
    }
