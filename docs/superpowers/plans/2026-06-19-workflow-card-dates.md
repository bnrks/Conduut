# Workflow Kartında Tarihler — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Workflow dashboard kartında her workflow için oluşturma/düzenleme tarihi ve son çalıştırma tarihini göster.

**Architecture:** Arka uçta `list_workflows` enrich adımı, n8n executions API'den her workflow'un en son execution'ını çekip `lastExecutionAt`'i doldurur. Ön uçta kart, n8n `createdAt`/`updatedAt` farkına göre "Created" veya "Edited" satırı ve ayrı bir "Last run" satırı gösterir.

**Tech Stack:** Python 3.12 / FastAPI / pytest (backend), Next.js / React / TypeScript / Tailwind / lucide-react (frontend).

## Global Constraints

- Backend doğrulama: `cd apps/agent && ruff check . && ruff format --check . && pytest`
- Frontend doğrulama: `cd apps/web && pnpm lint && npx tsc --noEmit` (frontend birim test harness'i yok)
- `Workflow` TS tipi zaten `createdAt`, `updatedAt`, `lastExecutionAt`, `executionCount` içerir — **tip değişikliği yok**.
- Kart metinleri İngilizce (mevcut UI ile tutarlı).
- "Edited" eşiği: `updatedAt - createdAt > 60_000 ms`.
- Async fonksiyon tercih edilir; type hints zorunlu (Python).

---

### Task 1: Backend — `lastExecutionAt`'i n8n executions'tan doldur

**Files:**
- Modify: `apps/agent/src/routes/workflows.py` (`list_workflows._enrich`, ~117-137)
- Test: `apps/agent/tests/test_workflows_route.py` (yeni testler, dosya sonuna)

**Interfaces:**
- Consumes: `n8n_client.list_executions(workflow_id: str | None = None, limit: int = 10) -> list[N8nExecution]` (mevcut); `N8nExecution.started_at: str`; `n8n_client.N8nWorkflow(id, name, active, created_at, updated_at)`.
- Produces: `list_workflows` her workflow dict'ine `lastExecutionAt: str | None` ekler (en yeni execution'ın `started_at`'i, yoksa `None`). Diğer alanlar (`id`, `name`, `status`, `nodeCount`, `createdAt`, `updatedAt`, `executionCount`, `inputSchema`) değişmez.

- [ ] **Step 1: Failing test'leri yaz**

`apps/agent/tests/test_workflows_route.py` dosyasının sonuna ekle:

```python
@pytest.mark.asyncio
async def test_list_workflows_includes_last_execution_at(monkeypatch):
    monkeypatch.setattr(workflows_route, "get_user_id", lambda _request: "user_1")

    async def fake_list_workflows():
        return [
            workflows_route.n8n_client.N8nWorkflow(
                id="wf_1",
                name="Has runs",
                active=True,
                created_at="2026-06-10T10:00:00.000Z",
                updated_at="2026-06-12T10:00:00.000Z",
            ),
            workflows_route.n8n_client.N8nWorkflow(
                id="wf_2",
                name="No runs",
                active=False,
                created_at="2026-06-11T10:00:00.000Z",
                updated_at="2026-06-11T10:00:00.000Z",
            ),
        ]

    async def fake_get_workflow(workflow_id: str):
        return {"id": workflow_id, "nodes": [{"a": 1}, {"b": 2}]}

    async def fake_list_executions(*, workflow_id: str, limit: int):
        assert limit == 1
        if workflow_id == "wf_1":
            return [
                workflows_route.n8n_client.N8nExecution(
                    id="exec_2",
                    workflow_id="wf_1",
                    status="success",
                    started_at="2026-06-15T09:00:00.000Z",
                )
            ]
        return []

    async def fake_metadata(_user_id: str, _workflow_id: str):
        return None

    monkeypatch.setattr(workflows_route.n8n_client, "list_workflows", fake_list_workflows)
    monkeypatch.setattr(workflows_route.n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(workflows_route.n8n_client, "list_executions", fake_list_executions)
    monkeypatch.setattr(workflows_route.store, "get_workflow_metadata", fake_metadata)

    result = await workflows_route.list_workflows(object())

    by_id = {w["id"]: w for w in result["workflows"]}
    assert by_id["wf_1"]["lastExecutionAt"] == "2026-06-15T09:00:00.000Z"
    assert by_id["wf_1"]["nodeCount"] == 2
    assert by_id["wf_1"]["createdAt"] == "2026-06-10T10:00:00.000Z"
    assert by_id["wf_1"]["updatedAt"] == "2026-06-12T10:00:00.000Z"
    assert by_id["wf_2"]["lastExecutionAt"] is None


@pytest.mark.asyncio
async def test_list_workflows_tolerates_execution_lookup_failure(monkeypatch):
    monkeypatch.setattr(workflows_route, "get_user_id", lambda _request: "user_1")

    async def fake_list_workflows():
        return [
            workflows_route.n8n_client.N8nWorkflow(
                id="wf_1",
                name="Boom",
                active=True,
                created_at="2026-06-10T10:00:00.000Z",
                updated_at="2026-06-10T10:00:00.000Z",
            )
        ]

    async def fake_get_workflow(workflow_id: str):
        return {"id": workflow_id, "nodes": []}

    async def fake_list_executions(*, workflow_id: str, limit: int):
        raise workflows_route.n8n_client.N8nApiError(
            500, "executions disabled", method="GET", path="/executions"
        )

    async def fake_metadata(_user_id: str, _workflow_id: str):
        return None

    monkeypatch.setattr(workflows_route.n8n_client, "list_workflows", fake_list_workflows)
    monkeypatch.setattr(workflows_route.n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(workflows_route.n8n_client, "list_executions", fake_list_executions)
    monkeypatch.setattr(workflows_route.store, "get_workflow_metadata", fake_metadata)

    result = await workflows_route.list_workflows(object())

    assert result["workflows"][0]["lastExecutionAt"] is None
```

- [ ] **Step 2: Test'lerin başarısız olduğunu doğrula**

Run: `cd apps/agent && pytest tests/test_workflows_route.py -k last_execution -v`
Expected: FAIL — `KeyError: 'lastExecutionAt'` (alan henüz dict'te yok).

- [ ] **Step 3: `_enrich`'i minimal şekilde güncelle**

`apps/agent/src/routes/workflows.py` içindeki `_enrich` fonksiyonunu (mevcut hali node sayısını seri çeker) şununla değiştir:

```python
    async def _enrich(w: n8n_client.N8nWorkflow) -> dict:
        async def _node_count() -> int:
            try:
                detail = await n8n_client.get_workflow(w.id)
                return len(detail.get("nodes", []))
            except Exception:
                return 0

        async def _last_execution_at() -> str | None:
            try:
                executions = await n8n_client.list_executions(workflow_id=w.id, limit=1)
                return executions[0].started_at if executions else None
            except Exception:
                return None

        node_count, last_execution_at = await asyncio.gather(
            _node_count(), _last_execution_at()
        )
        metadata = await store.get_workflow_metadata(user_id, w.id)
        input_schema = _workflow_input_schema_from_metadata(metadata)
        return {
            "id": w.id,
            "name": w.name,
            "status": "active" if w.active else "inactive",
            "nodeCount": node_count,
            "lastExecutionAt": last_execution_at,
            "createdAt": w.created_at,
            "updatedAt": w.updated_at,
            "executionCount": 0,
            "inputSchema": _input_schema_payload(input_schema),
        }
```

- [ ] **Step 4: Test'lerin geçtiğini ve suite'in temiz olduğunu doğrula**

Run: `cd apps/agent && pytest tests/test_workflows_route.py -v && ruff check . && ruff format --check .`
Expected: Tüm testler PASS, ruff temiz.

- [ ] **Step 5: Commit**

```bash
git add apps/agent/src/routes/workflows.py apps/agent/tests/test_workflows_route.py
git commit -m "feat(workflows): list endpoint'inde lastExecutionAt'i n8n executions'tan doldur"
```

---

### Task 2: Frontend — kartta oluşturma/düzenleme + son çalıştırma satırları

**Files:**
- Modify: `apps/web/src/components/dashboard/workflow-card.tsx`

**Interfaces:**
- Consumes: `Workflow.createdAt: string`, `Workflow.updatedAt: string`, `Workflow.lastExecutionAt?: string` (Task 1'in arka uç çıktısı); mevcut `formatRelativeTime(dateStr?: string): string` helper'ı.
- Produces: Görsel değişiklik (testsiz). Yeni yerel helper `workflowDateMeta(workflow: Workflow): { label: "Edited" | "Created"; date: string; edited: boolean }`.

- [ ] **Step 1: lucide ikon importlarını genişlet**

`apps/web/src/components/dashboard/workflow-card.tsx` ilk import satırını değiştir:

```tsx
import { Calendar, Clock, Pencil, Play, Trash2, Zap } from "lucide-react";
```

- [ ] **Step 2: `workflowDateMeta` helper'ını ekle**

Dosyadaki mevcut `formatRelativeTime` fonksiyonunun hemen altına ekle:

```tsx
function workflowDateMeta(
  workflow: Workflow
): { label: "Edited" | "Created"; date: string; edited: boolean } {
  const created = new Date(workflow.createdAt).getTime();
  const updated = new Date(workflow.updatedAt).getTime();
  const edited =
    Number.isFinite(created) && Number.isFinite(updated) && updated - created > 60_000;
  return {
    label: edited ? "Edited" : "Created",
    date: edited ? workflow.updatedAt : workflow.createdAt,
    edited,
  };
}
```

- [ ] **Step 3: Footer JSX'ini iki-satır tarih bloğu + aksiyon satırı olacak şekilde değiştir**

Bileşen gövdesinde, `return (` içindeki `<CardContent ...>` altında `dateMeta` hesapla ve footer'ı yeniden yapılandır. Mevcut footer bloğunu (`{/* Footer */}` ile başlayan, `⚡ N nodes` + saat + Run + toggle'ı tek satırda tutan `<div className="flex items-center justify-between pt-1 border-t border-border">...</div>`) tamamen şununla değiştir:

```tsx
        {/* Dates */}
        <div className="flex flex-col gap-1 pt-1 border-t border-border">
          {(() => {
            const dateMeta = workflowDateMeta(workflow);
            return (
              <span className="flex items-center gap-1.5 text-[12px] text-muted-foreground tabular-nums">
                {dateMeta.edited ? (
                  <Pencil className="h-3 w-3" />
                ) : (
                  <Calendar className="h-3 w-3" />
                )}
                {dateMeta.label} {formatRelativeTime(dateMeta.date)}
              </span>
            );
          })()}
          <span className="flex items-center gap-1.5 text-[12px] text-muted-foreground tabular-nums">
            <Clock className="h-3 w-3" />
            {workflow.lastExecutionAt
              ? `Last run ${formatRelativeTime(workflow.lastExecutionAt)}`
              : "Never run"}
          </span>
        </div>

        {/* Footer: nodes + actions */}
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1 text-[12px] text-muted-foreground">
            <Zap className="h-3 w-3" />
            {workflow.nodeCount} nodes
          </span>

          <div className="flex items-center gap-2">
            {onRun && (
              <button
                type="button"
                disabled={isRunning}
                className={cn(
                  "flex h-7 items-center gap-1.5 rounded-md px-2 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  isRunning && "cursor-not-allowed opacity-70 hover:bg-transparent hover:text-muted-foreground"
                )}
                onClick={(e) => {
                  e.stopPropagation();
                  if (!isRunning) onRun(workflow);
                }}
              >
                {isRunning ? <Spinner size="sm" /> : <Play className="h-3.5 w-3.5" />}
                {isRunning ? "Running…" : "Run"}
              </button>
            )}

            <button
              role="switch"
              aria-checked={workflow.status === "active"}
              onClick={(e) => {
                e.stopPropagation();
                onToggle?.(workflow);
              }}
              className={cn(
                "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                workflow.status === "active" ? "bg-conduut-500" : "bg-gray-200"
              )}
            >
              <span
                className={cn(
                  "pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow-sm ring-0 transition-transform duration-200",
                  workflow.status === "active" ? "translate-x-4" : "translate-x-0"
                )}
              />
            </button>
          </div>
        </div>
```

Not: `Zap`, `Play`, `Clock`, `Spinner`, `cn` zaten import edilmiş durumda kalır; yalnızca eski tek-saat (`lastExecutionAt`) gösterimi yeni iki-satır bloğuyla değiştirilir.

- [ ] **Step 4: Typecheck ve lint**

Run: `cd apps/web && npx tsc --noEmit && pnpm lint`
Expected: tsc hata yok; eslint 0 hata.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/dashboard/workflow-card.tsx
git commit -m "feat(dashboard): workflow kartında oluşturma/düzenleme ve son çalıştırma tarihleri"
```

---

### Task 3: Knowledge-base ve CLAUDE.md güncellemesi

**Files:**
- Modify: `CLAUDE.md` (oturum özeti / önemli dosyalar)
- Modify: `knowledge-database/04-features/` ilgili not (varsa `dashboard.md` / workflow özelliği notu)

**Interfaces:**
- Consumes: yok. Produces: yok (dokümantasyon).

- [ ] **Step 1: CLAUDE.md'ye kısa oturum özeti ekle**

`CLAUDE.md` içine 2026-06-19 tarihli kısa bir bölüm ekle: workflow kartında `lastExecutionAt` artık n8n executions'tan dolduruluyor; kart created/edited (updatedAt-createdAt > 60sn eşiği) + last run gösteriyor; kabul edilen sınırlama (aktive/deaktive de updatedAt'i değiştirir → "Edited" görünebilir).

- [ ] **Step 2: knowledge-database dashboard/feature notunu güncelle**

`knowledge-database/04-features/` veya `knowledge-database/02-architecture/web-app.md` içinde dashboard workflow kartı bahsi varsa, kart artık tarih bilgisi gösteriyor diye güncelle. İlgili not yoksa bu adım atlanır.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md knowledge-database
git commit -m "docs: workflow kartı tarih özelliği — oturum özeti ve knowledge-base"
```

---

## Self-Review

**Spec coverage:**
- Son çalıştırma tarihi → Task 1 (`lastExecutionAt`) + Task 2 ("Last run" satırı). ✓
- Oluşturma tarihi → Task 2 ("Created" satırı, mevcut `createdAt`). ✓
- Düzenlenmişse düzenleme tarihi → Task 2 (`workflowDateMeta`, 60sn eşiği, "Edited"). ✓
- Workflows view'da gösterim → Task 2 (kart). ✓
- Kabul edilen sınırlama (aktive/deaktive → "Edited") → Task 3 dokümante eder. ✓

**Placeholder scan:** Tüm kod adımları tam içerik içeriyor; "TBD"/"TODO" yok. Task 3 Step 2 koşullu ("varsa") ama bu gerçek bir karar, placeholder değil.

**Type consistency:** `workflowDateMeta` dönüş tipi (`label`/`date`/`edited`) Task 2 içinde tanımlanıp aynı isimlerle tüketiliyor. Backend `lastExecutionAt` adı Task 1 ve Task 2'de tutarlı. `list_executions(workflow_id=..., limit=...)` keyword imzası mevcut client ile uyumlu.
