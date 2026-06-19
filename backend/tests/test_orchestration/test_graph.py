import pytest

from app.orchestration.graph import build_graph


@pytest.mark.asyncio
async def test_build_graph_importable():
    graph = build_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_graph_ainvoke_produces_all_outputs():
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
        }
    )
    assert result["part_analysis"]
    assert result["process_plan"]
    assert result["gcode_programs"]
    assert result["schedule"]
    assert result["quotation"]
    assert result["review"]
    # 回归：events 用 operator.add reducer，每个节点只应贡献 1 个事件。
    # 若节点错误地返回整个累积列表，reducer 会重复累加导致事件膨胀。
    assert len(result["events"]) == 6, f"事件数应为 6，实际 {len(result['events'])}"
    assert [e["type"] for e in result["events"]] == ["step_complete"] * 6
