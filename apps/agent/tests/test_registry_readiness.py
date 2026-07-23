import hashlib
import json

import pytest

from src import registry as registry_module
from src.config import settings


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_registry_data_dir_prefers_runtime_then_source_checkout(tmp_path):
    source_file = tmp_path / "apps" / "agent" / "src" / "registry.py"
    source_file.parent.mkdir(parents=True)
    source_file.touch()
    checkout_data = tmp_path / "packages" / "n8n-registry" / "data"
    checkout_data.mkdir(parents=True)

    assert registry_module._resolve_registry_data_dir(source_file) == checkout_data

    runtime_data = tmp_path / "apps" / "agent" / "data"
    runtime_data.mkdir(parents=True)

    assert registry_module._resolve_registry_data_dir(source_file) == runtime_data


def test_registry_artifact_readiness_checks_hashes_and_version(tmp_path, monkeypatch):
    nodes = tmp_path / "nodes.json"
    workflow_cards = tmp_path / "workflow_cards.jsonl"
    node_cards = tmp_path / "node_cards.jsonl"
    index = tmp_path / "retrieval.sqlite"
    manifest = tmp_path / "registry_manifest.json"
    for path, content in (
        (nodes, "[]"),
        (workflow_cards, '{"id":"1"}\n'),
        (node_cards, '{"type_name":"x"}\n'),
        (index, "sqlite"),
    ):
        path.write_text(content, encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "artifactVersion": 2,
                "finished": True,
                "n8nVersion": "1.100.0",
                "nodeSchemaSha256": _sha256(nodes),
                "workflowCardsSha256": _sha256(workflow_cards),
                "nodeCardsSha256": _sha256(node_cards),
                "retrievalIndexSha256": _sha256(index),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(registry_module, "_NODES_PATH", nodes)
    monkeypatch.setattr(registry_module, "_WORKFLOW_CARDS_PATH", workflow_cards)
    monkeypatch.setattr(registry_module, "_NODE_CARDS_PATH", node_cards)
    monkeypatch.setattr(registry_module, "_RETRIEVAL_INDEX_PATH", index)
    monkeypatch.setattr(registry_module, "_REGISTRY_MANIFEST_PATH", manifest)
    monkeypatch.setattr(settings, "n8n_version", "1.100.0")

    ready, reason, _manifest = registry_module._registry_artifact_readiness()

    assert ready is True
    assert reason == "ready"

    monkeypatch.setattr(registry_module, "_NODES_PATH", tmp_path / "missing-nodes.json")
    ready, reason, _manifest = registry_module._registry_artifact_readiness()
    assert ready is False
    assert reason == "missing_artifacts:missing-nodes.json"

    monkeypatch.setattr(registry_module, "_NODES_PATH", nodes)
    workflow_cards.write_text('{"id":"changed"}\n', encoding="utf-8")
    ready, reason, _manifest = registry_module._registry_artifact_readiness()
    assert ready is False
    assert reason == "artifact_hash_mismatch:workflow_cards.jsonl"


@pytest.mark.asyncio
async def test_registry_enforce_mode_fails_closed_without_artifacts(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    monkeypatch.setattr(registry_module, "_WORKFLOW_CARDS_PATH", missing / "workflow_cards.jsonl")
    monkeypatch.setattr(registry_module, "_NODE_CARDS_PATH", missing / "node_cards.jsonl")
    monkeypatch.setattr(registry_module, "_RETRIEVAL_INDEX_PATH", missing / "retrieval.sqlite")
    monkeypatch.setattr(registry_module, "_REGISTRY_MANIFEST_PATH", missing / "manifest.json")
    monkeypatch.setattr(settings, "workflow_card_retrieval_mode", "enforce")

    with pytest.raises(RuntimeError, match="required in enforce mode"):
        await registry_module.initialize_registry("")


@pytest.mark.asyncio
async def test_registry_observe_fallback_disables_workflow_cards(monkeypatch):
    observed = {}

    async def fake_initialize_from_n8n(**kwargs):
        observed.update(kwargs)

    fake_registry = type(
        "FakeRegistry",
        (),
        {
            "initialize_from_n8n": staticmethod(fake_initialize_from_n8n),
            "node_count": 0,
            "template_count": 0,
            "workflow_card_count": 0,
            "credential_count": 0,
        },
    )()
    monkeypatch.setattr(
        registry_module,
        "_registry_artifact_readiness",
        lambda: (False, "artifact_hash_mismatch:workflow_cards.jsonl", {}),
    )
    monkeypatch.setattr(registry_module, "registry", fake_registry)
    monkeypatch.setattr(settings, "workflow_card_retrieval_mode", "observe")

    await registry_module.initialize_registry("")

    assert observed["enable_workflow_cards"] is False
    assert observed["workflow_cards_path"] is None
    assert observed["search_index_path"] is None


@pytest.mark.asyncio
async def test_registry_enforce_mode_requires_explicit_n8n_version(tmp_path, monkeypatch):
    nodes = tmp_path / "nodes.json"
    workflow_cards = tmp_path / "workflow_cards.jsonl"
    node_cards = tmp_path / "node_cards.jsonl"
    index = tmp_path / "retrieval.sqlite"
    manifest = tmp_path / "registry_manifest.json"
    for path, content in (
        (nodes, "[]"),
        (workflow_cards, '{"id":"1"}\n'),
        (node_cards, '{"type_name":"x"}\n'),
        (index, "sqlite"),
    ):
        path.write_text(content, encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "artifactVersion": 2,
                "finished": True,
                "n8nVersion": None,
                "nodeSchemaSha256": _sha256(nodes),
                "workflowCardsSha256": _sha256(workflow_cards),
                "nodeCardsSha256": _sha256(node_cards),
                "retrievalIndexSha256": _sha256(index),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(registry_module, "_NODES_PATH", nodes)
    monkeypatch.setattr(registry_module, "_WORKFLOW_CARDS_PATH", workflow_cards)
    monkeypatch.setattr(registry_module, "_NODE_CARDS_PATH", node_cards)
    monkeypatch.setattr(registry_module, "_RETRIEVAL_INDEX_PATH", index)
    monkeypatch.setattr(registry_module, "_REGISTRY_MANIFEST_PATH", manifest)
    monkeypatch.setattr(settings, "workflow_card_retrieval_mode", "enforce")
    monkeypatch.setattr(settings, "n8n_version", "")

    with pytest.raises(RuntimeError, match="n8n_version_required_in_enforce_mode"):
        await registry_module.initialize_registry("")
