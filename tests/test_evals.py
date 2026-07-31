import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_runner():
    spec = importlib.util.spec_from_file_location("eval_runner", ROOT / "evals" / "runner.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["eval_runner"] = module
    spec.loader.exec_module(module)
    return module


def test_eval_suites_pass():
    runner = _load_runner()
    result = runner.run()
    assert result["passed"], result
    assert result["decision"] == "continue"

    python_suite = next(s for s in result["suites"] if s["suite"] == "python")
    assert all(case["recall_ok"] for case in python_suite["cases"])


def test_multi_language_recall_when_grammars_present():
    from whyloom.languages import TREE_SITTER_GRAMMARS, _load_parser

    if _load_parser(TREE_SITTER_GRAMMARS[".ts"]) is None:
        return  # grammars optional; base install skips this suite

    runner = _load_runner()
    result = runner.run()
    multi = next((s for s in result["suites"] if s["suite"] == "multi-language"), None)
    assert multi is not None and "skipped" not in multi
    # Every case must reach its expected target, including cross-file ones.
    assert all(case["recall_ok"] for case in multi["cases"])
