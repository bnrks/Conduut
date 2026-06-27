"""Assemble ordered render 'steps' from the agent SSE event stream.

A run emits visible text and tool activity across multiple model rounds. Instead
of gluing every round's text into one bubble, we split the stream into ordered
steps — one 'text' step per narration segment, one 'activity' step per burst of
tool calls — inferred from the token<->tool_call alternation. Pure/stateful; no
I/O. The frontend runs the same rule live; the backend uses it to persist.
"""

from collections.abc import Iterable


class StepAssembler:
    def __init__(self) -> None:
        self._steps: list[dict] = []

    def add(self, event: str, data: dict) -> None:
        if event == "token":
            text = str(data.get("text") or "")
            if not text:
                return
            if not self._steps or self._steps[-1]["kind"] != "text":
                self._steps.append({"kind": "text", "text": ""})
            self._steps[-1]["text"] += text
        elif event == "tool_call":
            tool = data.get("tool")
            if not isinstance(tool, str) or not tool:
                return
            if not self._steps or self._steps[-1]["kind"] != "activity":
                self._steps.append({"kind": "activity", "actions": []})
            self._steps[-1]["actions"].append(tool)
        # thinking / attachment / keep-alive / anything else: no segment effect

    def steps(self) -> list[dict]:
        return self._steps


def build_steps(events: Iterable[tuple[str, dict]]) -> list[dict]:
    assembler = StepAssembler()
    for event, data in events:
        assembler.add(event, data)
    return assembler.steps()
