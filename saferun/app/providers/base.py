from abc import ABC, abstractmethod
from typing import Dict, Any

class Provider(ABC):
    @abstractmethod
    async def get_metadata(self, target_id: str, token: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def get_children_count(self, target_id: str, token: str) -> int:
        pass

    @abstractmethod
    async def archive(self, target_id: str, token: str) -> None:
        pass

    @abstractmethod
    async def unarchive(self, target_id: str, token: str) -> None:
        pass
