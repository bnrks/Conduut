"""Tests for the deterministic workflow repair layer (agent.repair)."""

from typing import Any

from src.agent.repair import repair_workflow


class FakeRegistry:
    def __init__(self, schemas: dict[str, dict[str, Any]]):
        self.schemas = schemas

    def get_node_schema(self, node_type: str):
        if node_type in self.schemas:
            return self.schemas[node_type]
        for schema in self.schemas.values():
            if schema["type"].split(".")[-1].lower() == node_type.lower():
                return schema
        return None


SCHEMAS = {
    "n8n-nodes-base.webhook": {
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "isTrigger": True,
    },
    "n8n-nodes-base.code": {
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "isTrigger": False,
    },
    "n8n-nodes-base.gmail": {
        "type": "n8n-nodes-base.gmail",
        "typeVersion": 2.1,
        "isTrigger": False,
    },
    "n8n-nodes-base.emailSend": {
        "type": "n8n-nodes-base.emailSend",
        "typeVersion": 2.1,
        "isTrigger": False,
    },
    "@n8n/n8n-nodes-langchain.agent": {
        "type": "@n8n/n8n-nodes-langchain.agent",
        "typeVersion": 1.7,
        "isTrigger": False,
    },
    "@n8n/n8n-nodes-langchain.lmChatOpenAi": {
        "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
        "typeVersion": 1,
        "isTrigger": False,
    },
    "n8n-nodes-base.googleSheets": {
        "type": "n8n-nodes-base.googleSheets",
        "typeVersion": 4.7,
        "isTrigger": False,
    },
    "n8n-nodes-base.httpRequest": {
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "isTrigger": False,
    },
}

REGISTRY = FakeRegistry(SCHEMAS)


def _node(name, node_type, **kw):
    node = {"name": name, "type": node_type, "parameters": kw.pop("parameters", {})}
    node.update(kw)
    return node


def _all_main_targets(connections):
    targets = []
    for value in connections.values():
        for group in value.get("main", []):
            for conn in group:
                targets.append(conn["node"])
    return targets


# --------------------------------------------------------------------------
# Stage 1 — boilerplate fill
# --------------------------------------------------------------------------


def test_boilerplate_id_typeversion_position_filled():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("Code", "n8n-nodes-base.code", parameters={"jsCode": "return items;"}),
    ]
    repaired, _conns, repairs = repair_workflow(
        nodes,
        {"Webhook": {"main": [[{"node": "Code", "type": "main", "index": 0}]]}},
        registry=REGISTRY,
    )
    for node in repaired:
        assert node.get("id")
        assert isinstance(node["position"], list) and len(node["position"]) == 2
    code = next(n for n in repaired if n["name"] == "Code")
    assert code["typeVersion"] == 2
    webhook = next(n for n in repaired if n["name"] == "Webhook")
    assert webhook.get("webhookId")
    assert repairs  # at least one repair recorded


# --------------------------------------------------------------------------
# Stage 2 — linear connection inference
# --------------------------------------------------------------------------


def test_linear_connections_inferred_when_missing():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("Code", "n8n-nodes-base.code", parameters={"jsCode": "return items;"}),
        _node(
            "Gmail", "n8n-nodes-base.gmail", parameters={"resource": "message", "operation": "send"}
        ),
    ]
    repaired, conns, _ = repair_workflow(nodes, None, registry=REGISTRY)
    assert conns["Webhook"]["main"][0][0]["node"] == "Code"
    assert conns["Code"]["main"][0][0]["node"] == "Gmail"


# --------------------------------------------------------------------------
# Stage 3 — sub-node port repair
# --------------------------------------------------------------------------


def test_chat_model_wired_into_main_moved_to_ai_port():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("OpenAI Chat Model", "@n8n/n8n-nodes-langchain.lmChatOpenAi"),
        _node("AI Agent", "@n8n/n8n-nodes-langchain.agent", parameters={"text": "hi"}),
        _node(
            "Gmail", "n8n-nodes-base.gmail", parameters={"resource": "message", "operation": "send"}
        ),
    ]
    connections = {
        "Webhook": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
        "OpenAI Chat Model": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
        "AI Agent": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]},
    }
    _repaired, conns, repairs = repair_workflow(nodes, connections, registry=REGISTRY)

    # Chat model no longer feeds the main flow anywhere
    assert "OpenAI Chat Model" not in _all_main_targets(conns)
    assert "main" not in conns.get("OpenAI Chat Model", {})
    # It is attached to the agent through the ai_languageModel port
    ai = conns["OpenAI Chat Model"]["ai_languageModel"]
    assert ai[0][0]["node"] == "AI Agent"
    assert ai[0][0]["type"] == "ai_languageModel"
    assert any("ai_languageModel" in r or "sub-node" in r.lower() for r in repairs)


