"""
知识库服务 - 向量数据库 + RAG
用于存储和检索加工工艺知识
"""
import os
import json
import hashlib
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
        # BM25 词法检索语料：与 ChromaDB 文档保持平行（同序同长）
        # _bm25_corpus[i] 的原文对应 _bm25_ids[i] 的文档ID、_bm25_cats[i] 的分类
        self._bm25_corpus: List[str] = []
        self._bm25_ids: List[str] = []
        self._bm25_cats: List[str] = []
        # BM25 索引缓存：语料变更时置 _bm25_dirty=True，下次查询才重建，
        # 避免在 get_context_for_query 这类 RAG 热路径上每次查询都从零重建索引。
        self._bm25 = None
        self._bm25_dirty: bool = True
    
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
            # 生成文档ID：用内容的 md5 摘要而非内置 hash()。
            # 内置 hash() 对字符串带进程级随机化（PYTHONHASHSEED），同一内容跨重启会得到
            # 不同 id，导致 ChromaDB 重复入库、BM25 语料漂移；md5 是确定性的，可天然幂等。
            digest = hashlib.md5(content.encode("utf-8")).hexdigest()[:12]
            doc_id = f"{category}_{digest}"

            # 生成嵌入向量
            embedding = model.encode(content).tolist()

            # 准备元数据
            doc_metadata = {
                "category": category,
                "category_name": self.categories.get(category, category),
                "title": title,
                **(metadata or {})
            }

            # upsert 而非 add：doc_id 由内容确定，重复导入同一文档幂等覆盖，
            # 不会因 "ID already exists" 抛错，也不会产生重复文档。
            collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[content],
                metadatas=[doc_metadata]
            )

            # 同步维护 BM25 词法检索语料（按 doc_id 去重；新增才标记索引需重建）
            if doc_id not in self._bm25_ids:
                self._bm25_corpus.append(content)
                self._bm25_ids.append(doc_id)
                self._bm25_cats.append(category)
                self._bm25_dirty = True

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
        """搜索相关知识（对外接口不变，内部走 BM25+Dense 混合检索）"""
        return self.hybrid_search(query, category=category, top_k=top_k)

    def _dense_search(
        self,
        query: str,
        category: Optional[str] = None,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """纯 dense 向量检索（原 search 逻辑，hybrid_search 的降级回退路径）"""
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

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """分词：优先用 jieba（中文友好），不可用则退化为 split()。
        机加工型号/牌号/公差串（CNMG120408、GH4169、H7/g6）作为整体 token 保留。"""
        try:
            import jieba
            return [t for t in jieba.cut(text) if t.strip()]
        except Exception:
            return text.split()

    def _ensure_bm25_corpus(self) -> None:
        """让 BM25 语料与 ChromaDB 对齐。

        以集合为权威来源：新进程冷启动、或跨进程「先 add 后 search」时，本地语料
        可能为空 / 残缺 / 与持久化集合漂移。只要本地条目数与集合文档数不一致，
        就整体从集合重建语料，杜绝 BM25 召回与向量库不一致。数量一致（in-process
        增量维护即如此）则零成本跳过。
        """
        collection = get_collection()
        if not collection:
            return
        try:
            count = collection.count()
        except Exception as e:
            print(f"[知识库] 读取集合文档数失败: {e}")
            return

        # 已对齐：无需任何回填，热路径零开销
        if len(self._bm25_ids) == count:
            return

        # 集合已清空 → 同步清空本地语料，避免命中已删除文档
        if count == 0:
            self._bm25_corpus, self._bm25_ids, self._bm25_cats = [], [], []
            self._bm25_dirty = True
            return

        try:
            data = collection.get(include=["documents", "metadatas"])
            ids = data.get("ids") or []
            docs = data.get("documents") or []
            metas = data.get("metadatas") or []
            self._bm25_ids = list(ids)
            self._bm25_corpus = [docs[i] if i < len(docs) else "" for i in range(len(ids))]
            self._bm25_cats = [
                (metas[i] or {}).get("category", "") if i < len(metas) else ""
                for i in range(len(ids))
            ]
            self._bm25_dirty = True  # 语料整体重建 → 索引需重建
        except Exception as e:
            print(f"[知识库] BM25 语料回填失败: {e}")

    def _build_bm25(self):
        """构建并缓存 BM25Okapi 索引。

        语料未变更（_bm25_dirty=False）则直接复用缓存，避免在 RAG 热路径上每次
        查询都重新分词+重建索引。rank_bm25 不可用或语料为空时返回 None（触发降级）。
        """
        if not self._bm25_corpus:
            self._bm25 = None
            return None
        if self._bm25 is not None and not self._bm25_dirty:
            return self._bm25
        try:
            from rank_bm25 import BM25Okapi
        except Exception as e:
            print(f"[知识库] rank_bm25 不可用，降级为纯 dense: {e}")
            return None
        tokenized_corpus = [self._tokenize(d) for d in self._bm25_corpus]
        self._bm25 = BM25Okapi(tokenized_corpus)
        self._bm25_dirty = False
        return self._bm25

    def hybrid_search(
        self,
        query: str,
        category: Optional[str] = None,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """BM25 词法检索 + Dense 向量检索，用 RRF 融合。

        刀片型号/材料牌号/公差串/GB标准号等精确 token 由 BM25 兜底，
        语义相近内容由 dense 兜底，二者排名经 RRF (1/(60+rank)) 融合。
        语料为空（知识库未初始化）时安全降级为纯 dense 检索。
        """
        collection = get_collection()
        model = get_embedding_model()

        if not collection or not model:
            return []

        # 对齐语料 → 构建/复用 BM25 索引；任一环节不可用即安全降级为纯 dense
        self._ensure_bm25_corpus()
        bm25 = self._build_bm25()
        if bm25 is None:
            # 语料为空（知识库未初始化）或 rank_bm25 缺失 → 纯 dense 返回，不报错
            return self._dense_search(query, category=category, top_k=top_k)

        try:
            # ---- BM25 词法排名 ----
            # 用 get_scores 而非 get_top_n：get_top_n 会把零分（与查询无任何词法重叠）的
            # 文档也凑满 n 个并按下标 tie-break 返回，这些文档进入 RRF 会污染融合排名。
            # 这里只保留命中（score>0）的文档，再按分数降序，必要时按分类过滤。
            query_tokens = self._tokenize(query)
            scores = bm25.get_scores(query_tokens)
            scored = [
                (self._bm25_ids[i], scores[i])
                for i in range(len(scores))
                if scores[i] > 0 and (category is None or self._bm25_cats[i] == category)
            ]
            scored.sort(key=lambda x: x[1], reverse=True)
            bm25_ranked = [doc_id for doc_id, _ in scored[:min(100, len(scored))]]

            # ---- Dense 向量排名 ----
            query_embedding = model.encode(query).tolist()
            where_filter = {"category": category} if category else None
            n_dense = min(100, collection.count()) or top_k
            dense_res = collection.query(
                query_embeddings=[query_embedding],
                n_results=n_dense,
                where=where_filter,
                include=["documents", "metadatas", "distances"]
            )
            dense_ids = dense_res["ids"][0] if dense_res.get("ids") else []
            dense_detail: Dict[str, Dict[str, Any]] = {}
            for i, did in enumerate(dense_ids):
                dense_detail[did] = {
                    "content": dense_res["documents"][0][i] if dense_res.get("documents") else "",
                    "metadata": dense_res["metadatas"][0][i] if dense_res.get("metadatas") else {},
                    "distance": dense_res["distances"][0][i] if dense_res.get("distances") else 0,
                }
            dense_ranked = list(dense_ids)

            # ---- RRF 融合：score[doc_id] += 1 / (60 + rank) ----
            rrf: Dict[str, float] = {}
            for rank, did in enumerate(dense_ranked):
                rrf[did] = rrf.get(did, 0.0) + 1.0 / (60 + rank)
            for rank, did in enumerate(bm25_ranked):
                rrf[did] = rrf.get(did, 0.0) + 1.0 / (60 + rank)

            if not rrf:
                return self._dense_search(query, category=category, top_k=top_k)

            fused_ids = sorted(rrf, key=lambda d: rrf[d], reverse=True)[:top_k]

            # 补齐仅 BM25 命中（不在 dense top-N）文档的正文/元数据/向量
            missing = [did for did in fused_ids if did not in dense_detail]
            if missing:
                self._fill_missing_detail(missing, query_embedding, dense_detail)

            # ---- 组装结果 ----
            # relevance 一律保持原有不变式 relevance == 1 - distance/2：
            # dense 命中用其返回的 distance；仅 BM25 命中的用与查询向量的余弦距离还原，
            # 不再使用任何与下游阈值耦合的魔数。
            formatted: List[Dict[str, Any]] = []
            for did in fused_ids:
                detail = dense_detail.get(did)
                if not detail:
                    continue
                distance = detail.get("distance", 0)
                formatted.append({
                    "content": detail.get("content", ""),
                    "metadata": detail.get("metadata", {}),
                    "distance": distance,
                    "relevance": 1 - (distance / 2),
                    "rrf_score": rrf[did],
                })

            return formatted

        except Exception as e:
            print(f"[知识库] 混合检索失败，降级为纯 dense: {e}")
            return self._dense_search(query, category=category, top_k=top_k)

    def _fill_missing_detail(
        self,
        missing: List[str],
        query_embedding: List[float],
        dense_detail: Dict[str, Dict[str, Any]],
    ) -> None:
        """为仅 BM25 命中（未进 dense top-N）的文档补齐正文/元数据，并用其向量与查询
        向量的余弦距离还原 distance，使 relevance 仍满足 1 - distance/2 不变式。"""
        collection = get_collection()
        if not collection or not missing:
            return
        try:
            extra = collection.get(
                ids=missing,
                include=["documents", "metadatas", "embeddings"]
            )
        except Exception as e:
            print(f"[知识库] 补齐 BM25 命中文档失败: {e}")
            return

        ids = extra.get("ids") or []
        docs = extra.get("documents") or []
        metas = extra.get("metadatas") or []
        embs = extra.get("embeddings")

        try:
            import numpy as np
            q = np.asarray(query_embedding, dtype=float)
            q_norm = float(np.linalg.norm(q)) or 1.0
        except Exception:
            np = None
            q = q_norm = None

        for i, did in enumerate(ids):
            distance = 0.0
            if np is not None and embs is not None and i < len(embs) and embs[i] is not None:
                v = np.asarray(embs[i], dtype=float)
                v_norm = float(np.linalg.norm(v)) or 1.0
                cos = float(np.dot(q, v) / (q_norm * v_norm))
                distance = 1.0 - cos  # 余弦距离，与 ChromaDB cosine 空间口径一致
            dense_detail[did] = {
                "content": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if i < len(metas) else {},
                "distance": distance,
            }

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
