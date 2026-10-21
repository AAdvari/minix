from datetime import datetime

from sqlalchemy import Integer, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, declared_attr, has_inherited_table
from minix.core.entity import Entity
from minix.core.utils import to_snake_case


class Base(DeclarativeBase):
    pass


class SqlEntity(Base, Entity):
    __abstract__ = True

    def __init_subclass__(cls, **kwargs):
        # A subclass of an already-mapped entity that does not name its own
        # table is a single-table-inheritance extension: it adds columns to the
        # parent's table. Say so explicitly — otherwise declarative would pick
        # up the parent's inherited `__tablename__` (or a generated one) and try
        # to define a second table with the same name.
        if "__tablename__" not in cls.__dict__ and has_inherited_table(cls):
            cls.__tablename__ = None
        super().__init_subclass__(**kwargs)

    @declared_attr.directive
    def __tablename__(cls) -> str:
        parts = cls.__module__.split('.')
        try:
            module_name = parts[parts.index('modules') + 1]
        except (ValueError, IndexError):
            module_name = parts[-1]

        entity_name = cls.__name__.removesuffix('Entity')
        entity_name = to_snake_case(entity_name)
        return f'{module_name}_{entity_name}'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at : Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), server_default=func.now(), index=True)
    updated_at : Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), server_default=func.now(), onupdate=func.now(), index=True)

    def __repr__(self):
        return f'<{self.__class__.__name__} {self.id}>'
