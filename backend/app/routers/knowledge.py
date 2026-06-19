"""
知识库API路由
"""
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import Optional, List
from pydantic import BaseModel

from app.services.knowledge_service import knowledge_service

router = APIRouter()


class AddDocumentRequest(BaseModel):
    content: str
    category: str
    title: str
    metadata: Optional[dict] = None


class SearchRequest(BaseModel):
    query: str
    category: Optional[str] = None
    top_k: int = 5


@router.get("/stats")
async def get_stats():
    """获取知识库统计信息"""
    return knowledge_service.get_stats()


@router.post("/init")
async def init_knowledge():
    """初始化默认知识库"""
    knowledge_service.init_default_knowledge()
    return {"message": "知识库初始化完成", "stats": knowledge_service.get_stats()}


@router.post("/add")
async def add_document(request: AddDocumentRequest):
    """添加文档到知识库"""
    success = knowledge_service.add_document(
        content=request.content,
        category=request.category,
        title=request.title,
        metadata=request.metadata
    )
    
    if success:
        return {"message": "文档添加成功", "stats": knowledge_service.get_stats()}
    else:
        raise HTTPException(status_code=500, detail="文档添加失败")


@router.post("/search")
async def search(request: SearchRequest):
    """搜索知识库"""
    results = knowledge_service.search(
        query=request.query,
        category=request.category,
        top_k=request.top_k
    )
    
    return {
        "query": request.query,
        "count": len(results),
        "results": results
    }


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form(...),
    title: str = Form(...)
):
    """上传文档文件"""
    content = await file.read()
    
    # 根据文件类型解析内容
    filename = file.filename.lower()
    
    if filename.endswith('.txt'):
        text_content = content.decode('utf-8')
    elif filename.endswith('.pdf'):
        try:
            import fitz
            pdf = fitz.open(stream=content, filetype="pdf")
            text_content = ""
            for page in pdf:
                text_content += page.get_text()
            pdf.close()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"PDF解析失败: {e}")
    elif filename.endswith(('.doc', '.docx')):
        try:
            from docx import Document
            import io
            doc = Document(io.BytesIO(content))
            text_content = "\n".join([p.text for p in doc.paragraphs])
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Word文档解析失败: {e}")
    else:
        raise HTTPException(status_code=400, detail="不支持的文件格式，请上传txt/pdf/docx文件")
    
    # 添加到知识库
    success = knowledge_service.add_document(
        content=text_content,
        category=category,
        title=title,
        metadata={"filename": file.filename}
    )
    
    if success:
        return {"message": "文档上传成功", "stats": knowledge_service.get_stats()}
    else:
        raise HTTPException(status_code=500, detail="文档添加失败")


@router.get("/list")
async def list_knowledge():
    """获取所有知识库条目"""
    try:
        items = knowledge_service.list_all()
        return {"items": items, "count": len(items)}
    except Exception as e:
        return {"items": [], "count": 0, "error": str(e)}


@router.get("/categories")
async def get_categories():
    """获取知识分类"""
    return knowledge_service.categories
