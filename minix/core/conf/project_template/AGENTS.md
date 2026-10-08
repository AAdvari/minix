# AGENTS.md — Minix CLI guide for coding agents

This file is for AI coding agents working in a Minix app. **Prefer the `minix`
CLI over hand-writing project or module boilerplate.** Hand-edited scaffolds
drift from framework conventions; the CLI keeps bindings, exports, and
`installed_modules` consistent.

```bash
minix --help
minix init --help
minix add module --help
```

---

## Command catalog

Minix exposes these CLI entry points (nothing else):

| Command | Purpose |
|---------|---------|
| `minix` / `minix --help` | Root help (`no_args_is_help`) |
| `minix -v` / `minix --version` | Print installed Minix version and exit |
| `minix init APP_NAME` | Scaffold a **new project** in the current directory |
| `minix add module MODULE_NAME` | Scaffold a **feature module** under `src/modules/<name>/` |

There is **no** short form like `minix add orders`. Module creation is always:

```bash
minix add module <snake_case_name>
```

---

## Agent rules

1. **New project** → run `minix init`, do not invent `config.py` / Docker /
   `entries/` by hand.
2. **New feature module** → run `minix add module …`, then only edit generated
   files for business logic.
3. **Do not** create `src/modules/<name>/` trees manually when the CLI can.
4. After `minix add module` with `--register` (default), confirm the dotted path
   appears in `config.py` → `installed_modules`.
5. Long flags that take an optional class name use **`=`**:
   `--controller=ShopController`, `--task=ShipOrder`.
6. Short flags (`-c`, `-t`, `-e`, …) are **presence-only** — never pass a
   following token as their value.
7. Entity + repository + service are **one binding** (`add_binding`). Generate
   all three or use `--no-binding` (never a partial SQL stack).
8. For shared SQL commits across modules/repos, use
   `from minix.core.connectors import sql_transaction` — do not open ad-hoc
   sessions that commit independently unless intentional.

---

## `minix init`

Scaffold a project **in the current working directory**.

```bash
minix init APP_NAME [OPTIONS]
```

| Argument / option | Default | Description |
|-------------------|---------|-------------|
| `APP_NAME` | *(required)* | Written to `app_name` in `config.py` / `.env` |
| `--db-driver` | prompted (`postgresql`) | `postgresql` and/or `mysql` (comma-separated) |
| `--app-port` | `8000` | API port |
| `--db-port` | `5432` / `3306` | Host port for the **primary** SQL DB |
| `--redis-port` | `6379` | Redis host port |
| `--qdrant-port` | `6333` | Qdrant HTTP host port |
| `--qdrant-grpc-port` | `6334` | Qdrant gRPC host port |
| `--object-storage-port` | `9000` | MinIO API host port |
| `--object-storage-console-port` | `9001` | MinIO console host port |
| `--extras` | *(auto)* | PyPI extras: `postgresql`, `mysql`, `vdb`, `clickhouse`, `ai` |
| `--no-extras` | off | Skip auto-detected non-SQL extras |

**Behavior agents must respect:**

- Fails if `config.py` or `settings.py` already exists.
- Asks which SQL database(s) to use when `--db-driver` is omitted (TTY);
  non-TTY defaults to PostgreSQL.
- Keeps existing optional files (`.env`, Docker, `entries/`, this `AGENTS.md`).
- Wires connectors via settings maps in `config.py`; boot with
  `bootstrap_from_settings()` in `entries/api.py`.

```bash
minix init my_app
minix init my_app --db-driver postgresql
minix init my_app --db-driver mysql --db-port 3307
minix init my_app --db-driver postgresql,mysql
minix init my_app --app-port 8001 --redis-port 6380
minix init my_app --extras vdb
minix init my_app --no-extras
```

---

## `minix add module`

Scaffold under `src/modules/<name>/` (override with `--path`).

```bash
minix add module MODULE_NAME [OPTIONS]
```

**Default stack:** entity + repository + service + controller, registered in
`config.py` `installed_modules`.

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--entity[=Name]` | `-e` | on (binding) | Binding entity class name |
| `--repository[=Name]` | `-r` | on (binding) | Binding repository class name |
| `--service[=Name]` | `-s` | on (binding) | Binding service class name |
| `--controller[=Name]` | `-c` | on | HTTP controller |
| `--task[=Name]` | `-t` | off | Celery `Task` |
| `--helper[=Name]` | `-H` | off | `HelperService` |
| `--consumer[=Name]` | | off | Kafka `AsyncConsumer` |
| `--periodic[=Name]` | `-p` | off | `PeriodicTask` |
| `--all` / `-a` | | off | Default stack + task, helper, consumer, periodic |
| `--no-binding` | | off | Skip entity + repository + service together |
| `--no-controller` | | off | Skip controller only |
| `--path DIR` | | `src/modules/<name>` | Package directory |
| `--force` / `-f` | | off | Overwrite existing files |
| `--register` / `--no-register` | | register | Append to `installed_modules` |

```bash
# Default CRUD/API stack + auto-register
minix add module orders

# Custom names (binding still complete)
minix add module orders --entity=ShopOrder --controller=ShopController

# Safe short flags (presence-only)
minix add module orders -t --no-register
minix add module orders --task=ShipOrder -H

# Everything
minix add module orders -a

# Worker-oriented (no HTTP)
minix add module orders --no-controller -t

# No SQL binding
minix add module orders --no-binding -H --consumer=OrderEventsConsumer
```

**Avoid:** `minix add module orders -t ShipOrder`  
**Use:** `minix add module orders --task=ShipOrder`

### Generated layout

```
src/modules/<name>/
  __init__.py          # exports <Name>Module
  module.py            # BusinessModule + add_binding / add_*
  entities/            # when binding is on
  repositories/
  services/
  controllers/         # optional
  tasks/               # optional
  consumers/           # optional
```

---

## Global options

| Option | Short | Description |
|--------|-------|-------------|
| `--version` | `-v` | Print Minix version and exit |
| `--help` | | Help for `minix` or a subcommand |

```bash
minix -v
minix --version
minix init --help
minix add module --help
```

---

## After scaffolding (typical agent workflow)

1. `minix add module <feature>`
2. Edit entity columns / service methods / controller routes only as needed.
3. Run the API via `entries/api.py` (e.g. `uvicorn entries.api:Api --reload`).
4. For multi-repository writes that must succeed or fail together:

```python
from minix.core.connectors import sql_transaction
from minix.core.registry import Registry

with sql_transaction():
    Registry().get(OrderSqlService).create(...)
    Registry().get(PaymentSqlService).create(...)
```

Use `sql_transaction("other_connection")` for a named `DATABASES` entry.
