"""
Mistral AI 服务
支持云端API和本地部署(Ollama)
"""
import json
import httpx
import base64
import io
from typing import Optional, Dict, Any, List
from app.core.config import settings

# OCR初始化（延迟加载）
_ocr_reader = None

def get_ocr_reader():
    """获取OCR读取器（延迟初始化）"""
    global _ocr_reader
    if _ocr_reader is None:
        try:
            import easyocr
            print("[OCR] 正在初始化EasyOCR（首次加载较慢）...")
            _ocr_reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)
            print("[OCR] EasyOCR初始化完成")
        except Exception as e:
            print(f"[OCR] EasyOCR初始化失败: {e}")
            _ocr_reader = False
    return _ocr_reader if _ocr_reader else None

class MistralService:
    def __init__(self):
        self.api_key = settings.mistral_api_key
        self.base_url = settings.mistral_base_url
        self.model = settings.mistral_model
        # 视觉模型：优先使用环境变量配置
        self.vision_model = getattr(settings, 'vision_model', None) or "llava"
        
        # 判断是否使用云端API（OpenAI兼容格式）
        self.is_cloud_api = any(x in self.base_url for x in ["siliconflow", "openai", "api2d", "closeai"])
        print(f"[AI] 模型: {self.model}, 视觉模型: {self.vision_model}")
        print(f"[AI] API地址: {self.base_url}")
    
    def _extract_text_ocr(self, image_base64: str) -> str:
        """使用OCR提取图片中的文字"""
        reader = get_ocr_reader()
        if not reader:
            return ""
        
        try:
            from PIL import Image
            import numpy as np
            
            # 去除可能的data URL前缀
            if ',' in image_base64:
                image_base64 = image_base64.split(',')[1]
            
            # 解码base64图片
            image_data = base64.b64decode(image_base64)
            
            # 检查是否为有效图片
            print(f"[OCR] 图片数据大小: {len(image_data)} bytes, 前20字节: {image_data[:20]}")
            if len(image_data) < 100:
                print(f"[OCR] 图片数据太小")
                return ""
            
            # 检查图片格式
            if image_data[:4] == b'\x89PNG':
                print("[OCR] 检测到PNG格式")
            elif image_data[:2] == b'\xff\xd8':
                print("[OCR] 检测到JPEG格式")
            elif image_data[:4] == b'%PDF':
                print("[OCR] 检测到PDF格式，跳过OCR")
                return ""
            
            image = Image.open(io.BytesIO(image_data))
            
            # 确保图像是RGB模式
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # 转换为numpy数组
            image_np = np.array(image)
            
            # OCR识别
            results = reader.readtext(image_np)
            
            # 提取文字
            texts = [text for (_, text, conf) in results if conf > 0.3]
            extracted = " ".join(texts)
            print(f"[OCR] 提取文字: {extracted[:200]}...")
            return extracted
        except Exception as e:
            print(f"[OCR] 提取失败: {e}")
            import traceback
            traceback.print_exc()
            return ""
        
    async def _call_api(self, messages: List[Dict], temperature: float = 0.3, model: str = None, json_mode: bool = True) -> str:
        """调用API

        json_mode=True 时请求结构化 JSON 输出（OpenAI 兼容协议的 response_format），
        由 API 保证返回合法 JSON，大幅降低落入 _parse_json_response 容错分支的概率。
        如需纯文本输出可显式传 json_mode=False。
        """
        use_model = model or self.model
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        payload = {
            "model": use_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 4000  # 增加以确保完整响应
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                print(f"[API] 调用模型: {use_model}")
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            print(f"[API] HTTP错误: {e.response.status_code}")
            print(f"[API] 响应内容: {e.response.text}")
            raise
        except Exception as e:
            print(f"[API] 调用失败: {e}")
            raise
    
    async def _call_vision_api(self, image_base64: str, file_type: str, prompt: str, json_mode: bool = True) -> str:
        """调用视觉模型API（支持云端和本地）

        json_mode=True 时请求结构化 JSON 输出（云端走 response_format，
        Ollama 走 format=json），降低视觉模型返回非 JSON 文本的概率。
        """
        import base64
        
        # 确保base64没有前缀
        if "," in image_base64:
            image_base64 = image_base64.split(",")[1]
        
        # 清理base64字符串（移除空白字符）
        image_base64 = image_base64.strip().replace("\n", "").replace("\r", "").replace(" ", "")
        
        # 验证base64是否有效
        try:
            decoded = base64.b64decode(image_base64)
            print(f"[Vision API] 图片解码成功，大小: {len(decoded)} 字节")
        except Exception as e:
            print(f"[Vision API] Base64解码失败: {e}")
            raise ValueError(f"无效的图片数据: {e}")

        # 修正图片格式：jpg -> jpeg
        mime_type = file_type.lower()
        if mime_type == "jpg":
            mime_type = "jpeg"
        
        # 确保mime_type是支持的格式
        if mime_type not in ["png", "jpeg", "gif", "webp"]:
            print(f"[Vision API] 不支持的格式 {mime_type}，尝试使用 jpeg")
            mime_type = "jpeg"

        if self.is_cloud_api:
            # OpenAI/硅基流动格式
            payload = {
                "model": self.vision_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/{mime_type};base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 2000
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
        else:
            # Ollama本地格式
            payload = {
                "model": self.vision_model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [image_base64]
                    }
                ],
                "stream": False,
                "options": {"num_predict": 4000}
            }
            if json_mode:
                payload["format"] = "json"  # Ollama 的 JSON 约束输出
            headers = {"Content-Type": "application/json"}

        # 添加重试机制（OpenAI Vision API 有时会随机返回400错误）
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    print(f"[Vision API] 调用模型: {payload['model']} (尝试 {attempt + 1}/{max_retries})")
                    print(f"[Vision API] 请求URL: {self.base_url}/chat/completions")
                    print(f"[Vision API] 图片格式: {mime_type}, 大小: {len(image_base64)} 字符")

                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload
                    )
                    
                    # 检查响应状态
                    if response.status_code == 200:
                        result = response.json()
                        return result["choices"][0]["message"]["content"]
                    
                    # 400错误可能是临时的，重试
                    if response.status_code == 400 and attempt < max_retries - 1:
                        print(f"[Vision API] 收到400错误，等待后重试...")
                        print(f"[Vision API] 响应: {response.text[:200]}")
                        import asyncio
                        await asyncio.sleep(2)  # 等待2秒后重试
                        continue
                    
                    print(f"[Vision API] HTTP错误: {response.status_code}")
                    print(f"[Vision API] 响应内容: {response.text}")
                    response.raise_for_status()
                    
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 400 and attempt < max_retries - 1:
                    print(f"[Vision API] 400错误，重试中...")
                    import asyncio
                    await asyncio.sleep(2)
                    continue
                print(f"[Vision API] HTTP错误: {e.response.status_code}")
                print(f"[Vision API] 响应内容: {e.response.text}")
                raise
            except Exception as e:
                print(f"[Vision API] 调用失败: {e}")
                raise
        
        if last_error:
            raise last_error
    
    async def analyze_drawing(self, image_base64: str, file_type: str) -> Dict[str, Any]:
        """分析图纸，提取零件特征（使用视觉模型）"""
        
        # 暂时禁用OCR以加快速度，Vision模型本身可以识别文字
        ocr_context = ""
        # try:
        #     ocr_text = self._extract_text_ocr(image_base64)
        #     if ocr_text:
        #         ocr_context = f"\n\n【OCR识别到的图纸文字信息】：\n{ocr_text}\n"
        # except Exception as e:
        #     print(f"[OCR] 跳过OCR: {e}")
        
        prompt = f"""你是一位拥有20年经验的高级机械工程师和GD&T专家。请仔细分析这张机械零件图纸，提取所有关键信息。
{ocr_context}
【图纸分析步骤】
第1步：查看标题栏 → 提取零件名称、图号、材料、数量
第2步：查看主视图 → 确定零件基本形状和主要尺寸
第3步：查看其他视图 → 补充细节尺寸和隐藏特征
第4步：查看技术要求 → 识别热处理、表面处理等

【尺寸识别要点】
- Φ符号表示直径（如Φ50表示直径50mm）
- ±表示对称公差（如50±0.1）
- H7/h6等是配合公差（H孔、h轴）
- Ra后的数字是表面粗糙度（单位μm）
- M后的数字是螺纹规格（如M10×1.5）

【常见材料识别】
- 45钢/45#：普通调质钢
- 40Cr：合金调质钢
- Q235/Q345：碳素结构钢
- 6061/7075：铝合金
- SUS304/316：不锈钢
- H62/H68：黄铜

【特征类型说明】
- 孔：通孔（贯穿）、盲孔（有底）、螺纹孔（M开头）、沉头孔、锪平孔
- 轴：外圆面、台阶轴、锥面、圆弧面
- 槽：键槽（平行槽）、退刀槽（环形）、T型槽、燕尾槽
- 平面：端面、台阶面、基准面A/B/C
- 螺纹：外螺纹、内螺纹（注意螺距）
- 其他：倒角C（如C2=2×45°）、圆角R（如R5）

【示例输出】
某轴类零件的正确分析结果：
{{"part_name":"传动轴","part_number":"SZ-2024-001","material":{{"name":"40Cr","grade":"40Cr","hardness":"HRC28-32"}},"overall_dimensions":{{"length":150,"width":50,"height":50}},"features":[{{"name":"主轴外圆","type":"轴","dimensions":{{"diameter":50,"length":80}},"tolerance":"h6","surface_finish":"Ra1.6","description":"主要配合面"}},{{"name":"轴承位","type":"轴","dimensions":{{"diameter":35,"length":25}},"tolerance":"k6","surface_finish":"Ra0.8","description":"轴承安装位"}},{{"name":"键槽","type":"槽","dimensions":{{"width":10,"depth":5,"length":40}},"tolerance":"N9","surface_finish":"Ra3.2","description":"传动键槽"}},{{"name":"中心孔","type":"孔","dimensions":{{"diameter":5,"depth":10}},"tolerance":"-","surface_finish":"-","description":"A2型中心孔"}},{{"name":"端面倒角","type":"倒角","dimensions":{{"size":2}},"tolerance":"-","surface_finish":"-","description":"C2倒角"}}],"complexity_level":"中等","estimated_weight":2.3,"notes":"调质处理HRC28-32"}}

请严格按照以上JSON格式返回分析结果（只返回JSON，不要其他文字）："""

        response = await self._call_vision_api(image_base64, file_type, prompt)
        result = self._parse_json_response(response)

        # 解析失败：不再静默返回一套看似正常的假零件（会污染下游工艺/G代码/报价），
        # 改为返回低置信标记，保留可识别到的原始响应，交由下游/审查 Agent 处理。
        if result.get("parse_error"):
            return {
                "part_name": "识别失败-待人工确认",
                "confidence": "low",
                "error": "图纸识别结果无法解析为结构化数据",
                "raw_response": result.get("raw_response", ""),
                "features": [],
                "complexity_level": "未知",
            }

        # 确保features字段存在
        if "features" not in result or not result["features"]:
            result["features"] = [
                {"name": "主体", "type": "基础形状", "dimensions": {}, "description": "从图纸识别"}
            ]

        return result
    
    async def analyze_drawing_from_text(self, description: str) -> Dict[str, Any]:
        """根据文字描述分析零件（用于测试或无图纸情况）"""
        system_prompt = """你是一位资深的机械工程师。根据用户描述的零件信息，生成详细的零件分析结果。

【重要】请只返回纯JSON格式，不要有任何其他文字。features数组必须包含3-8个特征！

返回格式：
{
  "part_name": "零件名称",
  "part_number": "P001",
  "material": {"name": "45钢", "grade": "45", "hardness": "HRC28-32"},
  "overall_dimensions": {"length": 100, "width": 50, "height": 30},
  "features": [
    {"name": "外圆面", "type": "圆柱面", "dimensions": {"diameter": 50, "length": 100}, "tolerance": "h7", "surface_finish": "Ra3.2", "description": "主轴外圆"},
    {"name": "中心孔", "type": "孔", "dimensions": {"diameter": 20, "depth": 80}, "tolerance": "H7", "surface_finish": "Ra1.6", "description": "中心定位孔"},
    {"name": "键槽", "type": "槽", "dimensions": {"width": 8, "depth": 4, "length": 30}, "tolerance": "N9", "surface_finish": "Ra3.2", "description": "传动键槽"},
    {"name": "螺纹", "type": "螺纹", "dimensions": {"diameter": 20, "pitch": 1.5, "length": 15}, "tolerance": "6g", "surface_finish": "Ra3.2", "description": "端部螺纹"},
    {"name": "倒角", "type": "倒角", "dimensions": {"size": 2}, "tolerance": "-", "surface_finish": "-", "description": "端面倒角C2"}
  ],
  "complexity_level": "中等",
  "estimated_weight": 2.5,
  "notes": "需调质处理"
}

请根据用户描述识别所有加工特征，每个可加工的几何形状都应作为一个特征。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请分析以下零件：{description}"}
        ]

        response = await self._call_api(messages)
        result = self._parse_json_response(response)
        
        # 确保features字段存在
        if "features" not in result or not result["features"]:
            result["features"] = [
                {"name": "主体特征", "type": "基础形状", "dimensions": {}, "description": "根据描述推断"}
            ]
        
        return result
    
    async def generate_process_plan(self, part_analysis: Dict, company_resources: Dict) -> Dict[str, Any]:
        """根据零件特征生成工艺方案"""
        
        # 从知识库检索相关知识
        knowledge_context = ""
        try:
            from app.services.knowledge_service import knowledge_service
            material_name = part_analysis.get("material", {}).get("name", "45钢") if isinstance(part_analysis.get("material"), dict) else "45钢"
            query = f"{material_name} 加工参数 工艺"
            knowledge_context = knowledge_service.get_context_for_query(query, max_chars=1500)
            if knowledge_context:
                knowledge_context = f"\n\n【参考知识】\n{knowledge_context}"
                print(f"[知识库] 检索到相关知识: {len(knowledge_context)} 字符")
        except Exception as e:
            print(f"[知识库] 检索失败: {e}")
        
        system_prompt = """只返回JSON，不要任何解释！

