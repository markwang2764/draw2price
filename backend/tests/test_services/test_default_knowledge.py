"""验收测试：init_default_knowledge() 扩充到 40+ 条，category 统一规范。

出题人独立测试，对照大白话验收标准逐条断言：
1. init 后 get_stats()['count'] >= 40
2. search("TC4 切削速度") 命中 "40-80" 或 "钛合金"
3. search("GH4169 难加工合金") 命中 "20-40" 或 "高温合金"
4. search("深孔钻 L/D") 命中深孔钻工艺条目
5. search("H7/g6 配合") 命中公差配合条目
6. 所有条目 category ∈ {material, process, standard, tool, cost}

为保证可复现、不被既有 chroma_db 历史数据污染，测试在临时目录里
新建一个隔离的 ChromaDB，再跑真实的 init_default_knowledge()。
"""
from __future__ import annotations

import pytest

import app.services.knowledge_service as ks_mod
from app.services.knowledge_service import KnowledgeService

ALLOWED_CATEGORIES = {"material", "process", "standard", "tool", "cost"}


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    """在隔离临时目录构建全新知识库，跑一次 init，供本模块所有断言复用。"""
    tmp = tmp_path_factory.mktemp("kb_chroma")

    # 重定向 ChromaDB 持久化目录到临时路径，并清空模块级缓存的 client/collection，
    # 保证拿到的是干净的全新集合（不读既有 knowledge_base/chroma_db）。
    ks_mod.CHROMA_DIR = tmp / "chroma_db"
    ks_mod._chroma_client = None
    ks_mod._collection = None

    svc = KnowledgeService()
    col = ks_mod.get_collection()
    assert col is not None, "ChromaDB 集合创建失败，无法运行验收测试"
    assert col.count() == 0, f"隔离库应为空，实际 {col.count()} 条"

    svc.init_default_knowledge()
    return svc


def _search_hits_any(results, needles):
    """search 结果(top_k 列表)中任一条 content 命中任一关键字即视为命中。"""
    return any(any(n in r["content"] for n in needles) for r in results)


def test_count_at_least_40(service):
    # 验收1
    stats = service.get_stats()
    assert stats["count"] >= 40, f"知识条目不足 40,实际 {stats['count']} 条"


def test_search_tc4(service):
    # 验收2: TC4 极低速核心知识
    results = service.search("TC4 切削速度")
    assert results, "search('TC4 切削速度') 返回空"
    assert _search_hits_any(results, ["40-80", "钛合金"]), \
        f"TC4 检索未命中 '40-80'/'钛合金',返回: {[r['metadata'].get('title') for r in results]}"


def test_search_gh4169(service):
    # 验收3: GH4169 高温合金
    results = service.search("GH4169 难加工合金")
    assert results, "search('GH4169 难加工合金') 返回空"
    assert _search_hits_any(results, ["20-40", "高温合金"]), \
        f"GH4169 检索未命中 '20-40'/'高温合金',返回: {[r['metadata'].get('title') for r in results]}"


def test_search_deep_hole(service):
    # 验收4: 深孔钻 L/D 工艺
    results = service.search("深孔钻 L/D")
    assert results, "search('深孔钻 L/D') 返回空"
    assert _search_hits_any(results, ["深孔", "L/D"]), \
        f"深孔钻检索未命中,返回: {[r['metadata'].get('title') for r in results]}"


def test_search_fit_h7g6(service):
    # 验收5: H7/g6 公差配合
    results = service.search("H7/g6 配合")
    assert results, "search('H7/g6 配合') 返回空"
    assert _search_hits_any(results, ["H7/g6", "配合"]), \
        f"H7/g6 检索未命中,返回: {[r['metadata'].get('title') for r in results]}"


def test_all_categories_in_whitelist(service):
    # 验收6: 所有条目 category 仅限白名单
    items = service.list_all(limit=1000)
    assert items, "list_all 返回空"
    bad = {it["category"] for it in items} - ALLOWED_CATEGORIES
    assert not bad, f"出现非法 category: {bad}"
    # 同时确认 5 个白名单分类都有产出(避免某类整组写空)
    present = {it["category"] for it in items}
    assert ALLOWED_CATEGORIES <= present, f"缺少分类: {ALLOWED_CATEGORIES - present}"