def test_chat_model_left_alone_when_multiple_agents():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("Chat", "@n8n/n8n-nodes-langchain.lmChatOpenAi"),
        _node("Agent A", "@n8n/n8n-nodes-langchain.agent", parameters={"text": "a"}),
        _node("Agent B", "@n8n/n8n-nodes-langchain.agent", parameters={"text": "b"}),
    ]
    connections = {
        "Webhook": {"main": [[{"node": "Agent A", "type": "main", "index": 0}]]},
        "Chat": {"main": [[{"node": "Agent A", "type": "main", "index": 0}]]},
    }
    _repaired, conns, _ = repair_workflow(nodes, connections, registry=REGISTRY)
    # Ambiguous: repair declines, leaves it wired in main for validate to reject.
    assert "main" in conns["Chat"]
    assert "ai_languageModel" not in conns["Chat"]


# --------------------------------------------------------------------------
# Stage 4 — expression repair
# --------------------------------------------------------------------------


def test_bare_input_expression_rewritten_to_trigger_body():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node(
            "AI Agent",
            "@n8n/n8n-nodes-langchain.agent",
            parameters={"text": "Write a proposal for {{input.company}}"},
        ),
    ]
    connections = {"Webhook": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]}}
    repaired, _conns, _ = repair_workflow(
        nodes,
        connections,
        runtime_fields={"company"},
        trigger_name="Webhook",
        registry=REGISTRY,
    )
    agent = next(n for n in repaired if n["name"] == "AI Agent")
    text = agent["parameters"]["text"]
    assert "input.company" not in text
    assert "$('Webhook').first().json.body.company" in text


def test_bare_json_field_rewritten_to_body_for_trigger_fed_node():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node(
            "Code",
            "n8n-nodes-base.code",
            parameters={"jsCode": "const c = $json.company; return [{json:{c}}];"},
        ),
    ]
    connections = {"Webhook": {"main": [[{"node": "Code", "type": "main", "index": 0}]]}}
    repaired, _conns, _ = repair_workflow(
        nodes,
        connections,
        runtime_fields={"company"},
        trigger_name="Webhook",
        registry=REGISTRY,
    )
    code = next(n for n in repaired if n["name"] == "Code")
    assert "$json.body.company" in code["parameters"]["jsCode"]
    assert "$json.company" not in code["parameters"]["jsCode"]


def test_http_array_index_rewritten_for_http_fed_node():
    # n8n's HTTP Request node splits a JSON array response into items, so a node
    # fed by it reads $json.<field>, not $json[0].<field> (which is empty).
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node(
            "Get Quote",
            "n8n-nodes-base.httpRequest",
            parameters={"url": "https://api.api-ninjas.com/v1/quotes"},
        ),
        _node(
            "Send Email",
            "n8n-nodes-base.gmail",
            parameters={
                "resource": "message",
                "operation": "send",
                "sendTo": "x@y.com",
                "subject": "s",
                "message": "=💬 {{ $json[0].quote }}\n— {{ $json[0].author }}",
                "emailType": "text",
            },
        ),
    ]
    connections = {
        "Webhook": {"main": [[{"node": "Get Quote", "type": "main", "index": 0}]]},
        "Get Quote": {"main": [[{"node": "Send Email", "type": "main", "index": 0}]]},
    }
    repaired, _conns, _ = repair_workflow(nodes, connections, registry=REGISTRY)
    msg = next(n for n in repaired if n["name"] == "Send Email")["parameters"]["message"]
    assert "$json.quote" in msg
    assert "$json.author" in msg
    assert "$json[0]" not in msg


def test_http_array_index_rewritten_for_referenced_node():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("Get Quote", "n8n-nodes-base.httpRequest", parameters={"url": "https://x"}),
        _node("Prep", "n8n-nodes-base.code", parameters={"jsCode": "return $input.all();"}),
        _node(
            "Send Email",
            "n8n-nodes-base.gmail",
            parameters={
                "resource": "message",
                "operation": "send",
                "sendTo": "x@y.com",
                "subject": "s",
                "message": "={{ $('Get Quote').first().json[0].quote }}",
                "emailType": "text",
            },
        ),
    ]
    connections = {
        "Webhook": {"main": [[{"node": "Get Quote", "type": "main", "index": 0}]]},
        "Get Quote": {"main": [[{"node": "Prep", "type": "main", "index": 0}]]},
        "Prep": {"main": [[{"node": "Send Email", "type": "main", "index": 0}]]},
    }
    repaired, _conns, _ = repair_workflow(nodes, connections, registry=REGISTRY)
    msg = next(n for n in repaired if n["name"] == "Send Email")["parameters"]["message"]
    assert "$('Get Quote').first().json.quote" in msg
    assert "json[0]" not in msg