{"part_name": "零件", "material": "45钢", "blank_type": "棒料", "blank_dimensions": {"length": 110, "width": 55, "height": 35}, "total_steps": 3, "steps": [{"step_number": 1, "process_name": "粗车", "process_type": "车削", "description": "粗车外圆", "equipment_type": "CNC_LATHE", "cutting_parameters": {"spindle_speed": 800, "feed_rate": 0.3, "depth_of_cut": 2}, "tools_required": ["外圆车刀"], "estimated_time_minutes": 30, "quality_requirements": "Ra6.3"}, {"step_number": 2, "process_name": "精车", "process_type": "车削", "description": "精车外圆", "equipment_type": "CNC_LATHE", "cutting_parameters": {"spindle_speed": 1200, "feed_rate": 0.1, "depth_of_cut": 0.5}, "tools_required": ["精车刀"], "estimated_time_minutes": 20, "quality_requirements": "Ra1.6"}], "total_time_minutes": 50, "special_requirements": "无"}

根据零件特征和参考知识生成工序，每道工序的equipment_type必须是字符串。只输出JSON！"""

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user", 
                "content": f"""零件分析结果：
{json.dumps(part_analysis, ensure_ascii=False, indent=2)}{knowledge_context}

公司设备资源：
{json.dumps(company_resources.get('equipment', []), ensure_ascii=False, indent=2)}

