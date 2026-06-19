# MistralAiFactory 多 Agent 编排改造 · 总规划

> 主控:Claude Code(统筹/划分模块/写spec/审查测试)
> 执行:Cursor(按任务开发各模块)
> 协作:通过 agent-orchestra 的 MCP 板子流转任务与审查
> 状态:规划中 · 生成于改造启动日

## 一、为什么这个项目适合改造(判断依据)

现状摸底结论:
- 6 个分析步骤已是 6 个独立 async 方法(`analyze_drawing` / `generate_process_plan`
  / `generate_gcode` / `generate_schedule` / `generate_quotation` / 导出),边界天然清晰
- 但**无编排框架**,纯 FastAPI 串行 await,步骤靠手写顺序调用串起来
- AI 调用已抽象(`_call_api` / `_call_vision_api`,支持多后端切换),复用性好
- 痛点:无并行、无交叉校验、SSE 与业务紧耦合、错误恢复粗糙

三条"适合多 agent"的黄金特征全中:**可拆分、有依赖、需校验**。

## 二、改造目标架构

```
            ┌──────────── Orchestrator(编排器, LangGraph)────────────┐
            │  维护流程状态 / 调度依赖 / 失败重试 / 统一发 SSE 事件      │
            └───────────────────────┬───────────────────────────────┘
   识别Agent → 工艺Agent →┬→ G代码Agent(可并行多工序) ┐
                          └→ 排产Agent                 ┴→ 报价Agent → 导出
                                    ↓
                           ★ 审查Agent(贯穿关键步骤,交叉复核)
```

**核心升级点(每条都是真实架构变化,经得起面试追问):**

1. **串行 service → Agent 流水线**:6 个方法包装成 6 个 agent 节点,用 LangGraph 编排。
   保留现有 `mistral_service` 的方法体,agent 节点调用它们,**不重写业务逻辑,只换编排层**。
2. **加审查 Agent(最大价值)**:工艺/G代码出结果后,审查 agent 按规则复核——
   刀具可用性、公差合理性、G代码语法。冲突标记人工确认。降低机加工高代价误判。
3. **G代码并行**:多工序的 G 代码生成本可并行(LangGraph 的 fan-out),提速。
4. **流式解耦**:SSE 事件发送从业务逻辑抽出成统一 emitter,由编排器在节点间发事件,
   现有"AI 思考可视化"亮点保留且更干净。

## 三、模块划分(= Cursor 的任务清单)

每个模块对应一份 spec(存 ../agent-orchestra/specs/),按依赖顺序:

| # | 模块 | 依赖 | spec 文件 | 说明 |
|---|------|------|-----------|------|
| M0 | 编排骨架 + 工具抽取 | 无 | maf-orchestrator.md | LangGraph 接入;抽 JSONResponseParser/EquipmentMatcher/StreamEmitter |
| M1 | 识别 Agent | M0 | maf-agent-drawing.md | 包装 analyze_drawing,定义节点输入输出 |
| M2 | 工艺 Agent | M1 | maf-agent-process.md | 包装 generate_process_plan + RAG 检索 |
| M3 | G代码 Agent | M2 | maf-agent-gcode.md | 包装 generate_gcode,支持多工序并行 |
| M4 | 排产 Agent | M2 | maf-agent-schedule.md | 包装 generate_schedule |
| M5 | 报价 Agent | M2,M4 | maf-agent-quotation.md | 包装 generate_quotation |
| M6 | 审查 Agent ★ | M2,M3 | maf-agent-reviewer.md | 规则复核,本次改造的灵魂 |
| M7 | 流式/状态整合 | M0-M6 | maf-streaming.md | SSE emitter 接入编排器,前端事件兼容 |

## 四、改造铁律(避免改坏现有可用系统)

1. **不重写业务逻辑**:mistral_service 的 5 个方法体保留,agent 只做"包装+编排"。
2. **保持 API 兼容**:前端现有的 SSE 事件类型(start/thinking/step_complete/complete/error)
   必须继续工作,不能让前端跟着大改。
