"""LangGraph orchestration graph — M1+ wiring target."""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from .nodes import (
    gcode_node,
    identify_node,
    process_node,
    quotation_node,
    review_node,
    schedule_node,
)
from .state import AnalysisState

NODE_IDENTIFY  = "identify_node"
NODE_PROCESS   = "process_node"
NODE_GCODE     = "gcode_node"
NODE_SCHEDULE  = "schedule_node"
NODE_REVIEW    = "review_node"      # 审查在 gcode 之后、quotation 之前
NODE_QUOTATION = "quotation_node"


def _route_after_review(state: AnalysisState) -> str:
    """review blocked → 跳过报价直接结束；否则继续报价"""
    review = state.get("review") or {}
    if review.get("status") == "blocked":
        return END
    return NODE_QUOTATION


def build_graph(checkpointer=None):
    """
    流水线拓扑（修正后）:
        identify → process → gcode ──→ review ─┬→ quotation → END
                           ↘ schedule ──────────┘
                                                └→ END (blocked)

    修正点：
      1. gcode 与 schedule 从 process 并行 fan-out（原 add_edge 不做并行）
      2. review 提前到 gcode/schedule 之后，发现问题可阻断 quotation
      3. 挂 checkpointer 支持断点续跑
    """
    g = StateGraph(AnalysisState)

    g.add_node(NODE_IDENTIFY,  identify_node)
    g.add_node(NODE_PROCESS,   process_node)
    g.add_node(NODE_GCODE,     gcode_node)
    g.add_node(NODE_SCHEDULE,  schedule_node)
    g.add_node(NODE_REVIEW,    review_node)
    g.add_node(NODE_QUOTATION, quotation_node)

    g.set_entry_point(NODE_IDENTIFY)
    g.add_edge(NODE_IDENTIFY, NODE_PROCESS)

    # process → gcode 和 schedule 并行（LangGraph 多出边即并行 fan-out）
    g.add_edge(NODE_PROCESS, NODE_GCODE)
    g.add_edge(NODE_PROCESS, NODE_SCHEDULE)

    # gcode + schedule 都完成后汇入 review（两条入边自动做 join-barrier）
    g.add_edge(NODE_GCODE,    NODE_REVIEW)
    g.add_edge(NODE_SCHEDULE, NODE_REVIEW)

    # review 根据结果决定是否继续报价
    g.add_conditional_edges(NODE_REVIEW, _route_after_review, {NODE_QUOTATION: NODE_QUOTATION, END: END})
    g.add_edge(NODE_QUOTATION, END)

    return g.compile(checkpointer=checkpointer or MemorySaver())
