from dotenv import load_dotenv

load_dotenv()

from minix.core.bootstrap import bootstrap_from_settings
from minix.core.bootstrap.bootstrap import register_scheduler
from minix.core.conf import settings
from minix.core.conf.builders import modules_from_settings
from minix.core.registry import Registry
from minix.core.scheduler import Scheduler

modules = modules_from_settings(settings)
for module in modules:
    module.exclude_all_consumers()
    module.exclude_all_controllers()

bootstrap_from_settings(modules=modules)

if Registry().get(Scheduler) is None:
    register_scheduler()

Worker = Registry().get(Scheduler).get_app()
