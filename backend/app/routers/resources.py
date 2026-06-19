"""
公司资源管理API路由
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import json
from pathlib import Path

from app.services.analysis_service import analysis_service
from app.core.config import settings

router = APIRouter()

@router.get("/")
async def get_resources():
    """获取公司资源配置"""
    return analysis_service.company_resources

@router.get("/equipment")
async def get_equipment():
    """获取设备列表"""
    return analysis_service.company_resources.get("equipment", [])

@router.get("/personnel")
async def get_personnel():
    """获取人员列表"""
    return analysis_service.company_resources.get("personnel", [])

@router.get("/materials")
async def get_materials():
    """获取材料成本"""
    return analysis_service.company_resources.get("material_costs", {})

@router.put("/")
async def update_resources(resources: Dict[str, Any]):
    """更新公司资源配置"""
    config_path = Path(settings.company_config_path)
    
    # 保存到文件
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(resources, f, ensure_ascii=False, indent=2)
    
    # 重新加载
    analysis_service.reload_resources()
    
    return {"message": "资源配置已更新", "resources": analysis_service.company_resources}

@router.post("/equipment")
async def add_equipment(equipment: Dict[str, Any]):
    """添加设备"""
    resources = analysis_service.company_resources
    if "equipment" not in resources:
        resources["equipment"] = []
    
    resources["equipment"].append(equipment)
    
    # 保存
    config_path = Path(settings.company_config_path)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(resources, f, ensure_ascii=False, indent=2)
    
    analysis_service.reload_resources()
    
    return {"message": "设备已添加", "equipment": equipment}

@router.post("/personnel")
async def add_personnel(person: Dict[str, Any]):
    """添加人员"""
    resources = analysis_service.company_resources
    if "personnel" not in resources:
        resources["personnel"] = []
    
    resources["personnel"].append(person)
    
    # 保存
    config_path = Path(settings.company_config_path)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(resources, f, ensure_ascii=False, indent=2)
    
    analysis_service.reload_resources()
    
    return {"message": "人员已添加", "personnel": person}

@router.delete("/equipment/{equipment_id}")
async def delete_equipment(equipment_id: str):
    """删除设备"""
    resources = analysis_service.company_resources
    equipment_list = resources.get("equipment", [])
    
    resources["equipment"] = [e for e in equipment_list if e.get("id") != equipment_id]
    
    # 保存
    config_path = Path(settings.company_config_path)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(resources, f, ensure_ascii=False, indent=2)
    
    analysis_service.reload_resources()
    
    return {"message": f"设备 {equipment_id} 已删除"}

@router.delete("/personnel/{person_id}")
async def delete_personnel(person_id: str):
    """删除人员"""
    resources = analysis_service.company_resources
    personnel_list = resources.get("personnel", [])
    
    resources["personnel"] = [p for p in personnel_list if p.get("id") != person_id]
    
    # 保存
    config_path = Path(settings.company_config_path)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(resources, f, ensure_ascii=False, indent=2)
    
    analysis_service.reload_resources()
    
    return {"message": f"人员 {person_id} 已删除"}