def test_http_array_index_left_alone_for_non_http_fed_node():
    # A node fed by a Code node (which may genuinely output an array) is untouched.
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("Get Quote", "n8n-nodes-base.httpRequest", parameters={"url": "https://x"}),
        _node("Build", "n8n-nodes-base.code", parameters={"jsCode": "return [{json:[{a:1}]}]"}),
        _node(
            "Use",
            "n8n-nodes-base.gmail",
            parameters={
                "resource": "message",
                "operation": "send",
                "sendTo": "x@y.com",
                "subject": "s",
                "message": "={{ $json[0].a }}",
                "emailType": "text",
            },
        ),
    ]
    connections = {
        "Webhook": {"main": [[{"node": "Get Quote", "type": "main", "index": 0}]]},
        "Get Quote": {"main": [[{"node": "Build", "type": "main", "index": 0}]]},
        "Build": {"main": [[{"node": "Use", "type": "main", "index": 0}]]},
    }
    repaired, _conns, _ = repair_workflow(nodes, connections, registry=REGISTRY)
    msg = next(n for n in repaired if n["name"] == "Use")["parameters"]["message"]
    assert "$json[0].a" in msg  # Build (Code) is not an HTTP node -> left as-is


def test_template_field_gets_equals_prefix():
    # A field with {{ }} but no leading '=' is sent literally by n8n; repair must
    # turn it into an expression.
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node(
            "AI Agent",
            "@n8n/n8n-nodes-langchain.agent",
            parameters={"text": "Teklif: {{ $json.body.company }}"},
        ),
    ]
    connections = {"Webhook": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]}}
    repaired, _conns, _ = repair_workflow(
        nodes, connections, runtime_fields={"company"}, trigger_name="Webhook", registry=REGISTRY
    )
    agent = next(n for n in repaired if n["name"] == "AI Agent")
    assert agent["parameters"]["text"].startswith("=")


def test_non_trigger_fed_node_qualifies_webhook_reference():
    # Gmail is fed by AI Agent, not the webhook, so $json.body.email is undefined
    # there; it must be qualified to $('Webhook').first().json.body.email.
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("AI Agent", "@n8n/n8n-nodes-langchain.agent", parameters={"text": "hi"}),
        _node(
            "Gmail",
            "n8n-nodes-base.gmail",
            parameters={
                "resource": "message",
                "operation": "send",
                "sendTo": "={{ $json.body.email }}",
                "message": "={{ $('AI Agent').first().json.output }}",
            },
        ),
    ]
    connections = {
        "Webhook": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
        "AI Agent": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]},
    }
    repaired, _conns, _ = repair_workflow(
        nodes, connections, runtime_fields={"email"}, trigger_name="Webhook", registry=REGISTRY
    )
    gmail = next(n for n in repaired if n["name"] == "Gmail")
    assert gmail["parameters"]["sendTo"] == "={{ $('Webhook').first().json.body.email }}"
    # The agent-output reference is already qualified and must be left intact.
    assert gmail["parameters"]["message"] == "={{ $('AI Agent').first().json.output }}"


def test_code_node_jscode_not_prefixed_with_equals():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node(
            "Code",
            "n8n-nodes-base.code",
            parameters={"jsCode": "const c = $json.company; return [{json:{c}}];"},
        ),
    ]
    connections = {"Webhook": {"main": [[{"node": "Code", "type": "main", "index": 0}]]}}
    repaired, _conns, _ = repair_workflow(
        nodes, connections, runtime_fields={"company"}, trigger_name="Webhook", registry=REGISTRY
    )
    code = next(n for n in repaired if n["name"] == "Code")
    assert not code["parameters"]["jsCode"].startswith("=")
    assert "$json.body.company" in code["parameters"]["jsCode"]


