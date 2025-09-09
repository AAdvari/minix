from datetime import datetime

from sqlalchemy import Integer, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, MappedAsDataclass
from minix.core.entity import Entity

class Base(DeclarativeBase):
    pass


class SqlEntity(Base, Entity):
    __abstract__ = True
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at : Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), index=True)
    updated_at : Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), index=True)

    def __repr__(self):
        return f'<{self.__class__.__name__} {self.id}>'







