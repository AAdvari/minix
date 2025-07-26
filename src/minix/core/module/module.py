from abc import ABC
from typing import Self, Type, List, Tuple, Dict

from minix.core.consumer import AsyncConsumer
from minix.core.controller import Controller
from minix.core.entity import Entity
from minix.core.install import Installable
from minix.core.model import Model
from minix.core.repository import Repository
from minix.core.scheduler.task import PeriodicTask, Task
from minix.core.service import Service


class Module(Installable, ABC):


    def __init__(self, name: str):
        self.name = name
        self.entities: List[Type[Entity]] = []
        self.services: List[Type[Service]] = []
        self.repositories: List[Tuple[Type[Repository], str | None]] = []
        self.periodic_tasks : List[Type[PeriodicTask]] = []
        self.tasks: List[Type[Task]] = []
        self.controllers: List[Type[Controller]] = []
        self.models: List[Tuple[Type[Model], Dict]] = []
        self.consumers: List[Type[AsyncConsumer]] = []

    def add_entity(self, entity: Type[Entity])-> Self:
        self.entities.append(entity)
        return self

    def add_periodic_task(self, periodic_task: Type[PeriodicTask])-> Self:
        self.periodic_tasks.append(periodic_task)
        return self

    def add_service(self, service: Type[Service])-> Self:
        self.services.append(service)
        return self

    def add_repository(self, repository: Type[Repository], connector_salt: str | None = None)-> Self:
        self.repositories.append((repository, connector_salt))
        return self


    def add_task(self, task: Type[Task])-> Self:
        self.tasks.append(task)
        return self

    def add_controller(self, controller: Type[Controller])-> Self:
        self.controllers.append(controller)
        return self

    def add_model(self, model: Type[Model], config: Dict)-> Self:
        self.models.append((model, config))
        return self


    def add_consumer(self, consumer: Type[AsyncConsumer]):
        self.consumers.append(consumer)
        return self


    def exclude_all_consumers(self)-> Self:
        self.consumers = []
        return self

    def exclude_all_controllers(self)-> Self:
        self.controllers = []
        return self










