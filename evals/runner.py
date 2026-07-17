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


def flat_search(root: Path, task: str, limit: int = 8) -> dict:
    query = terms(task)
    started = time.perf_counter()
    matches = []
    for path in [*root.rglob("*.md"), *root.rglob("*.py")]:
        if any(part in {".whyloom", ".git", ".venv"} for part in path.parts):
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


def run() -> dict:
    cases = json.loads((ROOT / "evals" / "cases" / "cases.json").read_text(encoding="utf-8"))
    fixture = ROOT / "tests" / "fixtures" / "sample_repo"
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
                results.append(
                    {
                        "id": case["id"],
                        "passed": recall_ok and precision_ok,
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
    return {
        "passed": all(item["passed"] for item in results),
        "decision": "continue" if all(item["passed"] for item in results) else "revise",
        "cases": results,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
