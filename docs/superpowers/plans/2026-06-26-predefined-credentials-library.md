# Predefined Credential Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** n8n'in hazır (predefined) credential tiplerini — özellikle AI node'larının ihtiyaç duyduğu `openAiApi` — birleşik Conduut Credentials kütüphanesine birinci sınıf, **credential-tipiyle eşleşen** alt-tür olarak eklemek; alanları n8n şemasından dinamik göstermek.

**Architecture:** Mevcut `CustomCredential` / `users/{uid}/credentials` koleksiyonu `match_kind: "host" | "type"` ile genelleştirilir. Yeni `agent/credential_catalog.py` modülü node registry'den tüm credential tiplerini çıkarır, OAuth olanları ayıklar, dostane etiket üretir; alanlar n8n'in `GET /credentials/schema/{type}` ucundan canlı gelir. Readiness, predefined tipler için kütüphaneyi tipe göre kontrol eder; chat ve dashboard ortak forma dayanır.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic AI (agent), Next.js 14 App Router / TypeScript / Tailwind (web), Firestore (metadata), n8n REST API (secret store).

## Global Constraints

- Secret **asla** Conduut tarafından loglanmaz, geri okunmaz, agent/LLM'den geçmez; yalnızca n8n credential store'unda tutulur (write-only).
- Python: ruff formatter + linter temiz, type hints zorunlu, async fonksiyonlar.
- TypeScript: strict mode, named exports.
- Kullanıcı n8n credential tip adlarını (örn. `openAiApi`) ham görmemeli; dostane etiket gösterilir.
- Connections (Google OAuth, `direct_api_enabled`, `platforms/`) **bu planda değişmez**.
- V1 kapsam dışı: OAuth2 tabanlı predefined tipler (`*OAuth2Api`), yeni broker provider, secret rotation.
- Conventional commits (`feat:`, `refactor:`, `test:`, `docs:`).
- Backend test komutu: `cd apps/agent && python -m pytest <path> -v` ; tam suite + lint: `cd apps/agent && ruff check . && ruff format --check . && python -m pytest`.
- n8n-registry test komutu: `cd packages/n8n-registry && python -m pytest tests/ -v`.
- Frontend doğrulama: `cd apps/web && pnpm lint && npx tsc --noEmit`.
- Branch zaten açık: `feature/predefined-credentials`.

## File Structure

Backend (`apps/agent/src`):
- `store.py` — `CustomCredential.match_kind` alanı + `save_custom_credential(match_kind=)` (MODIFY).
- `agent/credential_catalog.py` — **YENİ**: tip keşfi, OAuth ayıklama, dostane etiket, `match_credentials_by_type`, `parse_schema_fields`, `fetch_credential_fields`.
- `agent/tools/readiness.py` — type-matched kütüphane kontrolü; `parse_schema_fields`'i catalog'tan al (MODIFY).
- `agent/schemas.py` — `CredentialRequestData.matchKind` (MODIFY).
- `routes/credentials.py` — `GET /credentials/catalog`, `GET /credentials/catalog/{type}/schema`, `POST` `match_kind`, list payload (MODIFY).
- `agent/tools/credentials.py` — `list_credentials_payload(credential_type=)`, `add_service_credential_payload` (MODIFY).
- `agent/tools/factory.py` — `add_service_credential` tool + `list_credentials` `credential_type` param (MODIFY).
- `agent/tools/prompt.py` — predefined credential kuralı (MODIFY).

Registry (`packages/n8n-registry/src/n8n_registry`):
- `search.py` — `collect_credential_types(nodes)` (MODIFY).
- `registry.py` — `NodeRegistry.list_credential_types()` (MODIFY).

Frontend (`apps/web/src`):
- `app/api/credentials/catalog/route.ts` — **YENİ** BFF (GET list).
- `app/api/credentials/catalog/[type]/schema/route.ts` — **YENİ** BFF (GET schema).
- `lib/credential-auth-methods.ts` — `humanizeCredentialType`, `serviceMethodFromFields` (MODIFY).
- `components/credentials/service-credential-picker.tsx` — **YENİ**: aranabilir servis listesi + dinamik form.
- `app/(dashboard)/dashboard/credentials/page.tsx` — iki mod (Service / Custom HTTP), kart etiketi (MODIFY).
- `components/chat/credential-request.tsx` — `matchKind` submit (MODIFY).

Tests:
- `packages/n8n-registry/tests/test_search.py` (MODIFY).
- `apps/agent/tests/test_custom_credential_store.py` (MODIFY).
- `apps/agent/tests/test_credential_catalog.py` (**YENİ**).
- `apps/agent/tests/test_credentials_route.py` (MODIFY).
- `apps/agent/tests/test_readiness.py` (MODIFY).
- `apps/agent/tests/test_credential_tools.py` (MODIFY).

---

### Task 1: `CustomCredential.match_kind` + store

**Files:**
- Modify: `apps/agent/src/store.py` (dataclass ~41-64, `_custom_credential_from_data` ~267-284, `save_custom_credential` ~242-264)
- Test: `apps/agent/tests/test_custom_credential_store.py`

**Interfaces:**
- Produces: `store.CustomCredential.match_kind: str` (default `"host"`); `store.save_custom_credential(..., match_kind: str = "host")`.

- [ ] **Step 1: Write the failing test**

`apps/agent/tests/test_custom_credential_store.py` dosyasının sonuna ekle:

```python
def test_custom_credential_match_kind_defaults_to_host():
    cred = store._custom_credential_from_data("c1", {"label": "X", "credential_type": "httpHeaderAuth"})
    assert cred.match_kind == "host"


def test_custom_credential_match_kind_type_roundtrip():
    cred = store._custom_credential_from_data(
        "c2", {"label": "OpenAI", "credential_type": "openAiApi", "match_kind": "type"}
    )
    assert cred.match_kind == "type"
    assert cred.credential_type == "openAiApi"
```

Dosyada `from src import store` importu yoksa başına ekle.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agent && python -m pytest tests/test_custom_credential_store.py -k match_kind -v`
Expected: FAIL — `AttributeError: 'CustomCredential' object has no attribute 'match_kind'`.

- [ ] **Step 3: Write minimal implementation**

`store.py` dataclass `CustomCredential` içinde `confidence: str = ""` satırının altına ekle:

```python
    # "host" -> matched to HTTP Request nodes by URL host (generic HTTP auth);
    # "type" -> matched to any node by n8n credential type (e.g. openAiApi).
    match_kind: str = "host"
```

`_custom_credential_from_data` içinde `confidence=data.get("confidence", ""),` satırının altına ekle:

```python
        match_kind=data.get("match_kind", "host"),
```

`save_custom_credential` imzasına parametre ekle (`n8n_credential_name: str,` satırından sonra):

```python
    match_kind: str = "host",
```

ve `data` dict'ine `"status": "ready",` satırından sonra ekle:

```python
        "match_kind": match_kind,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/agent && python -m pytest tests/test_custom_credential_store.py -v`
Expected: PASS (tüm dosya).

- [ ] **Step 5: Commit**

```bash
git add apps/agent/src/store.py apps/agent/tests/test_custom_credential_store.py
git commit -m "feat(agent): add match_kind to CustomCredential (host|type)"
```

---

### Task 2: Registry credential-type enumeration

**Files:**
- Modify: `packages/n8n-registry/src/n8n_registry/search.py`
- Modify: `packages/n8n-registry/src/n8n_registry/registry.py` (~109-150)
- Test: `packages/n8n-registry/tests/test_search.py`

**Interfaces:**
- Produces: `search.collect_credential_types(nodes: list[NodeInfo]) -> list[dict]` her öğe `{"type": str, "nodes": list[str]}` (tipe göre alfabetik); `NodeRegistry.list_credential_types() -> list[dict]` aynı şekil.

- [ ] **Step 1: Write the failing test**

`packages/n8n-registry/tests/test_search.py` sonuna ekle:

```python
from n8n_registry.search import collect_credential_types


def _cred_node(type_name, display_name, creds):
    return NodeInfo(
        type_name=type_name,
        display_name=display_name,
        description="",
        type_version=1,
        credentials=creds,
        category="",
        is_trigger=False,
    )


