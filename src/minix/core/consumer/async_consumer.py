import asyncio
import threading
import json
from abc import ABC, abstractmethod
from typing import List
from aiokafka import AIOKafkaConsumer
from pydantic import BaseModel


class AsyncConsumerConfig(BaseModel):
    topics: List[str]
    group_id: str
    bootstrap_servers: List[str] | None = None
    name: str

class AsyncConsumer(ABC):
    def __init__(self):
        self._thread = None
        self._loop = None
        self._task = None
        self._consumer = None
        self._running = False



    @abstractmethod
    def get_config(self) -> AsyncConsumerConfig:
        """Return Kafka config including topic, bootstrap_servers, group_id"""
        pass

    @abstractmethod
    async def run(self, message: dict):
        """Process a single Kafka message."""
        pass

    async def _consume(self):
        config = self.get_config()
        topic = config.pop("topic")

        self._consumer = AIOKafkaConsumer(
            topic,
            **config.model_dump(),
            value_deserializer=lambda m: json.loads(m.decode("utf-8"))
        )

        await self._consumer.start()
        self._running = True
        print(f"[{self.__class__.__name__}] Started on topic '{topic}'")

        try:
            async for msg in self._consumer:
                await self.run(msg.value)
        except asyncio.CancelledError:
            print(f"[{self.__class__.__name__}] Cancelled")
        except Exception as e:
            print(f"[{self.__class__.__name__}] Error: {e}")
        finally:
            await self._consumer.stop()
            self._running = False
            print(f"[{self.__class__.__name__}] Stopped")

    def start_in_thread(self):
        def thread_target():
            try:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self._task = self._loop.create_task(self._consume())
                self._loop.run_until_complete(self._task)
            except Exception as e:
                print(f"[{self.__class__.__name__}] Fatal thread error: {e}")
            finally:
                self._loop.close()

        self._thread = threading.Thread(target=thread_target, daemon=True)
        self._thread.start()

    def stop(self):
        if self._loop and self._task and not self._task.done():
            def shutdown():
                self._task.cancel()

            self._loop.call_soon_threadsafe(shutdown)
            self._thread.join(timeout=10)
