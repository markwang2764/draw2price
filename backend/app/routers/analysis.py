"""
工艺分析API路由
"""
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import Optional
import json

from app.services.analysis_service import analysis_service
from app.models.schemas import AnalysisRequest

router = APIRouter()

@router.post("/full")
async def full_analysis(
    file: Optional[UploadFile] = File(None),
    description: Optional[str] = Form(None),
    quantity: int = Form(1),
    priority: str = Form("normal"),
    due_date: Optional[str] = Form(None),
    customer: Optional[str] = Form(None)
):
    """
    完整工艺分析
    - 上传图纸文件或提供零件描述
    - 自动分析零件特征
    - 生成工艺方案
    - 生成G代码
    - 生成排产计划
    - 生成报价单
    """
    file_content = None
    file_type = None
    
    if file:
        file_content = await file.read()
        # 获取文件类型
        if file.filename:
            ext = file.filename.lower().split('.')[-1]
            file_type = ext if ext in ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'] else 'png'
    
    if not file_content and not description:
        raise HTTPException(status_code=400, detail="请上传图纸文件或提供零件描述")
    
    result = await analysis_service.full_analysis(
        file_content=file_content,
        file_type=file_type,
        description=description,
        quantity=quantity,
        priority=priority,
        due_date=due_date,
        customer=customer
    )
    
    return result

@router.post("/part")
async def analyze_part(
    file: Optional[UploadFile] = File(None),
    description: Optional[str] = Form(None)
):
    """仅分析零件特征"""
    file_content = None
    file_type = None
    
    if file:
        file_content = await file.read()
        if file.filename:
            ext = file.filename.lower().split('.')[-1]
            file_type = ext if ext in ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'] else 'png'
    
    if not file_content and not description:
        raise HTTPException(status_code=400, detail="请上传图纸文件或提供零件描述")
    
    result = await analysis_service.analyze_part_only(
        file_content=file_content,
        file_type=file_type,
        description=description
    )
    
    return result

@router.post("/process")
async def generate_process(part_analysis: dict):
    """根据零件分析生成工艺方案"""
    result = await analysis_service.generate_process_only(part_analysis)
    return result

@router.post("/gcode")
async def generate_gcode(process_step: dict):
    """根据工序生成G代码"""
    result = await analysis_service.generate_gcode_only(process_step)
    return result

@router.post("/schedule")
async def generate_schedule(
    process_plan: dict,
    quantity: int = 1,
    priority: str = "normal",
    due_date: Optional[str] = None
):
    """生成排产计划"""
    result = await analysis_service.generate_schedule_only(
        process_plan=process_plan,
        quantity=quantity,
        priority=priority,
        due_date=due_date
    )
    return result

@router.get("/{analysis_id}")
async def get_analysis(analysis_id: str):
    """获取分析结果"""
    result = analysis_service.get_analysis(analysis_id)
    if not result:
        raise HTTPException(status_code=404, detail="分析结果不存在")
    return result

@router.get("/")
async def list_analyses():
    """列出所有分析结果"""
    return analysis_service.list_analyses()