def test_body_path_not_rewritten_when_field_not_declared():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node(
            "Code",
            "n8n-nodes-base.code",
            parameters={"jsCode": "const x = $json.other; return [];"},
        ),
    ]
    connections = {"Webhook": {"main": [[{"node": "Code", "type": "main", "index": 0}]]}}
    repaired, _conns, _ = repair_workflow(
        nodes,
        connections,
        runtime_fields={"company"},
        trigger_name="Webhook",
        registry=REGISTRY,
    )
    code = next(n for n in repaired if n["name"] == "Code")
    assert "$json.other" in code["parameters"]["jsCode"]


def test_body_path_idempotent_when_already_body():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node(
            "Code",
            "n8n-nodes-base.code",
            parameters={"jsCode": "const c = $json.body.company; return [];"},
        ),
    ]
    connections = {"Webhook": {"main": [[{"node": "Code", "type": "main", "index": 0}]]}}
    repaired, _conns, _ = repair_workflow(
        nodes,
        connections,
        runtime_fields={"company"},
        trigger_name="Webhook",
        registry=REGISTRY,
    )
    code = next(n for n in repaired if n["name"] == "Code")
    assert code["parameters"]["jsCode"].count("body.company") == 1
    assert "body.body" not in code["parameters"]["jsCode"]


# --------------------------------------------------------------------------
# n8n attribution footer removal
# --------------------------------------------------------------------------


def test_gmail_send_attribution_disabled_by_default():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node(
            "Gmail",
            "n8n-nodes-base.gmail",
            parameters={"resource": "message", "operation": "send", "sendTo": "a@b.com"},
        ),
    ]
    connections = {"Webhook": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]}}
    repaired, _conns, repairs = repair_workflow(nodes, connections, registry=REGISTRY)
    gmail = next(n for n in repaired if n["name"] == "Gmail")
    assert gmail["parameters"]["options"]["appendAttribution"] is False
    assert any("attribution" in r.lower() for r in repairs)


def test_email_send_attribution_disabled_by_default():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("Email", "n8n-nodes-base.emailSend", parameters={"operation": "send"}),
    ]
    connections = {"Webhook": {"main": [[{"node": "Email", "type": "main", "index": 0}]]}}
    repaired, _conns, _ = repair_workflow(nodes, connections, registry=REGISTRY)
    email = next(n for n in repaired if n["name"] == "Email")
    assert email["parameters"]["options"]["appendAttribution"] is False


def test_attribution_respects_explicit_choice():
    nodes = [
        _node(
            "Gmail",
            "n8n-nodes-base.gmail",
            parameters={
                "resource": "message",
                "operation": "send",
                "options": {"appendAttribution": True},
            },
        ),
    ]
    repaired, _conns, _ = repair_workflow(nodes, None, registry=REGISTRY)
    gmail = next(n for n in repaired if n["name"] == "Gmail")
    # An explicit user/model choice must be left untouched.
    assert gmail["parameters"]["options"]["appendAttribution"] is True


def test_attribution_not_applied_to_gmail_read():
    nodes = [
        _node(
            "Gmail",
            "n8n-nodes-base.gmail",
            parameters={"resource": "message", "operation": "get"},
        ),
    ]
    repaired, _conns, _ = repair_workflow(nodes, None, registry=REGISTRY)
    gmail = next(n for n in repaired if n["name"] == "Gmail")
    assert "appendAttribution" not in gmail["parameters"].get("options", {})


# --------------------------------------------------------------------------
# resourceLocator normalization
# --------------------------------------------------------------------------


def test_google_sheets_plain_string_locators_wrapped():
    # The model writes documentId/sheetName as plain strings (its natural prior),
    # but n8n's googleSheets node expects resourceLocator (__rl) objects. Left as
    # strings, n8n reads .value/.mode as undefined -> "Can not get sheet
    # 'undefined' with a value of 'undefined'" at runtime.
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node(
            "Sheets",
            "n8n-nodes-base.googleSheets",
            parameters={
                "resource": "sheet",
                "operation": "append",
                "documentId": "1sNwiUOwJEx2eZS3T1fOyWzxUB6BPQCjVXsPp33h4qvs",
                "sheetName": "Veriler",
            },
        ),
    ]
    connections = {"Webhook": {"main": [[{"node": "Sheets", "type": "main", "index": 0}]]}}
    repaired, _conns, repairs = repair_workflow(nodes, connections, registry=REGISTRY)
    sheets = next(n for n in repaired if n["name"] == "Sheets")
    assert sheets["parameters"]["documentId"] == {
        "__rl": True,
        "mode": "id",
        "value": "1sNwiUOwJEx2eZS3T1fOyWzxUB6BPQCjVXsPp33h4qvs",
    }
    assert sheets["parameters"]["sheetName"] == {
        "__rl": True,
        "mode": "name",
        "value": "Veriler",
    }
    assert any("resourceLocator" in r or "Sheets" in r for r in repairs)


