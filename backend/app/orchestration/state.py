"""Shared orchestration state."""
from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict


class AnalysisState(TypedDict, total=False):
    input: Dict[str, Any]
    part_analysis: Optional[Dict[str, Any]]
    process_plan: Optional[Dict[str, Any]]
    gcode_programs: Annotated[List[Dict[str, Any]], operator.add]
    schedule: Optional[Dict[str, Any]]
    quotation: Optional[Dict[str, Any]]
    review: Optional[Dict[str, Any]]
    errors: Annotated[List[Dict[str, Any]], operator.add]
    events: Annotated[List[Dict[str, Any]], operator.add]
    # SSE 桥接器（运行时注入，不序列化到 checkpointer）
    _emitter: Optional[Any]
