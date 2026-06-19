"""
数据模型定义
"""
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

class PartFeature(BaseModel):
    """零件特征"""
    name: str
    type: str  # 孔、槽、平面、螺纹等
    dimensions: Dict[str, float]
    tolerance: Optional[str] = None
    surface_finish: Optional[str] = None
    description: str

class Material(BaseModel):
    """材料信息"""
    name: str
    grade: str
    hardness: Optional[str] = None
    density: Optional[float] = None

class PartAnalysis(BaseModel):
    """零件分析结果"""
    part_name: str
    part_number: Optional[str] = None
    material: Material
    overall_dimensions: Dict[str, float]
    features: List[PartFeature]
    complexity_level: str  # 简单、中等、复杂
    estimated_weight: Optional[float] = None
    notes: Optional[str] = None

class ProcessStep(BaseModel):
    """工序步骤"""
    step_number: int
    process_name: str
    process_type: str  # 车削、铣削、钻孔等
    description: str
    equipment_type: str
    cutting_parameters: Optional[Dict[str, Any]] = None
    tools_required: List[str]
    estimated_time_minutes: float
    quality_requirements: Optional[str] = None

class ProcessPlan(BaseModel):
    """工艺方案"""
    part_name: str
    material: str
    blank_type: str  # 毛坯类型
    blank_dimensions: Dict[str, float]
    total_steps: int
    steps: List[ProcessStep]
    total_time_minutes: float
    special_requirements: Optional[str] = None

class PLCCode(BaseModel):
    """PLC代码"""
    process_step: int
    equipment_id: str
    code_type: str  # G代码、M代码等
    code_content: str
    description: str

class GCodeProgram(BaseModel):
    """G代码程序"""
    program_number: str
    part_name: str
    equipment: str
    total_lines: int
    code: str
    setup_notes: str
    tool_list: List[Dict[str, Any]]

class ScheduleTask(BaseModel):
    """排产任务"""
    task_id: str
    process_step: int
    process_name: str
    equipment_id: str
    equipment_name: str
    operator_id: str
    operator_name: str
    start_time: str
    end_time: str
    duration_minutes: float
    status: str = "planned"

class ProductionSchedule(BaseModel):
    """排产计划"""
    part_name: str
    quantity: int
    priority: str
    start_date: str
    due_date: str
    tasks: List[ScheduleTask]
    total_hours: float
    utilization_rate: float

class QuotationItem(BaseModel):
    """报价项"""
    item: str
    description: str
    quantity: float
    unit: str
    unit_price: float
    total_price: float

class Quotation(BaseModel):
    """报价单"""
    quotation_number: str
    date: str
    valid_until: str
    customer: Optional[str] = None
    part_name: str
    quantity: int
    material_cost: float
    processing_cost: float
    equipment_cost: float
    labor_cost: float
    overhead_rate: float = 0.15
    profit_rate: float = 0.20
    items: List[QuotationItem]
    subtotal: float
    overhead: float
    profit: float
    total: float
    notes: Optional[str] = None

class AnalysisRequest(BaseModel):
    """分析请求"""
    quantity: int = 1
    priority: str = "normal"  # urgent, normal, low
    due_date: Optional[str] = None
    customer: Optional[str] = None
    notes: Optional[str] = None

class FullAnalysisResult(BaseModel):
    """完整分析结果"""
    id: str
    created_at: str
    part_analysis: PartAnalysis
    process_plan: ProcessPlan
    gcode_programs: List[GCodeProgram]
    production_schedule: ProductionSchedule
    quotation: Quotation
    status: str = "completed"
