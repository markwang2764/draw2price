#!/bin/bash

# ============================================
# 自动部署并实时显示日志
# 适用于需要快速更新代码并查看日志的场景
# ============================================

SERVER_IP="8.136.55.76"
SERVER_USER="root"
SERVER_PORT="22"
APP_DIR="/opt/mistral-factory"
LOG_DIR="/var/log/mistral-factory"

# 打印函数
info() { printf "\033[0;34m%s\033[0m\n" "$1"; }
success() { printf "\033[0;32m%s\033[0m\n" "$1"; }
warn() { printf "\033[1;33m%s\033[0m\n" "$1"; }

# 获取脚本和项目目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

info "============================================"
info "  自动部署 + 实时日志"
info "============================================"
echo ""

# 1. 上传后端代码
info "[1/5] 上传后端代码..."
cd "$PROJECT_DIR"
COPYFILE_DISABLE=1 tar --exclude='node_modules' --exclude='venv' --exclude='.git' \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.env' \
    --exclude='chroma_db' --exclude='frontend/dist' -czf /tmp/mistral-factory.tar.gz .

scp -P $SERVER_PORT /tmp/mistral-factory.tar.gz $SERVER_USER@$SERVER_IP:$APP_DIR/ > /dev/null 2>&1
ssh -p $SERVER_PORT $SERVER_USER@$SERVER_IP "cd $APP_DIR && tar -xzf mistral-factory.tar.gz && rm mistral-factory.tar.gz" > /dev/null 2>&1
success "✅ 后端代码上传完成"

# 2. 构建前端
info "[2/5] 本地构建前端..."
cd "$PROJECT_DIR/frontend"
if [ ! -d "node_modules" ]; then
    npm install > /dev/null 2>&1
fi
npm run build > /dev/null 2>&1

if [ ! -d "dist" ]; then
    warn "前端构建失败!"
    exit 1
fi
success "✅ 前端构建完成"

# 3. 上传前端
info "[3/5] 上传前端文件..."
scp -P $SERVER_PORT -r "$PROJECT_DIR/frontend/dist" $SERVER_USER@$SERVER_IP:"$APP_DIR/frontend/" > /dev/null 2>&1
success "✅ 前端上传完成"

# 4. 重启后端
info "[4/5] 重启后端服务..."
ssh -p $SERVER_PORT $SERVER_USER@$SERVER_IP "systemctl restart mistral-backend" > /dev/null 2>&1
sleep 2
success "✅ 后端已重启"

# 5. 重载 Nginx
info "[5/5] 重载 Nginx..."
ssh -p $SERVER_PORT $SERVER_USER@$SERVER_IP "nginx -t && systemctl reload nginx" > /dev/null 2>&1
success "✅ Nginx已重载"

echo ""
success "🎉 部署完成!"
success "访问地址: http://$SERVER_IP:7799"
echo ""

# 6. 开始实时显示日志
info "============================================"
info "  后端实时日志 (Ctrl+C 退出)"
info "============================================"
echo ""

# 实时监控日志 (使用 journalctl)
ssh -p $SERVER_PORT $SERVER_USER@$SERVER_IP "journalctl -u mistral-backend -f --no-pager"
