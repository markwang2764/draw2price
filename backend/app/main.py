"""
MistralAI 制造工艺分析系统 - 主入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from app.routers import analysis, export, resources, analysis_stream, knowledge
from app.core.config import settings

app = FastAPI(
    title="智能制造工艺分析系统",
    description="基于Mistral AI的零部件图纸分析、工艺生成、排产计划系统",
    version="1.0.0"
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
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
