import os
from typing import Self
from fastapi import FastAPI
from minix.core.module import Module
from minix.core.registry.registry import Registry
from minix.core.repository import SqlRepository
from minix.core.repository import RedisRepository
from minix.core.scheduler import Scheduler
from minix.core.connectors.sql_connector import SqlConnector


class BusinessModule(Module):

    def install(self):
        if len(self.entities) == len(self.services) == len(self.repositories):
            self.install_models(self.models)
            self.install_entities(self.entities)
            self.install_repositories(self.repositories)
            self.install_services(self.services)
            self.install_periodic_tasks(self.periodic_tasks)
            self.install_tasks(self.tasks)
            self.install_controllers(self.controllers)
            self.install_consumers(self.consumers)
        else:
            raise ValueError('The number of entities, services and repositories must be equal')

    def install_entities(self, entities)-> Self:
        return self

    def install_repositories(self, repositories)-> Self:
        for idx, repo_salt_tuple in enumerate(repositories):
            repository, salt = repo_salt_tuple
            if salt is not None:
                sql_connector = Registry().get(SqlConnector, salt=salt)
            else:
                sql_connector = Registry().get(SqlConnector)
            if issubclass(repository, SqlRepository):
                Registry().register(
                    repository,
                    repository(self.entities[idx], sql_connector)
                )

            elif issubclass(repository, RedisRepository):
                from redis import Redis
                redis = Registry().get(Redis)
                Registry().register(
                    repository,
                    repository(
                        self.entities[idx],
                        redis
                    )
                )
        return self

    def install_services(self, services)-> Self:
        for idx, service in enumerate(services):

            Registry().register(
                service,
                service(Registry().get(self.repositories[idx][0]))
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
        for controller in controllers:
            Registry().register(
                controller,
                controller()
            )
            r = Registry().get(controller)
            api.include_router(r.get_router)

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
                bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
                if bootstrap_servers is None:
                    raise ValueError("Bootstrap servers must be provided either in the config or as an environment variable")
                config.bootstrap_servers = [server.strip() for server in bootstrap_servers.split(",")]
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


