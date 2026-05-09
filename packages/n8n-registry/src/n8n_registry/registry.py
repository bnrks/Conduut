"""NodeRegistry — uygulama genelinde tek instance (singleton)."""

import logging
from pathlib import Path

from .loader import (
    fetch_nodes_from_n8n,
    load_nodes_from_file,
    load_templates_from_file,
)
from .models import NodeInfo, WorkflowTemplate
from .search import (
    build_schema_response,
    build_template_response,
    find_templates,
    get_node_by_type,
    search_nodes,
)

log = logging.getLogger(__name__)

# Varsayılan data dizini (packages/n8n-registry/data/)
_DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"


class NodeRegistry:
    """
    n8n node şemaları ve workflow template'lerini bellekte tutar.
    Agent startup'ında initialize_from_n8n() çağrılmalı.
    """

    def __init__(self) -> None:
        self._nodes: list[NodeInfo] = []
        self._templates: list[WorkflowTemplate] = []
        self._loaded: bool = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def template_count(self) -> int:
        return len(self._templates)

    async def initialize_from_n8n(
        self,
        n8n_base_url: str,
        templates_path: str | Path | None = None,
        nodes_path: str | Path | None = None,
    ) -> None:
        """
        n8n node registry'sini başlatır.

        nodes.json kaynağı (öncelik sırası):
        1. nodes_path parametresi (varsa)
        2. Paketin data/nodes.json dosyası
        3. n8n /types/nodes.json HTTP (modern n8n'de auth gerekir — büyük ihtimal çalışmaz)
        """
        log.info("Initializing node registry")

        # 1. Explicit path
        if nodes_path:
            self._nodes = load_nodes_from_file(nodes_path)

        # 2. data/nodes.json next to the installed package
        # Works both locally (packages/n8n-registry/data/) and in Docker (/app/data/)
        if not self._nodes:
            # Try package-relative path (dev environment)
            pkg_data = Path(__file__).parent.parent.parent / "data" / "nodes.json"
            if pkg_data.exists():
                self._nodes = load_nodes_from_file(pkg_data)
            else:
                # Try sibling data dir (Docker: /app/data/ when installed with -e)
                sibling = Path(__file__).parent.parent.parent.parent / "data" / "nodes.json"
                if sibling.exists():
                    self._nodes = load_nodes_from_file(sibling)

        # 3. Fallback: try HTTP (likely 401 on modern n8n — logged as warning, not error)
        if not self._nodes and n8n_base_url:
            self._nodes = await fetch_nodes_from_n8n(n8n_base_url)

        if not self._nodes:
            log.warning(
                "No nodes loaded — run scripts/fetch_nodes.py to populate data/nodes.json"
            )
        else:
            log.info("Registry loaded %d nodes", len(self._nodes))

        if templates_path:
            self._templates = load_templates_from_file(templates_path)

        self._loaded = True

    def load_from_files(
        self,
        nodes_path: str | Path,
        templates_path: str | Path | None = None,
    ) -> None:
        """Daha önce kaydedilmiş dosyalardan yükler (test / offline kullanım)."""
        self._nodes = load_nodes_from_file(nodes_path)
        if templates_path:
            self._templates = load_templates_from_file(templates_path)
        self._loaded = True

    # ------------------------------------------------------------------
    # Search API (tools.py tarafından çağrılır)
    # ------------------------------------------------------------------

    def search_nodes(self, query: str, limit: int = 20) -> list[dict]:
        """
        Query'ye göre node arar.
        Her sonuç: {type, displayName, description, typeVersion, credentials, category, isTrigger}
        """
        if not self._nodes:
            return []
        limit = max(1, min(limit, 50))
        results = search_nodes(query, self._nodes, limit=limit)
        return [
            {
                "type": n.type_name,
                "displayName": n.display_name,
                "description": n.description[:150],
                "typeVersion": n.type_version,
                "credentials": n.credentials,
                "category": n.category,
                "isTrigger": n.is_trigger,
            }
            for n in results
        ]

    def get_node_schema(self, type_name: str) -> dict | None:
        """
        Tek bir node'un tam kondanse şemasını döner.
        type_name: "n8n-nodes-base.gmail" veya kısaltma "gmail"
        """
        node = get_node_by_type(type_name, self._nodes)
        if not node:
            return None
        return build_schema_response(node)

    def find_templates(self, query: str, limit: int = 3) -> list[dict]:
        """Query'ye uygun workflow template'lerini döner."""
        if not self._templates:
            return []
        results = find_templates(query, self._templates, limit=limit)
        return [build_template_response(t) for t in results]


# Uygulama genelinde tek instance
registry = NodeRegistry()
