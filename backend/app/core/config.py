"""
应用配置
"""
import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # AI模型配置
    mistral_api_key: str = os.getenv("MISTRAL_API_KEY", "")
    mistral_base_url: str = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1")
    mistral_model: str = os.getenv("MISTRAL_MODEL", "mistral-large-latest")
    vision_model: str = os.getenv("VISION_MODEL", "llava")
    
    # 服务器配置
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    
    # 公司配置
    company_config_path: str = os.getenv("COMPANY_CONFIG_PATH", "./config/company_resources.json")

    # 数据库（当前未使用，仅声明以兼容 .env 中的 DATABASE_URL）
    database_url: str = os.getenv("DATABASE_URL", "")

    class Config:
        env_file = ".env"
        extra = "ignore"  # 忽略 .env 中未声明的额外字段，避免 pydantic v2 启动报错

settings = Settings()
