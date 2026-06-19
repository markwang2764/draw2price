"""
知识库服务 - JSON文件存储 + 关键词搜索
用于存储和检索加工工艺知识
（简化版：不依赖向量数据库和HuggingFace模型）
"""
import os
import json
import re
from typing import List, Dict, Any, Optional
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "knowledge_base"
KNOWLEDGE_FILE = KNOWLEDGE_DIR / "knowledge_data.json"

# 内存缓存
_knowledge_cache = None


def load_knowledge() -> List[Dict]:
    """加载知识库数据"""
    global _knowledge_cache
    if _knowledge_cache is not None:
        return _knowledge_cache
    
    try:
        KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        if KNOWLEDGE_FILE.exists():
            with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
                _knowledge_cache = json.load(f)
                print(f"[知识库] 已加载 {len(_knowledge_cache)} 条知识")
        else:
            _knowledge_cache = []
            print("[知识库] 知识库文件不存在，创建空库")
    except Exception as e:
        print(f"[知识库] 加载失败: {e}")
        _knowledge_cache = []
    
    return _knowledge_cache


def save_knowledge(data: List[Dict]):
    """保存知识库数据"""
    global _knowledge_cache
    try:
        KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        with open(KNOWLEDGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _knowledge_cache = data
        print(f"[知识库] 已保存 {len(data)} 条知识")
    except Exception as e:
        print(f"[知识库] 保存失败: {e}")


def calculate_relevance(query: str, content: str, title: str) -> float:
    """计算关键词匹配相关性"""
    query_lower = query.lower()
    content_lower = content.lower()
    title_lower = title.lower()
    
    # 分词（简单按空格和标点分割）
    query_words = set(re.findall(r'[\u4e00-\u9fa5]+|[a-zA-Z0-9]+', query_lower))
    
    if not query_words:
        return 0.0
    
    # 计算匹配分数
    score = 0.0
    for word in query_words:
        if len(word) < 2:
            continue
        # 标题匹配权重更高
        if word in title_lower:
            score += 3.0
        # 内容匹配
        count = content_lower.count(word)
        if count > 0:
            score += min(count, 5) * 0.5  # 最多计5次
    
    # 归一化到0-1
    max_score = len(query_words) * 5.5
    return min(score / max_score, 1.0) if max_score > 0 else 0.0


class KnowledgeService:
    """知识库服务"""
    
    def __init__(self):
        self.categories = {
            "tool": "刀具库",
            "process_route": "工艺路线库", 
            "cost": "工时成本库",
            "feature": "特征信息库"
        }
    
    def add_document(
        self,
        content: str,
        category: str,
        title: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """添加文档到知识库"""
        try:
            data = load_knowledge()
            
            # 生成文档ID
            doc_id = f"{category}_{abs(hash(content)) % 100000:05d}"
            
            # 检查是否已存在
            for item in data:
                if item.get("id") == doc_id:
                    print(f"[知识库] 文档已存在，跳过: {title}")
                    return True
            
            # 添加新文档
            doc = {
                "id": doc_id,
                "content": content,
                "category": category,
                "category_name": self.categories.get(category, category),
                "title": title,
                "metadata": metadata or {}
            }
            data.append(doc)
            
            save_knowledge(data)
            print(f"[知识库] 已添加文档: {title} ({category})")
            return True
            
        except Exception as e:
            print(f"[知识库] 添加文档失败: {e}")
            return False
    
    def search(
        self,
        query: str,
        category: Optional[str] = None,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """搜索相关知识（关键词匹配）"""
        try:
            data = load_knowledge()
            
            if not data:
                return []
            
            # 过滤分类
            if category:
                data = [d for d in data if d.get("category") == category]
            
            # 计算相关性并排序
            results = []
            for doc in data:
                relevance = calculate_relevance(
                    query, 
                    doc.get("content", ""),
                    doc.get("title", "")
                )
                if relevance > 0.1:  # 最低相关性阈值
                    results.append({
                        "content": doc.get("content", ""),
                        "metadata": {
                            "category": doc.get("category", ""),
                            "category_name": doc.get("category_name", ""),
                            "title": doc.get("title", ""),
                            **doc.get("metadata", {})
                        },
                        "relevance": relevance
                    })
            
            # 按相关性排序
            results.sort(key=lambda x: x["relevance"], reverse=True)
            
            return results[:top_k]
            
        except Exception as e:
            print(f"[知识库] 搜索失败: {e}")
            return []
    
    def get_context_for_query(self, query: str, max_chars: int = 2000) -> str:
        """获取查询相关的上下文（用于RAG）"""
        results = self.search(query, top_k=3)
        
        if not results:
            return ""
        
        context_parts = []
        total_chars = 0
        
        for r in results:
            if r["relevance"] < 0.15:  # 相关性太低则跳过
                continue
            
            content = r["content"]
            title = r["metadata"].get("title", "")
            
            part = f"【{title}】\n{content}\n"
            
            if total_chars + len(part) > max_chars:
                break
            
            context_parts.append(part)
            total_chars += len(part)
        
        return "\n".join(context_parts)
    
    def list_all(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取所有知识库条目"""
        try:
            data = load_knowledge()
            items = []
            for doc in data[:limit]:
                items.append({
                    "id": doc.get("id", ""),
                    "content": doc.get("content", ""),
                    "metadata": {
                        "category": doc.get("category", ""),
                        "category_name": doc.get("category_name", ""),
                        "title": doc.get("title", ""),
                        **doc.get("metadata", {})
                    },
                    "title": doc.get("title", ""),
                    "category": doc.get("category", "")
                })
            return items
        except Exception as e:
            print(f"[知识库] 获取列表失败: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """获取知识库统计信息"""
        try:
            data = load_knowledge()
            
            # 统计各分类数量
            category_counts = {}
            for doc in data:
                cat = doc.get("category", "unknown")
                category_counts[cat] = category_counts.get(cat, 0) + 1
            
            return {
                "status": "正常",
                "count": len(data),
                "categories": self.categories,
                "category_counts": category_counts
            }
        except Exception as e:
            return {"status": f"错误: {e}", "count": 0}
    
    def delete_document(self, doc_id: str) -> bool:
        """删除文档"""
        try:
            data = load_knowledge()
            new_data = [d for d in data if d.get("id") != doc_id]
            if len(new_data) < len(data):
                save_knowledge(new_data)
                print(f"[知识库] 已删除文档: {doc_id}")
                return True
            return False
        except Exception as e:
            print(f"[知识库] 删除失败: {e}")
            return False
    
    def clear_all(self) -> bool:
        """清空知识库"""
        try:
            save_knowledge([])
            print("[知识库] 已清空所有数据")
            return True
        except Exception as e:
            print(f"[知识库] 清空失败: {e}")
            return False


# 全局实例
knowledge_service = KnowledgeService()
