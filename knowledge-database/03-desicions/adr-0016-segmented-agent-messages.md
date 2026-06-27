# ADR 0016: Segmented Agent Messages (interleaved bubbles + activity)

Merkez: [[index]]

## Durum

Accepted - 2026-06-27. Canli dogrulandi (DeepSeek-pro): segmentasyon calisiyor,
leak gitti, main'e merge edildi (commit a6079ff).

## Baglam

Bir agent run'i birden cok **model turu** icerir (her tur = bir
`POST /chat/completions`). Model her turda kullaniciya "simdi sunu yapiyorum"
diye kisa bir ara-anlati yaziyordu ve `runner.py` `full_content =
"".join(text_chunks)` ile **tum turlarin metnini tek balona yapistiriyordu**.
Sonuc: surec narrasyonu nihai mesaja sizmis gibi gorunen tek, cirkin bir balon
(glue-mark'lar: `kontrol edeyim.Anthropic`, `olusturuyorum.Is`). Concat tum
modellerde latent'ti ama Claude/GPT metni genelde sadece son turda urettigi icin
temiz cikiyordu; DeepSeek-pro her turda gevezelik edince yuzeye cikti.

Anahtar gozlem: SSE stream **zaten dogru sirada** (`R1 token -> R1 tool_call ->
R2 token -> ...`); `emit_tool_call` tool **calisirken** (model turundan sonraki
CallToolsNode'da) `event_queue`'ya dusuyor. Yani segment sinirlari
`token<->tool_call` degisiminden cikarilabilir; yeni SSE event tipi gerekmez.

## Karar

Tek-balon-concat yerine **interleaved agentic UX** (ChatGPT/Claude gibi): her
model turunun metni **ayri balon**, aralarinda o turda yapilan isin **tek satir
aktivite** ozeti. Reload'da `steps` Firestore'dan yeniden kurulur.

- **Cikarim kurali (backend + frontend AYNI):** `token` -> mevcut `text` adimina
  ekle (yoksa ac); `tool_call` -> mevcut `activity` adimina action ekle (yoksa ac);
  thinking/attachment segment yapisini etkilemez. Bir turdaki paralel araclar tek
  `activity` adiminda toplanir.
- **Veri modeli:** mesaja sirali `steps` alani —
  `{"kind":"text","text":str}` / `{"kind":"activity","actions":[tool_keys]}`.
  `content` (tum metnin birlesimi) **aynen korunur** -> history, arama, baslik,
  eski-mesaj fallback hic degismez. `actions` ham tool key tutar; friendly label
  + dedupe frontend'de (`activityLineLabel`).
- **Esik:** `steps` yalnizca **`len > 1`** ise kaydedilir/render edilir
  (backend `_persist_and_done`, frontend `useSteps`). Tek-adimli ve eski
  (steps'siz) mesajlar tek balon olarak render -> geriye uyumlu, migrasyon yok.
- **Kapsam (V1):** tum modeller; ekler ve thinking paneli segment'lerden sonra,
  en sonda (konum-duyarli ek + per-segment thinking ileride).

## Eklenen/degisen

- `agent/step_assembler.py` (**yeni**): `StepAssembler` + `build_steps` (saf,
  test-edilebilir, I/O yok). Hem live (`_run_live`) hem buffered (`build_steps(buffer)`)
  yol besler.
- `runner.py`: assembler wiring (live ana dongu + drain; buffered replay), esik
  `_persist_and_done`'da.
- `store.py`: `Message.steps` + `add_message(steps=)` + `get_conversation*` okur.
- `routes/conversations.py`: GET serileştirmesine `steps` eklendi (**final review
  Critical C1**: bu seam'i hicbir task sahiplenmemisti -> reload segment gostermiyordu).
- Frontend: `types/chat.ts` `AgentStep`; `messages.ts` normalize; `tool-activity.ts`
  6 eksik label + `activityLineLabel`; `message.tsx` segment render + fallback
  (**Critical C2**: `useSteps` clarification bastirmasini (`inputRequestAttachments`)
  atliyordu); `[conversationId]/page.tsx` + `chat/page.tsx` canli `steps` insasi.

## Internal-context echo leak (ayni oturum, ayri kok-neden)

Canli dogrulamada bulundu: `_history_from_store_messages`, prior mesajlara model
**GIRDISI** olarak `[Conduut internal context for future tool calls: ...]`
ekliyor (`_content_with_attachment_context`). DeepSeek-pro bunu history'den
**taklit edip** cevabina yaziyor -> balona siziyor (segmentasyondan degil,
on-mevcut). Fix: deterministik `strip_internal_context()` — buffered `_replay_buffer`
(ardisik token'lari gruplayip token-sinirina yayilan notu siler) + `_persist_and_done`
(content + step metni) + prompt kurali. Strip garanti; prompt kaynakta azaltir.
(bkz. [[known-issues]])

## Sonuc

TDD, subagent-driven (6 task + final review + 2 Critical fix + leak fix).
Backend 366 passed (5 on-mevcut Windows-tmp), ruff temiz; frontend tsc 0 / lint 0.
Final whole-branch review (opus) iki Critical seam-bug yakaladi (C1/C2) — task
review'larin yapisal olarak goremedigi; ikisi de duzeltildi. Canli: interleaved
balonlar + aktivite satirlari, DeepSeek artik yapistirmıyor, leak yok.

Spec: `docs/superpowers/specs/2026-06-27-segmented-agent-messages-design.md`.
Plan: `docs/superpowers/plans/2026-06-27-segmented-agent-messages.md`.
