"""
启动后端服务
"""
import sys
import logging
import uvicorn
from app.core.config import settings

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.StreamHandler(sys.stderr)
    ]
)

if __name__ == "__main__":
    print("="*60)
    print("🏭 智能制造工艺分析系统 - 后端服务")
    print("="*60)
    print(f"📡 主机: {settings.host}")
    print(f"🔌 端口: {settings.port}")
    print(f"🤖 AI模型: {settings.mistral_model}")
    print(f"👁️ 视觉模型: {settings.vision_model}")
    print(f"🌐 API地址: {settings.mistral_base_url}")
    print("="*60)
    print()

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level="info",
        access_log=True
    )