def test_collect_credential_types_aggregates_nodes():
    nodes = [
        _cred_node("n8n-nodes-base.openAi", "OpenAI", ["openAiApi"]),
        _cred_node("@n8n/n8n-nodes-langchain.lmChatOpenAi", "OpenAI Chat Model", ["openAiApi"]),
        _cred_node("n8n-nodes-base.slack", "Slack", ["slackApi", "slackOAuth2Api"]),
        _cred_node("n8n-nodes-base.noAuth", "No Auth", []),
    ]
    result = collect_credential_types(nodes)
    by_type = {entry["type"]: entry["nodes"] for entry in result}
    assert set(by_type) == {"openAiApi", "slackApi", "slackOAuth2Api"}
    assert by_type["openAiApi"] == ["OpenAI", "OpenAI Chat Model"]
    assert [entry["type"] for entry in result] == sorted(by_type)


def test_registry_list_credential_types():
    registry = NodeRegistry()
    registry._nodes = [_cred_node("n8n-nodes-base.openAi", "OpenAI", ["openAiApi"])]
    assert registry.list_credential_types() == [{"type": "openAiApi", "nodes": ["OpenAI"]}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/n8n-registry && python -m pytest tests/test_search.py -k credential -v`
Expected: FAIL — `ImportError: cannot import name 'collect_credential_types'`.

- [ ] **Step 3: Write minimal implementation**

`search.py` sonuna ekle:

```python
def collect_credential_types(nodes: list[NodeInfo]) -> list[dict]:
    """Tüm node'lardan referans edilen credential tiplerini toplar.

    Her tip için onu kullanan node'ların display_name'lerini (görülme sırasında,
    tekrarsız) biriktirir. Tipe göre alfabetik sıralı döner.
    """
    by_type: dict[str, list[str]] = {}
    for node in nodes:
        for cred_type in node.credentials or []:
            names = by_type.setdefault(cred_type, [])
            if node.display_name and node.display_name not in names:
                names.append(node.display_name)
    return [{"type": cred_type, "nodes": names} for cred_type, names in sorted(by_type.items())]
```

`registry.py` `search` importuna `collect_credential_types` ekle (üstteki `from .search import (...)` bloğuna) ve `find_templates` metodundan önce ekle:

```python
    def list_credential_types(self) -> list[dict]:
        """Registry'deki tüm node'lardan referans edilen credential tiplerini döner.

        Her öğe: {type, nodes} — nodes, o tipi kullanan node display_name'leri.
        """
        return collect_credential_types(self._nodes)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/n8n-registry && python -m pytest tests/test_search.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/n8n-registry/src/n8n_registry/search.py packages/n8n-registry/src/n8n_registry/registry.py packages/n8n-registry/tests/test_search.py
git commit -m "feat(n8n-registry): enumerate referenced credential types from nodes"
```

---

### Task 3: `credential_catalog.py` modülü

**Files:**
- Create: `apps/agent/src/agent/credential_catalog.py`
- Modify: `apps/agent/src/agent/tools/readiness.py` (`_fields_from_schema` ~299-325 ve iki çağrı yeri; import)
- Test: `apps/agent/tests/test_credential_catalog.py`

**Interfaces:**
- Consumes: `registry.list_credential_types()` (Task 2), `n8n_client.get_credential_schema`, `schemas.CredentialField`.
- Produces:
  - `is_oauth_type_name(type_name: str) -> bool`
  - `schema_is_oauth(schema: dict) -> bool`
  - `friendly_label(type_name: str, node_names: list[str]) -> str`
  - `build_catalog(raw_types: list[dict], query: str | None = None) -> list[dict]` — her öğe `{"type", "label", "fillable": True}` (OAuth hariç, label'a göre sıralı).
  - `match_credentials_by_type(credential_type: str, credentials: list) -> list` — `credential_type` eşleşen ve `status == "ready"`.
  - `parse_schema_fields(schema: dict) -> list[CredentialField]`
  - `async fetch_credential_fields(credential_type: str) -> list[CredentialField]`

- [ ] **Step 1: Write the failing test**

`apps/agent/tests/test_credential_catalog.py` (yeni):

```python
"""Tests for the predefined credential catalog (type discovery + classification)."""

from dataclasses import dataclass

from src.agent import credential_catalog as cc


@dataclass
class _Cred:
    id: str
    credential_type: str
    status: str = "ready"


def test_is_oauth_type_name():
    assert cc.is_oauth_type_name("slackOAuth2Api") is True
    assert cc.is_oauth_type_name("googleSheetsOAuth2") is True
    assert cc.is_oauth_type_name("openAiApi") is False


def test_schema_is_oauth_detects_oauth_fields():
    assert cc.schema_is_oauth({"properties": {"clientId": {}, "oauthTokenData": {}}}) is True
    assert cc.schema_is_oauth({"properties": {"apiKey": {"type": "string"}}}) is False


def test_friendly_label_prefers_shortest_node_name():
    assert cc.friendly_label("openAiApi", ["OpenAI Chat Model", "OpenAI"]) == "OpenAI"
    assert cc.friendly_label("stripeApi", []) == "Stripe"


def test_build_catalog_excludes_oauth_filters_and_sorts():
    raw = [
        {"type": "openAiApi", "nodes": ["OpenAI"]},
        {"type": "slackOAuth2Api", "nodes": ["Slack"]},
        {"type": "anthropicApi", "nodes": ["Anthropic Chat Model"]},
    ]
    full = cc.build_catalog(raw)
    assert [c["type"] for c in full] == ["anthropicApi", "openAiApi"]  # OAuth excluded, sorted by label
    assert all(c["fillable"] is True for c in full)
    filtered = cc.build_catalog(raw, query="open")
    assert [c["type"] for c in filtered] == ["openAiApi"]


def test_match_credentials_by_type_only_ready():
    creds = [
        _Cred("c1", "openAiApi"),
        _Cred("c2", "openAiApi", status="draft"),
        _Cred("c3", "anthropicApi"),
    ]
    matched = cc.match_credentials_by_type("openAiApi", creds)
    assert {c.id for c in matched} == {"c1"}


def test_parse_schema_fields_marks_secrets():
    schema = {
        "properties": {
            "apiKey": {"type": "string", "displayName": "API Key"},
            "organizationId": {"type": "string", "displayName": "Org"},
        },
        "required": ["apiKey"],
    }
    fields = cc.parse_schema_fields(schema)
    by_name = {f.name: f for f in fields}
    assert by_name["apiKey"].type == "password"
    assert by_name["apiKey"].required is True
    assert by_name["organizationId"].type == "string"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agent && python -m pytest tests/test_credential_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agent.credential_catalog'`.

- [ ] **Step 3: Write minimal implementation**

`apps/agent/src/agent/credential_catalog.py` (yeni):

```python
"""Predefined n8n credential type catalog: discovery, OAuth filtering, fields.

The node registry references credential types by name (e.g. ``openAiApi``). This
module turns those into a friendly, searchable catalog of *fillable* (static
secret) credential types — OAuth2 types are excluded because their consent flow
cannot be driven through the n8n public API. Field schemas come live from
n8n's ``GET /credentials/schema/{type}``.
"""

import re

from src import n8n_client
from src.agent.schemas import CredentialField

# Field names that signal an OAuth2 credential (second-line defense after the
# name heuristic; the static schema then must not be offered as a fillable form).
_OAUTH_FIELD_SIGNATURES = {
    "oauthTokenData",
    "grantType",
    "authUrl",
    "accessTokenUrl",
    "authQueryParameters",
}

# Stripped from a credential type name when humanizing a label as a fallback.
_TYPE_SUFFIXES = ("OAuth2Api", "OAuth2", "Api", "Auth")


def is_oauth_type_name(type_name: str) -> bool:
    """Name heuristic: any credential type containing 'oauth' is OAuth-based."""

    return "oauth" in type_name.lower()


def schema_is_oauth(schema: dict) -> bool:
    """Whether an n8n credential schema looks OAuth-based by its field names."""

    properties = schema.get("properties") if isinstance(schema, dict) else None
    keys = set(properties.keys()) if isinstance(properties, dict) else set()
    return bool(keys & _OAUTH_FIELD_SIGNATURES)


def _humanize(type_name: str) -> str:
    base = type_name
    for suffix in _TYPE_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix):
            base = base[: -len(suffix)]
            break
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", base).strip()
    words = [word for word in spaced.split() if word]
    if not words:
        return type_name
    return " ".join(word[:1].upper() + word[1:] for word in words)


def friendly_label(type_name: str, node_names: list[str]) -> str:
    """Pick a user-facing label: shortest node display name, else humanized type."""

    names = [name for name in node_names if name]
    if names:
        return sorted(names, key=lambda name: (len(name), name))[0]
    return _humanize(type_name)


def build_catalog(raw_types: list[dict], query: str | None = None) -> list[dict]:
    """Fillable predefined credential types as a searchable, label-sorted catalog.

    OAuth types (by name) are excluded. ``query`` matches the label or type name
    (case-insensitive substring).
    """

    needle = (query or "").strip().lower()
    catalog: list[dict] = []
    for entry in raw_types:
        type_name = str(entry.get("type") or "")
        if not type_name or is_oauth_type_name(type_name):
            continue
        label = friendly_label(type_name, list(entry.get("nodes") or []))
        if needle and needle not in label.lower() and needle not in type_name.lower():
            continue
        catalog.append({"type": type_name, "label": label, "fillable": True})
    catalog.sort(key=lambda item: item["label"].lower())
    return catalog


def match_credentials_by_type(credential_type: str, credentials: list) -> list:
    """Saved credentials of this exact n8n type that are ready (have an n8n cred)."""

    matches = []
    for credential in credentials:
        if getattr(credential, "credential_type", None) != credential_type:
            continue
        if getattr(credential, "status", "ready") != "ready":
            continue
        matches.append(credential)
    return matches


def parse_schema_fields(schema: dict) -> list[CredentialField]:
    """Turn an n8n credential schema into form fields (secrets -> password)."""

    properties = schema.get("properties") if isinstance(schema, dict) else None
    required = set(schema.get("required") or []) if isinstance(schema, dict) else set()
    if not isinstance(properties, dict):
        return [CredentialField(name="apiKey", label="API Key", type="password", required=True)]

    fields: list[CredentialField] = []
    for name, meta in properties.items():
        if not isinstance(meta, dict):
            continue
        field_type = str(meta.get("type") or "string")
        if field_type not in {"string", "number", "integer", "boolean"}:
            continue
        display_name = meta.get("displayName") or name.replace("_", " ").title()
        secret = any(part in name.lower() for part in ("key", "token", "secret", "password"))
        fields.append(
            CredentialField(
                name=name,
                label=str(display_name),
                type="password" if secret else field_type,
                required=name in required or len(properties) == 1,
            )
        )

    return fields or [
        CredentialField(name="apiKey", label="API Key", type="password", required=True)
    ]


async def fetch_credential_fields(credential_type: str) -> list[CredentialField]:
    """Fetch + parse the fillable fields for a credential type from n8n."""

    schema = await n8n_client.get_credential_schema(credential_type)
    return parse_schema_fields(schema)
```

Şimdi `readiness.py`'de tekrarı kaldır. `readiness.py` üstüne import ekle (mevcut `from src.agent.credential_types import (...)` bloğunun altına):

```python
from src.agent.credential_catalog import parse_schema_fields
```

`readiness.py` içindeki `_fields_from_schema` fonksiyonunun (yaklaşık 299-325) **tüm gövdesini** şununla değiştir (geriye dönük çağrı isimleri korunur):

```python
def _fields_from_schema(schema: dict[str, Any]) -> list[CredentialField]:
    # Moved to credential_catalog.parse_schema_fields (shared with the catalog);
    # kept as a thin alias so existing call sites stay unchanged.
    return parse_schema_fields(schema)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/agent && python -m pytest tests/test_credential_catalog.py tests/test_readiness.py -v`
Expected: PASS (yeni catalog testleri + readiness regresyon yok).

- [ ] **Step 5: Commit**

```bash
git add apps/agent/src/agent/credential_catalog.py apps/agent/src/agent/tools/readiness.py apps/agent/tests/test_credential_catalog.py
git commit -m "feat(agent): credential_catalog — discover/classify predefined credential types"
```

---

### Task 4: Routes — catalog endpoints + `match_kind` + list payload

**Files:**
- Modify: `apps/agent/src/routes/credentials.py`
- Test: `apps/agent/tests/test_credentials_route.py`

**Interfaces:**
- Consumes: `registry.list_credential_types()`, `credential_catalog.build_catalog/is_oauth_type_name/schema_is_oauth/parse_schema_fields`, `store.save_custom_credential(match_kind=)`.
- Produces: `GET /credentials/catalog?q=` → `{"catalog": [{type,label,fillable}]}`; `GET /credentials/catalog/{credential_type}/schema` → `{"credentialType", "fields": [...]}`; `POST /credentials` artık `match_kind` kabul eder; `GET /credentials` öğelerine `match_kind` eklenir.

- [ ] **Step 1: Write the failing test**

`apps/agent/tests/test_credentials_route.py` sonuna ekle:

```python
async def test_credential_catalog_excludes_oauth(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(
        credentials_route.registry,
        "list_credential_types",
        lambda: [
            {"type": "openAiApi", "nodes": ["OpenAI"]},
            {"type": "slackOAuth2Api", "nodes": ["Slack"]},
        ],
    )
    result = await credentials_route.credential_catalog_list(object(), q=None)
    assert [c["type"] for c in result["catalog"]] == ["openAiApi"]


async def test_credential_catalog_schema_returns_fields(monkeypatch):
    _patch_user(monkeypatch)

    async def fake_schema(credential_type):
        assert credential_type == "openAiApi"
        return {"properties": {"apiKey": {"type": "string", "displayName": "API Key"}}, "required": ["apiKey"]}

    monkeypatch.setattr(credentials_route.n8n_client, "get_credential_schema", fake_schema)
    result = await credentials_route.credential_catalog_schema(object(), "openAiApi")
    assert result["credentialType"] == "openAiApi"
    assert result["fields"][0]["name"] == "apiKey"
    assert result["fields"][0]["type"] == "password"


async def test_credential_catalog_schema_rejects_oauth_by_name(monkeypatch):
    _patch_user(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await credentials_route.credential_catalog_schema(object(), "slackOAuth2Api")
    assert exc.value.status_code == 422


async def test_submit_type_matched_credential_no_host(monkeypatch):
    _patch_user(monkeypatch)
    calls: dict = {"attach": False}

    async def fake_create(name, credential_type, data):
        return n8n_client.N8nCredential(id="n8n_9", name=name, type=credential_type)

    async def fake_save(user_id, **kwargs):
        calls["save"] = kwargs
        return _custom_credential(
            id="cred_t", label=kwargs["label"], credential_type="openAiApi", host=""
        )

    async def fake_attach(*args, **kwargs):
        calls["attach"] = kwargs
        return {}

    monkeypatch.setattr(credentials_route.n8n_client, "create_credential", fake_create)
    monkeypatch.setattr(credentials_route.store, "save_custom_credential", fake_save)
    monkeypatch.setattr(credentials_route.n8n_client, "attach_credential_to_workflow", fake_attach)

    body = CredentialSubmitIn(
        credential_type="openAiApi",
        data={"apiKey": "sk-x"},
        label="OpenAI",
        match_kind="type",
        workflow_id="wf1",
        node_name="OpenAI Chat Model",
    )
    result = await credentials_route.submit_credential(object(), body)
    assert calls["save"]["match_kind"] == "type"
    assert calls["save"]["host"] == ""
    # Predefined type-matched: do NOT wire generic HTTP auth.
    assert calls["attach"]["generic_auth_type"] is None
    assert result["credential"]["credential_type"] == "openAiApi"


async def test_list_credentials_includes_match_kind(monkeypatch):
    _patch_user(monkeypatch)

    async def fake_list(user_id):
        return [_custom_credential(credential_type="openAiApi", host="", match_kind="type")]

    monkeypatch.setattr(credentials_route.store, "list_custom_credentials", fake_list)
    result = await credentials_route.list_credentials(object())
    assert result["credentials"][0]["match_kind"] == "type"
```

`_custom_credential` yardımcısı `match_kind` kabul edebilmeli; testin başındaki helper zaten `**overrides` ile `store.CustomCredential(**data)` kuruyor — `match_kind` Task 1 ile dataclass'a eklendiği için otomatik çalışır.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agent && python -m pytest tests/test_credentials_route.py -k "catalog or type_matched or match_kind" -v`
Expected: FAIL — `AttributeError: module 'src.routes.credentials' has no attribute 'credential_catalog_list'` ve `CredentialSubmitIn` `match_kind` kabul etmez.

- [ ] **Step 3: Write minimal implementation**

`routes/credentials.py` importlarına ekle (mevcut `from src.agent.credential_types import (...)` bloğunun altına):

```python
from src.agent import credential_catalog
from src.registry import registry
```

`CredentialSubmitIn` modeline alan ekle (`generic_auth_type: str | None = None` satırının altına):

```python
    match_kind: str | None = None  # "host" | "type"; derived from type when absent
```

`list_credentials` route'unda dönen sözlüğe `"status": item.status,` satırının altına ekle:

```python
                "match_kind": item.match_kind,
```

`credential_types` route'unun (`@router.get("/credentials/types")`) hemen altına iki yeni route ekle:

```python
@router.get("/credentials/catalog")
async def credential_catalog_list(request: Request, q: str | None = None):
    get_user_id(request)
    raw_types = registry.list_credential_types()
    return {"catalog": credential_catalog.build_catalog(raw_types, q)}


@router.get("/credentials/catalog/{credential_type}/schema")
async def credential_catalog_schema(request: Request, credential_type: str):
    get_user_id(request)
    if credential_catalog.is_oauth_type_name(credential_type):
        raise HTTPException(
            status_code=422,
            detail={"message": "OAuth-based services are managed under Connections."},
        )
    try:
        schema = await n8n_client.get_credential_schema(credential_type)
    except n8n_client.N8nApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"message": exc.message}) from exc
    if credential_catalog.schema_is_oauth(schema):
        raise HTTPException(
            status_code=422,
            detail={"message": "OAuth-based services are managed under Connections."},
        )
    fields = credential_catalog.parse_schema_fields(schema)
    return {"credentialType": credential_type, "fields": [field.model_dump() for field in fields]}
```

`submit_credential` route'unu güncelle. `credential_type = body.credential_type` satırından sonra `match_kind` türet ve host/generic mantığını match_kind'e bağla. Mevcut `host`/`host_required` bloğunu şununla değiştir:

```python
    match_kind = body.match_kind or ("host" if is_supported_http_type(credential_type) else "type")

    # Host is required only for the generic HTTP (host-matched) library path.
    host = normalize_host(body.host) or ""
    host_required = (
        match_kind == "host"
        and is_supported_http_type(credential_type)
        and (body.generic_auth_type is not None or not body.workflow_id)
    )
    if host_required and not host:
        raise HTTPException(
            status_code=422,
            detail={"message": "A valid host (e.g. api.example.com) is required."},
        )
```

`save_custom_credential` çağrısına `match_kind=match_kind,` ekle (`n8n_credential_name=credential.name,` satırının altına).

Attach bloğundaki `generic` hesabını değiştir:

```python
        if body.workflow_id and body.node_name:
            generic = (
                None
                if match_kind == "type"
                else (
                    body.generic_auth_type
                    or (credential_type if is_supported_http_type(credential_type) else None)
                )
            )
            await n8n_client.attach_credential_to_workflow(
                body.workflow_id,
                body.node_name,
                credential_type,
                credential.id,
                credential.name,
                generic_auth_type=generic,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/agent && python -m pytest tests/test_credentials_route.py -v`
Expected: PASS (yeni + mevcut testler).

- [ ] **Step 5: Commit**

```bash
git add apps/agent/src/routes/credentials.py apps/agent/tests/test_credentials_route.py
git commit -m "feat(agent): credential catalog routes + match_kind in submit/list"
```

---

### Task 5: Schema `matchKind` + readiness type-matched akış

**Files:**
- Modify: `apps/agent/src/agent/schemas.py` (`CredentialRequestData` ~229-246)
- Modify: `apps/agent/src/agent/tools/readiness.py` (`analyze_workflow_readiness_payload` non-HTTP dalı ~509-540; host reuse_candidates ~484-493; `_credential_request_for_node` non-HTTP kartı ~408-420)
- Test: `apps/agent/tests/test_readiness.py`

**Interfaces:**
- Consumes: `credential_catalog.match_credentials_by_type`, `store.list_custom_credentials`.
- Produces: `schemas.CredentialRequestData.matchKind: str | None`; readiness `reuse_candidates` öğeleri `matchKind` (`"host"`|`"type"`) taşır; predefined tip için tip-eşleşmeli adaylar üretir; reaktif non-HTTP kart `matchKind="type"` taşır.

- [ ] **Step 1: Write the failing test**

`apps/agent/tests/test_readiness.py` sonuna ekle:

```python
import pytest

from src.agent.tools import readiness as readiness_mod


@dataclass
class _Cred:
    id: str
    label: str
    credential_type: str
    host: str = ""
    status: str = "ready"
    n8n_credential_id: str = "n8n_x"
    n8n_credential_name: str = "n8n_x"


@pytest.mark.anyio
async def test_readiness_type_matched_library_suggests_candidate(monkeypatch):
    workflow = {
        "id": "wf1",
        "name": "AI flow",
        "nodes": [
            {
                "name": "OpenAI Chat Model",
                "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
                "parameters": {},
            }
        ],
        "connections": {},
    }

    monkeypatch.setattr(
        readiness_mod.registry,
        "get_node_schema",
        lambda node_type: {"credentials": ["openAiApi"]},
    )

    async def fake_list(user_id):
        return [_Cred(id="cred_o", label="OpenAI", credential_type="openAiApi")]

    monkeypatch.setattr(readiness_mod.store, "list_custom_credentials", fake_list)

    result = await readiness_mod.analyze_workflow_readiness_payload(workflow, user_id="u1")
    assert result["missing_credentials"] == []
    candidates = result["reuse_candidates"]
    assert len(candidates) == 1
    assert candidates[0]["credentialId"] == "cred_o"
    assert candidates[0]["matchKind"] == "type"
```

Not: `anyio` marker dosyada zaten yoksa, dosyanın diğer async testleri nasıl çağrılıyorsa onu izle (örn. `pytestmark = pytest.mark.anyio` veya düz `async def`). Mevcut `test_readiness.py` desenine uy; gerekiyorsa `@pytest.mark.anyio`'yu kaldır.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agent && python -m pytest tests/test_readiness.py -k type_matched -v`
Expected: FAIL — `reuse_candidates` boş (tip-eşleşme henüz yok) veya `matchKind` anahtarı yok.

- [ ] **Step 3: Write minimal implementation**

`schemas.py` `CredentialRequestData` içinde `sourceUrl: str | None = None` satırının altına ekle:

```python
    # "type" -> credential matched/saved by n8n credential type (e.g. openAiApi),
    # not by host. The card hides the host field and submits match_kind="type".
    matchKind: str | None = None
```

`readiness.py` importlarına ekle (mevcut `from src.agent.credential_catalog import parse_schema_fields` satırını genişlet):

```python
from src.agent.credential_catalog import match_credentials_by_type, parse_schema_fields
```

Host reuse_candidates append'ine (HTTP dalı) `matchKind` ekle. `"host": credential.host,` satırının altına ekle:

```python
                            "matchKind": "host",
```

Non-HTTP reuse bridge'inden ÖNCE tip-eşleşme dalını ekle. `# Non-HTTP, managed-less types (e.g. openAiApi): cross-workflow reuse bridge.` yorumunun hemen üstüne ekle:

```python
        # Predefined credential library (type-matched), before the reuse bridge.
        if http_credentials is None:
            http_credentials = await store.list_custom_credentials(user_id) if user_id else []
        type_matches = match_credentials_by_type(credential_type, http_credentials)
        if type_matches:
            for credential in type_matches:
                reuse_candidates.append(
                    {
                        "nodeName": str(node.get("name") or ""),
                        "credentialId": credential.id,
                        "label": credential.label,
                        "credentialType": credential.credential_type,
                        "host": credential.host,
                        "matchKind": "type",
                    }
                )
            continue
```

`_credential_request_for_node` non-HTTP kartına `matchKind="type"` ekle. Fonksiyonun son `return CredentialRequestAttachment(...)`'ındaki `CredentialRequestData(...)` içine, `description=f"{node_name} needs {credential_type} credentials before it can run.",` satırının altına ekle:

```python
            matchKind="type",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/agent && python -m pytest tests/test_readiness.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/agent/src/agent/schemas.py apps/agent/src/agent/tools/readiness.py apps/agent/tests/test_readiness.py
git commit -m "feat(agent): type-matched predefined credential readiness + matchKind"
```

---

### Task 6: Agent tools — `list_credentials(credential_type)` + `add_service_credential` + prompt

**Files:**
- Modify: `apps/agent/src/agent/tools/credentials.py` (`list_credentials_payload` ~98-118; yeni `add_service_credential_payload`)
- Modify: `apps/agent/src/agent/tools/factory.py` (`list_credentials` tool ~769-781; yeni `add_service_credential` tool)
- Modify: `apps/agent/src/agent/tools/prompt.py`
- Test: `apps/agent/tests/test_credential_tools.py`

**Interfaces:**
- Consumes: `credential_catalog.build_catalog/fetch_credential_fields/match_credentials_by_type`, `registry.list_credential_types()`.
- Produces:
  - `list_credentials_payload(deps, url=None, credential_type=None)` → öğelere `matches_type` eklenir.
  - `add_service_credential_payload(deps, service_or_type, workflow_id=None, node_name=None) -> dict` — `status` ∈ {`card`, `not_found`}; `card` varsa `CredentialRequestAttachment`.
  - factory: `add_service_credential` tool (kartı emit eder), `list_credentials` tool `credential_type` parametresi.

- [ ] **Step 1: Write the failing test**

`apps/agent/tests/test_credential_tools.py` sonuna ekle:

```python
from src.agent.tools import credentials as cred_tools
from src.agent.schemas import CredentialField


def _deps():
    return AgentDeps(user_id="u1", conversation_id="c1", event_queue=asyncio.Queue())


async def test_list_credentials_payload_flags_type_match(monkeypatch):
    from src import store

    async def fake_list(user_id):
        return [
            store.CustomCredential(
                id="c1", label="OpenAI", credential_type="openAiApi", host="",
                n8n_credential_id="n", n8n_credential_name="n", created_at="", updated_at="",
                match_kind="type",
            )
        ]

    monkeypatch.setattr(cred_tools.store, "list_custom_credentials", fake_list)
    result = await cred_tools.list_credentials_payload(_deps(), credential_type="openAiApi")
    assert result["credentials"][0]["matches_type"] is True


async def test_add_service_credential_known_type_returns_card(monkeypatch):
    monkeypatch.setattr(
        cred_tools.registry, "list_credential_types",
        lambda: [{"type": "openAiApi", "nodes": ["OpenAI"]}],
    )

    async def fake_fields(credential_type):
        return [CredentialField(name="apiKey", label="API Key", type="password", required=True)]

    monkeypatch.setattr(cred_tools.credential_catalog, "fetch_credential_fields", fake_fields)
    result = await cred_tools.add_service_credential_payload(_deps(), "OpenAI")
    assert result["status"] == "card"
    assert result["credentialType"] == "openAiApi"
    assert result["card"].data.matchKind == "type"
    assert result["card"].data.host is None


async def test_add_service_credential_unknown_returns_not_found(monkeypatch):
    monkeypatch.setattr(cred_tools.registry, "list_credential_types", lambda: [])
    result = await cred_tools.add_service_credential_payload(_deps(), "nonexistent-svc")
    assert result["status"] == "not_found"
```

Dosyanın başında `import asyncio` ve `from src.agent.schemas import AgentDeps` yoksa ekle (mevcut testlerin desenine uy).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agent && python -m pytest tests/test_credential_tools.py -k "type_match or add_service" -v`
Expected: FAIL — `add_service_credential_payload` yok; `list_credentials_payload` `credential_type` kabul etmez.

- [ ] **Step 3: Write minimal implementation**

`tools/credentials.py` importlarına ekle:

```python
from src.agent import credential_catalog
from src.agent.credential_catalog import match_credentials_by_type
from src.registry import registry
```

`list_credentials_payload`'ı değiştir:

```python
async def list_credentials_payload(
    deps: AgentDeps, url: str | None = None, credential_type: str | None = None
) -> dict[str, Any]:
    """Return the user's saved custom credentials (no secrets).

    ``url`` flags host matches (HTTP nodes); ``credential_type`` flags type
    matches (predefined service nodes, e.g. openAiApi).
    """

    credentials = await store.list_custom_credentials(deps.user_id)
    matched_ids = {c.id for c in match_credentials(url, credentials)} if url else set()
    type_ids = (
        {c.id for c in match_credentials_by_type(credential_type, credentials)}
        if credential_type
        else set()
    )
    return {
        "credentials": [
            {
                "id": credential.id,
                "label": credential.label,
                "credential_type": credential.credential_type,
                "host": credential.host,
                "matches_host": credential.id in matched_ids,
                "matches_type": credential.id in type_ids,
            }
            for credential in credentials
        ]
    }
```

`tools/credentials.py` sonuna `add_service_credential_payload` ekle:

```python
async def add_service_credential_payload(
    deps: AgentDeps,
    service_or_type: str,
    workflow_id: str | None = None,
    node_name: str | None = None,
) -> dict[str, Any]:
    """Resolve a predefined n8n service credential and show its secret form.

    Looks the catalog up by exact type/label, then by substring. Returns a
    type-matched credential card (``status="card"``) whose fields come from
    n8n's schema, or ``status="not_found"`` when nothing fillable matches.
    """

    catalog = credential_catalog.build_catalog(registry.list_credential_types())
    needle = service_or_type.strip().lower()
    match = next(
        (e for e in catalog if e["type"].lower() == needle or e["label"].lower() == needle),
        None,
    )
    if match is None:
        match = next(
            (e for e in catalog if needle in e["label"].lower() or needle in e["type"].lower()),
            None,
        )
    if match is None:
        return {
            "status": "not_found",
            "instruction": (
                "No fillable n8n credential type matched that service. Ask the user for "
                "the exact service name, or note it may be OAuth-based (Connections)."
            ),
        }

    fields = await credential_catalog.fetch_credential_fields(match["type"])
    card = CredentialRequestAttachment(
        data=CredentialRequestData(
            workflowId=workflow_id or "",
            nodeName=node_name or "",
            service=match["label"],
            credentialType=match["type"],
            credentialName=f"{match['label']} - Conduut",
            fields=fields,
            submitPath="/api/credentials",
            description=f"Enter your {match['label']} credentials to save them in Conduut.",
            host=None,
            matchKind="type",
        )
    )
    return {
        "status": "card",
        "credentialType": match["type"],
        "label": match["label"],
        "card": card,
        "instruction": (
            f"A credential form for {match['label']} is shown. Ask the user to enter the "
            "secret in the card; never accept the key as chat text. Once saved you can "
            "attach it to a node with attach_credential."
        ),
    }
```

`tools/factory.py` — credential tool importlarını genişlet (mevcut `from src.agent.tools.credentials import (...)` bloğu):

```python
from src.agent.tools.credentials import (
    add_service_credential_payload,
    attach_credential_payload,
    list_credentials_payload,
    prepare_api_credential_payload,
)
```

`list_credentials` tool'unu `credential_type` parametresiyle değiştir:

```python
    @agent.tool
    async def list_credentials(
        ctx: RunContext[AgentDeps],
        url: str | None = None,
        credential_type: str | None = None,
    ) -> dict[str, Any]:
        """List the user's saved credentials (labels/types/hosts only, never secrets).

        Pass the HTTP node URL to flag host matches, or credential_type (e.g.
        openAiApi) to flag the saved credential a service node can reuse.
        """

        await ctx.deps.emit_tool_call("list_credentials")
        started_at = perf_counter()
        result = await list_credentials_payload(ctx.deps, url, credential_type)
        _log_tool_finished("list_credentials", started_at, result)
        return result
```

`prepare_api_credential` tool'unun hemen altına `add_service_credential` tool'unu ekle:

```python
    @agent.tool
    async def add_service_credential(
        ctx: RunContext[AgentDeps],
        service_or_type: str,
        workflow_id: str | None = None,
        node_name: str | None = None,
    ) -> dict[str, Any]:
        """Show a form to save a predefined n8n service credential (e.g. OpenAI).

        Use when a node needs a known service credential (openAiApi, anthropicApi,
        slackApi, ...) and none is saved, or when the user asks to add one. The
        user enters the secret in the card; it never passes through you. Pass
        workflow_id/node_name to help attach it afterward.
        """

        await ctx.deps.emit_tool_call("add_service_credential")
        started_at = perf_counter()
        try:
            result = await add_service_credential_payload(
                ctx.deps, service_or_type, workflow_id, node_name
            )
        except Exception as exc:
            log.error("tool_error", tool="add_service_credential", error=str(exc))
            result = {"error": _safe_error(exc)}
            _log_tool_finished("add_service_credential", started_at, result)
            return result
        card = result.pop("card", None)
        if card is not None:
            await ctx.deps.emit_attachment(card)
            ctx.deps.awaiting_user_input = True
        _log_tool_finished("add_service_credential", started_at, result)
        return result
```

`tools/prompt.py` — kütüphane/credential kurallarının bulunduğu yere (HTTP auth kuralının yakınına) şu kuralı ekle (bir kural maddesi olarak):

```text
- Predefined service credentials (AI/chat model nodes need `openAiApi`, `anthropicApi`; Slack token `slackApi`, etc.): first call `list_credentials(credential_type="<type>")`. If a saved credential matches (`matches_type`), ask the user to confirm with `request_user_input`, then `attach_credential(workflow_id, node_name, credential_id)`. If none is saved, call `add_service_credential("<service or type>", workflow_id, node_name)` to show a secret form. Never ask for or accept the API key as chat text; you do not see secrets. OAuth-based services (Gmail/Sheets) stay on the Connections/OAuth path.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/agent && python -m pytest tests/test_credential_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/agent/src/agent/tools/credentials.py apps/agent/src/agent/tools/factory.py apps/agent/src/agent/tools/prompt.py apps/agent/tests/test_credential_tools.py
git commit -m "feat(agent): add_service_credential tool + type-aware list_credentials + prompt rule"
```

- [ ] **Step 6: Full backend gate**

Run: `cd apps/agent && ruff check . && ruff format --check . && python -m pytest`
Expected: PASS (Windows tmp-izni kaynaklı bilinen ~5 alakasız hata hariç). Hata varsa düzelt, sonra devam et.

---

### Task 7: BFF catalog routes

**Files:**
- Create: `apps/web/src/app/api/credentials/catalog/route.ts`
- Create: `apps/web/src/app/api/credentials/catalog/[type]/schema/route.ts`

**Interfaces:**
- Produces: `GET /api/credentials/catalog?q=` ve `GET /api/credentials/catalog/{type}/schema` proxy'leri (agent servisine yönlendirir).

- [ ] **Step 1: Create the catalog list BFF route**

`apps/web/src/app/api/credentials/catalog/route.ts`:

```typescript
import { NextRequest, NextResponse } from "next/server";

import { agentHeaders } from "@/lib/request-id";

function getAgentBaseUrl(): string {
  const fromEnv = process.env.AGENT_API_BASE_URL || process.env.NEXT_PUBLIC_AGENT_API_BASE_URL;
  return fromEnv || "http://localhost:8000";
}

function getAuthHeader(request: NextRequest): string | null {
  return request.headers.get("authorization");
}

async function toResponsePayload(response: Response) {
  const data = await response.json().catch(() => null);
  return NextResponse.json(data, { status: response.status });
}

export async function GET(request: NextRequest) {
  const authHeader = getAuthHeader(request);
  if (!authHeader) {
    return NextResponse.json({ message: "Missing Authorization header" }, { status: 401 });
  }

  const query = request.nextUrl.searchParams.get("q") ?? "";
  const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
  try {
    const response = await fetch(`${getAgentBaseUrl()}/api/credentials/catalog${suffix}`, {
      method: "GET",
      headers: agentHeaders(request, { Authorization: authHeader }),
      cache: "no-store",
    });
    return await toResponsePayload(response);
  } catch {
    return NextResponse.json({ message: "Agent service is unreachable." }, { status: 503 });
  }
}
```

- [ ] **Step 2: Create the catalog schema BFF route**

`apps/web/src/app/api/credentials/catalog/[type]/schema/route.ts`:

```typescript
import { NextRequest, NextResponse } from "next/server";

import { agentHeaders } from "@/lib/request-id";

function getAgentBaseUrl(): string {
  const fromEnv = process.env.AGENT_API_BASE_URL || process.env.NEXT_PUBLIC_AGENT_API_BASE_URL;
  return fromEnv || "http://localhost:8000";
}

function getAuthHeader(request: NextRequest): string | null {
  return request.headers.get("authorization");
}

async function toResponsePayload(response: Response) {
  const data = await response.json().catch(() => null);
  return NextResponse.json(data, { status: response.status });
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ type: string }> }
) {
  const authHeader = getAuthHeader(request);
  if (!authHeader) {
    return NextResponse.json({ message: "Missing Authorization header" }, { status: 401 });
  }

  const { type } = await params;
  try {
    const response = await fetch(
      `${getAgentBaseUrl()}/api/credentials/catalog/${encodeURIComponent(type)}/schema`,
      {
        method: "GET",
        headers: agentHeaders(request, { Authorization: authHeader }),
        cache: "no-store",
      }
    );
    return await toResponsePayload(response);
  } catch {
    return NextResponse.json({ message: "Agent service is unreachable." }, { status: 503 });
  }
}
```

Not: Next.js 14'te `params` Promise olmayabilir. Mevcut `apps/web/src/app/api/credentials/[credentialId]/route.ts` dosyasındaki imzayı aç ve birebir aynı `params` tipini (Promise mi düz nesne mi) kullan.

- [ ] **Step 3: Verify typecheck + lint**

Run: `cd apps/web && pnpm lint && npx tsc --noEmit`
Expected: PASS (hata yok).

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/app/api/credentials/catalog
git commit -m "feat(web): BFF routes for credential catalog list + schema"
```