请制定详细的加工工艺方案。"""
            }
        ]
        
        response = await self._call_api(messages)
        result = self._parse_json_response(response)
        
        # 确保工艺方案数据有效
        steps = result.get("steps", [])
        
        # 确保每个工序有工时
        for step in steps:
            if not step.get("estimated_time_minutes") or step.get("estimated_time_minutes") == 0:
                step["estimated_time_minutes"] = 30  # 默认30分钟
        
        # 计算总工时
        total_time = sum(s.get("estimated_time_minutes", 30) for s in steps)
        if not result.get("total_time_minutes") or result.get("total_time_minutes") == 0:
            result["total_time_minutes"] = total_time if total_time > 0 else 120
            
        if not result.get("total_steps") or result.get("total_steps") == 0:
            result["total_steps"] = len(steps) if steps else 3
        
        return result
    
    async def generate_gcode(self, process_step: Dict, equipment: Dict) -> Dict[str, Any]:
        """根据工序生成G代码"""
        system_prompt = """你是一位CNC编程专家。根据工序信息和设备参数，生成标准的G代码程序。

重要：请只返回纯JSON格式的数据，不要有任何其他文字、解释或markdown标记。

返回JSON格式：
{
  "program_number": "O0001",
  "part_name": "零件名称",
  "equipment": "设备名称",
  "total_lines": 50,
  "code": "完整G代码程序",
  "setup_notes": "装夹说明和注意事项",
  "tool_list": [
    {"tool_number": "T01", "tool_name": "外圆车刀", "offset": "H01"}
  ]
}

