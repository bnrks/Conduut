"""Conversations and messages — chat history."""

from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

import src.store as _pkg_store
from src.agent.setup_guide import SetupStageName, get_setup_stage_order

ExecutionPolicy = Literal["safe", "fast"]
ConversationMode = Literal["default", "automation-server-setup"]


@dataclass
class Message:
    id: str
    role: str
    content: str
    created_at: str
    provider: str | None = None
    model: str | None = None
    tier: str | None = None
    attachments: list[dict] | None = None
    steps: list[dict] | None = None


@dataclass
class Conversation:
    id: str
    title: str
    message_count: int
    created_at: str
    updated_at: str
    provider: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    execution_policy: ExecutionPolicy = "safe"
    execution_policy_locked: bool = True
    conversation_mode: ConversationMode = "default"
    setup_next_stage: SetupStageName | None = None
    setup_stage_locked: bool = False
    setup_last_stage: SetupStageName | None = None
    messages: list[Message] | None = None


def _conversation_execution_policy(data: dict | None) -> ExecutionPolicy:
    value = (data or {}).get("execution_policy")
    return "fast" if value == "fast" else "safe"


def _conversation_execution_policy_locked(data: dict | None) -> bool:
    value = (data or {}).get("execution_policy_locked")
    return True if value is None else bool(value)


def _conversation_mode(data: dict | None) -> ConversationMode:
    value = (data or {}).get("conversation_mode")
    return "automation-server-setup" if value == "automation-server-setup" else "default"


def _conversation_setup_next_stage(data: dict | None) -> SetupStageName | None:
    value = (data or {}).get("setup_next_stage")
    if value in get_setup_stage_order():
        return value
    return "requirements" if _conversation_mode(data) == "automation-server-setup" else None


def _conversation_setup_stage_locked(data: dict | None) -> bool:
    return bool((data or {}).get("setup_stage_locked") or False)


def _conversation_setup_last_stage(data: dict | None) -> SetupStageName | None:
    value = (data or {}).get("setup_last_stage")
    if value in get_setup_stage_order():
        return value
    return None


def _conv_ref(user_id: str, conv_id: str):
    return _pkg_store._user_ref(user_id).collection("conversations").document(conv_id)


def _msg_ref(user_id: str, conv_id: str, msg_id: str):
    return _pkg_store._conv_ref(user_id, conv_id).collection("messages").document(msg_id)


async def list_conversations(user_id: str) -> list[Conversation]:
    docs = await _pkg_store._run(
        lambda: list(
            _pkg_store._user_ref(user_id)
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
                execution_policy=_conversation_execution_policy(data),
                execution_policy_locked=_conversation_execution_policy_locked(data),
                conversation_mode=_conversation_mode(data),
                setup_next_stage=_conversation_setup_next_stage(data),
                setup_stage_locked=_conversation_setup_stage_locked(data),
                setup_last_stage=_conversation_setup_last_stage(data),
            )
        )
    return result


