"""Resolve the bundled research source without replacing its algorithms."""

import importlib
import importlib.util
from hashlib import sha256
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PYKT_ROOT = (
    ROOT / "research"
    / "363_EpiKT_Causal_Recursive_Con_Supplementary Material"
    / "code" / "pykt-toolkit-main-epikt"
)


def pykt_source_digest() -> str:
    files = sorted((PYKT_ROOT / "pykt").rglob("*.py"))
    if not files:
        raise FileNotFoundError("Bundled pyKT source is missing.")
    digest = sha256()
    for path in files:
        digest.update(path.relative_to(PYKT_ROOT).as_posix().encode("utf-8") + b"\0")
        digest.update(sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _load_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None or not path.is_file():
        raise FileNotFoundError(f"Bundled pyKT module missing: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def preprocessing_module(name: str):
    # The splitter is standalone, so data preparation does not require PyTorch.
    return _load_file(f"_querystep_pykt_{name}", PYKT_ROOT / "pykt/preprocess" / f"{name}.py")


def epikt_analysis():
    return _load_file("_querystep_epikt_analysis",
                      PYKT_ROOT.parent / "analysis/analyze_epikt_branches.py")


def bundled_pykt():
    expected = PYKT_ROOT / "pykt" / "__init__.py"
    if not expected.is_file():
        raise FileNotFoundError(f"Bundled pyKT source missing: {expected}")
    root = str(PYKT_ROOT)
    if not sys.path or sys.path[0] != root:
        sys.path.insert(0, root)
    module = importlib.import_module("pykt")
    if Path(module.__file__).resolve() != expected.resolve():
        raise RuntimeError("A different pyKT package is already loaded. Use a fresh process.")
    return module
