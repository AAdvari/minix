# Minix


**Minix** is a modular Python framework for building backend, AI, and data-driven applications. It provides a clean, layered architecture with built-in support for REST APIs, task scheduling, message queues, and machine learning workflows.

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Version](https://img.shields.io/badge/version-0.1.32-green.svg)
![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)

---

## Table of Contents

- [Key Features](#key-features)
- [Architecture Overview](#architecture-overview)
- [Installation](#installation)
- [Core Concepts](#core-concepts)
  - [Bootstrap](#bootstrap)
  - [Modules](#modules)
  - [Entities](#entities)
  - [Repositories](#repositories)
  - [Services](#services)
  - [Controllers](#controllers)
  - [Connectors](#connectors)
  - [Tasks & Scheduling](#tasks--scheduling)
    - [Async Task](#async-task)
    - [Periodic Task](#periodic-task)
    - [Running Tasks Manually](#running-tasks-manually)
    - [Workflows (DAG Scheduling)](#workflows-dag-scheduling)
  - [Kafka Consumers](#kafka-consumers)
  - [ML Models](#ml-models)
- [Configuration](#configuration)
- [Extras](#extras)
- [Registry Usage](#registry-usage)
- [CLI Commands](#cli-commands)
- [License](#license)
- [Contributing](#contributing)
- [Author](#author)

---

## Key Features

- **FastAPI Integration**: Build high-performance REST APIs with automatic OpenAPI documentation
- **Modular Architecture**: Organize code into self-contained modules with entities, repositories, services, and controllers
- **Multi-Database Support**: Built-in connectors for MySQL, ClickHouse, Redis, and Qdrant (vector DB)
- **Task Scheduling**: Celery-powered background tasks with RedBeat scheduler for periodic jobs
- **Kafka Consumers**: Async Kafka message processing with `aiokafka`
- **Object Storage**: S3-compatible storage support via `boto3`
- **ML Workflows**: Optional MLflow integration for model versioning and deployment
- **Dependency Registry**: Singleton-based service container for clean dependency injection
- **Environment Management**: `config.py` (pydantic-settings) with `.env` support

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Application                              │
├─────────────────────────────────────────────────────────────────┤
│  Bootstrap → Registers Connectors & Modules                      │
├─────────────────────────────────────────────────────────────────┤
│                          Modules                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │Controller│ │ Service  │ │Repository│ │  Entity  │            │
│  │ (API)    │→│ (Logic)  │→│  (Data)  │→│ (Model)  │            │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘            │
├─────────────────────────────────────────────────────────────────┤
│  Tasks (Celery)  │  Consumers (Kafka)  │  Models (MLflow)       │
├─────────────────────────────────────────────────────────────────┤
│                        Connectors                                │
│  SQL (MySQL/ClickHouse) │ Redis │ Qdrant │ Object Storage (S3)  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Installation

### Requirements

- Python 3.10 or higher

### Install via pip

```bash
pip install minix
```

### Install from source (development)

```bash
git clone <repository-url>
cd minix
pip install -e .
```

---

## Core Concepts

### Bootstrap

The `bootstrap` function initializes your application by registering connectors and modules:

```python
# Preferred: connectors and INSTALLED_MODULES come from config.py.
from minix.core.bootstrap import bootstrap_from_settings
bootstrap_from_settings()

# Deprecated (backward compatible): pass explicit lists.
from minix.core.bootstrap import bootstrap
bootstrap(
    modules=[Module1(), Module2()],
    connectors=[
        (sql_connector, None),           # Default connector
        (sql_connector_2, "analytics")   # Named connector with salt
    ]
)
```

### Modules

Modules are self-contained units that group related functionality:

```python
from minix.core.module.business_module import BusinessModule

class ProductModule(BusinessModule):
    def __init__(self):
        super().__init__("product")
        self.add_binding(ProductEntity, ProductRepository, ProductService)
        self.add_controller(ProductController)
        self.add_periodic_task(SyncProductsTask)
        self.add_consumer(ProductEventConsumer)
```

**Module Methods:**
- `add_binding(entity, repository, service, connection=None)` - Register a paired entity / repository / service (preferred)
- `add_entity(entity)` - Register a data entity (**deprecated**, use `add_binding`)
- `add_repository(repository, connector_salt)` - Register a repository with optional connector (**deprecated**, use `add_binding`)
- `add_service(service)` - Register a service (**deprecated**, use `add_binding`)
- `add_controller(controller)` - Register an API controller
- `add_task(task)` - Register an async task
- `add_periodic_task(periodic_task)` - Register a scheduled task
- `add_consumer(consumer)` - Register a Kafka consumer
- `add_model(model, config)` - Register an ML model

### Entities

Entities define your data models:

#### SQL Entity

```python
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from minix.core.entity import SqlEntity

class UserEntity(SqlEntity):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
```

SQL entities automatically include `id`, `created_at`, and `updated_at` columns.

#### Qdrant Entity (Vector DB)

```python
from minix.core.entity import QdrantEntity

class DocumentEntity(QdrantEntity):
    content: str

    @staticmethod
    def collection() -> str:
        return "documents"
```

#### Redis Entity

```python
from minix.core.entity import RedisEntity

class CacheEntity(RedisEntity):
    pass
```

### Repositories

Repositories handle data access:

#### SQL Repository

```python
from minix.core.repository import SqlRepository

class UserRepository(SqlRepository[UserEntity]):
    pass
```

**Built-in methods:**
- `save(entity)` - Save a single entity
- `save_all(entities)` - Save multiple entities
- `save_bulk(entities, chunk_size)` - Bulk insert with chunking
- `get_all()` - Get all entities
- `get_by_id(id)` - Get by ID
- `get_by(**kwargs)` - Filter by attributes
- `update(entity)` - Update an entity
- `delete(entity)` - Delete an entity

#### Qdrant Repository

```python
from minix.core.repository import QdrantRepository

class DocumentRepository(QdrantRepository[DocumentEntity]):
    pass
```

**Methods:**
- `insert(entities)` - Insert vectors
- `query(entity, top_k)` - Similarity search
- `delete(entity_ids)` - Delete vectors

### Services

Services contain business logic:

```python
from minix.core.service import Service

class UserService(Service[UserEntity]):
    def get_active_users(self):
        return self.repository.get_by(status="active")

    def create_user(self, name: str, email: str) -> UserEntity:
        user = UserEntity(name=name, email=email)
        return self.repository.save(user)
```

### Controllers

Controllers define REST API endpoints:

```python
from minix.core.controller import Controller
from minix.core.registry import Registry

class UserController(Controller):
    def get_prefix(self):
        return "/users"

    def define_routes(self):
        @self.router.get("/")
        def get_users():
            service = Registry().get(UserService)
            return service.get_repository().get_all()

        @self.router.post("/")
        def create_user(name: str, email: str):
            service = Registry().get(UserService)
            return service.create_user(name, email)
```

### Connectors

#### SQL Connector (MySQL/ClickHouse)

```python
from minix.core.connectors import SqlConnector

# Reads DB_* from settings / env
connector = SqlConnector()

# Deprecated — still supported for backward compatibility:
# from minix.core.connectors import SqlConnector, SqlConnectorConfig
# connector = SqlConnector(SqlConnectorConfig(username="root", ...))
```

#### Qdrant Connector

```python
from minix.core.connectors import QdrantConnector

# Reads QDRANT_CONNECTIONS[connection] from settings / env
connector = QdrantConnector()
await connector.connect()
```

#### Object Storage Connector (S3-compatible)

```python
from minix.core.object_storage import ObjectStorageConnector

# Reads OBJECT_STORAGES[connection] from settings / env
connector = ObjectStorageConnector()

# Upload, download, delete files
await connector.upload_file(file_obj, "path/to/file.txt")
await connector.download_file("path/to/file.txt", local_file)
await connector.generate_presigned_url("path/to/file.txt", expiration=3600)
```

### Tasks & Scheduling

#### Async Task

```python
from minix.core.scheduler.task import Task

class ProcessOrderTask(Task):
    def get_name(self) -> str:
        return "process_order"

    def run(self, order_id: int):
        # Process the order
        pass
```

#### Periodic Task

```python
from celery.schedules import crontab
from minix.core.scheduler.task import PeriodicTask

class DailyReportTask(PeriodicTask):
    def get_name(self) -> str:
        return "daily_report"

    def get_schedule(self) -> crontab:
        return crontab(hour=0, minute=0)  # Run at midnight

    def run(self):
        # Generate daily report
        pass
```

#### Running Tasks Manually

```python
from minix.core.registry import Registry
from minix.core.scheduler import Scheduler

scheduler = Registry().get(Scheduler)
scheduler.run_task(ProcessOrderTask(order_id=123))
```

#### Workflows (DAG Scheduling)

Minix supports defining and executing **workflows as DAGs** (Directed Acyclic Graphs) where:
- Each node is a `Task`
- Nodes can depend on other nodes
- Dependency results can be passed to downstream tasks
- The workflow engine guarantees **each node runs at most once** during a workflow execution
- If the DAG has multiple sink nodes, **all sinks are executed**

##### Creating a Workflow

```python
from minix.core.registry import Registry
from minix.core.scheduler import Scheduler
from minix.core.scheduler.workflow import Workflow

scheduler = Registry().get(Scheduler)

wf = Workflow("order_pipeline")

t1 = wf.add(DAGTaskTest1(in_a=aaaaa), node_id="task1")
t2 = wf.add(DAGTaskTest2(), node_id="task2", depends_on=[t1], consume_dependency_results=True)
t3 = wf.add(DAGTaskTest3(), node_id="task3", depends_on=[t2, t1], consume_dependency_results=True)
t4 = wf.add(DAGTaskTest4(), node_id="task4", depends_on=[t3], consume_dependency_results=True)

t5 = wf.add(DAGTaskTest5(), node_id="task5", depends_on=[t4], consume_dependency_results=True)

res = scheduler.run_workflow(wf)
```

##### Dependency Result Passing

For a node with `consume_dependency_results=True`:

- If it has **1 dependency**, that dependency result is passed as the **first positional argument** (`arg0`) to the task.
- If it has **multiple dependencies**, a **list of dependency results** is passed as `arg0` in the same order as `depends_on`.

For a node with `consume_dependency_results=False`, no dependency result is injected.

> This design allows tasks to explicitly opt in/out of consuming upstream values, while still receiving their own constructor-provided `args/kwargs`.

##### Running the Entire Workflow

```python
res = scheduler.run_workflow(wf)
print(res.id)  # Celery task id
# output = res.get(timeout=...)  # if you want to block and fetch the final result
```

**Final result shape when running the whole workflow:**
- If the workflow has **one sink**, the final result is that sink’s output.
- If the workflow has **multiple sinks**, the final result is a dictionary mapping sink node ids to outputs:
  ```python
  {
    "task5": <result_of_task6>,
    "task4": <result_of_task9>
  }
  ```

##### Running a Specific Target Node

You can execute only the subgraph required to compute a particular node (useful for partial runs or debugging):

```python
res = scheduler.run_workflow(wf, target_node_id="task9")
# output = res.get(timeout=...)
```

In this mode, only `task9` and its dependency closure are executed, and the returned value corresponds to the output of the target node (`task9`).

##### Workflow Execution Guarantees

When executing a workflow:
- **No duplicate execution**: if a node is required by multiple downstream nodes, it runs once.
- **Multiple sinks are supported**: all sink nodes run when executing the whole workflow.
- **Full-graph execution**: when no `target_node_id` is provided, the workflow runs the entire DAG (not only the ancestry of a single sink).

---

### Kafka Consumers

```python
from minix.core.consumer import AsyncConsumer, AsyncConsumerConfig

class OrderEventConsumer(AsyncConsumer):
    def get_config(self) -> AsyncConsumerConfig:
        return AsyncConsumerConfig(
            name="order_consumer",
            topics=["orders"],
            group_id="order_service",
            bootstrap_servers=["localhost:9092"]
        )

    async def run(self, message: dict):
        # Process the message
        order_id = message.get("order_id")
        print(f"Processing order: {order_id}")
```

### ML Models

#### Base Model

```python
from minix.core.model import Model

class MyModel(Model):
    def get_model_name(self):
        return "my_model"

    def predict(self, model_input: dict):
        # Prediction logic
        pass

    def set_device(self, device: str):
        self.device = device
```

#### Embedding Model

```python
from minix.core.model import EmbeddingModel
import numpy as np

class TextEmbedder(EmbeddingModel):
    def get_model_name(self):
        return "text_embedder"

    def embed(self, text: str) -> np.ndarray:
        # Return embedding vector
        pass

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        # Return batch of embeddings
        pass

    def set_device(self, device: str):
        self.device = device
```

#### MLflow Model (requires `ai` extra)

```python
from minix.core.model import MlflowModel

class MyMlflowModel(MlflowModel):
    def __init__(self):
        super().__init__(
            name="my_model",
            version=1,
            packages=["torch", "transformers"]
        )

    def get_model(self):
        # Return your model instance
        pass

    def predict(self, model_input):
        model = self.load_model()
        return model.predict(model_input)
```

---

## Configuration

Minix uses a **pydantic-settings** config module (`config.py`).
Values come from the environment / `.env`, with defaults on the `Settings` class.

### Project config

```bash
minix init my_project
```

This creates `config.py`, `.env`, `.env.example`, `Dockerfile`,
`docker-compose.yml`, and `entries/`. The name argument sets `app_name`;
optional `--*-port` flags set Docker / env port defaults.
`.env` includes `MINIX_SETTINGS_MODULE=config`.


```python
from minix.core.conf import settings
from config import config

print(settings.APP_NAME)
print(settings.DATABASES["default"]["host"])
print(config.app_name)  # same pydantic instance
```

Override the module with `MINIX_SETTINGS_MODULE`. With no `config` module,
framework defaults from `global_settings` are used.

### Connectors from config

Edit the `Settings` class (or the exported `DATABASES` map) in `config.py`.
When ``bootstrap_from_settings()`` is called without ``connectors=``, Minix registers one
connector per map key:

```python
# config.py — add another database entry under DATABASES
DATABASES = {
    "default": {...},
    "analytics": {
        "user": "...",
        "password": "...",
        "host": "...",
        "port": 3306,
        "name": "analytics",
        "driver": "mysql",
    },
}

# entries/api.py
bootstrap_from_settings()
```

Maps wired automatically: ``DATABASES``, ``OBJECT_STORAGES``,
``QDRANT_CONNECTIONS``, ``REDIS_CONNECTIONS``. Each key becomes Registry
``salt`` (``"default"`` → no salt).

Modules are listed in ``INSTALLED_MODULES`` as dotted paths::

    INSTALLED_MODULES = [
        "minix.core.modules.auth.AuthModule",
        "src.modules.example.ExampleModule",
    ]

Pass an explicit ``connectors=[...]`` / ``modules=[...]`` list to take full
control (existing apps keep working). Pass ``connectors=[]`` /
``modules=[]`` to register/install none.

Multiple Celery apps use ``CELERY_CONNECTIONS``;
``scheduler_config(connection="priority")`` picks a named entry.
Bootstrap still registers the ``"default"`` scheduler when modules need tasks.

Missing keys raise ``ImproperlyConfigured``.

Passing an explicit ``SqlConnectorConfig`` / URL still works but is
**deprecated**; prefer ``connection=`` with settings maps.

### Environment overrides

Any key in `.env` overrides the default in `config.py`:

```env
DB_HOST=localhost
DB_DATABASE=myapp
CELERY_BROKER_URL=redis://localhost:6379/0
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
MLFLOW_TRACKING_URL=http://localhost:5000
```

---

## Extras

### AI Capabilities

Install with AI tools (PyTorch, MLflow, Qdrant):

```bash
pip install "minix[ai]"
```

### ClickHouse Support

Install with ClickHouse support:

```bash
pip install "minix[clickhouse]"
```

### Install All Extras

```bash
pip install "minix[ai,vdb,clickhouse]"
```

---

## Registry Usage

The `Registry` is a singleton-based dependency container:

```python
from minix.core.registry import Registry

# Register a service
Registry().register(MyService, MyService())

# Register with a salt (for multiple instances)
Registry().register(SqlConnector, connector, salt="analytics")

# Retrieve a service
service = Registry().get(MyService)

# Retrieve with salt
connector = Registry().get(SqlConnector, salt="analytics")
```

---

## CLI Commands

Install Minix, then use the `minix` entry point:

```bash
minix --help
minix <command> --help
```

### Global options

| Option | Short | Description |
|--------|-------|-------------|
| `--version` | `-v` | Print the installed Minix version and exit |
| `--help` | | Show CLI help |

```bash
minix -v
minix --version
```

### `minix init`

Scaffold a project in the **current directory**.

```bash
minix init APP_NAME [OPTIONS]
```

| Argument / option | Default | Description |
|-------------------|---------|-------------|
| `APP_NAME` | *(required)* | Written to `app_name` in `config.py`, `.env`, and `.env.example` |
| `--app-port` | `8000` | API port (Dockerfile `EXPOSE` / compose `app` mapping) |
| `--db-port` | `3306` | Host port for MySQL |
| `--redis-port` | `6379` | Host port for Redis |
| `--qdrant-port` | `6333` | Host port for Qdrant HTTP |
| `--qdrant-grpc-port` | `6334` | Host port for Qdrant gRPC |
| `--object-storage-port` | `9000` | Host port for MinIO API |
| `--object-storage-console-port` | `9001` | Host port for MinIO console |
| `--extras` | *(auto)* | Comma-separated PyPI extras: `vdb`, `clickhouse`, `ai` |
| `--no-extras` | off | Minimal Docker/compose (base `minix` only) |

**Creates:**

| File | Purpose |
|------|---------|
| `config.py` | Explicit pydantic `Settings` (all options in one file) |
| `.env.example` | Documented env keys with copy instructions (commit this) |
| `.env` | Local overrides without the copy header (gitignored) |
| `.gitignore` | Python / IDE / dotenv ignores |
| `Dockerfile` | App image (`pip install "minix~=X.Y.Z"` / extras from PyPI) |
| `docker-compose.yml` | MySQL, Redis, MinIO, API, Celery; optional Qdrant / ClickHouse / MLflow |
| `.dockerignore` | Build context excludes |
| `entries/` | `api.py`, `worker.py`, `beat.py` process entrypoints |

**Behavior:**

- Fails with exit code `1` if `config.py` or `settings.py` already exists.
- Existing optional files (`.env`, `.gitignore`, Docker files, `entries/`) are kept
  (`.env` only gains `MINIX_SETTINGS_MODULE` when missing).
- Port flags bake defaults into `Dockerfile`, `docker-compose.yml`, `.env`, and `config.py`.
- **Optional extras:** If you installed Minix with extras in the same environment
  (e.g. `pip install "minix[vdb]"`), `minix init` adds matching `pip install`
  in the Dockerfile and enables the related compose services and config blocks.
  Override with `--extras vdb,clickhouse,ai` or use `--no-extras` for a minimal stack.
- **Version pin:** The Dockerfile uses a compatible release on the installed minor
  (e.g. ``minix~=0.2.2`` → latest ``0.2.x`` ≥ ``0.2.2``, not ``0.3``).

```bash
minix init my_app
minix init my_app --app-port 8001 --db-port 3307 --redis-port 6380
pip install "minix[vdb]"
minix init my_app --extras vdb
minix init my_app --no-extras
```

---

## License

Minix is licensed under the **MIT License**. See the `LICENSE` file for more details.

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## Author

**AmirHossein Advari** - [amiradvari@gmail.com](mailto:amiradvari@gmail.com) \
**Shirin Dehghani** - [shirin.dehghani1996@gmail.com](mailto:shirin.dehghani1996@gmail.com) \
**Parsa Mohammadpour** - [parsa.mohammadpour01@gmail.com](mailto:parsa.mohammadpour01@gmail.com)
