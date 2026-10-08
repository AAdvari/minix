from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from minix.core.bootstrap import bootstrap_from_settings
from minix.core.bootstrap.bootstrap import register_fast_api
from minix.core.registry import Registry

bootstrap_from_settings()

Api = Registry().get(FastAPI)
if Api is None:
    register_fast_api()
    Api = Registry().get(FastAPI)