async def get_conversation(user_id: str, conv_id: str) -> Conversation | None:
    doc = await _pkg_store._run(lambda: _pkg_store._conv_ref(user_id, conv_id).get())
    if not doc.exists:
        return None
    data = doc.to_dict()

    msg_docs = await _pkg_store._run(
        lambda: list(
            _pkg_store._conv_ref(user_id, conv_id)
            .collection("messages")
            .order_by("created_at")
            .stream()
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
            tier=m.to_dict().get("tier"),
            attachments=m.to_dict().get("attachments"),
            steps=m.to_dict().get("steps"),
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
        reasoning_effort=data.get("reasoning_effort"),
        execution_policy=_conversation_execution_policy(data),
        execution_policy_locked=_conversation_execution_policy_locked(data),
        conversation_mode=_conversation_mode(data),
        setup_next_stage=_conversation_setup_next_stage(data),
        setup_stage_locked=_conversation_setup_stage_locked(data),
        setup_last_stage=_conversation_setup_last_stage(data),
        messages=messages,
    )


async def get_or_create_conversation(
    user_id: str,
    conv_id: str | None,
    execution_policy: ExecutionPolicy = "safe",
    conversation_mode: ConversationMode = "default",
    provider: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> Conversation:
    if conv_id:
        doc = await _pkg_store._run(lambda: _pkg_store._conv_ref(user_id, conv_id).get())
        if doc.exists:
            data = doc.to_dict()
            stored_execution_policy = _conversation_execution_policy(data)
            stored_execution_policy_locked = _conversation_execution_policy_locked(data)
            if (
                data.get("execution_policy") != stored_execution_policy
                or data.get("execution_policy_locked") is None
                or data.get("conversation_mode") != _conversation_mode(data)
                or data.get("setup_stage_locked") != _conversation_setup_stage_locked(data)
                or data.get("setup_next_stage") != _conversation_setup_next_stage(data)
                or data.get("setup_last_stage") != _conversation_setup_last_stage(data)
            ):
                await _pkg_store._run(
                    lambda: _pkg_store._conv_ref(user_id, conv_id).update(
                        {
                            "execution_policy": stored_execution_policy,
                            "execution_policy_locked": stored_execution_policy_locked,
                            "conversation_mode": _conversation_mode(data),
                            "setup_next_stage": _conversation_setup_next_stage(data),
                            "setup_stage_locked": _conversation_setup_stage_locked(data),
                            "setup_last_stage": _conversation_setup_last_stage(data),
                        }
                    )
                )
            return Conversation(
                id=conv_id,
                title=data.get("title", "New conversation"),
                message_count=data.get("message_count", 0),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
                provider=data.get("provider"),
                model=data.get("model"),
                reasoning_effort=data.get("reasoning_effort"),
                execution_policy=stored_execution_policy,
                execution_policy_locked=stored_execution_policy_locked,
                conversation_mode=_conversation_mode(data),
                setup_next_stage=_conversation_setup_next_stage(data),
                setup_stage_locked=_conversation_setup_stage_locked(data),
                setup_last_stage=_conversation_setup_last_stage(data),
            )

    new_id = str(uuid4())
    now = _pkg_store._now_iso()
    doc_data: dict = {
        "title": "New conversation",
        "message_count": 0,
        "created_at": now,
        "updated_at": now,
        "execution_policy": execution_policy,
        "execution_policy_locked": True,
        "conversation_mode": conversation_mode,
        "setup_next_stage": (
            "requirements" if conversation_mode == "automation-server-setup" else None
        ),
        "setup_stage_locked": False,
        "setup_last_stage": None,
    }
    if provider:
        doc_data["provider"] = provider
    if model:
        doc_data["model"] = model
    if reasoning_effort:
        doc_data["reasoning_effort"] = reasoning_effort

    await _pkg_store._run(lambda: _pkg_store._conv_ref(user_id, new_id).set(doc_data))
    return Conversation(
        id=new_id,
        title="New conversation",
        message_count=0,
        created_at=now,
        updated_at=now,
        provider=provider,
        model=model,
        reasoning_effort=reasoning_effort,
        execution_policy=execution_policy,
        execution_policy_locked=True,
        conversation_mode=conversation_mode,
        setup_next_stage="requirements" if conversation_mode == "automation-server-setup" else None,
        setup_stage_locked=False,
        setup_last_stage=None,
    )  # noqa: E501


async def save_setup_stage_state(
    user_id: str,
    conv_id: str,
    *,
    next_stage: SetupStageName | None,
    stage_locked: bool,
    last_stage: SetupStageName | None,
) -> None:
    await _pkg_store._run(
        lambda: _pkg_store._conv_ref(user_id, conv_id).update(
            {
                "setup_next_stage": next_stage,
                "setup_stage_locked": stage_locked,
                "setup_last_stage": last_stage,
            }
        )
    )


async def add_message(
    user_id: str,
    conv_id: str,
    role: str,
    content: str,
    provider: str | None = None,
    model: str | None = None,
    tier: str | None = None,
    attachments: list[dict] | None = None,
    steps: list[dict] | None = None,
) -> Message:
    msg_id = str(uuid4())
    now = _pkg_store._now_iso()

    data: dict = {"role": role, "content": content, "created_at": now}
    if provider:
        data["provider"] = provider
    if model:
        data["model"] = model
    if tier:
        data["tier"] = tier
    if attachments:
        data["attachments"] = attachments
    if steps:
        data["steps"] = steps

    await _pkg_store._run(lambda: _pkg_store._msg_ref(user_id, conv_id, msg_id).set(data))

    # Conversation'ı güncelle
    conv_ref = _pkg_store._conv_ref(user_id, conv_id)

    def _update():
        doc = conv_ref.get()
        data = doc.to_dict() if doc.exists else {}
        count = data.get("message_count", 0) + 1
        update = {"message_count": count, "updated_at": now}
        if role == "user" and data.get("title") == "New conversation":
            update["title"] = content[:60] + ("..." if len(content) > 60 else "")
        conv_ref.update(update)

    await _pkg_store._run(_update)
    return Message(
        id=msg_id,
        role=role,
        content=content,
        created_at=now,
        provider=provider,
        model=model,
        tier=tier,
        attachments=attachments or None,
        steps=steps,
    )


async def get_conversation_messages(user_id: str, conv_id: str) -> list[Message]:
    docs = await _pkg_store._run(
        lambda: list(
            _pkg_store._conv_ref(user_id, conv_id)
            .collection("messages")
            .order_by("created_at")
            .stream()
        )
    )
    return [
        Message(
            id=d.id,
            role=d.to_dict()["role"],
            content=d.to_dict()["content"],
            created_at=d.to_dict()["created_at"],
            provider=d.to_dict().get("provider"),
            model=d.to_dict().get("model"),
            tier=d.to_dict().get("tier"),
            attachments=d.to_dict().get("attachments"),
            steps=d.to_dict().get("steps"),
        )
        for d in docs
    ]


async def delete_conversation(user_id: str, conv_id: str) -> bool:
    doc = await _pkg_store._run(lambda: _pkg_store._conv_ref(user_id, conv_id).get())
    if not doc.exists:
        return False

    # Mesajları sil
    msg_docs = await _pkg_store._run(
        lambda: list(_pkg_store._conv_ref(user_id, conv_id).collection("messages").stream())
    )
    for m in msg_docs:
        await _pkg_store._run(
            lambda mid=m.id: (
                _pkg_store._conv_ref(user_id, conv_id).collection("messages").document(mid).delete()
            )
        )  # noqa: E501

    await _pkg_store._run(lambda: _pkg_store._conv_ref(user_id, conv_id).delete())
    return True
