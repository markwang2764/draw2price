"""验收测试：G代码语法校验器 + review_node 规则6。

逐条对应大白话验收标准：
1. 合法代码 → 空列表
2. 非标准G码(G200) → invalid_g_code issue
3. X9999 → travel_exceeded critical
4. 空代码 → 空列表
5. review_node 对含非标准G码的程序产生 issues
"""
from app.orchestration.tools import validate_gcode
from app.orchestration.tools.gcode_validator import validate_gcode as direct_import
from app.orchestration.nodes import review_node


# ── 验收标准 1: 合法代码无问题 ────────────────────────────────────────────────
def test_legal_code_returns_empty():
    issues = validate_gcode("G0 X0 Z0\nT01 M06\nG01 X50 F0.3\nM30")
    assert issues == [], f"合法代码不应有任何问题: {issues}"


# ── 验收标准 2: 非标准 G 码 → invalid_g_code ──────────────────────────────────
def test_invalid_g_code_detected():
    # 说明文档指出 G99 实为有效的固定循环返回，故用 G200 测非法G码
    issues = validate_gcode("G200 X0")
    assert any(i["rule"] == "invalid_g_code" for i in issues), \
        f"G200 应触发 invalid_g_code: {issues}"
    inv = [i for i in issues if i["rule"] == "invalid_g_code"][0]
    assert inv["severity"] == "major"


def test_valid_g99_not_flagged():
    # 反向确认：标准集里的 G99 不应被误报
    issues = validate_gcode("G99 X0")
    assert not any(i["rule"] == "invalid_g_code" for i in issues), \
        f"G99 是合法固定循环返回，不应误报: {issues}"


# ── 验收标准 3: 行程越界 critical ─────────────────────────────────────────────
def test_travel_exceeded_critical():
    issues = validate_gcode("G0 X9999 Z0")
    travel = [i for i in issues if i["rule"] == "travel_exceeded"]
    assert travel, f"X9999 应触发 travel_exceeded: {issues}"
    assert travel[0]["severity"] == "critical", f"行程越界应为 critical: {travel}"


def test_travel_within_limit_no_critical():
    issues = validate_gcode("G0 X0 Z0\nG0 X50 Z-10")
    assert not any(i["severity"] == "critical" for i in issues), \
        f"行程内不应有 critical: {issues}"


# ── 验收标准 4: 空代码不报错 ──────────────────────────────────────────────────
def test_empty_code_returns_empty():
    assert validate_gcode("") == []


def test_comment_only_returns_empty():
    assert validate_gcode("; 仅注释\n(comment)\n%") == []


# ── 验收标准 5: review_node 对非标准G码程序产生 issues ─────────────────────────
def test_review_node_flags_nonstandard_gcode(monkeypatch):
    # 隔离资源依赖，聚焦规则6行为
    import app.orchestration.nodes as nodes_mod
    monkeypatch.setattr(nodes_mod, "_get_resources", lambda: {"equipment": []})

    state = {
        "part_analysis": {"confidence": "high"},
        "process_plan": {"steps": []},
        "gcode_programs": [
            {
                "program_number": "O1234",
                "code": "G200 X0\nG01 X50 F0.3",
                "tool_list": [],
            }
        ],
        "schedule": {"tasks": []},
    }
    updates = review_node(state)
    issues = updates["review"]["issues"]
    rules = {i["rule"] for i in issues}
    assert "invalid_g_code" in rules, f"review_node 应对G200产生 invalid_g_code: {issues}"
    # 消息应带上程序号与行号前缀
    g_issue = [i for i in issues if i["rule"] == "invalid_g_code"][0]
    assert "O1234" in g_issue["message"] and "行" in g_issue["message"]


def test_review_node_skips_validation_for_legal_gcode(monkeypatch):
    import app.orchestration.nodes as nodes_mod
    monkeypatch.setattr(nodes_mod, "_get_resources", lambda: {"equipment": []})

    state = {
        "part_analysis": {"confidence": "high"},
        "process_plan": {"steps": []},
        "gcode_programs": [
            {"program_number": "O1", "code": "G0 X0 Z0\nT01 M06\nM30", "tool_list": []}
        ],
        "schedule": {"tasks": []},
    }
    updates = review_node(state)
    rules = {i["rule"] for i in updates["review"]["issues"]}
    assert "invalid_g_code" not in rules and "travel_exceeded" not in rules


# ── 导出可用性 ────────────────────────────────────────────────────────────────
def test_exported_from_tools_package():
    assert validate_gcode is direct_import
