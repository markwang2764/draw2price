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
_embedding_model_failed = False  # 记录模型加载已失败，避免每次写入都重试联网（离线时会很慢）
_embedding_dim = None  # 模型加载成功后记录其输出维度（用于维度一致性校验）
_collection = None

KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "knowledge_base"
CHROMA_DIR = KNOWLEDGE_DIR / "chroma_db"

# 离线兜底嵌入维度（仅在「全新空库 + 模型不可用」时使用；有数据时跟随集合实际维度）
FALLBACK_EMBEDDING_DIM = 256

# ChromaDB 距离度量。必须是 cosine：全库的 relevance=1-distance/2 与 _fill_missing_detail
# 的余弦距离回填都以 [0,2] 的余弦距离为前提；默认 L2 距离可达任意大，会算出负 relevance、
# 污染排序，并使 get_context_for_query 的 relevance<0.3 过滤把所有结果误删。
EMBEDDING_SPACE = "cosine"
_COLLECTION_NAME = "manufacturing_knowledge"
_COLLECTION_METADATA = {"description": "制造工艺知识库", "hnsw:space": EMBEDDING_SPACE}


def _stable_hash(s: str) -> int:
    """跨进程稳定的哈希（内置 hash() 会受 PYTHONHASHSEED 随机化，不能用于持久化场景）"""
    return int(hashlib.md5(s.encode("utf-8")).hexdigest(), 16)


def _relevance_from_distance(distance: float) -> float:
    """余弦距离 [0,2] → relevance [0,1]。钳制以吸收浮点误差/异常距离，绝不返回负值。"""
    try:
        return max(0.0, min(1.0, 1.0 - float(distance) / 2.0))
    except (TypeError, ValueError):
        return 0.0


