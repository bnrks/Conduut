"""
Agent servisi için n8n node registry singleton'u.
n8n_registry paketini wrap eder ve agent config'iyle initialize eder.
"""

from pathlib import Path

import structlog
from n8n_registry import NodeRegistry

log = structlog.get_logger()

# Uygulama genelinde tek instance
registry: NodeRegistry = NodeRegistry()

# Data dizini: /app/data/ (Dockerfile: COPY packages/n8n-registry/data/ ./data/)
_DATA_DIR = Path(__file__).parent.parent / "data"
_NODES_PATH = _DATA_DIR / "nodes.json"
_TEMPLATES_PATH = _DATA_DIR / "templates.json"
_CREDENTIALS_PATH = _DATA_DIR / "credentials.json"


async def initialize_registry(n8n_base_url: str) -> None:
    """Agent startup'ında çağrılır. n8n'den node şemalarını çeker."""
    await registry.initialize_from_n8n(
        n8n_base_url=n8n_base_url,
        nodes_path=_NODES_PATH if _NODES_PATH.exists() else None,
        templates_path=_TEMPLATES_PATH if _TEMPLATES_PATH.exists() else None,
        credentials_path=_CREDENTIALS_PATH if _CREDENTIALS_PATH.exists() else None,
    )
    log.info(
        "node_registry_ready",
        node_count=registry.node_count,
        template_count=registry.template_count,
        credential_count=registry.credential_count,
    )
