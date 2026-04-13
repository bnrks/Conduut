"""
Agent servisi için n8n node registry singleton'u.
n8n_registry paketini wrap eder ve agent config'iyle initialize eder.
"""

import logging
import logging.config
from pathlib import Path

from n8n_registry import NodeRegistry

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Uygulama genelinde tek instance
registry: NodeRegistry = NodeRegistry()

# Data dizini: /app/data/ (Dockerfile: COPY packages/n8n-registry/data/ ./data/)
_DATA_DIR = Path(__file__).parent.parent / "data"
_NODES_PATH = _DATA_DIR / "nodes.json"
_TEMPLATES_PATH = _DATA_DIR / "templates.json"


async def initialize_registry(n8n_base_url: str) -> None:
    """Agent startup'ında çağrılır. n8n'den node şemalarını çeker."""
    await registry.initialize_from_n8n(
        n8n_base_url=n8n_base_url,
        nodes_path=_NODES_PATH if _NODES_PATH.exists() else None,
        templates_path=_TEMPLATES_PATH if _TEMPLATES_PATH.exists() else None,
    )
    log.info(
        "Node registry ready: %d nodes, %d templates",
        registry.node_count,
        registry.template_count,
    )
