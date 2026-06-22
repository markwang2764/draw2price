"""
流式分析API - 展示AI思考过程
"""
import os
import json
import asyncio
import uuid
import io
from datetime import datetime
from typing import Optional, List, Tuple
from fastapi import APIRouter, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse
import base64

from app.services.analysis_service import analysis_service
from app.services.mistral_service import MistralService
from app.core.config import settings
from app.main import limiter

router = APIRouter()

# 并发上限：限制同时运行的昂贵 LLM 编排数，避免单机被打满。
# 与按 IP 的限流互补——限流挡住单一来源刷量，信号量挡住全局并发洪峰。
_ANALYSIS_SEM = asyncio.Semaphore(int(os.environ.get("MAX_CONCURRENT_ANALYSES", "4")))

def convert_pdf_to_images(pdf_content: bytes) -> List[Tuple[bytes, str]]:
    """将PDF转换为图片列表，返回 [(image_bytes, file_type), ...]"""
    import fitz  # PyMuPDF
    
    images = []
    pdf_document = fitz.open(stream=pdf_content, filetype="pdf")
    
    for page_num in range(min(pdf_document.page_count, 5)):  # 最多处理5页
        page = pdf_document[page_num]
        # 放大2倍以获得更清晰的图像
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        images.append((img_bytes, "png"))
    
    pdf_document.close()
    return images

