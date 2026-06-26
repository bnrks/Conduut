# Schema-Driven Service Credential Form Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Service credential formunu n8n'in kendi formu gibi yapmak — default'lu, zorunlu işaretli, boolean=toggle, options=dropdown, koşullu (displayOptions) alanlar + servis ikonu — n8n cache'indeki `credentials.json`'ı registry'ye yükleyip kaynak yaparak.

**Architecture:** `credentials.json` (415 tip, full INodeProperties) `nodes.json` gibi n8n-registry'ye yüklenir. Zengin `CredentialField` modeli (default/placeholder/description/advanced/options/showWhen) backend'de definition'dan üretilir; yeni `DynamicCredentialFields` frontend bileşeni bunu n8n-benzeri render eder. Katalog + alanlar registry'den senkron gelir (n8n HTTP çağrısı yok); public-API yolu yalnız fallback.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic (agent + n8n-registry), Next.js 14 App Router / TypeScript / Tailwind (web).

## Global Constraints

- Secret **asla** loglanmaz/geri okunmaz/agent'tan geçmez; yalnız n8n'de. Default'lar secret değildir, ön-doldurulabilir.
- Python: ruff temiz, type hints, async fonksiyonlar. Yeni test imports **dosya başında** (asyncio_mode=auto → testler düz `async def`, marker yok).
- TypeScript: strict, named exports.
- credentials.json kaynağı: `/home/node/.cache/n8n/public/types/credentials.json` (docker cp, gitignored — nodes.json gibi).
- OAuth tespiti: isim `/oauth/i` **VEYA** `extends` girdisi `/oauth/i` **VEYA** property oauth imzası (`oauthTokenData`/`grantType`/`authUrl`/`accessTokenUrl`/`authQueryParameters`).
- `genericAuth: true` tipler (httpHeaderAuth vb.) Service kataloğundan **çıkar** (Custom HTTP'ye ait).
- Sadeleştirme: `required olmayan alan → advanced=true`. `type:"notice"`/`"hidden"` alanları atlanır.
- Conventional commits. Branch zaten açık: `feature/predefined-credentials`.
- Backend test: `cd apps/agent && python -m pytest <path> -v`. n8n-registry test: `cd packages/n8n-registry && python -m pytest tests/ -v`. Frontend: `cd apps/web && pnpm lint && npx tsc --noEmit`.

## File Structure

n8n-registry (`packages/n8n-registry`):
- `src/n8n_registry/models.py` — `CredentialTypeInfo` dataclass (MODIFY).
- `src/n8n_registry/loader.py` — `parse_credentials_json`, `load_credentials_from_file`, `_parse_credential_type`, `_credential_is_oauth` (MODIFY).
- `src/n8n_registry/registry.py` — load credentials + `list_credential_catalog`/`get_credential_definition`/`credential_count` + init params (MODIFY).
- `scripts/fetch_credentials.py` — **YENİ** fetch script.
- `tests/test_credentials_registry.py` — **YENİ**.

agent (`apps/agent/src`):
- `registry.py` — `_CREDENTIALS_PATH` + `credentials_path` wiring (MODIFY).
- `agent/schemas.py` — rich `CredentialField` + `CredentialFieldOption` + `CredentialFieldCondition` (MODIFY).
- `agent/credential_catalog.py` — `credential_fields_from_definition`; remove dead catalog helpers (MODIFY).
- `routes/credentials.py` — catalog/schema from registry + rich fields + iconUrl (MODIFY).
- `agent/tools/credentials.py` — `add_service_credential_payload` uses registry definition (MODIFY).
- `agent/tools/readiness.py` — `_credential_request_for_node` non-HTTP uses definition fields (MODIFY).

web (`apps/web/src`):
- `components/credentials/dynamic-credential-fields.tsx` — **YENİ**.
- `components/credentials/service-credential-picker.tsx` — use DynamicCredentialFields + icon (MODIFY).
- `components/chat/credential-request.tsx` — predefined card uses DynamicCredentialFields (MODIFY).

---

### Task 1: `CredentialTypeInfo` model + loader

**Files:**
- Modify: `packages/n8n-registry/src/n8n_registry/models.py`
- Modify: `packages/n8n-registry/src/n8n_registry/loader.py`
- Test: `packages/n8n-registry/tests/test_credentials_registry.py` (create)

**Interfaces:**
- Produces: `models.CredentialTypeInfo(name, display_name, icon_url, documentation_url, properties: list[dict], extends: list[str], generic_auth: bool, is_oauth: bool)`; `loader.parse_credentials_json(data) -> list[CredentialTypeInfo]`; `loader.load_credentials_from_file(path) -> list[CredentialTypeInfo]`.

- [ ] **Step 1: Write the failing test**

`packages/n8n-registry/tests/test_credentials_registry.py`:

```python
"""Tests for credentials.json parsing + OAuth/generic classification."""

from n8n_registry.loader import parse_credentials_json


def _raw():
    return [
        {
            "name": "anthropicApi",
            "displayName": "Anthropic",
            "iconUrl": "icons/anthropic.svg",
            "properties": [
                {"displayName": "API Key", "name": "apiKey", "type": "string",
                 "typeOptions": {"password": True}, "required": True, "default": ""},
                {"displayName": "Base URL", "name": "url", "type": "string",
                 "default": "https://api.anthropic.com"},
            ],
        },
        {"name": "slackOAuth2Api", "displayName": "Slack OAuth2 API",
         "extends": ["oAuth2Api"], "properties": [{"name": "scope", "type": "string"}]},
        {"name": "googleSheetsOAuth2Api", "displayName": "Google Sheets OAuth2 API",
         "extends": ["googleOAuth2Api"], "properties": [{"name": "scope", "type": "string"}]},
        {"name": "httpHeaderAuth", "displayName": "Header Auth", "genericAuth": True,
         "properties": [{"name": "name", "type": "string"}]},
    ]


def test_parse_basic_fields():
    by_name = {c.name: c for c in parse_credentials_json(_raw())}
    a = by_name["anthropicApi"]
    assert a.display_name == "Anthropic"
    assert a.icon_url == "icons/anthropic.svg"
    assert a.is_oauth is False
    assert a.generic_auth is False
    assert len(a.properties) == 2


def test_oauth_detected_by_name_extends_and_signature():
    by_name = {c.name: c for c in parse_credentials_json(_raw())}
    assert by_name["slackOAuth2Api"].is_oauth is True       # name + extends
    assert by_name["googleSheetsOAuth2Api"].is_oauth is True  # extends chain only
    assert by_name["anthropicApi"].is_oauth is False


def test_generic_auth_flag():
    by_name = {c.name: c for c in parse_credentials_json(_raw())}
    assert by_name["httpHeaderAuth"].generic_auth is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/n8n-registry && python -m pytest tests/test_credentials_registry.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_credentials_json'`.

- [ ] **Step 3: Write minimal implementation**

`models.py` — `WorkflowTemplate` dataclass'ının altına ekle:

```python
@dataclass
class CredentialTypeInfo:
    name: str                       # "anthropicApi"
    display_name: str               # "Anthropic"
    icon_url: str = ""              # "icons/anthropic.svg"
    documentation_url: str = ""
    properties: list[dict] = field(default_factory=list)  # raw n8n INodeProperties
    extends: list[str] = field(default_factory=list)
    generic_auth: bool = False      # n8n genericAuth (httpHeaderAuth etc.)
    is_oauth: bool = False
```

`loader.py` — `from .models import NodeInfo, WorkflowTemplate` satırını `CredentialTypeInfo` ekleyerek genişlet, dosya sonuna ekle:

```python
_OAUTH_PROP_SIGNATURES = {
    "oauthTokenData",
    "grantType",
    "authUrl",
    "accessTokenUrl",
    "authQueryParameters",
}


def _credential_is_oauth(name: str, extends: list[str], properties: list[dict]) -> bool:
    if "oauth" in name.lower():
        return True
    if any("oauth" in str(item).lower() for item in extends):
        return True
    prop_names = {p.get("name") for p in properties if isinstance(p, dict)}
    return bool(prop_names & _OAUTH_PROP_SIGNATURES)


def _parse_credential_type(raw: dict[str, Any]) -> CredentialTypeInfo | None:
    name = raw.get("name", "")
    if not name:
        return None
    extends = raw.get("extends") or []
    if not isinstance(extends, list):
        extends = [extends]
    extends = [str(item) for item in extends]
    properties = raw.get("properties") or []
    if not isinstance(properties, list):
        properties = []
    return CredentialTypeInfo(
        name=name,
        display_name=raw.get("displayName", name),
        icon_url=str(raw.get("iconUrl") or ""),
        documentation_url=str(raw.get("documentationUrl") or ""),
        properties=properties,
        extends=extends,
        generic_auth=bool(raw.get("genericAuth")),
        is_oauth=_credential_is_oauth(name, extends, properties),
    )


def parse_credentials_json(data: Any) -> list[CredentialTypeInfo]:
    """Parse n8n credentials.json (list, or {"data": [...]}) into CredentialTypeInfo."""
    if isinstance(data, dict):
        raw_list = data.get("data") or data.get("credentials") or []
    elif isinstance(data, list):
        raw_list = data
    else:
        log.warning("credentials.json unexpected format: %s", type(data))
        return []
    by_name: dict[str, CredentialTypeInfo] = {}
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        parsed = _parse_credential_type(raw)
        if parsed:
            by_name[parsed.name] = parsed
    log.info("Loaded %d credential types from credentials.json", len(by_name))
    return list(by_name.values())


def load_credentials_from_file(path: str | Path) -> list[CredentialTypeInfo]:
    """Load credential type definitions from a saved credentials.json file."""
    p = Path(path)
    if not p.exists():
        log.warning("credentials.json not found at %s", path)
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return parse_credentials_json(data)
    except Exception as exc:
        log.warning("Failed to load credentials.json from %s: %s", path, exc)
        return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/n8n-registry && python -m pytest tests/test_credentials_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/n8n-registry/src/n8n_registry/models.py packages/n8n-registry/src/n8n_registry/loader.py packages/n8n-registry/tests/test_credentials_registry.py
git commit -m "feat(n8n-registry): CredentialTypeInfo model + credentials.json loader"
```

---

### Task 2: Registry credentials loading + catalog/definition + fetch script

**Files:**
- Modify: `packages/n8n-registry/src/n8n_registry/registry.py`
- Create: `packages/n8n-registry/scripts/fetch_credentials.py`
- Test: `packages/n8n-registry/tests/test_credentials_registry.py`

**Interfaces:**
- Consumes: `loader.load_credentials_from_file`, `models.CredentialTypeInfo` (Task 1).
- Produces: `NodeRegistry.list_credential_catalog(query: str | None = None) -> list[dict]` (each `{"type", "label", "icon_url"}`, non-OAuth + non-generic, label-sorted); `NodeRegistry.get_credential_definition(type_name) -> CredentialTypeInfo | None`; `NodeRegistry.credential_count` property; `initialize_from_n8n(..., credentials_path=None)`; `load_from_files(..., credentials_path=None)`.

- [ ] **Step 1: Write the failing test**

Append to `packages/n8n-registry/tests/test_credentials_registry.py`:

```python
from n8n_registry.registry import NodeRegistry


def _registry():
    reg = NodeRegistry()
    reg._credentials = parse_credentials_json(_raw())
    return reg


def test_list_credential_catalog_excludes_oauth_and_generic():
    reg = _registry()
    catalog = reg.list_credential_catalog()
    types = [c["type"] for c in catalog]
    assert types == ["anthropicApi"]  # oauth + generic excluded; sorted by label
    assert catalog[0]["label"] == "Anthropic"
    assert catalog[0]["icon_url"] == "icons/anthropic.svg"


def test_list_credential_catalog_query_filters():
    reg = _registry()
    assert [c["type"] for c in reg.list_credential_catalog("anth")] == ["anthropicApi"]
    assert reg.list_credential_catalog("zzz") == []


def test_get_credential_definition():
    reg = _registry()
    assert reg.get_credential_definition("anthropicApi").display_name == "Anthropic"
    assert reg.get_credential_definition("missing") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/n8n-registry && python -m pytest tests/test_credentials_registry.py -k "catalog or definition" -v`
Expected: FAIL — `AttributeError: 'NodeRegistry' object has no attribute '_credentials'` / `list_credential_catalog`.

- [ ] **Step 3: Write minimal implementation**

`registry.py` — imports: extend `from .loader import (...)` with `load_credentials_from_file`, and `from .models import NodeInfo, WorkflowTemplate` → add `CredentialTypeInfo`.

In `__init__`, after `self._templates: list[WorkflowTemplate] = []` add:

```python
        self._credentials: list[CredentialTypeInfo] = []
```

Add a property next to `template_count`:

```python
    @property
    def credential_count(self) -> int:
        return len(self._credentials)
```

`initialize_from_n8n` — add `credentials_path: str | Path | None = None` parameter (after `nodes_path`), and after the templates block (`if templates_path:`), add:

```python
        if credentials_path:
            self._credentials = load_credentials_from_file(credentials_path)
```

`load_from_files` — add `credentials_path: str | Path | None = None` parameter and body:

```python
        if credentials_path:
            self._credentials = load_credentials_from_file(credentials_path)
```

Add methods after `find_templates`:

```python
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
            if needle and needle not in cred.display_name.lower() and needle not in cred.name.lower():
                continue
            out.append({"type": cred.name, "label": cred.display_name, "icon_url": cred.icon_url})
        out.sort(key=lambda item: item["label"].lower())
        return out

    def get_credential_definition(self, type_name: str) -> CredentialTypeInfo | None:
        for cred in self._credentials:
            if cred.name == type_name:
                return cred
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/n8n-registry && python -m pytest tests/test_credentials_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Create the fetch script**

`packages/n8n-registry/scripts/fetch_credentials.py`:

```python
#!/usr/bin/env python3
"""Copy credentials.json from the n8n container cache to data/credentials.json.

Mirror of fetch_nodes.py — n8n's HTTP types endpoint needs browser auth, so we
copy the cache file directly.

    python scripts/fetch_credentials.py [--container conduut-n8n] [--out data/credentials.json]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

_N8N_CREDENTIALS_PATH = "/home/node/.cache/n8n/public/types/credentials.json"


def fetch_via_docker_cp(container: str, out_path: Path) -> bool:
    print(f"Copying {_N8N_CREDENTIALS_PATH} from container '{container}'...")
    result = subprocess.run(
        ["docker", "cp", f"{container}:{_N8N_CREDENTIALS_PATH}", str(out_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: docker cp failed: {result.stderr}", file=sys.stderr)
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch n8n credential schemas from container")
    parser.add_argument("--container", default="conduut-n8n", help="Docker container name")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).parent.parent / "data" / "credentials.json"),
        help="Output file path",
    )
    args = parser.parse_args()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not fetch_via_docker_cp(args.container, out_path):
        sys.exit(1)
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
        count = len(data) if isinstance(data, list) else len(data.get("data") or [])
        size_kb = out_path.stat().st_size / 1024
        print(f"Saved {count} credential types ({size_kb:.0f} KB) to {out_path}")
    except Exception as exc:
        print(f"Warning: could not parse output: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Commit**

```bash
git add packages/n8n-registry/src/n8n_registry/registry.py packages/n8n-registry/scripts/fetch_credentials.py packages/n8n-registry/tests/test_credentials_registry.py
git commit -m "feat(n8n-registry): credential catalog/definition lookups + fetch_credentials.py"
```

---

### Task 3: Rich `CredentialField` + `credential_fields_from_definition`

**Files:**
- Modify: `apps/agent/src/agent/schemas.py` (`CredentialField` ~216-220)
- Modify: `apps/agent/src/agent/credential_catalog.py`
- Test: `apps/agent/tests/test_credential_catalog.py`

**Interfaces:**
- Consumes: `registry` `CredentialTypeInfo` (via `get_credential_definition`); `schemas.CredentialField`.
- Produces: `schemas.CredentialField` gains `default: Any = None`, `placeholder: str | None`, `description: str | None`, `advanced: bool = False`, `options: list[CredentialFieldOption] | None`, `showWhen: CredentialFieldCondition | None`; `type` now allows `text|password|json|number|boolean|options`. New `schemas.CredentialFieldOption(label, value)`, `schemas.CredentialFieldCondition(field, values)`. `credential_catalog.credential_fields_from_definition(definition) -> list[CredentialField]`.

- [ ] **Step 1: Write the failing test**

Append to `apps/agent/tests/test_credential_catalog.py`:

```python
from n8n_registry.models import CredentialTypeInfo


def _anthropic_definition():
    return CredentialTypeInfo(
        name="anthropicApi",
        display_name="Anthropic",
        icon_url="icons/anthropic.svg",
        properties=[
            {"displayName": "API Key", "name": "apiKey", "type": "string",
             "typeOptions": {"password": True}, "required": True, "default": ""},
            {"displayName": "Base URL", "name": "url", "type": "string",
             "default": "https://api.anthropic.com", "description": "Override base URL"},
            {"displayName": "Add Custom Header", "name": "header", "type": "boolean", "default": False},
            {"displayName": "Header Name", "name": "headerName", "type": "string", "default": "",
             "displayOptions": {"show": {"header": [True]}}},
            {"displayName": "Header Value", "name": "headerValue", "type": "string", "default": "",
             "typeOptions": {"password": True}, "displayOptions": {"show": {"header": [True]}}},
            {"displayName": "Notice", "name": "notice", "type": "notice", "default": ""},
            {"displayName": "Allowed HTTP Request Domains", "name": "allowedHttpRequestDomains",
             "type": "options", "default": "all",
             "options": [{"name": "All", "value": "all"}, {"name": "None", "value": "none"}]},
        ],
    )


def test_credential_fields_from_definition_anthropic():
    fields = cc.credential_fields_from_definition(_anthropic_definition())
    by_name = {f.name: f for f in fields}
    assert "notice" not in by_name  # notice skipped
    assert by_name["apiKey"].type == "password"
    assert by_name["apiKey"].required is True
    assert by_name["apiKey"].advanced is False
    assert by_name["url"].default == "https://api.anthropic.com"
    assert by_name["url"].advanced is True
    assert by_name["url"].description == "Override base URL"
    assert by_name["header"].type == "boolean"
    assert by_name["headerName"].showWhen.field == "header"
    assert by_name["headerName"].showWhen.values == [True]
    assert by_name["headerValue"].type == "password"
    opts = by_name["allowedHttpRequestDomains"]
    assert opts.type == "options"
    assert opts.default == "all"
    assert [o.value for o in opts.options] == ["all", "none"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agent && python -m pytest tests/test_credential_catalog.py -k from_definition -v`
Expected: FAIL — `AttributeError: module 'src.agent.credential_catalog' has no attribute 'credential_fields_from_definition'`.

- [ ] **Step 3: Write minimal implementation**

`schemas.py` — replace the `CredentialField` block (and add the two sub-models above it):

```python
class CredentialFieldOption(BaseModel):
    label: str
    value: str


class CredentialFieldCondition(BaseModel):
    field: str
    values: list[Any] = Field(default_factory=list)


class CredentialField(BaseModel):
    name: str
    label: str
    type: str = "string"  # text | password | json | number | boolean | options
    required: bool = False
    default: Any = None
    placeholder: str | None = None
    description: str | None = None
    advanced: bool = False
    options: list[CredentialFieldOption] | None = None
    showWhen: CredentialFieldCondition | None = None
```

(Ensure `Any` is imported in `schemas.py` — it already is via `from typing import Any`. If not, add it.)

`credential_catalog.py` — add imports at top: `from n8n_registry.models import CredentialTypeInfo` and extend the schemas import to `from src.agent.schemas import CredentialField, CredentialFieldCondition, CredentialFieldOption`. Add:

```python
# n8n property types that are display-only / not user-fillable.
_SKIP_PROPERTY_TYPES = {"notice", "hidden"}


def credential_fields_from_definition(definition: CredentialTypeInfo) -> list[CredentialField]:
    """Build rich form fields from an n8n credential definition (credentials.json).

    Honors default, required (-> non-required is advanced), password, options,
    and single-key displayOptions.show (conditional visibility). Unknown property
    types fall back to a plain text input.
    """

    fields: list[CredentialField] = []
    for prop in definition.properties:
        if not isinstance(prop, dict):
            continue
        name = prop.get("name")
        if not name:
            continue
        prop_type = str(prop.get("type") or "string")
        if prop_type in _SKIP_PROPERTY_TYPES:
            continue
        is_password = bool((prop.get("typeOptions") or {}).get("password"))
        if prop_type == "string":
            field_type = "password" if is_password else "text"
        elif prop_type in {"boolean", "number", "json", "options"}:
            field_type = prop_type
        else:
            field_type = "text"  # safe fallback for unusual types

        options = None
        if field_type == "options":
            options = [
                CredentialFieldOption(
                    label=str(opt.get("name", opt.get("value", ""))),
                    value=str(opt.get("value", "")),
                )
                for opt in (prop.get("options") or [])
                if isinstance(opt, dict)
            ]

        show_when = None
        display_options = prop.get("displayOptions")
        if isinstance(display_options, dict):
            show = display_options.get("show")
            if isinstance(show, dict) and show:
                first_key = next(iter(show))
                show_when = CredentialFieldCondition(
                    field=first_key, values=list(show.get(first_key) or [])
                )

        required = bool(prop.get("required"))
        fields.append(
            CredentialField(
                name=name,
                label=str(prop.get("displayName") or name),
                type=field_type,
                required=required,
                default=prop.get("default"),
                placeholder=prop.get("placeholder") or None,
                description=prop.get("description") or None,
                advanced=not required,
                options=options,
                showWhen=show_when,
            )
        )
    return fields
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/agent && python -m pytest tests/test_credential_catalog.py -v`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add apps/agent/src/agent/schemas.py apps/agent/src/agent/credential_catalog.py apps/agent/tests/test_credential_catalog.py
git commit -m "feat(agent): rich CredentialField + credential_fields_from_definition"
```

---

### Task 4: Catalog + schema routes from registry + agent registry wiring

**Files:**
- Modify: `apps/agent/src/registry.py` (~17-28)
- Modify: `apps/agent/src/routes/credentials.py` (catalog routes ~85-130)
- Test: `apps/agent/tests/test_credentials_route.py`

**Interfaces:**
- Consumes: `registry.list_credential_catalog`, `registry.get_credential_definition` (Task 2); `credential_catalog.credential_fields_from_definition` (Task 3); `credential_catalog.is_oauth_type_name`/`schema_is_oauth`/`parse_schema_fields` (fallback).
- Produces: `GET /credentials/catalog?q=` → `{"catalog": [{type,label,icon_url}]}` (from registry); `GET /credentials/catalog/{type}/schema` → `{"credentialType", "label", "iconUrl", "fields": [rich CredentialField]}` (definition first, public-API fallback; OAuth/generic → 422).

- [ ] **Step 1: Write the failing test**

Append to `apps/agent/tests/test_credentials_route.py` (top-level imports already include `pytest`, `HTTPException`, `credentials_route`):

```python
from n8n_registry.models import CredentialTypeInfo


async def test_catalog_list_from_registry(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(
        credentials_route.registry, "list_credential_catalog",
        lambda q=None: [{"type": "anthropicApi", "label": "Anthropic", "icon_url": "icons/a.svg"}],
    )
    result = await credentials_route.credential_catalog_list(object(), q=None)
    assert result["catalog"][0]["icon_url"] == "icons/a.svg"


async def test_catalog_schema_from_definition(monkeypatch):
    _patch_user(monkeypatch)
    definition = CredentialTypeInfo(
        name="anthropicApi", display_name="Anthropic", icon_url="icons/a.svg",
        properties=[{"displayName": "API Key", "name": "apiKey", "type": "string",
                     "typeOptions": {"password": True}, "required": True}],
    )
    monkeypatch.setattr(
        credentials_route.registry, "get_credential_definition",
        lambda t: definition if t == "anthropicApi" else None,
    )
    result = await credentials_route.credential_catalog_schema(object(), "anthropicApi")
    assert result["label"] == "Anthropic"
    assert result["iconUrl"] == "icons/a.svg"
    assert result["fields"][0]["name"] == "apiKey"
    assert result["fields"][0]["type"] == "password"


async def test_catalog_schema_oauth_definition_rejected(monkeypatch):
    _patch_user(monkeypatch)
    definition = CredentialTypeInfo(name="slackOAuth2Api", display_name="Slack", is_oauth=True)
    monkeypatch.setattr(
        credentials_route.registry, "get_credential_definition", lambda t: definition
    )
    with pytest.raises(HTTPException) as exc:
        await credentials_route.credential_catalog_schema(object(), "slackOAuth2Api")
    assert exc.value.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agent && python -m pytest tests/test_credentials_route.py -k "from_registry or from_definition or oauth_definition" -v`
Expected: FAIL — routes still call `registry.list_credential_types`/`get_credential_schema`.

- [ ] **Step 3: Write minimal implementation**

`apps/agent/src/registry.py` — after `_TEMPLATES_PATH` add:

```python
_CREDENTIALS_PATH = _DATA_DIR / "credentials.json"
```

In `initialize_registry`, add `credentials_path=` to the call and include `credential_count` in the log:

```python
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
```

`routes/credentials.py` — import already has `from src.agent import credential_catalog` and `from src.registry import registry`. Replace the `credential_catalog_list` and `credential_catalog_schema` route bodies:

```python
@router.get("/credentials/catalog")
async def credential_catalog_list(request: Request, q: str | None = None):
    get_user_id(request)
    return {"catalog": registry.list_credential_catalog(q)}


@router.get("/credentials/catalog/{credential_type}/schema")
async def credential_catalog_schema(request: Request, credential_type: str):
    get_user_id(request)
    definition = registry.get_credential_definition(credential_type)
    if definition is not None:
        if definition.is_oauth or definition.generic_auth:
            raise HTTPException(
                status_code=422,
                detail={"message": "OAuth-based services are managed under Connections."},
            )
        fields = credential_catalog.credential_fields_from_definition(definition)
        return {
            "credentialType": credential_type,
            "label": definition.display_name,
            "iconUrl": definition.icon_url,
            "fields": [field.model_dump() for field in fields],
        }
    # Fallback: definition missing from credentials.json -> public-API schema.
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
    return {
        "credentialType": credential_type,
        "label": credential_type,
        "iconUrl": "",
        "fields": [field.model_dump() for field in fields],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/agent && python -m pytest tests/test_credentials_route.py -v`
Expected: PASS. (The earlier `test_credential_catalog_excludes_oauth` and `test_credential_catalog_schema_*` tests from the prior plan that patched `registry.list_credential_types`/`get_credential_schema` will now fail — UPDATE them: the list test should patch `list_credential_catalog`; the by-name/by-signature schema tests should patch `get_credential_definition` to return `None` so the fallback path runs, keeping their original assertions. Adjust those tests in this step and re-run until green.)

- [ ] **Step 5: Commit**

```bash
git add apps/agent/src/registry.py apps/agent/src/routes/credentials.py apps/agent/tests/test_credentials_route.py
git commit -m "feat(agent): credential catalog/schema routes from registry definitions"
```

---

### Task 5: `add_service_credential` + readiness use definitions; remove dead catalog code

**Files:**
- Modify: `apps/agent/src/agent/tools/credentials.py` (`add_service_credential_payload`)
- Modify: `apps/agent/src/agent/tools/readiness.py` (`_credential_request_for_node` non-HTTP branch)
- Modify: `apps/agent/src/agent/credential_catalog.py` (remove dead `build_catalog`/`friendly_label`/`_humanize`/`_TYPE_SUFFIXES`)
- Modify: `packages/n8n-registry/src/n8n_registry/registry.py` + `search.py` (remove dead `list_credential_types`/`collect_credential_types`)
- Test: `apps/agent/tests/test_credential_tools.py`, `apps/agent/tests/test_credential_catalog.py`, `packages/n8n-registry/tests/test_search.py`

**Interfaces:**
- Consumes: `registry.list_credential_catalog`, `registry.get_credential_definition`, `credential_catalog.credential_fields_from_definition`.
- Produces: `add_service_credential_payload` resolves via `registry.list_credential_catalog()` + builds the card from `get_credential_definition` rich fields (+ `iconUrl`); OAuth/generic → `not_found`. Card data carries `iconUrl`.

- [ ] **Step 1: Write the failing test**

In `apps/agent/tests/test_credential_tools.py`, REPLACE the body of `test_add_service_credential_known_type_returns_card` and the oauth test to drive the registry path, and add an icon assertion:

```python
async def test_add_service_credential_known_type_returns_card(monkeypatch):
    from n8n_registry.models import CredentialTypeInfo

    monkeypatch.setattr(
        cred_tools.registry, "list_credential_catalog",
        lambda q=None: [{"type": "anthropicApi", "label": "Anthropic", "icon_url": "icons/a.svg"}],
    )
    definition = CredentialTypeInfo(
        name="anthropicApi", display_name="Anthropic", icon_url="icons/a.svg",
        properties=[{"displayName": "API Key", "name": "apiKey", "type": "string",
                     "typeOptions": {"password": True}, "required": True}],
    )
    monkeypatch.setattr(cred_tools.registry, "get_credential_definition", lambda t: definition)
    result = await cred_tools.add_service_credential_payload(_deps(), "Anthropic")
    assert result["status"] == "card"
    assert result["credentialType"] == "anthropicApi"
    assert result["card"].data.matchKind == "type"
    assert result["card"].data.iconUrl == "icons/a.svg"
    assert result["card"].data.fields[0].name == "apiKey"


async def test_add_service_credential_oauth_rejected(monkeypatch):
    from n8n_registry.models import CredentialTypeInfo

    monkeypatch.setattr(
        cred_tools.registry, "list_credential_catalog",
        lambda q=None: [{"type": "slackOAuth2Api", "label": "Slack", "icon_url": ""}],
    )
    monkeypatch.setattr(
        cred_tools.registry, "get_credential_definition",
        lambda t: CredentialTypeInfo(name="slackOAuth2Api", display_name="Slack", is_oauth=True),
    )
    result = await cred_tools.add_service_credential_payload(_deps(), "Slack")
    assert result["status"] == "not_found"
```

Also add `iconUrl: str | None = None` to `CredentialRequestData` (schemas.py) and assert it flows through (the card builder sets it).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/agent && python -m pytest tests/test_credential_tools.py -k add_service -v`
Expected: FAIL — `add_service_credential_payload` still uses `build_catalog`/`fetch_credential_fields`; `CredentialRequestData` has no `iconUrl`.

- [ ] **Step 3: Write minimal implementation**

`schemas.py` `CredentialRequestData` — add after `matchKind`:

```python
    iconUrl: str | None = None
```

`tools/credentials.py` `add_service_credential_payload` — replace the catalog-resolve + field-fetch + card build with the registry path:

```python
async def add_service_credential_payload(
    deps: AgentDeps,
    service_or_type: str,
    workflow_id: str | None = None,
    node_name: str | None = None,
) -> dict[str, Any]:
    """Resolve a predefined n8n service credential and show its rich secret form."""

    catalog = registry.list_credential_catalog()
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

    definition = registry.get_credential_definition(match["type"])
    if definition is None or definition.is_oauth or definition.generic_auth:
        return {
            "status": "not_found",
            "instruction": (
                "That service can't be set up as a simple key/secret credential "
                "(OAuth-based or unavailable). Tell the user it isn't available here."
            ),
        }
    fields = credential_catalog.credential_fields_from_definition(definition)
    card = CredentialRequestAttachment(
        data=CredentialRequestData(
            workflowId=workflow_id or "",
            nodeName=node_name or "",
            service=definition.display_name,
            credentialType=definition.name,
            credentialName=f"{definition.display_name} - Conduut",
            fields=fields,
            submitPath="/api/credentials",
            description=f"Enter your {definition.display_name} credentials to save them in Conduut.",
            host=None,
            matchKind="type",
            iconUrl=definition.icon_url or None,
        )
    )
    return {
        "status": "card",
        "credentialType": definition.name,
        "label": definition.display_name,
        "card": card,
        "instruction": (
            f"A credential form for {definition.display_name} is shown. Ask the user to enter "
            "the secret in the card; never accept the key as chat text. Once saved you can "
            "attach it with attach_credential."
        ),
    }
```

Update imports in `tools/credentials.py`: add `from src.registry import registry` (if not present) and `from src.agent import credential_catalog`; remove the now-unused `match_credentials_by_type` import only if it's no longer used elsewhere in the file (it is still used by `list_credentials_payload` — keep it).

`tools/readiness.py` `_credential_request_for_node` — in the non-HTTP fallback branch (currently `schema = await n8n_client.get_credential_schema(...)` + `_fields_from_schema`), prefer the registry definition:

```python
    definition = registry.get_credential_definition(credential_type)
    if definition is not None and not definition.is_oauth and not definition.generic_auth:
        from src.agent.credential_catalog import credential_fields_from_definition

        fields = credential_fields_from_definition(definition)
        icon_url = definition.icon_url or None
    else:
        try:
            schema = await n8n_client.get_credential_schema(credential_type)
            fields = _fields_from_schema(schema)
        except Exception:
            fields = [CredentialField(name="apiKey", label="API Key", type="password", required=True)]
        icon_url = None
```

and pass `iconUrl=icon_url` into the `CredentialRequestData(...)` it returns (alongside the existing fields).

`credential_catalog.py` — REMOVE the now-dead `build_catalog`, `friendly_label`, `_humanize`, and `_TYPE_SUFFIXES` (no remaining callers after this task). Keep `is_oauth_type_name`, `schema_is_oauth`, `parse_schema_fields`, `fetch_credential_fields` (public-API fallback) and `match_credentials_by_type`.

`test_credential_catalog.py` — remove the tests for the deleted functions: `test_is_oauth_type_name` stays (function kept), `test_build_catalog_excludes_oauth_filters_and_sorts` and `test_friendly_label_prefers_shortest_node_name` are DELETED.

`n8n-registry` — REMOVE `NodeRegistry.list_credential_types` (registry.py) and `collect_credential_types` (search.py); delete `test_collect_credential_types_aggregates_nodes` and `test_registry_list_credential_types` from `tests/test_search.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/agent && python -m pytest tests/test_credential_tools.py tests/test_credential_catalog.py tests/test_readiness.py -v`
Run: `cd packages/n8n-registry && python -m pytest tests/ -v`
Expected: PASS (dead-code tests removed; new registry-path tests green).

- [ ] **Step 5: Full backend gate**

Run: `cd apps/agent && ruff check . && python -m pytest`
Expected: PASS except the known ~5 Windows tmp-permission errors. Fix any real failure (e.g. a missed `build_catalog`/`list_credential_types` reference) before committing.

- [ ] **Step 6: Commit**

```bash
git add apps/agent/src/agent/tools/credentials.py apps/agent/src/agent/tools/readiness.py apps/agent/src/agent/schemas.py apps/agent/src/agent/credential_catalog.py apps/agent/tests/test_credential_tools.py apps/agent/tests/test_credential_catalog.py packages/n8n-registry/src/n8n_registry/registry.py packages/n8n-registry/src/n8n_registry/search.py packages/n8n-registry/tests/test_search.py
git commit -m "feat(agent): service credential cards from registry definitions; drop dead catalog code"
```

---

### Task 6: `DynamicCredentialFields` component

**Files:**
- Create: `apps/web/src/components/credentials/dynamic-credential-fields.tsx`

**Interfaces:**
- Produces: `CredentialFieldSpec` TS type + `<DynamicCredentialFields fields={CredentialFieldSpec[]} initialLabel? submitLabel? onSubmit={(data: Record<string, unknown>) => Promise<void>} />`.

- [ ] **Step 1: Create the component**

`apps/web/src/components/credentials/dynamic-credential-fields.tsx`:

```typescript
"use client";

import { FormEvent, useMemo, useState } from "react";
import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Spinner } from "@/components/ui/spinner";

export interface CredentialFieldOptionSpec {
  label: string;
  value: string;
}

export interface CredentialFieldSpec {
  name: string;
  label: string;
  type: string; // text | password | json | number | boolean | options
  required?: boolean;
  default?: unknown;
  placeholder?: string;
  description?: string;
  advanced?: boolean;
  options?: CredentialFieldOptionSpec[];
  showWhen?: { field: string; values: unknown[] };
}

export interface DynamicCredentialFieldsProps {
  fields: CredentialFieldSpec[];
  submitLabel?: string;
  onSubmit: (data: Record<string, unknown>) => Promise<void>;
}

function initialValues(fields: CredentialFieldSpec[]): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const field of fields) {
    values[field.name] = field.default ?? (field.type === "boolean" ? false : "");
  }
  return values;
}

function isVisible(field: CredentialFieldSpec, values: Record<string, unknown>): boolean {
  if (!field.showWhen) return true;
  const current = values[field.showWhen.field];
  return field.showWhen.values.some((value) => value === current);
}

export function DynamicCredentialFields({
  fields,
  submitLabel = "Save credential",
  onSubmit,
}: DynamicCredentialFieldsProps) {
  const [values, setValues] = useState<Record<string, unknown>>(() => initialValues(fields));
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const hasAdvanced = useMemo(() => fields.some((f) => f.advanced), [fields]);

  const setValue = (name: string, value: unknown) =>
    setValues((prev) => ({ ...prev, [name]: value }));

  const visible = fields.filter(
    (field) => isVisible(field, values) && (!field.advanced || showAdvanced)
  );

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    for (const field of fields) {
      if (field.required && isVisible(field, values) && !String(values[field.name] ?? "").trim()) {
        setError(`${field.label} is required.`);
        return;
      }
    }
    // Only submit fields that are currently visible (respect conditional hiding).
    const data: Record<string, unknown> = {};
    for (const field of fields) {
      if (isVisible(field, values)) data[field.name] = values[field.name];
    }
    setSaving(true);
    try {
      await onSubmit(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Credential could not be saved.");
    } finally {
      setSaving(false);
    }
  };

  const renderControl = (field: CredentialFieldSpec) => {
    const value = values[field.name];
    if (field.type === "boolean") {
      return (
        <label className="inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(event) => setValue(field.name, event.target.checked)}
            className="h-4 w-4 rounded border-input text-conduut-500 focus-visible:ring-2 focus-visible:ring-ring"
          />
          <span className="text-[12px] text-muted-foreground">{field.description ?? "Enable"}</span>
        </label>
      );
    }
    if (field.type === "options") {
      return (
        <select
          value={String(value ?? "")}
          onChange={(event) => setValue(field.name, event.target.value)}
          className="h-9 w-full rounded-lg border border-input bg-transparent px-3 text-[13px] text-foreground hover:border-gray-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {(field.options ?? []).map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      );
    }
    if (field.type === "json") {
      return (
        <Textarea
          value={String(value ?? "")}
          placeholder={field.placeholder}
          onChange={(event) => setValue(field.name, event.target.value)}
          className="min-h-[88px] font-mono text-[12px]"
        />
      );
    }
    return (
      <Input
        type={field.type === "password" ? "password" : field.type === "number" ? "number" : "text"}
        value={String(value ?? "")}
        placeholder={field.placeholder}
        onChange={(event) => setValue(field.name, event.target.value)}
        className="h-9 text-[13px]"
      />
    );
  };

  return (
    <form onSubmit={submit} className="space-y-2">
      {visible.map((field) => (
        <label key={field.name} className="block">
          <span className="mb-1 block text-[12px] font-medium text-muted-foreground">
            {field.label}
            {field.required && <span className="ml-0.5 text-error">*</span>}
          </span>
          {renderControl(field)}
          {field.description && field.type !== "boolean" && (
            <span className="mt-1 block text-[11px] text-muted-foreground">{field.description}</span>
          )}
        </label>
      ))}

      {hasAdvanced && (
        <button
          type="button"
          onClick={() => setShowAdvanced((open) => !open)}
          className="text-[12px] font-medium text-conduut-500 hover:text-conduut-700"
        >
          {showAdvanced ? "Hide advanced options" : "Advanced options"}
        </button>
      )}

      {error && (
        <p className="flex items-center gap-1.5 text-[12px] text-error">
          <AlertCircle className="h-3.5 w-3.5" />
          {error}
        </p>
      )}

      <Button type="submit" size="sm" disabled={saving} className="w-full">
        {saving && <Spinner size="sm" className="text-white" />}
        {submitLabel}
      </Button>
    </form>
  );
}
```

- [ ] **Step 2: Verify typecheck + lint**

Run: `cd apps/web && pnpm lint && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/credentials/dynamic-credential-fields.tsx
git commit -m "feat(web): DynamicCredentialFields (defaults, required, toggle, dropdown, conditional)"
```

---

### Task 7: Service picker uses `DynamicCredentialFields` + icon

**Files:**
- Modify: `apps/web/src/components/credentials/service-credential-picker.tsx`

**Interfaces:**
- Consumes: `DynamicCredentialFields`, `CredentialFieldSpec` (Task 6); the schema endpoint now returns `{label, iconUrl, fields: CredentialFieldSpec[]}`.

- [ ] **Step 1: Switch the form to DynamicCredentialFields + render icon**

In `service-credential-picker.tsx`:
- Replace the `serviceMethodFromFields` import/usage with `import { DynamicCredentialFields, type CredentialFieldSpec } from "@/components/credentials/dynamic-credential-fields";`.
- Change the local `ServiceCredentialField`/`fields` state type to `CredentialFieldSpec[]`, and the schema fetch response type to `{ fields?: CredentialFieldSpec[]; label?: string; iconUrl?: string }`. Store `iconUrl` in a new state (`const [iconUrl, setIconUrl] = useState("")`), set it in `pick()` from the response.
- In the selected view, replace the `CredentialForm` block with:

```tsx
        {loadingSchema ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : (
          <DynamicCredentialFields
            fields={fields}
            submitLabel="Save credential"
            onSubmit={(data) => onSubmit(selected.type, selected.label, data)}
          />
        )}
```

- Render the service icon next to the selected service name and in each catalog row when `icon_url`/`iconUrl` is present (use a plain `<img src={url} className="h-4 w-4" alt="" />` with a graceful fallback to the existing text when absent). The catalog list entries already carry `icon_url` from `GET /api/credentials/catalog`; extend the `CatalogEntry` interface with `icon_url?: string` and render `<img>` when set.

(Keep the existing search/debounce/error-handling logic from the prior version unchanged.)

- [ ] **Step 2: Verify typecheck + lint**

Run: `cd apps/web && pnpm lint && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/credentials/service-credential-picker.tsx
git commit -m "feat(web): service picker renders rich dynamic fields + service icons"
```

---

### Task 8: Chat predefined card uses `DynamicCredentialFields`

**Files:**
- Modify: `apps/web/src/components/chat/credential-request.tsx`

**Interfaces:**
- Consumes: `DynamicCredentialFields`, `CredentialFieldSpec` (Task 6). The card's `data.fields` for predefined (type-matched) cards now carry the rich spec; `data.iconUrl` may be present.

- [ ] **Step 1: Route type-matched cards through DynamicCredentialFields**

In `credential-request.tsx`:
- Extend `CredentialRequestData.fields` element type and the `CredentialField` interface here with the rich optional props (`default?`, `placeholder?`, `description?`, `advanced?`, `options?`, `showWhen?`) so they pass through to the component. Add `iconUrl?: string` and `matchKind?: string` (matchKind already added previously) to `CredentialRequestData`.
- For a **type-matched** card (`data.matchKind === "type"` and not a draft), render `DynamicCredentialFields` instead of `CredentialForm`:

```tsx
      {data.matchKind === "type" && !isDraft ? (
        <DynamicCredentialFields
          fields={data.fields as CredentialFieldSpec[]}
          submitLabel="Save credential"
          onSubmit={(formData) =>
            handleSubmit({
              credential_type: data.credentialType,
              generic_auth_type: "",
              label: data.credentialName,
              data: formData,
            } as CredentialSubmission)
          }
        />
      ) : (
        /* existing CredentialForm path for HTTP / draft cards, unchanged */
      )}
```

- The existing `handleSubmit` already includes `match_kind: data.matchKind`; for type-matched cards `generic_auth_type` is empty and the backend ignores it (match_kind="type"). Render `data.iconUrl` in the card header `<img>` when present.

- [ ] **Step 2: Verify typecheck + lint**

Run: `cd apps/web && pnpm lint && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/chat/credential-request.tsx
git commit -m "feat(web): chat type-matched credential card uses rich dynamic fields"
```

---

### Task 9: Populate data, live verify, docs

**Files:**
- Run: `packages/n8n-registry/scripts/fetch_credentials.py`
- Modify: `knowledge-database/03-desicions/adr-0015-predefined-credential-library.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Populate credentials.json**

Run (n8n container running): `python packages/n8n-registry/scripts/fetch_credentials.py`
Expected: `Saved 415 credential types (~600 KB) to .../data/credentials.json`. (Gitignored, like nodes.json.) Restart the agent so the registry loads it.

- [ ] **Step 2: Live verification (n8n + agent + web up)**

1. Dashboard → Credentials → Add → **Service** → "Anthropic" → form shows: **API Key** (required `*`) up front; **Advanced options** reveals **Base URL** pre-filled `https://api.anthropic.com`, **Add Custom Header** toggle (off); toggling it ON reveals **Header Name**/**Header Value**; **Allowed HTTP Request Domains** dropdown default "All". Save → n8n `anthropicApi` credential created (with url default).
2. Service catalog rows + selected header show the service icon.
3. Chat: "OpenAI anahtarımı ekle" → `add_service_credential` card renders the same rich form (API Key up front).
4. OAuth/generic types (Slack OAuth, Header Auth) do **not** appear in the Service catalog.

Note results; if a bug appears, use systematic-debugging and add a fix commit.

- [ ] **Step 3: Update docs**

In `adr-0015-predefined-credential-library.md`, add a short "Güncelleme (2026-06-26b)" note: field source moved from the public-API JSON-schema to `credentials.json` registry; form is now schema-driven (default/required/toggle/dropdown/conditional + icon) via `DynamicCredentialFields`. In `CLAUDE.md`, add a one-line entry under the 2026-06-26 session summary and list `packages/n8n-registry/scripts/fetch_credentials.py` + `components/credentials/dynamic-credential-fields.tsx` in Önemli dosyalar.

- [ ] **Step 4: Commit**

```bash
git add knowledge-database/03-desicions/adr-0015-predefined-credential-library.md CLAUDE.md
git commit -m "docs: schema-driven credential form note (ADR-0015 update + CLAUDE.md)"
```

---

## Self-Review

**1. Spec coverage:**
- credentials.json fetch + registry load → Task 1, 2, 4. ✓
- CredentialTypeInfo + is_oauth (name/extends/signature) + generic_auth → Task 1. ✓
- Catalog (label/icon, OAuth+generic excluded) → Task 2 + Task 4 route. ✓
- Rich CredentialField + definition→fields mapping (default/required/password/boolean/options/showWhen, notice skipped, non-required→advanced) → Task 3. ✓
- Schema route rich fields + iconUrl + OAuth/generic 422 + public-API fallback → Task 4. ✓
- add_service + readiness use definitions → Task 5. ✓
- Dead nodes.json-catalog/humanize removal → Task 5. ✓
- DynamicCredentialFields (defaults/required/toggle/dropdown/conditional/advanced/icon) → Task 6. ✓
- Service picker + chat card wiring + icons → Task 7, 8. ✓
- fetch script + live verify + docs → Task 2 (script), Task 9. ✓
- Non-goals (OAuth excluded, multi-key displayOptions→first key, manual sync) honored. ✓

**2. Placeholder scan:** Task 7/8 describe edits to existing components in prose with the key code blocks + exact anchors (the components are read in context at execution; full re-listing of those files is avoided per "follow existing patterns" — the changed regions have explicit code). No "TBD"/"add error handling". ✓

**3. Type consistency:**
- `CredentialTypeInfo(name, display_name, icon_url, documentation_url, properties, extends, generic_auth, is_oauth)` — Task 1 defines, Tasks 2/3/4/5 consume with matching attrs. ✓
- `list_credential_catalog(query=None) -> [{type,label,icon_url}]` — Task 2 defines; Tasks 4/5 use `icon_url` (snake) on the catalog dict, and the route passes it through as `icon_url` to the BFF; frontend `CatalogEntry.icon_url`. ✓ (Schema route returns `iconUrl` camelCase for the per-type response — distinct from the catalog-list `icon_url`; Tasks 4/7/8 use the right casing per surface.)
- `CredentialField` rich fields (`default/placeholder/description/advanced/options/showWhen`) — Task 3 defines (Pydantic), Task 6 mirrors (`CredentialFieldSpec` TS). `showWhen={field,values}` consistent both sides. ✓
- `credential_fields_from_definition(definition)` — Task 3 defines; Tasks 4/5 call. ✓
- Fixed during review: Task 4 Step 4 explicitly updates the prior-plan tests that patched the now-removed `list_credential_types`/`get_credential_schema` catalog path, preventing a stale-test failure.
