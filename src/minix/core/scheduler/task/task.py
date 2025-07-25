from abc import abstractmethod, ABC
from celery.schedules import crontab

from celery import Task as CeleryTask
class Task(CeleryTask, ABC):

    def __init__(
            self,
            *args,
            **kwargs
    ):
        self.args = args
        self.kwargs = kwargs
        super().__init__()


    def get_args(self):
        return self.args

    def get_kwargs(self):
        return self.kwargs


    @property
    def name(self):
        return self.get_name()

    @abstractmethod
    def get_name(self)-> str:
        pass

    @abstractmethod
    def run(self, *args, **kwargs):
        pass




class PeriodicTask(Task, ABC):

    @abstractmethod
    def get_schedule(self)-> crontab:
        pass




