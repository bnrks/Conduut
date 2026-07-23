"""Shared typed oracle contracts derived from deterministic assurance analysis."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.agent.assurance.analyzer import analyze_workflow_semantics
from src.agent.schemas import OracleContextSource, OracleContract, Postcondition
from src.registry import get_node_contract

_POSTCONDITION_CODES = {
    "every action has a provider receipt": "action_provider_receipt",
    "every successful action has one write-back": "successful_action_writeback",
    "write-back identity is non-empty and unique": "writeback_identity_live",
}


def build_oracle_contract(
    workflow: dict[str, Any] | None,
    *,
    context_source: OracleContextSource = "missing",
) -> OracleContract:
    if not workflow:
        return OracleContract(contextSource=context_source)

    report = analyze_workflow_semantics(
        list(workflow.get("nodes") or []),
        workflow.get("connections") or {},
    )
    plan = report.plan
    action_nodes = sorted(name for name, role in plan.node_roles.items() if role == "action")
    writeback_nodes = sorted(name for name, role in plan.node_roles.items() if role == "writeback")
    mutation_nodes = [*action_nodes, *writeback_nodes]
    node_contract_hashes: dict[str, str] = {}
    expected_effects: dict[str, str] = {}
    contract_candidates = 0
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_name = str(node.get("name") or node.get("type") or "")
        node_type = str(node.get("type") or "")
        parameters = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}
        operation = str(parameters.get("operation") or "") or None
        resource = str(parameters.get("resource") or "") or None
        contract_candidates += 1
        contract = get_node_contract(
            node_type,
            type_version=(
                node.get("typeVersion")
                if isinstance(node.get("typeVersion"), (int, float))
                else None
            ),
            resource=resource,
            operation=operation,
        )
        if isinstance(contract, dict) and not any(
            key in contract for key in ("error", "availableResources", "availableOperations")
        ):
            contract_hash = str(contract.get("contractHash") or "")
            if not contract_hash:
                encoded = json.dumps(
                    contract,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
                contract_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            node_contract_hashes[node_name] = contract_hash
        if node_name in action_nodes and node_type == "n8n-nodes-base.gmail":
            expected_effects[node_name] = "gmail_message_sent"
        elif node_name in writeback_nodes and node_type == "n8n-nodes-base.googleSheets":
            expected_effects[node_name] = "sheets_row_updated"
    expected_postconditions = [
        Postcondition(
            code=_POSTCONDITION_CODES.get(description, "workflow_postcondition"),
            description=description,
            status="pending",
        )
        for description in plan.expected_postconditions
    ]
    return OracleContract(
        fingerprint=plan.fingerprint,
        contextSource=context_source,
        nodeContractHashes=node_contract_hashes,
        contractCoverage=(
            "full"
            if contract_candidates and len(node_contract_hashes) == contract_candidates
            else "partial"
            if node_contract_hashes
            else "none"
        ),
        actionNodes=action_nodes,
        writebackNodes=writeback_nodes,
        mutationNodes=mutation_nodes,
        expectedEffects=expected_effects,
        identityFields={key: list(value) for key, value in plan.identity_fields.items()},
        cardinalityRelations=list(plan.cardinality_relations),
        expectedPostconditions=expected_postconditions,
        claimScope=(
            ["action_verified", "postcondition_verified"]
            if writeback_nodes
            else ["action_verified"]
            if action_nodes
            else ["structurally_valid"]
        ),
    )
