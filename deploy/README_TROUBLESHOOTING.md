# 后端无响应问题排查指南

## 快速诊断

在服务器上运行诊断脚本：

```bash
cd /opt/mistral-factory/deploy
bash diagnose_backend.sh
```

## 快速修复

运行自动修复脚本：

```bash
cd /opt/mistral-factory/deploy
bash fix_backend.sh
```

## 常见问题及解决方案

### 1. API Key 无效或过期

**症状：** 后端启动但 API 调用失败

**解决方案：**

```bash
# 编辑 .env 文件
vi /opt/mistral-factory/backend/.env

# 更新 API Key
MISTRAL_API_KEY=你的新密钥

# 重启服务
systemctl restart mistral-backend
```

### 2. 依赖安装失败

**症状：** 日志显示 `ModuleNotFoundError` 或 `ImportError`

**解决方案：**

```bash
cd /opt/mistral-factory/backend
source venv/bin/activate

# 重新安装依赖
pip install -r requirements.txt

# 或单独安装缺失的包
pip install fastapi uvicorn httpx pydantic

# 重启服务
systemctl restart mistral-backend
```

### 3. 端口被占用

**症状：** 日志显示 `Address already in use`

**解决方案：**

```bash
# 查找占用端口的进程
lsof -i :8000

# 杀死进程
kill -9 <PID>

# 或使用脚本自动清理
pkill -f "uvicorn app.main:app"

# 重启服务
systemctl restart mistral-backend
```

### 4. Python 版本不兼容

**症状：** 日志显示语法错误或版本相关错误

**解决方案：**

```bash
# 检查 Python 版本（需要 3.9+）
/opt/miniconda3/bin/python --version

# 重建虚拟环境
cd /opt/mistral-factory/backend
rm -rf venv
/opt/miniconda3/bin/python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 重启服务
systemctl restart mistral-backend
```

### 5. 内存不足

**症状：** 服务启动后自动停止，日志显示 `Killed`

**解决方案：**

```bash
# 检查内存使用
free -h

# 临时禁用 OCR 和向量数据库（减少内存占用）
# 编辑 .env 文件，添加：
DISABLE_OCR=true
DISABLE_VECTOR_DB=true

# 重启服务
systemctl restart mistral-backend
```

### 6. 文件权限问题

**症状：** 日志显示 `Permission denied`

**解决方案：**

```bash
# 修复权限
chown -R root:root /opt/mistral-factory
chmod -R 755 /opt/mistral-factory/backend/uploads
chmod -R 755 /opt/mistral-factory/backend/exports

# 重启服务
systemctl restart mistral-backend
```

### 7. Nginx 反向代理问题

**症状：** 前端可以访问但 API 调用失败

**解决方案：**

```bash
# 检查 Nginx 配置
nginx -t

# 查看 Nginx 错误日志
tail -f /var/log/nginx/mistral-factory-error.log

# 确保后端正在运行
curl http://localhost:8000/health

# 重载 Nginx
systemctl reload nginx
```

## 手动测试启动

如果自动修复失败，手动启动查看详细错误：

```bash
cd /opt/mistral-factory/backend
source venv/bin/activate
python run.py
```

观察输出的错误信息，根据错误类型采取相应措施。

## 查看日志

```bash
# 实时查看错误日志
tail -f /var/log/mistral-factory/backend-error.log

# 实时查看运行日志
tail -f /var/log/mistral-factory/backend.log

# 查看 systemd 日志
journalctl -u mistral-backend -f
```

## 检查服务状态

```bash
# 服务状态
systemctl status mistral-backend

# 端口监听
ss -tlnp | grep 8000

# 测试 API
curl http://localhost:8000/health
curl http://localhost:8000/docs
```

## 完全重置

如果以上方法都无效，执行完全重置：

```bash
# 1. 停止服务
systemctl stop mistral-backend

# 2. 清理旧环境
cd /opt/mistral-factory/backend
rm -rf venv __pycache__ app/__pycache__

# 3. 重新创建环境
/opt/miniconda3/bin/python -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. 测试导入
python -c "from app.main import app; print('OK')"

# 5. 重启服务
systemctl restart mistral-backend

# 6. 查看状态
systemctl status mistral-backend
curl http://localhost:8000/health
```

## 联系支持

如果问题仍未解决，请提供以下信息：

1. 错误日志：`/var/log/mistral-factory/backend-error.log`
2. 服务状态：`systemctl status mistral-backend`
3. Python 版本：`/opt/miniconda3/bin/python --version`
4. 依赖列表：`source venv/bin/activate && pip list`
