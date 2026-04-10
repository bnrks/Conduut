"""Firestore tabanlı store. Tüm sync Firestore çağrıları asyncio.to_thread ile sarılır."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from src.firebase import db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


# ---------------------------------------------------------------------------
# Dataclass'lar (route'larda kullanılır)
# ---------------------------------------------------------------------------


@dataclass
class LLMSettings:
    provider: str
    model: str
    api_key: str


@dataclass
class ProviderConnection:
    provider: str
    api_key: str

    @property
    def masked_key(self) -> str:
        if len(self.api_key) <= 8:
            return "****"
        return self.api_key[:4] + "****" + self.api_key[-4:]


@dataclass
class Message:
    id: str
    role: str
    content: str
    created_at: str
    provider: str | None = None
    model: str | None = None
    attachments: list[dict] | None = None


@dataclass
class Conversation:
    id: str
    title: str
    message_count: int
    created_at: str
    updated_at: str
    provider: str | None = None
    model: str | None = None
    messages: list[Message] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_ref(user_id: str):
    return db.collection("users").document(user_id)


def _conv_ref(user_id: str, conv_id: str):
    return _user_ref(user_id).collection("conversations").document(conv_id)


def _msg_ref(user_id: str, conv_id: str, msg_id: str):
    return _conv_ref(user_id, conv_id).collection("messages").document(msg_id)


async def _run(fn):
    return await asyncio.to_thread(fn)


# ---------------------------------------------------------------------------
# LLM Settings
# ---------------------------------------------------------------------------


async def get_llm_settings(user_id: str) -> LLMSettings | None:
    doc = await _run(lambda: _user_ref(user_id).collection("settings").document("llm").get())
    if not doc.exists:
        return None
    d = doc.to_dict()
    return LLMSettings(provider=d["provider"], model=d["model"], api_key=d["api_key"])


async def save_llm_settings(user_id: str, provider: str, model: str, api_key: str) -> LLMSettings:
    await _run(
        lambda: (
            _user_ref(user_id)
            .collection("settings")
            .document("llm")
            .set({"provider": provider, "model": model, "api_key": api_key})
        )
    )
    return LLMSettings(provider=provider, model=model, api_key=api_key)


async def delete_llm_settings(user_id: str) -> None:
    await _run(lambda: _user_ref(user_id).collection("settings").document("llm").delete())


# ---------------------------------------------------------------------------
# Provider Connections
# ---------------------------------------------------------------------------


async def list_providers(user_id: str) -> list[ProviderConnection]:
    docs = await _run(lambda: list(_user_ref(user_id).collection("providers").stream()))
    return [ProviderConnection(provider=d.id, api_key=d.to_dict().get("api_key", "")) for d in docs]


async def get_provider(user_id: str, provider: str) -> ProviderConnection | None:
    doc = await _run(lambda: _user_ref(user_id).collection("providers").document(provider).get())
    if not doc.exists:
        return None
    return ProviderConnection(provider=provider, api_key=doc.to_dict().get("api_key", ""))


async def save_provider(user_id: str, provider: str, api_key: str) -> list[ProviderConnection]:
    await _run(
        lambda: (
            _user_ref(user_id).collection("providers").document(provider).set({"api_key": api_key})
        )
    )  # noqa: E501
    return await list_providers(user_id)


async def get_favorites(user_id: str) -> dict[str, list[str]]:
    """{ provider: [model_id, ...] }"""
    doc = await _run(lambda: _user_ref(user_id).collection("settings").document("favorites").get())
    if not doc.exists:
        return {}
    return doc.to_dict() or {}


async def add_favorite(user_id: str, provider: str, model: str) -> dict[str, list[str]]:
    ref = _user_ref(user_id).collection("settings").document("favorites")

    def _update():
        doc = ref.get()
        data = doc.to_dict() or {} if doc.exists else {}
        models = data.get(provider, [])
        if model not in models:
            models.append(model)
        data[provider] = models
        ref.set(data)
        return data

    return await _run(_update)


async def remove_favorite(user_id: str, provider: str, model: str) -> dict[str, list[str]]:
    ref = _user_ref(user_id).collection("settings").document("favorites")

    def _update():
        doc = ref.get()
        data = doc.to_dict() or {} if doc.exists else {}
        models = data.get(provider, [])
        if model in models:
            models.remove(model)
        data[provider] = models
        ref.set(data)
        return data

    return await _run(_update)


async def delete_provider(user_id: str, provider: str) -> list[ProviderConnection] | None:
    doc = await _run(lambda: _user_ref(user_id).collection("providers").document(provider).get())
    if not doc.exists:
        return None
    await _run(lambda: _user_ref(user_id).collection("providers").document(provider).delete())
    return await list_providers(user_id)


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


async def list_conversations(user_id: str) -> list[Conversation]:
    docs = await _run(
        lambda: list(
            _user_ref(user_id)
            .collection("conversations")
            .order_by("updated_at", direction="DESCENDING")
            .stream()
        )
    )
    result = []
    for d in docs:
        data = d.to_dict()
        result.append(
            Conversation(
                id=d.id,
                title=data.get("title", "New conversation"),
                message_count=data.get("message_count", 0),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
            )
        )
    return result


async def get_conversation(user_id: str, conv_id: str) -> Conversation | None:
    doc = await _run(lambda: _conv_ref(user_id, conv_id).get())
    if not doc.exists:
        return None
    data = doc.to_dict()

    msg_docs = await _run(
        lambda: list(
            _conv_ref(user_id, conv_id).collection("messages").order_by("created_at").stream()
        )
    )
    messages = [
        Message(
            id=m.id,
            role=m.to_dict()["role"],
            content=m.to_dict()["content"],
            created_at=m.to_dict()["created_at"],
            provider=m.to_dict().get("provider"),
            model=m.to_dict().get("model"),
            attachments=m.to_dict().get("attachments"),
        )
        for m in msg_docs
    ]

    return Conversation(
        id=doc.id,
        title=data.get("title", "New conversation"),
        message_count=data.get("message_count", 0),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        provider=data.get("provider"),
        model=data.get("model"),
        messages=messages,
    )


async def get_or_create_conversation(
    user_id: str,
    conv_id: str | None,
    provider: str | None = None,
    model: str | None = None,
) -> Conversation:
    if conv_id:
        doc = await _run(lambda: _conv_ref(user_id, conv_id).get())
        if doc.exists:
            data = doc.to_dict()
            return Conversation(
                id=conv_id,
                title=data.get("title", "New conversation"),
                message_count=data.get("message_count", 0),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
                provider=data.get("provider"),
                model=data.get("model"),
            )

    new_id = str(uuid4())
    now = _now_iso()
    doc_data: dict = {
        "title": "New conversation",
        "message_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    if provider:
        doc_data["provider"] = provider
    if model:
        doc_data["model"] = model

    await _run(lambda: _conv_ref(user_id, new_id).set(doc_data))
    return Conversation(
        id=new_id,
        title="New conversation",
        message_count=0,
        created_at=now,
        updated_at=now,
        provider=provider,
        model=model,
    )  # noqa: E501


async def add_message(
    user_id: str,
    conv_id: str,
    role: str,
    content: str,
    provider: str | None = None,
    model: str | None = None,
    attachments: list[dict] | None = None,
) -> Message:
    msg_id = str(uuid4())
    now = _now_iso()

    data: dict = {"role": role, "content": content, "created_at": now}
    if provider:
        data["provider"] = provider
    if model:
        data["model"] = model
    if attachments:
        data["attachments"] = attachments

    await _run(lambda: _msg_ref(user_id, conv_id, msg_id).set(data))

    # Conversation'ı güncelle
    conv_ref = _conv_ref(user_id, conv_id)

    def _update():
        doc = conv_ref.get()
        data = doc.to_dict() if doc.exists else {}
        count = data.get("message_count", 0) + 1
        update = {"message_count": count, "updated_at": now}
        if role == "user" and data.get("title") == "New conversation":
            update["title"] = content[:60] + ("..." if len(content) > 60 else "")
        conv_ref.update(update)

    await _run(_update)
    return Message(
        id=msg_id,
        role=role,
        content=content,
        created_at=now,
        provider=provider,
        model=model,
        attachments=attachments or None,
    )


async def get_conversation_messages(user_id: str, conv_id: str) -> list[Message]:
    docs = await _run(
        lambda: list(
            _conv_ref(user_id, conv_id).collection("messages").order_by("created_at").stream()
        )
    )
    return [
        Message(
            id=d.id,
            role=d.to_dict()["role"],
            content=d.to_dict()["content"],
            created_at=d.to_dict()["created_at"],
        )
        for d in docs
    ]


async def delete_conversation(user_id: str, conv_id: str) -> bool:
    doc = await _run(lambda: _conv_ref(user_id, conv_id).get())
    if not doc.exists:
        return False

    # Mesajları sil
    msg_docs = await _run(lambda: list(_conv_ref(user_id, conv_id).collection("messages").stream()))
    for m in msg_docs:
        await _run(
            lambda mid=m.id: (
                _conv_ref(user_id, conv_id).collection("messages").document(mid).delete()
            )
        )  # noqa: E501

    await _run(lambda: _conv_ref(user_id, conv_id).delete())
    return True
