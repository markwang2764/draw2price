#!/bin/bash

# ============================================
# 智能制造工艺分析系统 - 服务器部署脚本
# 服务器: 8.136.55.76 (CentOS 7)
# 模式: 生产部署 (本地构建前端 + Nginx静态文件)
# ============================================

# 配置
SERVER_IP="8.136.55.76"
SERVER_USER="root"
SERVER_PORT="22"
APP_DIR="/opt/mistral-factory"
LOG_DIR="/var/log/mistral-factory"
MINICONDA_PATH="/opt/miniconda3"

# 打印函数
info() { printf "\033[0;34m%s\033[0m\n" "$1"; }
success() { printf "\033[0;32m%s\033[0m\n" "$1"; }
warn() { printf "\033[1;33m%s\033[0m\n" "$1"; }
error() { printf "\033[0;31m%s\033[0m\n" "$1"; }

# 获取脚本和项目目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

info "============================================"
info "  智能制造工艺分析系统 - 部署脚本"
info "============================================"
echo ""

# 显示菜单
show_menu() {
    success "请选择操作:"
    echo "  1) 完整部署 (首次部署)"
    echo "  2) 更新代码并重启"
    echo "  3) 仅更新前端"
    echo "  4) 仅重启后端"
    echo "  5) 停止服务"
    echo "  6) 查看实时日志 (后端)"
    echo "  7) 查看实时日志 (Nginx)"
    echo "  8) 查看服务状态"
    echo "  9) SSH 登录服务器"
    echo "  0) 退出"
    echo ""
    printf "请输入选项 [0-9]: "
    read choice
}

# SSH 命令封装
ssh_cmd() {
    ssh -p $SERVER_PORT $SERVER_USER@$SERVER_IP "$1"
}

# SCP 上传
scp_upload() {
    scp -P $SERVER_PORT -r "$1" $SERVER_USER@$SERVER_IP:"$2"
}

# 构建前端
build_frontend() {
    info "本地构建前端..."
    cd "$PROJECT_DIR/frontend"
    
    # 检查 node_modules
    if [ ! -d "node_modules" ]; then
        info "安装前端依赖..."
        npm install
    fi
    
    # 构建生产版本
    npm run build
    
    if [ ! -d "dist" ]; then
        error "前端构建失败!"
        return 1
    fi
    success "前端构建完成"
}

# 上传前端静态文件
upload_frontend() {
    info "上传前端静态文件..."
    scp_upload "$PROJECT_DIR/frontend/dist" "$APP_DIR/frontend/"
    success "前端上传完成"
}

# 完整部署
full_deploy() {
    warn "开始完整部署..."
    
    # 1. 创建目录
    info "[1/8] 创建应用目录..."
    ssh_cmd "mkdir -p $APP_DIR $LOG_DIR"
    
    # 2. 上传后端代码
    info "[2/8] 上传后端代码..."
    cd "$PROJECT_DIR"
    COPYFILE_DISABLE=1 tar --exclude='node_modules' --exclude='venv' --exclude='.git' \
        --exclude='__pycache__' --exclude='*.pyc' --exclude='.env' \
        --exclude='chroma_db' --exclude='frontend/dist' -czf /tmp/mistral-factory.tar.gz .
    scp_upload "/tmp/mistral-factory.tar.gz" "$APP_DIR/"
    ssh_cmd "cd $APP_DIR && tar -xzf mistral-factory.tar.gz && rm mistral-factory.tar.gz"
    
    # 3. 安装 Miniconda (Python 3.9)
    info "[3/8] 安装 Python 3.9 (Miniconda)..."
    ssh_cmd "
        if [ ! -d $MINICONDA_PATH ]; then
            curl -sL https://repo.anaconda.com/miniconda/Miniconda3-py39_4.12.0-Linux-x86_64.sh -o /tmp/miniconda.sh
            bash /tmp/miniconda.sh -b -p $MINICONDA_PATH
            rm /tmp/miniconda.sh
        fi
        $MINICONDA_PATH/bin/python --version
    "
    
    # 4. 配置后端虚拟环境
    info "[4/8] 配置后端环境..."
    ssh_cmd "cd $APP_DIR/backend && rm -rf venv && $MINICONDA_PATH/bin/python -m venv venv"
    ssh_cmd "source $APP_DIR/backend/venv/bin/activate && pip install --upgrade pip"
    
    # 分批安装依赖 (避免超时)
    info "安装核心依赖..."
    ssh_cmd "source $APP_DIR/backend/venv/bin/activate && pip install fastapi uvicorn python-multipart pillow openai httpx pydantic pydantic-settings python-dotenv aiofiles reportlab"
    
    info "安装 AI/ML 依赖..."
    ssh_cmd "source $APP_DIR/backend/venv/bin/activate && pip install easyocr chromadb sentence-transformers"
    
    info "安装 PDF 处理依赖..."
    ssh_cmd "source $APP_DIR/backend/venv/bin/activate && pip install --only-binary :all: pymupdf || pip install pymupdf"
    
    # 上传 .env 文件
    if [ -f "$PROJECT_DIR/backend/.env" ]; then
        info "上传 .env 配置文件..."
        scp_upload "$PROJECT_DIR/backend/.env" "$APP_DIR/backend/.env"
    else
        error "警告: 未找到 backend/.env 文件，请手动配置"
    fi
    
    # 5. 构建并上传前端
    info "[5/8] 构建前端..."
    build_frontend
    
    info "[6/8] 上传前端..."
    upload_frontend
    
    # 7. 配置 Nginx (生产模式: 静态文件)
    info "[7/8] 配置 Nginx..."
    ssh_cmd "yum install -y nginx" || true
    setup_nginx_production
    ssh_cmd "nginx -t && systemctl enable nginx && systemctl reload nginx"
    
    # 8. 创建 systemd 服务 (仅后端)
    info "[8/8] 配置系统服务..."
    create_backend_service
    
    success "✅ 部署完成!"
    success "访问地址: http://$SERVER_IP:7799"
}

