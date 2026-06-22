"""
知识库服务 - 向量数据库 + RAG
用于存储和检索加工工艺知识
"""
import os
import json
from typing import List, Dict, Any, Optional
from pathlib import Path

# 延迟导入以避免启动时加载
_chroma_client = None
_embedding_model = None
_collection = None

KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "knowledge_base"
CHROMA_DIR = KNOWLEDGE_DIR / "chroma_db"


def get_embedding_model():
    """获取嵌入模型（延迟加载，使用国内镜像）"""
    global _embedding_model
    if _embedding_model is None:
        try:
            import os
            # 设置国内镜像（HuggingFace Mirror）
            os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
            
            from sentence_transformers import SentenceTransformer
            print("[知识库] 正在从国内镜像加载嵌入模型...")
            
            # 使用支持中文的模型
            # bge-large-zh-v1.5: 中文技术文本专用，对机加工数值/型号 token 校准更好
            # 备选: paraphrase-multilingual-MiniLM-L12-v2（通用，对数值辨识差）
            model_name = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
            _embedding_model = SentenceTransformer(
                model_name,
                cache_folder=str(KNOWLEDGE_DIR / "models")
            )
            print(f"[知识库] 嵌入模型加载完成: {model_name}")
        except Exception as e:
            print(f"[知识库] 嵌入模型加载失败: {e}")
            return None
    return _embedding_model


def get_collection():
    """获取ChromaDB集合（延迟加载）"""
    global _chroma_client, _collection
    if _collection is None:
        try:
            import chromadb
            from chromadb.config import Settings
            
            # 确保目录存在
            CHROMA_DIR.mkdir(parents=True, exist_ok=True)
            
            print("[知识库] 正在初始化ChromaDB...")
            _chroma_client = chromadb.PersistentClient(
                path=str(CHROMA_DIR),
                settings=Settings(anonymized_telemetry=False)
            )
            
            # 获取或创建集合
            _collection = _chroma_client.get_or_create_collection(
                name="manufacturing_knowledge",
                metadata={"description": "制造工艺知识库"}
            )
            print(f"[知识库] ChromaDB初始化完成，当前文档数: {_collection.count()}")
        except Exception as e:
            print(f"[知识库] ChromaDB初始化失败: {e}")
            return None
    return _collection


