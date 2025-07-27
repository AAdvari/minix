from typing import Tuple

import pymysql

from minix.core.connectors import Connector
from minix.core.module import Module
from fastapi import FastAPI
from minix.core.registry import Registry
from minix.core.scheduler import SchedulerConfig, Scheduler
pymysql.install_as_MySQLdb()
import os
import dotenv
dotenv.load_dotenv()


def register_connectors(connectors: list[Tuple[Connector, str | None]]):
    for connector, salt in connectors:
        if salt is not None:
            Registry().register(connector.__class__, connector, salt=salt)
        else:
            Registry().register(connector.__class__, connector)

def register_scheduler():
    Registry().register(Scheduler, Scheduler(
        SchedulerConfig()
        .set_broker_url(os.getenv('CELERY_BROKER_URL'))
        .set_result_backend(os.getenv('CELERY_RESULT_BACKEND'))
        .set_task_serializer('json')
        .set_result_serializer('json')
        .set_accept_content(['json'])
        .set_timezone('GMT')
    ))
def register_fast_api():
    Registry().register(FastAPI, FastAPI())
def register_modules(modules: list[Module]):
    fast_api = False
    scheduler = False
    for module in modules:
        if module.controllers is not None and len(module.controllers) > 0:
            fast_api = True
        if module.periodic_tasks is not None and len(module.periodic_tasks) > 0:
            scheduler = True
        if module.tasks is not None and len(module.tasks) > 0:
            scheduler = True

    if fast_api:
        register_fast_api()
    if scheduler:
        register_scheduler()
    for module in modules:
        module.install()


def bootstrap(
        modules: list[Module] = None,
        connectors: list[Tuple[Connector, str | None]] = None
):

    if connectors:
        register_connectors(connectors)
    if modules:
        register_modules(modules)