3. **可回退**:改造在新模块里做,旧的 analysis_stream 串行路径保留到新路径验证通过。
4. **每模块有测试**:agent 节点的输入输出、编排的依赖顺序、审查 agent 的规则,都要测。
5. **先骨架后填充**:M0 编排骨架先跑通一个"假节点"流水线,再逐个换成真 agent。

## 五、主控(Claude Code)的职责

- 写每个模块的 spec(数据契约 + 节点接口 + 验收标准)
- Cursor 完成后审查:跑测试 + 对照验收标准 + 验证 API 兼容性
- 审查意见写回 MCP 板子,不达标标 blocked
- 维护本规划文档与进度

## 六、RAG 知识库在编排中的定位

现有 `knowledge_service.py`(ChromaDB 向量检索)是工艺生成的关键输入。
在多 agent 架构里,**知识库是"共享工具",不是"流水线节点"**:

- 它不占流水线的一棒,而是被 M2 工艺 Agent、M6 审查 Agent **按需调用**。
- 理由:RAG 是"检索能力",任何 agent 需要查工艺经验/刀具库时都能用,
  做成节点会强行把它塞进固定顺序,失去灵活性。这与 MCP "共享工具" 思想一致。
- 封装:M0 阶段把 knowledge_service 包一层统一检索接口
  `retrieve(query, category, top_k) -> list[doc]`,放进 `orchestration/tools/`,
  供各 agent 调用。检索逻辑本身不重写。
- M2 spec 将明确:工艺 Agent 在生成前先检索相关工艺知识,拼进 prompt。
- M6 审查 Agent 可用同一工具检索"标准工艺规范"来对照复核。

> 影响:M0 的工具抽取(2.4)应顺带把 RAG 检索接口纳入 tools/,
> 已在 M0 spec 范围内的"工具层"思想下,不算扩范围。

## 七、端到端验收基准(改造正确性的硬标准)

改造类项目最大的风险是"改完了,但产出和原来不一样还不自知"。
因此设立**新旧路径对比基准**作为整个改造的总验收:

1. **样例集**:固定 3-5 张代表性图纸(简单件/复杂件/带公差件),存
   `backend/tests/fixtures/sample_drawings/`。
2. **黄金输出**:先用现有串行路径(analysis_stream)跑这批样例,
   把产出(part_analysis / process_plan / gcode / schedule / quotation)存为
   基准快照 `tests/fixtures/golden/`。
3. **对比测试**:新 agent 流水线跑同一批样例,关键字段与黄金快照对比。
   - 确定性字段(零件名、材料、工序数、设备类型、刀具号)必须一致。
   - AI 生成的自然语言描述允许差异(因为本就非确定),只校验结构与关键数值。
4. **判定**:确定性字段全部吻合 = 改造未破坏原有能力。差异需能解释
   (要么是修复了原 bug,要么是审查 agent 主动标记的问题)。
5. **运行**:`cd backend && pytest tests/test_e2e_regression.py`,
   主控在每个 agent 模块合入后都跑一次,守住回归。

> 这条基准在 M0 搭测试地基时**预留**(建 golden/ 目录 + 录黄金快照的脚本),
> 等 M1-M5 的真实 agent 就位后才能真正比对。M0 阶段先把样例和录制脚本备好。

## 八、推进顺序(滚动式)

```
M0 编排骨架+测试地基+工具(含RAG接口)+录黄金快照脚本   ← 当前,板子#2
  ↓ 跑通并审查通过后
M1 识别 → M2 工艺(接RAG)→ M3 G代码/M4 排产(并行)→ M5 报价
  ↓ 主线 agent 就位后
M6 审查 Agent(交叉复核)+ M7 流式整合
  ↓ 全部就位后
端到端回归基准比对(第七节)→ 切换默认路径到新流水线 → 旧路径降级保留
```

每完成一个 M,主控审查 + 更新进度,再写下一个 spec。不一次性铺完。

