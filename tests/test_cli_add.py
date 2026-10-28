"""`minix add module` / `minix add <component>` tests."""

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from minix.core.cli.cli import app


class AddBindingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        original = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, original)
        sys.path.insert(0, str(self.root))
        self.addCleanup(sys.path.remove, str(self.root))
        self.addCleanup(self._forget_packages)

    def _forget_packages(self):
        for name in [m for m in sys.modules if m.split(".")[0] in ("src", "app")]:
            del sys.modules[name]

    def invoke(self, *args, success=True):
        result = CliRunner().invoke(app, list(args))
        if success:
            self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
        else:
            self.assertNotEqual(result.exit_code, 0, result.output)
        return result

    def tables(self, package):
        entities = importlib.import_module(package)
        return {getattr(entities, name).__table__.name for name in entities.__all__}

    def entity_file(self, module, stem):
        return (self.root / "src/modules" / module / "entities" / f"{stem}_entity.py").read_text()

    def test_each_binding_gets_its_own_table(self):
        self.invoke("add", "module", "intake_discoveries", "--no-register")
        self.invoke("add", "binding", "-m", "intake_discoveries", "-e", "Role")
        self.invoke("add", "binding", "-m", "intake_discoveries", "-e", "Status")

        # `minix add module` output is unchanged.
        self.assertIn(
            '"""SQL entity for the ``intake_discoveries`` module."""\n\n'
            '    __tablename__ = "intake_discoveries"\n\n    name:',
            self.entity_file("intake_discoveries", "intake_discovery"),
        )
        self.assertEqual(
            self.tables("src.modules.intake_discoveries.entities"),
            {"intake_discoveries", "intake_discoveries_role", "intake_discoveries_status"},
        )

    def test_custom_path_keeps_the_module_prefix(self):
        self.invoke("add", "module", "disc", "--path", "app/disc", "--no-register")
        self.invoke("add", "binding", "-m", "disc", "--path", "app/disc", "-e", "Role")
        self.assertEqual(self.tables("app.disc.entities"), {"discs", "disc_role"})

    def test_force_keeps_the_existing_table(self):
        self.invoke("add", "module", "orders", "--no-register")
        self.invoke("add", "binding", "-m", "orders", "-e", "Item")
        self.invoke("add", "binding", "-m", "orders", "--force")
        self.invoke("add", "binding", "-m", "orders", "-e", "Item", "--force")
        self.assertIn('__tablename__ = "orders"', self.entity_file("orders", "order"))
        self.assertIn('__tablename__ = "orders_item"', self.entity_file("orders", "item"))

    def test_entities_outside_add_binding_count(self):
        self.invoke("add", "module", "legacy", "--no-binding", "--no-register")
        entities = self.root / "src/modules/legacy/entities"
        entities.mkdir()
        (entities / "old_entity.py").write_text(
            "from minix.core.entity import SqlEntity\n\n\n"
            "class Old(SqlEntity):\n    __tablename__ = \"legacies\"\n"
        )
        (entities / "__init__.py").write_text(
            "from src.modules.legacy.entities.old_entity import Old\n\n__all__ = [\"Old\"]\n"
        )
        self.invoke("add", "binding", "-m", "legacy", "-e", "Thing")
        self.assertEqual(self.tables("src.modules.legacy.entities"), {"legacies", "legacy_thing"})

    def test_pascal_case_names_are_kept(self):
        self.invoke("add", "module", "orders", "--no-register")
        self.invoke("add", "binding", "-m", "orders", "-e", "HTTPLog")
        entities = importlib.import_module("src.modules.orders.entities")
        self.assertEqual(entities.HTTPLog.__table__.name, "orders_http_log")

    def test_taken_table_is_rejected(self):
        self.invoke("add", "module", "orders", "--no-register")
        self.invoke("add", "binding", "-m", "orders", "-e", "Item")
        item = self.root / "src/modules/orders/entities/item_entity.py"
        item.write_text(item.read_text() + '\n\nclass Clash(SqlEntity):\n    __tablename__ = "orders_widget"\n')
        result = self.invoke("add", "binding", "-m", "orders", "-e", "Widget", success=False)
        self.assertIn("'orders_widget' is already used by", result.output)


if __name__ == "__main__":
    unittest.main()
