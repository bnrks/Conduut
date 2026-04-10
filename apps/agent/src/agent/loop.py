"""Agentic loop — tool calling döngüsü + SSE streaming."""
import asyncio
import json
from typing import AsyncIterator

import litellm
import structlog

from src.agent.tools import TOOL_DEFINITIONS, execute_tool
from src import store

log = structlog.get_logger()

SYSTEM_PROMPT = """You are Conduut, an AI assistant that helps users build and manage n8n workflow automations.

You have access to tools to create, manage, and run n8n workflows.
When a user asks you to automate something, use the tools to build it for them immediately — do not ask for permission before acting.

Guidelines:
- Act directly. When the user asks you to do something (create, update, run a workflow), do it right away using tools. Do not ask for confirmation — just execute and then report what you did.
- CREATE vs UPDATE: Use create_workflow only for brand new workflows. If a workflow already exists (you know its ID from earlier in the conversation or from list_workflows), always use update_workflow to modify it. Never create a duplicate workflow.
- When modifying an existing workflow: first call get_workflow to fetch its current nodes and connections, merge in the changes, then call update_workflow with the complete updated structure.
- Track workflow IDs: when you create or update a workflow, remember its ID for the rest of the conversation. Use that ID when the user asks to run, update, or delete it.
- When creating workflows, produce valid n8n JSON structure with correct node types and connections.
- After acting, briefly tell the user what you did and what the workflow does.
- If the user just wants to chat or ask questions, respond normally without using tools.
"""

MAX_TOOL_ROUNDS = 5  # sonsuz döngü koruması


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def run(
    user_id: str,
    conv_id: str,
    messages: list[dict],
    settings: store.LLMSettings,
) -> AsyncIterator[str]:
    """
    Agentic loop. Tool call varsa execute edip tekrar LLM'e gönderir.
    Son text cevabı token token stream eder.
    """
    model = f"{settings.provider}/{settings.model}"
    loop_messages = list(messages)  # kopya al, orijinali bozma

    # System prompt'u başa ekle (zaten yoksa)
    if not loop_messages or loop_messages[0].get("role") != "system":
        loop_messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})

    full_content = ""

    for round_num in range(MAX_TOOL_ROUNDS):
        # Tool call round'larında streaming kapalı
        # Son cevap (text) round'unda streaming açık
        is_last_attempt = round_num == MAX_TOOL_ROUNDS - 1

        try:
            response = await litellm.acompletion(
                model=model,
                messages=loop_messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                api_key=settings.api_key,
                stream=False,
            )
        except litellm.AuthenticationError:
            yield _sse("error", {"code": "auth_error", "message": "Invalid API key. Please check your provider settings."})
            return
        except litellm.RateLimitError:
            yield _sse("error", {"code": "rate_limit", "message": "Rate limit exceeded. Please try again in a moment or switch to a different model."})
            return
        except litellm.NotFoundError:
            yield _sse("error", {"code": "model_not_found", "message": "Model not found. Please select a different model."})
            return
        except litellm.ContextWindowExceededError:
            yield _sse("error", {"code": "context_exceeded", "message": "The conversation is too long for this model. Please start a new conversation."})
            return
        except Exception as e:
            log.error("agent_loop_error", round=round_num, error=str(e))
            yield _sse("error", {"code": "unknown", "message": "Something went wrong. Please try again."})
            return

        message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason
        log.info("llm_response", round=round_num, finish_reason=finish_reason, has_tool_calls=bool(message.tool_calls), content_len=len(message.content or ""))

        # Tool call yok → son cevap, stream et
        if not message.tool_calls:
            text = message.content or ""
            log.info("streaming_text", round=round_num, text_len=len(text))

            chunk_size = 10
            for i in range(0, len(text), chunk_size):
                chunk = text[i:i + chunk_size]
                full_content += chunk
                yield _sse("token", {"text": chunk, "conversation_id": conv_id})

            log.info("tokens_yielded", chunk_count=len(text) // chunk_size + (1 if len(text) % chunk_size else 0))

            try:
                await store.add_message(
                    user_id, conv_id, "assistant", full_content,
                    provider=settings.provider, model=settings.model,
                )
            except Exception as e:
                log.error("store_add_message_error", error=str(e))

            yield _sse("done", {"conversation_id": conv_id, "provider": settings.provider, "model": settings.model})
            return

        # Tool call var → execute et
        # Önce assistant mesajını (tool_calls içeren) listeye ekle
        loop_messages.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in message.tool_calls
            ],
        })

        # Tool'ları çalıştır ve sonuçları ekle
        for tool_call in message.tool_calls:
            yield _sse("tool_call", {
                "tool": tool_call.function.name,
                "conversation_id": conv_id,
            })

            # Execute tool with keep-alive pings to prevent SSE connection timeouts
            task = asyncio.ensure_future(
                execute_tool(tool_call.function.name, tool_call.function.arguments)
            )
            while not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
            try:
                result = task.result()
            except Exception as e:
                log.error("tool_error", tool=tool_call.function.name, error=str(e))
                result = json.dumps({"error": str(e)})

            loop_messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

        if is_last_attempt:
            yield _sse("error", {"code": "max_rounds", "message": "Agent could not complete the task. Please try again."})
