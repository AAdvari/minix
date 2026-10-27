from typing import ClassVar, List

from pgvector.sqlalchemy import VECTOR
from sqlalchemy.orm import Mapped, mapped_column, declared_attr

from minix.core.entity import SqlEntity


class PGVectorEntity(SqlEntity):
    """SQL entity stored in PostgreSQL with a pgvector ``vector`` column.

    Subclasses set ``vector_size`` to the embedding dimension; it becomes the
    column type ``VECTOR(<vector_size>)``. ``None`` leaves the dimension
    unbounded, which pgvector accepts but cannot index.
    """
    __abstract__ = True

    vector_size: ClassVar[int | None] = None

    @declared_attr
    def vector(cls) -> Mapped[List[float]]:
        return mapped_column(VECTOR(cls.vector_size), nullable=False)
