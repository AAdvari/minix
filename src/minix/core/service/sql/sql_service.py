from typing import TypeVar, List

from minix.core.entity import SqlEntity
from minix.core.repository import SqlRepository
from minix.core.service import Service


T = TypeVar('T', bound=SqlEntity)
class SqlService(Service[T]):
    def __init__(self, repository: SqlRepository[T]):
        super().__init__(repository)
        self.repository = repository

    def get_repository(self) -> SqlRepository[T]:
        return self.repository

    def get_entity(self)-> T:
        return self.get_repository().get_entity()

    def save(self, entity: T) -> T:
        return self.get_repository().save(entity)

    def get_all(self)-> List[T]:
        return self.get_repository().get_all()

    def get_by_id(self, id: int)-> T | None:
        return self.get_repository().get_by_id(id)

    def delete(self, entity: T):
        self.get_repository().delete(entity)

    def update(self, entity: T)-> T:
        return self.get_repository().update(entity)

    def get_by(self, **kwargs)-> List[T]:
        return self.get_repository().get_by(**kwargs)



