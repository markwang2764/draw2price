# CLAUDE.md — MistralAiFactory(机加工 AI 工艺分析平台)

> 给 Claude Code 的项目上下文。新对话先读这份。
> 本项目正在进行**多 Agent 编排改造**,详见 docs/多Agent改造规划.md。

## 这是什么

面向机加工企业的 AI 工艺分析平台:上传零件图纸 → 多模态大模型端到端生成
工艺方案 / G代码 / 排产 / 报价 → 导出 PDF/.nc。慧银科技项目。

现有业务闭环(6步流水线):
```
图纸识别 → RAG检索工艺知识 → 工艺路线 → 逐工序G代码 → 排产 → 报价 → 导出
```

## 技术栈

- 后端:FastAPI + uvicorn + pydantic,目录 `backend/`
- 前端:React 18 + Vite + TailwindCSS,目录 `frontend/`
- AI:多后端可切换(GPT-4o / Qwen / Ollama),OpenAI 兼容协议,httpx 异步
- 图纸识别:EasyOCR + Vision API;PDF 用 PyMuPDF 2× 渲染
- 知识库:ChromaDB 向量库 + sentence-transformers,RAG
- 导出:ReportLab(PDF)

## 启动

```bash
cd backend && python run.py        # 后端 :8000,文档 /docs
cd frontend && npm run dev         # 前端 :3000
# 需配 backend/.env 的 MISTRAL_API_KEY / MISTRAL_BASE_URL
```

## 现有代码结构(改造前)

- `backend/app/services/mistral_service.py`(969行,核心)——6步分析方法都在这:
  analyze_drawing / generate_process_plan / generate_gcode / generate_schedule /
  generate_quotation。AI 调用封装在 _call_api / _call_vision_api。
  JSON 容错解析在 _parse_json_response(多层容错,勿动)。
- `backend/app/routers/analysis_stream.py`——SSE 流式编排入口,串行 await 6 步。
  事件类型:start/thinking/step_complete/complete/error。
- `backend/app/services/export_service.py`(691行)——PDF/报价单/工艺卡导出。
- `backend/app/services/knowledge_service.py`——RAG 知识库。
- `backend/config/company_resources.json`——设备/人员/材料/费率配置。

## 正在做:多 Agent 编排改造

**目标**:串行 service → LangGraph 编排的 agent 流水线 + 加审查 agent 交叉复核。
**总规划**:`docs/多Agent改造规划.md`(架构图、8模块划分、铁律)。

### 改造铁律(别改坏现有可用系统)
1. **不重写业务逻辑**:mistral_service 的 5 个方法体保留,agent 只做"包装+编排"。
2. **保持 API/SSE 兼容**:前端依赖的 5 种 SSE 事件类型必须继续工作。
3. **可回退**:新代码放 `backend/app/orchestration/`,旧 analysis_stream 路径保留到新路径验证通过。
4. **每模块有测试**。
5. **先骨架后填充**:M0 占位流水线先跑通,再逐个换真 agent。

### 模块与进度
| # | 模块 | spec | 状态 |
|---|------|------|------|
| M0 | 编排骨架+工具抽取 | ../../../../mark_dev/agent-orchestra/specs/maf-orchestrator.md | 板子#2 pending,待Cursor |
| M1 | 识别Agent | (待写) | - |
| M2 | 工艺Agent | (待写) | - |
| M3 | G代码Agent(并行) | (待写) | - |
| M4 | 排产Agent | (待写) | - |
| M5 | 报价Agent | (待写) | - |
| M6 | 审查Agent ★灵魂 | (待写) | - |
| M7 | 流式整合 | (待写) | - |

> spec 实际存于 agent-orchestra/specs/(与编排层共享)。M0 跑通后再写 M1/M2。

## 协作模式

Claude Code = 主控(划分模块、写spec、审查测试),Cursor = 执行(按任务开发)。
通过 `/Users/mark/mark_dev/agent-orchestra` 的 MCP 板子流转。
- 主控写 spec 到 agent-orchestra/specs/ → task_add 上板
- Cursor:task_claim → spec_read → 实现 → task_update 标 done
- 主控审查:跑测试 + 对照验收标准 + 验证兼容性,不达标标 blocked
- 编排层说明见 agent-orchestra/CLAUDE.md

## 审查原则

**测试通过 ≠ 达标**。必须对照 spec 验收标准逐条核对,尤其验证:
SSE 事件格式逐字节兼容、旧路径回归不受影响、工具抽取行为不变。