def test_google_sheets_url_documentid_uses_url_mode():
    nodes = [
        _node(
            "Sheets",
            "n8n-nodes-base.googleSheets",
            parameters={
                "resource": "sheet",
                "operation": "append",
                "documentId": "https://docs.google.com/spreadsheets/d/1abcXYZ/edit",
                "sheetName": "Sheet1",
            },
        ),
    ]
    repaired, _conns, _ = repair_workflow(nodes, None, registry=REGISTRY)
    sheets = next(n for n in repaired if n["name"] == "Sheets")
    assert sheets["parameters"]["documentId"]["mode"] == "url"
    assert (
        sheets["parameters"]["documentId"]["value"]
        == "https://docs.google.com/spreadsheets/d/1abcXYZ/edit"
    )


def test_google_sheets_locators_left_when_already_rl():
    already = {"__rl": True, "mode": "id", "value": "abc123"}
    nodes = [
        _node(
            "Sheets",
            "n8n-nodes-base.googleSheets",
            parameters={
                "resource": "sheet",
                "operation": "append",
                "documentId": dict(already),
                "sheetName": {"__rl": True, "mode": "list", "value": "gid=0"},
            },
        ),
    ]
    repaired, _conns, repairs = repair_workflow(nodes, None, registry=REGISTRY)
    sheets = next(n for n in repaired if n["name"] == "Sheets")
    # Already a resourceLocator -> untouched, no spurious repair recorded.
    assert sheets["parameters"]["documentId"] == already
    assert sheets["parameters"]["sheetName"] == {"__rl": True, "mode": "list", "value": "gid=0"}
    assert not any("resourceLocator" in r or "locator" in r.lower() for r in repairs)


# --------------------------------------------------------------------------
# Google Sheets legacy schema upgrade (resource/spreadsheetId/range -> v4)
# --------------------------------------------------------------------------


def test_google_sheets_spreadsheet_resource_read_upgraded_to_v4():
    # The model's pre-v4 prior: resource "spreadsheet" + spreadsheetId + range.
    # On the installed googleSheets v4 node the router dispatches resource
    # "spreadsheet" to a module implementing only create/delete, so "read"
    # resolves to undefined -> TypeError at runtime. Upgrade to resource "sheet"
    # with documentId/sheetName resourceLocators.
    nodes = [
        _node("Schedule", "n8n-nodes-base.code", parameters={"jsCode": "return items;"}),
        _node(
            "Read Siparisler",
            "n8n-nodes-base.googleSheets",
            parameters={
                "resource": "spreadsheet",
                "operation": "read",
                "spreadsheetId": "1efQabc",
                "range": "Siparisler!A:F",
                "authentication": "oAuth2",
            },
        ),
    ]
    connections = {
        "Schedule": {"main": [[{"node": "Read Siparisler", "type": "main", "index": 0}]]}
    }
    repaired, _conns, repairs = repair_workflow(nodes, connections, registry=REGISTRY)
    sheets = next(n for n in repaired if n["name"] == "Read Siparisler")
    params = sheets["parameters"]
    assert params["resource"] == "sheet"
    assert params["documentId"] == {"__rl": True, "mode": "id", "value": "1efQabc"}
    assert params["sheetName"] == {"__rl": True, "mode": "name", "value": "Siparisler"}
    # Legacy keys removed so they can't mislead a later read of the node.
    assert "spreadsheetId" not in params
    assert "range" not in params
    assert any("googleSheets" in r for r in repairs)


def test_google_sheets_update_addressing_upgraded_from_expression_range():
    # An update node addressed a cell via an expression range
    # ("=Siparisler!E{{ $json.row_number }}"). Extract the tab name (the literal
    # before "!") into sheetName; the A1 cell part has no v4 equivalent and is
    # dropped (v4 update matches rows by column, not A1 range).
    nodes = [
        _node(
            "Update Siparis",
            "n8n-nodes-base.googleSheets",
            parameters={
                "resource": "spreadsheet",
                "operation": "update",
                "spreadsheetId": "1efQabc",
                "range": "=Siparisler!E{{ $json.row_number }}",
                "dataMode": "raw",
                "values": {"teslim_mail": "evet"},
            },
        ),
    ]
    repaired, _conns, _ = repair_workflow(nodes, None, registry=REGISTRY)
    params = next(n for n in repaired if n["name"] == "Update Siparis")["parameters"]
    assert params["resource"] == "sheet"
    assert params["documentId"] == {"__rl": True, "mode": "id", "value": "1efQabc"}
    assert params["sheetName"] == {"__rl": True, "mode": "name", "value": "Siparisler"}
    assert "range" not in params


