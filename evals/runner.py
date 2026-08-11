from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from pathlib import Path

from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.retrieval import context_packet
from whyloom.store import GraphStore

ROOT = Path(__file__).resolve().parents[1]


def terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9_-]+", text.casefold()) if len(term) > 2}


_SEARCH_SUFFIXES = (".md", ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".cs")


def flat_search(root: Path, task: str, limit: int = 8) -> dict:
    query = terms(task)
    started = time.perf_counter()
    matches = []
    files = [path for suffix in _SEARCH_SUFFIXES for path in root.rglob(f"*{suffix}")]
    for path in files:
        relative_parts = path.relative_to(root).parts
        if any(part in {".git", ".venv"} for part in relative_parts) or relative_parts[:2] == (".whyloom", "cache"):
            continue
        body = path.read_text(encoding="utf-8")
        score = len(query & terms(f"{path.as_posix()} {body}"))
        if score:
            matches.append({"path": path.relative_to(root).as_posix(), "body": body, "score": score})
    matches.sort(key=lambda item: (-item["score"], item["path"]))
    matches = matches[:limit]
    return {
        "items": matches,
        "characters": sum(len(item["body"]) for item in matches),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }


SUITES = [
    {
        "name": "python",
        "fixture": ROOT / "tests" / "fixtures" / "sample_repo",
        "cases": ROOT / "evals" / "cases" / "cases.json",
        "gate": "recall+precision",
    },
    {
        "name": "multi-language",
        "fixture": ROOT / "evals" / "fixtures" / "multi_lang",
        "cases": ROOT / "evals" / "cases" / "cases_multi_lang.json",
        "gate": "recall",
    },
    {
        # Zero-record retrieval: proves the day-zero graph finds the RIGHT file
        # with no rationale records at all, including two ranking traps a naive
        # lexical search fails — term-frequency (a noise file repeating a query
        # word) and file-monopoly (a symbol-dense file burying a sparse relevant
        # one). Gates on recall; this is the benefit measured in the benchmark.
        "name": "zero-record-retrieval",
        "fixture": ROOT / "evals" / "fixtures" / "zero_record",
        "cases": ROOT / "evals" / "cases" / "cases_zero_record.json",
        "gate": "recall",
    },
]


def run_suite(fixture: Path, cases_path: Path, gate: str = "recall+precision") -> list[dict]:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    results = []
    with tempfile.TemporaryDirectory() as directory:
        repo = Path(directory) / "repo"
        shutil.copytree(fixture, repo)
        index_project(repo, DEFAULT_CONFIG)
        with GraphStore(repo / DEFAULT_CONFIG["database"]) as store:
            for case in cases:
                baseline = flat_search(repo, case["task"])
                started = time.perf_counter()
                packet = context_packet(store, case["task"])
                graph_ms = round((time.perf_counter() - started) * 1000, 2)
                expected_records = set(case["expected_records"])
                expected_targets = set(case["expected_targets"])
                record_ids = {item["id"] for item in packet["governing_records"]}
                file_paths = {item["path"] for item in packet["files"] if item["path"]}

                def graph_relevant(item: dict) -> bool:
                    if item["id"] in expected_records or item.get("path") in expected_targets or item.get("source_path") in expected_targets:
                        return True
                    via = item.get("via") or {}
                    expected_nodes = expected_records | {f"file:{path}" for path in expected_targets}
                    return via.get("source") in expected_nodes or via.get("target") in expected_nodes

                graph_irrelevant = sum(not graph_relevant(item) for item in packet["evidence"])
                baseline_irrelevant = sum(
                    item["path"] not in expected_targets
                    and not any(identifier in item["body"] for identifier in expected_records)
                    for item in baseline["items"]
                )
                recall_ok = expected_records.issubset(record_ids) and expected_targets.issubset(file_paths)
                precision_ok = graph_irrelevant <= baseline_irrelevant
                # Python suite gates on both (the original A/B claim). The
                # multi-language suite gates on recall only: its purpose is to
                # prove cross-file traversal that grep cannot do at all, and a
                # tiny fixture makes graph expansion look imprecise even when the
                # right target is found. Precision is still reported.
                passed = recall_ok if gate == "recall" else (recall_ok and precision_ok)
                results.append(
                    {
                        "id": case["id"],
                        "passed": passed,
                        "recall_ok": recall_ok,
                        "precision_ok": precision_ok,
                        "whyloom": {
                            "records": sorted(record_ids),
                            "files": sorted(file_paths),
                            "irrelevant_items": graph_irrelevant,
                            "characters": len(json.dumps(packet)),
                            "elapsed_ms": graph_ms,
                        },
                        "baseline": {
                            "paths": [item["path"] for item in baseline["items"]],
                            "irrelevant_items": baseline_irrelevant,
                            "characters": baseline["characters"],
                            "elapsed_ms": baseline["elapsed_ms"],
                        },
                    }
                )
    return results


def run() -> dict:
    """Run every suite and aggregate. Multi-language suites are skipped (not
    failed) when their tree-sitter grammar is unavailable, so the base install
    still reports a clean result."""
    from whyloom.languages import TREE_SITTER_GRAMMARS, _load_parser

    grammars_ready = _load_parser(TREE_SITTER_GRAMMARS[".ts"]) is not None
    suites = []
    for suite in SUITES:
        if suite["name"] == "multi-language" and not grammars_ready:
            suites.append({"suite": suite["name"], "skipped": "tree-sitter grammars not installed", "cases": []})
            continue
        cases = run_suite(suite["fixture"], suite["cases"], suite.get("gate", "recall+precision"))
        suites.append(
            {
                "suite": suite["name"],
                "gate": suite.get("gate", "recall+precision"),
                "passed": all(c["passed"] for c in cases),
                "cases": cases,
            }
        )

    scored = [s for s in suites if "passed" in s]
    all_passed = all(s["passed"] for s in scored)
    return {
        "passed": all_passed,
        "decision": "continue" if all_passed else "revise",
        "suites": suites,
    }


if __name__ == "__main__":
    import sys

    result = run()
    print(json.dumps(result, indent=2))
    # Exit non-zero on any eval-suite failure so CI gates retrieval quality — a
    # regression fails the build, it is not merely reported.
    sys.exit(0 if result["passed"] else 1)
