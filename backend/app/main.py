"""
MistralAI 制造工艺分析系统 - 主入口
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.middleware.auth import APIKeyMiddleware

app = FastAPI(
    title="智能制造工艺分析系统",
    description="基于Mistral AI的零部件图纸分析、工艺生成、排产计划系统",
    version="1.0.0"
)

# 限流器：按客户端 IP 限流。挂到 app.state 供 slowapi 中间件/路由装饰器使用。
# 路由模块通过 `from app.main import limiter` 取用，故 limiter 必须在 include_router 之前定义。
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS：明确列出允许来源，不用通配符
_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

# API Key 认证（设置 API_KEY 环境变量后生效，不设则跳过）
app.add_middleware(APIKeyMiddleware)

# 注册路由（放在 limiter 定义之后，路由模块可安全 `from app.main import limiter`）
from app.routers import analysis, export, resources, analysis_stream, knowledge

app.include_router(analysis.router, prefix="/api/analysis", tags=["工艺分析"])
app.include_router(analysis_stream.router, prefix="/api/analysis", tags=["流式分析"])
app.include_router(export.router, prefix="/api/export", tags=["文档导出"])
app.include_router(resources.router, prefix="/api/resources", tags=["资源管理"])
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["知识库"])

# 创建上传目录
os.makedirs("uploads", exist_ok=True)
os.makedirs("exports", exist_ok=True)

# 静态文件服务
app.mount("/exports", StaticFiles(directory="exports"), name="exports")

@app.get("/")
async def root():
    return {
        "message": "智能制造工艺分析系统 API",
        "version": "1.0.0",
        "docs": "/docs"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
