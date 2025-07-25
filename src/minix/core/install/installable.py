from abc import ABC, abstractmethod


class Installable(ABC):

    @abstractmethod
    def install(self):
        pass