def test_google_sheets_spreadsheet_create_left_alone():
    # resource "spreadsheet" + "create" is a genuine spreadsheet-level operation;
    # it must NOT be rewritten to resource "sheet".
    nodes = [
        _node(
            "Create Doc",
            "n8n-nodes-base.googleSheets",
            parameters={"resource": "spreadsheet", "operation": "create", "title": "New"},
        ),
    ]
    repaired, _conns, repairs = repair_workflow(nodes, None, registry=REGISTRY)
    params = next(n for n in repaired if n["name"] == "Create Doc")["parameters"]
    assert params["resource"] == "spreadsheet"
    assert not any("googleSheets" in r for r in repairs)


def test_google_sheets_schema_upgrade_idempotent():
    nodes = [
        _node("Schedule", "n8n-nodes-base.code", parameters={"jsCode": "return items;"}),
        _node(
            "Read",
            "n8n-nodes-base.googleSheets",
            parameters={
                "resource": "spreadsheet",
                "operation": "read",
                "spreadsheetId": "1efQabc",
                "range": "Urunler!A:B",
            },
        ),
    ]
    connections = {"Schedule": {"main": [[{"node": "Read", "type": "main", "index": 0}]]}}
    once_nodes, once_conns, _ = repair_workflow(nodes, connections, registry=REGISTRY)
    twice_nodes, twice_conns, _ = repair_workflow(once_nodes, once_conns, registry=REGISTRY)
    assert once_nodes == twice_nodes
    assert once_conns == twice_conns


def test_google_sheets_range_without_tab_left_alone():
    # A bare range that IS A1 notation ("A:F") is a real cell range, not a tab ->
    # decline, leave for validation rather than invent a wrong sheetName.
    nodes = [
        _node(
            "Read",
            "n8n-nodes-base.googleSheets",
            parameters={
                "resource": "spreadsheet",
                "operation": "read",
                "spreadsheetId": "1efQabc",
                "range": "A:F",
            },
        ),
    ]
    repaired, _conns, _ = repair_workflow(nodes, None, registry=REGISTRY)
    params = next(n for n in repaired if n["name"] == "Read")["parameters"]
    # resource + documentId still upgraded, but no sheetName invented from "A:F".
    assert params["resource"] == "sheet"
    assert "sheetName" not in params
    assert params["range"] == "A:F"


def test_google_sheets_bare_range_tab_name_mapped_to_sheetname():
    # Regression E1 (İletişim Formu → Sheets): the model wrote a v4 append with the
    # tab in a top-level ``range: "Kayıtlar"`` (no "!") instead of sheetName, so n8n
    # rejected the node ("workflow has issues") and never ran. A bare range that is
    # NOT A1 notation is unambiguously the tab name -> move it to sheetName (which
    # the resourceLocator stage then wraps into an __rl object).
    nodes = [
        _node(
            "Webhook",
            "n8n-nodes-base.webhook",
            parameters={"httpMethod": "POST", "path": "contact-form"},
        ),
        _node(
            "Sheets",
            "n8n-nodes-base.googleSheets",
            parameters={
                "resource": "sheet",
                "operation": "append",
                "documentId": {"__rl": True, "mode": "id", "value": "18s2abc"},
                "range": "Kayıtlar",
            },
        ),
    ]
    connections = {"Webhook": {"main": [[{"node": "Sheets", "type": "main", "index": 0}]]}}
    repaired, _conns, repairs = repair_workflow(nodes, connections, registry=REGISTRY)
    params = next(n for n in repaired if n["name"] == "Sheets")["parameters"]
    assert params["sheetName"] == {"__rl": True, "mode": "name", "value": "Kayıtlar"}
    assert "range" not in params
    assert any("range->sheetName" in r for r in repairs)


def test_google_sheets_bare_a1_range_with_row_still_left_alone():
    # "A1:C10" is a real cell range, not a tab -> must NOT become a sheetName.
    nodes = [
        _node(
            "Read",
            "n8n-nodes-base.googleSheets",
            parameters={
                "resource": "sheet",
                "operation": "read",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "range": "A1:C10",
            },
        ),
    ]
    repaired, _conns, _ = repair_workflow(nodes, None, registry=REGISTRY)
    params = next(n for n in repaired if n["name"] == "Read")["parameters"]
    assert "sheetName" not in params
    assert params["range"] == "A1:C10"


