"""BM25 + Dense 混合检索 (RRF 融合) 测试。

用假的 collection / embedding model，不依赖真实 ChromaDB 与向量模型，但**真实**
驱动 rank_bm25 + jieba 的词法检索核心路径（两者已声明于 requirements.txt）。
"""
import pytest

from app.services import knowledge_service as ks_module
from app.services.knowledge_service import KnowledgeService


class _FakeEmbedding(list):
    def tolist(self):
        return list(self)


class _FakeModel:
    def encode(self, text):
        return _FakeEmbedding([0.1, 0.2, 0.3])


class _FakeCollection:
    """docs: list of (id, content, category)。dense 按列表顺序给递增 distance（越前越相关）。"""

    def __init__(self, docs=None):
        self._docs = list(docs or [])

    def count(self):
        return len(self._docs)

    def upsert(self, ids, embeddings, documents, metadatas):
        for i, did in enumerate(ids):
            self._docs = [d for d in self._docs if d[0] != did]  # 幂等覆盖
            self._docs.append((did, documents[i], metadatas[i]["category"]))

    def get(self, ids=None, include=None):
        sel = [d for d in self._docs if ids is None or d[0] in ids]
        return {
            "ids": [d[0] for d in sel],
            "documents": [d[1] for d in sel],
            "metadatas": [{"category": d[2], "title": d[0]} for d in sel],
        }

    def query(self, query_embeddings, n_results, where=None, include=None):
        sel = self._docs
        if where:
            cat = where.get("category")
            sel = [d for d in sel if d[2] == cat]
        sel = sel[:n_results]
        return {
            "ids": [[d[0] for d in sel]],
            "documents": [[d[1] for d in sel]],
            "metadatas": [[{"category": d[2], "title": d[0]} for d in sel]],
            "distances": [[0.1 * (i + 1) for i in range(len(sel))]],
        }


def _patch(monkeypatch, collection):
    monkeypatch.setattr(ks_module, "get_collection", lambda: collection)
    monkeypatch.setattr(ks_module, "get_embedding_model", lambda: _FakeModel())


def _seed(ks, docs):
    """直接把语料置成与集合一致（count==len → _ensure_bm25_corpus 视为已对齐）。"""
    ks._bm25_corpus = [d[1] for d in docs]
    ks._bm25_ids = [d[0] for d in docs]
    ks._bm25_cats = [d[2] for d in docs]
    ks._bm25_dirty = True


# --- 基础：降级与语料维护 -------------------------------------------------

def test_degrade_to_dense_when_corpus_empty(monkeypatch):
    """语料为空 (知识库未初始化) 时安全降级为纯 dense，不报错。"""
    _patch(monkeypatch, _FakeCollection([]))  # count()==0
    ks = KnowledgeService()
    assert ks.hybrid_search("CNMG120408") == []
    assert ks.search("CNMG120408") == []


def test_add_document_maintains_corpus_and_deterministic_id(monkeypatch):
    """add_document 维护平行语料、按 doc_id 去重，且 doc_id 由内容确定（跨调用稳定）。"""
    coll = _FakeCollection([])
    _patch(monkeypatch, coll)
    ks = KnowledgeService()

    assert ks.add_document("GH4169 高温合金", "material", "GH4169") is True
    assert ks._bm25_corpus == ["GH4169 高温合金"]
    assert ks._bm25_cats == ["material"]
    first_id = ks._bm25_ids[0]
    # doc_id 确定性：由内容 md5 派生，不含进程随机化
    assert first_id.startswith("material_")

    # 再次添加同内容同分类 → doc_id 相同 → 去重，不重复入库
    ks.add_document("GH4169 高温合金", "material", "GH4169")
    assert len(ks._bm25_ids) == 1
    assert ks._bm25_ids[0] == first_id


# --- 缓存：BM25 索引不在热路径上每次重建 ----------------------------------

