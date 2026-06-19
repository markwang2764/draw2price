# 智能制造工艺分析系统

基于 Mistral AI 的零部件图纸分析与工艺规划系统。

## 功能特性

- **图纸分析**: 上传零件图纸，自动识别零件特征
- **工艺生成**: 根据零件特征自动生成加工工艺方案
- **G 代码生成**: 为每道工序生成标准数控程序
- **排产计划**: 考虑公司设备和人员，智能排产
- **成本报价**: 自动计算材料、加工、人工成本，生成报价单

## 系统架构

```
MistralAiFactory/
├── backend/                 # 后端服务 (FastAPI)
│   ├── app/
│   │   ├── main.py         # 主入口
│   │   ├── core/           # 核心配置
│   │   ├── models/         # 数据模型
│   │   ├── routers/        # API路由
│   │   └── services/       # 业务服务
│   ├── config/             # 公司资源配置
│   ├── requirements.txt
│   └── run.py
├── frontend/               # 前端应用 (React + Vite)
│   ├── src/
│   └── package.json
└── README.md
```

## 快速开始

### 1. 配置 Mistral AI

复制环境变量文件并配置 API Key:

```bash
cd backend
cp .env.example .env
```

编辑 `.env` 文件，设置你的 Mistral API Key:

```
MISTRAL_API_KEY=your_api_key_here
```

**本地部署 Mistral (可选)**:

如果你想使用本地部署的 Mistral (通过 Ollama)，配置如下:

```bash
# 安装 Ollama
brew install ollama

# 拉取 Mistral 模型
ollama pull mistral

# 修改 .env
MISTRAL_BASE_URL=http://localhost:11434/v1
MISTRAL_MODEL=mistral
```

### 2. 启动后端

```bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 启动服务
python run.py
```

后端服务将在 http://localhost:8000 启动，API 文档: http://localhost:8000/docs

### 3. 启动前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端将在 http://localhost:3000 启动

## 使用说明

### 1. 上传图纸或描述零件

- 拖拽上传零件图纸 (支持 PNG, JPG 等格式)
- 或在文本框中描述零件信息

### 2. 设置生产参数

- 生产数量
- 优先级 (低/正常/紧急)
- 交货日期
- 客户名称

### 3. 开始分析

点击"开始分析"按钮，系统将依次执行:

1. 图纸分析 - 识别零件特征
2. 工艺生成 - 制定加工方案
3. G 代码生成 - 生成数控程序
4. 排产计划 - 安排生产任务
5. 成本报价 - 计算费用

### 4. 下载文档

分析完成后可下载:

- **G 代码** (.nc) - 标准数控程序文件
- **排产计划** (.csv) - 可用 Excel 打开
- **报价单** (.html) - 可打印的标准格式
- **工艺卡** (.html) - 可打印的工艺文档

## 配置公司资源

编辑 `backend/config/company_resources.json` 配置:

- **equipment**: 设备列表 (型号、能力、费率)
- **personnel**: 人员列表 (技能、班次、费率)
- **material_costs**: 材料成本
- **working_hours**: 工作时间

## API 接口

### 工艺分析

- `POST /api/analysis/full` - 完整分析流程
- `POST /api/analysis/part` - 仅分析零件
- `POST /api/analysis/process` - 仅生成工艺
- `POST /api/analysis/gcode` - 仅生成 G 代码
- `POST /api/analysis/schedule` - 仅生成排产

### 文档导出

- `POST /api/export/gcode/{id}` - 导出 G 代码
- `POST /api/export/schedule/{id}` - 导出排产计划
- `POST /api/export/quotation/{id}` - 导出报价单
- `POST /api/export/process-card/{id}` - 导出工艺卡

### 资源管理

- `GET /api/resources/` - 获取公司资源
- `PUT /api/resources/` - 更新资源配置
- `POST /api/resources/equipment` - 添加设备
- `POST /api/resources/personnel` - 添加人员

## 技术栈

**后端**:

- Python 3.9+
- FastAPI
- Mistral AI API
- Pydantic
- Jinja2

**前端**:

- React 18
- Vite
- TailwindCSS
- Axios
- Lucide Icons

## License

MIT