def test_google_sheets_append_missing_columns_gets_automap():
    # v4 append needs a column mapping to know what to write; when the model omits
    # it, default to autoMapInputData (n8n's "Map Automatically") so the incoming
    # item fields land as a row. update/appendOrUpdate are NOT auto-filled (they
    # need a matching column -> left to validation).
    nodes = [
        _node(
            "Sheets",
            "n8n-nodes-base.googleSheets",
            parameters={
                "resource": "sheet",
                "operation": "append",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "Log"},
            },
        ),
    ]
    repaired, _conns, repairs = repair_workflow(nodes, None, registry=REGISTRY)
    params = next(n for n in repaired if n["name"] == "Sheets")["parameters"]
    assert params["columns"]["mappingMode"] == "autoMapInputData"
    assert any("autoMap" in r for r in repairs)


def test_google_sheets_append_defineBelow_value_preserved_and_schema_synthesized():
    # An explicit defineBelow value must be preserved (not replaced by autoMap),
    # but a missing schema is synthesized so n8n can execute it (columns.schema).
    nodes = [
        _node(
            "Sheets",
            "n8n-nodes-base.googleSheets",
            parameters={
                "resource": "sheet",
                "operation": "append",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "Log"},
                "columns": {"mappingMode": "defineBelow", "value": {"ad": "={{ $json.ad }}"}},
            },
        ),
    ]
    repaired, _conns, _ = repair_workflow(nodes, None, registry=REGISTRY)
    cols = next(n for n in repaired if n["name"] == "Sheets")["parameters"]["columns"]
    assert cols["mappingMode"] == "defineBelow"
    assert cols["value"] == {"ad": "={{ $json.ad }}"}
    assert [s["id"] for s in cols["schema"]] == ["ad"]


def test_google_sheets_append_e2_define_alias_is_canonicalized_with_schema():
    # Exact E2 failure shape: n8n accepted the workflow definition, then the
    # Sheets node failed with "Could not get parameter: columns.schema".
    nodes = [
        _node(
            "Sheet'e Ekle",
            "n8n-nodes-base.googleSheets",
            parameters={
                "resource": "sheet",
                "operation": "append",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "E-posta Logu"},
                "columns": {
                    "mappingMode": "define",
                    "value": {
                        "from": "={{ $json.from }}",
                        "subject": "={{ $json.subject }}",
                        "date": "={{ $json.date }}",
                    },
                },
            },
        ),
    ]
    repaired, _conns, repairs = repair_workflow(nodes, None, registry=REGISTRY)
    cols = repaired[0]["parameters"]["columns"]

    assert cols["mappingMode"] == "defineBelow"
    assert cols["matchingColumns"] == []
    assert [entry["id"] for entry in cols["schema"]] == ["from", "subject", "date"]
    assert any("column mapping" in repair for repair in repairs)


def test_google_sheets_columns_mappingvalues_flattened_with_schema():
    # Confirmed E1 rebuild bug: the model wrote defineBelow columns as
    # value.mappingValues[{column, mappingValue}] and omitted schema -> n8n throws
    # "Could not get parameter: columns.schema". Flatten to a value map + synth schema.
    nodes = [
        _node(
            "Sheets",
            "n8n-nodes-base.googleSheets",
            parameters={
                "resource": "sheet",
                "operation": "append",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "Kayıtlar"},
                "columns": {
                    "mappingMode": "defineBelow",
                    "value": {
                        "mappingValues": [
                            {"column": "Ad", "mappingValue": "={{ $json.body.ad }}"},
                            {"column": "E-posta", "mappingValue": "={{ $json.body.eposta }}"},
                        ]
                    },
                },
            },
        ),
    ]
    repaired, _conns, repairs = repair_workflow(nodes, None, registry=REGISTRY)
    cols = next(n for n in repaired if n["name"] == "Sheets")["parameters"]["columns"]
    assert cols["value"] == {
        "Ad": "={{ $json.body.ad }}",
        "E-posta": "={{ $json.body.eposta }}",
    }
    assert [s["id"] for s in cols["schema"]] == ["Ad", "E-posta"]
    assert cols["schema"][0]["canBeUsedToMatch"] is True
    assert any("column mapping" in r for r in repairs)