G代码要求：
1. 包含完整的程序头和程序尾
2. 包含必要的安全代码(G28, M05等)
3. 注释清晰
4. 切削参数合理"""

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"""工序信息：
{json.dumps(process_step, ensure_ascii=False, indent=2)}

设备信息：
{json.dumps(equipment, ensure_ascii=False, indent=2)}

请生成该工序的G代码程序。"""
            }
        ]
        
        response = await self._call_api(messages)
        return self._parse_json_response(response)
    
    async def generate_schedule(
        self,
        process_plan: Dict,
        company_resources: Dict,
        quantity: int,
        priority: str,
        due_date: Optional[str]
    ) -> Dict[str, Any]:
        """生成排产计划"""
        # 确保quantity是数字
        try:
            quantity = int(quantity) if quantity else 1
        except (ValueError, TypeError):
            quantity = 1
        
        system_prompt = """只返回JSON，不要任何解释！

{"part_name": "零件", "quantity": 10, "priority": "normal", "start_date": "2024-01-15", "due_date": "2024-01-20", "tasks": [{"task_id": "TASK-001", "process_step": 1, "process_name": "工序名", "equipment_id": "EQ-001", "equipment_name": "设备", "operator_id": "OP-001", "operator_name": "操作员", "start_time": "2024-01-15 08:00", "end_time": "2024-01-15 10:00", "duration_minutes": 120, "status": "planned"}], "total_hours": 8, "utilization_rate": 0.8}

根据工艺方案生成任务列表。只输出JSON！"""

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"""工艺方案：
{json.dumps(process_plan, ensure_ascii=False, indent=2)}

公司资源：
设备：{json.dumps(company_resources.get('equipment', []), ensure_ascii=False, indent=2)}
人员：{json.dumps(company_resources.get('personnel', []), ensure_ascii=False, indent=2)}
工作时间：{json.dumps(company_resources.get('working_hours', {}), ensure_ascii=False, indent=2)}

