from typing import Tuple

import pymysql

from minix.core.connectors import Connector
from minix.core.module import Module
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from minix.core.registry import Registry
from minix.core.scheduler import Scheduler
from minix.core.conf import settings
from minix.core.conf.builders import scheduler_config

pymysql.install_as_MySQLdb()


def register_connectors(connectors: list[Tuple[Connector, str | None]]):
    for connector, salt in connectors:
        if salt is not None:
            Registry().register(connector.__class__, connector, salt=salt)
        else:
            Registry().register(connector.__class__, connector)

def register_scheduler():
    Registry().register(Scheduler, Scheduler(scheduler_config(settings)))

def register_fast_api():
    app = FastAPI(title=getattr(settings, "APP_NAME", "minix"))
    # Allow CORS for localhost-related origins and local network IPs.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=(
            r"^https?://("
            r"localhost|"
            r"127(?:\.\d{1,3}){3}|"
            r"10(?:\.\d{1,3}){3}|"
            r"192\.168(?:\.\d{1,3}){2}|"
            r"172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}|"
            r"\[::1\]"
            r")(?::\d+)?$"
        ),
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    Registry().register(FastAPI, app)
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