def test_google_sheets_columns_correct_shape_left_alone():
    # A defineBelow mapping that already has a schema is executable -> untouched.
    schema = [
        {
            "id": "ad",
            "displayName": "ad",
            "required": False,
            "defaultMatch": False,
            "display": True,
            "type": "string",
            "canBeUsedToMatch": True,
            "removed": False,
        }
    ]
    nodes = [
        _node(
            "Sheets",
            "n8n-nodes-base.googleSheets",
            parameters={
                "resource": "sheet",
                "operation": "append",
                "documentId": {"__rl": True, "mode": "id", "value": "1abc"},
                "sheetName": {"__rl": True, "mode": "name", "value": "Log"},
                "columns": {
                    "mappingMode": "defineBelow",
                    "value": {"ad": "={{ $json.ad }}"},
                    "schema": schema,
                    "matchingColumns": [],
                },
            },
        ),
    ]
    repaired, _conns, repairs = repair_workflow(nodes, None, registry=REGISTRY)
    cols = next(n for n in repaired if n["name"] == "Sheets")["parameters"]["columns"]
    assert cols["schema"] == schema
    assert not any("column mapping" in r for r in repairs)


# --------------------------------------------------------------------------
# Webhook responseMode normalization
# --------------------------------------------------------------------------


def test_webhook_response_mode_defaulted_to_last_node():
    # Without responseMode n8n defaults to "onReceived" → the webhook returns
    # immediately with no execution data, so Conduut can't show a run result
    # ("n8n'den cevap gelmedi"). Force lastNode so the run returns synchronously.
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook", parameters={"httpMethod": "POST", "path": "x"}),
        _node("Code", "n8n-nodes-base.code", parameters={"jsCode": "return items;"}),
    ]
    repaired, _conns, repairs = repair_workflow(nodes, None, registry=REGISTRY)
    webhook = next(n for n in repaired if n["name"] == "Webhook")
    assert webhook["parameters"]["responseMode"] == "lastNode"
    assert any("responseMode" in r for r in repairs)


def test_webhook_response_mode_onreceived_upgraded():
    nodes = [
        _node(
            "Webhook",
            "n8n-nodes-base.webhook",
            parameters={"httpMethod": "POST", "path": "x", "responseMode": "onReceived"},
        ),
    ]
    repaired, _conns, _ = repair_workflow(nodes, None, registry=REGISTRY)
    webhook = next(n for n in repaired if n["name"] == "Webhook")
    assert webhook["parameters"]["responseMode"] == "lastNode"


def test_webhook_explicit_response_node_left_alone():
    nodes = [
        _node(
            "Webhook",
            "n8n-nodes-base.webhook",
            parameters={"httpMethod": "POST", "path": "x", "responseMode": "responseNode"},
        ),
    ]
    repaired, _conns, _ = repair_workflow(nodes, None, registry=REGISTRY)
    webhook = next(n for n in repaired if n["name"] == "Webhook")
    assert webhook["parameters"]["responseMode"] == "responseNode"


def test_webhook_with_respond_node_uses_response_node_mode():
    # A Respond to Webhook node only fires with responseMode=responseNode; with
    # lastNode n8n rejects the run as "Unused Respond to Webhook node found".
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook", parameters={"httpMethod": "POST", "path": "x"}),
        _node("Fetch", "n8n-nodes-base.httpRequest", parameters={"url": "https://e.com"}),
        _node("Respond", "n8n-nodes-base.respondToWebhook", parameters={}),
    ]
    repaired, _conns, repairs = repair_workflow(nodes, None, registry=REGISTRY)
    webhook = next(n for n in repaired if n["name"] == "Webhook")
    assert webhook["parameters"]["responseMode"] == "responseNode"
    assert any("responseNode" in r for r in repairs)


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------


def test_repair_is_idempotent():
    nodes = [
        _node("Webhook", "n8n-nodes-base.webhook"),
        _node("OpenAI Chat Model", "@n8n/n8n-nodes-langchain.lmChatOpenAi"),
        _node(
            "AI Agent", "@n8n/n8n-nodes-langchain.agent", parameters={"text": "{{input.company}}"}
        ),
    ]
    connections = {
        "Webhook": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
        "OpenAI Chat Model": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
    }
    once_nodes, once_conns, _ = repair_workflow(
        nodes, connections, runtime_fields={"company"}, trigger_name="Webhook", registry=REGISTRY
    )
    twice_nodes, twice_conns, _ = repair_workflow(
        once_nodes,
        once_conns,
        runtime_fields={"company"},
        trigger_name="Webhook",
        registry=REGISTRY,
    )
    assert once_conns == twice_conns
    assert once_nodes == twice_nodes