生产要求：
- 数量：{quantity} 件
- 优先级：{priority}
- 交货日期：{due_date or '尽快'}

请制定排产计划。"""
            }
        ]
        
        response = await self._call_api(messages)
        result = self._parse_json_response(response)
        
        # 修正日期为实际当前日期
        from datetime import datetime, timedelta
        today = datetime.now()
        
        # 设置开始日期为今天或明天
        result["start_date"] = today.strftime("%Y-%m-%d")
        
        # 计算预计完成日期
        total_hours = result.get("total_hours", 0) or 2
        work_days = max(1, int(total_hours / 8) + 1)  # 假设每天8小时
        end_date = today + timedelta(days=work_days)
        result["end_date"] = end_date.strftime("%Y-%m-%d")
        
        # 确保排产数据有效，如果工时为0则根据工艺方案估算
        if not result.get("total_hours") or result.get("total_hours") == 0:
            # 从工艺方案计算总工时
            total_minutes = process_plan.get("total_time_minutes", 0)
            if total_minutes == 0:
                steps = process_plan.get("steps", [])
                total_minutes = sum(s.get("estimated_time_minutes", 30) for s in steps)
            if total_minutes == 0:
                total_minutes = 120  # 默认2小时
            result["total_hours"] = round(total_minutes * quantity / 60, 2)
        
        if not result.get("utilization_rate") or result.get("utilization_rate") == 0:
            result["utilization_rate"] = 0.75  # 默认75%利用率
        
        # 确保tasks数组有效
        if not result.get("tasks") or len(result.get("tasks", [])) == 0:
            # 根据工艺方案生成任务列表
            steps = process_plan.get("steps", [])
            equipment_list = company_resources.get("equipment", [])
            personnel_list = company_resources.get("personnel", [])
            
            tasks = []
            current_time = today.replace(hour=8, minute=0, second=0)
            
            for i, step in enumerate(steps):
                duration = step.get("estimated_time_minutes", 30) * quantity
                end_time = current_time + timedelta(minutes=duration)
                
                # 匹配设备
                equip = equipment_list[i % len(equipment_list)] if equipment_list else {"id": f"EQ-{i+1}", "name": "默认设备"}
                # 匹配人员
                person = personnel_list[i % len(personnel_list)] if personnel_list else {"id": f"OP-{i+1}", "name": "操作员"}
                
                tasks.append({
                    "task_id": f"TASK-{i+1:03d}",
                    "process_step": step.get("step_number", i+1),
                    "process_name": step.get("process_name", f"工序{i+1}"),
                    "equipment_id": equip.get("id", f"EQ-{i+1}"),
                    "equipment_name": equip.get("name", "设备"),
                    "operator_id": person.get("id", f"OP-{i+1}"),
                    "operator_name": person.get("name", "操作员"),
                    "start_time": current_time.strftime("%Y-%m-%d %H:%M"),
                    "end_time": end_time.strftime("%Y-%m-%d %H:%M"),
                    "duration_minutes": duration,
                    "status": "planned"
                })
                
                current_time = end_time + timedelta(minutes=15)  # 15分钟间隔
            
            result["tasks"] = tasks
            
        return result
    
    async def generate_quotation(
        self,
        part_analysis: Dict,
        process_plan: Dict,
        schedule: Dict,
        company_resources: Dict,
        quantity: int,
        customer: Optional[str]
    ) -> Dict[str, Any]:
        """生成报价单"""
        # 确保数值类型正确
        try:
            quantity = int(quantity) if quantity else 1
        except (ValueError, TypeError):
            quantity = 1
        
        # 预先计算所有费用 - 使用公司实际配置
        total_hours = float(schedule.get('total_hours', 2) or 2)
        weight = float(part_analysis.get('estimated_weight', 2.5) or 2.5)
        
        # 获取材料价格（从配置文件）
        material_name = part_analysis.get('material', {}).get('name', '45钢') if isinstance(part_analysis.get('material'), dict) else '45钢'
        material_costs = company_resources.get('material_costs', {})
        material_price = float(material_costs.get(material_name, material_costs.get('45钢', 6.0)) or 6.0)
        
        # 计算平均设备费率（从配置文件）
        equipment_list = company_resources.get('equipment', [])
        avg_equipment_rate = 85.0  # 默认值
        if equipment_list:
            rates = [eq.get('hourly_rate', 85) for eq in equipment_list if eq.get('hourly_rate')]
            avg_equipment_rate = sum(rates) / len(rates) if rates else 85.0
        
        # 计算平均人工费率（从配置文件）
        personnel_list = company_resources.get('personnel', [])
        avg_labor_rate = 50.0  # 默认值
        if personnel_list:
            rates = [p.get('hourly_rate', 50) for p in personnel_list if p.get('hourly_rate')]
            avg_labor_rate = sum(rates) / len(rates) if rates else 50.0
        
        # 获取管理费率和利润率（从配置文件）
        overhead_rate = float(company_resources.get('overhead_rate', 0.15) or 0.15)
        profit_rate = float(company_resources.get('profit_rate', 0.18) or 0.18)
        
        # 计算各项费用
        material_cost = round(weight * quantity * material_price, 2)
        equipment_cost = round(total_hours * avg_equipment_rate, 2)  # 设备费（含加工）
        labor_cost = round(total_hours * avg_labor_rate, 2)          # 人工费
        subtotal = material_cost + equipment_cost + labor_cost
        overhead = round(subtotal * overhead_rate, 2)                 # 管理费
        profit = round((subtotal + overhead) * profit_rate, 2)        # 利润
        total = round(subtotal + overhead + profit, 2)
        
        # 直接构建报价单JSON让AI确认或微调
        pre_calc_json = {
            "customer": customer or "待定",
            "part_name": part_analysis.get("part_name", "零件"),
            "quantity": quantity,
            "material_cost": material_cost,
            "equipment_cost": equipment_cost,
            "labor_cost": labor_cost,
            "subtotal": subtotal,
            "overhead": overhead,
            "profit": profit,
            "total": total,
            "notes": f"材料:{material_name}(¥{material_price}/kg), 设备费率:¥{avg_equipment_rate:.0f}/h, 人工费率:¥{avg_labor_rate:.0f}/h, 工时:{total_hours}h"
        }
        
        system_prompt = f"""返回以下JSON（可微调数值）：
{json.dumps(pre_calc_json, ensure_ascii=False)}
只输出JSON！"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "请确认或微调上述报价单，只返回JSON。"}
        ]
        
        response = await self._call_api(messages)
        result = self._parse_json_response(response)
        
        # 如果解析失败，直接使用预计算的JSON
        if result.get("parse_error"):
            result = pre_calc_json.copy()
        
        # 合并预计算值（确保所有字段都有值）
        for key, value in pre_calc_json.items():
            if key not in result or result.get(key) in [None, 0, "", []]:
                result[key] = value
        
        # 确保总价正确
        if not result.get("total") or result.get("total") == 0:
            result["total"] = total
        
        # 确保items列表有内容
        if not result.get("items") or len(result.get("items", [])) == 0:
            result["items"] = [
                {"item": "1", "description": "材料费", "quantity": quantity, "unit": "件", "unit_price": round(result.get("material_cost", 0)/quantity, 2) if quantity > 0 else 0, "total_price": result.get("material_cost", 0)},
                {"item": "2", "description": "设备加工费", "quantity": 1, "unit": "批", "unit_price": result.get("equipment_cost", 0), "total_price": result.get("equipment_cost", 0)},
                {"item": "3", "description": "人工费", "quantity": 1, "unit": "批", "unit_price": result.get("labor_cost", 0), "total_price": result.get("labor_cost", 0)},
            ]
        
        # 修正报价单日期为实际当前日期
        from datetime import datetime, timedelta
        today = datetime.now()
        result["date"] = today.strftime("%Y-%m-%d")
        result["valid_until"] = (today + timedelta(days=30)).strftime("%Y-%m-%d")
        result["quotation_number"] = f"QT-{today.strftime('%Y%m%d')}-{str(hash(str(part_analysis)))[-4:]}"
        
        return result
    
    def _clean_js_expressions(self, response: str) -> str:
        """清理响应中的JavaScript表达式和注释，替换为计算结果"""
        import re
        import logging

        logger = logging.getLogger(__name__)

        # 移除JavaScript风格的单行注释 // comment
        response = re.sub(r'\s*//[^\n]*', '', response)

        # 移除多行注释 /* comment */
        response = re.sub(r'/\*.*?\*/', '', response, flags=re.DOTALL)

        # 移除所有的 .toFixed() 调用，然后处理数学表达式
        def replace_tofixed_expression(match):
            """替换带.toFixed()的表达式"""
            full_expr = match.group(1)
            logger.debug(f"处理表达式: {full_expr}")

            try:
                # 安全评估简单的数学表达式（仅包含数字和基本运算符）
                if re.match(r'^[\d\s+\-*/().]+$', full_expr):
                    result = eval(full_expr)
                    logger.info(f"替换表达式 {match.group(0)} -> {result:.2f}")
                    return str(round(result, 2))
                else:
                    logger.warning(f"表达式包含非法字符: {full_expr}")
                    return "0.00"
            except Exception as e:
                logger.warning(f"无法评估表达式 {match.group(0)}: {str(e)}")
                return "0.00"

        # 匹配更复杂的模式: 任何东西.toFixed(N)
        # 例如: (2.5 * 8.5).toFixed(2) 或 ((40 + 50 + 30) * 1.5).toFixed(2)
        cleaned = re.sub(r'\(([\d\s+\-*/().]+)\)\.toFixed\(\d+\)', replace_tofixed_expression, response)

        # 替换引用未定义变量的表达式为合理的默认值
        cleaned = re.sub(r':\s*[a-zA-Z_]\w*\s*[,}]', lambda m: ': 0.00' + m.group(0)[-1], cleaned)
        cleaned = re.sub(r':\s*\([^)]*[a-zA-Z_]\w*[^)]*\)[^,}]*[,}]', lambda m: ': 0.00' + m.group(0)[-1], cleaned)

        return cleaned
    
    def _fix_invalid_escapes(self, text: str) -> str:
        """修复JSON中的无效转义字符"""
        import re
        
        # 修复无效的转义序列: \x -> \\x (除了有效的 \n \r \t \\ \" \/ \b \f \u)
        # 有效的JSON转义: \\ \" \/ \b \f \n \r \t \uXXXX
        valid_escapes = {'n', 'r', 't', '\\', '"', '/', 'b', 'f', 'u'}
        
        result = []
        i = 0
        while i < len(text):
            if text[i] == '\\' and i + 1 < len(text):
                next_char = text[i + 1]
                if next_char in valid_escapes:
                    # 有效转义，保留
                    result.append(text[i])
                    result.append(next_char)
                    i += 2
                elif next_char == 'x':
                    # \x 十六进制转义 -> 删除或替换
                    result.append('x')
                    i += 2
                else:
                    # 无效转义，双重转义
                    result.append('\\\\')
                    result.append(next_char)
                    i += 2
            else:
                result.append(text[i])
                i += 1
        
        return ''.join(result)
    
    def _fix_truncated_json(self, text: str) -> Optional[str]:
        """尝试修复被截断的JSON"""
        import re
        
        # 提取JSON部分
        text = text.strip()
        if text.startswith('```'):
            text = re.sub(r'^```(?:json)?\s*\n?', '', text)
            text = re.sub(r'\n?```\s*$', '', text)
        
        # 找到JSON开始位置
        start = text.find('{')
        if start == -1:
            return None
        
        text = text[start:]
        
        # 计算括号平衡
        open_braces = text.count('{')
        close_braces = text.count('}')
        open_brackets = text.count('[')
        close_brackets = text.count(']')
        
        # 尝试补全
        fixed = text.rstrip()
        
        # 移除不完整的最后一个键值对
        # 例如 "key": 被截断
        fixed = re.sub(r',?\s*"[^"]*":\s*$', '', fixed)
        fixed = re.sub(r',?\s*"[^"]*$', '', fixed)
        
        # 补全缺失的括号
        missing_brackets = open_brackets - close_brackets
        missing_braces = open_braces - close_braces
        
        fixed = fixed.rstrip(',')  # 移除尾随逗号
        fixed += ']' * missing_brackets
        fixed += '}' * missing_braces
        
        return fixed

    # 切削参数合法范围：超出则标记 warning，不静默归零
    _PARAM_RANGES = {
        'spindle_speed':  (50.0,   8000.0),   # RPM
        'feed_rate':      (0.05,   2.0),       # mm/r
        'depth_of_cut':   (0.05,   15.0),      # mm
        'utilization_rate': (0.0,  1.0),       # 0~1
    }

    def _sanitize_dimensions(self, data: Any) -> Any:
        """递归清理数据：数值字段转 float，安全关键参数校验范围并注入 _warnings"""
        FLOAT_FIELDS = {
            'dimensions', 'overall_dimensions', 'blank_dimensions',
            'total_hours', 'utilization_rate', 'estimated_time_minutes',
            'duration_minutes', 'estimated_weight', 'total_time_minutes',
            'material_cost', 'processing_cost', 'equipment_cost', 'labor_cost',
            'subtotal', 'overhead', 'profit', 'total', 'unit_price', 'total_price',
            'spindle_speed', 'feed_rate', 'depth_of_cut', 'quantity'
        }

        if isinstance(data, dict):
            cleaned = {}
            warnings = []
            for k, v in data.items():
                if k in ['dimensions', 'overall_dimensions', 'blank_dimensions']:
                    if isinstance(v, dict):
                        cleaned[k] = {dk: self._safe_float(dv) for dk, dv in v.items()}
                    else:
                        cleaned[k] = {}
                elif k in FLOAT_FIELDS:
                    fv = self._safe_float(v)
                    if k in self._PARAM_RANGES:
                        lo, hi = self._PARAM_RANGES[k]
                        if fv != 0.0 and not (lo <= fv <= hi):
                            warnings.append(f"{k}={fv} 超出合理范围 [{lo}, {hi}]，请人工复核")
                    cleaned[k] = fv
                elif isinstance(v, dict):
                    cleaned[k] = self._sanitize_dimensions(v)
                elif isinstance(v, list):
                    cleaned[k] = [self._sanitize_dimensions(item) for item in v]
                else:
                    cleaned[k] = v
            if warnings:
                existing = cleaned.get('_warnings', [])
                cleaned['_warnings'] = existing + warnings
            return cleaned
        elif isinstance(data, list):
            return [self._sanitize_dimensions(item) for item in data]
        return data
    
    def _safe_float(self, value: Any) -> float:
        """安全地将值转换为float，无法转换时返回0"""
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # 移除常见的非数字占位符
            if value in ['-', '--', 'N/A', 'n/a', '', '无', '—']:
                return 0.0
            try:
                # 尝试提取数字部分 (如 "50mm" -> 50)
                import re
                match = re.search(r'[-+]?\d*\.?\d+', value)
                if match:
                    return float(match.group())
            except:
                pass
        return 0.0

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析JSON响应"""
        import re
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"开始解析响应，长度: {len(response)}")
        print(f"[DEBUG] 原始响应前800字符:\n{response[:800]}")  # 打印到控制台方便调试

        # 先清理JavaScript表达式
        response = self._clean_js_expressions(response)
        
        # 修复无效的转义字符
        response = self._fix_invalid_escapes(response)
        
        # 修复中文标点符号
        response = response.replace('、', ',').replace('：', ':').replace('；', ';')
        response = response.replace('"', '"').replace('"', '"').replace(''', "'").replace(''', "'")
        
        # 修复错误的反斜杠转义（如 part\_name -> part_name）
        response = response.replace('\\_', '_').replace('\\-', '-')
        
        # 移除JavaScript注释
        import re
        response = re.sub(r'/\*[^*]*\*/', '', response)  # /* comment */
        response = re.sub(r'//[^\n]*', '', response)      # // comment
        
        # 修复尾随逗号 (JSON不允许)
        response = re.sub(r',(\s*[}\]])', r'\1', response)
        
        # 修复无效值
        response = re.sub(r':\s*-"-"', ': 0', response)
        response = re.sub(r':\s*"-"', ': "-"', response)
        
        # 修复缺少逗号的情况 ("value" "key" -> "value", "key")
        response = re.sub(r'"\s+"', '", "', response)
        
        # 修复数字后缺少逗号 (0\n  "key" -> 0,\n  "key")
        response = re.sub(r'(\d)\s*\n(\s*")', r'\1,\n\2', response)
        
        # 修复 } 或 ] 后缺少逗号
        response = re.sub(r'([}\]])\s*\n(\s*")', r'\1,\n\2', response)

        # 尝试直接解析
        try:
            result = json.loads(response)
            logger.info("直接JSON解析成功")
            return self._sanitize_dimensions(result)
        except json.JSONDecodeError:
            logger.warning("直接JSON解析失败，尝试清理...")
            pass

        # 尝试移除markdown代码块标记
        cleaned = response.strip()
        if '```' in cleaned:
            # 移除 ```json 或 ``` 开头和结尾
            cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
            cleaned = re.sub(r'\n?```\s*$', '', cleaned)
            cleaned = cleaned.strip()
            # 再次应用修复
            cleaned = re.sub(r',(\s*[}\]])', r'\1', cleaned)
            try:
                result = json.loads(cleaned)
                logger.info("清理markdown后解析成功")
                return self._sanitize_dimensions(result)
            except json.JSONDecodeError as e:
                logger.warning(f"清理markdown后解析失败: {e}")
                pass

        # 尝试提取JSON部分（查找最大的JSON对象）
        json_matches = list(re.finditer(r'\{[^\{\}]*(?:\{[^\{\}]*\}[^\{\}]*)*\}', response, re.DOTALL))
        logger.info(f"找到 {len(json_matches)} 个JSON对象候选")

        best_match = None
        max_length = 0

        for i, match in enumerate(json_matches):
            json_str = match.group()
            # 对候选也应用清理
            json_str = json_str.replace('\\_', '_').replace('\\-', '-')
            json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
            if len(json_str) > max_length:
                try:
                    parsed = json.loads(json_str)
                    best_match = parsed
                    max_length = len(json_str)
                    logger.info(f"候选{i}: 成功解析，长度 {len(json_str)}")
                except json.JSONDecodeError as e:
                    logger.warning(f"候选{i}: 解析失败 - {str(e)}")
                    continue

        if best_match:
            logger.info("使用最佳匹配的JSON对象")
            return self._sanitize_dimensions(best_match)

        # 尝试修复截断的JSON
        logger.warning("尝试修复截断的JSON...")
        fixed = self._fix_truncated_json(response)
        if fixed:
            try:
                result = json.loads(fixed)
                logger.info("修复截断JSON后解析成功")
                return self._sanitize_dimensions(result)
            except:
                pass
        
        # 返回原始响应包装
        logger.error("所有解析方法失败，返回原始响应")
        return {"raw_response": response[:1000], "parse_error": True}

mistral_service = MistralService()
