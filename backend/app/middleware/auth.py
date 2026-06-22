"""API Key 认证中间件"""
import os
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

# 白名单：无需认证的路径
_PUBLIC_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}

API_KEY = os.environ.get("API_KEY", "")


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not API_KEY:
            return await call_next(request)

        path = request.url.path
        if path in _PUBLIC_PATHS or path.startswith("/exports"):
            return await call_next(request)

        key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if key != API_KEY:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

        return await call_next(request)
