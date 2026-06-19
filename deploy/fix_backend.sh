#!/bin/bash

# ============================================
# 后端修复脚本 - 自动修复常见问题
# ============================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

APP_DIR="/opt/mistral-factory"
LOG_DIR="/var/log/mistral-factory"

echo "=========================================="
echo "  后端自动修复工具"
echo "=========================================="
echo ""

# 1. 停止服务
info "1. 停止现有服务..."
systemctl stop mistral-backend 2>/dev/null || true
pkill -f "uvicorn app.main:app" 2>/dev/null || true
sleep 2
success "服务已停止"

# 2. 检查并创建必要目录
info "2. 检查目录结构..."
mkdir -p $APP_DIR/backend/uploads
mkdir -p $APP_DIR/backend/exports
mkdir -p $LOG_DIR
chmod 755 $APP_DIR/backend/uploads
chmod 755 $APP_DIR/backend/exports
success "目录结构正常"

# 3. 检查 .env 文件
info "3. 检查环境配置..."
if [ ! -f "$APP_DIR/backend/.env" ]; then
    error ".env 文件不存在，创建默认配置..."
    cat > $APP_DIR/backend/.env << 'EOF'
# AI 配置
MISTRAL_API_KEY=fk235827-D45Ckk36E63dygtwM2ubQZ8rkr0Slpkr
MISTRAL_BASE_URL=https://oa.api2d.net/v1
MISTRAL_MODEL=gpt-4o
VISION_MODEL=gpt-4o

# 服务器配置
HOST=0.0.0.0
PORT=8000

# 公司配置
COMPANY_CONFIG_PATH=./config/company_resources.json
EOF
    success "已创建默认 .env 文件"
else
    success ".env 文件存在"
fi

# 4. 检查 Python 虚拟环境
info "4. 检查 Python 环境..."
if [ ! -d "$APP_DIR/backend/venv" ]; then
    warn "虚拟环境不存在，重新创建..."
    cd $APP_DIR/backend
    /opt/miniconda3/bin/python -m venv venv
    success "虚拟环境已创建"
fi

# 5. 更新 pip 和安装依赖
info "5. 安装/更新依赖（这可能需要几分钟）..."
source $APP_DIR/backend/venv/bin/activate

# 升级 pip
pip install --upgrade pip -q

# 分批安装依赖，避免超时
info "   安装核心依赖..."
pip install fastapi uvicorn python-multipart pillow httpx pydantic pydantic-settings python-dotenv aiofiles -q

info "   安装文档处理依赖..."
pip install reportlab pymupdf -q

info "   安装 AI 依赖（较慢）..."
pip install openai sentence-transformers -q

# 可选依赖（如果失败不影响核心功能）
info "   安装可选依赖..."
pip install easyocr chromadb -q 2>/dev/null || warn "可选依赖安装失败（不影响核心功能）"

success "依赖安装完成"

# 6. 测试导入
info "6. 测试 Python 导入..."
cd $APP_DIR/backend
python -c "from app.main import app; print('导入成功')" 2>&1
if [ $? -eq 0 ]; then
    success "Python 模块导入正常"
else
    error "Python 模块导入失败，查看上方错误信息"
    exit 1
fi

# 7. 修复 systemd 服务配置
info "7. 更新 systemd 服务配置..."
cat > /etc/systemd/system/mistral-backend.service << 'EOF'
[Unit]
Description=Mistral Factory Backend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/mistral-factory/backend
Environment=PATH=/opt/mistral-factory/backend/venv/bin:/opt/miniconda3/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/mistral-factory/backend/venv/bin/python run.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/mistral-factory/backend.log
StandardError=append:/var/log/mistral-factory/backend-error.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
success "systemd 配置已更新"

# 8. 启动服务
info "8. 启动后端服务..."
systemctl enable mistral-backend
systemctl start mistral-backend
sleep 5

# 9. 检查服务状态
info "9. 检查服务状态..."
if systemctl is-active --quiet mistral-backend; then
    success "服务启动成功"
    systemctl status mistral-backend --no-pager | head -15
else
    error "服务启动失败"
    systemctl status mistral-backend --no-pager
    echo ""
    error "查看错误日志："
    tail -50 /var/log/mistral-factory/backend-error.log
    exit 1
fi

# 10. 测试 API
info "10. 测试 API 响应..."
sleep 3
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health)
if [ "$HTTP_CODE" = "200" ]; then
    success "API 响应正常 (HTTP $HTTP_CODE)"
else
    error "API 响应异常 (HTTP $HTTP_CODE)"
    echo ""
    warn "尝试手动启动查看详细错误："
    echo "   cd /opt/mistral-factory/backend"
    echo "   source venv/bin/activate"
    echo "   python run.py"
    exit 1
fi

echo ""
echo "=========================================="
success "✅ 后端修复完成！"
echo "=========================================="
echo ""
echo "服务信息："
echo "  状态: $(systemctl is-active mistral-backend)"
echo "  端口: 8000"
echo "  API文档: http://localhost:8000/docs"
echo ""
echo "查看日志："
echo "  tail -f /var/log/mistral-factory/backend.log"
echo "  tail -f /var/log/mistral-factory/backend-error.log"
echo ""
