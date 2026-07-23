"""NodeRegistry — in-memory node contracts, workflow cards, and FTS search."""

from __future__ import annotations

import logging
from pathlib import Path

from .cards import legacy_template_response
from .fts import CardSearchIndex
from .loader import (
    fetch_nodes_from_n8n,
    load_credentials_from_file,
    load_nodes_from_file,
    load_templates_from_file,
    load_workflow_templates_from_jsonl,
)
from .models import CredentialTypeInfo, NodeInfo, WorkflowCard, WorkflowTemplate
from .search import (
    build_node_contract_response,
    build_schema_response,
    build_template_response,
    build_workflow_card_response,
    build_workflow_card_search_response,
    find_templates,
    get_node_by_type,
    search_nodes,
    search_workflow_cards,
)

log = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"
_DEFAULT_WORKFLOW_CARDS_PATH = _DEFAULT_DATA_DIR / "workflow_cards.jsonl"
_DEFAULT_RETRIEVAL_DB_PATH = _DEFAULT_DATA_DIR / "retrieval.sqlite"


class NodeRegistry:
    """Holds node schemas, workflow cards, and credential definitions in memory."""

    def __init__(self) -> None:
        self._nodes: list[NodeInfo] = []
        self._templates: list[WorkflowTemplate] = []
        self._workflow_cards: list[WorkflowCard] = []
        self._credentials: list[CredentialTypeInfo] = []
        self._node_by_type: dict[str, NodeInfo] = {}
        self._workflow_card_by_id: dict[str, WorkflowCard] = {}
        self._search_index: CardSearchIndex | None = None

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def template_count(self) -> int:
        return len(self._templates)

    @property
    def workflow_card_count(self) -> int:
        return len(self._workflow_cards)

    @property
    def credential_count(self) -> int:
        return len(self._credentials)

    async def initialize_from_n8n(
        self,
        n8n_base_url: str,
        templates_path: str | Path | None = None,
        nodes_path: str | Path | None = None,
        credentials_path: str | Path | None = None,
        workflow_cards_path: str | Path | None = None,
        search_index_path: str | Path | None = None,
        enable_workflow_cards: bool = True,
    ) -> None:
        log.info("Initializing node registry")

        if nodes_path:
            self._nodes = load_nodes_from_file(nodes_path)

        if not self._nodes:
            pkg_data = Path(__file__).parent.parent.parent / "data" / "nodes.json"
            sibling = Path(__file__).parent.parent.parent.parent / "data" / "nodes.json"
            if pkg_data.exists():
                self._nodes = load_nodes_from_file(pkg_data)
            elif sibling.exists():
                self._nodes = load_nodes_from_file(sibling)

        if not self._nodes and n8n_base_url:
            self._nodes = await fetch_nodes_from_n8n(n8n_base_url)

        if self._nodes:
            self._node_by_type = {node.type_name.lower(): node for node in self._nodes}
            log.info("Registry loaded %d nodes", len(self._nodes))
        else:
            log.warning("No nodes loaded — run scripts/fetch_nodes.py to populate data/nodes.json")

        cards_path = (
            Path(workflow_cards_path) if workflow_cards_path else _DEFAULT_WORKFLOW_CARDS_PATH
        )
        if enable_workflow_cards and cards_path.exists():
            self._templates = load_workflow_templates_from_jsonl(cards_path)
        elif templates_path:
            self._templates = load_templates_from_file(templates_path)
        else:
            pkg_templates = Path(__file__).parent.parent.parent / "data" / "templates.json"
            sibling_templates = (
                Path(__file__).parent.parent.parent.parent / "data" / "templates.json"
            )
            if pkg_templates.exists():
                self._templates = load_templates_from_file(pkg_templates)
            elif sibling_templates.exists():
                self._templates = load_templates_from_file(sibling_templates)

        self._workflow_cards = (
            [template.card for template in self._templates if template.card is not None]
            if enable_workflow_cards
            else []
        )
        self._workflow_card_by_id = {str(card.id): card for card in self._workflow_cards}

        if credentials_path:
            self._credentials = load_credentials_from_file(credentials_path)

        if not self._credentials:
            pkg_creds = Path(__file__).parent.parent.parent / "data" / "credentials.json"
            sibling_creds = Path(__file__).parent.parent.parent.parent / "data" / "credentials.json"
            if pkg_creds.exists():
                self._credentials = load_credentials_from_file(pkg_creds)
            elif sibling_creds.exists():
                self._credentials = load_credentials_from_file(sibling_creds)

        if self._credentials:
            log.info("Registry loaded %d credentials", len(self._credentials))
        else:
            log.warning("No credentials loaded — credentials.json not found")

        self._build_search_index(
            search_index_path=search_index_path if enable_workflow_cards else ":memory:"
        )

    def _build_search_index(self, *, search_index_path: str | Path | None = None) -> None:
        if self._search_index is not None:
            self._search_index.close()
        node_cards = [node.card for node in self._nodes if node.card is not None]
        index_path = Path(search_index_path) if search_index_path else _DEFAULT_RETRIEVAL_DB_PATH
        if search_index_path and index_path.exists():
            loaded = CardSearchIndex.load(index_path)
            if loaded is not None:
                self._search_index = loaded
                return
        self._search_index = CardSearchIndex.build(
            workflow_cards=self._workflow_cards,
            node_cards=node_cards,
            path=index_path,
        )

    def search_nodes(self, query: str, limit: int = 20) -> list[dict]:
        if not self._nodes:
            return []
        safe_limit = max(1, min(limit, 50))
        ordered_nodes: list[NodeInfo] = []
        seen_types: set[str] = set()

        if self._search_index is not None:
            for type_name in self._search_index.search_node_cards(query, limit=safe_limit):
                node = self._node_by_type.get(type_name.lower())
                if node is None:
                    continue
                ordered_nodes.append(node)
                seen_types.add(node.type_name.lower())

        for node in search_nodes(query, self._nodes, limit=safe_limit):
            if node.type_name.lower() in seen_types:
                continue
            ordered_nodes.append(node)
            seen_types.add(node.type_name.lower())
            if len(ordered_nodes) >= safe_limit:
                break

        return [
            {
                "type": node.type_name,
                "displayName": node.display_name,
                "description": node.description[:150],
                "typeVersion": node.type_version,
                "credentials": node.credentials,
                "category": node.category,
                "isTrigger": node.is_trigger,
            }
            for node in ordered_nodes[:safe_limit]
        ]

    def get_node_schema(self, type_name: str) -> dict | None:
        node = get_node_by_type(type_name, self._nodes)
        if node is None:
            return None
        return build_schema_response(node)

    def get_node_contract(
        self,
        type_name: str,
        *,
        type_version: int | float | None = None,
        resource: str | None = None,
        operation: str | None = None,
    ) -> dict | None:
        node = get_node_by_type(type_name, self._nodes)
        if node is None:
            return None

        if type_version is not None and node.type_version != type_version:
            return {
                "error": (
                    f"Node type '{type_name}' is available only at typeVersion "
                    f"{node.type_version} in this registry snapshot."
                ),
                "availableTypeVersions": [node.type_version],
            }

        normalized_resource = (
            resource.strip() if isinstance(resource, str) and resource.strip() else None
        )
        normalized_operation = (
            operation.strip() if isinstance(operation, str) and operation.strip() else None
        )

        contracts = list(node.contracts)
        if normalized_resource is not None:
            contracts = [
                contract
                for contract in contracts
                if str(contract.resource or "").casefold() == normalized_resource.casefold()
            ]
        if normalized_operation is not None:
            contracts = [
                contract
                for contract in contracts
                if str(contract.operation or "").casefold() == normalized_operation.casefold()
            ]

        if not contracts:
            return None

        available_resources = sorted(
            {
                contract.resource
                for contract in contracts
                if isinstance(contract.resource, str) and contract.resource
            }
        )
        if normalized_resource is None and len(available_resources) > 1:
            return {
                "type": node.type_name,
                "typeVersion": node.type_version,
                "availableResources": available_resources,
                "hint": "Pass resource=... to select an exact node contract.",
            }

        available_operations = sorted(
            {
                contract.operation
                for contract in contracts
                if isinstance(contract.operation, str) and contract.operation
            }
        )
        if normalized_operation is None and len(available_operations) > 1:
            return {
                "type": node.type_name,
                "typeVersion": node.type_version,
                "resource": normalized_resource,
                "availableOperations": available_operations,
                "hint": "Pass operation=... to select an exact node contract.",
            }

        return build_node_contract_response(node, contracts[0])

    def search_workflow_cards(
        self,
        query: str,
        limit: int = 5,
        *,
        services: list[str] | None = None,
        capabilities: list[str] | None = None,
        risk_level: str | None = None,
    ) -> list[dict]:
        if not self._workflow_cards:
            return []
        safe_limit = max(1, min(limit, 20))
        service_filter = {item.casefold() for item in (services or []) if item.strip()}
        capability_filter = {item.casefold() for item in (capabilities or []) if item.strip()}
        risk_filter = str(risk_level or "").strip().casefold()

        def matches(card: WorkflowCard) -> bool:
            card_services = {item.casefold() for item in card.services}
            card_capabilities = {item.casefold() for item in card.capabilities}
            return (
                (not service_filter or service_filter.issubset(card_services))
                and (not capability_filter or capability_filter.issubset(card_capabilities))
                and (not risk_filter or card.risk_level.casefold() == risk_filter)
            )

        ordered_cards: list[WorkflowCard] = []
        seen_ids: set[str] = set()

        if self._search_index is not None:
            for card_id in self._search_index.search_workflow_cards(
                query,
                limit=max(safe_limit * 5, 20),
            ):
                card = self._workflow_card_by_id.get(card_id)
                if card is None or not matches(card):
                    continue
                ordered_cards.append(card)
                seen_ids.add(str(card.id))

        for card in search_workflow_cards(query, self._workflow_cards, limit=safe_limit):
            if str(card.id) in seen_ids or not matches(card):
                continue
            ordered_cards.append(card)
            seen_ids.add(str(card.id))
            if len(ordered_cards) >= safe_limit:
                break

        return [build_workflow_card_search_response(card) for card in ordered_cards[:safe_limit]]

    def get_workflow_card(self, template_id: int | str) -> dict | None:
        card = self._workflow_card_by_id.get(str(template_id))
        if card is None:
            return None
        return build_workflow_card_response(card)

    def find_templates(self, query: str, limit: int = 3) -> list[dict]:
        safe_limit = max(1, min(limit, 20))
        results = find_templates(query, self._templates, limit=safe_limit)
        if results:
            output: list[dict] = []
            for template in results:
                if template.card is not None:
                    output.append(legacy_template_response(template.card))
                else:
                    output.append(build_template_response(template))
            return output
        return [build_template_response(template) for template in self._templates[:safe_limit]]

    def list_credential_catalog(self, query: str | None = None) -> list[dict]:
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
        for cred in self._credentials:
            if cred.name == type_name:
                return cred
        return None


registry = NodeRegistry()
