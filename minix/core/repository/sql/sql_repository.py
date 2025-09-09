from typing import Type, TypeVar, List
from sqlalchemy.orm import Session

from minix.core.entity import SqlEntity
from minix.core.repository import Repository
from minix.core.connectors.sql_connector import SqlConnector


T = TypeVar('T', bound=SqlEntity)
class SqlRepository(Repository[T]):
    def __init__(self, entity: Type[T], sql_connector: SqlConnector):
        super().__init__(entity)
        self.sql_connector = sql_connector
        self.entity = entity

    def get_entity(self)-> Type[T]:
        return self.entity

    def get_session(self)-> Session:
        return self.sql_connector.get_session()

    def save(self, entity: T)-> T:
        with self.get_session() as session:
            session.add(entity)
            session.commit()
            session.refresh(entity)
        return entity


    def get_all(self)-> List[T]:
        with self.get_session() as session:
            result = session.query(self.entity).all()
        return result

    def get_by_id(self, id: int)-> T | None:
        with self.get_session() as session:
            result = session.query(self.entity).filter(self.entity.id == id).first()
        return result

    def delete(self, entity: T):
        with self.get_session() as session:
            session.delete(entity)
            session.commit()

    def update(self, entity: T)-> T:
        with self.get_session() as session:
            res = session.merge(entity)
            session.commit()
        return res

    def get_by(self, **kwargs)-> List[T]:
        with self.get_session() as session:
            result = session.query(self.entity).filter_by(**kwargs).all()
        return result


    def save_all(self, entities: List[T])-> List[T]:
        with self.get_session() as session:
            for entity in entities:
                session.add(entity)
            session.commit()
        return entities
    def save_bulk(self, entities: List[T], chunk_size: int)-> int:
        total = 0
        with self.get_session() as session:
            for i in range(0, len(entities), chunk_size):
                chunk = entities[i: i + chunk_size]
                session.add_all(chunk)
                total += len(chunk)
            session.commit()
        return total
















