FROM python:3.12-slim

WORKDIR /app

# n8n-registry paketini önce kur (agent dependency'si)
COPY packages/n8n-registry/pyproject.toml ./packages/n8n-registry/
COPY packages/n8n-registry/src ./packages/n8n-registry/src/
RUN pip install --no-cache-dir -e ./packages/n8n-registry

# Agent bağımlılıklarını kur
COPY apps/agent/pyproject.toml .
RUN pip install --no-cache-dir -e .

# Uygulama kaynak kodunu kopyala
COPY apps/agent/src/ ./src/

# Registry verilerini kopyala. nodes.json + credentials.json gitignored ve
# container-specific: build ÖNCESİ scripts/fetch_nodes.py + fetch_credentials.py
# çalıştırılmazsa node registry / credential katalogu boş gelir (ADR-0015).
# templates.json repoda tracked.
COPY packages/n8n-registry/data/ ./data/

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
