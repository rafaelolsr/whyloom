import json

from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.retrieval import compact_context_packet, context_packet
from whyloom.store import GraphStore


def _project(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "infra").mkdir()
    (root / ".whyloom").mkdir()
    (root / "src" / "auth.py").write_text(
        "class BaseAuth:\n    pass\n\n"
        "class AzureAuth(BaseAuth):\n"
        "    def exchange(self):\n        return 'token'\n",
        encoding="utf-8",
    )
    (root / "src" / "fetcher.py").write_text(
        "from src.auth import AzureAuth\n\n"
        "class FabricFetcher:\n"
        "    def __init__(self):\n        self.auth = AzureAuth()\n\n"
        "    def get_definition(self):\n        return self._post()\n\n"
        "    def _post(self):\n        return self.auth.exchange()\n\n"
        "    def auth_mode(self):\n        return settings.fabric_auth_mode\n",
        encoding="utf-8",
    )
    (root / "infra" / "app-service.json").write_text(
        json.dumps({"properties": {"fabricAuthMode": "obo", "easyAuthAppClientId": "not-indexed-as-a-value"}}),
        encoding="utf-8",
    )
    return root


def test_project_resolution_configuration_and_communities(tmp_path):
    root = _project(tmp_path)
    result = index_project(root, DEFAULT_CONFIG)
    assert result["indexed"]
    assert result["coverage"]["files_assigned"] == result["coverage"]["files_total"] == 3
    coverage = json.loads((root / result["coverage_manifest"]).read_text(encoding="utf-8"))
    assert coverage["communities"]
    assert all(item["rationale_status"] == "missing" for item in coverage["communities"])

    with GraphStore(root / DEFAULT_CONFIG["database"], create=False) as store:
        rows = store.connection.execute(
            "SELECT source, target, type, provenance FROM edges WHERE type IN ('CALLS','INHERITS') ORDER BY type, source, target"
        ).fetchall()
        config = store.search("fabricAuthMode")
        config_links = store.connection.execute(
            "SELECT source, target FROM edges WHERE origin = 'config-name-resolver'"
        ).fetchall()
        packet = compact_context_packet(context_packet(store, "GetDefinition Fabric authentication", max_depth=4, max_items=40))

    relationships = {(row["source"], row["target"], row["type"], row["provenance"]) for row in rows}
    assert (
        "symbol:src/fetcher.py:FabricFetcher.get_definition",
        "symbol:src/fetcher.py:FabricFetcher._post",
        "CALLS",
        "EXTRACTED",
    ) in relationships
    assert (
        "symbol:src/fetcher.py:FabricFetcher._post",
        "symbol:src/auth.py:AzureAuth.exchange",
        "CALLS",
        "INFERRED",
    ) in relationships
    assert (
        "symbol:src/auth.py:AzureAuth",
        "symbol:src/auth.py:BaseAuth",
        "INHERITS",
        "EXTRACTED",
    ) in relationships
    assert any(item["type"] == "ConfigKey" and item["label"].endswith("fabricAuthMode") for item in config)
    assert any(
        row[0] == "symbol:src/fetcher.py:FabricFetcher.auth_mode"
        and row[1].endswith(":properties.fabricAuthMode")
        for row in config_links
    )
    assert any(item["type"] == "CALLS" for item in packet["relationships"])


def test_structural_communities_are_stable(tmp_path):
    root = _project(tmp_path)
    first = index_project(root, DEFAULT_CONFIG)
    first_coverage = (root / first["coverage_manifest"]).read_text(encoding="utf-8")
    second = index_project(root, DEFAULT_CONFIG)
    second_coverage = (root / second["coverage_manifest"]).read_text(encoding="utf-8")
    assert not second["changed"]
    assert first_coverage == second_coverage


def test_config_reference_resolution_ignores_ambiguous_generic_keys(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "service.py").write_text("def load(settings):\n    return settings.name\n", encoding="utf-8")
    for index in range(8):
        (root / f"config-{index}.json").write_text('{"name": "secret-not-indexed"}\n', encoding="utf-8")
    config = {
        **DEFAULT_CONFIG,
        "include": ["**/*.py", "**/*.json"],
    }

    result = index_project(root, config)

    assert result["indexed"] is True
    with GraphStore(root / config["database"], create=False) as store:
        edges = store.connection.execute("SELECT * FROM edges WHERE type = 'REFERENCES'").fetchall()
    assert edges == []