def _fallback_embedding(text: str, dim: int = FALLBACK_EMBEDDING_DIM) -> List[float]:
    """离线兜底嵌入：当 sentence-transformers 模型无法加载（离线/无网络/无 GPU）时，
    用确定性特征哈希（feature hashing）生成稳定向量，保证知识库仍能写入并做粗排检索。

    说明：这是真实的向量化（按 词 + 2-gram 字符 做带符号哈希计数 + L2 归一化），
    并非占位/假数据；语义质量低于 bge 等模型，仅作为模型不可用时的降级方案。
    """
    vec = [0.0] * dim
    # 词级特征 + 字符 2-gram（提升对型号/数值如 "TC4"、"40-80m/min" 的区分度）
    grams = text.split() + [text[i:i + 2] for i in range(len(text) - 1)]
    for g in grams:
        if not g:
            continue
        h = _stable_hash(g)
        idx = h % dim
        sign = 1.0 if (h // dim) % 2 == 0 else -1.0
        vec[idx] += sign
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def _cached_model_snapshots() -> List[Path]:
    """扫描 cache_folder 下已完整缓存的 sentence-transformers 快照目录。

    HuggingFace 缓存布局为 models--<org>--<name>/snapshots/<rev>/。一个快照只有同时具备
    config.json 与权重文件才算完整、可直接按本地路径离线加载（绕开 hub 的联网 revision 解析，
    这是默认模型未预下载时仍能离线起服务的关键）。
    """
    models_dir = KNOWLEDGE_DIR / "models"
    if not models_dir.exists():
        return []
    snaps = []
    for snap in models_dir.glob("models--*/snapshots/*"):
        if not snap.is_dir():
            continue
        has_cfg = (snap / "config.json").exists()
        has_weights = (snap / "model.safetensors").exists() or (snap / "pytorch_model.bin").exists()
        if has_cfg and has_weights:
            snaps.append(snap)
    return snaps


def get_embedding_model():
    """获取嵌入模型（延迟加载）。

    依次尝试：环境变量/默认配置的模型 → 本地已缓存的快照（按路径直接加载，离线可用）。
    全部失败才返回 None，由调用方走离线兜底嵌入。加载成功时记录输出维度，供维度一致性校验。
    """
    global _embedding_model, _embedding_model_failed, _embedding_dim
    if _embedding_model_failed:
        return None
    if _embedding_model is not None:
        return _embedding_model

    try:
        from sentence_transformers import SentenceTransformer
    except Exception as e:
        print(f"[知识库] sentence-transformers 不可用: {e}（使用离线兜底嵌入）")
        _embedding_model_failed = True
        return None

    # 仅在用户未显式配置时才设国内镜像，避免覆盖离线模式(HF_HUB_OFFLINE)或自定义端点
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    cache_folder = str(KNOWLEDGE_DIR / "models")

    # bge-large-zh-v1.5: 中文技术文本专用；不可用时回退到任何本地已缓存模型（如
    # paraphrase-multilingual-MiniLM-L12-v2），保证离线/新机器仍能起服务。
    configured = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
    candidates: List[str] = [configured]
    candidates += [str(p) for p in _cached_model_snapshots() if str(p) != configured]

    for cand in candidates:
        try:
            print(f"[知识库] 尝试加载嵌入模型: {cand}")
            model = SentenceTransformer(cand, cache_folder=cache_folder)
            _embedding_model = model
            _embedding_dim = model.get_sentence_embedding_dimension()
            print(f"[知识库] 嵌入模型加载完成: {cand} (dim={_embedding_dim})")
            return _embedding_model
        except Exception as e:
            print(f"[知识库] 加载失败 {cand}: {e}")

    print("[知识库] 所有候选嵌入模型均不可用，改用离线兜底嵌入")
    _embedding_model_failed = True
    return None


def _existing_collection_dim() -> Optional[int]:
    """探测已持久化集合的向量维度（取一条样本的 embedding 长度）。空库返回 None。"""
    try:
        col = get_collection()
        if not col or col.count() == 0:
            return None
        peek = col.get(limit=1, include=["embeddings"])
        embs = peek.get("embeddings")
        if embs is not None and len(embs) > 0 and embs[0] is not None:
            return len(embs[0])
    except Exception as e:
        print(f"[知识库] 探测集合维度失败: {e}")
    return None


def _active_embedding_dim() -> int:
    """当前应使用的嵌入维度。

    模型已加载 → 模型维度；否则跟随已有集合维度（保证离线兜底向量能写入/检索同一个库，
    根治 "Collection expecting embedding with dimension of X, got Y"）；全新空库 → 兜底默认值。
    """
    if _embedding_dim:
        return _embedding_dim
    dim = _existing_collection_dim()
    if dim:
        return dim
    return FALLBACK_EMBEDDING_DIM


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
            
            # 获取或创建集合（cosine 空间）
            _collection = _chroma_client.get_or_create_collection(
                name=_COLLECTION_NAME,
                metadata=dict(_COLLECTION_METADATA),
            )
            # 迁移：旧集合可能用默认 L2 空间（建库时漏设 hnsw:space），relevance=1-distance/2
            # 在 L2 下会得到负值/错排。空间一经创建无法原地修改，只能删除重建。集合是可由
            # init_default_knowledge / 上传重新填充的派生缓存，重建安全（旧 L2 数据本就不可用）。
            space = (_collection.metadata or {}).get("hnsw:space")
            if space != EMBEDDING_SPACE:
                cnt = _collection.count()
                print(f"[知识库] 集合距离度量为 {space!r}≠{EMBEDDING_SPACE}，删除重建"
                      f"（原 {cnt} 条，需重新 init / 上传填充）")
                _chroma_client.delete_collection(_COLLECTION_NAME)
                _collection = _chroma_client.create_collection(
                    name=_COLLECTION_NAME,
                    metadata=dict(_COLLECTION_METADATA),
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
    
    def _encode(self, text: str) -> List[float]:
        """文本向量化：优先用语义模型，模型不可用时回退到离线兜底嵌入。
        返回值始终是非空向量，保证写入/检索在离线环境下也不会整体失败。"""
        model = get_embedding_model()
        if model is not None:
            try:
                return model.encode(text).tolist()
            except Exception as e:
                print(f"[知识库] 模型编码失败，改用离线兜底嵌入: {e}")
        # 兜底向量维度跟随激活维度（已有集合维度 / 模型维度），避免与持久化集合维度冲突
        return _fallback_embedding(text, dim=_active_embedding_dim())

    def add_document(
        self,
        content: str,
        category: str,
        title: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """添加文档到知识库"""
        collection = get_collection()

        if not collection:
            return False

        try:
            # 生成文档ID（用稳定哈希，避免 PYTHONHASHSEED 随机化导致跨进程 ID 漂移）
            doc_id = f"{category}_{_stable_hash(content) % 100000:05d}"

            # 生成嵌入向量（模型不可用时自动回退离线兜底嵌入）
            embedding = self._encode(content)

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

        if not collection:
            return []

        try:
            # 生成查询向量（与写入端一致：模型不可用时回退离线兜底嵌入）
            query_embedding = self._encode(query)

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
                        "relevance": _relevance_from_distance(results["distances"][0][i]) if results["distances"] else 1.0
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

        if not collection:
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

            # ---- Dense 向量排名 ----（与写入端一致：模型不可用时回退离线兜底嵌入）
            query_embedding = self._encode(query)
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
                    "relevance": _relevance_from_distance(distance),
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
    
    def _existing_titles(self) -> set:
        """读取知识库中已存在的标题集合（用于按 title 去重，避免重复写入）"""
        collection = get_collection()
        if not collection:
            return set()
        try:
            results = collection.get(include=["metadatas"])
            titles = set()
            if results and results.get("metadatas"):
                for meta in results["metadatas"]:
                    t = (meta or {}).get("title")
                    if t:
                        titles.add(t)
            return titles
        except Exception as e:
            print(f"[知识库] 读取已有标题失败: {e}")
            return set()

    def init_default_knowledge(self):
        """初始化默认知识库内容

        注意:
        - category 名称统一为 material/process/standard/tool/cost，与 self.categories 对齐。
        - 按 title 去重：已存在的标题不再重复写入，因此可在已有数据的库上安全地补充新条目，
          而不是简单地"有数据就整体跳过"。
        """
        collection = get_collection()
        if not collection:
            return

        before = collection.count()
        print(f"[知识库] 初始化默认知识，当前已有 {before} 条，开始按标题补充缺失条目...")

        # 材料参数库 category="material"
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
            },
            {
                "title": "40Cr调质钢加工参数",
                "content": """40Cr是常用的合金调质钢，强度和淬透性优于45钢。
硬度：调质处理后HRC28-32
推荐切削参数：
- 粗车：切削速度100-140m/min，进给0.2-0.4mm/r，切深1-3mm
- 精车：切削速度140-180m/min，进给0.1-0.2mm/r，切深0.3-1mm
注意事项：调质后硬度高、较难切削，推荐使用涂层硬质合金刀片
适用：齿轮、轴、螺栓等承受交变载荷的重要零件"""
            },
            {
                "title": "42CrMo高强钢加工参数",
                "content": """42CrMo是高强度合金结构钢，淬透性好、强度高。
推荐切削参数：
- 粗车：切削速度80-120m/min，进给0.2-0.4mm/r，切深1-3mm
- 精车：切削速度120-160m/min，进给0.1-0.2mm/r
- 铣削：切削速度80-120m/min
注意事项：推荐TiAlN涂层刀片，尽量避免断续切削以防崩刃；切削力较大，机床刚性要足
适用：大截面齿轮轴、连杆、高强度螺栓、模具"""
            },
            {
                "title": "Q235普碳钢加工参数",
                "content": """Q235是最常用的普通碳素结构钢，塑性好、易加工。
推荐切削参数：
- 车削：切削速度150-200m/min，进给0.2-0.4mm/r
- 钻孔（高速钢钻头）：切削速度15-25m/min
- 钻孔（硬质合金钻头）：切削速度30-50m/min
注意事项：加工性好，普通车削可不用冷却液；塑性大易粘刀，注意排屑
适用：一般结构件、焊接件、支架、法兰"""
            },
            {
                "title": "7075铝合金加工参数",
                "content": """7075是高强度航空铝合金（Al-Zn-Mg-Cu系）。
推荐切削参数：
- 铣削：切削速度600-1000m/min，每齿进给0.05-0.2mm
注意事项：使用PCD或锋利的未涂层刀具，保持充分冷却以防积屑瘤与热变形；高速加工排屑要顺畅
适用：航空结构件、模具、高强度受力零件"""
            },
            {
                "title": "TC4钛合金加工参数",
                "content": """TC4（Ti-6Al-4V）钛合金，强度高、导热差，属难加工材料。极低切削速度！
推荐切削参数：
- 车削：切削速度40-80m/min（仅为铝合金的约1/8），进给0.1-0.2mm/r，切深0.5-2mm
关键注意事项：
- 必须使用大量冷却液，严禁干切（钛屑易燃、刀-屑温度极高）
- 使用锋利刀片、小前角，保持锋利避免摩擦生热
- 导热差导致热量集中刀尖，刀具寿命极短，需勤换刀
适用：航空航天、医疗植入体、高端结构件"""
            },
            {
                "title": "GH4169高温合金加工参数",
                "content": """GH4169（Inconel 718）镍基高温合金，是最难加工的材料之一。
推荐切削参数：
- 车削：切削速度20-40m/min，进给0.1-0.15mm/r，切深0.5-1.5mm
关键注意事项：
- 切削力约为45钢的3倍，机床与刀具系统刚性要高
- 加工硬化与高温强度极强，使用陶瓷或CBN刀片
- 严格控制切削温度，充足冷却，刀具磨损快需密切监控
适用：航空发动机涡轮盘/叶片、燃气轮机高温部件"""
            },
            {
                "title": "HT200灰铸铁加工参数",
                "content": """HT200是常用灰铸铁，含片状石墨，切削性好、可干切。
推荐切削参数：
- 车削：切削速度80-120m/min
- 钻孔：切削速度20-30m/min
注意事项：可干切（石墨自润滑），推荐无涂层硬质合金刀片；切屑呈崩碎状，注意防尘
适用：机床床身、箱体、泵壳、阀体等承压铸件"""
            },
            {
                "title": "H62黄铜加工参数",
                "content": """H62是常用黄铜（铜锌合金），切削性优良、易加工。
推荐切削参数：
- 车削：切削速度150-250m/min，进给0.2-0.4mm/r
注意事项：易产生积屑瘤，应使用前角较大的锋利刀具改善表面质量；切屑短小利于排屑
适用：阀门、接头、装饰件、电气导电零件"""
            },
            {
                "title": "POM/尼龙工程塑料加工参数",
                "content": """POM（聚甲醛）、尼龙等工程塑料，热膨胀大、易受热变形。
推荐切削参数：
- 铣削：切削速度200-400m/min，进给0.1-0.2mm/齿
关键注意事项：
- 禁止使用冷却液（吸湿/吸液影响尺寸精度）
- 粗加工后让零件充分冷却再精加工，避免热变形导致尺寸超差
- 刀具锋利、排屑顺畅，防止熔化粘刀
适用：齿轮、轴承保持架、绝缘件、精密结构件"""
            },
            {
                "title": "65Mn弹簧钢加工参数",
                "content": """65Mn是常用弹簧钢，淬火后硬度高、弹性好。
推荐切削参数（退火态）：
- 车削：切削速度70-110m/min，进给0.15-0.3mm/r，切深1-2.5mm
注意事项：一般在退火/正火态加工成形，淬火后仅做磨削；淬火态硬车需CBN刀片
适用：弹簧、卡簧、垫圈、刀片等弹性零件"""
            },
        ]

        # 工艺路线库 category="process"
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
            },
            {
                "title": "盘类零件加工工艺",
                "content": """盘类零件标准加工工艺流程：
车端面 → 粗车外圆 → 精车外圆 → 钻孔 → 镗孔 → 铣槽 → 检验
关键控制点：
- 端面跳动≤0.02mm
- 一次装夹尽量完成端面与外圆加工，保证位置精度
- 大端面注意防止让刀和热变形
适用：法兰盘、齿轮坯、端盖、皮带轮等盘类件"""
            },
            {
                "title": "薄壁件防振防变形工艺",
                "content": """薄壁件（壁厚<3mm）加工要点：
1. 夹持：使用软爪夹持，减小夹紧力以防夹紧变形
2. 切削：多次轻切，粗、精加工分开，逐步释放残余应力
3. 充填法：腔体内灌注蜡或低熔点合金增加刚性，加工后熔出
4. 刀具：锋利刀具、小切深、高转速，减小切削力
关键：防止夹紧变形与切削振动导致的壁厚不均
适用：薄壁套筒、薄壁壳体、薄壁环类零件"""
            },
            {
                "title": "深孔钻削工艺（L/D>5）",
                "content": """深孔（长径比L/D>5）钻削工艺：
1. 先钻引导孔约2mm深，保证后续钻头不偏斜
2. 使用深孔钻，进给0.05-0.1mm/r
3. 每钻入1-2倍直径（1-2×D）退刀排屑，防止堵屑折断
4. 采用高压内冷，将切屑冲出并冷却刀刃
5. 转速降至正常的约60%，控制切削温度与振动
关键：排屑与冷却是深孔加工成败关键
适用：液压阀体油道、喷油嘴、长轴中心孔"""
            },
            {
                "title": "内螺纹攻丝工艺",
                "content": """内螺纹攻丝（数控加工）：
- 指令：G84攻右旋螺纹，G74攻左旋螺纹
- 进给 = 主轴转速 × 螺距（同步攻丝）
- 底孔直径 = 螺纹外径 - 1.08 × 螺距
- 攻丝前先对孔口倒角，便于丝锥切入、保护牙顶
注意：刚性攻丝需主轴与进给严格同步，使用攻丝专用浮动夹头或刚性攻丝功能
适用：各类内螺纹孔加工"""
            },
            {
                "title": "外螺纹车削工艺",
                "content": """外螺纹车削（数控车）：
- 指令：G32单行程螺纹切削 / G92螺纹切削循环 / G76螺纹复合循环
- 分层切深：首次切深约0.4mm，逐渐递减至0.05mm，保证牙型与表面质量
- 牙型角60°（普通公制/英制三角螺纹），使用60°螺纹车刀片
注意：转速与螺距匹配，注意退刀槽，防止乱牙
适用：螺栓、丝杆、管螺纹等外螺纹零件"""
            },
            {
                "title": "高精度外圆磨削工艺",
                "content": """高精度外圆磨削工艺：
- 磨削余量：0.2-0.3mm
- 分阶段：粗磨留0.05mm → 精磨至最终尺寸
- 砂轮线速度：30-35m/s
- 工件转速：15-25m/min
- 可达表面粗糙度Ra0.8以下
注意：充分冷却防烧伤，及时修整砂轮保持锋利
适用：高精度轴颈、配合外圆、量具表面"""
            },
            {
                "title": "孔珩磨工艺",
                "content": """孔珩磨（超精加工）工艺：
- 适用孔径：>10mm
- 往复速度：5-20m/min
- 旋转速度：30-120rpm
- 每次往复进给（涨刀量）：0.005-0.02mm
- 可达表面粗糙度Ra0.2-0.4μm
特点：珩磨头浮动，可纠正孔的圆度与圆柱度，形成交叉网纹利于储油
适用：液压缸内孔、发动机缸孔、精密配合孔"""
            },
            {
                "title": "淬硬钢硬车工艺（HRC45+）",
                "content": """淬硬钢硬车（硬度HRC45以上）：
- 刀具：必须使用CBN（立方氮化硼）刀片
- 切削速度：80-200m/min
- 进给：0.08-0.15mm/r
- 切深：0.1-0.5mm
- 可达表面粗糙度Ra0.4，常可替代磨削（以车代磨）
注意：机床刚性要高，刀尖圆角与负前角增强强度，控制切削热
适用：淬火轴承环、齿轮、淬硬模具型面"""
            },
        ]

        # 刀具库 category="tool"
        tools = [
            {
                "title": "外圆车刀CNMG刀片规格",
                "content": """CNMG系列外圆车刀片（80°菱形）选用：
- CNMG120408：通用型，适合一般粗车、半精车
- CNMG120404：刀尖圆角小（R0.4），适合精加工
特点：80°菱形刀尖强度高，可用于车削外圆和端面（双向切削）
命名规律：C-80°菱形，N-0°后角，M-公差等级，G-断屑槽型；12-边长，04-厚度，08/04-刀尖圆角(R0.8/R0.4)
适用：外圆、端面车削，钢件/不锈钢/铸铁"""
            },
            {
                "title": "钻头直径与进给量关系",
                "content": """麻花钻进给量随直径选取（钢件参考）：
- φ3-6mm：进给0.05-0.1mm/r
- φ6-12mm：进给0.1-0.2mm/r
- φ12-25mm：进给0.2-0.3mm/r
深孔提示：孔深超过20倍直径（20×D）需采用啄钻（间断退屑）
注意：直径越大进给越大，但需结合机床功率与排屑能力；脆性材料可适当提高进给"""
            },
            {
                "title": "立铣刀切削参数",
                "content": """立铣刀参数选用：
- 每齿进给估算 = 铣床功率×效率 ÷ (齿数 × Vc/π/D)
- 小径立铣刀（≤6mm）：每齿进给0.01-0.05mm/齿
- 硬质合金立铣刀切削速度较高速钢快3-5倍
要点：小刀具刚性差，应小切深高转速；大切深时降低每齿进给防崩刃
适用：平面、台阶、轮廓、键槽铣削"""
            },
            {
                "title": "刀具磨损判定标准",
                "content": """刀具磨损与换刀判据：
- 后刀面磨损VB=0.3mm（粗加工）需换刀
- 后刀面磨损VB=0.1mm（精加工）需换刀
- 切削力突然增大约20%，提示刀具急剧磨损/崩刃，需换刀
- 加工表面粗糙度超差，提示刀刃钝化，需换刀
辅助信号：异常噪声、切屑颜色变深、火花增多
意义：及时换刀保证尺寸精度与表面质量，避免崩刀损伤工件"""
            },
            {
                "title": "刀具涂层选择指南",
                "content": """常见刀具涂层及适用：
- TiN（氮化钛，金黄色）：通用涂层，适合钢铁普通加工
- TiAlN（氮铝化钛）：耐高温，适合高速切削及难加工材料
- AlTiN：含铝量更高，最耐热，适合高温合金/淬硬钢
- DLC（类金刚石）：适合铝合金/有色金属，低摩擦不易产生积屑瘤
选择原则：按工件材料、切削速度、是否高温干切综合选涂层"""
            },
        ]

        # 标准规范库 category="standard"
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
            },
            {
                "title": "GB/T 1958形位公差检测",
                "content": """GB/T 1958 形位公差检测方法：
- 圆度：用V形块支承工件+千分表，回转一周读取最大最小差
- 圆柱度：用圆柱度仪测量，或V形块多截面测量取包络
- 平面度：用平晶（光学）或水平仪/平板+塞尺测量
- 同轴度：两顶尖支承（轴类），千分表测各截面跳动
- 直线度/平行度：百分表沿基准移动测量
原则：先确定基准，再按公差项目选用对应量具与方法"""
            },
            {
                "title": "表面粗糙度与加工方法对应表",
                "content": """表面粗糙度Ra（μm）与加工方法对应（由细到粗）：
- Ra0.025：研磨/超精加工
- Ra0.05：超精磨
- Ra0.1：精研
- Ra0.2：精磨
- Ra0.4：精车、精铣
- Ra0.8：半精磨、精铣
- Ra1.6：精车、铰孔
- Ra3.2：半精车、精钻
- Ra6.3：粗车、半精钻
- Ra12.5：粗加工
用途：据图纸Ra反查可行加工方法，规划工序与余量"""
            },
            {
                "title": "公差配合选用指南",
                "content": """常用孔轴配合（基孔制）选用：
- H7/g6：高精度滑动配合（主轴、轴承位）
- H7/k6：过渡配合（轮毂与轴、定位销）
- H7/n6：较紧过渡/轻过盈（齿轮与轴）
- H8/f7：一般动配合（液压缸、滑动轴承）
- H11/c11：松动配合（一般间隙、装拆方便处）
原则：相对运动选间隙配合，需传扭/定位选过渡或过盈配合"""
            },
            {
                "title": "刀具寿命Taylor公式",
                "content": """刀具寿命Taylor公式：Vc·T^n = C
- Vc：切削速度，T：刀具寿命(min)，n、C为经验常数
- 指数n参考值：
  · 高速钢HSS：n=0.1-0.15
  · 硬质合金：n=0.2-0.3
  · 陶瓷：n=0.4-0.6
- 推荐刀具寿命T：粗加工15min / 精加工60min / 自动线180min
用途：在切削速度与刀具寿命间权衡，估算换刀周期与单件刀具成本"""
            },
        ]

        # 工时成本库 category="cost"
        costs = [
            {
                "title": "车削工时与机时费率",
                "content": """车削工时与成本估算：
- 普通车床机时费率：30-60元/小时
- 数控车床机时费率：60-120元/小时
- 单件工时 = 切削时间 + 辅助时间(装夹/对刀/测量) + 准备分摊
- 切削时间(车外圆) ≈ 加工长度 ÷ (转速 × 进给)
用途：报价中机加工费 = 工时 × 机时费率，是单价主要构成"""
            },
            {
                "title": "铣削工时与机时费率",
                "content": """铣削工时与成本估算：
- 普通铣床机时费率：40-70元/小时
- 加工中心机时费率：80-150元/小时
- 工时 = 各工序铣削时间之和 + 换刀/定位辅助时间
- 复杂型腔/多面加工辅助时间占比高，需计入装夹次数
用途：估算铣削/加工中心工序费用，复杂件需按特征逐项累加"""
            },
            {
                "title": "加工成本构成",
                "content": """单件机加工成本构成：
1. 材料费 = 毛坯重量 × 材料单价（计入损耗5-10%）
2. 机加工费 = Σ(各工序工时 × 机时费率)
3. 刀具分摊费 = 刀具/刀片单价 ÷ 单刀可加工件数
4. 编程与调试分摊费（小批量占比高）
5. 检验费、表面处理/热处理外协费
6. 管理费与利润（按总成本一定比例）
用途：报价Agent按此结构逐项汇总得出单件价格"""
            },
            {
                "title": "材料费计算方法",
                "content": """材料费计算：
- 毛坯重量(kg) = 体积(cm³) × 密度(g/cm³) ÷ 1000
- 棒料体积 ≈ π × (D/2)² × L，含切断与夹持余量
- 材料费 = 毛坯重量 × 材料单价 × (1 + 损耗率)
- 损耗率：车削件5-15%（切屑），可回收料按废料价折抵
常用密度：钢7.85、铝2.7、铜8.9、钛4.5 g/cm³
用途：报价中材料费项与余量评估"""
            },
            {
                "title": "编程与调试费分摊",
                "content": """数控编程与首件调试费：
- 简单件编程：0.5-2小时；复杂件：2-8小时
- 首件试切与对刀调试：0.5-2小时
- 该费用一次性发生，按批量分摊：单件分摊 = 编程调试总费 ÷ 批量
特点：小批量单件成本高、大批量趋近于零
用途：报价时区分单件/小批量/大批量，体现批量经济性"""
            },
            {
                "title": "表面处理与热处理外协费",
                "content": """常见表面/热处理外协费（参考，按重量或面积计）：
- 调质处理：2-5元/kg
- 淬火+回火：3-8元/kg
- 镀锌/发黑：按表面积，5-20元/件起
- 阳极氧化（铝）：按面积，10-40元/件起
- 喷砂/抛光：按工时或件数计
用途：含表面处理要求的零件报价需计入外协费与运输周期"""
            },
            {
                "title": "批量与单价折扣关系",
                "content": """批量对单价的影响：
- 小批量(1-10件)：编程/调试/装夹分摊高，单价偏高
- 中批量(10-100件)：分摊下降，单价趋稳
- 大批量(>100件)：可优化夹具/工艺，单价最低
经验：批量翻倍，固定费用分摊约减半，单价随之下降
用途：报价Agent按批量档位给出阶梯价"""
            },
            {
                "title": "检验工时与质量成本",
                "content": """检验工时与质量成本：
- 首件全尺寸检验：0.3-1小时
- 过程抽检：每批按比例抽检（如AQL），计入工时
- 高精度/形位公差项需三坐标(CMM)，机时费80-200元/小时
- 关键件100%全检，普通件按抽检比例
用途：高精度零件报价需计入检验工时与计量设备费用"""
            },
        ]

        # 汇总并按 title 去重写入（已存在标题不重复添加）
        all_items = (
            [("material", x) for x in materials]
            + [("process", x) for x in processes]
            + [("tool", x) for x in tools]
            + [("standard", x) for x in standards]
            + [("cost", x) for x in costs]
        )

        existing = self._existing_titles()
        added = 0
        skipped = 0
        for category, item in all_items:
            if item["title"] in existing:
                skipped += 1
                continue
            if self.add_document(item["content"], category, item["title"]):
                existing.add(item["title"])
                added += 1

        print(
            f"[知识库] 默认知识初始化完成：新增 {added} 条，已存在跳过 {skipped} 条，"
            f"当前共 {collection.count()} 条"
        )
    
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
