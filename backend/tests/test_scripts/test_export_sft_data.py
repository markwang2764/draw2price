"""
测试出题人：export_sft_data.py 导出脚本验收测试。
与实现分离，只验证实现是否满足大白话验收标准（逐条覆盖）。
不改动任何实现代码；通过子进程运行脚本，贴合脚本真实 CLI 行为。
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export_sft_data.py"


def _make_db(db_path: Path, records):
    """records: list of (id, status, data_dict)"""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS analyses (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            data TEXT NOT NULL
        )
        """
    )
    for i, (rid, status, data) in enumerate(records):
        conn.execute(
            "INSERT OR REPLACE INTO analyses (id, created_at, status, data) VALUES (?,?,?,?)",
            (rid, f"2026-06-22T00:00:0{i}", status, json.dumps(data, ensure_ascii=False)),
        )
    conn.commit()
    conn.close()


def _run(args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def _high_quality_analysis():
    """一条完整的高质量分析，覆盖 工艺/G代码/排产/报价 四类样本。"""
    return {
        "part_analysis": {"material": "45钢", "confidence": "high"},
        "process_plan": {
            "steps": [
                {"step_number": 1, "name": "粗车"},
                {"step_number": 2, "name": "精车"},
            ]
        },
        "gcode_programs": [
            {"step_number": 1, "program_number": "O0001", "code": "G00 X0", "equipment": "CNC-1"},
            {"step_number": 2, "program_number": "O0002", "code": "G01 X5", "equipment": "CNC-2"},
        ],
        "production_schedule": {"tasks": [{"id": "t1", "machine": "CNC-1"}]},
        "quotation": {"total": 1234.5, "currency": "CNY"},
        "review": {"status": "passed"},
        "quantity": 10,
    }


# ── 验收标准 1：--help 正常显示帮助 ──────────────────────────────
def test_help_shows_usage():
    r = _run(["--help"])
    assert r.returncode == 0, f"--help 应以 0 退出, got {r.returncode}, stderr={r.stderr}"
    out = r.stdout + r.stderr
    assert "--db" in out
    assert "--output" in out
    assert "--min-quality" in out


# ── 验收标准 2：db 不存在 → 打印错误且非零退出，不崩溃 ─────────────
def test_missing_db_nonzero_exit(tmp_path):
    missing = tmp_path / "does_not_exist.db"
    out_file = tmp_path / "out.json"
    r = _run(["--db", str(missing), "--output", str(out_file)])
    assert r.returncode != 0, f"db 不存在应非零退出, got {r.returncode}"
    # 是受控错误信息，而非未捕获的 traceback（不崩溃）
    assert "Traceback" not in r.stderr, f"不应抛未捕获异常: {r.stderr}"
    assert "数据库不存在" in (r.stdout + r.stderr)


# ── 验收标准 3：db 存在但为空 → "导出完成: 0 条样本" 且写出 [] ──────
def test_empty_db_zero_samples(tmp_path):
    db = tmp_path / "empty.db"
    _make_db(db, [])
    out_file = tmp_path / "out.json"
    r = _run(["--db", str(db), "--output", str(out_file)])
    assert r.returncode == 0, f"空db应正常退出, stderr={r.stderr}"
    assert "导出完成: 0 条样本" in r.stdout, f"stdout={r.stdout}"
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data == [], f"空db应写出空数组, got {data!r}"


# ── 验收标准 4/5/6：输出可被 json.loads；每条含4字段；input/output为合法JSON串 ──
def test_full_export_structure(tmp_path):
    db = tmp_path / "full.db"
    _make_db(
        db,
        [
            ("a1", "completed", _high_quality_analysis()),
            # status != completed 应被 SQL 过滤掉
            ("a2", "processing", _high_quality_analysis()),
        ],
    )
    out_file = tmp_path / "out.json"
    r = _run(["--db", str(db), "--output", str(out_file)])
    assert r.returncode == 0, f"stderr={r.stderr}"

    # 验收4：输出文件可被 json.loads 解析
    samples = json.loads(out_file.read_text(encoding="utf-8"))
    assert isinstance(samples, list)
    assert len(samples) > 0, "高质量分析应产出样本"
    # 一条高质量分析覆盖 工艺/2条G代码/排产/报价 = 5 条
    assert len(samples) == 5, f"期望5条样本(工艺1+G代码2+排产1+报价1), got {len(samples)}"

    for s in samples:
        # 验收5：四个字段齐全
        for field in ("system", "instruction", "input", "output"):
            assert field in s, f"样本缺字段 {field}: {s}"
        # 验收6：input/output 都是合法 JSON 字符串（可二次解析）
        assert isinstance(s["input"], str)
        assert isinstance(s["output"], str)
        json.loads(s["input"])
        json.loads(s["output"])


# ── 补充：min-quality high 会跳过低质量分析（low confidence / blocked review）──
def test_low_quality_skipped(tmp_path):
    bad_low = _high_quality_analysis()
    bad_low["part_analysis"]["confidence"] = "low"

    bad_blocked = _high_quality_analysis()
    bad_blocked["review"]["status"] = "blocked"

    db = tmp_path / "mixed.db"
    _make_db(
        db,
        [
            ("good", "completed", _high_quality_analysis()),
            ("low", "completed", bad_low),
            ("blocked", "completed", bad_blocked),
        ],
    )
    out_file = tmp_path / "out.json"
    r = _run(["--db", str(db), "--output", str(out_file)])
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "跳过 2 条低质量分析" in r.stdout, f"stdout={r.stdout}"
    samples = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(samples) == 5, f"仅 good 一条入选, got {len(samples)}"


# ── 补充：--min-quality any 不跳过 ────────────────────────────────
def test_min_quality_any_keeps_all(tmp_path):
    bad_low = _high_quality_analysis()
    bad_low["part_analysis"]["confidence"] = "low"
    db = tmp_path / "any.db"
    _make_db(db, [("low", "completed", bad_low)])
    out_file = tmp_path / "out.json"
    r = _run(["--db", str(db), "--output", str(out_file), "--min-quality", "any"])
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "跳过 0 条" in r.stdout, f"stdout={r.stdout}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
