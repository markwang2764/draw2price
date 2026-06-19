"""Placeholder orchestration nodes for M0."""
from __future__ import annotations

from typing import Any, Dict

from ..state import AnalysisState
from ..tools import EquipmentMatcher, StreamEventEmitter


_emitter = StreamEventEmitter()


def _append_event(state: AnalysisState, event_type: str, content: str, step: int) -> Dict[str, Any]:
    # events 字段在 state 中用 operator.add 作为 reducer，会自动把各节点返回的
    # 列表拼接起来。因此这里只返回「新增的那一个事件」，不要再手动并入旧列表，
    # 否则会和 reducer 重复累加导致事件指数级膨胀。
    event = {"type": event_type, "step": step, "content": content}
    return {"events": [event]}


def identify_node(state: AnalysisState) -> Dict[str, Any]:
    input_data = state.get("input", {})
    part_analysis = {
        "part_name": input_data.get("description", "待识别零件") or "待识别零件",
        "features": [],
        "complexity_level": "中等",
    }
    updates = {"part_analysis": part_analysis}
    updates.update(_append_event(state, "step_complete", "identify 完成", 1))
    return updates


def process_node(state: AnalysisState) -> Dict[str, Any]:
    process_plan = {
        "part_name": (state.get("part_analysis") or {}).get("part_name", "待识别零件"),
        "steps": [
            {"step_number": 1, "process_name": "粗加工", "equipment_type": "CNC_LATHE"},
            {"step_number": 2, "process_name": "精加工", "equipment_type": "CNC_MILL"},
        ],
        "total_steps": 2,
    }
    updates = {"process_plan": process_plan}
    updates.update(_append_event(state, "step_complete", "process 完成", 2))
    return updates


def gcode_node(state: AnalysisState) -> Dict[str, Any]:
    matcher = EquipmentMatcher((state.get("input", {}) or {}).get("equipment", []))
    gcode_programs = []
    for idx, step in enumerate((state.get("process_plan") or {}).get("steps", []), start=1):
        equipment = matcher.match(step.get("equipment_type")) or {}
        gcode_programs.append({
            "program_number": f"O{idx:04d}",
            "step_number": step.get("step_number", idx),
            "equipment": equipment.get("name", "DEFAULT"),
            "code": f"; placeholder for {step.get('process_name', 'step')}"
        })
    if not gcode_programs:
        gcode_programs = [{
            "program_number": "O0001",
            "step_number": 1,
            "equipment": "DEFAULT",
            "code": "; placeholder"
        }]
    updates = {"gcode_programs": gcode_programs}
    updates.update(_append_event(state, "step_complete", "gcode 完成", 3))
    return updates


def schedule_node(state: AnalysisState) -> Dict[str, Any]:
    schedule = {
        "start_date": "2026-06-05",
        "tasks": [
            {"task_id": "TASK-001", "status": "planned"}
        ],
        "total_hours": 2,
        "utilization_rate": 0.75,
    }
    updates = {"schedule": schedule}
    updates.update(_append_event(state, "step_complete", "schedule 完成", 3))
    return updates


def quotation_node(state: AnalysisState) -> Dict[str, Any]:
    quotation = {"total": 0.0, "items": []}
    updates = {"quotation": quotation}
    updates.update(_append_event(state, "step_complete", "quotation 完成", 4))
    return updates


def review_node(state: AnalysisState) -> Dict[str, Any]:
    review = {"status": "pending", "summary": "M0 placeholder review"}
    updates = {"review": review}
    updates.update(_append_event(state, "step_complete", "review 完成", 5))
    return updates
