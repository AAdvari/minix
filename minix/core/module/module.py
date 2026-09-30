from abc import ABC
from typing import Self, Type, List, Tuple, Dict
from minix.core.consumer import AsyncConsumer
from minix.core.controller import Controller
from minix.core.entity import Entity
from minix.core.install import Installable
from minix.core.model import Model
from minix.core.repository import Repository
from minix.core.scheduler.task import PeriodicTask, Task
from minix.core.service import Service, BaseService, HelperService


class Module(Installable, ABC):


    def __init__(self, name: str):
        self.name = name
        self.entities: List[Type[Entity]] = []
        # services / repositories / controllers carry an optional `provides`
        # alias: when set, the installed instance is ALSO registered in the
        # Registry under that base type, so lazy `Registry().get(Base)` lookups
        # resolve to a subclass supplied by another module (DI interface
        # binding). `provides=None` (the default) registers only under the
        # concrete class.
        self.services: List[Tuple[Type[Service], Type[Service] | None]] = []
        self.helper_services: List[Type[BaseService]] = []
        self.repositories: List[Tuple[Type[Repository], str | None, Type[Repository] | None]] = []
        self.periodic_tasks : List[Type[PeriodicTask]] = []
        self.tasks: List[Type[Task]] = []
        self.controllers: List[Tuple[Type[Controller], Type[Controller] | None]] = []
        self.models: List[Tuple[Type[Model], Dict]] = []
        self.consumers: List[Type[AsyncConsumer]] = []

    def add_binding(
        self,
        entity: Type[Entity],
        repository: Type[Repository],
        service: Type[Service],
        connector_salt: str | None = None,
        *,
        provides_repository: Type[Repository] | None = None,
        provides_service: Type[Service] | None = None,
    ) -> Self:
        """Register an entity, repository, and service as one binding.

        Prefer this over calling ``add_entity``, ``add_repository``, and
        ``add_service`` separately so their order cannot drift.

        ``provides_repository`` / ``provides_service`` additionally register the
        installed instances under a base type, so a subclass can stand in for a
        base class that other code resolves lazily via ``Registry().get(Base)``.
        """
        self.entities.append(entity)
        self.repositories.append((repository, connector_salt, provides_repository))
        self.services.append((service, provides_service))
        return self

    def add_entity(self, entity: Type[Entity])-> Self:
        """Register a data entity.

        Deprecated: prefer :meth:`add_binding` to register entity, repository,
        and service together so they stay paired by design.
        """
        self.entities.append(entity)
        return self

    def add_periodic_task(self, periodic_task: Type[PeriodicTask])-> Self:
        self.periodic_tasks.append(periodic_task)
        return self

    def add_service(self, service: Type[Service], provides: Type[Service] | None = None)-> Self:
        """Register a service, optionally also under the base type `provides`.

        Deprecated: prefer :meth:`add_binding` to register entity, repository,
        and service together so they stay paired by design.
        """
        self.services.append((service, provides))
        return self

    def add_helper_service(self, service: Type[HelperService])-> Self:
        self.helper_services.append(service)
        return self

    def add_repository(self, repository: Type[Repository], connector_salt: str | None = None,
                       provides: Type[Repository] | None = None)-> Self:
        """Register a repository with an optional connector salt, optionally
        also under the base type `provides`.

        Deprecated: prefer :meth:`add_binding` to register entity, repository,
        and service together so they stay paired by design.
        """
        self.repositories.append((repository, connector_salt, provides))
        return self


    def add_task(self, task: Type[Task])-> Self:
        self.tasks.append(task)
        return self

    def add_controller(self, controller: Type[Controller], provides: Type[Controller] | None = None)-> Self:
        """Register a controller, optionally also under the base type
        `provides` (e.g. a subclass that replaces a framework controller)."""
        self.controllers.append((controller, provides))
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










