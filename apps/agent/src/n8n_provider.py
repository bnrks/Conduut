from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from src import n8n_client, store
from src.config import canonical_n8n_version, settings, shared_dev_n8n_api_key
from src.n8n_security import N8nUrlValidationError, normalize_customer_owned_n8n_url
from src.n8n_target import N8nRequestContext, N8nTarget
from src.secret_store import SecretStore, get_secret_store


class N8nResolver(Protocol):
    async def resolve(
        self, user_id: str, *, request_id: str | None = None
    ) -> N8nRequestContext: ...


@dataclass(frozen=True)
class N8nPreflightResult:
    base_url: str
    webhook_base_url: str
    detected_version: str
    canonical_version: str
    compatibility_status: str
    capabilities: list[str]
    status: str
    last_error_code: str | None = None


class N8nProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        retryable: bool,
        action: str,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.action = action


class N8nConnectionRequiredError(N8nProviderError):
    def __init__(self, message: str = "Connect an n8n instance before continuing."):
        super().__init__(
            "n8n_connection_required",
            message,
            status_code=404,
            retryable=False,
            action="connect",
        )


class N8nConnectionUnreachableError(N8nProviderError):
    def __init__(self, message: str = "n8n instance is unreachable."):
        super().__init__(
            "n8n_unreachable",
            message,
            status_code=502,
            retryable=True,
            action="verify_n8n_url_and_network",
        )


class N8nAuthInvalidError(N8nProviderError):
    def __init__(self, message: str = "n8n API key is invalid."):
        super().__init__(
            "n8n_auth_invalid",
            message,
            status_code=401,
            retryable=True,
            action="rotate_n8n_api_key",
        )


class N8nVersionUnsupportedError(N8nProviderError):
    def __init__(self, *, detected_version: str, canonical_version: str):
        super().__init__(
            "n8n_version_unsupported",
            (
                "This n8n version is not supported by the current Conduut registry "
                f"(detected={detected_version or 'unknown'}, "
                f"canonical={canonical_version or 'unknown'})."
            ),
            status_code=409,
            retryable=False,
            action="upgrade_or_pin_n8n_version",
        )


class N8nVersionUnverifiableError(N8nProviderError):
    def __init__(self, message: str | None = None, *, action: str = "rebuild_registry_artifacts"):
        super().__init__(
            "n8n_version_unverifiable",
            message
            or (
                "Conduut could not determine the canonical supported n8n version "
                "from bundled registry artifacts."
            ),
            status_code=500,
            retryable=False,
            action=action,
        )


class N8nCapabilityMissingError(N8nProviderError):
    def __init__(self, message: str = "Required n8n API capability is missing."):
        super().__init__(
            "n8n_capability_missing",
            message,
            status_code=502,
            retryable=False,
            action="enable_required_n8n_public_api_capability",
        )


class N8nConfigurationError(N8nProviderError):
    def __init__(self, message: str):
        super().__init__(
            "n8n_configuration_error",
            message,
            status_code=500,
            retryable=False,
            action="fix_conduut_backend_configuration",
        )


class N8nInstanceChangedError(N8nProviderError):
    def __init__(self):
        super().__init__(
            "n8n_instance_changed",
            "Disconnect the current automation server before connecting a different instance.",
            status_code=409,
            retryable=False,
            action="disconnect",
        )


def error_detail(exc: N8nProviderError) -> dict[str, str]:
    return {
        "code": exc.code,
        "message": exc.message,
        "retryable": exc.retryable,
        "action": exc.action,
    }


def _normalized_version(value: str) -> str:
    text = str(value or "").strip().removeprefix("v")
    return text.split("-", 1)[0]


def _version_is_supported(detected_version: str, canonical_version: str) -> bool:
    if not canonical_version:
        return True
    return _normalized_version(detected_version) == _normalized_version(canonical_version)


