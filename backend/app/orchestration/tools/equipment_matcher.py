"""Equipment matching helper."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


class EquipmentMatcher:
    def __init__(self, equipment: Iterable[Dict[str, Any]]):
        self._equipment = list(equipment)

    def match(self, equipment_type: Optional[str]) -> Optional[Dict[str, Any]]:
        if not equipment_type:
            return None
        available = [eq for eq in self._equipment if eq.get("status") in {None, "available"}]
        for eq in available:
            if eq.get("type") == equipment_type:
                return eq
        for eq in available:
            if equipment_type in str(eq.get("type", "")):
                return eq
        return available[0] if available else (self._equipment[0] if self._equipment else None)
