#!/bin/bash

# ============================================
# 后端诊断脚本 - 快速定位问题
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

echo "=========================================="
echo "  后端服务诊断工具"
echo "=========================================="
echo ""

# 1. 检查服务状态
info "1. 检查服务状态..."
if systemctl is-active --quiet mistral-backend; then
    success "服务正在运行"
    systemctl status mistral-backend --no-pager | head -20
else
    error "服务未运行"
    systemctl status mistral-backend --no-pager | head -20
fi
echo ""

# 2. 检查端口监听
info "2. 检查端口监听..."
if ss -tlnp | grep -q ":8000"; then
    success "端口 8000 正在监听"
    ss -tlnp | grep ":8000"
else
    error "端口 8000 未监听"
fi
echo ""

# 3. 测试健康检查
info "3. 测试健康检查..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null)
if [ "$HTTP_CODE" = "200" ]; then
    success "健康检查通过 (HTTP $HTTP_CODE)"
else
    error "健康检查失败 (HTTP $HTTP_CODE)"
fi
echo ""

# 4. 检查日志文件
info "4. 检查最近的错误日志..."
if [ -f /var/log/mistral-factory/backend-error.log ]; then
    echo "--- 最近 30 行错误日志 ---"
    tail -30 /var/log/mistral-factory/backend-error.log
else
    warn "错误日志文件不存在"
fi
echo ""

# 5. 检查运行日志
info "5. 检查最近的运行日志..."
if [ -f /var/log/mistral-factory/backend.log ]; then
    echo "--- 最近 30 行运行日志 ---"
    tail -30 /var/log/mistral-factory/backend.log
else
    warn "运行日志文件不存在"
fi
echo ""

# 6. 检查 Python 环境
info "6. 检查 Python 环境..."
if [ -f /opt/mistral-factory/backend/venv/bin/python ]; then
    success "虚拟环境存在"
    /opt/mistral-factory/backend/venv/bin/python --version
else
    error "虚拟环境不存在"
fi
echo ""

# 7. 检查 .env 文件
info "7. 检查环境配置..."
if [ -f /opt/mistral-factory/backend/.env ]; then
    success ".env 文件存在"
    echo "--- 配置内容（隐藏敏感信息）---"
    grep -v "^#" /opt/mistral-factory/backend/.env | grep -v "^$" | sed 's/=.*/=***/'
else
    error ".env 文件不存在"
fi
echo ""

# 8. 检查关键依赖
info "8. 检查关键依赖..."
/opt/mistral-factory/backend/venv/bin/pip list | grep -E "fastapi|uvicorn|httpx|pydantic" || error "关键依赖缺失"
echo ""

# 9. 测试手动启动
info "9. 建议的修复步骤..."
echo "如果服务无响应，尝试以下步骤："
echo ""
echo "1) 查看完整错误日志："
echo "   tail -f /var/log/mistral-factory/backend-error.log"
echo ""
echo "2) 手动启动后端（查看详细错误）："
echo "   cd /opt/mistral-factory/backend"
echo "   source venv/bin/activate"
echo "   python run.py"
echo ""
echo "3) 检查 API Key 是否有效："
echo "   vi /opt/mistral-factory/backend/.env"
echo ""
echo "4) 重新安装依赖："
echo "   source /opt/mistral-factory/backend/venv/bin/activate"
echo "   pip install -r /opt/mistral-factory/backend/requirements.txt"
echo ""
echo "5) 重启服务："
echo "   systemctl restart mistral-backend"
echo ""

# 10. 提供快速修复选项
echo "=========================================="
echo "快速操作："
echo "  r) 重启后端服务"
echo "  l) 实时查看错误日志"
echo "  t) 手动测试启动"
echo "  q) 退出"
echo "=========================================="
read -p "选择操作 [r/l/t/q]: " choice

case $choice in
    r|R)
        info "重启后端服务..."
        systemctl restart mistral-backend
        sleep 3
        systemctl status mistral-backend --no-pager
        ;;
    l|L)
        info "实时查看错误日志 (Ctrl+C 退出)..."
        tail -f /var/log/mistral-factory/backend-error.log
        ;;
    t|T)
        info "手动测试启动..."
        cd /opt/mistral-factory/backend
        source venv/bin/activate
        python run.py
        ;;
    q|Q)
        echo "退出"
        ;;
    *)
        warn "无效选项"
        ;;
esac
