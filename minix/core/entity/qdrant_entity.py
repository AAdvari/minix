from abc import abstractmethod
from datetime import datetime
from typing import List, Dict, Any

from pydantic import BaseModel
from minix.core.entity import Entity


class QdrantEntity(Entity, BaseModel):
    id: str
    created_at: datetime
    vector: List[float]



    @property
    def payload(self) -> Dict[str, Any]:
        return vars(self)

    @staticmethod
    @abstractmethod
    def collection()-> str:
        """
        Returns the name of the Qdrant collection this entity belongs to.
        """
        pass
