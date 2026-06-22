"""独立验收测试（测试出题人编写，与实现者分离）。

逐条覆盖大白话验收标准：
1. 合法代码 → 空列表
2. 非标准 G 码(G200) → invalid_g_code
3. X9999 → travel_exceeded critical
4. 空代码 → 空列表
5. review_node 对含非标准 G 码的程序产生 issues
（6. 全部测试通过由 pytest 整体运行判定）
"""
from app.orchestration.tools import validate_gcode as exported_validate
from app.orchestration.tools.gcode_validator import validate_gcode
from app.orchestration.nodes import review_node


# 验收标准 1: 合法代码无问题
def test_ac1_legal_code_empty():
    issues = validate_gcode("G0 X0 Z0\nT01 M06\nG01 X50 F0.3\nM30")
    assert issues == [], f"合法代码应返回空列表，实际: {issues}"


# 验收标准 2: 非标准 G 码（说明文档指明 G99 实为合法固定循环返回，故用 G200）
def test_ac2_invalid_g_code_g200():
    issues = validate_gcode("G200 X0")
    assert any(i["rule"] == "invalid_g_code" for i in issues), \
        f"G200 应触发 invalid_g_code，实际: {issues}"


def test_ac2_g99_is_valid_not_flagged():
    # 反向确认验收标准文字里"G99 实际是有效的"这一点
    issues = validate_gcode("G99 X0")
    assert not any(i["rule"] == "invalid_g_code" for i in issues), \
        f"G99 是合法固定循环返回，不应误报: {issues}"


# 验收标准 3: 行程越界 critical
def test_ac3_travel_exceeded_critical():
    issues = validate_gcode("G0 X9999 Z0")
    travel = [i for i in issues if i["rule"] == "travel_exceeded"]
    assert travel, f"X9999 应触发 travel_exceeded，实际: {issues}"
    assert travel[0]["severity"] == "critical", \
        f"行程越界应为 critical 级别，实际: {travel}"


# 验收标准 4: 空代码不报错
def test_ac4_empty_code_empty():
    assert validate_gcode("") == [], "空代码应返回空列表"


# 验收标准 5: review_node 对非标准 G 码程序产生 issues
def test_ac5_review_node_flags_nonstandard_gcode(monkeypatch):
    import app.orchestration.nodes as nodes_mod
    monkeypatch.setattr(nodes_mod, "_get_resources", lambda: {"equipment": []})

    state = {
        "part_analysis": {"confidence": "high"},
        "process_plan": {"steps": []},
        "gcode_programs": [
            {"program_number": "O5678", "code": "G200 X0\nG01 X50 F0.3", "tool_list": []}
        ],
        "schedule": {"tasks": []},
    }
    updates = review_node(state)
    issues = updates["review"]["issues"]
    rules = {i["rule"] for i in issues}
    assert "invalid_g_code" in rules, \
        f"review_node 应对非标准 G 码产生 invalid_g_code issue，实际: {issues}"
    g_issue = next(i for i in issues if i["rule"] == "invalid_g_code")
    assert "O5678" in g_issue["message"], f"消息应带程序号: {g_issue}"


def test_ac5_review_node_legal_gcode_no_gcode_issues(monkeypatch):
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
    assert "invalid_g_code" not in rules and "travel_exceeded" not in rules, \
        f"合法 G 代码不应产生语法/行程 issue: {updates['review']['issues']}"


# 导出可用性（spec 要求 tools/__init__.py 导出 validate_gcode）
def test_exported_symbol_identity():
    assert exported_validate is validate_gcode
