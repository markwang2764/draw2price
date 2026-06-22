"""
独立测试出题人：export_sft_data.py 验收测试（与实现/既有测试分离）。
逐条覆盖大白话验收标准 1~6。通过子进程运行脚本真实 CLI 行为，不改实现。
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export_sft_data.py"


def _make_db(db_path: Path, records, create_table=True):
    conn = sqlite3.connect(db_path)
    if create_table:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS analyses (
                   id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                   status TEXT NOT NULL, data TEXT NOT NULL)"""
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
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )


def _good():
    return {
        "part_analysis": {"material": "45钢", "confidence": "high"},
        "process_plan": {"steps": [
            {"step_number": 1, "name": "粗车"},
            {"step_number": 2, "name": "精车"},
        ]},
        "gcode_programs": [
            {"step_number": 1, "program_number": "O0001", "code": "G00 X0", "equipment": "CNC-1"},
            {"step_number": 2, "program_number": "O0002", "code": "G01 X5", "equipment": "CNC-2"},
        ],
        "production_schedule": {"tasks": [{"id": "t1"}]},
        "quotation": {"total": 1234.5},
        "review": {"status": "passed"},
        "quantity": 10,
    }


# 验收1: --help
def test_help():
    r = _run(["--help"])
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "--db" in out and "--output" in out and "--min-quality" in out


# 验收2: db 不存在 → 非零退出 + 错误信息 + 不崩溃
def test_missing_db(tmp_path):
    r = _run(["--db", str(tmp_path / "nope.db"), "--output", str(tmp_path / "o.json")])
    assert r.returncode != 0
    assert "Traceback" not in r.stderr, r.stderr
    assert "数据库不存在" in (r.stdout + r.stderr)


# 验收3a: db 存在(有表)但无记录 → 0 条样本 + []
def test_empty_db_with_table(tmp_path):
    db = tmp_path / "e.db"
    _make_db(db, [])
    out = tmp_path / "o.json"
    r = _run(["--db", str(db), "--output", str(out)])
    assert r.returncode == 0, r.stderr
    assert "导出完成: 0 条样本" in r.stdout, r.stdout
    assert json.loads(out.read_text(encoding="utf-8")) == []


# 验收3b: db 文件存在但完全空(无表) → 不崩溃, 0 条 + []
def test_empty_db_no_table(tmp_path):
    db = tmp_path / "blank.db"
    sqlite3.connect(db).close()  # 仅创建空 db 文件
    out = tmp_path / "o.json"
    r = _run(["--db", str(db), "--output", str(out)])
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "Traceback" not in r.stderr, r.stderr
    assert "导出完成: 0 条样本" in r.stdout, r.stdout
    assert json.loads(out.read_text(encoding="utf-8")) == []


# 验收4/5/6: 输出可解析 + 四字段 + input/output 是合法JSON串
def test_structure(tmp_path):
    db = tmp_path / "f.db"
    _make_db(db, [
        ("a1", "completed", _good()),
        ("a2", "processing", _good()),  # 非 completed 被过滤
    ])
    out = tmp_path / "o.json"
    r = _run(["--db", str(db), "--output", str(out)])
    assert r.returncode == 0, r.stderr
    samples = json.loads(out.read_text(encoding="utf-8"))  # 验收4
    assert isinstance(samples, list) and len(samples) == 5, len(samples)
    for s in samples:
        for f in ("system", "instruction", "input", "output"):  # 验收5
            assert f in s, s
        assert isinstance(s["input"], str) and isinstance(s["output"], str)
        json.loads(s["input"])   # 验收6
        json.loads(s["output"])  # 验收6


# 补充: high 跳过低质量
def test_high_skips_low(tmp_path):
    low = _good(); low["part_analysis"]["confidence"] = "low"
    blk = _good(); blk["review"]["status"] = "blocked"
    db = tmp_path / "m.db"
    _make_db(db, [("g", "completed", _good()), ("l", "completed", low), ("b", "completed", blk)])
    out = tmp_path / "o.json"
    r = _run(["--db", str(db), "--output", str(out)])
    assert r.returncode == 0, r.stderr
    assert "跳过 2 条低质量分析" in r.stdout, r.stdout
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 5


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