class StreamingAnalysisService:
    def __init__(self):
        self.mistral = MistralService()
        
    async def stream_analysis(
        self,
        file_content: Optional[bytes],
        file_type: Optional[str],
        description: Optional[str],
        quantity: int,
        priority: str,
        due_date: Optional[str],
        customer: Optional[str]
    ):
        """流式分析，返回思考过程"""
        analysis_id = str(uuid.uuid4())[:8].upper()
        
        # 开始
        yield self._format_event("start", {
            "id": analysis_id,
            "message": "🚀 开始分析任务..."
        })
        await asyncio.sleep(0.3)
        
        result = {
            "id": analysis_id,
            "created_at": datetime.now().isoformat(),
            "status": "processing"
        }
        
        try:
            # ========== 步骤1: 图纸/零件分析 ==========
            yield self._format_event("thinking", {
                "step": 1,
                "title": "📐 图纸分析",
                "content": "正在读取输入信息..."
            })
            await asyncio.sleep(0.5)
            
            # 处理PDF文件
            processed_images = []
            if file_content and file_type:
                if file_type.lower() == 'pdf':
                    yield self._format_event("thinking", {
                        "step": 1,
                        "content": "📄 检测到PDF文件，正在转换为图像..."
                    })
                    await asyncio.sleep(0.3)
                    try:
                        processed_images = convert_pdf_to_images(file_content)
                        yield self._format_event("thinking", {
                            "step": 1,
                            "content": f"✅ 成功提取 {len(processed_images)} 页图纸"
                        })
                    except Exception as e:
                        yield self._format_event("thinking", {
                            "step": 1,
                            "content": f"⚠️ PDF转换出错: {str(e)}，尝试其他方式..."
                        })
                else:
                    processed_images = [(file_content, file_type)]
                    yield self._format_event("thinking", {
                        "step": 1,
                        "content": "检测到图纸文件，正在进行图像识别..."
                    })
                
                await asyncio.sleep(0.3)
                yield self._format_event("thinking", {
                    "step": 1,
                    "content": "分析图纸中的几何特征、尺寸标注、公差要求..."
                })
            else:
                yield self._format_event("thinking", {
                    "step": 1,
                    "content": f"正在解析零件描述: \"{description[:50]}{'...' if len(description) > 50 else ''}\""
                })
            
            await asyncio.sleep(0.5)
            yield self._format_event("thinking", {
                "step": 1,
                "content": "🔍 识别材料类型和牌号..."
            })
            await asyncio.sleep(0.3)
            yield self._format_event("thinking", {
                "step": 1,
                "content": "📏 提取整体尺寸信息..."
            })
            await asyncio.sleep(0.3)
            yield self._format_event("thinking", {
                "step": 1,
                "content": "🔩 识别加工特征: 孔、槽、螺纹、倒角..."
            })
            await asyncio.sleep(0.5)
            
            # 实际调用AI分析（使用心跳任务保持连接）
            if processed_images:
                # 分析第一页图纸
                img_bytes, img_type = processed_images[0]
                image_base64 = base64.b64encode(img_bytes).decode('utf-8')
                
                # 创建心跳生成器
                heartbeat_messages = [
                    "🔄 正在调用AI视觉模型分析图纸...",
                    "🧠 AI正在识别图纸中的几何特征...",
                    "📊 正在提取尺寸和公差信息...",
                    "🔍 正在分析材料和加工要求...",
                    "⏳ AI分析中，请稍候...",
                    "🤖 正在生成分析结果..."
                ]
                
                # 使用asyncio.create_task并行执行心跳
                analysis_task = asyncio.create_task(
                    self.mistral.analyze_drawing(image_base64, img_type)
                )
                
                heartbeat_idx = 0
                part_analysis = None
                while not analysis_task.done():
                    yield self._format_event("thinking", {
                        "step": 1,
                        "content": heartbeat_messages[heartbeat_idx % len(heartbeat_messages)]
                    })
                    heartbeat_idx += 1
                    try:
                        await asyncio.wait_for(asyncio.shield(analysis_task), timeout=5.0)
                    except asyncio.TimeoutError:
                        continue  # 继续发送心跳
                    except Exception as e:
                        print(f"[流式分析] 心跳等待异常: {e}")
                        break
                
                # 获取结果，处理异常
                try:
                    if analysis_task.done():
                        part_analysis = analysis_task.result()
                    else:
                        part_analysis = {"error": "分析超时", "part_name": "未知"}
                except Exception as e:
                    print(f"[流式分析] 获取分析结果失败: {e}")
                    part_analysis = {"error": str(e), "part_name": "分析失败"}
            elif description:
                part_analysis = await self.mistral.analyze_drawing_from_text(description)
            else:
                part_analysis = {"error": "无输入数据"}
            
            result["part_analysis"] = part_analysis
            
            yield self._format_event("thinking", {
                "step": 1,
                "content": f"✅ 识别完成！零件名称: {part_analysis.get('part_name', '未知')}"
            })
            await asyncio.sleep(0.2)
            yield self._format_event("thinking", {
                "step": 1,
                "content": f"   材料: {self._format_material(part_analysis.get('material', {}))}"
            })
            await asyncio.sleep(0.2)
            yield self._format_event("thinking", {
                "step": 1,
                "content": f"   特征数量: {len(part_analysis.get('features', []))} 个"
            })
            await asyncio.sleep(0.2)
            yield self._format_event("thinking", {
                "step": 1,
                "content": f"   复杂程度: {part_analysis.get('complexity_level', '中等')}"
            })
            
            yield self._format_event("step_complete", {"step": 1, "data": part_analysis})
            await asyncio.sleep(0.5)
            
            # ========== 步骤2: 工艺方案生成 ==========
            yield self._format_event("thinking", {
                "step": 2,
                "title": "⚙️ 工艺方案生成",
                "content": "根据零件特征制定加工策略..."
            })
            await asyncio.sleep(0.5)
            
            yield self._format_event("thinking", {
                "step": 2,
                "content": "🏭 匹配公司可用设备资源..."
            })
            await asyncio.sleep(0.3)
            yield self._format_event("thinking", {
                "step": 2,
                "content": "📊 分析加工难点和关键工序..."
            })
            await asyncio.sleep(0.3)
            yield self._format_event("thinking", {
                "step": 2,
                "content": "🔄 优化工序顺序，考虑基准统一原则..."
            })
            await asyncio.sleep(0.5)
            yield self._format_event("thinking", {
                "step": 2,
                "content": "⏱️ 估算各工序加工时间..."
            })
            await asyncio.sleep(0.5)
            
            # 实际生成工艺
            process_plan = await self.mistral.generate_process_plan(
                part_analysis, 
                analysis_service.company_resources
            )
            result["process_plan"] = process_plan
            
            yield self._format_event("thinking", {
                "step": 2,
                "content": f"✅ 工艺方案制定完成！共 {process_plan.get('total_steps', 0)} 道工序"
            })
            
            for step in process_plan.get("steps", [])[:5]:
                await asyncio.sleep(0.2)
                yield self._format_event("thinking", {
                    "step": 2,
                    "content": f"   工序{step.get('step_number')}: {step.get('process_name')} ({step.get('equipment_type')})"
                })
            
            if len(process_plan.get("steps", [])) > 5:
                yield self._format_event("thinking", {
                    "step": 2,
                    "content": f"   ... 共 {len(process_plan.get('steps', []))} 道工序"
                })
            
            yield self._format_event("step_complete", {"step": 2, "data": process_plan})
            await asyncio.sleep(0.5)
            
            # ========== 步骤3: G代码生成 ==========
            yield self._format_event("thinking", {
                "step": 3,
                "title": "💻 G代码生成",
                "content": "为数控工序生成加工程序..."
            })
            await asyncio.sleep(0.5)
            
            gcode_programs = []
            # 筛选出需要生成G代码的CNC工序
            cnc_steps = []
            for s in process_plan.get("steps", []):
                equipment_type = s.get("equipment_type")
                if not equipment_type:
                    continue

                # equipment_type可能是字符串或数组
                if isinstance(equipment_type, list):
                    # 如果是数组，检查是否有CNC或MACHINING
                    if any("CNC" in et or "MACHINING" in et for et in equipment_type if isinstance(et, str)):
                        cnc_steps.append(s)
                elif isinstance(equipment_type, str):
                    # 如果是字符串，直接检查
                    if "CNC" in equipment_type or "MACHINING" in equipment_type:
                        cnc_steps.append(s)
            
            for i, step in enumerate(cnc_steps[:3]):
                yield self._format_event("thinking", {
                    "step": 3,
                    "content": f"🔧 生成工序 {step.get('step_number')} 的G代码..."
                })
                await asyncio.sleep(0.3)
                yield self._format_event("thinking", {
                    "step": 3,
                    "content": f"   计算刀具路径和切削参数..."
                })
                await asyncio.sleep(0.3)
                yield self._format_event("thinking", {
                    "step": 3,
                    "content": f"   添加安全代码和换刀指令..."
                })
                await asyncio.sleep(0.3)
                
                equipment = self._find_equipment(step.get("equipment_type"))
                gcode = await self.mistral.generate_gcode(step, equipment or {})
                gcode_programs.append(gcode)
                
                yield self._format_event("thinking", {
                    "step": 3,
                    "content": f"   ✅ 程序 {gcode.get('program_number', f'O000{i+1}')} 生成完成"
                })
                await asyncio.sleep(0.2)
            
            result["gcode_programs"] = gcode_programs
            
            yield self._format_event("thinking", {
                "step": 3,
                "content": f"✅ 共生成 {len(gcode_programs)} 个G代码程序"
            })
            
            yield self._format_event("step_complete", {"step": 3, "data": gcode_programs})
            await asyncio.sleep(0.5)
            
            # ========== 步骤4: 排产计划 ==========
            yield self._format_event("thinking", {
                "step": 4,
                "title": "📅 排产计划",
                "content": "根据产能安排生产任务..."
            })
            await asyncio.sleep(0.5)
            
            yield self._format_event("thinking", {
                "step": 4,
                "content": f"📦 生产数量: {quantity} 件，优先级: {priority}"
            })
            await asyncio.sleep(0.3)
            yield self._format_event("thinking", {
                "step": 4,
                "content": "👥 检查操作人员技能匹配..."
            })
            await asyncio.sleep(0.3)
            yield self._format_event("thinking", {
                "step": 4,
                "content": "🔧 检查设备可用状态..."
            })
            await asyncio.sleep(0.3)
            yield self._format_event("thinking", {
                "step": 4,
                "content": "⏰ 考虑班次安排和交接时间..."
            })
            await asyncio.sleep(0.5)
            
            schedule = await self.mistral.generate_schedule(
                process_plan,
                analysis_service.company_resources,
                quantity,
                priority,
                due_date
            )
            result["production_schedule"] = schedule
            
            yield self._format_event("thinking", {
                "step": 4,
                "content": f"✅ 排产完成！预计 {schedule.get('start_date', '今天')} 开始"
            })
            await asyncio.sleep(0.2)
            yield self._format_event("thinking", {
                "step": 4,
                "content": f"   总工时: {schedule.get('total_hours', 0)} 小时"
            })
            await asyncio.sleep(0.2)
            yield self._format_event("thinking", {
                "step": 4,
                "content": f"   设备利用率: {(schedule.get('utilization_rate', 0) * 100):.1f}%"
            })
            
            yield self._format_event("step_complete", {"step": 4, "data": schedule})
            await asyncio.sleep(0.5)
            
            # ========== 步骤5: 成本报价 ==========
            yield self._format_event("thinking", {
                "step": 5,
                "title": "💰 成本报价",
                "content": "计算生产成本和报价..."
            })
            await asyncio.sleep(0.5)
            
            yield self._format_event("thinking", {
                "step": 5,
                "content": "📦 计算材料成本..."
            })
            await asyncio.sleep(0.3)
            yield self._format_event("thinking", {
                "step": 5,
                "content": "⚙️ 计算设备折旧和能耗..."
            })
            await asyncio.sleep(0.3)
            yield self._format_event("thinking", {
                "step": 5,
                "content": "👷 计算人工成本..."
            })
            await asyncio.sleep(0.3)
            yield self._format_event("thinking", {
                "step": 5,
                "content": "📊 添加管理费用和利润..."
            })
            await asyncio.sleep(0.5)
            
            quotation = await self.mistral.generate_quotation(
                part_analysis,
                process_plan,
                schedule,
                analysis_service.company_resources,
                quantity,
                customer
            )
            result["quotation"] = quotation
            
            yield self._format_event("thinking", {
                "step": 5,
                "content": f"✅ 报价完成！"
            })
            await asyncio.sleep(0.2)
            yield self._format_event("thinking", {
                "step": 5,
                "content": f"   材料费: ¥{quotation.get('material_cost', 0):.2f}"
            })
            await asyncio.sleep(0.2)
            yield self._format_event("thinking", {
                "step": 5,
                "content": f"   加工费: ¥{quotation.get('processing_cost', 0):.2f}"
            })
            await asyncio.sleep(0.2)
            yield self._format_event("thinking", {
                "step": 5,
                "content": f"   💵 总报价: ¥{quotation.get('total', 0):.2f}"
            })
            
            yield self._format_event("step_complete", {"step": 5, "data": quotation})
            await asyncio.sleep(0.3)
            
            # 完成
            result["status"] = "completed"
            analysis_service.analyses_cache[analysis_id] = result
            
            yield self._format_event("complete", {
                "id": analysis_id,
                "message": "🎉 分析完成！",
                "result": result
            })
            
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"\n{'='*60}")
            print(f"[流式分析] 发生错误:")
            print(f"错误类型: {type(e).__name__}")
            print(f"错误信息: {str(e)}")
            print(f"详细堆栈:")
            print(error_detail)
            print(f"{'='*60}\n")

            yield self._format_event("error", {
                "message": f"分析出错: {str(e)}",
                "detail": error_detail
            })
    
    def _format_event(self, event_type: str, data: dict) -> str:
        """格式化SSE事件"""
        return f"data: {json.dumps({'type': event_type, **data}, ensure_ascii=False)}\n\n"
    
    def _format_material(self, material) -> str:
        """格式化材料信息"""
        if isinstance(material, dict):
            return f"{material.get('name', '')} {material.get('grade', '')}"
        return str(material)
    
    def _find_equipment(self, equipment_type: str):
        """查找设备"""
        for eq in analysis_service.company_resources.get("equipment", []):
            if eq.get("type") == equipment_type:
                return eq
        return None

