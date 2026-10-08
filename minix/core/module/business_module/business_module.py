import asyncio
import importlib.util
from typing import Self

from fastapi import FastAPI

from minix.core.connectors import SqlConnector
from minix.core.conf.builders import kafka_bootstrap_servers
from minix.core.module import Module
from minix.core.registry.registry import Registry
from minix.core.repository import RedisRepository, SqlRepository
from minix.core.scheduler import Scheduler


class BusinessModule(Module):

    def install(self):
        if len(self.entities) == len(self.services) == len(self.repositories):
            self.install_models(self.models)
            self.install_entities(self.entities)
            self.install_repositories(self.repositories)
            self.install_services(self.services)
            self.install_helper_services(self.helper_services)
            self.install_periodic_tasks(self.periodic_tasks)
            self.install_tasks(self.tasks)
            self.install_controllers(self.controllers)
            self.install_consumers(self.consumers)
        else:
            raise ValueError('The number of entities, services and repositories must be equal')

    def install_entities(self, entities)-> Self:
        return self

    def install_repositories(self, repositories)-> Self:
        for idx, repo_tuple in enumerate(repositories):
            repository, salt, provides = repo_tuple
            instance = None

            if issubclass(repository, SqlRepository):
                if salt is not None:
                    sql_connector = Registry().get(SqlConnector, salt=salt)
                else:
                    sql_connector = Registry().get(SqlConnector)
                instance = repository(self.entities[idx], sql_connector)

            elif issubclass(repository, RedisRepository):
                from redis import Redis
                if salt is not None:
                    redis = Registry().get(Redis, salt=salt)
                else:
                    redis = Registry().get(Redis)
                instance = repository(
                        self.entities[idx],
                        redis
                    )
            elif importlib.util.find_spec("qdrant_client"):
                from minix.core.connectors import QdrantConnector
                from minix.core.repository import QdrantRepository

                if not issubclass(repository, QdrantRepository):
                    continue
                if salt is not None:
                    qdrant_connector = Registry().get(QdrantConnector, salt=salt)
                else:
                    qdrant_connector = Registry().get(QdrantConnector)
                instance = repository(
                    self.entities[idx],
                    qdrant_connector,
                )
                try:
                    loop = asyncio.get_running_loop()
                    asyncio.run_coroutine_threadsafe(instance.create_collection(), loop)
                except RuntimeError:
                    asyncio.run(instance.create_collection())

            if instance is not None:
                Registry().register(repository, instance)
                if provides is not None:
                    Registry().register(provides, instance)
        return self

    def install_services(self, services)-> Self:
        for idx, service_tuple in enumerate(services):
            service, provides = service_tuple
            instance = service(Registry().get(self.repositories[idx][0]))
            Registry().register(service, instance)
            if provides is not None:
                Registry().register(provides, instance)
        return self

    def install_helper_services(self, services)-> Self:
        for service in services:
            Registry().register(
                service,
                service()
            )
        return self

    def install_periodic_tasks(self, periodic_tasks)-> Self:
        for periodic_task in periodic_tasks:
            (Registry().get(Scheduler).register_periodic_task(periodic_task()))
        return self

    def install_tasks(self, tasks)-> Self:
        for task in tasks:
            (Registry().get(Scheduler).register_async_task(task()))
        return self

    def install_controllers(self, controllers)-> Self:
        if len(controllers) == 0:
            return self
        api = Registry().get(FastAPI)
        for controller_tuple in controllers:
            controller, provides = controller_tuple
            instance = controller()
            Registry().register(controller, instance)
            if provides is not None:
                Registry().register(provides, instance)
            api.include_router(instance.get_router)

        return self

    def install_models(self, models)-> Self:
        for model, config in models:
            Registry().register(
                model,
                model(**config)
            )
        return self

    def install_consumers(self, consumers) -> Self:
        for consumer in consumers:
            consumer_obj = consumer()
            config = consumer_obj.get_config()
            if config.bootstrap_servers is None:
                servers = kafka_bootstrap_servers()
                if not servers:
                    raise ValueError(
                        "Bootstrap servers must be provided either in the consumer "
                        "config or via KAFKA_BOOTSTRAP_SERVERS / settings"
                    )
                config.bootstrap_servers = servers
            consumer_obj.set_config(config)
            api = Registry().get(FastAPI)
            api.add_event_handler(
                'startup',
                consumer_obj.start_in_thread
            )
            api.add_event_handler(
                'shutdown',
                consumer_obj.stop
            )
        return self


