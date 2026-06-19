"""
完整分析服务 - 整合所有分析步骤
"""
import json
import uuid
import base64
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path

from app.services.mistral_service import mistral_service
from app.core.config import settings

class AnalysisService:
    def __init__(self):
        self.company_resources = self._load_company_resources()
        self.analyses_cache: Dict[str, Dict] = {}
    
    def _load_company_resources(self) -> Dict:
        """加载公司资源配置"""
        config_path = Path(settings.company_config_path)
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def reload_resources(self):
        """重新加载公司资源"""
        self.company_resources = self._load_company_resources()
    
    async def full_analysis(
        self,
        file_content: Optional[bytes] = None,
        file_type: Optional[str] = None,
        description: Optional[str] = None,
        quantity: int = 1,
        priority: str = "normal",
        due_date: Optional[str] = None,
        customer: Optional[str] = None
    ) -> Dict[str, Any]:
        """执行完整的工艺分析流程"""
        analysis_id = str(uuid.uuid4())[:8].upper()
        created_at = datetime.now().isoformat()
        
        result = {
            "id": analysis_id,
            "created_at": created_at,
            "status": "processing"
        }
        
        try:
            # 步骤1: 分析图纸/零件特征
            if file_content and file_type:
                image_base64 = base64.b64encode(file_content).decode('utf-8')
                part_analysis = await mistral_service.analyze_drawing(image_base64, file_type)
            elif description:
                part_analysis = await mistral_service.analyze_drawing_from_text(description)
            else:
                raise ValueError("需要提供图纸文件或零件描述")
            
            result["part_analysis"] = part_analysis
            
            # 步骤2: 生成工艺方案
            process_plan = await mistral_service.generate_process_plan(
                part_analysis, 
                self.company_resources
            )
            result["process_plan"] = process_plan
            
            # 步骤3: 为每个工序生成G代码
            gcode_programs = []
            for step in process_plan.get("steps", []):
                # 找到匹配的设备
                equipment = self._find_equipment(step.get("equipment_type"))
                if equipment:
                    gcode = await mistral_service.generate_gcode(step, equipment)
                    gcode_programs.append(gcode)
            
            result["gcode_programs"] = gcode_programs
            
            # 步骤4: 生成排产计划
            schedule = await mistral_service.generate_schedule(
                process_plan,
                self.company_resources,
                quantity,
                priority,
                due_date
            )
            result["production_schedule"] = schedule
            
            # 步骤5: 生成报价单
            quotation = await mistral_service.generate_quotation(
                part_analysis,
                process_plan,
                schedule,
                self.company_resources,
                quantity,
                customer
            )
            result["quotation"] = quotation
            
            result["status"] = "completed"
            
            # 缓存结果
            self.analyses_cache[analysis_id] = result
            
            return result
            
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            return result
    
    def _find_equipment(self, equipment_type: str) -> Optional[Dict]:
        """根据设备类型查找可用设备"""
        for equipment in self.company_resources.get("equipment", []):
            if equipment.get("type") == equipment_type and equipment.get("status") == "available":
                return equipment
        # 如果没找到精确匹配，返回第一个可用设备
        for equipment in self.company_resources.get("equipment", []):
            if equipment.get("status") == "available":
                return equipment
        return None
    
    def get_analysis(self, analysis_id: str) -> Optional[Dict]:
        """获取分析结果"""
        return self.analyses_cache.get(analysis_id)
    
    def list_analyses(self) -> List[Dict]:
        """列出所有分析结果"""
        return list(self.analyses_cache.values())
    
    async def analyze_part_only(
        self,
        file_content: Optional[bytes] = None,
        file_type: Optional[str] = None,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """仅分析零件特征"""
        if file_content and file_type:
            image_base64 = base64.b64encode(file_content).decode('utf-8')
            return await mistral_service.analyze_drawing(image_base64, file_type)
        elif description:
            return await mistral_service.analyze_drawing_from_text(description)
        else:
            raise ValueError("需要提供图纸文件或零件描述")
    
    async def generate_process_only(self, part_analysis: Dict) -> Dict[str, Any]:
        """仅生成工艺方案"""
        return await mistral_service.generate_process_plan(part_analysis, self.company_resources)
    
    async def generate_gcode_only(self, process_step: Dict) -> Dict[str, Any]:
        """仅生成G代码"""
        equipment = self._find_equipment(process_step.get("equipment_type"))
        return await mistral_service.generate_gcode(process_step, equipment or {})
    
    async def generate_schedule_only(
        self,
        process_plan: Dict,
        quantity: int = 1,
        priority: str = "normal",
        due_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """仅生成排产计划"""
        return await mistral_service.generate_schedule(
            process_plan,
            self.company_resources,
            quantity,
            priority,
            due_date
        )

analysis_service = AnalysisService()
