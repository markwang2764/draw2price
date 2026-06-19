"""
知识库扩展脚本 - 大规模专业知识导入
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.knowledge_service import knowledge_service
from scripts.knowledge_data import (
    MATERIAL_KNOWLEDGE,
    TOOL_KNOWLEDGE_EXT,
    PROCESS_ROUTE_EXT,
    COST_KNOWLEDGE_EXT,
    FEATURE_KNOWLEDGE_EXT,
    STANDARD_KNOWLEDGE
)


def init_extended_knowledge():
    """初始化扩展知识库"""
    print("=" * 50)
    print("开始导入扩展知识库...")
    print("=" * 50)
    
    total_added = 0
    
    # 1. 材料知识库
    print("\n[1/6] 导入材料知识库...")
    for item in MATERIAL_KNOWLEDGE:
        success = knowledge_service.add_document(
            content=item["content"],
            category="material",
            title=item["title"]
        )
        if success:
            total_added += 1
            print(f"  ✓ {item['title']}")
    
    # 2. 刀具知识库扩展
    print("\n[2/6] 导入刀具知识库扩展...")
    for item in TOOL_KNOWLEDGE_EXT:
        success = knowledge_service.add_document(
            content=item["content"],
            category="tool",
            title=item["title"]
        )
        if success:
            total_added += 1
            print(f"  ✓ {item['title']}")
    
    # 3. 工艺路线库扩展
    print("\n[3/6] 导入工艺路线库扩展...")
    for item in PROCESS_ROUTE_EXT:
        success = knowledge_service.add_document(
            content=item["content"],
            category="process_route",
            title=item["title"]
        )
        if success:
            total_added += 1
            print(f"  ✓ {item['title']}")
    
    # 4. 工时成本库扩展
    print("\n[4/6] 导入工时成本库扩展...")
    for item in COST_KNOWLEDGE_EXT:
        success = knowledge_service.add_document(
            content=item["content"],
            category="cost",
            title=item["title"]
        )
        if success:
            total_added += 1
            print(f"  ✓ {item['title']}")
    
    # 5. 特征信息库扩展
    print("\n[5/6] 导入特征信息库扩展...")
    for item in FEATURE_KNOWLEDGE_EXT:
        success = knowledge_service.add_document(
            content=item["content"],
            category="feature",
            title=item["title"]
        )
        if success:
            total_added += 1
            print(f"  ✓ {item['title']}")
    
    # 6. 标准规范库
    print("\n[6/6] 导入标准规范库...")
    for item in STANDARD_KNOWLEDGE:
        success = knowledge_service.add_document(
            content=item["content"],
            category="standard",
            title=item["title"]
        )
        if success:
            total_added += 1
            print(f"  ✓ {item['title']}")
    
    # 完成
    print("\n" + "=" * 50)
    print(f"扩展知识库导入完成！本次添加 {total_added} 条知识")
    print("=" * 50)
    
    # 显示统计
    stats = knowledge_service.get_stats()
    print(f"\n当前知识库状态：")
    print(f"  总条目数：{stats.get('count', 0)}")
    print(f"  分类：{list(stats.get('categories', {}).keys())}")


if __name__ == "__main__":
    init_extended_knowledge()
