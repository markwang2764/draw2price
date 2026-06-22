"""独立验收测试：BM25 + Dense 混合检索 (RRF 融合)。

与实现者分离的「出题人」测试，逐条覆盖大白话验收标准 1~5。

设计要点（保证测试是真的在考实现，而不是空跑）:
- 真用 rank_bm25 做词法检索（验收 1 的前提；缺失则该项直接 FAIL）。
- get_collection / get_embedding_model 用确定性假件替换，不连真实 ChromaDB / 向量模型，
  贴合现有 test_hybrid_search.py 的「不连库」风格。
- 假的向量模型 _SemanticModel 故意对“词法精确 token”(刀片型号 CNMG120408、材料牌号
  GH4169、公差串 H7/IT7、GB 标准号) 视而不见——只认语义概念词。这正是本特性要解决的
  痛点：dense 区分不开这些精确 token，必须靠 BM25 兜底。于是：
    * 验收 2(GH4169 词法精确匹配) 真正考的是 BM25 的贡献，纯 dense 实现会露馅；
    * 验收 3(精密配合孔→铰孔/镗孔) 真正考的是 dense 语义召回。
"""
import inspect
from typing import List, Optional

import pytest

from app.services import knowledge_service as ks_module
from app.services.knowledge_service import KnowledgeService


# --- 验收 1：rank_bm25 必须可用，否则整个特性无从谈起 ----------------------------
def test_acc1_rank_bm25_importable():
    """验收1：pip install rank-bm25 后 import 不报错。"""
    bm = pytest.importorskip("rank_bm25")
    assert hasattr(bm, "BM25Okapi")


# --- 确定性假件：语义向量模型 + ChromaDB 集合 ------------------------------------
# 只认“语义概念词”，刻意不含任何零件号/牌号/公差串/标准号 —— 模拟 dense 对精确 token 失能。
_VOCAB = [
    "切削速度", "高温合金", "难加工", "调质", "车削", "钢", "外圆",
    "孔", "铰孔", "镗孔", "钻孔", "高精度", "精密", "配合", "公差",
    "刀片", "轴类", "磨削", "参数",
]


def _vec(text: str) -> List[float]:
    return [1.0 if term in text else 0.0 for term in _VOCAB]


