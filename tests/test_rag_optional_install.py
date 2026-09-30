"""The RAG module is optional: `pip install minix` never needs its dependencies,
and `pip install "minix[rag]"` is all it takes to use it.

These pin the packaging contract from the inside:

* nothing outside `minix/core/modules/rag/` imports the RAG package or any of its
  third-party dependencies, so the rest of minix imports with the extra absent;
* touching the RAG module without the extra raises an ImportError that names the
  command to run, instead of an opaque ModuleNotFoundError;
* the `rag` extra declares every dependency the RAG code imports (including the
  PostgreSQL driver), so no second extra is needed.
"""
import pathlib
import re
import subprocess
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MINIX = _ROOT / "minix"
_RAG = _MINIX / "core" / "modules" / "rag"

# Third-party top-level packages that only the RAG extra provides.
_RAG_ONLY_DEPS = (
    "langchain_core", "langchain_litellm", "langchain_qdrant",
    "langchain_text_splitters", "litellm", "pdf2image", "PIL", "psycopg2",
    "landingai",
)
_IMPORT = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", re.M)


def _python_files():
    for path in _MINIX.rglob("*.py"):
        if "__pycache__" not in path.parts:
            yield path


def test_nothing_outside_the_rag_package_imports_it_or_its_dependencies():
    offenders = []
    for path in _python_files():
        if _RAG in path.parents:
            continue
        for m in _IMPORT.finditer(path.read_text()):
            target = m.group(1)
            if target.startswith("minix.core.modules.rag") or target.split(".")[0] in _RAG_ONLY_DEPS:
                offenders.append(f"{path.relative_to(_ROOT)}: {target}")
    assert not offenders, "non-RAG code depends on the optional RAG extra:\n" + "\n".join(offenders)


def test_rag_package_has_no_stray_top_level_home():
    """The RAG building blocks live inside the module, like config / session /
    dependencies do in `modules/oidc`, not in a second package next to the
    framework layers."""
    assert not (_MINIX / "core" / "rag").exists()


_PROBE = r"""
import importlib.util

# Simulate an environment without the extra: the packages are not findable.
_HIDDEN = {"langchain_core", "litellm"}
_real_find_spec = importlib.util.find_spec
importlib.util.find_spec = lambda name, package=None: (
    None if name.split(".")[0] in _HIDDEN else _real_find_spec(name, package)
)

import minix.core.modules.rag as rag      # the package itself imports fine
try:
    rag.RagModule
except ImportError as e:
    print("HINT:" + str(e))
else:
    print("NO ERROR")
"""


def test_missing_extra_raises_an_actionable_import_error():
    out = subprocess.run(
        [sys.executable, "-c", _PROBE], capture_output=True, text=True, cwd=_ROOT, timeout=120,
    )
    assert out.returncode == 0, out.stderr[-1500:]
    hint = out.stdout.strip().splitlines()[-1]
    assert hint.startswith("HINT:"), hint
    assert 'pip install "minix[rag]"' in hint


def test_rag_extra_declares_every_third_party_import():
    import tomllib

    extra = tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]["rag"]
    declared = {re.split(r"[<>=!~\[ ]", d, maxsplit=1)[0].lower().replace("_", "-") for d in extra}
    # import name -> distribution name
    wanted = {
        "langchain_core": "langchain-core",
        "langchain_litellm": "langchain-litellm", "langchain_qdrant": "langchain-qdrant",
        "langchain_text_splitters": "langchain-text-splitters", "litellm": "litellm",
        "qdrant_client": "qdrant-client", "pdf2image": "pdf2image",
        "PIL": "pillow", "psycopg2": "psycopg2-binary", "multipart": "python-multipart",
    }
    imported = set()
    for path in _RAG.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for m in _IMPORT.finditer(path.read_text()):
            top = m.group(1).split(".")[0]
            if top in wanted:
                imported.add(top)
    missing = {wanted[t] for t in imported} - declared
    assert not missing, f"imported by the RAG code but absent from the `rag` extra: {sorted(missing)}"
    # The driver SqlConnector needs for PostgreSQL ships in the same extra.
    assert "psycopg2-binary" in declared
