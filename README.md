
# Minix

**Minix** is a lightweight backend framework tailored for building data-driven applications quickly and effectively. With its modular design and strong integration with modern tools, Minix empowers developers to create scalable and maintainable systems with minimal setup.

---

## Key Features

- **FastAPI Integration**: Leverage the power of FastAPI for building highly efficient REST APIs.
- **Celery Integration**: Built-in support for distributed task queues using Celery.
- **Database Support**: Seamless database connectivity with SQLAlchemy and support for MySQL (via PyMySQL).
- **Kafka Compatibility**: Asynchronous Kafka message processing with `aiokafka`.
- **Environment Management**: Simplified environment configuration using `dotenv`.
- **Cloud Ready**: Enables integration with AWS services using `boto3`.
- **Expandability**: Optional AI tools with extras like PyTorch and MLflow for machine learning use cases.

---

## Installation

First, make sure Python 3.12 or a newer version is installed. Then, install the package via pip:

```shell script
pip install minix
```


If you are developing locally, you can install it in editable mode:

```shell script
pip install -e .
```


---

## Getting Started

### 1. **Create Your Application**

After installation, you can use the CLI to kickstart your project:

```shell script
minix init your_project_name
```


This will generate a boilerplate folder structure for your data application.

### 2. **Define Your Application Logic**

Easily define and organize tasks, APIs, or other services. For example:

- **API Routes**: Using FastAPI, you can create and register endpoints effortlessly.
- **Task Scheduling**: Add Celery tasks for distributed job processing.

### 3. **Run Your Services**

Once your application is ready, you can execute services like the development server or workers:

```shell script
# Start the FastAPI server
minix run

# Start Celery workers
minix runworker
```


---

## Configuration

Minix uses environment variables for configuration management. You can define your settings in a `.env` file.
note that for other connectors you should add their respective environment variables as needed.
(example `.env` file)

```plain text
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=db+mysql://root:rootpassword@mysql:3306/db_name
CELERY_RESULT_BACKEND=db+mysql://root:rootpassword@localhost:3306/db_name
```


---

## Extras

### AI Capabilities
To enable optional AI-related tools, install the package with the `ai` extra:

```shell script
pip install "minix[ai]"
```


This will add support for tools like PyTorch and MLflow for machine learning.

### Development Tools
For local development, optional dev tools like `typer` can be installed:

```shell script
pip install "minix[dev]"
```


## License

Minix is licensed under the **MIT License**. See the `LICENSE` file for more details.

---

Let me know if you’d like to add anything specific, like usage examples, advanced configurations, or badges!