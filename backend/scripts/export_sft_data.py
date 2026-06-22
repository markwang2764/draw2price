#!/usr/bin/env python3
"""
导出 SFT 训练数据（从 analyses.db → LLaMA-Factory alpaca JSON）
用法: python scripts/export_sft_data.py [--db analyses.db] [--output sft_data.json] [--min-quality high]
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

SYSTEM_PROMPTS = {
    "process": "你是专业的机加工工艺工程师AI助手。根据零件分析信息，生成符合实际生产条件的工艺路线，以JSON格式输出。",
    "gcode":   "你是专业的数控编程工程师AI助手。根据工序信息和设备参数，生成标准ISO 6983 G代码，以JSON格式输出。",
    "schedule":"你是专业的生产计划工程师AI助手。根据工艺方案和设备资源，生成合理的排产计划，以JSON格式输出。",
    "quotation":"你是专业的机加工报价工程师AI助手。根据零件信息、工艺方案和生产计划，计算准确的加工报价，以JSON格式输出。",
}

def is_high_quality(analysis: dict) -> bool:
    pa = analysis.get("part_analysis", {}) or {}
    review = analysis.get("review", {}) or {}
    if pa.get("confidence") == "low" or pa.get("parse_error"):
        return False
    if review.get("status") == "blocked":
        return False
    if not analysis.get("process_plan") or not analysis.get("gcode_programs"):
        return False
    return True

def make_samples(analysis: dict) -> list:
    samples = []
    pa  = analysis.get("part_analysis", {}) or {}
    pp  = analysis.get("process_plan", {}) or {}
    gc  = analysis.get("gcode_programs", []) or []
    sch = analysis.get("production_schedule", {}) or analysis.get("schedule", {}) or {}
    qt  = analysis.get("quotation", {}) or {}

    # 工艺路线
    if pp:
        samples.append({
            "system": SYSTEM_PROMPTS["process"],
            "instruction": "根据以下零件分析结果，生成完整加工工艺路线",
            "input": json.dumps(pa, ensure_ascii=False),
            "output": json.dumps(pp, ensure_ascii=False),
        })
    # G代码（每道工序一条样本）
    for prog in gc:
        step_num = prog.get("step_number", 1)
        steps = pp.get("steps", [])
        step = next((s for s in steps if s.get("step_number") == step_num), {})
        if step and prog.get("code"):
            samples.append({
                "system": SYSTEM_PROMPTS["gcode"],
                "instruction": f"为以下工序生成G代码程序",
                "input": json.dumps({"step": step, "equipment": prog.get("equipment", "")}, ensure_ascii=False),
                "output": json.dumps({"program_number": prog.get("program_number"), "code": prog.get("code")}, ensure_ascii=False),
            })
    # 排产
    if sch and sch.get("tasks"):
        samples.append({
            "system": SYSTEM_PROMPTS["schedule"],
            "instruction": "根据以下工艺方案生成排产计划",
            "input": json.dumps({"process_plan": pp, "quantity": analysis.get("quantity", 1)}, ensure_ascii=False),
            "output": json.dumps(sch, ensure_ascii=False),
        })
    # 报价
    if qt and qt.get("total", 0) > 0:
        samples.append({
            "system": SYSTEM_PROMPTS["quotation"],
            "instruction": "根据以下信息计算加工报价",
            "input": json.dumps({"part_analysis": pa, "process_plan": pp, "schedule": sch}, ensure_ascii=False),
            "output": json.dumps(qt, ensure_ascii=False),
        })
    return samples

def main():
    parser = argparse.ArgumentParser(description="导出SFT训练数据")
    parser.add_argument("--db", default="analyses.db", help="analyses.db路径")
    parser.add_argument("--output", default="sft_data.json", help="输出JSON路径")
    parser.add_argument("--min-quality", choices=["any", "high"], default="high")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[错误] 数据库不存在: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT data FROM analyses WHERE status='completed'"
        ).fetchall()
    except sqlite3.OperationalError:
        # 数据库存在但还没有 analyses 表（空库）→ 视为零条记录，而非崩溃
        rows = []
    finally:
        conn.close()

    all_samples = []
    skipped = 0
    for row in rows:
        analysis = json.loads(row["data"])
        if args.min_quality == "high" and not is_high_quality(analysis):
            skipped += 1
            continue
        all_samples.extend(make_samples(analysis))

    out_path = Path(args.output)
    out_path.write_text(json.dumps(all_samples, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"导出完成: {len(all_samples)} 条样本（跳过 {skipped} 条低质量分析）→ {out_path}")

if __name__ == "__main__":
    main()
