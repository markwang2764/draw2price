import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.orchestration.graph import build_graph

_STUB_PART = {
    "part_name": "测试轴",
    "material": "45钢",
    "confidence": "high",
    "features": [{"name": "外圆", "diameter": 50}],
    "overall_dimensions": {"length": 100, "diameter": 50},
    "tolerances": "h7",
}
_STUB_PLAN = {
    "part_name": "测试轴",
    "steps": [
        {
            "step_number": 1,
            "process_name": "粗车",
            "equipment_type": "CNC_LATHE",
            "cutting_parameters": {"spindle_speed": 800, "feed_rate": 0.3, "depth_of_cut": 2},
        }
    ],
    "total_steps": 1,
}
_STUB_GCODE = {
    "program_number": "O0001",
    "step_number": 1,
    "equipment": "CNC车床1",
    "code": "G0 X0 Z0\nT01 M06\nG01 X50 F0.3\nM30",
    "tool_list": [{"number": "01", "name": "外圆刀"}],
}
_STUB_SCHEDULE = {
    "start_date": "2026-06-22",
    "tasks": [{"task_id": "T001", "equipment_id": "EQ-1", "status": "planned"}],
    "total_hours": 2,
    "utilization_rate": 0.75,
}
_STUB_QUOTATION = {
    "total": 1000.0,
    "material_cost": 400,
    "processing_cost": 400,
    "equipment_cost": 100,
    "labor_cost": 50,
    "overhead": 50,
}


def _make_mock_mistral():
    m = MagicMock()
    m.analyze_drawing_from_text = AsyncMock(return_value=_STUB_PART)
    m.analyze_drawing = AsyncMock(return_value=_STUB_PART)
    m.generate_process_plan = AsyncMock(return_value=_STUB_PLAN)
    m.generate_gcode = AsyncMock(return_value=_STUB_GCODE)
    m.generate_schedule = AsyncMock(return_value=_STUB_SCHEDULE)
    m.generate_quotation = AsyncMock(return_value=_STUB_QUOTATION)
    return m


@pytest.mark.asyncio
async def test_build_graph_importable():
    graph = build_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_graph_ainvoke_produces_all_outputs():
    mock_mistral = _make_mock_mistral()

    with patch("app.orchestration.nodes._get_mistral", return_value=mock_mistral):
        graph = build_graph()
        result = await graph.ainvoke(
            {
                "input": {
                    "description": "测试零件",
                    "equipment": [
                        {"id": "EQ-1", "name": "CNC车床1", "type": "CNC_LATHE", "status": "available"},
                        {"id": "EQ-2", "name": "CNC铣床1", "type": "CNC_MILL", "status": "available"},
                    ],
                },
                "events": [],
                "errors": [],
                "gcode_programs": [],
            },
            config={"configurable": {"thread_id": "test-run"}},
        )

    assert result["part_analysis"]["part_name"] == "测试轴"
    assert result["process_plan"]["total_steps"] == 1
    assert len(result["gcode_programs"]) == 1
    assert result["schedule"]["total_hours"] == 2
    assert result["quotation"]["total"] == 1000.0
    assert result["review"] is not None
    assert result["review"]["status"] in ("approved", "requires_review", "blocked")

    # 回归：events 用 operator.add reducer，每个节点只应贡献 1 个事件。
    # identify/process/gcode/schedule/review/quotation = 6 节点各 1 事件。
    assert len(result["events"]) == 6, f"事件数应为 6，实际 {len(result['events'])}"
    assert all(e["type"] == "step_complete" for e in result["events"][:-1])
