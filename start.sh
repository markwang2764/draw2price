#!/bin/bash

# 智能制造工艺分析系统 - 启动脚本

echo "🏭 智能制造工艺分析系统"
echo ""

# 检查是否在正确目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 停止旧服务
echo "🛑 停止旧服务..."
lsof -ti:8000 | xargs kill -9 2>/dev/null && echo "   已停止端口 8000 上的服务" || echo "   端口 8000 无旧服务"
lsof -ti:3000 | xargs kill -9 2>/dev/null && echo "   已停止端口 3000 上的服务" || echo "   端口 3000 无旧服务"
lsof -ti:3001 | xargs kill -9 2>/dev/null && echo "   已停止端口 3001 上的服务" || echo "   端口 3001 无旧服务"
sleep 1
echo ""

# 启动后端
echo "📡 启动后端服务..."
cd backend

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 直接用 venv 的 python，不走 `source venv/bin/activate`：
# 本项目 venv 是从旧路径迁移过来的，activate 脚本里的 VIRTUAL_ENV 仍指向不存在的旧路径，
# source 后会把 PATH 指歪、python 落回系统/anaconda 解释器 → 找不到 reportlab 等依赖而崩。
# venv/bin/python 本身可正常解析并已装好全部依赖，绝对路径调用最稳。
BACKEND_PY="$SCRIPT_DIR/backend/venv/bin/python"

# 依赖自检：缺关键依赖才安装（联网失败也不阻塞启动）。
# 用 `python -m pip` 而非 `venv/bin/pip`：后者的 shebang 同样指向旧路径已失效。
if ! "$BACKEND_PY" -c "import fastapi, uvicorn, reportlab, chromadb" 2>/dev/null; then
    echo "⚠️  检测到缺失依赖，尝试安装 requirements.txt（联网失败不影响已装好的环境）..."
    "$BACKEND_PY" -m pip install -r requirements.txt -q || echo "   ⚠️ 依赖安装未完成（可能离线），将用现有环境继续启动"
else
    echo "   ✓ 后端依赖已就绪"
fi

# 检查.env文件
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "⚠️  请编辑 backend/.env 文件配置 MISTRAL_API_KEY"
fi

# 先启动前端（后台运行）
cd ../frontend

# 检查 node_modules（注意：若为损坏的自指向软链需先删除再装）
if [ ! -d "node_modules" ] || [ -L "node_modules" ]; then
    [ -L "node_modules" ] && { echo "检测到损坏的 node_modules 软链，移除中..."; rm -f node_modules; }
    echo "安装前端依赖..."
    npm install
fi

echo "🖥️  启动前端服务..."
npm run dev &
FRONTEND_PID=$!
echo "前端服务 PID: $FRONTEND_PID"

echo ""
echo "✅ 系统启动完成!"
echo ""
echo "📍 前端地址: http://localhost:3000"
echo "📍 后端API: http://localhost:8000"
echo "📍 API文档: http://localhost:8000/docs"
echo ""
echo "=========================================="
echo "📡 后端实时日志 (按 Ctrl+C 停止所有服务)"
echo "=========================================="
echo ""

cd ../backend

# 设置退出时清理前端进程
trap "kill $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM

# 前台运行后端，显示实时日志。HF_HUB_OFFLINE 让嵌入模型优先用本地缓存、
# 离线时快速回退（默认 bge 模型若未缓存会自动回退到已缓存模型）。
HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}" "$BACKEND_PY" run.py