class KnowledgeService:
    """知识库服务"""
    
    def __init__(self):
        self.categories = {
            "material": "材料参数库",
            "process": "工艺路线库",
            "standard": "标准规范库",
            "tool": "刀具库",
            "cost": "工时成本库",
            "feature": "特征信息库",
        }
    
    def add_document(
        self,
        content: str,
        category: str,
        title: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """添加文档到知识库"""
        collection = get_collection()
        model = get_embedding_model()
        
        if not collection or not model:
            return False
        
        try:
            # 生成文档ID
            doc_id = f"{category}_{hash(content) % 100000:05d}"
            
            # 生成嵌入向量
            embedding = model.encode(content).tolist()
            
            # 准备元数据
            doc_metadata = {
                "category": category,
                "category_name": self.categories.get(category, category),
                "title": title,
                **(metadata or {})
            }
            
            # 添加到集合
            collection.add(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[content],
                metadatas=[doc_metadata]
            )
            
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
        """搜索相关知识"""
        collection = get_collection()
        model = get_embedding_model()
        
        if not collection or not model:
            return []
        
        try:
            # 生成查询向量
            query_embedding = model.encode(query).tolist()
            
            # 构建过滤条件
            where_filter = None
            if category:
                where_filter = {"category": category}
            
            # 执行搜索
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where_filter,
                include=["documents", "metadatas", "distances"]
            )
            
            # 格式化结果
            formatted = []
            if results and results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    formatted.append({
                        "content": doc,
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                        "distance": results["distances"][0][i] if results["distances"] else 0,
                        "relevance": 1 - (results["distances"][0][i] / 2) if results["distances"] else 1
                    })
            
            return formatted
            
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
            if r["relevance"] < 0.3:  # 相关性太低则跳过
                continue
            
            content = r["content"]
            title = r["metadata"].get("title", "")
            
            part = f"【{title}】\n{content}\n"
            
            if total_chars + len(part) > max_chars:
                break
            
            context_parts.append(part)
            total_chars += len(part)
        
        return "\n".join(context_parts)
    
    def init_default_knowledge(self):
        """初始化默认知识库内容"""
        collection = get_collection()
        if not collection:
            return
        
        # 如果已有数据，跳过初始化
        if collection.count() > 0:
            print(f"[知识库] 已有 {collection.count()} 条知识，跳过初始化")
            return
        
        print("[知识库] 正在初始化默认知识...")
        
        # 材料知识
        materials = [
            {
                "title": "45号钢加工参数",
                "content": """45号钢（45#钢）是常用的优质碳素结构钢。
硬度：HRC20-30（调质后）
密度：7.85 g/cm³
推荐切削参数：
- 粗车：切削速度80-120m/min，进给0.3-0.5mm/r，切深2-4mm
- 精车：切削速度120-180m/min，进给0.1-0.2mm/r，切深0.5-1mm
- 钻孔：切削速度20-30m/min，进给0.1-0.3mm/r
热处理：可进行调质、淬火处理，淬火后硬度可达HRC55-60
适用：轴类、齿轮、连杆等中等强度零件"""
            },
            {
                "title": "铝合金6061加工参数",
                "content": """6061铝合金是最常用的铝合金之一。
硬度：HB95（T6状态）
密度：2.7 g/cm³
推荐切削参数：
- 粗车：切削速度200-400m/min，进给0.2-0.4mm/r，切深2-5mm
- 精车：切削速度400-600m/min，进给0.05-0.15mm/r，切深0.3-1mm
- 铣削：切削速度300-500m/min，进给0.1-0.3mm/齿
注意事项：易产生积屑瘤，建议使用锋利刀具和充足冷却液
适用：航空零件、电子外壳、精密零件"""
            },
            {
                "title": "不锈钢304加工参数",
                "content": """304不锈钢是最常用的奥氏体不锈钢。
硬度：HB187（固溶态）
密度：7.93 g/cm³
推荐切削参数：
- 粗车：切削速度60-100m/min，进给0.2-0.4mm/r，切深1.5-3mm
- 精车：切削速度100-150m/min，进给0.1-0.2mm/r，切深0.3-0.8mm
注意事项：加工硬化严重，避免切削速度过低；建议使用涂层刀具
冷却：必须使用充足的切削液
适用：食品机械、医疗器械、化工设备零件"""
            }
        ]
        
        for m in materials:
            self.add_document(m["content"], "material", m["title"])
        
        # 工艺知识
        processes = [
            {
                "title": "轴类零件加工工艺",
                "content": """轴类零件标准加工工艺流程：
1. 下料：根据毛坯余量选择棒料，长度余量3-5mm
2. 粗车：车端面、打中心孔，粗车各外圆留余量0.5-1mm
3. 调质（如需要）：根据材料和硬度要求进行热处理
4. 精车：精车各外圆、台阶面，达到图纸尺寸和粗糙度要求
5. 铣削（如需要）：铣键槽、铣扁位
6. 钻孔（如需要）：钻径向孔、攻螺纹
7. 磨削（如需要）：磨削高精度外圆，Ra0.8以下
8. 检验：检查尺寸、形位公差、表面粗糙度
关键控制点：同轴度、圆柱度、表面粗糙度"""
            },
            {
                "title": "孔加工工艺选择",
                "content": """孔加工方法选择指南：
1. 钻孔：适用于一般精度孔（IT12-IT14），表面粗糙度Ra12.5-25
2. 扩孔：钻孔后扩孔，提高精度至IT10-IT11，Ra6.3-12.5
3. 铰孔：适用于高精度孔（IT7-IT9），Ra1.6-3.2，适合H7配合孔
4. 镗孔：适用于大孔（>30mm）或高精度孔，IT7-IT8，Ra1.6-3.2
5. 磨孔：最高精度，IT6-IT7，Ra0.4-0.8
6. 珩磨：超精加工，Ra0.2-0.4
选择原则：根据孔径、精度、表面粗糙度和批量综合考虑"""
            }
        ]
        
        for p in processes:
            self.add_document(p["content"], "process", p["title"])
        
        # 标准规范
        standards = [
            {
                "title": "一般公差GB/T 1804",
                "content": """GB/T 1804 一般公差 未注公差的线性和角度尺寸的公差
精度等级：f（精密级）、m（中等级）、c（粗糙级）、v（最粗级）

线性尺寸公差（mm）- 中等级m：
- 0.5-3: ±0.1
- 3-6: ±0.1
- 6-30: ±0.2
- 30-120: ±0.3
- 120-400: ±0.5
- 400-1000: ±0.8
- 1000-2000: ±1.2

倒圆和倒角（未注）：0.5-3mm取±0.2，3-6mm取±0.5"""
            },
            {
                "title": "表面粗糙度Ra选用",
                "content": """表面粗糙度Ra选用指南：
Ra0.1-0.2：精密配合面、密封面、量具
Ra0.4-0.8：精密轴承配合、液压阀芯
Ra1.6：一般配合面、滑动面、H7/g6配合
Ra3.2：一般加工面、非配合面
Ra6.3：粗加工面、非重要面
Ra12.5：毛坯面、铸造面

对应加工方法：
Ra0.1-0.4：研磨、珩磨
Ra0.8-1.6：精磨、精车、精铣
Ra3.2：半精加工
Ra6.3-12.5：粗加工"""
            }
        ]
        
        for s in standards:
            self.add_document(s["content"], "standard", s["title"])
        
        print(f"[知识库] 默认知识初始化完成，共 {collection.count()} 条")
    
    def list_all(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取所有知识库条目"""
        collection = get_collection()
        if not collection:
            return []
        
        try:
            # 获取所有文档
            results = collection.get(
                limit=limit,
                include=["documents", "metadatas"]
            )
            
            items = []
            if results and results.get("ids"):
                for i, doc_id in enumerate(results["ids"]):
                    items.append({
                        "id": doc_id,
                        "content": results["documents"][i] if results.get("documents") else "",
                        "metadata": results["metadatas"][i] if results.get("metadatas") else {},
                        "title": results["metadatas"][i].get("title", "") if results.get("metadatas") else "",
                        "category": results["metadatas"][i].get("category", "") if results.get("metadatas") else ""
                    })
            
            return items
        except Exception as e:
            print(f"[知识库] 获取列表失败: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """获取知识库统计信息"""
        collection = get_collection()
        if not collection:
            return {"status": "未初始化", "count": 0, "category_counts": {}}
        
        # 统计每个分类的数量
        category_counts = {}
        try:
            results = collection.get(include=["metadatas"])
            if results and results.get("metadatas"):
                for meta in results["metadatas"]:
                    cat = meta.get("category", "unknown")
                    category_counts[cat] = category_counts.get(cat, 0) + 1
        except Exception as e:
            print(f"[知识库] 统计分类数量失败: {e}")
        
        return {
            "status": "正常",
            "count": collection.count(),
            "categories": self.categories,
            "category_counts": category_counts
        }


# 全局实例
knowledge_service = KnowledgeService()
