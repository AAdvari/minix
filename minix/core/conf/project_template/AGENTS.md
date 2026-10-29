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
| `minix init APP_NAME --rag` | Scaffold a project with built-in RAG and Qdrant (requires PostgreSQL) |
| `minix add rag` | Enable built-in RAG in an **existing** PostgreSQL project |
| `minix add module MODULE_NAME` | Scaffold a **feature module** under `src/modules/<name>/` |
| `minix add controller\|task\|periodic\|helper\|consumer\|binding [NAME] --module=MODULE` | Add one piece to an **existing** module and wire it in `module.py` |
| `minix db makemigrations -m "message"` | Generate a migration from SQL entity changes (`migrations/<connection>/versions/`) |
| `minix db migrate` / `minix db downgrade -1` | Apply / revert migrations |
| `minix db init` | Recreate `migrations/<connection>/` (`minix init` already creates it) |
| `minix db current\|history\|heads\|branches\|show\|check\|stamp\|merge\|edit` | Alembic's command of the same name, run for the project's connections |

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
   To add a controller / task / helper / consumer / periodic task / binding to
   an existing module, run `minix add <component> [NAME] --module=<module>` instead of
   hand-editing `module.py` and the subpackage `__init__.py`.
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
9. **Schema changes** → `minix db makemigrations -m "…"` then `minix db migrate`.
   Never call `Base.metadata.create_all()` or hand-write `env.py`. Review each
   generated revision before applying it (see [`minix db`](#minix-db)).
10. **Never edit a migration that has been applied or committed.** Write a new
    one instead. Never change an entity's `__tablename__` after its table has
    been migrated; that is a rename and needs its own migration.
11. **Ask the user before** `minix db downgrade`, `minix db stamp`, or any
    migration that drops a table or column. They change or lose data.
12. Before finishing a change that touched entities, run `minix db check`; it
    fails when a migration is missing.

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
| `--extras` | *(auto)* | PyPI extras: `postgresql`, `mysql`, `vdb`, `clickhouse`, `ai`, `rag` |
| `--rag` | off | Register RAG and configure Qdrant, model settings, and Docker PDF support |
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
minix init my_app --rag
```

---

## `minix add rag`

Run in an existing project with `config.py` and PostgreSQL as the default database.
Registers `AuthModule` and `RagModule`, adds missing RAG environment keys while
preserving existing values, and adds Docker dependencies (the `rag` extra and
Poppler), and the `rag` extra on the minix requirement in `pyproject.toml` or
`requirements.txt`. Creates `docker-compose.rag.yml` for Qdrant (keep the base Compose
file) and sets `COMPOSE_FILE` and a random `QDRANT_API_KEY` in `.env`.

```bash
minix add rag
poetry lock && poetry install  # or: pip install "minix[rag]"
docker compose up --build
```

Set the model provider's API key in `.env` and create the SQL tables with
`minix db makemigrations -m "add rag" && minix db migrate`. Local PDF ingestion
needs Poppler. Repeated calls preserve the generated files. `--extras rag` at init has the same effect as `--rag`;
`--rag --no-extras` still enables RAG and its required services.

---

## `minix db`

Alembic migrations for the SQL entities of the modules in `installed_modules`.
Each `DATABASES` connection has its own `migrations/<connection>/` and only
manages the tables of entities bound to it (`add_binding(..., connection=...)`).

```bash
minix db makemigrations -m "add orders"   # needs the database running and at head
minix db migrate                          # apply up to head
minix db current                          # where the database is
minix db history                          # all migrations
minix db check                            # fails if entities changed without a migration
```

| Command | Use |
|---------|-----|
| `makemigrations -m "…"` | Generate a migration from entity changes. Writes nothing when there are none. |
| `makemigrations --empty -m "…"` | Blank migration for data changes or hand-written DDL |
| `migrate [REVISION]` | Apply migrations (default `head`) |
| `downgrade REVISION` | Revert (`-1`, an id, `base`). Ask the user first. |
| `current`, `history`, `heads`, `branches`, `show` | Inspect; extra arguments go to Alembic |
| `check` | Missing-migration check |
| `merge -m "merge" heads` | Join two heads after parallel branches each added a migration |
| `stamp REVISION` | Record a revision without running it. Ask the user first. |

Every command takes `--database/-d NAME`; without it, it runs for every
connection that has a `migrations/` directory.

**Review every generated migration before `migrate`:**

- A renamed column or table appears as a drop plus an add, which loses data.
  Replace it with `op.alter_column(..., new_column_name=...)` or `op.rename_table(...)`.
- Adding an enum column on PostgreSQL needs the type created first:
  `sa.Enum(..., name="x").create(op.get_bind(), checkfirst=True)`.
- Tables no installed module owns are never dropped automatically. To drop a
  removed module's tables, write it in an `--empty` migration.

**Errors:**

| Message | Fix |
|---------|-----|
| `Target database is not up to date` | `minix db migrate`, then `makemigrations` again |
| `Multiple head revisions are present` / `Multiple heads are present` | `minix db merge -m "merge" heads`, then `minix db migrate` |
| `No migrations set up` | `minix db init` |
| Connection refused | Start the database (`docker compose up -d`) |

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

### Adding to an existing module

```bash
minix add controller --module=orders             # OrderController + .add_controller(...)
minix add controller OrderAdmin --module=orders  # OrderAdminController
minix add task ShipOrder -m orders               # ShipOrderTask + .add_task(...)
minix add periodic -m orders                     # OrderPeriodicTask
minix add helper -m orders                       # OrderHelperService
minix add consumer -m orders                     # OrderConsumer
minix add binding -m orders                      # Order + OrderSqlRepository + OrderSqlService
minix add binding -m orders --entity=ShopOrder --service=ShopOrderService
```

Each command writes the file, exports it from the subpackage `__init__.py`
and appends `.add_*(...)` to the module chain. Running it again does nothing.
`--module/-m` is required; the optional `NAME` argument sets the class name.
Other options: `--path DIR`, `--force/-f`.

**Names:**

- A class name typed in PascalCase is kept as typed (`-e HTTPLog` → `HTTPLog`);
  snake_case input is converted (`-e http_log` → `HttpLog`).
- `--entity=ShopOrder` alone names the repository and service after it:
  `ShopOrderSqlRepository`, `ShopOrderSqlService`. A binding that would share a
  class with an existing `add_binding(...)` is rejected.

**Table names** (`minix add binding`):

| Entity | `__tablename__` | Example (module `orders`) |
|--------|-----------------|---------------------------|
| The module's first entity | the module name, pluralized | `orders` |
| Every later entity | `<module>_<entity>` in snake_case | `orders_item`, `orders_http_log` |
| Regenerated with `--force` | unchanged from the existing file | |

The CLI writes the name explicitly and fails when it is already declared in
the module's `entities/`. Do not remove or rename a generated `__tablename__`.

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
minix db --help
minix db history --help    # Alembic's own help for passthrough commands
```

---

## After scaffolding (typical agent workflow)

1. `minix add module <feature>`
2. Edit entity columns / service methods / controller routes only as needed.
3. `minix db makemigrations -m "add <feature>"`, review the file, then `minix db migrate`.
4. Run the API via `entries/api.py` (e.g. `uvicorn entries.api:Api --reload`).
5. For multi-repository writes that must succeed or fail together:

```python
from minix.core.connectors import sql_transaction
from minix.core.registry import Registry

with sql_transaction():
    Registry().get(OrderSqlService).create(...)
    Registry().get(PaymentSqlService).create(...)
```

Use `sql_transaction("other_connection")` for a named `DATABASES` entry.
