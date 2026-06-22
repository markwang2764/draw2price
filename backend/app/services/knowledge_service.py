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
_collection = None

KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "knowledge_base"
CHROMA_DIR = KNOWLEDGE_DIR / "chroma_db"

# 离线兜底嵌入维度（与语义模型无关，仅在模型不可用时使用，必须全库一致）
FALLBACK_EMBEDDING_DIM = 256


def _stable_hash(s: str) -> int:
    """跨进程稳定的哈希（内置 hash() 会受 PYTHONHASHSEED 随机化，不能用于持久化场景）"""
    return int(hashlib.md5(s.encode("utf-8")).hexdigest(), 16)


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


def get_embedding_model():
    """获取嵌入模型（延迟加载，使用国内镜像）"""
    global _embedding_model, _embedding_model_failed
    # 之前已加载失败（如离线/无缓存）则不再重试，直接返回 None 交由调用方走兜底嵌入，
    # 避免批量写入时每条都重复联网超时。
    if _embedding_model_failed:
        return None
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
            print(f"[知识库] 嵌入模型加载失败: {e}（后续将使用离线兜底嵌入）")
            _embedding_model_failed = True
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
    
    def _encode(self, text: str) -> List[float]:
        """文本向量化：优先用语义模型，模型不可用时回退到离线兜底嵌入。
        返回值始终是非空向量，保证写入/检索在离线环境下也不会整体失败。"""
        model = get_embedding_model()
        if model is not None:
            try:
                return model.encode(text).tolist()
            except Exception as e:
                print(f"[知识库] 模型编码失败，改用离线兜底嵌入: {e}")
        return _fallback_embedding(text)

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
