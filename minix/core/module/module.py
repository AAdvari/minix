from abc import ABC
from typing import Self, Type, List, Tuple, Dict
import warnings
from minix.core.consumer import AsyncConsumer
from minix.core.controller import Controller
from minix.core.entity import Entity
from minix.core.install import Installable
from minix.core.model import Model
from minix.core.repository import Repository
from minix.core.scheduler.task import PeriodicTask, Task
from minix.core.service import Service, BaseService, HelperService

_SENTINEL = object()


class Module(Installable, ABC):


    def __init__(self, name: str):
        self.name = name
        self.entities: List[Type[Entity]] = []
        self.services: List[Type[Service]] = []
        self.helper_services: List[Type[BaseService]] = []
        self.repositories: List[Tuple[Type[Repository], str | None]] = []
        self.periodic_tasks : List[Type[PeriodicTask]] = []
        self.tasks: List[Type[Task]] = []
        self.controllers: List[Type[Controller]] = []
        self.models: List[Tuple[Type[Model], Dict]] = []
        self.consumers: List[Type[AsyncConsumer]] = []

    def add_binding(
        self,
        entity: Type[Entity],
        repository: Type[Repository],
        service: Type[Service],
        connection: str | None = None,
        *,
        connector_salt: str | None = _SENTINEL,  # type: ignore[assignment]
    ) -> Self:
        """Register an entity, repository, and service as one binding.

        ``connection`` is the settings connection name (e.g. ``"analytics"``);
        ``"default"`` / ``None`` → no Registry salt.

        ``connector_salt`` is deprecated; prefer ``connection=``. When passed
        it is used as-is (including ``"default"``).
        """
        if connector_salt is not _SENTINEL:
            warnings.warn(
                "add_binding(..., connector_salt=...) is deprecated; "
                "use connection=... instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            salt = connector_salt
        else:
            salt = None if connection in (None, "default") else connection
        self.entities.append(entity)
        self.repositories.append((repository, salt))
        self.services.append(service)
        return self

    def add_entity(self, entity: Type[Entity])-> Self:
        """Register a data entity.

        .. deprecated::
            Prefer :meth:`add_binding` so entity, repository, and service stay paired.
        """
        warnings.warn(
            "add_entity() is deprecated; prefer add_binding(entity, repository, service).",
            DeprecationWarning,
            stacklevel=2,
        )
        self.entities.append(entity)
        return self

    def add_periodic_task(self, periodic_task: Type[PeriodicTask])-> Self:
        self.periodic_tasks.append(periodic_task)
        return self

    def add_service(self, service: Type[Service])-> Self:
        """Register a service.

        .. deprecated::
            Prefer :meth:`add_binding` so entity, repository, and service stay paired.
        """
        warnings.warn(
            "add_service() is deprecated; prefer add_binding(entity, repository, service).",
            DeprecationWarning,
            stacklevel=2,
        )
        self.services.append(service)
        return self

    def add_helper_service(self, service: Type[HelperService])-> Self:
        self.helper_services.append(service)
        return self

    def add_repository(self, repository: Type[Repository], connector_salt: str | None = None)-> Self:
        """Register a repository with an optional connector salt.

        .. deprecated::
            Prefer :meth:`add_binding` so entity, repository, and service stay paired.
        """
        warnings.warn(
            "add_repository() is deprecated; prefer add_binding(entity, repository, service, connection=...).",
            DeprecationWarning,
            stacklevel=2,
        )
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