def _display_host(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.path and parsed.path != "/":
        return f"{parsed.netloc}{parsed.path}"
    return parsed.netloc


def _shared_dev_target() -> N8nTarget:
    if str(settings.environment or "").strip().lower() == "production":
        raise N8nConfigurationError(
            "Shared development n8n mode is disabled in production. "
            "Set CONDUUT_N8N_PROVIDER_MODE=customer_owned."
        )
    base_url = str(settings.n8n_url or "").strip().rstrip("/")
    api_key = shared_dev_n8n_api_key()
    if not base_url or not api_key:
        raise N8nConfigurationError("Shared development n8n config is incomplete.")
    return N8nTarget(
        tenant_id="shared_dev",
        instance_id="shared_dev",
        ownership="shared_dev",
        base_url=base_url,
        webhook_base_url=base_url,
        api_key_secret_ref="env:CONDUUT_DEV_SHARED_N8N_API_KEY",
        n8n_version=canonical_n8n_version(),
        api_key=api_key,
    )


class N8nClientFactory:
    def __init__(self, *, secret_store: SecretStore | None = None):
        self._secret_store = secret_store or get_secret_store()

    async def for_target(self, target: N8nTarget) -> n8n_client.N8nClient:
        api_key = target.api_key
        if api_key is None:
            try:
                api_key = await self._secret_store.get_secret(target.api_key_secret_ref)
            except Exception as exc:
                raise N8nConfigurationError(
                    "Conduut could not access the stored n8n credential."
                ) from exc
        if not api_key:
            raise N8nConnectionRequiredError(
                "Stored n8n credentials are missing. Reconnect the instance."
            )
        return n8n_client.N8nClient(
            base_url=target.base_url,
            api_key=api_key,
            webhook_base_url=target.webhook_base_url,
            instance_id=target.instance_id,
            ownership=target.ownership,
        )

    async def for_request_context(self, context: N8nRequestContext) -> n8n_client.N8nClient:
        return await self.for_target(context.target)


class N8nInstanceResolver:
    def __init__(self, *, secret_store: SecretStore | None = None):
        self._secret_store = secret_store or get_secret_store()

    async def resolve(self, user_id: str, *, request_id: str | None = None) -> N8nRequestContext:
        mode = str(settings.n8n_provider_mode or "shared_dev").strip().lower()
        if mode == "shared_dev":
            return N8nRequestContext(
                user_id=user_id, request_id=request_id, target=_shared_dev_target()
            )
        if mode != "customer_owned":
            raise N8nConfigurationError(
                "Unsupported CONDUUT_N8N_PROVIDER_MODE; expected shared_dev or customer_owned."
            )

        instance = await store.get_active_n8n_instance(user_id)
        if not instance or instance.connection_status != "connected":
            raise N8nConnectionRequiredError()

        return N8nRequestContext(
            user_id=user_id,
            request_id=request_id,
            target=N8nTarget(
                tenant_id=user_id,
                instance_id=instance.id,
                ownership="customer_owned",
                base_url=instance.base_url,
                webhook_base_url=instance.webhook_base_url,
                api_key_secret_ref=instance.api_key_secret_ref,
                n8n_version=instance.n8n_version,
            ),
        )

    async def preflight(
        self,
        *,
        base_url: str,
        api_key: str,
        webhook_base_url: str | None = None,
    ) -> N8nPreflightResult:
        try:
            normalized_url = normalize_customer_owned_n8n_url(base_url)
            normalized_webhook_url = (
                normalize_customer_owned_n8n_url(webhook_base_url)
                if webhook_base_url
                else normalized_url
            )
        except N8nUrlValidationError as exc:
            raise N8nConnectionUnreachableError(str(exc)) from exc

        client = n8n_client.N8nClient(
            base_url=normalized_url,
            api_key=api_key,
            webhook_base_url=normalized_webhook_url,
            ownership="customer_owned",
            instance_id="preflight",
        )
        try:
            is_healthy = await client.health_check()
            if not is_healthy:
                raise N8nConnectionUnreachableError("n8n health check did not succeed.")
            payload = await client.get_rest_settings()
            workflows_response = await client.request("GET", "/workflows", params={"limit": 1})
            n8n_client._raise_for_status(workflows_response)
            executions_response = await client.request("GET", "/executions", params={"limit": 1})
            n8n_client._raise_for_status(executions_response)
            credential_response = await client.request("GET", "/credentials/schema/httpBasicAuth")
            n8n_client._raise_for_status(credential_response)
        except n8n_client.N8nApiError as exc:
            if exc.status_code in {401, 403}:
                raise N8nAuthInvalidError() from exc
            if exc.status_code in {404, 405} and exc.path.startswith("/credentials"):
                raise N8nCapabilityMissingError() from exc
            raise N8nConnectionUnreachableError(exc.message) from exc
        except httpx.HTTPError as exc:
            raise N8nConnectionUnreachableError() from exc

        detected_version = n8n_client.extract_n8n_version(payload)
        if not detected_version:
            raise N8nVersionUnverifiableError(
                "Conduut could not verify the connected n8n instance version.",
                action="verify_n8n_version",
            )
        canonical_version = canonical_n8n_version()
        if not canonical_version:
            raise N8nVersionUnverifiableError()
        if not _version_is_supported(detected_version, canonical_version):
            raise N8nVersionUnsupportedError(
                detected_version=detected_version,
                canonical_version=canonical_version,
            )
        return N8nPreflightResult(
            base_url=normalized_url,
            webhook_base_url=normalized_webhook_url,
            detected_version=detected_version,
            canonical_version=canonical_version,
            compatibility_status="supported",
            capabilities=["workflows", "executions", "credentials"],
            status="connected",
        )

    async def connect(
        self,
        user_id: str,
        *,
        base_url: str,
        api_key: str,
        display_name: str,
        webhook_base_url: str | None = None,
    ) -> store.N8nInstanceRecord:
        if await store.get_active_n8n_instance(user_id) is not None:
            raise N8nInstanceChangedError()
        preflight = await self.preflight(
            base_url=base_url,
            api_key=api_key,
            webhook_base_url=webhook_base_url,
        )
        instance_id = f"n8n_{uuid4().hex}"
        secret_ref = f"{user_id}/{instance_id}/api_key"
        await self._secret_store.put_secret(secret_ref, api_key)
        try:
            return await store.save_n8n_instance(
                user_id,
                instance_id=instance_id,
                display_name=display_name,
                ownership="customer_owned",
                provider="manual",
                base_url=preflight.base_url,
                webhook_base_url=preflight.webhook_base_url,
                api_key_secret_ref=secret_ref,
                n8n_version=preflight.detected_version,
                compatibility_status=preflight.compatibility_status,
                connection_status=preflight.status,
                capabilities=preflight.capabilities,
                verified_at=store._now_iso(),
                last_health_at=store._now_iso(),
                last_error_code=preflight.last_error_code,
                is_active=True,
            )
        except Exception:
            await self._secret_store.delete_secret(secret_ref)
            raise

    async def rotate(
        self,
        user_id: str,
        *,
        api_key: str,
        base_url: str | None = None,
        webhook_base_url: str | None = None,
        display_name: str | None = None,
    ) -> store.N8nInstanceRecord:
        existing = await store.get_active_n8n_instance(user_id)
        if not existing:
            raise N8nConnectionRequiredError()
        preflight = await self.preflight(
            base_url=base_url or existing.base_url,
            api_key=api_key,
            webhook_base_url=webhook_base_url or existing.webhook_base_url,
        )
        if hasattr(self._secret_store, "put_secret_version"):
            await self._secret_store.put_secret_version(existing.api_key_secret_ref, api_key)
        else:
            await self._secret_store.put_secret(existing.api_key_secret_ref, api_key)
        return await store.save_n8n_instance(
            user_id,
            instance_id=existing.id,
            display_name=display_name or existing.display_name,
            ownership=existing.ownership,
            provider=existing.provider,
            base_url=preflight.base_url,
            webhook_base_url=preflight.webhook_base_url,
            api_key_secret_ref=existing.api_key_secret_ref,
            n8n_version=preflight.detected_version,
            compatibility_status=preflight.compatibility_status,
            connection_status=preflight.status,
            capabilities=preflight.capabilities,
            verified_at=store._now_iso(),
            last_health_at=store._now_iso(),
            last_error_code=preflight.last_error_code,
            is_active=True,
        )

    async def check(self, user_id: str) -> store.N8nInstanceRecord:
        existing = await store.get_active_n8n_instance(
            user_id
        ) or await store.get_latest_n8n_instance(user_id)
        if not existing:
            raise N8nConnectionRequiredError()
        api_key = await self._secret_store.get_secret(existing.api_key_secret_ref)
        if not api_key:
            return await store.save_n8n_instance(
                user_id,
                instance_id=existing.id,
                display_name=existing.display_name,
                ownership=existing.ownership,
                provider=existing.provider,
                base_url=existing.base_url,
                webhook_base_url=existing.webhook_base_url,
                api_key_secret_ref=existing.api_key_secret_ref,
                n8n_version=existing.n8n_version,
                compatibility_status=existing.compatibility_status,
                connection_status="auth_invalid",
                capabilities=existing.capabilities,
                verified_at=existing.verified_at,
                last_health_at=store._now_iso(),
                last_error_code="n8n_auth_invalid",
                is_active=existing.is_active,
            )
        try:
            preflight = await self.preflight(
                base_url=existing.base_url,
                api_key=api_key,
                webhook_base_url=existing.webhook_base_url,
            )
            status = preflight.status
            error_code = preflight.last_error_code
            version = preflight.detected_version
            compatibility_status = preflight.compatibility_status
            capabilities = preflight.capabilities
        except N8nProviderError as exc:
            status = {
                "n8n_unreachable": "unreachable",
                "n8n_auth_invalid": "auth_invalid",
                "n8n_version_unsupported": "unsupported",
                "n8n_version_unverifiable": "unsupported",
                "n8n_capability_missing": "unsupported",
            }.get(exc.code, existing.connection_status)
            error_code = exc.code
            version = existing.n8n_version
            compatibility_status = existing.compatibility_status
            capabilities = existing.capabilities
        return await store.save_n8n_instance(
            user_id,
            instance_id=existing.id,
            display_name=existing.display_name,
            ownership=existing.ownership,
            provider=existing.provider,
            base_url=existing.base_url,
            webhook_base_url=existing.webhook_base_url,
            api_key_secret_ref=existing.api_key_secret_ref,
            n8n_version=version,
            compatibility_status=compatibility_status,
            connection_status=status,
            capabilities=capabilities,
            verified_at=existing.verified_at if status != "connected" else store._now_iso(),
            last_health_at=store._now_iso(),
            last_error_code=error_code,
            is_active=existing.is_active,
        )

    async def disconnect(self, user_id: str) -> store.N8nInstanceRecord:
        existing = await store.get_active_n8n_instance(
            user_id
        ) or await store.get_latest_n8n_instance(user_id)
        if not existing:
            raise N8nConnectionRequiredError()
        disconnecting = await store.save_n8n_instance(
            user_id,
            instance_id=existing.id,
            display_name=existing.display_name,
            ownership=existing.ownership,
            provider=existing.provider,
            base_url=existing.base_url,
            webhook_base_url=existing.webhook_base_url,
            api_key_secret_ref=existing.api_key_secret_ref,
            n8n_version=existing.n8n_version,
            compatibility_status=existing.compatibility_status,
            connection_status="disconnecting",
            capabilities=existing.capabilities,
            verified_at=existing.verified_at,
            last_health_at=existing.last_health_at,
            last_error_code=None,
            is_active=False,
        )
        await self._secret_store.delete_secret(existing.api_key_secret_ref)
        return await store.save_n8n_instance(
            user_id,
            instance_id=existing.id,
            display_name=disconnecting.display_name,
            ownership=disconnecting.ownership,
            provider=disconnecting.provider,
            base_url=disconnecting.base_url,
            webhook_base_url=disconnecting.webhook_base_url,
            api_key_secret_ref="",
            n8n_version=disconnecting.n8n_version,
            compatibility_status=disconnecting.compatibility_status,
            connection_status="disconnected",
            capabilities=disconnecting.capabilities,
            verified_at=disconnecting.verified_at,
            last_health_at=store._now_iso(),
            last_error_code=None,
            is_active=False,
        )
