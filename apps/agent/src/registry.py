"""
Agent servisi için n8n node registry singleton'u.
n8n_registry paketini wrap eder ve agent config'iyle initialize eder.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import structlog
from n8n_registry import NodeRegistry

from src.config import settings

log = structlog.get_logger()

# Uygulama genelinde tek instance
registry: NodeRegistry = NodeRegistry()


def _resolve_registry_data_dir(source_file: Path | None = None) -> Path:
    """Resolve Docker's /app/data or the source checkout registry data."""

    source = (source_file or Path(__file__)).resolve()
    runtime_data = source.parent.parent / "data"
    if runtime_data.exists():
        return runtime_data

    for parent in source.parents:
        checkout_data = parent / "packages" / "n8n-registry" / "data"
        if checkout_data.exists():
            return checkout_data
    return runtime_data


# Dockerfile copies registry artifacts to /app/data. Local development reads
# the same generated corpus directly from packages/n8n-registry/data.
_DATA_DIR = _resolve_registry_data_dir()
_NODES_PATH = _DATA_DIR / "nodes.json"
_TEMPLATES_PATH = _DATA_DIR / "templates.json"
_CREDENTIALS_PATH = _DATA_DIR / "credentials.json"
_WORKFLOW_CARDS_PATH = _DATA_DIR / "workflow_cards.jsonl"
_NODE_CARDS_PATH = _DATA_DIR / "node_cards.jsonl"
_RETRIEVAL_INDEX_PATH = _DATA_DIR / "retrieval.sqlite"
_REGISTRY_MANIFEST_PATH = _DATA_DIR / "registry_manifest.json"

registry_card_status: dict[str, Any] = {
    "mode": "observe",
    "ready": False,
    "reason": "not_initialized",
    "dataDir": str(_DATA_DIR),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _card_retrieval_mode() -> str:
    configured = str(settings.workflow_card_retrieval_mode or "auto").strip().lower()
    if configured == "auto":
        return "enforce" if settings.environment.strip().lower() == "production" else "observe"
    if configured not in {"observe", "hybrid", "enforce"}:
        return "observe"
    return configured


def _registry_artifact_readiness() -> tuple[bool, str, dict[str, Any]]:
    required = (
        _NODES_PATH,
        _WORKFLOW_CARDS_PATH,
        _NODE_CARDS_PATH,
        _RETRIEVAL_INDEX_PATH,
        _REGISTRY_MANIFEST_PATH,
    )
    missing = [path.name for path in required if not path.exists()]
    if missing:
        return False, f"missing_artifacts:{','.join(missing)}", {}
    try:
        manifest = json.loads(_REGISTRY_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"invalid_manifest:{type(exc).__name__}", {}
    if manifest.get("artifactVersion") != 2 or manifest.get("finished") is not True:
        return False, "manifest_incomplete_or_unsupported", manifest

    expected_hashes = {
        _WORKFLOW_CARDS_PATH: manifest.get("workflowCardsSha256"),
        _NODE_CARDS_PATH: manifest.get("nodeCardsSha256"),
        _RETRIEVAL_INDEX_PATH: manifest.get("retrievalIndexSha256"),
    }
    expected_hashes[_NODES_PATH] = manifest.get("nodeSchemaSha256")
    for path, expected in expected_hashes.items():
        if not isinstance(expected, str) or not expected or _sha256(path) != expected:
            return False, f"artifact_hash_mismatch:{path.name}", manifest

    expected_version = str(settings.n8n_version or "").strip()
    manifest_version = str(manifest.get("n8nVersion") or "").strip()
    if expected_version and manifest_version != expected_version:
        return False, "n8n_version_mismatch", manifest
    return True, "ready", manifest


async def initialize_registry(n8n_base_url: str) -> None:
    """Initialize the bundled registry, with a dev-only live n8n fallback."""
    mode = _card_retrieval_mode()
    ready, reason, manifest = _registry_artifact_readiness()
    production = settings.environment.strip().lower() == "production"
    if production and ready and not _CREDENTIALS_PATH.exists():
        ready = False
        reason = "missing_artifacts:credentials.json"
    if mode == "enforce" and ready:
        expected_version = str(settings.n8n_version or "").strip()
        manifest_version = str(manifest.get("n8nVersion") or "").strip()
        if not expected_version or not manifest_version:
            ready = False
            reason = "n8n_version_required_in_enforce_mode"
    registry_card_status.update(
        {
            "mode": mode,
            "ready": ready,
            "reason": reason,
            "artifactVersion": manifest.get("artifactVersion"),
            "n8nVersion": manifest.get("n8nVersion"),
            "dataDir": str(_DATA_DIR),
        }
    )
    if (mode == "enforce" or production) and not ready:
        raise RuntimeError(
            "Bundled registry artifacts are required in enforce mode or production "
            f"but are not ready ({reason}). Run packages/n8n-registry/scripts/build_cards.py."
        )
    if not ready:
        log.warning("workflow_card_registry_fallback", mode=mode, reason=reason)

    await registry.initialize_from_n8n(
        n8n_base_url="" if production else n8n_base_url,
        nodes_path=_NODES_PATH if _NODES_PATH.exists() else None,
        templates_path=_TEMPLATES_PATH if _TEMPLATES_PATH.exists() else None,
        credentials_path=_CREDENTIALS_PATH if _CREDENTIALS_PATH.exists() else None,
        workflow_cards_path=_WORKFLOW_CARDS_PATH if ready else None,
        search_index_path=_RETRIEVAL_INDEX_PATH if ready else None,
        enable_workflow_cards=ready,
    )
    log.info(
        "node_registry_ready",
        node_count=registry.node_count,
        template_count=registry.template_count,
        workflow_card_count=registry.workflow_card_count,
        credential_count=registry.credential_count,
        card_retrieval=registry_card_status,
    )


def search_workflow_cards(
    query: str,
    limit: int = 5,
    *,
    services: list[str] | None = None,
    capabilities: list[str] | None = None,
    risk_level: str | None = None,
) -> list[dict[str, Any]]:
    method = getattr(registry, "search_workflow_cards", None)
    if callable(method):
        safe_limit = max(1, min(limit, 10))
        return method(
            query,
            limit=safe_limit,
            services=services,
            capabilities=capabilities,
            risk_level=risk_level,
        )
    log.info("workflow_card_search_unavailable")
    return []


def get_workflow_card(card_id: str) -> dict[str, Any] | None:
    method = getattr(registry, "get_workflow_card", None)
    if callable(method):
        return method(card_id)
    log.info("workflow_card_lookup_unavailable")
    return None


def get_node_contract(
    node_type: str,
    *,
    type_version: int | float | None = None,
    resource: str | None = None,
    operation: str | None = None,
) -> dict[str, Any] | None:
    method = getattr(registry, "get_node_contract", None)
    if callable(method):
        return method(
            node_type,
            type_version=type_version,
            resource=resource,
            operation=operation,
        )
    log.info(
        "node_contract_lookup_unavailable",
        node_type=node_type,
        type_version=type_version,
        resource=resource,
        operation=operation,
    )
    return None
