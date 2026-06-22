"""
Orchestration nodes — M1~M6 接真实服务。
每个节点：读 state → 调 mistral_service → 写回 state + 发 SSE 事件。
节点函数是同步的（LangGraph 默认），async 调用用 asyncio.run_coroutine_threadsafe。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from ..state import AnalysisState
from ..tools import EquipmentMatcher, StreamEventEmitter

logger = logging.getLogger(__name__)

# 延迟导入，避免循环依赖
def _get_mistral():
    from app.services.mistral_service import mistral_service
    return mistral_service

def _get_resources():
    from app.services.analysis_service import analysis_service
    return analysis_service.company_resources


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _run_async(coro):
    """在已有事件循环里安全执行协程（LangGraph 同步节点调 async service）"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=180)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _emitter(state: AnalysisState) -> Optional[StreamEventEmitter]:
    return state.get("_emitter")


def _emit(state: AnalysisState, event_type: str, **kwargs):
    emitter = _emitter(state)
    if emitter:
        emitter.emit_sync(event_type, kwargs)


def _append_event(state: AnalysisState, event_type: str, content: str, step: int) -> Dict[str, Any]:
    event = {"type": event_type, "step": step, "content": content}
    return {"events": [event]}


# ── M1: 图纸识别节点 ──────────────────────────────────────────────────────────

def identify_node(state: AnalysisState) -> Dict[str, Any]:
    input_data = state.get("input", {}) or {}
    _emit(state, "thinking", step=1, title="图纸识别", content="正在识别零件特征...")

    try:
        mistral = _get_mistral()
        images = input_data.get("images")          # [(base64, file_type), ...]
        description = input_data.get("description")

        if images:
            # 取第一张（多页 PDF 已在路由层转好）
            img_b64, file_type = images[0]
            part_analysis = _run_async(mistral.analyze_drawing(img_b64, file_type))
        elif description:
            part_analysis = _run_async(mistral.analyze_drawing_from_text(description))
        else:
            part_analysis = {
                "part_name": "未知零件",
                "confidence": "low",
                "parse_error": True,
                "error": "无图纸或描述输入",
            }

        updates = {"part_analysis": part_analysis}
        updates.update(_append_event(state, "step_complete", "图纸识别完成", 1))
        _emit(state, "step_complete", step=1, title="图纸识别", result=part_analysis)
        return updates

    except Exception as e:
        logger.exception("identify_node failed")
        err = {"step": "identify", "error": str(e)}
        updates = {
            "part_analysis": {"part_name": "识别失败", "confidence": "low", "error": str(e)},
            "errors": [err],
        }
        updates.update(_append_event(state, "step_complete", f"识别失败: {e}", 1))
        return updates


# ── M2: 工艺规划节点 ──────────────────────────────────────────────────────────

def process_node(state: AnalysisState) -> Dict[str, Any]:
    part_analysis = state.get("part_analysis") or {}
    _emit(state, "thinking", step=2, title="工艺规划", content="正在生成工艺路线...")

    try:
        mistral = _get_mistral()
        resources = _get_resources()
        process_plan = _run_async(mistral.generate_process_plan(part_analysis, resources))

        updates = {"process_plan": process_plan}
        updates.update(_append_event(state, "step_complete", "工艺规划完成", 2))
        _emit(state, "step_complete", step=2, title="工艺规划", result=process_plan)
        return updates

    except Exception as e:
        logger.exception("process_node failed")
        fallback = {"steps": [], "total_steps": 0, "part_name": part_analysis.get("part_name", "未知")}
        updates = {"process_plan": fallback, "errors": [{"step": "process", "error": str(e)}]}
        updates.update(_append_event(state, "step_complete", f"工艺规划失败: {e}", 2))
        return updates


# ── M3: G 代码节点（支持多工序，每步独立调用）─────────────────────────────────

def gcode_node(state: AnalysisState) -> Dict[str, Any]:
    process_plan = state.get("process_plan") or {}
    steps = process_plan.get("steps", [])
    resources = _get_resources()
    matcher = EquipmentMatcher(resources.get("equipment", []))

    _emit(state, "thinking", step=3, title="G代码生成", content=f"正在为 {len(steps)} 道工序生成 G 代码...")

    try:
        mistral = _get_mistral()
        gcode_programs = []

        for idx, step in enumerate(steps, start=1):
            equipment = matcher.match(step.get("equipment_type")) or {}
            _emit(state, "thinking", step=3, title="G代码生成",
                  content=f"工序 {idx}/{len(steps)}: {step.get('process_name', '')}...")
            gcode = _run_async(mistral.generate_gcode(step, equipment))
            gcode_programs.append(gcode)

        updates = {"gcode_programs": gcode_programs}
        updates.update(_append_event(state, "step_complete", f"G代码生成完成 ({len(gcode_programs)} 个程序)", 3))
        _emit(state, "step_complete", step=3, title="G代码生成", count=len(gcode_programs))
        return updates

    except Exception as e:
        logger.exception("gcode_node failed")
        updates = {"gcode_programs": [], "errors": [{"step": "gcode", "error": str(e)}]}
        updates.update(_append_event(state, "step_complete", f"G代码生成失败: {e}", 3))
        return updates


# ── M4: 排产节点 ──────────────────────────────────────────────────────────────

