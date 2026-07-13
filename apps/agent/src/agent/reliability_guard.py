"""Incrementally detect DeepSeek #1244 failures in visible model text.

The model occasionally writes `execute_workflow {...}` into the message instead
of issuing a structured tool call (deepseek-ai/DeepSeek-V3#1244). This module
provides a pure detector the runner uses to decide whether to retry the run.
"""

import hashlib
import re
from collections.abc import Sequence

from src.agent.tool_safety import CONDUUT_TOOL_NAMES

MAX_MESSAGE_CHARS = 8000
MAX_ATTEMPTS = 3
REPEAT_WINDOWS = (20, 40, 80, 160, 320, 640, 1280)
REPEAT_COUNT = 4
REPEAT_GAP_FACTOR = 2
_ROLLING_BASE = 1_000_003
_ROLLING_MASK = (1 << 64) - 1


def _periodic_span(content: Sequence[str], start: int, period: int) -> bool:
    """Validate four complete equal periods."""

    end = start + period * REPEAT_COUNT
    if start < 0 or period <= 0 or end > len(content):
        return False
    for index in range(start + period, end):
        if content[index] != content[start + (index - start) % period]:
            return False
    return True


def looks_like_garbage(content: str, tool_names: frozenset[str] = CONDUUT_TOOL_NAMES) -> str | None:
    """Return a short reason if ``content`` looks like a #1244 failure, else None."""

    return IncrementalReliabilityGuard(tool_names).feed(content)


class IncrementalReliabilityGuard:
    """Bounded-memory detector suitable for a live stream.

    A short suffix recognizes tool signatures split across provider chunks.
    Repetition uses one rolling 64-bit hash per window scale, so each new
    character has constant work independent of prior response length. Hashes
    only nominate candidates; exact character comparison prevents collision
    false positives. Per-response state resets between model rounds, while the
    attempt-wide length limit remains cumulative.
    """

    def __init__(self, tool_names: frozenset[str] = CONDUUT_TOOL_NAMES) -> None:
        self._tool_names = tool_names
        longest_name = max((len(name) for name in tool_names), default=0)
        self._tool_lookbehind_chars = longest_name + 24
        self._tool_patterns = tuple(
            (
                name,
                re.compile(rf"\b{re.escape(name)}\s*[(\[{{]"),
                re.compile(rf'"{re.escape(name)}"\s*[:,]'),
            )
            for name in tool_names
        )
        self._tool_tail = ""
        self._total_chars = 0
        self._response_chars = 0
        self._response_content: list[str] = []
        self._rolling_hashes = dict.fromkeys(REPEAT_WINDOWS, 0)
        self._rolling_powers = {
            window_size: pow(_ROLLING_BASE, window_size, 1 << 64) for window_size in REPEAT_WINDOWS
        }
        self._window_state: dict[tuple[int, int], tuple[int, int, int]] = {}
        self._pending_candidates: dict[int, list[tuple[int, int, int, int, int]]] = {}
        self._diagnostics: dict[str, int | str] = {}
        self.reason: str | None = None

    @property
    def diagnostics(self) -> dict[str, int | str]:
        """Return content-free fields suitable for structured failure logs."""

        return {
            "guard_response_chars": self._response_chars,
            "guard_total_chars": self._total_chars,
            **self._diagnostics,
        }

    def finish_model_response(self) -> None:
        """Prevent ordinary narration across separate model rounds from accumulating."""

        if self.reason is not None:
            return
        self._tool_tail = ""
        self._response_chars = 0
        self._response_content.clear()
        self._rolling_hashes = dict.fromkeys(REPEAT_WINDOWS, 0)
        self._window_state.clear()
        self._pending_candidates.clear()

    def _accept_candidate(
        self,
        *,
        sequence_start: int,
        period: int,
        window_size: int,
        window_start: int,
        gap: int,
    ) -> bool:
        """Accept only after all four full periods are buffered and equal."""

        if not _periodic_span(self._response_content, sequence_start, period):
            return False
        window = "".join(self._response_content[window_start : window_start + window_size])
        self.reason = "repetition"
        self._diagnostics = {
            "guard_repeat_fingerprint": hashlib.sha256(window.encode("utf-8")).hexdigest()[:12],
            "guard_repeat_window_chars": window_size,
            "guard_repeat_period_chars": period,
            "guard_repeat_count": REPEAT_COUNT,
            "guard_repeat_gap_chars": gap,
        }
        return True

    def _schedule_candidate(
        self,
        *,
        sequence_start: int,
        period: int,
        window_size: int,
        window_start: int,
        gap: int,
    ) -> bool:
        required_end = sequence_start + period * REPEAT_COUNT
        candidate = (sequence_start, period, window_size, window_start, gap)
        if required_end <= len(self._response_content):
            return self._accept_candidate(
                sequence_start=sequence_start,
                period=period,
                window_size=window_size,
                window_start=window_start,
                gap=gap,
            )
        self._pending_candidates.setdefault(required_end, []).append(candidate)
        return False

    def _resolve_pending_candidates(self) -> bool:
        candidates = self._pending_candidates.pop(len(self._response_content), ())
        for sequence_start, period, window_size, window_start, gap in candidates:
            if self._accept_candidate(
                sequence_start=sequence_start,
                period=period,
                window_size=window_size,
                window_start=window_start,
                gap=gap,
            ):
                return True
        return False

    def feed(self, chunk: str) -> str | None:
        if self.reason is not None or not chunk:
            return self.reason

        self._total_chars += len(chunk)
        self._response_chars += len(chunk)
        if self._total_chars > MAX_MESSAGE_CHARS:
            self.reason = "runaway-length"
            return self.reason

        tool_scan = self._tool_tail + chunk
        for name, function_pattern, json_pattern in self._tool_patterns:
            if function_pattern.search(tool_scan) or json_pattern.search(tool_scan):
                self.reason = f"tool-call-as-text:{name}"
                return self.reason
        self._tool_tail = tool_scan[-self._tool_lookbehind_chars :]

        for char in chunk:
            position = len(self._response_content)
            self._response_content.append(char)
            if self._resolve_pending_candidates():
                return self.reason
            char_code = ord(char) + 1
            for window_size in REPEAT_WINDOWS:
                rolling_hash = (
                    self._rolling_hashes[window_size] * _ROLLING_BASE + char_code
                ) & _ROLLING_MASK
                if position >= window_size:
                    old_code = ord(self._response_content[position - window_size]) + 1
                    rolling_hash = (
                        rolling_hash - old_code * self._rolling_powers[window_size]
                    ) & _ROLLING_MASK
                self._rolling_hashes[window_size] = rolling_hash
                if position + 1 < window_size:
                    continue

                window_start = position - window_size + 1
                key = (window_size, rolling_hash)
                previous = self._window_state.get(key)
                gap = window_start - previous[0] if previous else 0
                if previous and gap <= window_size * REPEAT_GAP_FACTOR:
                    if previous[1] == 1:
                        count, period = 2, gap
                    elif gap == previous[2]:
                        count, period = previous[1] + 1, previous[2]
                    else:
                        count, period = 1, 0
                else:
                    count, period = 1, 0
                if count >= REPEAT_COUNT:
                    sequence_start = window_start - period * (REPEAT_COUNT - 1)
                    if self._schedule_candidate(
                        sequence_start=sequence_start,
                        period=period,
                        window_size=window_size,
                        window_start=window_start,
                        gap=gap,
                    ):
                        return self.reason
                self._window_state[key] = (window_start, count, period)

        return None
