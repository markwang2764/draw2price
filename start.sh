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

source venv/bin/activate
pip install -r requirements.txt -q

# 检查.env文件
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "⚠️  请编辑 backend/.env 文件配置 MISTRAL_API_KEY"
fi

# 先启动前端（后台运行）
cd ../frontend

# 检查node_modules
if [ ! -d "node_modules" ]; then
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

# 前台运行后端，显示实时日志
python run.py
