---
name: n8n-node
description: "n8n node registry'ye yeni bir node şeması ekler. RAG pipeline için kullanılır."
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# n8n node şeması ekle: $ARGUMENTS

packages/n8n-registry/ altına yeni bir n8n node tanımı ekle.

## Yapılacaklar

1. n8n'in resmi dokümanlarından veya kaynak kodundan $ARGUMENTS node'unun bilgilerini araştır
2. packages/n8n-registry/nodes/ altına `{node_name}.json` dosyası oluştur
3. Şema formatı:

```json
{
  "name": "node_display_name",
  "type": "n8n-nodes-base.{nodeName}",
  "credential_type": "{credentialType}",
  "description": "Bu node ne yapar",
  "operations": ["op1", "op2"],
  "required_fields": {
    "op1": ["field1", "field2"],
    "op2": ["field1"]
  },
  "optional_fields": {
    "op1": ["optField1"]
  },
  "example_workflow": {
    "nodes": [],
    "connections": {}
  },
  "oauth_scopes": ["scope1", "scope2"],
  "webhook_support": false,
  "trigger_support": false
}
```

4. packages/n8n-registry/index.json dosyasına node'u ekle
5. Mevcut node şemalarıyla tutarlılığı kontrol et
