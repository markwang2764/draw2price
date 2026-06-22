#!/usr/bin/env python3
"""
蒸馏式 SFT 语料生成（强模型 → 高质量训练数据）。

用法（在 backend/ 目录下）:
    # 1) 先把 .env 指向强模型（蒸馏阶段才需要 key）：
    #    MISTRAL_BASE_URL=https://api.mistral.ai/v1   # 或 OpenAI/硅基流动
    #    MISTRAL_MODEL=mistral-large-latest           # 或 gpt-4o
    #    MISTRAL_API_KEY=<你的key>
    # 2) 运行：
    venv/bin/python scripts/generate_sft_corpus.py --output ../training/data/machining_sft.json

对每个「种子零件」依次跑 4 个文本任务（工艺路线→逐工序G代码→排产→报价），
组装成与 export_sft_data.py 完全一致的 alpaca 样本（system/instruction/input/output）。
质量门槛复用 export_sft_data.is_high_quality；解析失败/低置信的整条丢弃。

注意:
- 这是「强模型蒸馏」——务必用云端 large 模型跑，别用本地 7B 自产自销（质量不够）。
- 纯文本 4 任务，不含图纸识别（视觉）。种子零件即「图纸识别后的 part_analysis」。
- 一次完整种子约 3+N 次 LLM 调用（N=工序数），云端跑几十个种子即可攒出几百条样本。
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# 让脚本能 import app.* 与同目录的 export_sft_data
_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "scripts"))

from export_sft_data import make_samples, is_high_quality  # noqa: E402


# ── 种子零件库（= 图纸识别后的 part_analysis，覆盖高频材料/特征/精度）──────────────
# 每条尽量贴近 analyze_drawing 的输出结构，让下游任务拿到真实形态的输入。
SEED_PARTS = [
    {"part_name": "传动轴", "material": "45钢", "overall_dimensions": {"length": 200, "diameter": 50},
     "features": [{"type": "外圆", "diameter": 50, "length": 200}, {"type": "键槽", "width": 14, "depth": 5.5}],
     "tolerances": "外圆φ50h7", "surface_roughness": "Ra1.6", "quantity": 50, "confidence": "high"},
    {"part_name": "法兰盘", "material": "40Cr", "overall_dimensions": {"diameter": 160, "thickness": 25},
     "features": [{"type": "中心孔", "diameter": 40}, {"type": "螺栓孔", "diameter": 13, "count": 6}],
     "tolerances": "中心孔φ40H7", "surface_roughness": "Ra3.2", "quantity": 20, "confidence": "high"},
    {"part_name": "齿轮坯", "material": "42CrMo", "overall_dimensions": {"diameter": 120, "thickness": 40},
     "features": [{"type": "内孔", "diameter": 50}, {"type": "外圆", "diameter": 120}],
     "tolerances": "内孔φ50H7/外圆φ120js6", "surface_roughness": "Ra1.6", "quantity": 30, "confidence": "high"},
    {"part_name": "薄壁套筒", "material": "304不锈钢", "overall_dimensions": {"outer_diameter": 80, "inner_diameter": 72, "length": 100},
     "features": [{"type": "内孔", "diameter": 72}, {"type": "外圆", "diameter": 80}],
     "tolerances": "内孔φ72H8/壁厚4", "surface_roughness": "Ra0.8", "quantity": 15, "confidence": "high"},
    {"part_name": "端盖", "material": "6061铝合金", "overall_dimensions": {"diameter": 90, "thickness": 15},
     "features": [{"type": "止口", "diameter": 60}, {"type": "螺纹孔", "spec": "M6", "count": 4}],
     "tolerances": "止口φ60H7", "surface_roughness": "Ra1.6", "quantity": 100, "confidence": "high"},
    {"part_name": "结构支架", "material": "7075铝合金", "overall_dimensions": {"length": 150, "width": 80, "height": 40},
     "features": [{"type": "型腔", "depth": 20}, {"type": "通孔", "diameter": 8, "count": 4}],
     "tolerances": "型腔±0.05", "surface_roughness": "Ra1.6", "quantity": 25, "confidence": "high"},
    {"part_name": "钛合金接头", "material": "TC4钛合金", "overall_dimensions": {"length": 60, "diameter": 35},
     "features": [{"type": "外圆", "diameter": 35}, {"type": "内螺纹", "spec": "M20"}],
     "tolerances": "外圆φ35h7", "surface_roughness": "Ra0.8", "quantity": 10, "confidence": "high"},
    {"part_name": "高温合金涡轮盘坯", "material": "GH4169高温合金", "overall_dimensions": {"diameter": 180, "thickness": 50},
     "features": [{"type": "中心孔", "diameter": 60}, {"type": "外圆", "diameter": 180}],
     "tolerances": "中心孔φ60H7", "surface_roughness": "Ra0.8", "quantity": 5, "confidence": "high"},
    {"part_name": "铸铁泵体", "material": "HT200灰铸铁", "overall_dimensions": {"length": 200, "width": 150, "height": 120},
     "features": [{"type": "内腔"}, {"type": "轴承孔", "diameter": 62, "count": 2}],
     "tolerances": "轴承孔φ62H7", "surface_roughness": "Ra1.6", "quantity": 40, "confidence": "high"},
    {"part_name": "黄铜阀芯", "material": "H62黄铜", "overall_dimensions": {"length": 70, "diameter": 28},
     "features": [{"type": "外圆", "diameter": 28}, {"type": "锥面", "angle": 60}],
     "tolerances": "外圆φ28g6", "surface_roughness": "Ra0.8", "quantity": 200, "confidence": "high"},
    {"part_name": "深孔导向套", "material": "40Cr", "overall_dimensions": {"length": 300, "diameter": 40},
     "features": [{"type": "深孔", "diameter": 20, "depth": 280}],
     "tolerances": "深孔φ20H8/L:D=14", "surface_roughness": "Ra1.6", "quantity": 12, "confidence": "high"},
    {"part_name": "精密丝杠", "material": "45钢", "overall_dimensions": {"length": 500, "diameter": 32},
     "features": [{"type": "梯形螺纹", "spec": "Tr32x6"}, {"type": "轴颈", "diameter": 25}],
     "tolerances": "轴颈φ25k6", "surface_roughness": "Ra0.4", "quantity": 8, "confidence": "high"},
    {"part_name": "POM绝缘垫块", "material": "POM聚甲醛", "overall_dimensions": {"length": 50, "width": 50, "height": 20},
     "features": [{"type": "沉孔", "diameter": 10, "count": 2}],
     "tolerances": "孔距±0.05", "surface_roughness": "Ra1.6", "quantity": 500, "confidence": "high"},
    {"part_name": "淬硬销轴", "material": "GCr15轴承钢", "overall_dimensions": {"length": 80, "diameter": 16},
     "features": [{"type": "外圆", "diameter": 16}], "heat_treatment": "淬火HRC60",
     "tolerances": "外圆φ16g6", "surface_roughness": "Ra0.4", "quantity": 300, "confidence": "high"},
    {"part_name": "电机端盖", "material": "ZL104铸铝", "overall_dimensions": {"diameter": 130, "thickness": 18},
     "features": [{"type": "轴承位", "diameter": 47}, {"type": "螺纹孔", "spec": "M8", "count": 4}],
     "tolerances": "轴承位φ47H7", "surface_roughness": "Ra1.6", "quantity": 60, "confidence": "high"},
    {"part_name": "液压缸筒", "material": "27SiMn", "overall_dimensions": {"outer_diameter": 100, "inner_diameter": 80, "length": 400},
     "features": [{"type": "内孔", "diameter": 80}], "tolerances": "内孔φ80H8",
     "surface_roughness": "Ra0.4", "quantity": 18, "confidence": "high"},
    {"part_name": "蜗杆", "material": "45钢", "overall_dimensions": {"length": 180, "diameter": 45},
     "features": [{"type": "蜗杆齿", "module": 4}, {"type": "轴颈", "diameter": 30}],
     "tolerances": "轴颈φ30k6", "surface_roughness": "Ra0.8", "quantity": 14, "confidence": "high"},
    {"part_name": "异形凸轮", "material": "40Cr", "overall_dimensions": {"diameter": 100, "thickness": 20},
     "features": [{"type": "凸轮轮廓"}, {"type": "中心孔", "diameter": 25}],
     "tolerances": "轮廓±0.02/中心孔φ25H7", "surface_roughness": "Ra0.8", "quantity": 22, "confidence": "high"},
    {"part_name": "不锈钢轴", "material": "304不锈钢", "overall_dimensions": {"length": 250, "diameter": 30},
     "features": [{"type": "外圆", "diameter": 30}, {"type": "退刀槽", "width": 3}],
     "tolerances": "外圆φ30h7", "surface_roughness": "Ra1.6", "quantity": 35, "confidence": "high"},
    {"part_name": "模具镶件", "material": "Cr12MoV", "overall_dimensions": {"length": 60, "width": 40, "height": 30},
     "features": [{"type": "型面"}, {"type": "冷却孔", "diameter": 6}], "heat_treatment": "淬火HRC58",
     "tolerances": "型面±0.01", "surface_roughness": "Ra0.4", "quantity": 6, "confidence": "high"},
]


async def _build_analysis(part: dict) -> dict:
    """对单个种子零件跑完 4 个文本任务，组装成 export_sft_data 期望的 analysis 结构。"""
    from app.services.mistral_service import mistral_service
    from app.services.analysis_service import analysis_service

    resources = analysis_service.company_resources
    quantity = part.get("quantity", 1)

    # 1) 工艺路线
    process_plan = await mistral_service.generate_process_plan(part, resources)

    # 2) 逐工序 G 代码
    gcode_programs = []
    for idx, step in enumerate(process_plan.get("steps", []), start=1):
        # 给 step 补 step_number，便于 make_samples 把 G代码对回工序
        step = {**step, "step_number": step.get("step_number", idx)}
        equipment = {}
        for eq in resources.get("equipment", []):
            if eq.get("type") == step.get("equipment_type"):
                equipment = eq
                break
        try:
            gc = await mistral_service.generate_gcode(step, equipment)
            gc.setdefault("step_number", step["step_number"])
            gcode_programs.append(gc)
        except Exception as e:
            print(f"      [跳过工序{idx} G代码] {e}")

    # 3) 排产
    schedule = await mistral_service.generate_schedule(
        process_plan, resources, quantity, "normal", None
    )

    # 4) 报价
    quotation = await mistral_service.generate_quotation(
        part, process_plan, schedule, resources, quantity, None
    )

    return {
        "part_analysis": part,
        "process_plan": process_plan,
        "gcode_programs": gcode_programs,
        "schedule": schedule,
        "quotation": quotation,
        "quantity": quantity,
    }


async def main_async(args):
    if args.seeds_file:
        seeds = json.loads(Path(args.seeds_file).read_text(encoding="utf-8"))
    else:
        seeds = SEED_PARTS
    if args.limit:
        seeds = seeds[: args.limit]

    print(f"种子零件 {len(seeds)} 个，开始蒸馏（每个约 3+N 次 LLM 调用）...")
    all_samples = []
    ok, skipped = 0, 0
    for i, part in enumerate(seeds, start=1):
        name = part.get("part_name", f"seed-{i}")
        print(f"[{i}/{len(seeds)}] {name} ({part.get('material','?')}) ...")
        try:
            analysis = await _build_analysis(part)
        except Exception as e:
            print(f"      [整条丢弃] 生成失败: {e}")
            skipped += 1
            continue
        if not is_high_quality(analysis):
            print("      [整条丢弃] 未过质量门槛(解析失败/低置信/缺工艺或G代码)")
            skipped += 1
            continue
        samples = make_samples(analysis)
        all_samples.extend(samples)
        ok += 1
        print(f"      ✓ 产出 {len(samples)} 条样本（累计 {len(all_samples)}）")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(all_samples, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成: {len(all_samples)} 条样本（{ok} 个种子成功 / {skipped} 个丢弃）→ {out}")
    print("下一步: 把该 json 拷到 GPU 机器，按 training/README.md 注册数据并训练。")


def main():
    p = argparse.ArgumentParser(description="蒸馏式 SFT 语料生成")
    p.add_argument("--output", default="../training/data/machining_sft.json", help="输出 alpaca JSON 路径")
    p.add_argument("--limit", type=int, default=0, help="只跑前 N 个种子（调试用，0=全部）")
    p.add_argument("--seeds-file", default="", help="自定义种子 JSON（part_analysis 列表），覆盖内置种子")
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
