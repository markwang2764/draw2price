#!/bin/bash
# AutoDL 一键部署脚本
# 使用方法: bash deploy_autodl.sh

set -e

echo "=========================================="
echo "  智能制造工艺分析系统 - AutoDL部署脚本"
echo "=========================================="

# 1. 安装Ollama
echo "[1/6] 安装Ollama..."
if ! command -v ollama &> /dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
fi

# 2. 启动Ollama服务
echo "[2/6] 启动Ollama服务..."
pkill ollama || true
nohup ollama serve > /tmp/ollama.log 2>&1 &
sleep 5

# 3. 拉取模型
echo "[3/6] 拉取AI模型（这可能需要几分钟）..."
ollama pull mistral
ollama pull llava

# 4. 安装后端依赖
echo "[4/6] 安装后端依赖..."
cd backend
pip install -r requirements.txt -q

# 5. 启动后端服务
echo "[5/6] 启动后端服务..."
pkill -f "uvicorn app.main:app" || true
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/backend.log 2>&1 &
sleep 3

# 6. 构建并启动前端
echo "[6/6] 构建前端..."
cd ../frontend
npm install --silent
npm run build

# 启动前端服务
pkill -f "python -m http.server 3000" || true
cd dist
nohup python -m http.server 3000 > /tmp/frontend.log 2>&1 &

echo ""
echo "=========================================="
echo "  部署完成！"
echo "=========================================="
echo ""
echo "服务地址："
echo "  前端: http://localhost:3000"
echo "  后端: http://localhost:8000"
echo "  API文档: http://localhost:8000/docs"
echo ""
echo "请在AutoDL控制台开启'自定义服务'暴露端口3000和8000"
echo ""
echo "查看日志："
echo "  Ollama: tail -f /tmp/ollama.log"
echo "  后端:   tail -f /tmp/backend.log"
echo ""
