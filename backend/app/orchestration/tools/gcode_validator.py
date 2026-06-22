"""ISO 6983 G 代码语法校验器。

对 LLM 生成的 G 代码做静态语法检查：无效 G 码 / M 码、行程越界。
纯文本规则，不依赖任何外部服务，供 review_node(M6) 调用。
"""
import re
from typing import List, Dict, Any

# ISO 6983 标准 G 码集（常用）
_VALID_G = {
    0, 1, 2, 3, 4,        # 定位/插补/暂停
    17, 18, 19,           # 平面选择
    20, 21,               # 英制/公制
    28, 29,               # 参考点
    40, 41, 42,           # 刀具半径补偿
    43, 44, 49,           # 刀具长度补偿
    54, 55, 56, 57, 58, 59,  # 工件坐标系
    70, 71, 73, 74, 76, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89,  # 固定循环
    90, 91,               # 绝对/增量
    92,                   # 坐标系设定
    94, 95, 96, 97,       # 进给/转速模式
    98, 99,               # 固定循环返回
}
_VALID_M = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 19, 30, 48, 49, 98, 99}


def validate_gcode(
    code: str,
    max_travel_x: float = 500.0,
    max_travel_z: float = 600.0,
    max_travel_y: float = 500.0,
) -> List[Dict[str, Any]]:
    """校验一段 G 代码，返回问题列表。

    每个问题: {"line": int, "severity": str, "rule": str, "detail": str}
    severity: critical(撞机) > major(无效G码) > minor(可能的厂商扩展M码)
    """
    issues = []
    for line_num, raw_line in enumerate(code.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(';') or line.startswith('(') or line.startswith('%') or line.startswith('N'):
            # N开头的行号前缀，先去掉再检查
            line = re.sub(r'^N\d+\s*', '', line).strip()
        if not line or line.startswith(';') or line.startswith('(') or line.startswith('%'):
            continue

        # G 码范围检查
        for g_str in re.findall(r'[Gg](\d+\.?\d*)', line):
            g_int = int(float(g_str))
            if g_int not in _VALID_G:
                issues.append({
                    "line": line_num, "severity": "major",
                    "rule": "invalid_g_code",
                    "detail": f"G{g_str} 不在 ISO 6983 标准 G码集，请确认机床控制器是否支持",
                })

        # M 码范围检查
        for m_str in re.findall(r'[Mm](\d+)', line):
            m_int = int(m_str)
            if m_int not in _VALID_M:
                issues.append({
                    "line": line_num, "severity": "minor",
                    "rule": "invalid_m_code",
                    "detail": f"M{m_str} 不在标准 M码集，可能是厂商扩展码，请人工确认",
                })

        # 行程越界检查（G0/G1 快速/直线移动）
        if re.search(r'[Gg][01]\b', line):
            for axis, limit in [('X', max_travel_x), ('Y', max_travel_y), ('Z', max_travel_z)]:
                match = re.search(rf'{axis}([-\d.]+)', line, re.IGNORECASE)
                if match:
                    val = abs(float(match.group(1)))
                    if val > limit:
                        issues.append({
                            "line": line_num, "severity": "critical",
                            "rule": "travel_exceeded",
                            "detail": f"{axis}{match.group(1)} 超出机床行程限制 {limit}mm，有撞机风险",
                        })

    return issues
