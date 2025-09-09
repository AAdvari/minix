from typing import Self
from celery import Celery
from minix.core.scheduler.task import PeriodicTask, Task


class SchedulerConfig:
    def __init__(self):
        self.broker_url = ''
        self.result_backend = ''
        self.task_serializer = 'json'
        self.result_serializer = 'json'
        self.accept_content = ['json']
        self.timezone = 'GMT'

    def set_broker_url(self, url) -> Self:
        self.broker_url = url
        return self

    def set_result_backend(self, url) -> Self:
        self.result_backend = url
        return self

    def set_task_serializer(self, serializer) -> Self:
        self.task_serializer = serializer
        return self

    def set_result_serializer(self, serializer) -> Self:
        self.result_serializer = serializer
        return self

    def set_accept_content(self, content) -> Self:
        self.accept_content = content
        return self

    def set_timezone(self, timezone) -> Self:
        self.timezone = timezone
        return self

    def get_broker_url(self):
        return self.broker_url

    def get_result_backend(self):
        return self.result_backend

    def get_task_serializer(self):
        return self.task_serializer

    def get_result_serializer(self):
        return self.result_serializer

    def get_accept_content(self):
        return self.accept_content

    def get_timezone(self):
        return self.timezone


class Scheduler(Celery):

    def __init__(self, config: SchedulerConfig):
        super().__init__('scheduler')
        self.celery = Celery(
            "task_scheduler",
            broker=config.get_broker_url(),
            backend=config.get_result_backend(),
            timezone=config.get_timezone(),
            broker_connection_retry_on_startup=False,
            task_track_started=True,
            result_extended=True,
        )
        self.celery.beat_scheduler = 'redbeat.RedBeatScheduler'
        self.celery.redbeat_redis_url = config.get_broker_url()
        self.celery.conf.task_serializer = config.get_task_serializer()
        self.celery.conf.result_serializer = config.get_result_serializer()
        self.celery.conf.accept_content = config.get_accept_content()
        self.celery.conf.timezone = config.get_timezone()

    def get_app(self):
        return self.celery


    def run_task(self, task: Task):
        self.get_app().send_task(
            task.get_name(),
            args=task.get_args(),
            kwargs=task.get_kwargs()
        )

    def register_async_task(self, task: Task):
        self.get_app().register_task(task)
        return self

    # def register_periodic_task(self, task: PeriodicTask):
    #     registering_task = task
    #     self.get_app().register_task(registering_task)
    #     self.get_app().conf.beat_schedule = {
    #         registering_task.get_name(): {
    #             'task': registering_task.get_name(),
    #             'schedule': registering_task.get_schedule(),
    #             'args': registering_task.get_args(),
    #             'kwargs': registering_task.get_kwargs()
    #         }
    #     }
    #     return self

    def register_periodic_task(self, task: PeriodicTask):
        app = self.get_app()
        app.register_task(task)

        # merge instead of replace
        beat = getattr(app.conf, "beat_schedule", {}) or {}
        beat[task.get_name()] = {
            "task": task.get_name(),
            "schedule": task.get_schedule(),
            "args": task.get_args(),
            "kwargs": task.get_kwargs(),
        }
        app.conf.beat_schedule = beat
        return self

