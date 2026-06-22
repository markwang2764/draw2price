#!/usr/bin/env python3
"""
训后评估：对微调模型在验证集上的输出算硬指标（对照 docs/本地训练待办.md 第5节）。

输入 predictions.jsonl，每行一个 JSON：
    {"task": "process|gcode|schedule|quotation", "output": "<模型输出字符串>", "reference": "<参考输出字符串>"}
（output/reference 都是模型应产出的 JSON 字符串；reference 来自蒸馏数据的 output 字段。）

用法:
    python evaluate.py --pred predictions.jsonl

指标:
    - JSON 合法率   : output 能被 json.loads 解析的比例          目标 100%
    - G代码语法正确率: task=gcode 的 code 无非法 G/M 码           目标 100%
    - 工序完整率     : task=process 模型工序数 / 参考工序数        目标 ≥90%
    - 报价 MAPE     : task=quotation 的 total 相对误差均值        目标 ≤10%

本脚本自包含，不依赖 backend（可直接在 GPU 机器跑）。
"""
import argparse
import json
import re
from pathlib import Path

# ISO 6983 常用 G/M 码集（与 backend/app/orchestration/tools/gcode_validator.py 同口径，精简内联）
_VALID_G = {0, 1, 2, 3, 4, 17, 18, 19, 20, 21, 28, 29, 40, 41, 42, 43, 44, 49,
            54, 55, 56, 57, 58, 59, 70, 71, 73, 74, 76, 80, 81, 82, 83, 84, 85,
            86, 87, 88, 89, 90, 91, 92, 94, 95, 96, 97, 98, 99}
_VALID_M = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 19, 30, 48, 49, 98, 99}


def _try_json(s):
    try:
        return json.loads(s)
    except Exception:
        return None


def _gcode_syntax_ok(code: str) -> bool:
    for raw in (code or "").splitlines():
        line = re.sub(r"^N\d+\s*", "", raw.strip())
        if not line or line[0] in ";(%":
            continue
        for g in re.findall(r"[Gg](\d+\.?\d*)", line):
            if int(float(g)) not in _VALID_G:
                return False
        for m in re.findall(r"[Mm](\d+)", line):
            if int(m) not in _VALID_M:
                return False
    return True


def main():
    ap = argparse.ArgumentParser(description="微调模型评估")
    ap.add_argument("--pred", required=True, help="predictions.jsonl 路径")
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.pred).read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:
        print("无数据")
        return

    n = len(rows)
    json_ok = 0
    gcode_total = gcode_ok = 0
    proc_ratios = []
    mapes = []

    for r in rows:
        task = r.get("task", "")
        out = _try_json(r.get("output", ""))
        ref = _try_json(r.get("reference", ""))
        if out is not None:
            json_ok += 1

        if task == "gcode" and out:
            gcode_total += 1
            if _gcode_syntax_ok(out.get("code", "")):
                gcode_ok += 1

        if task == "process" and out and ref:
            ref_steps = len(ref.get("steps", []) or [])
            out_steps = len(out.get("steps", []) or [])
            if ref_steps:
                proc_ratios.append(min(1.0, out_steps / ref_steps))

        if task == "quotation" and out and ref:
            ref_total = ref.get("total", 0) or 0
            out_total = out.get("total", 0) or 0
            if ref_total:
                mapes.append(abs(out_total - ref_total) / ref_total)

    def pct(x):
        return f"{x*100:.1f}%"

    print(f"样本总数: {n}")
    print(f"JSON 合法率   : {pct(json_ok/n)}  ({json_ok}/{n})            目标 100%")
    if gcode_total:
        print(f"G代码语法正确率: {pct(gcode_ok/gcode_total)}  ({gcode_ok}/{gcode_total})        目标 100%")
    if proc_ratios:
        print(f"工序完整率     : {pct(sum(proc_ratios)/len(proc_ratios))}  (n={len(proc_ratios)})    目标 ≥90%")
    if mapes:
        print(f"报价 MAPE     : {pct(sum(mapes)/len(mapes))}  (n={len(mapes)})         目标 ≤10%")
    print("\n判定: 各项 ≥ 现有 prompt 工程方案，才值得挂回平台。")


if __name__ == "__main__":
    main()
