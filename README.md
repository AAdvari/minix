# Minix


**Minix** is a modular Python framework for building backend, AI, and data-driven applications. It provides a clean, layered architecture with built-in support for REST APIs, task scheduling, message queues, and machine learning workflows.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
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
  - [Kafka Consumers](#kafka-consumers)
  - [ML Models](#ml-models)
- [Configuration](#configuration)
- [Extras](#extras)
- [License](#license)

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
        self.add_entity(ProductEntity)
        self.add_repository(ProductRepository)
        self.add_service(ProductService)
        self.add_controller(ProductController)
        self.add_periodic_task(SyncProductsTask)
        self.add_consumer(ProductEventConsumer)
```

**Module Methods:**
- `add_entity(entity)` - Register a data entity
- `add_repository(repository, connector_salt)` - Register a repository with optional connector
- `add_service(service)` - Register a service
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

### Install All Extras

```bash
pip install "minix[ai,clickhouse,dev]"
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

**AmirHossein Advari** - [amiradvari@gmail.com](mailto:amiradvari@gmail.com)
