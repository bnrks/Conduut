from dataclasses import dataclass
from typing import Literal

N8nOwnership = Literal["shared_dev", "customer_owned"]


@dataclass(frozen=True)
class N8nTarget:
    tenant_id: str
    instance_id: str
    ownership: N8nOwnership
    base_url: str
    webhook_base_url: str
    api_key_secret_ref: str
    n8n_version: str
    api_key: str | None = None


@dataclass(frozen=True)
class N8nRequestContext:
    user_id: str
    request_id: str | None
    target: N8nTarget