---

### Task 8: `credential-auth-methods.ts` — humanize + service method

**Files:**
- Modify: `apps/web/src/lib/credential-auth-methods.ts`

**Interfaces:**
- Produces: `humanizeCredentialType(type: string): string`; `friendlyTypeLabel` artık bilinmeyen tipi humanize eder; `serviceMethodFromFields(credentialType, label, fields): AuthMethod` (data passthrough).
- Consumes (sonraki task): `service-credential-picker.tsx` `serviceMethodFromFields`'ı kullanır.

- [ ] **Step 1: Add humanize + service method builder**

`credential-auth-methods.ts` sonuna ekle:

```typescript
const TYPE_SUFFIXES = ["OAuth2Api", "OAuth2", "Api", "Auth"];

// Fallback label for a predefined n8n credential type with no friendly mapping
// (e.g. "openAiApi" -> "Open Ai"). Catalog labels from the agent are preferred.
export function humanizeCredentialType(type: string): string {
  let base = type;
  for (const suffix of TYPE_SUFFIXES) {
    if (base.endsWith(suffix) && base.length > suffix.length) {
      base = base.slice(0, -suffix.length);
      break;
    }
  }
  const spaced = base.replace(/(?<!^)(?=[A-Z])/g, " ").trim();
  if (!spaced) return type;
  return spaced
    .split(/\s+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export interface ServiceCredentialField {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
}

// Build a one-method form for a predefined service credential whose fields come
// from n8n's schema. buildData passes values straight through (n8n field names).
export function serviceMethodFromFields(
  credentialType: string,
  label: string,
  fields: ServiceCredentialField[]
): AuthMethod {
  const safeFields = fields.length > 0 ? fields : [{ name: "apiKey", label: "API Key", type: "password" }];
  return {
    id: credentialType,
    credentialType,
    label,
    fields: safeFields.map((field) => ({
      name: field.name,
      label: field.label,
      type: field.type === "password" ? "password" : field.type === "json" ? "json" : "text",
    })),
    buildData: (values) =>
      Object.fromEntries(safeFields.map((field) => [field.name, values[field.name] ?? ""])),
  };
}
```

