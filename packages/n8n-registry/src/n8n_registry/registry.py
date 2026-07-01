"""NodeRegistry — uygulama genelinde tek instance (singleton)."""

import logging
from pathlib import Path

from .loader import (
    fetch_nodes_from_n8n,
    load_credentials_from_file,
    load_nodes_from_file,
    load_templates_from_file,
)
from .models import CredentialTypeInfo, NodeInfo, WorkflowTemplate
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
        self._credentials: list[CredentialTypeInfo] = []

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def template_count(self) -> int:
        return len(self._templates)

    @property
    def credential_count(self) -> int:
        return len(self._credentials)

    async def initialize_from_n8n(
        self,
        n8n_base_url: str,
        templates_path: str | Path | None = None,
        nodes_path: str | Path | None = None,
        credentials_path: str | Path | None = None,
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

        if credentials_path:
            self._credentials = load_credentials_from_file(credentials_path)

        if not self._credentials:
            pkg_creds = Path(__file__).parent.parent.parent / "data" / "credentials.json"
            if pkg_creds.exists():
                self._credentials = load_credentials_from_file(pkg_creds)
            else:
                sibling_creds = (
                    Path(__file__).parent.parent.parent.parent / "data" / "credentials.json"
                )
                if sibling_creds.exists():
                    self._credentials = load_credentials_from_file(sibling_creds)

        if self._credentials:
            log.info("Registry loaded %d credentials", len(self._credentials))
        else:
            log.warning("No credentials loaded — credentials.json not found")

    # ------------------------------------------------------------------
    # Search API (agent tools paketi tarafından çağrılır)
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

    def list_credential_catalog(self, query: str | None = None) -> list[dict]:
        """Fillable (non-OAuth, non-generic) credential types as a catalog.

        Each entry: {type, label, icon_url}. Sorted by label; query matches
        the display name or type name (case-insensitive substring).
        """
        needle = (query or "").strip().lower()
        out: list[dict] = []
        for cred in self._credentials:
            if cred.is_oauth or cred.generic_auth:
                continue
            name_match = needle in cred.display_name.lower() or needle in cred.name.lower()
            if needle and not name_match:
                continue
            out.append({"type": cred.name, "label": cred.display_name, "icon_url": cred.icon_url})
        out.sort(key=lambda item: item["label"].lower())
        return out

    def get_credential_definition(self, type_name: str) -> CredentialTypeInfo | None:
        """Return the full CredentialTypeInfo for a given credential type name."""
        for cred in self._credentials:
            if cred.name == type_name:
                return cred
        return None


# Uygulama genelinde tek instance
registry = NodeRegistry()