def _cos(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class _FakeEmbedding(list):
    def tolist(self):
        return list(self)


class _SemanticModel:
    def encode(self, text):
        return _FakeEmbedding(_vec(text))


class _SemanticCollection:
    """假 ChromaDB 集合：dense 查询按语义概念词的余弦相似度排序。

    docs: list[(id, content, category)]。dense 距离 = 1 - cos（越相关越小）。
    """

    def __init__(self, docs):
        self._docs = list(docs)

    def count(self):
        return len(self._docs)

    def get(self, ids=None, include=None):
        sel = [d for d in self._docs if ids is None or d[0] in ids]
        return {
            "ids": [d[0] for d in sel],
            "documents": [d[1] for d in sel],
            "metadatas": [{"category": d[2], "title": d[0]} for d in sel],
        }

    def query(self, query_embeddings, n_results, where=None, include=None):
        qv = query_embeddings[0]
        sel = self._docs
        if where:
            cat = where.get("category")
            sel = [d for d in sel if d[2] == cat]
        # 按 (-相似度, id) 稳定排序，确定性可复现
        ranked = sorted(sel, key=lambda d: (-_cos(qv, _vec(d[1])), d[0]))[:n_results]
        return {
            "ids": [[d[0] for d in ranked]],
            "documents": [[d[1] for d in ranked]],
            "metadatas": [[{"category": d[2], "title": d[0]} for d in ranked]],
            "distances": [[1.0 - _cos(qv, _vec(d[1])) for d in ranked]],
        }


# 语料：镜像默认知识库的关键条目（含精确 token：GH4169 / CNMG120408 / IT7 / H7 / GB/T 1804）
_DOCS = [
    ("material_gh4169", "GH4169 高温合金 切削速度 推荐参数 属于难加工材料", "material"),
    ("material_45", "45号钢 调质处理 切削速度 车削 钢件参数", "material"),
    ("process_hole", "孔加工工艺 铰孔 适用于高精度孔 IT7 H7 配合 镗孔 精密", "process"),
    ("process_shaft", "轴类零件加工 粗车 精车 磨削 钻孔", "process"),
    ("standard_gb", "GB/T 1804 一般公差 等级 未注公差", "standard"),
    ("tool_cnmg", "刀片 CNMG120408 外圆 车削 钢件", "tool"),
]


def _make_service(monkeypatch, docs=_DOCS):
    coll = _SemanticCollection(docs)
    monkeypatch.setattr(ks_module, "get_collection", lambda: coll)
    monkeypatch.setattr(ks_module, "get_embedding_model", lambda: _SemanticModel())
    ks = KnowledgeService()
    # 平行装载 BM25 语料（等价于 add_document 累积的结果），保持 docs/ids/cats 同序
    ks._bm25_corpus = [d[1] for d in docs]
    ks._bm25_ids = [d[0] for d in docs]
    ks._bm25_cats = [d[2] for d in docs]
    return ks, coll


# --- 验收 2：词法精确匹配（BM25 兜底） -------------------------------------------
def test_acc2_lexical_exact_match_returns_gh4169(monkeypatch):
    """验收2：search('GH4169 切削速度') 结果含 'GH4169'。

    dense 模型对 'GH4169' token 失能（不在概念词表里），所以这一条真正考的是 BM25。
    """
    pytest.importorskip("rank_bm25")
    ks, _ = _make_service(monkeypatch)
    res = ks.search("GH4169 切削速度")
    assert res, "应返回非空结果"
    contents = [r["content"] for r in res]
    assert any("GH4169" in c for c in contents), f"结果未命中 GH4169: {contents}"


def test_acc2_bm25_is_what_distinguishes_exact_token(monkeypatch):
    """验收2 加强：纯 dense 实现会失败的判别。

    两条仅型号不同、语义向量完全相同的刀片文档，dense 无法区分；
    查询精确型号 CNMG120408 时，只有 BM25 能把对应文档顶上来。
    """
    pytest.importorskip("rank_bm25")
    docs = [
        ("tool_08", "刀片 CNMG120408 外圆 车削 钢件", "tool"),
        ("tool_12", "刀片 CNMG120412 外圆 车削 钢件", "tool"),
    ]
    ks, _ = _make_service(monkeypatch, docs)
    # 证明 dense 确实分不开：两文档语义向量相同
    assert _vec(docs[0][1]) == _vec(docs[1][1])
    res = ks.search("CNMG120408", top_k=2)
    assert res
    # 词法精确命中的文档排第一，且确为 408 而非 412
    assert res[0]["metadata"]["title"] == "tool_08"
    assert "CNMG120408" in res[0]["content"]


# --- 验收 3：语义匹配（dense 召回） ---------------------------------------------
def test_acc3_semantic_match_returns_reaming_boring(monkeypatch):
    """验收3：search('精密配合孔 IT7') 返回铰孔/镗孔相关结果（语义匹配）。"""
    pytest.importorskip("rank_bm25")
    ks, _ = _make_service(monkeypatch)
    res = ks.search("精密配合孔 IT7")
    assert res, "应返回非空结果"
    joined = " ".join(r["content"] for r in res)
    assert ("铰孔" in joined) or ("镗孔" in joined), f"未召回铰孔/镗孔相关内容: {joined}"
    # 该语义命中的文档应在结果中且相关度过得下游 0.3 阈值
    hole = next((r for r in res if r["metadata"]["title"] == "process_hole"), None)
    assert hole is not None
    assert hole["relevance"] > 0.3

    # get_context_for_query 不改、仍走 search，应能取到该上下文
    ctx = ks.get_context_for_query("精密配合孔 IT7")
    assert ("铰孔" in ctx) or ("镗孔" in ctx)


# --- 验收 4：接口签名与返回结构不变 ---------------------------------------------
def test_acc4_signature_unchanged(monkeypatch):
    """验收4：search() 签名 (query, category=None, top_k=5) 不变。"""
    sig = inspect.signature(KnowledgeService.search)
    params = list(sig.parameters.values())
    names = [p.name for p in params]
    assert names == ["self", "query", "category", "top_k"]
    assert sig.parameters["category"].default is None
    assert sig.parameters["top_k"].default == 5


def test_acc4_result_structure_unchanged(monkeypatch):
    """验收4：result[i] 含 content/metadata/distance/relevance 字段，类型正确。"""
    pytest.importorskip("rank_bm25")
    ks, _ = _make_service(monkeypatch)
    res = ks.search("精密配合孔 IT7", top_k=5)
    assert res
    for r in res:
        for key in ("content", "metadata", "distance", "relevance"):
            assert key in r, f"缺字段 {key}: {r.keys()}"
        assert isinstance(r["content"], str)
        assert isinstance(r["metadata"], dict)
        assert isinstance(r["distance"], (int, float))
        assert isinstance(r["relevance"], (int, float))
        # relevance 与 distance 关系与改前一致：relevance == 1 - distance/2
        assert abs(r["relevance"] - (1 - r["distance"] / 2)) < 1e-9

    # 结构应与「改前」纯 dense 路径的字段集一致（hybrid 仅可附加字段，不可缺字段）
    dense = ks._dense_search("精密配合孔 IT7", top_k=5)
    dense_keys = set(dense[0].keys())
    assert dense_keys.issubset(set(res[0].keys()))


def test_acc4_search_delegates_to_hybrid(monkeypatch):
    """验收4：search() 内部改调 hybrid_search()，对外行为一致。"""
    pytest.importorskip("rank_bm25")
    ks, _ = _make_service(monkeypatch)
    a = ks.search("GH4169 切削速度", top_k=3)
    b = ks.hybrid_search("GH4169 切削速度", top_k=3)
    assert [r["metadata"]["title"] for r in a] == [r["metadata"]["title"] for r in b]


def test_acc4_category_filter_param_works(monkeypatch):
    """验收4：category 形参仍生效（两路检索都限定在该分类内）。"""
    pytest.importorskip("rank_bm25")
    ks, _ = _make_service(monkeypatch)
    res = ks.search("GH4169", category="material", top_k=5)
    cats = {r["metadata"]["category"] for r in res}
    assert cats <= {"material"}, f"越界返回非 material 分类: {cats}"


# --- 验收 5：知识库为空安全降级 -------------------------------------------------
def test_acc5_empty_kb_returns_empty_no_error(monkeypatch):
    """验收5：知识库为空时 search() 返回空列表且不报错。"""
    coll = _SemanticCollection([])  # count()==0
    monkeypatch.setattr(ks_module, "get_collection", lambda: coll)
    monkeypatch.setattr(ks_module, "get_embedding_model", lambda: _SemanticModel())
    ks = KnowledgeService()
    assert ks.search("CNMG120408") == []
    assert ks.hybrid_search("任意查询") == []
