"""
完整分析服务 - 整合所有分析步骤，结果持久化到 SQLite
"""
import json
import sqlite3
import uuid
import base64
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.services.mistral_service import mistral_service
from app.core.config import settings

_DB_PATH = Path(__file__).parent.parent.parent / "analyses.db"


def _init_db():
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                data TEXT NOT NULL
            )
        """)
        conn.commit()


_init_db()


@contextmanager
def _db():
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


class AnalysisService:
    def __init__(self):
        self.company_resources = self._load_company_resources()

    def _load_company_resources(self) -> Dict:
        config_path = Path(settings.company_config_path)
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def reload_resources(self):
        self.company_resources = self._load_company_resources()

    def _save(self, result: Dict):
        with _db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO analyses (id, created_at, status, data) VALUES (?,?,?,?)",
                (result["id"], result["created_at"], result["status"], json.dumps(result, ensure_ascii=False))
            )
            conn.commit()

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
        analysis_id = str(uuid.uuid4())[:8].upper()
        created_at = datetime.now().isoformat()

        result: Dict[str, Any] = {
            "id": analysis_id,
            "created_at": created_at,
            "status": "processing"
        }
        self._save(result)

        try:
            if file_content and file_type:
                image_base64 = base64.b64encode(file_content).decode('utf-8')
                part_analysis = await mistral_service.analyze_drawing(image_base64, file_type)
            elif description:
                part_analysis = await mistral_service.analyze_drawing_from_text(description)
            else:
                raise ValueError("需要提供图纸文件或零件描述")

            result["part_analysis"] = part_analysis

            process_plan = await mistral_service.generate_process_plan(
                part_analysis, self.company_resources
            )
            result["process_plan"] = process_plan

            gcode_programs = []
            for step in process_plan.get("steps", []):
                equipment = self._find_equipment(step.get("equipment_type"))
                if equipment:
                    gcode = await mistral_service.generate_gcode(step, equipment)
                    gcode_programs.append(gcode)
            result["gcode_programs"] = gcode_programs

            schedule = await mistral_service.generate_schedule(
                process_plan, self.company_resources, quantity, priority, due_date
            )
            result["production_schedule"] = schedule

            quotation = await mistral_service.generate_quotation(
                part_analysis, process_plan, schedule, self.company_resources, quantity, customer
            )
            result["quotation"] = quotation

            result["status"] = "completed"
            self._save(result)
            return result

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            self._save(result)
            return result

    def _find_equipment(self, equipment_type: str) -> Optional[Dict]:
        for eq in self.company_resources.get("equipment", []):
            if eq.get("type") == equipment_type and eq.get("status") == "available":
                return eq
        for eq in self.company_resources.get("equipment", []):
            if eq.get("status") == "available":
                return eq
        return None

    def get_analysis(self, analysis_id: str) -> Optional[Dict]:
        with _db() as conn:
            row = conn.execute("SELECT data FROM analyses WHERE id=?", (analysis_id,)).fetchone()
            return json.loads(row["data"]) if row else None

    def list_analyses(self) -> List[Dict]:
        with _db() as conn:
            rows = conn.execute("SELECT data FROM analyses ORDER BY created_at DESC LIMIT 200").fetchall()
            return [json.loads(r["data"]) for r in rows]

    async def analyze_part_only(
        self,
        file_content: Optional[bytes] = None,
        file_type: Optional[str] = None,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        if file_content and file_type:
            image_base64 = base64.b64encode(file_content).decode('utf-8')
            return await mistral_service.analyze_drawing(image_base64, file_type)
        elif description:
            return await mistral_service.analyze_drawing_from_text(description)
        else:
            raise ValueError("需要提供图纸文件或零件描述")

    async def generate_process_only(self, part_analysis: Dict) -> Dict[str, Any]:
        return await mistral_service.generate_process_plan(part_analysis, self.company_resources)

    async def generate_gcode_only(self, process_step: Dict) -> Dict[str, Any]:
        equipment = self._find_equipment(process_step.get("equipment_type"))
        return await mistral_service.generate_gcode(process_step, equipment or {})

    async def generate_schedule_only(
        self,
        process_plan: Dict,
        quantity: int = 1,
        priority: str = "normal",
        due_date: Optional[str] = None
    ) -> Dict[str, Any]:
        return await mistral_service.generate_schedule(
            process_plan, self.company_resources, quantity, priority, due_date
        )


analysis_service = AnalysisService()
