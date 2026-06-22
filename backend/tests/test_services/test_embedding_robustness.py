"""回归：嵌入维度一致性(bug#1) + cosine 距离/relevance(bug#2)。

bug#1: 默认模型(bge-large-zh,1024维)离线不可用 + 兜底嵌入(256维) + 持久化集合(384维)
       三方维度打架，导致写入/检索全部 "Collection expecting embedding with dimension of X, got Y"。
bug#2: 集合建库时漏设 hnsw:space，chroma 默认 L2 距离，使 relevance=1-distance/2 出现负值，
       并让 get_context_for_query 的 relevance<0.3 过滤误删全部结果。
"""
import app.services.knowledge_service as ks


# ── bug#2: relevance 钳制，绝不为负 ──────────────────────────────────────────────
def test_relevance_clamped_non_negative():
    f = ks._relevance_from_distance
    assert f(0.0) == 1.0          # 完全相同
    assert f(2.0) == 0.0          # 余弦最远
    assert f(1.0) == 0.5          # 正交
    assert f(12.0) == 0.0         # L2 大距离也不返回负值（防御）
    assert f(-0.001) == 1.0       # 浮点误差
    assert f(None) == 0.0         # 异常输入不崩


# ── bug#2: 集合声明 cosine 空间 ─────────────────────────────────────────────────
def test_collection_uses_cosine_space():
    assert ks.EMBEDDING_SPACE == "cosine"
    assert ks._COLLECTION_METADATA.get("hnsw:space") == "cosine"


# ── bug#1: 激活维度跟随已有集合，避免维度漂移 ───────────────────────────────────
def test_active_embedding_dim_follows_existing_collection(monkeypatch):
    # 模型未加载（_embedding_dim 为 None）且集合已有 384 维数据 → 兜底应取 384，而非默认 256
    monkeypatch.setattr(ks, "_embedding_dim", None)
    monkeypatch.setattr(ks, "_existing_collection_dim", lambda: 384)
    assert ks._active_embedding_dim() == 384

    # 模型已加载 → 用模型维度
    monkeypatch.setattr(ks, "_embedding_dim", 1024)
    assert ks._active_embedding_dim() == 1024

    # 全新空库 + 无模型 → 兜底默认维度
    monkeypatch.setattr(ks, "_embedding_dim", None)
    monkeypatch.setattr(ks, "_existing_collection_dim", lambda: None)
    assert ks._active_embedding_dim() == ks.FALLBACK_EMBEDDING_DIM


# ── bug#1: 兜底嵌入维度可指定，与集合一致 ───────────────────────────────────────
def test_fallback_embedding_respects_dim():
    assert len(ks._fallback_embedding("GH4169 切削速度", dim=384)) == 384
    assert len(ks._fallback_embedding("TC4 钛合金", dim=256)) == 256


# ── bug#1: 模型加载失败时回退到本地缓存快照（不抛异常，返回 None 或模型）─────────
def test_cached_model_snapshots_returns_list():
    # 仅验证扫描函数健壮：返回 list，且每项都是完整快照目录（有 config.json + 权重）
    snaps = ks._cached_model_snapshots()
    assert isinstance(snaps, list)
    for s in snaps:
        assert (s / "config.json").exists()
        assert (s / "model.safetensors").exists() or (s / "pytorch_model.bin").exists()
