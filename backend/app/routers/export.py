"""
文档导出API路由
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path

from app.services.export_service import export_service
from app.services.analysis_service import analysis_service

router = APIRouter()

@router.post("/gcode/{analysis_id}")
async def export_gcode(analysis_id: str):
    """导出G代码文件"""
    result = analysis_service.get_analysis(analysis_id)
    if not result:
        raise HTTPException(status_code=404, detail="分析结果不存在")
    
    if not result.get("gcode_programs"):
        raise HTTPException(status_code=400, detail="没有G代码可导出")
    
    filepath = export_service.export_all_gcode(result["gcode_programs"], analysis_id)
    
    return FileResponse(
        filepath,
        media_type="text/plain",
        filename=f"GCODE_{analysis_id}.nc"
    )

@router.post("/schedule/{analysis_id}")
async def export_schedule(analysis_id: str):
    """导出排产计划PDF"""
    result = analysis_service.get_analysis(analysis_id)
    if not result:
        raise HTTPException(status_code=404, detail="分析结果不存在")
    
    if not result.get("production_schedule"):
        raise HTTPException(status_code=400, detail="没有排产计划可导出")
    
    filepath = export_service.export_schedule(result["production_schedule"], analysis_id)
    
    return FileResponse(
        filepath,
        media_type="application/pdf",
        filename=f"排产计划_{analysis_id}.pdf"
    )

@router.post("/quotation/{analysis_id}")
async def export_quotation(analysis_id: str):
    """导出报价单PDF"""
    result = analysis_service.get_analysis(analysis_id)
    if not result:
        raise HTTPException(status_code=404, detail="分析结果不存在")
    
    if not result.get("quotation"):
        raise HTTPException(status_code=400, detail="没有报价单可导出")
    
    filepath = export_service.export_quotation(result["quotation"], analysis_id)
    
    return FileResponse(
        filepath,
        media_type="application/pdf",
        filename=f"报价单_{analysis_id}.pdf"
    )

@router.post("/process-card/{analysis_id}")
async def export_process_card(analysis_id: str):
    """导出工艺卡PDF"""
    result = analysis_service.get_analysis(analysis_id)
    if not result:
        raise HTTPException(status_code=404, detail="分析结果不存在")
    
    if not result.get("process_plan") or not result.get("part_analysis"):
        raise HTTPException(status_code=400, detail="没有工艺数据可导出")
    
    filepath = export_service.export_process_card(
        result["process_plan"],
        result["part_analysis"],
        analysis_id
    )
    
    return FileResponse(
        filepath,
        media_type="application/pdf",
        filename=f"工艺卡_{analysis_id}.pdf"
    )

@router.post("/all/{analysis_id}")
async def export_all(analysis_id: str):
    """导出所有文档"""
    result = analysis_service.get_analysis(analysis_id)
    if not result:
        raise HTTPException(status_code=404, detail="分析结果不存在")
    
    files = export_service.export_full_report(result)
    
    # 返回文件路径列表
    return {
        "analysis_id": analysis_id,
        "files": {
            key: f"/exports/{Path(path).name}" 
            for key, path in files.items()
        }
    }

@router.post("/from-data/gcode")
async def export_gcode_from_data(gcode_programs: list, analysis_id: str = "CUSTOM"):
    """从数据直接导出G代码"""
    filepath = export_service.export_all_gcode(gcode_programs, analysis_id)
    return FileResponse(
        filepath,
        media_type="text/plain",
        filename=f"GCODE_{analysis_id}.nc"
    )

@router.post("/from-data/schedule")
async def export_schedule_from_data(schedule_data: dict, analysis_id: str = "CUSTOM"):
    """从数据直接导出排产计划PDF"""
    filepath = export_service.export_schedule(schedule_data, analysis_id)
    return FileResponse(
        filepath,
        media_type="application/pdf",
        filename=f"排产计划_{analysis_id}.pdf"
    )

@router.post("/from-data/quotation")
async def export_quotation_from_data(quotation_data: dict, analysis_id: str = "CUSTOM"):
    """从数据直接导出报价单PDF"""
    filepath = export_service.export_quotation(quotation_data, analysis_id)
    return FileResponse(
        filepath,
        media_type="application/pdf",
        filename=f"报价单_{analysis_id}.pdf"
    )
