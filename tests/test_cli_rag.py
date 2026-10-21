"""CLI integration tests; no databases, model providers, or RAG extras required."""

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values
from typer.testing import CliRunner

from minix.core.cli.cli import app
from minix.core.cli.commands.init_scaffold import minix_pip_install_spec


class RagCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        original = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, original)
        self.version = patch(
            "minix.core.cli.commands.init_scaffold._minix_version_constraint",
            return_value="~=0.3.0",
        )
        self.version.start()
        self.addCleanup(self.version.stop)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.runner = CliRunner()

    def invoke(self, *args, success=True):
        result = self.runner.invoke(app, list(args))
        if success:
            self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
        else:
            self.assertNotEqual(result.exit_code, 0, result.output)
        return result

    def init(self, *args):
        return self.invoke("init", "demo", "--no-extras", "--db-driver", "postgresql", *args)

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def assert_rag_project(self):
        source = (self.root / "config.py").read_text()
        ast.parse(source)
        self.assertEqual(source.count('"minix.core.modules.rag.RagModule"'), 1)
        self.assertEqual(source.count('"minix.core.modules.auth.AuthModule"'), 1)
        for name in (".env", ".env.example"):
            values = dotenv_values(self.root / name)
            self.assertEqual(values["LLM_MODEL"], "gpt-4o")
            self.assertEqual(values["EMBEDDING_DIMENSION"], "1536")
            self.assertEqual(values["QDRANT_URL"], "http://localhost:6333")
        dockerfile = (self.root / "Dockerfile").read_text()
        self.assertIn("poppler-utils", dockerfile)
        self.assertRegex(dockerfile, r'pip install "minix\[[^\]]*rag[^\]]*\]~=0\.3\.0"')
        self.assertNotIn("__BEGIN_", source + dockerfile)

    def test_plain_init_keeps_rag_optional(self):
        self.init()
        self.assertNotIn("RagModule", (self.root / "config.py").read_text())
        self.assertNotIn("LLM_MODEL", (self.root / ".env").read_text())
        self.assertNotIn("qdrant:", (self.root / "docker-compose.yml").read_text())
        self.assertNotIn("poppler", (self.root / "Dockerfile").read_text())

    def test_init_rag_enables_dependencies_even_with_no_extras(self):
        self.init("--rag")
        self.assert_rag_project()
        compose = (self.root / "docker-compose.yml").read_text()
        self.assertIn("  postgres:", compose)
        self.assertIn("  qdrant:", compose)
        self.assertIn("qdrant_connections", (self.root / "config.py").read_text())

    def test_rag_extra_is_an_alias_for_init_flag(self):
        self.invoke("init", "demo", "--extras", "rag", "--db-driver", "postgresql,mysql")
        self.assert_rag_project()
        self.assertEqual(dotenv_values(self.root / ".env")["DB_DRIVER"], "postgresql")

    def test_mysql_only_rag_init_fails_without_writing(self):
        result = self.invoke("init", "demo", "--rag", "--db-driver", "mysql", success=False)
        self.assertIn("requires PostgreSQL", result.output)
        self.assertEqual(self.snapshot(), {})

    def test_add_rag_preserves_values_and_is_idempotent(self):
        self.init()
        with (self.root / ".env").open("a") as stream:
            stream.write("\nLLM_MODEL=custom/model\nOPENAI_API_KEY=keep-me\nQDRANT_PORT=7333\n")
        base_compose = (self.root / "docker-compose.yml").read_bytes()
        self.invoke("add", "rag")
        env = dotenv_values(self.root / ".env")
        self.assertEqual(env["LLM_MODEL"], "custom/model")
        self.assertEqual(env["OPENAI_API_KEY"], "keep-me")
        self.assertEqual(env["QDRANT_PORT"], "7333")
        self.assertEqual(env["QDRANT_URL"], "http://localhost:7333")
        self.assertEqual((self.root / "docker-compose.yml").read_bytes(), base_compose)
        override = (self.root / "docker-compose.rag.yml").read_text()
        self.assertIn("  qdrant:", override)
        self.assertIn("  celery_worker:", override)
        self.assertIn("QDRANT_URL: http://qdrant:6333", override)
        previous = self.snapshot()
        result = self.invoke("add", "rag")
        self.assertIn("already enabled", result.output)
        self.assertEqual(self.snapshot(), previous)

    def test_add_rag_does_not_duplicate_init_dependencies(self):
        self.init("--rag", "--qdrant-port", "7333")
        dockerfile = (self.root / "Dockerfile").read_bytes()
        self.invoke("add", "rag")
        self.assertEqual((self.root / "Dockerfile").read_bytes(), dockerfile)
        override = (self.root / "docker-compose.rag.yml").read_text()
        self.assertNotIn("image: qdrant", override)
        self.assertIn("QDRANT__SERVICE__API_KEY: ${QDRANT_API_KEY:?", override)
        self.assertEqual(dotenv_values(self.root / ".env")["QDRANT_URL"], "http://localhost:7333")

    def test_inline_list_comments_and_unicode_survive_without_running_config(self):
        config = self.root / "config.py"
        config.write_text(
            '# Café\nDATABASES = {"default": {"driver": "postgresql"}}\n'
            'INSTALLED_MODULES = ["my.CustomModule"  # keep this comment\n]\n'
            'raise RuntimeError("project code must not be executed")\n'
        )
        self.invoke("add", "rag")
        source = config.read_text()
        ast.parse(source)
        self.assertIn("# Café", source)
        self.assertIn("# keep this comment", source)
        self.assertIn('"my.CustomModule"', source)
        self.assertIn('"minix.core.modules.auth.AuthModule"', source)
        self.assertIn('"minix.core.modules.rag.RagModule"', source)

    def test_add_rejects_mysql_without_modifying_any_file(self):
        self.invoke("init", "demo", "--no-extras", "--db-driver", "mysql")
        previous = self.snapshot()
        result = self.invoke("add", "rag", success=False)
        self.assertIn("requires PostgreSQL", result.output)
        self.assertEqual(self.snapshot(), previous)

    def test_override_conflict_does_not_partially_modify_project(self):
        self.init()
        (self.root / "docker-compose.rag.yml").write_text("# user customization\n")
        previous = self.snapshot()
        result = self.invoke("add", "rag", success=False)
        self.assertIn("already exists", result.output)
        self.assertEqual(self.snapshot(), previous)

    def test_dynamic_module_list_fails_without_modifying_files(self):
        (self.root / "config.py").write_text(
            'DATABASES = {"default": {"driver": "postgresql"}}\n'
            'INSTALLED_MODULES = load_modules()\n'
        )
        previous = self.snapshot()
        self.invoke("add", "rag", success=False)
        self.assertEqual(self.snapshot(), previous)

    def test_add_requires_a_project(self):
        result = self.invoke("add", "rag", success=False)
        self.assertIn("No config.py", result.output)
        self.assertEqual(self.snapshot(), {})

    def test_db_driver_env_cannot_override_a_hardcoded_mysql_connection(self):
        (self.root / "config.py").write_text(
            'DATABASES = {"default": {"driver": "mysql"}}\nINSTALLED_MODULES = []\n'
        )
        (self.root / ".env").write_text("DB_DRIVER=postgresql\n")
        previous = self.snapshot()
        self.invoke("add", "rag", success=False)
        self.assertEqual(self.snapshot(), previous)

    def test_rag_dependency_cannot_pin_before_its_first_release(self):
        with patch("minix.core.cli.commands.init_scaffold._minix_version_constraint", return_value="~=0.2.2"):
            self.assertEqual(minix_pip_install_spec({"rag"}), "minix[rag]~=0.3.0")


    def test_add_rag_inserts_modules_without_blank_lines(self):
        self.init()
        self.invoke("add", "rag")
        source = (self.root / "config.py").read_text()
        self.assertNotRegex(source, r"\n[ \t]+\n")
        self.assertIn(
            '            # "src.modules.example.ExampleModule",\n'
            '            "minix.core.modules.rag.RagModule",\n'
            "        ]",
            source,
        )

    def test_add_rag_requires_and_generates_a_qdrant_api_key(self):
        self.init()
        self.invoke("add", "rag")
        key = dotenv_values(self.root / ".env")["QDRANT_API_KEY"]
        self.assertRegex(key, r"^[0-9a-f]{48}$")
        self.assertEqual(dotenv_values(self.root / ".env.example")["QDRANT_API_KEY"], "change-me")
        override = (self.root / "docker-compose.rag.yml").read_text()
        self.assertNotIn("QDRANT_API_KEY:-", override)
        self.assertIn("QDRANT__SERVICE__API_KEY: ${QDRANT_API_KEY:?", override)

    def test_init_rag_writes_a_real_qdrant_api_key(self):
        self.init("--rag")
        self.assertRegex(dotenv_values(self.root / ".env")["QDRANT_API_KEY"], r"^[0-9a-f]{48}$")
        self.assertEqual(dotenv_values(self.root / ".env.example")["QDRANT_API_KEY"], "change-me")
        self.assertNotIn("QDRANT_API_KEY:-", (self.root / "docker-compose.yml").read_text())

    def test_add_rag_loads_the_override_through_compose_file(self):
        self.init()
        with (self.root / ".env").open("a") as stream:
            stream.write("\nQDRANT_API_KEY=keep-me\n")
        result = self.invoke("add", "rag")
        env = dotenv_values(self.root / ".env")
        self.assertEqual(env["COMPOSE_FILE"], "docker-compose.yml:docker-compose.rag.yml")
        self.assertEqual(env["COMPOSE_PATH_SEPARATOR"], ":")
        self.assertEqual(env["QDRANT_API_KEY"], "keep-me")
        self.assertIn("Start services: docker compose up --build", result.output)

    def test_add_rag_adds_the_extra_to_dependency_files(self):
        self.init()
        (self.root / "pyproject.toml").write_text(
            '[project]\nname = "demo"\ndependencies = [\n    "minix[postgresql] (>=0.3.1,<0.4.0)",\n'
            '    "minix-helper>=1",\n]\n'
        )
        (self.root / "requirements.txt").write_text("minix~=0.3.1\nrequests\n")
        result = self.invoke("add", "rag")
        self.assertIn('"minix[postgresql,rag] (>=0.3.1,<0.4.0)"', (self.root / "pyproject.toml").read_text())
        self.assertIn('"minix-helper>=1"', (self.root / "pyproject.toml").read_text())
        self.assertEqual((self.root / "requirements.txt").read_text(), "minix[rag]~=0.3.1\nrequests\n")
        self.assertIn("poetry lock", result.output)
        previous = self.snapshot()
        self.invoke("add", "rag")
        self.assertEqual(self.snapshot(), previous)

    def test_add_rag_adds_the_extra_to_poetry_dependencies(self):
        self.init()
        pyproject = self.root / "pyproject.toml"
        pyproject.write_text('[tool.poetry.dependencies]\npython = "^3.12"\nminix = "^0.3.1"\n')
        self.invoke("add", "rag")
        self.assertIn('minix = { version = "^0.3.1", extras = ["rag"] }', pyproject.read_text())
        pyproject.write_text('[tool.poetry.dependencies]\nminix = { version = "^0.3.1", extras = ["postgresql"] }\n')
        self.invoke("add", "rag")
        self.assertIn('extras = ["rag", "postgresql"]', pyproject.read_text())

    def test_empty_qdrant_connections_follow_the_environment(self):
        from types import SimpleNamespace

        from minix.core.conf.minix_settings import exports_from_config

        with patch.dict(os.environ, {"QDRANT_URL": "http://qdrant:6333", "QDRANT_API_KEY": "secret"}):
            exports = exports_from_config(SimpleNamespace(qdrant_connections={}))
        self.assertEqual(exports["QDRANT_CONNECTIONS"]["default"], {"url": "http://qdrant:6333", "api_key": "secret"})

if __name__ == "__main__":
    unittest.main()