streaming_service = StreamingAnalysisService()

@router.post("/stream")
async def stream_analysis(
    file: Optional[UploadFile] = File(None),
    description: Optional[str] = Form(None),
    quantity: int = Form(1),
    priority: str = Form("normal"),
    due_date: Optional[str] = Form(None),
    customer: Optional[str] = Form(None)
):
    """流式分析接口，返回思考过程"""
    file_content = None
    file_type = None
    
    if file:
        file_content = await file.read()
        if file.filename:
            ext = file.filename.lower().split('.')[-1]
            file_type = ext if ext in ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'] else 'png'
    
    if not file_content and not description:
        async def error_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': '请上传图纸或输入描述'}, ensure_ascii=False)}\n\n"
        return StreamingResponse(error_gen(), media_type="text/event-stream")
    
    return StreamingResponse(
        streaming_service.stream_analysis(
            file_content, file_type, description,
            quantity, priority, due_date, customer
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


# ─── V2: LangGraph 编排路径 ────────────────────────────────────────────────────

@router.post("/stream/v2")
@limiter.limit("10/minute")  # 每 IP 每分钟 10 次，防止任意 IP 烧光 API 预算
async def stream_analysis_v2(
    request: Request,
    file: Optional[UploadFile] = File(None),
    description: Optional[str] = Form(None),
    quantity: int = Form(1),
    priority: str = Form("normal"),
    due_date: Optional[str] = Form(None),
    customer: Optional[str] = Form(None),
):
    """
    LangGraph 编排流式接口（V2）。
    SSE 事件类型与 /stream 完全兼容：start/thinking/step_complete/complete/error。
    新增字段：review_status, exportable（在 complete 事件里）。
    """
    from app.orchestration.graph import build_graph
    from app.orchestration.tools.stream_emitter import StreamEventEmitter

    file_content = None
    file_type = None
    images = []

    if file and file.filename:
        file_content = await file.read()
        ext = file.filename.lower().rsplit(".", 1)[-1]
        if ext == "pdf":
            raw_images = convert_pdf_to_images(file_content)
            images = [(base64.b64encode(b).decode(), ft) for b, ft in raw_images]
        else:
            file_type = ext if ext in {"png", "jpg", "jpeg", "gif", "bmp", "webp"} else "png"
            images = [(base64.b64encode(file_content).decode(), file_type)]

    if not images and not description:
        async def _err():
            yield f"data: {json.dumps({'type': 'error', 'message': '请上传图纸或输入描述'}, ensure_ascii=False)}\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    async def _run():
        emitter = StreamEventEmitter()
        graph = build_graph()
        analysis_id = str(uuid.uuid4())[:8].upper()

        state = {
            "input": {
                "images": images,
                "description": description,
                "quantity": quantity,
                "priority": priority,
                "due_date": due_date,
                "customer": customer,
            },
            "_emitter": emitter,
            "events": [],
            "errors": [],
            "gcode_programs": [],
        }

        yield f"data: {json.dumps({'type': 'start', 'id': analysis_id, 'message': '开始 LangGraph 编排分析...'}, ensure_ascii=False)}\n\n"

        async def _invoke():
            try:
                config = {"configurable": {"thread_id": analysis_id}}
                # 信号量限制全局并发：超过 MAX_CONCURRENT_ANALYSES 的请求在此排队，
                # 而非同时挤进 graph 触发 5+ 次并发 LLM 调用。
                async with _ANALYSIS_SEM:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: graph.invoke(state, config=config)
                    )
                # 汇总结果推 complete 事件
                review = result.get("review") or {}
                await emitter.emit("complete", {
                    "id": analysis_id,
                    "part_analysis": result.get("part_analysis"),
                    "process_plan": result.get("process_plan"),
                    "gcode_programs": result.get("gcode_programs", []),
                    "production_schedule": result.get("schedule"),
                    "quotation": result.get("quotation"),
                    "review": review,
                    "review_status": review.get("status", "approved"),
                    "exportable": review.get("status") != "blocked",
                    "errors": result.get("errors", []),
                })
            except Exception as e:
                await emitter.emit("error", {"message": f"编排异常: {e}"})
            finally:
                await emitter.close()

        asyncio.create_task(_invoke())

        async for chunk in emitter.events():
            yield chunk

    return StreamingResponse(
        _run(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
