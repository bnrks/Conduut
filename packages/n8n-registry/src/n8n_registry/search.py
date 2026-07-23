"""Node/workflow card search and contract responses."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .cards import legacy_template_response, workflow_card_response, workflow_search_response
from .models import NodeContract, NodeInfo, WorkflowCard, WorkflowTemplate

# Alias: kullanıcı bu kelimeleri yazarsa hangi node type'ları gösterilsin
_NODE_ALIASES: dict[str, list[str]] = {
    "email": ["gmail", "microsoftoutlook", "smtp", "imap", "emailsendsmt"],
    "mail": ["gmail", "microsoftoutlook", "smtp", "imap"],
    "send email": ["gmail", "microsoftoutlook", "smtp"],
    "sheet": ["googlesheets", "airtable", "notion"],
    "spreadsheet": ["googlesheets", "airtable"],
    "excel": ["microsoftexcel", "googlesheets"],
    "database": ["postgres", "mysql", "mongodb", "redis", "supabase"],
    "db": ["postgres", "mysql", "mongodb", "redis"],
    "sql": ["postgres", "mysql", "microsoftsql"],
    "message": ["slack", "discord", "telegram", "twilio"],
    "chat": ["slack", "discord", "telegram"],
    "notify": ["slack", "discord", "telegram", "gmail"],
    "notification": ["slack", "discord", "telegram", "gmail"],
    "file": ["googledrive", "dropbox", "s3", "ftp", "readwritefile"],
    "storage": ["googledrive", "dropbox", "s3"],
    "timer": ["scheduletrigger"],
    "schedule": ["scheduletrigger"],
    "cron": ["scheduletrigger"],
    "trigger": ["scheduletrigger", "webhook", "manualtrigger"],
    "http": ["httprequest"],
    "api": ["httprequest"],
    "request": ["httprequest"],
    "fetch": ["httprequest"],
    "rest": ["httprequest"],
    "code": ["code"],
    "function": ["code"],
    "javascript": ["code"],
    "python": ["code"],
    "script": ["code"],
    "transform": ["set", "code"],
    "condition": ["if", "switch", "filter"],
    "branch": ["if", "switch"],
    "loop": ["splitinbatches", "code"],
    "iterate": ["splitinbatches"],
    "ai": ["openai", "anthropic", "langchain"],
    "llm": ["openai", "anthropic", "langchain"],
    "gpt": ["openai"],
    "claude": ["anthropic"],
    "chatgpt": ["openai"],
    "count": ["code", "set"],
    "word count": ["code"],
    "string": ["code", "set"],
    "text": ["code", "set"],
    "parse": ["code", "set"],
    "split": ["code", "splitinbatches"],
}


def _score_node(node: NodeInfo, query: str) -> int:
    q = query.lower().strip()
    name_lower = node.display_name.lower()
    type_lower = node.type_name.lower()

    if type_lower == f"n8n-nodes-base.{q}" or type_lower == q:
        return 100
    if name_lower == q:
        return 90
    if name_lower.startswith(q):
        return 75
    if type_lower.endswith(f".{q}"):
        return 70
    if q in name_lower:
        return 55
    if q in type_lower:
        return 50
    if q in node.description.lower():
        return 30
    if q in node.category.lower():
        return 15

    alias_targets = _NODE_ALIASES.get(q, [])
    for alias in alias_targets:
        if alias in type_lower or alias in name_lower:
            return 40
    return 0


def search_nodes(query: str, nodes: list[NodeInfo], limit: int = 8) -> list[NodeInfo]:
    terms = query.lower().split()
    scored: list[tuple[int, NodeInfo]] = []
    for node in nodes:
        if len(terms) == 1:
            score = _score_node(node, terms[0])
        else:
            scores = [_score_node(node, term) for term in terms]
            score = sum(scores) // len(scores)
            if all(item == 0 for item in scores):
                score = 0
        if score > 0:
            scored.append((score, node))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [node for _, node in scored[:limit]]


def get_node_by_type(type_name: str, nodes: list[NodeInfo]) -> NodeInfo | None:
    type_lower = type_name.lower().strip()
    for node in nodes:
        if node.type_name.lower() == type_lower:
            return node
        if node.type_name.split(".")[-1].lower() == type_lower:
            return node
    return None


def _set_node_example(node: NodeInfo) -> dict[str, Any]:
    return {
        "id": "node2",
        "name": "Edit Fields (Set)",
        "type": node.type_name,
        "typeVersion": node.type_version,
        "position": [750, 300],
        "parameters": {
            "mode": "manual",
            "assignments": {
                "assignments": [
                    {
                        "id": "message",
                        "name": "message",
                        "type": "string",
                        "value": "hello from Conduut",
                    }
                ]
            },
            "options": {},
        },
    }


def _condition_rule_example() -> dict[str, Any]:
    return {
        "id": "condition-1",
        "leftValue": "={{ $json.status }}",
        "operator": {"type": "string", "operation": "equals"},
        "rightValue": "pending",
    }


def _conditions_example() -> dict[str, Any]:
    return {
        "options": {
            "caseSensitive": True,
            "leftValue": "",
            "typeValidation": "strict",
            "version": 2,
        },
        "combinator": "and",
        "conditions": [_condition_rule_example()],
    }


def _if_node_example(node: NodeInfo) -> dict[str, Any]:
    return {
        "id": "node1",
        "name": "If",
        "type": node.type_name,
        "typeVersion": node.type_version,
        "position": [500, 300],
        "parameters": {"conditions": _conditions_example()},
    }


def _filter_node_example(node: NodeInfo) -> dict[str, Any]:
    return {
        "id": "node1",
        "name": "Filter",
        "type": node.type_name,
        "typeVersion": node.type_version,
        "position": [500, 300],
        "parameters": {"conditions": _conditions_example()},
    }


def _code_node_example(node: NodeInfo) -> dict[str, Any]:
    return {
        "id": "node1",
        "name": "Code",
        "type": node.type_name,
        "typeVersion": node.type_version,
        "position": [500, 300],
        "parameters": {
            "mode": "runOnceForAllItems",
            "language": "javaScript",
            "jsCode": (
                "const items = $input.all();\n"
                "return items.filter(item => item.json.status !== 'sent');"
            ),
        },
    }


def _ensure_key_parameter(schema: dict[str, Any], parameter: dict[str, Any]) -> None:
    key_parameters = schema.setdefault("keyParameters", [])
    if not isinstance(key_parameters, list):
        schema["keyParameters"] = [parameter]
        return
    target_name = parameter.get("name")
    for existing in key_parameters:
        if existing.get("name") == target_name:
            existing.update({key: value for key, value in parameter.items() if value is not None})
            return
    key_parameters.append(parameter)


def _apply_node_specific_guidance(schema: dict[str, Any], node: NodeInfo) -> None:
    if node.type_name == "n8n-nodes-base.set":
        schema["usageHints"] = [
            (
                "To add or change fields with Edit Fields (Set), use "
                "parameters.assignments.assignments. Each assignment needs id, name, type, "
                "and value. Do not leave assignments empty."
            ),
            (
                "For a field named message, use an assignment like "
                "{id: 'message', name: 'message', type: 'string', value: 'hello'}."
            ),
        ]
        schema["exampleNode"] = _set_node_example(node)
        return

    if node.type_name == "n8n-nodes-base.if":
        schema["usageHints"] = [
            (
                "For IF typeVersion 2+, put rules under parameters.conditions.conditions as a "
                "non-empty list."
            ),
            (
                "Each IF rule must use an operator object like "
                '{"type": "string", "operation": "equals"}, never operator: "equals".'
            ),
        ]
        schema["exampleNode"] = _if_node_example(node)
        return

    if node.type_name == "n8n-nodes-base.filter":
        schema["usageHints"] = [
            (
                "Use Filter for single-path row elimination, such as keeping only unsent "
                "Sheet rows before downstream processing."
            ),
            (
                "For Filter typeVersion 2+, put rules under parameters.conditions.conditions "
                "as a non-empty list and use operator objects like "
                '{"type": "string", "operation": "equals"}.'
            ),
        ]
        schema["exampleNode"] = _filter_node_example(node)
        return

    if node.type_name == "n8n-nodes-base.code":
        _ensure_key_parameter(
            schema,
            {
                "name": "language",
                "displayName": "Language",
                "type": "options",
                "required": False,
                "default": "javaScript",
                "options": ["javaScript", "python", "pythonNative"],
            },
        )
        _ensure_key_parameter(
            schema,
            {
                "name": "jsCode",
                "displayName": "JavaScript Code",
                "type": "string",
                "required": False,
                "default": (
                    "const items = $input.all();\n"
                    "return items.filter(item => item.json.status !== 'sent');"
                ),
            },
        )
        schema["usageHints"] = [
            (
                "For Code node typeVersion 2+, use language='javaScript' with this exact "
                "camel-case spelling when writing JavaScript."
            ),
            (
                "When language is javaScript (or omitted and n8n defaults to JavaScript), "
                "provide non-empty parameters.jsCode."
            ),
        ]
        schema["exampleNode"] = _code_node_example(node)


def _example_parameter_value(prop: dict[str, Any]) -> Any:
    default = prop.get("default")
    if prop.get("type") == "resourceLocator":
        if isinstance(default, dict):
            value = default.get("value")
            if value is None:
                return None
            return {"__rl": True, "mode": default.get("mode") or "list", "value": value}
        if isinstance(default, str) and default:
            return {"__rl": True, "mode": "list", "value": default}
    return default


def _contract_example_params(contract: NodeContract) -> dict[str, Any]:
    example_params: dict[str, Any] = {}
    if contract.resource:
        example_params["resource"] = contract.resource
    if contract.operation:
        example_params["operation"] = contract.operation
    for prop in contract.key_properties:
        name = prop.get("name")
        default = _example_parameter_value(prop)
        if name and default is not None and name not in example_params:
            example_params[name] = default
    return example_params


def _node_contract_semantics(node: NodeInfo, contract: NodeContract) -> dict[str, Any]:
    node_type = node.type_name
    operation = str(contract.operation or "")
    operation_key = operation.casefold()
    required = [
        str(prop.get("name"))
        for prop in contract.key_properties
        if prop.get("required") and prop.get("name")
    ]
    optional = [
        str(prop.get("name"))
        for prop in contract.key_properties
        if not prop.get("required") and prop.get("name") and prop.get("type") != "callout"
    ]
    enum_values = {
        str(prop["name"]): list(prop["options"])
        for prop in contract.key_properties
        if prop.get("name") and isinstance(prop.get("options"), list)
    }
    dynamic_resolvers = [
        {
            "parameter": str(prop.get("name")),
            "typeOptions": dict(prop.get("typeOptions") or {}),
        }
        for prop in contract.key_properties
        if prop.get("name") and (prop.get("typeOptions") or prop.get("modes"))
    ]
    semantics: dict[str, Any] = {
        "requiredParameters": required,
        "optionalParameters": optional,
        "parameterDefaults": {
            str(prop["name"]): prop.get("default")
            for prop in contract.key_properties
            if prop.get("name") and prop.get("default") not in (None, "", [], {})
        },
        "enumValues": enum_values,
        "credentialContract": {
            "acceptedTypes": list(node.credentials),
            "required": bool(node.credentials),
        },
        "inputContract": {
            "shape": "n8n item list",
            "cardinality": "operation-dependent",
        },
        "outputContract": {
            "shape": "n8n item list",
            "cardinality": "operation-dependent",
        },
        "branchBehavior": {"outputs": 1, "routing": "single"},
        "fieldLineage": {"preservesInputItems": None, "preservesInputFields": None},
        "sideEffect": {"kind": "none", "external": False},
        "retryPolicy": {"automaticRetrySafe": True, "requiresIdentityKey": False},
        "identityRules": [],
        "dynamicResolvers": dynamic_resolvers,
        "knownPitfalls": [],
        "validatorRuleIds": [],
        "invalidExamples": [],
    }

    if node_type == "n8n-nodes-base.googleSheets":
        semantics["dynamicResolvers"].append(
            {
                "parameter": "columns.schema",
                "dependsOn": ["documentId.value", "sheetName.value"],
                "resolver": "managed_google_sheets_header_row",
            }
        )
        semantics["knownPitfalls"] = [
            "Write mappings belong under parameters.columns.value.",
            "matchingColumns must name live, non-empty Sheet header columns.",
            "Do not reuse a stale columns.schema from another spreadsheet.",
        ]
        semantics["validatorRuleIds"] = [
            "sheets_columns_shape",
            "sheets_matching_key_live",
            "sheets_dynamic_header_contract",
        ]
        if operation_key in {"append", "appendorupdate", "update"}:
            semantics["sideEffect"] = {"kind": "sheets_row_write", "external": True}
            semantics["retryPolicy"] = {
                "automaticRetrySafe": False,
                "requiresIdentityKey": operation_key != "append",
            }
            semantics["requiredParameters"] = list(
                dict.fromkeys(
                    [
                        *semantics["requiredParameters"],
                        "documentId",
                        "sheetName",
                        "columns.value",
                    ]
                )
            )
            if operation_key in {"appendorupdate", "update"}:
                semantics["requiredParameters"].append("columns.matchingColumns")
                semantics["identityRules"] = [
                    "matchingColumns must be non-empty and present in every input item",
                    "matching column values must survive the full upstream item lineage",
                ]
            semantics["outputContract"]["cardinality"] = "one write receipt per written item"

    elif node_type == "n8n-nodes-base.gmail":
        semantics["knownPitfalls"] = [
            "resource and operation must be selected together.",
            "A successful node status is not a send receipt; require message id and SENT label.",
        ]
        semantics["validatorRuleIds"] = ["gmail_operation_shape", "gmail_sent_receipt"]
        if operation_key in {
            "addlabels",
            "delete",
            "markasread",
            "markasunread",
            "removelabels",
            "reply",
            "send",
            "sendandwait",
            "trash",
            "untrash",
        }:
            semantics["sideEffect"] = {"kind": "gmail_mutation", "external": True}
            semantics["retryPolicy"] = {
                "automaticRetrySafe": False,
                "requiresIdentityKey": True,
            }
        if operation_key == "send":
            semantics["requiredParameters"] = list(
                dict.fromkeys([*semantics["requiredParameters"], "sendTo", "subject", "message"])
            )
            semantics["outputContract"] = {
                "shape": {"id": "string", "labelIds": ["SENT"]},
                "cardinality": "one provider receipt per input item",
            }

    elif node_type in {"n8n-nodes-base.if", "n8n-nodes-base.filter"}:
        semantics["requiredParameters"] = ["conditions.conditions"]
        semantics["fieldLineage"] = {
            "preservesInputItems": True,
            "preservesInputFields": True,
        }
        semantics["knownPitfalls"] = [
            "typeVersion 2+ requires an operator object, not operator='equals'.",
            "Item-scoped predicates must read $json instead of another node's .first().",
        ]
        semantics["validatorRuleIds"] = ["condition_operator_shape", "item_scope_first_forbidden"]
        if node_type.endswith(".if"):
            semantics["branchBehavior"] = {
                "outputs": 2,
                "ports": {"0": "true", "1": "false"},
                "routing": "exactly one branch per input item",
            }
        else:
            semantics["outputContract"]["cardinality"] = "0..N matching input items"

    elif node_type == "n8n-nodes-base.code":
        semantics["requiredParameters"] = ["jsCode when language is javaScript"]
        semantics["fieldLineage"] = {
            "preservesInputItems": None,
            "preservesInputFields": None,
            "responsibility": "Code must explicitly return required identity and write fields",
        }
        semantics["knownPitfalls"] = [
            "Use exact language value javaScript.",
            "runOnceForAllItems code must return an array of n8n items.",
        ]
        semantics["validatorRuleIds"] = ["code_language_exact", "code_body_nonempty"]

    elif node_type == "n8n-nodes-base.set":
        semantics["requiredParameters"] = ["assignments.assignments"]
        semantics["fieldLineage"] = {
            "preservesInputItems": True,
            "preservesInputFields": "unless keepOnlySet/includeOtherFields removes them",
        }
        semantics["knownPitfalls"] = [
            "Assignments belong under parameters.assignments.assignments.",
            "Do not drop identity fields required by downstream writes.",
        ]
        semantics["validatorRuleIds"] = ["set_assignments_shape", "field_lineage_required"]

    elif node_type == "n8n-nodes-base.merge":
        semantics["inputContract"] = {
            "shape": "two n8n item streams",
            "cardinality": "mode-dependent",
        }
        semantics["outputContract"]["cardinality"] = "mode-dependent"
        semantics["knownPitfalls"] = [
            "Combine mode and matching fields determine cardinality and item lineage.",
            "Do not assume input 0 and input 1 have equal item counts.",
        ]
        semantics["validatorRuleIds"] = ["merge_mode_shape", "merge_cardinality_explicit"]

    return semantics


def build_node_contract_response(node: NodeInfo, contract: NodeContract) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "contractKey": contract.key,
        "type": node.type_name,
        "displayName": node.display_name,
        "typeVersion": node.type_version,
        "description": node.description,
        "category": node.category,
        "isTrigger": node.is_trigger,
        "context": {"resource": contract.resource, "operation": contract.operation},
    }

    if node.credentials:
        schema["credentials"] = node.credentials
    if node.resources:
        schema["resources"] = node.resources
    if node.operations:
        all_ops: list[str] = []
        for operations in node.operations.values():
            for operation in operations:
                if operation not in all_ops:
                    all_ops.append(operation)
        if all_ops:
            schema["operations"] = all_ops
    if contract.key_properties:
        schema["keyParameters"] = contract.key_properties

    schema["exampleNode"] = {
        "id": "node1",
        "name": node.display_name,
        "type": node.type_name,
        "typeVersion": node.type_version,
        "position": [500, 300],
        "parameters": _contract_example_params(contract),
    }

    _apply_node_specific_guidance(schema, node)
    schema.update(_node_contract_semantics(node, contract))
    schema["validExample"] = schema["exampleNode"]
    invalid_examples = schema.get("invalidExamples")
    if isinstance(invalid_examples, list) and not invalid_examples:
        schema["invalidExamples"] = [
            {
                "reason": "Missing required operation-conditioned parameters",
                "parameters": {
                    key: value
                    for key, value in _contract_example_params(contract).items()
                    if key in {"resource", "operation"}
                },
            }
        ]
    encoded = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    schema["contractHash"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return schema


def build_schema_response(node: NodeInfo) -> dict[str, Any]:
    contract = (
        node.contracts[0]
        if node.contracts
        else NodeContract(
            key=f"{node.type_name}|v{node.type_version}",
            type_name=node.type_name,
            type_version=node.type_version,
            key_properties=node.key_properties,
        )
    )
    return build_node_contract_response(node, contract)


def _score_workflow_card(card: WorkflowCard, query: str) -> int:
    q = query.lower().strip()
    score = 0
    if q in card.name.lower():
        score += 60
    if q in card.summary.lower():
        score += 35
    if q in card.description.lower():
        score += 25
    for category in card.categories:
        if q in category.lower():
            score += 20
    for node_type in card.node_types:
        if q in node_type.lower():
            score += 10
    for operation in card.operations:
        if q in operation.lower():
            score += 15
    return score


def search_workflow_cards(
    query: str,
    workflow_cards: list[WorkflowCard],
    limit: int = 5,
) -> list[WorkflowCard]:
    terms = query.lower().split()
    scored: list[tuple[int, WorkflowCard]] = []
    for card in workflow_cards:
        score = sum(_score_workflow_card(card, term) for term in terms)
        if score > 0:
            scored.append((score, card))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [card for _, card in scored[:limit]]


def find_templates(
    query: str,
    templates: list[WorkflowTemplate],
    limit: int = 3,
) -> list[WorkflowTemplate]:
    scored: list[tuple[int, WorkflowTemplate]] = []
    terms = query.lower().split()
    for template in templates:
        card = template.card
        score = 0
        if card is not None:
            score = sum(_score_workflow_card(card, term) for term in terms)
        else:
            for term in terms:
                if term in template.name.lower():
                    score += 60
                if term in template.description.lower():
                    score += 30
                for node_type in template.node_types:
                    if term in node_type.lower():
                        score += 10
        if score > 0:
            scored.append((score, template))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [template for _, template in scored[:limit]]


def build_workflow_card_response(card: WorkflowCard) -> dict[str, Any]:
    return workflow_card_response(card)


def build_workflow_card_search_response(card: WorkflowCard) -> dict[str, Any]:
    return workflow_search_response(card)


def build_template_response(template: WorkflowTemplate) -> dict[str, Any]:
    if template.card is not None:
        return legacy_template_response(template.card)
    fallback = WorkflowCard(
        id=template.id,
        name=template.name,
        summary=template.description,
        description=template.description,
        categories=list(template.categories),
        node_types=list(template.node_types),
    )
    return legacy_template_response(fallback)