# 配置 Nginx 生产模式
setup_nginx_production() {
    ssh_cmd 'cat > /etc/nginx/conf.d/mistral-factory.conf << EOF
# 智能制造工艺分析系统 - Nginx 配置 (生产模式)

upstream backend {
    server 127.0.0.1:8000;
}

server {
    listen 7799;
    server_name _;
    
    # 前端静态文件
    root /opt/mistral-factory/frontend/dist;
    index index.html;
    
    location / {
        try_files \$uri \$uri/ /index.html;
    }
    
    # 后端 API
    location /api/ {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding on;
    }
    
    location /docs {
        proxy_pass http://backend/docs;
        proxy_set_header Host \$host;
    }
    
    location /openapi.json {
        proxy_pass http://backend/openapi.json;
    }
    
    client_max_body_size 50M;
    
    access_log /var/log/nginx/mistral-factory-access.log;
    error_log /var/log/nginx/mistral-factory-error.log;
}
EOF'
}

# 创建后端 systemd 服务
create_backend_service() {
    ssh_cmd 'cat > /etc/systemd/system/mistral-backend.service << EOF
[Unit]
Description=Mistral Factory Backend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/mistral-factory/backend
Environment=PATH=/opt/mistral-factory/backend/venv/bin:/opt/miniconda3/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/opt/mistral-factory/backend/venv/bin/python run.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/mistral-factory/backend.log
StandardError=append:/var/log/mistral-factory/backend-error.log

[Install]
WantedBy=multi-user.target
EOF'

    ssh_cmd "systemctl daemon-reload"
    ssh_cmd "systemctl enable mistral-backend"
    ssh_cmd "systemctl restart mistral-backend"
}

# 更新代码并重启
update_and_restart() {
    warn "更新代码..."
    
    # 上传后端代码
    info "上传后端代码..."
    cd "$PROJECT_DIR"
    COPYFILE_DISABLE=1 tar --exclude='node_modules' --exclude='venv' --exclude='.git' \
        --exclude='__pycache__' --exclude='*.pyc' --exclude='.env' \
        --exclude='chroma_db' --exclude='frontend/dist' -czf /tmp/mistral-factory.tar.gz .
    scp_upload "/tmp/mistral-factory.tar.gz" "$APP_DIR/"
    ssh_cmd "cd $APP_DIR && tar -xzf mistral-factory.tar.gz && rm mistral-factory.tar.gz"
    
    # 构建并上传前端
    build_frontend
    upload_frontend
    
    # 重启后端
    restart_backend
    
    # 重载 Nginx
    ssh_cmd "nginx -t && systemctl reload nginx"
    
    success "✅ 更新完成!"
    success "访问地址: http://$SERVER_IP:7799"
    echo ""
    
    # 显示实时日志
    info "正在显示后端实时日志 (Ctrl+C 退出)..."
    sleep 2
    ssh_cmd "journalctl -u mistral-backend -f --no-pager"
}

# 仅更新前端
update_frontend_only() {
    warn "更新前端..."
    build_frontend
    upload_frontend
    ssh_cmd "nginx -t && systemctl reload nginx" || true
    success "✅ 前端更新完成!"
}

# 重启后端
restart_backend() {
    warn "重启后端服务..."
    ssh_cmd "systemctl restart mistral-backend"
    success "✅ 后端已重启"
}

# 停止服务
stop_services() {
    warn "停止服务..."
    ssh_cmd "systemctl stop mistral-backend"
    success "✅ 服务已停止"
}

# 查看后端日志
view_backend_logs() {
    info "后端实时日志 (Ctrl+C 退出)"
    ssh_cmd "journalctl -u mistral-backend -f --no-pager"
}

# 查看 Nginx 日志
view_nginx_logs() {
    info "Nginx 实时日志 (Ctrl+C 退出)"
    ssh_cmd "tail -f /var/log/nginx/mistral-factory-access.log /var/log/nginx/mistral-factory-error.log"
}

# 查看服务状态
view_status() {
    info "服务状态:"
    ssh_cmd "systemctl status mistral-backend --no-pager" || true
    echo ""
    info "端口监听:"
    ssh_cmd "ss -tlnp | grep -E ':(8000|7799)'" || true
    echo ""
    info "测试访问:"
    ssh_cmd "curl -s -o /dev/null -w '前端: %{http_code}\n' http://localhost:7799/" || true
    ssh_cmd "curl -s -o /dev/null -w '后端: %{http_code}\n' http://localhost:8000/docs" || true
}

# SSH 登录
ssh_login() {
    info "连接到服务器..."
    ssh -p $SERVER_PORT $SERVER_USER@$SERVER_IP
}

# 主循环
while true; do
    show_menu
    case $choice in
        1) full_deploy ;;
        2) update_and_restart ;;
        3) update_frontend_only ;;
        4) restart_backend ;;
        5) stop_services ;;
        6) view_backend_logs ;;
        7) view_nginx_logs ;;
        8) view_status ;;
        9) ssh_login ;;
        0) echo "退出"; exit 0 ;;
        *) error "无效选项" ;;
    esac
    echo ""
    printf "按回车继续..."
    read _
    clear
done
