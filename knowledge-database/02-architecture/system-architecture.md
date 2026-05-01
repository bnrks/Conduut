# System Architecture

Merkez: [[index]]

Conduut mimarisi iki katmanda dusunulmeli: mevcut MVP ve hedef platform.

## Mevcut MVP

```text
Browser
  -> Next.js web app / API routes
  -> FastAPI agent service
  -> shared n8n instance
  -> Firestore for app state
```

Mevcut `docker-compose.yml` uc servis calistirir:

- `conduut-web`: Next.js frontend, port `3000`.
- `conduut-agent`: FastAPI agent, container port `8000`; local host port
  `8100` because Windows can reserve host port `8000`.
- `conduut-n8n`: tek shared n8n instance, port `5678`.

`apps/web/src/app/api/*` route handler'lari BFF/proxy gorevi gorur. Firebase ID
token'i browser'dan Next API route'a, oradan agent servisine Authorization
header olarak tasinir.

## Hedef Platform

Uzun vadeli hedef, `PROJECT.md` icinde anlatilan cok servisli platformdur:

- Agent service.
- Control plane.
- OAuth proxy.
- Her VPS uzerinde node-agent.
- Her kullaniciya ayri n8n container.
- PostgreSQL + pgvector, Redis, Vault, MinIO/S3.
- Traefik, monitoring ve billing.

Bu hedef henuz kodda yoktur. Yeni is planlanirken hedef mimariyle uyumlu
olmak iyi, fakat mevcut MVP'nin gercek sinirlarini bozmamak daha onemlidir.

## Ana Veri Akislari

- Chat: [[web-app]] -> [[agent-service]] -> LiteLLM -> n8n tools -> shared n8n.
- Conversation persistence: [[agent-service]] -> Firestore.
- Workflow list/toggle/delete: [[web-app]] API route -> agent workflow route ->
  `n8n_client.py` -> n8n REST API.
- Credential request: chat attachment -> [[web-app]] `/api/credentials` BFF ->
  [[agent-service]] `/api/credentials` -> n8n credential API -> workflow node
  attach.
- Workflow run: agent tool -> webhook-triggered workflow call -> n8n execution
  API -> agent internal verification -> normal assistant text response.
- Node knowledge: [[agent-service]] -> [[n8n-registry]].

## Mimari Dikkat Noktalari

- Shared n8n MVP karari icin bkz. [[adr-0001-shared-n8n-mvp]].
- Firestore MVP karari icin bkz. [[adr-0002-firestore-mvp]].
- API-key credential injection'in ilk fazi chat uzerinden uygulanmistir. OAuth
  proxy ve per-user isolation dokumanlarda gecse de henuz uygulanmamistir.