def schedule_node(state: AnalysisState) -> Dict[str, Any]:
    process_plan = state.get("process_plan") or {}
    input_data = state.get("input", {}) or {}
    _emit(state, "thinking", step=4, title="排产计划", content="正在生成排产方案...")

    try:
        mistral = _get_mistral()
        resources = _get_resources()
        schedule = _run_async(mistral.generate_schedule(
            process_plan,
            resources,
            input_data.get("quantity", 1),
            input_data.get("priority", "normal"),
            input_data.get("due_date"),
        ))

        updates = {"schedule": schedule}
        updates.update(_append_event(state, "step_complete", "排产计划完成", 4))
        _emit(state, "step_complete", step=4, title="排产计划", result=schedule)
        return updates

    except Exception as e:
        logger.exception("schedule_node failed")
        updates = {"schedule": {"tasks": [], "total_hours": 0}, "errors": [{"step": "schedule", "error": str(e)}]}
        updates.update(_append_event(state, "step_complete", f"排产失败: {e}", 4))
        return updates


# ── M6: 审查节点（在 gcode+schedule 后、quotation 前）──────────────────────────

def review_node(state: AnalysisState) -> Dict[str, Any]:
    _emit(state, "thinking", step=5, title="工艺审查", content="正在交叉校验工艺方案...")

    issues = []
    part_analysis  = state.get("part_analysis") or {}
    process_plan   = state.get("process_plan") or {}
    gcode_programs = state.get("gcode_programs") or []
    schedule       = state.get("schedule") or {}
    resources      = _get_resources()

    equipment_ids = {eq["id"] for eq in resources.get("equipment", []) if "id" in eq}
    equipment_types = {eq["id"]: eq.get("type", "") for eq in resources.get("equipment", [])}

    # 规则 1: 刀具存在性 — G代码里用到的 T 号必须在 tool_list 里
    for prog in gcode_programs:
        code = prog.get("code", "")
        tool_list = {str(t.get("number", "")) for t in prog.get("tool_list", [])}
        import re
        used_tools = set(re.findall(r"T(\d+)", code))
        missing = used_tools - tool_list
        if missing:
            issues.append({
                "severity": "critical",
                "rule": "tool_existence",
                "message": f"程序 {prog.get('program_number')} 使用了未定义刀具 T{missing}",
            })

    # 规则 2: 设备一致性 — 排产任务的 equipment_id 必须存在于资源表
    for task in schedule.get("tasks", []):
        eid = task.get("equipment_id", "")
        if eid and equipment_ids and eid not in equipment_ids:
            issues.append({
                "severity": "major",
                "rule": "equipment_existence",
                "message": f"排产任务引用了未知设备 {eid}",
            })

    # 规则 3: 公差-工艺一致性 — 精密公差必须有精加工工序
    tolerances = str(part_analysis.get("tolerances", ""))
    has_precision = any(t in tolerances for t in ["H6", "h6", "H7", "h7", "k6", "H8"])
    step_names = " ".join(s.get("process_name", "") for s in process_plan.get("steps", []))
    has_finish = any(k in step_names for k in ["精车", "精铣", "磨削", "镗", "珩磨"])
    if has_precision and not has_finish:
        issues.append({
            "severity": "major",
            "rule": "tolerance_process",
            "message": "零件含精密公差但工艺路线缺少精加工/磨削工序",
        })

    # 规则 4: 低置信识别阻断
    if part_analysis.get("confidence") == "low" or part_analysis.get("parse_error"):
        issues.append({
            "severity": "critical",
            "rule": "low_confidence",
            "message": "图纸识别置信度低，建议人工复核后再导出",
        })

    # 规则 5: _warnings 上升为 review issues
    for prog in gcode_programs:
        for w in prog.get("_warnings", []):
            issues.append({"severity": "major", "rule": "param_range", "message": w})

    critical = [i for i in issues if i["severity"] == "critical"]
    status = "blocked" if critical else ("requires_review" if issues else "approved")

    review = {
        "status": status,
        "issues": issues,
        "summary": f"{'阻断' if status == 'blocked' else '需复核' if status == 'requires_review' else '通过'}，共 {len(issues)} 条问题",
    }

    updates = {"review": review}
    updates.update(_append_event(state, "step_complete", review["summary"], 5))
    _emit(state, "step_complete", step=5, title="工艺审查", result=review)
    return updates


# ── M5: 报价节点 ──────────────────────────────────────────────────────────────

def quotation_node(state: AnalysisState) -> Dict[str, Any]:
    _emit(state, "thinking", step=6, title="报价生成", content="正在计算工艺成本和报价...")

    try:
        mistral = _get_mistral()
        resources = _get_resources()
        input_data = state.get("input", {}) or {}

        quotation = _run_async(mistral.generate_quotation(
            state.get("part_analysis") or {},
            state.get("process_plan") or {},
            state.get("schedule") or {},
            resources,
            input_data.get("quantity", 1),
            input_data.get("customer"),
        ))

        # 规则: 总价一致性校验
        total = quotation.get("total", 0)
        items_sum = sum(
            quotation.get(k, 0)
            for k in ("material_cost", "processing_cost", "equipment_cost", "labor_cost", "overhead")
        )
        if items_sum > 0 and abs(total - items_sum) / max(items_sum, 1) > 0.01:
            quotation.setdefault("_warnings", []).append(
                f"报价总额 {total} 与明细之和 {items_sum:.2f} 不一致，请复核"
            )

        review = state.get("review") or {}
        review_status = review.get("status", "approved")
        quotation["review_status"] = review_status
        quotation["exportable"] = review_status != "blocked"

        updates = {"quotation": quotation}
        updates.update(_append_event(state, "complete", "报价完成", 6))
        _emit(state, "step_complete", step=6, title="报价生成", result=quotation)
        return updates

    except Exception as e:
        logger.exception("quotation_node failed")
        updates = {"quotation": {"total": 0, "error": str(e)}, "errors": [{"step": "quotation", "error": str(e)}]}
        updates.update(_append_event(state, "complete", f"报价失败: {e}", 6))
        return updates
