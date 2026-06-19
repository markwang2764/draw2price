"""LangGraph orchestration skeleton for M0."""
from __future__ import annotations

from typing import Literal

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


NODE_IDENTIFY = "identify_node"
NODE_PROCESS = "process_node"
NODE_GCODE = "gcode_node"
NODE_SCHEDULE = "schedule_node"
NODE_QUOTATION = "quotation_node"
NODE_REVIEW = "review_node"


def build_graph():
    graph = StateGraph(AnalysisState)
    graph.add_node(NODE_IDENTIFY, identify_node)
    graph.add_node(NODE_PROCESS, process_node)
    graph.add_node(NODE_GCODE, gcode_node)
    graph.add_node(NODE_SCHEDULE, schedule_node)
    graph.add_node(NODE_QUOTATION, quotation_node)
    graph.add_node(NODE_REVIEW, review_node)

    graph.set_entry_point(NODE_IDENTIFY)
    graph.add_edge(NODE_IDENTIFY, NODE_PROCESS)
    graph.add_edge(NODE_PROCESS, NODE_GCODE)
    graph.add_edge(NODE_PROCESS, NODE_SCHEDULE)
    graph.add_edge(NODE_GCODE, NODE_QUOTATION)
    graph.add_edge(NODE_SCHEDULE, NODE_QUOTATION)
    graph.add_edge(NODE_QUOTATION, NODE_REVIEW)
    graph.add_edge(NODE_REVIEW, END)
    return graph.compile()
