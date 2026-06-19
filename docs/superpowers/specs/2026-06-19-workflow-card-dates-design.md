# Workflow kartında tarihler — Tasarım

**Tarih:** 2026-06-19
**Durum:** Onaylandı (brainstorming)

## Amaç

Workflow dashboard kartlarında her workflow için:

1. **Son çalıştırma tarihi** (last run) — şu an arka uç doldurmadığı için kart hep "Never" gösteriyor.
2. **Oluşturma tarihi** (created).
3. Workflow **düzenlenmişse** oluşturma yerine **düzenleme tarihi** (edited).

## Mevcut durum (kod incelendi)

- `apps/web/src/types/workflow.ts` — `Workflow` tipi zaten `createdAt`, `updatedAt`,
  `lastExecutionAt`, `executionCount` alanlarına sahip. **Tip değişikliği gerekmez.**
- `apps/agent/src/routes/workflows.py` `list_workflows._enrich` — `createdAt` ve
  `updatedAt` döndürüyor; `lastExecutionAt` **hiç set edilmiyor** (kart "Never"),
  `executionCount` sabit `0`.
- `apps/web/src/components/dashboard/workflow-card.tsx` — footer'da `⚡ N nodes` +
  `lastExecutionAt`'e bağlı tek saat ikonu (boş olduğu için hep "Never").
- `apps/agent/src/n8n_client.py` `list_executions(workflow_id, limit)` mevcut; n8n en
  yeni execution'ı başta döndürür.

## Tasarım

### 1. Backend — `lastExecutionAt`'i doldur

`apps/agent/src/routes/workflows.py` → `_enrich`:

- Her workflow için `n8n_client.list_executions(workflow_id=w.id, limit=1)` çağır;
  ilk (en yeni) execution'ın `started_at` değerini `lastExecutionAt` olarak set et.
  Execution yoksa `None`.
- `get_workflow` (node sayısı) ve `list_executions` çağrılarını `_enrich` içinde
  `asyncio.gather` ile paralel yap — ekstra latency olmasın.
- `list_executions` hata verirse `try/except` ile yut → `lastExecutionAt = None`.
- `createdAt`/`updatedAt` aynen kalır. `executionCount` bu işin kapsamı dışında,
  dokunulmaz.

### 2. Frontend — kart footer'ı

`apps/web/src/components/dashboard/workflow-card.tsx` — onaylanan iki-satır düzeni:

```
🗓 Edited 3d ago          (düzenlenmişse Pencil ikonu + "Edited", değilse Calendar + "Created")
🕐 Last run 2h ago        (lastExecutionAt yoksa "Never run")
⚡ 5 nodes      Run  [⚪→]
```

- Yeni yardımcı `workflowDateMeta(workflow)` → `{ label: "Edited" | "Created", date, edited }`.
  - `created = Date(createdAt)`, `updated = Date(updatedAt)`.
  - `edited = updated - created > 60_000` (ms). True ise `label="Edited"`, `date=updatedAt`;
    aksi halde `label="Created"`, `date=createdAt`.
- İkon: `edited` ise `Pencil`, değilse `Calendar`. Son çalıştırma için `Clock` kalır.
- `formatRelativeTime` yeniden kullanılır. `lastExecutionAt` yoksa satır "Never run" gösterir.
- Footer yeniden düzenlenir: iki tarih satırı (üstte, açıklamadan `border-t` ile ayrık),
  altında `⚡ N nodes` (sol) + `Run` + toggle (sağ) satırı.

### 3. Test (TDD)

- **Backend:** `list_workflows` için test — `n8n_client.list_executions` mock'lanır;
  (a) execution dönerse `lastExecutionAt` en yeni execution'ın `startedAt`'i,
  (b) boş liste/hata durumunda `None`. Mevcut workflows-route test dosyası varsa oraya
  eklenir; yoksa yeni dosya.
- **Frontend:** Bileşen test harness'i varsa `workflowDateMeta` için birim test
  (created vs edited eşiği). Yoksa `pnpm typecheck && pnpm lint` ile doğrulama.

## Kabul edilen sınırlama

- n8n `updatedAt`, salt aktive/deaktive işleminde de değişir → bu durumda kart "Edited"
  gösterebilir. MVP için kabul edildi.
- Kart metinleri İngilizce (mevcut UI ile tutarlı).

## Doğrulama komutları

- Backend: `cd apps/agent && ruff check . && ruff format --check . && pytest`
- Frontend: `cd apps/web && pnpm lint && pnpm typecheck && pnpm test`
