"""知识库数据模块"""
from .materials import MATERIAL_KNOWLEDGE
from .tools_ext import TOOL_KNOWLEDGE_EXT
from .process_ext import PROCESS_ROUTE_EXT
from .cost_ext import COST_KNOWLEDGE_EXT
from .features_ext import FEATURE_KNOWLEDGE_EXT
from .standards import STANDARD_KNOWLEDGE

__all__ = [
    'MATERIAL_KNOWLEDGE',
    'TOOL_KNOWLEDGE_EXT', 
    'PROCESS_ROUTE_EXT',
    'COST_KNOWLEDGE_EXT',
    'FEATURE_KNOWLEDGE_EXT',
    'STANDARD_KNOWLEDGE'
]