def test_bm25_index_is_cached_and_invalidated_on_add(monkeypatch):
    """_build_bm25 复用缓存；新增文档置脏后才重建。"""
    coll = _FakeCollection([])
    _patch(monkeypatch, coll)
    ks = KnowledgeService()
    ks.add_document("刀片 CNMG120408 钢件车削", "tool", "CNMG120408")

    idx1 = ks._build_bm25()
    assert idx1 is not None
    assert ks._bm25_dirty is False
    # 语料未变 → 复用同一对象
    assert ks._build_bm25() is idx1
    # 新增文档 → 置脏 → 重建为新对象
    ks.add_document("GH4169 高温合金", "material", "GH4169")
    assert ks._bm25_dirty is True
    idx2 = ks._build_bm25()
    assert idx2 is not idx1


# --- 漂移：跨进程 add 后 search 的语料回填 ---------------------------------

def test_ensure_corpus_resyncs_on_drift(monkeypatch):
    """本地语料数与集合不一致时，以集合为准整体回填，杜绝 BM25 与向量库漂移。"""
    docs = [
        ("material_A", "GH4169 高温合金", "material"),
        ("tool_C", "刀片 CNMG120408", "tool"),
    ]
    _patch(monkeypatch, _FakeCollection(docs))
    ks = KnowledgeService()
    # 冷启动：本地语料为空，集合已有 2 篇
    ks._ensure_bm25_corpus()
    assert ks._bm25_ids == ["material_A", "tool_C"]
    assert ks._bm25_cats == ["material", "tool"]
    assert ks._bm25_dirty is True


# --- 核心：RRF 融合 + 零分剔除 + relevance 不变式 -------------------------

def test_hybrid_rrf_lifts_lexical_exact_match_and_excludes_zero_score(monkeypatch):
    """词法精确命中的文档经 RRF 被抬到纯 dense 之上；且零分文档不污染 RRF。

    纯 dense 顺序: A > B > C（C 最差）；查询只在词法上命中 C。
    - 若零分文档被纳入 BM25 排名（旧 bug），A 会因额外的 BM25 名次反超 C → A 排第一；
    - 正确实现只让 C 获得 BM25 贡献 → C 排第一。
    """
    docs = [
        ("material_A", "45号钢调质处理", "material"),
        ("standard_B", "表面粗糙度 Ra1.6 选用", "standard"),
        ("tool_C", "刀片 CNMG120408 钢件外圆车削", "tool"),
    ]
    _patch(monkeypatch, _FakeCollection(docs))
    ks = KnowledgeService()
    _seed(ks, docs)

    # 纯 dense：C 排最后
    dense = ks._dense_search("CNMG120408", top_k=3)
    assert [r["metadata"]["title"] for r in dense][-1] == "tool_C"

    # 混合：C 被 BM25 抬到第一（证明零分的 A/B 没有获得 BM25 名次）
    hybrid = ks.hybrid_search("CNMG120408", top_k=3)
    titles = [r["metadata"]["title"] for r in hybrid]
    assert titles[0] == "tool_C"

    # rrf_score 单调不增
    scores = [r["rrf_score"] for r in hybrid]
    assert scores == sorted(scores, reverse=True)

    # relevance 不变式：一律 == 1 - distance/2，无魔数 0.6
    for r in hybrid:
        assert abs(r["relevance"] - (1 - r["distance"] / 2)) < 1e-9
        assert r["relevance"] != 0.6


def test_hybrid_respects_category_filter(monkeypatch):
    """指定 category 时，BM25 与 dense 两路都只在该分类内检索。"""
    docs = [
        ("material_A", "GH4169 高温合金材料参数", "material"),
        ("tool_C", "刀片 GH4169 涂层", "tool"),
    ]
    _patch(monkeypatch, _FakeCollection(docs))
    ks = KnowledgeService()
    _seed(ks, docs)

    res = ks.hybrid_search("GH4169", category="material", top_k=5)
    assert {r["metadata"]["title"] for r in res} == {"material_A"}
