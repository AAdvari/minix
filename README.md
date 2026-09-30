# Minix


**Minix** is a modular Python framework for building backend, AI, and data-driven applications. It provides a clean, layered architecture with built-in support for REST APIs, task scheduling, message queues, and machine learning workflows.

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Version](https://img.shields.io/badge/version-0.3.0-green.svg)
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
- [RAG Module](#rag-module)
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
- **RAG Module**: Pluggable retrieval-augmented generation — collections, document ingestion, chunking, hybrid BM25 + vector retrieval, LLM reranking, and answers with citations
- **Dependency Registry**: Singleton-based service container for clean dependency injection
- **Environment Management**: Configuration via `.env` files using `dotenv`

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
- `add_binding(entity, repository, service, connector_salt=None, *, provides_repository=None, provides_service=None)` - Register a paired entity / repository / service (preferred)
- `add_entity(entity)` - Register a data entity (**deprecated**, use `add_binding`)
- `add_repository(repository, connector_salt, provides=None)` - Register a repository with optional connector (**deprecated**, use `add_binding`)
- `add_service(service, provides=None)` - Register a service (**deprecated**, use `add_binding`)
- `add_helper_service(service)` - Register a stand-alone helper service (no repository)
- `add_controller(controller, provides=None)` - Register an API controller
- `add_task(task)` - Register an async task
- `add_periodic_task(periodic_task)` - Register a scheduled task
- `add_consumer(consumer)` - Register a Kafka consumer
- `add_model(model, config)` - Register an ML model

**Swapping in a subclass (`provides`)**: `provides=Base` also registers the
installed instance under `Base`, so every `Registry().get(Base)` lookup —
including the framework's own — resolves to your subclass. This is how you
extend a built-in module (e.g. the RAG module below) without editing it:

```python
from minix.core.modules.rag.controllers import RagController
from minix.core.modules.rag.services import RagCollectionService

module = (
    BusinessModule("my_rag")
    .add_binding(MyCollectionEntity, MyCollectionRepository, MyCollectionService,
                 provides_service=RagCollectionService)
    .add_controller(MyRagController, provides=RagController)
)
```

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
from minix.core.connectors.sql_connector import SqlConnector, SqlConnectorConfig

config = SqlConnectorConfig(
    username="root",
    password="password",
    host="localhost",
    port=3306,
    database="mydb",
    driver="mysql",  # or "clickhouse"
    connect_timeout=30,
    pool_recycle=3600
)
connector = SqlConnector(config)
```

#### Qdrant Connector

```python
from minix.core.connectors.qdrant_connector import QdrantConnector

connector = QdrantConnector(
    url="http://localhost:6333",
    api_key="your-api-key"
)
await connector.connect()
```

#### Object Storage Connector (S3-compatible)

```python
from minix.core.connectors.object_storage_connector import ObjectStorageConnector
from minix.core.connectors.object_storage_connector.config import ObjectStorageConfig

config = ObjectStorageConfig(
    endpoint_url="https://s3.amazonaws.com",
    access_key="your-access-key",
    secret_key="your-secret-key",
    bucket_name="my-bucket"
)
connector = ObjectStorageConnector(config)

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

## RAG Module

`minix.core.modules.rag` is a ready-made retrieval-augmented generation module:
a REST API over named **collections** of documents, with async ingestion, hybrid
retrieval and LLM answers that cite their sources.

**What it does**

- **Ingestion** — upload a file (`POST /rag/ingest/upload`: PDF or images read
  by a vision model, or text formats) or post raw text (`POST /rag/ingest/text`).
  Ingestion runs in the background and returns a `job_id` to poll.
- **Chunking** — per-collection strategy: `smart`, `fixed`, `by_heading`,
  `by_clause`, `qa`, `sentence` or `llm` (instruction-driven).
  `GET /rag/chunking/strategies` returns UI labels for each.
- **Metadata extraction** — the LLM detects the document type and extracts
  typed metadata, stored in PostgreSQL and on every vector payload.
- **Hybrid retrieval** — PostgreSQL full-text search (`tsvector`) plus Qdrant
  cosine vectors, fused (weighted or RRF) and filtered by a relevance floor.
- **LLM reranking** — optional reranker that re-orders the retrieved chunks
  before the answer prompt (per request, or server default).
- **Answers with citations** — `POST /rag/query` (async, poll by `query_id`),
  single collection or an explicit multi-collection allowlist. Every response
  carries the retrieved and selected chunks and a refusal classification
  (`out_of_corpus`, `out_of_scope`, `policy_violation`, `ambiguous`). Retrieved
  text is fenced as untrusted data in the prompt.
- **Search without an LLM** — `POST /rag/search` (hybrid / vector / keyword).
- **Multi-query match** — `POST /rag/match` blends several weighted queries into
  one document ranking (synchronous).
- **Management** — collections, documents, chunks, jobs, `GET /rag/health`,
  `GET /rag/me`.

**Install** — the module is optional; a plain `pip install minix` does not pull
in any of its dependencies:

```bash
pip install "minix[rag]"
```

At runtime it also needs a PostgreSQL server (keyword search + metadata) and a
Qdrant server (vectors); PDF ingestion needs the `poppler` system package.
Importing `minix.core.modules.rag` without the extra raises an `ImportError`
that tells you the command above.

**Mount it**

```python
import os
from fastapi import FastAPI
from minix.core.bootstrap import bootstrap
from minix.core.connectors import SqlConnector, SqlConnectorConfig
from minix.core.entity.sql_entity import Base
from minix.core.modules.auth import AuthModule
from minix.core.modules.rag import RagModule
from minix.core.registry import Registry

pg = SqlConnector(SqlConnectorConfig(
    username="rag", password="rag", host="localhost", port=5432,
    database="rag", driver="postgresql",
))
Base.metadata.create_all(pg.get_engine())   # or manage the schema with Alembic

# Qdrant: set QDRANT_URL (and QDRANT_API_KEY), or register a QdrantConnector
# alongside the SQL connector and the RAG module will use its URL / key:
#   connectors=[(pg, None), (QdrantConnector("http://localhost:6333"), None)]
bootstrap(modules=[AuthModule, RagModule], connectors=[(pg, None)])
app = Registry().get(FastAPI)   # uvicorn main:app
```

`AuthModule` provides the API keys the RAG routes accept (`X-API-Key`). With
`RAG_ACCESS_CONTROL_ENABLED=false` (the default) requests without a key run as
an anonymous admin; set it to `true` to require a key and enforce the key's role
(`readonly` may read and query, `user` may also ingest and edit, `admin` may
also delete collections).

**Configuration** (environment variables, read by `minix.core.modules.rag.config.RagConfig`)

| Variable | Default | Purpose |
|---|---|---|
| provider API key | — | The standard variable for the provider you use (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AZURE_API_KEY`, …) — LiteLLM reads it |
| `LLM_MODEL` | `gpt-4o` | Answers, reranking (any LiteLLM model name) |
| `LLM_TEMPERATURE` | unset | Passed to the model only when set |
| `RAG_LLM_TIMEOUT_SECONDS` / `RAG_LLM_MAX_TOKENS` | `60` / `2048` | LLM call bounds |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model (any LiteLLM embedding model) |
| `EMBEDDING_DIMENSION` | `1536` | Vector size of the Qdrant collections — must equal what the model returns |
| `RAG_EMBEDDING_SEND_DIMENSIONS` | `true` | Also send it as the `dimensions` parameter; `false` for fixed-size models that reject it |
| `DOCUMENT_PROCESSOR_MODEL` | `gpt-4o` | PDF / image transcription, metadata extraction, LLM chunking (vision-capable) |
| `QDRANT_URL` / `QDRANT_API_KEY` | `http://localhost:6333` / — | Vector store (a registered `QdrantConnector` takes precedence) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `800` / `100` | Default chunking |
| `TOP_K` | `5` | Default retrieval depth |
| `BM25_WEIGHT` / `VECTOR_WEIGHT` | `0.3` / `0.7` | Hybrid fusion weights |
| `MIN_RELEVANCE_SCORE` | `0.3` | Relevance floor before the answer prompt |
| `RAG_BM25_QUERY_MODE` | `plainto` | `or` suits long natural-language queries |
| `RAG_RETRIEVAL_FETCH_MULTIPLIER` / `RAG_RETRIEVAL_CANDIDATE_FLOOR` | `6` / `50` | Candidate pool per retrieval leg |
| `LLM_SELECTOR_ENABLED` | `true` | LLM reranker on `/query` by default |
| `SELECTOR_FALLBACK_TOP_N` | `5` | Chunks handed to the answer prompt |
| `RAG_RERANKER_MODEL` / `RAG_RERANKER_MIN_SCORE` / `RAG_RERANKER_MAX_CHARS` | `LLM_MODEL` / `5` / `1200` | Reranker tuning |
| `RAG_INGEST_IDENTITY_ENRICHMENT` | `false` | Prefix chunks with a title / parties header |
| `DEFAULT_COLLECTION` | `default` | Collection used when a request names none |
| `RAG_ACCESS_CONTROL_ENABLED` | `false` | Require an API key and enforce roles |

**How it fits the framework** — it is a regular module: `RagModule` is a
`BusinessModule` built from one `add_binding(entity, repository, service)` per
table (collections, documents, chunks, jobs, search requests, query requests)
plus a controller, exactly like `AuthModule` / `OidcModule`, and everything it
needs (config, chunking, retrieval, document processors) lives inside
`minix/core/modules/rag/`. It reads the SQL connector from the Registry like any
repository, authenticates with the `auth` module's API keys, and imports nothing
that the rest of minix imports back. Long-running work (ingestion, search,
query) uses FastAPI background tasks plus persisted job rows, so the module needs
no Celery broker or Kafka.

**Providers** — nothing is tied to one vendor: every model call (answers,
reranking, embeddings, metadata extraction, document transcription, LLM
chunking) goes through [LiteLLM](https://docs.litellm.ai/), so changing a model
name is all it takes to move to another provider, a gateway or a local server:

```env
LLM_MODEL=anthropic/claude-sonnet-5          # + ANTHROPIC_API_KEY
EMBEDDING_MODEL=ollama/nomic-embed-text         # local, no key
EMBEDDING_DIMENSION=768
RAG_EMBEDDING_SEND_DIMENSIONS=false
DOCUMENT_PROCESSOR_MODEL=anthropic/claude-sonnet-5
```

Any OpenAI-compatible endpoint (vLLM, LM Studio, a gateway) works with the
`openai/<model>` prefix and `OPENAI_API_BASE`. Changing the embedding model or
its size requires re-indexing: existing vectors were produced by the old one.

**Extending it** — `RagController` exposes protected hook methods (request
scoping, gating and usage metering, per-collection access policy via
`_svc_access()`, audit, input rewriting, answer generation, output shaping,
provider-event and cost recording) and swappable response models
(`COLLECTION_INFO_MODEL`, `QUERY_RESPONSE_MODEL`, …). All defaults are
single-scope no-ops. Subclass the controller and register it with
`provides=RagController`; add columns to the RAG tables with
single-table-inheritance subclasses of the entities (no `__tablename__`), mounted
through `provides=` on the paired repository and service.

---

## Configuration

Minix uses environment variables for configuration. Create a `.env` file in your project root:

```env
# Celery Configuration
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=db+mysql://root:password@localhost:3306/celery_results

# Kafka Configuration
KAFKA_BOOTSTRAP_SERVERS=localhost:9092

# MLflow Configuration (for AI extras)
MLFLOW_TRACKING_URL=http://localhost:5000
PYTHON_VERSION=3.10
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

### Development Tools

Install development dependencies:

```bash
pip install "minix[dev]"
```

### RAG Module

Install the RAG module's dependencies, PostgreSQL driver included (see
[RAG Module](#rag-module)):

```bash
pip install "minix[rag]"
```

### PostgreSQL

Just the PostgreSQL driver for `SqlConnector(driver="postgresql")` (already part
of the `rag` extra):

```bash
pip install "minix[postgres]"
```

### Install All Extras

```bash
pip install "minix[ai,clickhouse,dev,rag]"
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

```bash
# Initialize a new project
minix init <project_name>

# Show framework version
minix version
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
