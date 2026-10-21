# Repository for RAG collection CRUD and stats queries.
from typing import List

from minix.core.repository import SqlRepository
from minix.core.modules.rag.entities.collection_entity import RagCollectionEntity


class RagCollectionRepository(SqlRepository[RagCollectionEntity]):

    def get_by_name(self, name: str) -> RagCollectionEntity | None:
        with self.get_session() as session:
            return session.query(self.entity).filter(
                self.entity.name == name
            ).first()

    def list_all(self) -> List[RagCollectionEntity]:
        with self.get_session() as session:
            return session.query(self.entity).order_by(
                self.entity.created_at.desc()
            ).all()

    def delete_by_name(self, name: str) -> bool:
        with self.get_session() as session:
            row = session.query(self.entity).filter(self.entity.name == name).first()
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True

    def get_chunking_config(self, name: str) -> dict:
        row = self.get_by_name(name)
        if not row:
            return {"strategy": "smart", "chunk_size": 800, "chunk_overlap": 100, "min_chunk_size": 100}
        return row.chunking_config or {"strategy": "smart", "chunk_size": 800, "chunk_overlap": 100, "min_chunk_size": 100}

    def update_chunking_config(self, name: str, chunking_config: dict) -> RagCollectionEntity | None:
        with self.get_session() as session:
            row = session.query(self.entity).filter(self.entity.name == name).first()
            if not row:
                return None
            row.chunking_config = chunking_config
            session.commit()
            session.refresh(row)
            return row