`friendlyTypeLabel`'ı güncelle (humanize fallback):

```typescript
// Friendly label for a stored credential's n8n type (used in lists/badges).
export function friendlyTypeLabel(type: string): string {
  return METHOD_BY_TYPE.get(type)?.label ?? humanizeCredentialType(type);
}
```

- [ ] **Step 2: Verify typecheck + lint**

Run: `cd apps/web && pnpm lint && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/lib/credential-auth-methods.ts
git commit -m "feat(web): humanize predefined credential types + service method builder"
```

---

### Task 9: `service-credential-picker.tsx` (yeni)

**Files:**
- Create: `apps/web/src/components/credentials/service-credential-picker.tsx`

**Interfaces:**
- Consumes: `GET /api/credentials/catalog`, `GET /api/credentials/catalog/{type}/schema`, `serviceMethodFromFields`, `CredentialForm`, `CredentialSubmission`.
- Produces: `<ServiceCredentialPicker onSubmit={(credentialType, label, data) => Promise<void>} />` — kullanıcı servis seçip secret girince üst bileşene tip + data verir.

- [ ] **Step 1: Create the component**

`apps/web/src/components/credentials/service-credential-picker.tsx`:

```typescript
"use client";

import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/hooks/use-auth";
import {
  serviceMethodFromFields,
  type ServiceCredentialField,
} from "@/lib/credential-auth-methods";
import {
  CredentialForm,
  type CredentialSubmission,
} from "@/components/credentials/credential-form";

interface CatalogEntry {
  type: string;
  label: string;
}

export interface ServiceCredentialPickerProps {
  onSubmit: (credentialType: string, label: string, data: Record<string, unknown>) => Promise<void>;
}

export function ServiceCredentialPicker({ onSubmit }: ServiceCredentialPickerProps) {
  const { user } = useAuth();
  const [query, setQuery] = useState("");
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [selected, setSelected] = useState<CatalogEntry | null>(null);
  const [fields, setFields] = useState<ServiceCredentialField[]>([]);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user || selected) return;
    let active = true;
    const handle = setTimeout(async () => {
      setLoadingList(true);
      try {
        const token = await user.getIdToken();
        const suffix = query.trim() ? `?q=${encodeURIComponent(query.trim())}` : "";
        const response = await fetch(`/api/credentials/catalog${suffix}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = (await response.json().catch(() => null)) as { catalog?: CatalogEntry[] } | null;
        if (active) setEntries(data?.catalog ?? []);
      } finally {
        if (active) setLoadingList(false);
      }
    }, 200);
    return () => {
      active = false;
      clearTimeout(handle);
    };
  }, [user, query, selected]);

  const pick = async (entry: CatalogEntry) => {
    if (!user) return;
    setSelected(entry);
    setError("");
    setLoadingSchema(true);
    try {
      const token = await user.getIdToken();
      const response = await fetch(
        `/api/credentials/catalog/${encodeURIComponent(entry.type)}/schema`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      const data = (await response.json().catch(() => null)) as {
        fields?: ServiceCredentialField[];
        message?: string;
        detail?: { message?: string };
      } | null;
      if (!response.ok) {
        throw new Error(data?.detail?.message || data?.message || "Could not load fields.");
      }
      setFields(data?.fields ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load fields.");
      setSelected(null);
    } finally {
      setLoadingSchema(false);
    }
  };

  if (selected) {
    const method = serviceMethodFromFields(selected.type, selected.label, fields);
    return (
      <div className="space-y-3">
        <button
          type="button"
          onClick={() => setSelected(null)}
          className="text-[12px] font-medium text-conduut-500 hover:text-conduut-700"
        >
          ← Choose a different service
        </button>
        <p className="text-[13px] font-medium text-foreground">{selected.label}</p>
        {loadingSchema ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : (
          <CredentialForm
            methods={[method]}
            requireHost={false}
            initialLabel={selected.label}
            submitLabel="Save credential"
            onSubmit={(submission: CredentialSubmission) =>
              onSubmit(selected.type, submission.label, submission.data)
            }
          />
        )}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search a service (OpenAI, Slack, Notion...)"
          className="h-9 pl-9 text-[13px]"
        />
      </div>
      {error && <p className="text-[12px] text-error">{error}</p>}
      <div className="max-h-64 space-y-1 overflow-y-auto">
        {loadingList ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : entries.length === 0 ? (
          <p className="px-1 py-4 text-center text-[12px] text-muted-foreground">
            No matching services.
          </p>
        ) : (
          entries.map((entry) => (
            <button
              key={entry.type}
              type="button"
              onClick={() => void pick(entry)}
              className="flex w-full items-center justify-between rounded-lg border border-border bg-background px-3 py-2 text-left text-[13px] text-foreground transition-colors hover:border-conduut-400"
            >
              <span>{entry.label}</span>
              <span className="text-[11px] text-muted-foreground">{entry.type}</span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify typecheck + lint**

Run: `cd apps/web && pnpm lint && npx tsc --noEmit`
Expected: PASS. (Bileşen henüz kullanılmıyorsa eslint "unused" vermez — export'lu. Hata varsa düzelt.)

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/credentials/service-credential-picker.tsx
git commit -m "feat(web): service credential picker (searchable catalog + dynamic fields)"
```

---

### Task 10: Dashboard credentials page — iki mod + kart etiketi

**Files:**
- Modify: `apps/web/src/app/(dashboard)/dashboard/credentials/page.tsx`

**Interfaces:**
- Consumes: `ServiceCredentialPicker`, `POST /api/credentials` (`match_kind="type"` veya generic HTTP).

- [ ] **Step 1: Add a mode toggle and service submit handler**

`page.tsx` importlarına ekle:

```typescript
import { ServiceCredentialPicker } from "@/components/credentials/service-credential-picker";
```

`SavedCredential` arayüzüne `match_kind?: string;` ekle (interface içine).

`CredentialsPage` bileşeninde `const [showForm, setShowForm] = useState(false);` satırının altına ekle:

```typescript
  const [addMode, setAddMode] = useState<"service" | "http">("service");
```

`handleSubmit`'in (generic HTTP) altına servis için ayrı handler ekle:

```typescript
  const handleServiceSubmit = async (
    credentialType: string,
    label: string,
    data: Record<string, unknown>
  ) => {
    if (!user) throw new Error("Please sign in first.");
    const token = await user.getIdToken();
    const response = await fetch("/api/credentials", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        credential_type: credentialType,
        match_kind: "type",
        label,
        data,
      }),
    });
    if (!response.ok) {
      throw new Error(await getErrorMessage(response, "Credential could not be saved."));
    }
    toast.success("Credential saved.");
    setShowForm(false);
    await load();
  };
```

`{showForm && (...)}` bloğundaki `<CardContent>` içeriğini iki moda ayır:

```tsx
      {showForm && (
        <Card className="mb-6">
          <CardContent className="p-4">
            <div className="mb-3 flex gap-2">
              <Button
                size="sm"
                variant={addMode === "service" ? "default" : "outline"}
                className="h-7 px-3 text-[12px]"
                onClick={() => setAddMode("service")}
              >
                Service
              </Button>
              <Button
                size="sm"
                variant={addMode === "http" ? "default" : "outline"}
                className="h-7 px-3 text-[12px]"
                onClick={() => setAddMode("http")}
              >
                Custom HTTP
              </Button>
            </div>
            {addMode === "service" ? (
              <ServiceCredentialPicker onSubmit={handleServiceSubmit} />
            ) : (
              <CredentialForm methods={AUTH_METHODS} requireHost onSubmit={handleSubmit} />
            )}
          </CardContent>
        </Card>
      )}
```

- [ ] **Step 2: Show service vs host in the list card**

Liste kartındaki host satırını (`<p className="truncate text-[12px] text-muted-foreground">{credential.host}</p>`) şununla değiştir:

```tsx
                      <p className="truncate text-[12px] text-muted-foreground">
                        {credential.match_kind === "type"
                          ? friendlyTypeLabel(credential.credential_type)
                          : credential.host}
                      </p>
```

- [ ] **Step 3: Verify typecheck + lint**

Run: `cd apps/web && pnpm lint && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/app/(dashboard)/dashboard/credentials/page.tsx
git commit -m "feat(web): dashboard credentials — service picker mode + type-matched cards"
```

---

### Task 11: Chat card — `matchKind` submit

**Files:**
- Modify: `apps/web/src/components/chat/credential-request.tsx`

**Interfaces:**
- Consumes: `CredentialRequestData.matchKind` (Task 5 backend alanı).
- Produces: type-matched kart submit'i `match_kind: "type"` gönderir; host gizli kalır.

- [ ] **Step 1: Thread matchKind into the card data + submit**

`credential-request.tsx` `CredentialRequestData` arayüzüne ekle (`sourceUrl?: string;` altına):

```typescript
  matchKind?: string;
```

`handleSubmit` non-draft gövdesine `match_kind` ekle. `body: JSON.stringify(... isDraft ? ... : {` bloğundaki nesneye, `host: submission.host,` satırının altına ekle:

```typescript
              match_kind: data.matchKind,
```

`hasHost` zaten `host` undefined olduğunda false döner; type-matched kart `host=None` gönderdiği için host alanı gizli kalır — ek değişiklik gerekmez.

- [ ] **Step 2: Verify typecheck + lint**

Run: `cd apps/web && pnpm lint && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/chat/credential-request.tsx
git commit -m "feat(web): chat credential card submits match_kind for type-matched creds"
```

---

### Task 12: Bilgi tabanı + canlı doğrulama

**Files:**
- Create: `knowledge-database/03-desicions/adr-0015-predefined-credential-library.md`
- Modify: `knowledge-database/index.md` (Kararlar listesi)
- Modify: `CLAUDE.md` (son oturum özeti + önemli dosyalar)

**Interfaces:** Yok (dokümantasyon + manuel doğrulama).

- [ ] **Step 1: Write ADR-0015**

`knowledge-database/03-desicions/adr-0015-predefined-credential-library.md` oluştur; içerik: karar (birleşik kütüphane, `match_kind`, dinamik katalog, OAuth ayıklama, type-matched readiness, `add_service_credential`), bağlam (openAiApi gap), sonuçlar, kapsam dışı (OAuth predefined). [[adr-0012-custom-http-credentials]], [[adr-0013-agent-managed-credentials]], [[adr-0003-google-oauth-broker-mvp]], [[adr-0006-platform-capability-layer]]'e link ver. Tarih: 2026-06-26.

- [ ] **Step 2: Link from index + update CLAUDE.md**

`index.md` "Kararlar" listesine ekle:

```markdown
- [[adr-0015-predefined-credential-library]] - n8n hazir (predefined) credential
  tipleri (openAiApi vb.) birlesik Credentials kutuphanesine type-matched alt-tur
  olarak; dinamik katalog (registry + OAuth ayiklama) + alanlar n8n semasindan;
  `add_service_credential` tool + dashboard servis secici. Connections = servise
  n8n-disi direkt erisim (degismez).
```

`CLAUDE.md`'ye yeni "Son oturum özeti (2026-06-26)" bölümü ekle ve "Önemli dosyalar" listesine `agent/credential_catalog.py`'i ekle.

- [ ] **Step 3: Commit docs**

```bash
git add -f knowledge-database/03-desicions/adr-0015-predefined-credential-library.md
git add knowledge-database/index.md CLAUDE.md
git commit -m "docs: ADR-0015 predefined credential library + knowledge-database/CLAUDE.md"
```

- [ ] **Step 4: Live verification (n8n + agent + web açık)**

Manuel olarak doğrula (her biri için sonucu not et):

1. **Dashboard servis ekleme:** `/dashboard/credentials` → Add credential → Service → "OpenAI" ara → seç → `apiKey` alanı görünür → kaydet → liste kartında "OpenAI" etiketiyle görünür (host yerine servis adı). n8n'de `openAiApi` credential oluştu mu kontrol et.
2. **Chat reaktif:** Yeni konuşma → "Bir mesajı AI ile özetleyip webhook döndüren workflow kur" → AI node `openAiApi` ister → (1)'de kaydedilen credential varsa agent `list_credentials(credential_type="openAiApi")` → onay sorar → `attach_credential` → node'da `credentials.openAiApi` dolu.
3. **Chat proaktif:** "OpenAI anahtarımı ekle" → `add_service_credential` → secret kartı → doldur → kütüphaneye girer.
4. **Eşleşme yokken:** kayıtlı credential yokken AI workflow kur → reaktif kart çıkar → doldur → kütüphaneye `match_kind="type"` ile girer → ikinci workflow'da reuse önerisi gelir.
5. **OAuth ayıklama:** dashboard servis aramasında "Gmail"/"Slack OAuth" gibi OAuth tipleri **görünmemeli** (yalnızca fillable tipler).

Bulguları CLAUDE.md son oturum özetine işle; bug çıkarsa systematic-debugging ile düzelt ve ilgili task'a ek commit at.

---

## Self-Review

**1. Spec coverage:**
- Veri modeli `match_kind` → Task 1. ✓
- Katalog modülü (registry enumerate + OAuth ayıklama + fields) → Task 2, 3. ✓
- Backend route'lar (`/catalog`, `/catalog/{type}/schema`, POST match_kind, list) → Task 4. ✓
- Readiness type-matched + matchKind → Task 5. ✓
- Agent tool (`list_credentials` type, `add_service_credential`) + prompt → Task 6. ✓
- Dashboard "servis seç" + generic HTTP + kart etiketi → Task 7-10. ✓
- Reaktif kart matchKind → Task 5 (backend) + Task 11 (frontend). ✓
- Non-goals (OAuth predefined ayıklanır) → Task 3 (`is_oauth_type_name`) + Task 4 (schema endpoint 422). ✓
- Bilgi tabanı/ADR → Task 12. ✓

**2. Placeholder scan:** Tüm kod blokları tam; "TBD"/"TODO" yok. ✓

**3. Type consistency:**
- `match_kind` (snake, Python/store/route) vs `matchKind` (camel, Pydantic schema/TS) — bilinçli ayrım; route POST `match_kind` alır, kart datası `matchKind` taşır. Tutarlı.
- `match_credentials_by_type(credential_type, credentials)` — Task 3 tanımlar, Task 5/6 aynı imzayla kullanır. ✓
- `build_catalog(raw_types, query=None)` — Task 3 tanım, Task 4/6 kullanım. ✓
- `parse_schema_fields(schema)` — Task 3 tanım, readiness alias + route kullanım. ✓
- `fetch_credential_fields(credential_type)` — Task 3 tanım, Task 6 kullanım. ✓
- `serviceMethodFromFields(credentialType, label, fields)` — Task 8 tanım, Task 9 kullanım. ✓
- `registry.list_credential_types()` — Task 2 tanım, Task 3/4/6 kullanım. ✓

Tespit edilen düzeltme: Task 5 testindeki `@pytest.mark.anyio` mevcut `test_readiness.py` desenine göre uyarlanmalı (dosyada async testler nasıl çalışıyorsa o); plan bunu Step 1 notunda belirtti.
