"""M3 任务 #3 回归：gcode_node / schedule_node 在调用 LLM 前注入 RAG 上下文。

验收要点:
1. gcode_node 给 generate_gcode 的 step 参数带 _tool_rag 字段（list）
2. schedule_node 给 generate_schedule 的 process_plan 参数带 _time_rag 字段（list）
3. 知识库未初始化 / 检索抛异常时，节点正常运行不报错，RAG 字段为空列表
4. generate_gcode / generate_schedule 的调用签名（位置参数）不变
"""
from unittest.mock import AsyncMock, MagicMock, patch

from app.orchestration.nodes import gcode_node, schedule_node

_PART = {"part_name": "测试轴", "material": "45钢", "confidence": "high"}
_PLAN = {
    "part_name": "测试轴",
    "steps": [{"step_number": 1, "process_name": "粗车", "equipment_type": "CNC_LATHE"}],
    "total_steps": 1,
}
_RESOURCES = {"equipment": [{"id": "EQ-1", "name": "车床1", "type": "CNC_LATHE"}]}


def _mistral_with(gcode=None, schedule=None):
    m = MagicMock()
    m.generate_gcode = AsyncMock(return_value=gcode or {"program_number": "O0001", "code": "M30"})
    m.generate_schedule = AsyncMock(return_value=schedule or {"tasks": [], "total_hours": 1})
    return m


def _patches(mistral, retrieve_return=None, retrieve_raises=False):
    """统一打桩 _get_mistral / _get_resources / KnowledgeRetriever。"""
    retriever = MagicMock()
    if retrieve_raises:
        retriever.retrieve.side_effect = RuntimeError("chromadb 未初始化")
    else:
        retriever.retrieve.return_value = retrieve_return or []
    return [
        patch("app.orchestration.nodes._get_mistral", return_value=mistral),
        patch("app.orchestration.nodes._get_resources", return_value=_RESOURCES),
        patch("app.orchestration.nodes.KnowledgeRetriever", return_value=retriever),
    ]


def _run(node, state, mistral, **kw):
    ps = _patches(mistral, **kw)
    for p in ps:
        p.start()
    try:
        return node(state)
    finally:
        for p in ps:
            p.stop()


def test_gcode_node_injects_tool_rag():
    mistral = _mistral_with()
    state = {"process_plan": _PLAN, "part_analysis": _PART}
    _run(gcode_node, state, mistral, retrieve_return=[{"content": "CNMG120408 通用刀片"}])

    args, _ = mistral.generate_gcode.call_args
    step_arg = args[0]
    assert "_tool_rag" in step_arg
    assert step_arg["_tool_rag"] == ["CNMG120408 通用刀片"]
    # 原 step 字段保留、签名不变（位置参数 step, equipment）
    assert step_arg["process_name"] == "粗车"
    assert len(args) == 2


def test_schedule_node_injects_time_rag():
    mistral = _mistral_with()
    state = {"process_plan": _PLAN, "part_analysis": _PART, "input": {"quantity": 2}}
    _run(schedule_node, state, mistral, retrieve_return=[{"content": "机床利用率按 75% 估"}])

    args, _ = mistral.generate_schedule.call_args
    plan_arg = args[0]
    assert "_time_rag" in plan_arg
    assert plan_arg["_time_rag"] == ["机床利用率按 75% 估"]
    assert plan_arg["part_name"] == "测试轴"


def test_gcode_node_survives_empty_knowledge():
    """知识库返回空 → _tool_rag 为空列表，节点照常产出。"""
    mistral = _mistral_with()
    state = {"process_plan": _PLAN, "part_analysis": _PART}
    out = _run(gcode_node, state, mistral, retrieve_return=[])

    assert out["gcode_programs"]  # 仍生成了程序
    step_arg = mistral.generate_gcode.call_args[0][0]
    assert step_arg["_tool_rag"] == []


def test_nodes_survive_retrieve_exception():
    """检索抛异常时（知识库未初始化）节点不崩溃，降级为空 RAG。"""
    mistral = _mistral_with()
    g_state = {"process_plan": _PLAN, "part_analysis": _PART}
    g_out = _run(gcode_node, g_state, mistral, retrieve_raises=True)
    assert g_out["gcode_programs"]
    assert mistral.generate_gcode.call_args[0][0]["_tool_rag"] == []

    s_state = {"process_plan": _PLAN, "part_analysis": _PART, "input": {}}
    s_out = _run(schedule_node, s_state, mistral, retrieve_raises=True)
    assert "schedule" in s_out
    assert mistral.generate_schedule.call_args[0][0]["_time_rag"] == []
