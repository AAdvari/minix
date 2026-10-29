"""`minix db` tests. Set MINIX_TEST_POSTGRES_PORT (user/password minix) to also
run the migration round trip against a real PostgreSQL server."""

import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from alembic.operations import ops
from sqlalchemy import Column, Enum, Integer, MetaData, Table
from typer.testing import CliRunner

from minix.core.cli.cli import app
from minix.core.conf import settings
from minix.core.entity import SqlEntity
from minix.core.migrations import connection_tables, version_table
from minix.core.migrations.env import _drop_enum_types
from minix.core.module import BusinessModule
from minix.core.repository import SqlRepository
from minix.core.service import Service


class DbTestOrderEntity(SqlEntity):
    __tablename__ = "db_test_orders"


class DbTestEventEntity(SqlEntity):
    __tablename__ = "db_test_events"


class DbTestCacheEntity(SqlEntity):
    __tablename__ = "db_test_cache"


class NotSqlRepository:
    pass


class ProjectTestCase(unittest.TestCase):
    """Runs the CLI inside a fresh temporary project directory."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        original = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, original)
        version = patch(
            "minix.core.cli.commands.init_scaffold._minix_version_constraint",
            return_value="~=0.3.0",
        )
        version.start()
        self.addCleanup(version.stop)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.addCleanup(self._forget_project)
        self.runner = CliRunner()

    def _forget_project(self):
        # Each test has its own config.py; drop the cached module and settings.
        sys.modules.pop("config", None)
        settings._wrapped = None
        while str(self.root) in sys.path:
            sys.path.remove(str(self.root))

    def invoke(self, *args, success=True):
        result = self.runner.invoke(app, list(args))
        if success:
            self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
        else:
            self.assertNotEqual(result.exit_code, 0, result.output)
        return result

    def init(self, *args):
        return self.invoke("init", "demo", "--no-extras", "--db-driver", "postgresql", *args)


class DbCliTests(ProjectTestCase):
    def test_init_scaffolds_migrations_per_sql_connection(self):
        result = self.invoke("init", "demo", "--no-extras", "--db-driver", "postgresql,mysql")
        for connection in ("default", "mysql"):
            directory = self.root / "migrations" / connection
            self.assertTrue((directory / "alembic.ini").is_file())
            self.assertTrue((directory / "script.py.mako").is_file())
            self.assertTrue((directory / "versions").is_dir())
            self.assertIn(f"run_migrations({connection!r}", (directory / "env.py").read_text())
        self.assertIn("minix db makemigrations", result.output)

    def test_db_init_keeps_existing_files(self):
        self.init()
        env_py = self.root / "migrations" / "default" / "env.py"
        env_py.write_text("# customized\n")
        result = self.invoke("db", "init")
        self.assertEqual(env_py.read_text(), "# customized\n")
        self.assertIn("already set up", result.output)

    def test_db_init_restores_a_removed_directory(self):
        self.init()
        for path in sorted((self.root / "migrations").rglob("*"), reverse=True):
            path.rmdir() if path.is_dir() else path.unlink()
        result = self.invoke("db", "init")
        self.assertIn("migrations/default/env.py", result.output)

    def test_db_init_skips_clickhouse(self):
        self.invoke("init", "demo", "--extras", "clickhouse", "--db-driver", "postgresql")
        result = self.invoke("db", "init", "--database", "clickhouse")
        self.assertIn("skipped 'clickhouse'", result.output)
        self.assertFalse((self.root / "migrations" / "clickhouse").exists())

    def test_db_init_rejects_unknown_connections(self):
        self.init()
        result = self.invoke("db", "init", "--database", "nope", success=False)
        self.assertIn("Not in settings.DATABASES: nope", result.output)

    def test_db_commands_require_a_project(self):
        for args in (("init",), ("makemigrations",), ("migrate",)):
            result = self.invoke("db", *args, success=False)
            self.assertIn("No config.py found", result.output)

    def test_migrate_requires_db_init(self):
        self.init()
        for path in sorted((self.root / "migrations").rglob("*"), reverse=True):
            path.rmdir() if path.is_dir() else path.unlink()
        result = self.invoke("db", "migrate", success=False)
        self.assertIn("minix db init", result.output)
        result = self.invoke("db", "migrate", "--database", "default", success=False)
        self.assertIn("minix db init --database default", result.output)

    def test_other_alembic_commands_pass_through(self):
        self.init()
        self.invoke("db", "makemigrations", "--empty", "-m", "first")
        self.assertIn("first", self.invoke("db", "history", "-v").output)
        self.assertIn("(head)", self.invoke("db", "heads").output)
        self.assertIn("usage: minix db history", self.invoke("db", "history", "--help").output)
        result = self.invoke("db", "history", "--database", "nope", success=False)
        self.assertIn("minix db init --database nope", result.output)

    def test_add_rag_points_to_the_migration_commands(self):
        self.init()
        result = self.invoke("add", "rag")
        self.assertIn('minix db makemigrations -m "add rag" && minix db migrate', result.output)
        self.assertNotIn("minix db init &&", result.output)


class ConnectionTablesTests(unittest.TestCase):
    def test_tables_follow_the_binding_connection(self):
        module = (
            BusinessModule("db_test")
            .add_binding(DbTestOrderEntity, SqlRepository, Service)
            .add_binding(DbTestEventEntity, SqlRepository, Service, connection="analytics")
            .add_binding(DbTestCacheEntity, NotSqlRepository, Service)
        )
        self.assertEqual(list(connection_tables("default", [module])), ["db_test_orders"])
        self.assertEqual(list(connection_tables("analytics", [module])), ["db_test_events"])
        self.assertEqual(connection_tables("other", [module]), {})

    def test_version_table_is_distinct_per_connection(self):
        self.assertEqual(version_table("default"), "alembic_version")
        self.assertEqual(version_table("analytics"), "alembic_version_analytics")


class DropEnumTypesTests(unittest.TestCase):
    def test_downgrade_drops_each_enum_type_once_after_the_tables(self):
        metadata = MetaData()
        role = Enum("ADMIN", "USER", name="userrole")
        first = Table("first", metadata, Column("id", Integer, primary_key=True), Column("role", role))
        second = Table("second", metadata, Column("id", Integer, primary_key=True), Column("role", role))
        downgrade = ops.DowngradeOps(ops=[
            ops.DropTableOp.from_table(first),
            ops.DropTableOp.from_table(second),
        ])
        _drop_enum_types(downgrade)
        self.assertIsInstance(downgrade.ops[1], ops.DropTableOp)
        self.assertEqual(len(downgrade.ops), 3)
        self.assertEqual(downgrade.ops[2].sqltext, 'DROP TYPE IF EXISTS "userrole"')


@unittest.skipUnless(os.environ.get("MINIX_TEST_POSTGRES_PORT"), "set MINIX_TEST_POSTGRES_PORT")
class PostgresMigrationTests(ProjectTestCase):
    def setUp(self):
        port = os.environ["MINIX_TEST_POSTGRES_PORT"]
        super().setUp()
        import psycopg

        self.database = f"minix_test_{uuid.uuid4().hex[:8]}"
        admin = f"postgresql://minix:minix@localhost:{port}/postgres"
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{self.database}"')

        def drop():
            with psycopg.connect(admin, autocommit=True) as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{self.database}" WITH (FORCE)')

        self.addCleanup(drop)
        self.init("--db-port", port)
        os.environ.update(DB_DATABASE=self.database, DB_PORT=port, DB_PASS="minix")

    def tables(self):
        from sqlalchemy import create_engine, inspect

        port = os.environ["DB_PORT"]
        engine = create_engine(f"postgresql+psycopg://minix:minix@localhost:{port}/{self.database}")
        try:
            return set(inspect(engine).get_table_names())
        finally:
            engine.dispose()

    def test_round_trip(self):
        result = self.invoke("db", "makemigrations", "-m", "initial")
        self.assertIn("default: wrote migrations/default/versions/", result.output)
        self.invoke("db", "migrate")
        self.assertIn("api_keys", self.tables())
        self.assertIn("(head)", self.invoke("db", "current").output)
        self.invoke("db", "check")

        result = self.invoke("db", "makemigrations", "-m", "again")
        self.assertIn("default: no changes detected", result.output)
        self.assertEqual(len(list((self.root / "migrations/default/versions").glob("*.py"))), 1)

        # The enum type goes with the table, so upgrading again works.
        self.invoke("db", "downgrade", "-1")
        self.assertEqual(self.tables(), {"alembic_version"})
        self.invoke("db", "migrate")
        self.assertIn("api_keys", self.tables())

    def test_unknown_tables_are_never_dropped(self):
        from sqlalchemy import create_engine, text

        port = os.environ["DB_PORT"]
        engine = create_engine(f"postgresql+psycopg://minix:minix@localhost:{port}/{self.database}")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE legacy_orders (id integer primary key)"))
        engine.dispose()
        self.invoke("db", "makemigrations", "-m", "initial")
        revision = next((self.root / "migrations/default/versions").glob("*.py")).read_text()
        self.assertNotIn("legacy_orders", revision)


if __name__ == "__main__":
    unittest.main()
