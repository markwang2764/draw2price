"""Knowledge retrieval wrapper."""
from typing import Any, Dict, List, Optional

from app.services.knowledge_service import knowledge_service


class KnowledgeRetriever:
    def retrieve(self, query: str, category: Optional[str] = None, top_k: int = 5) -> List[Dict[str, Any]]:
        return knowledge_service.search(query=query, category=category, top_k=top_k)
