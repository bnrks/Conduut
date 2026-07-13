import hashlib

from src.agent.reliability_guard import (
    CONDUUT_TOOL_NAMES,
    IncrementalReliabilityGuard,
    looks_like_garbage,
)


def _unique_block(length: int, seed: str = "block") -> str:
    content = ""
    index = 0
    while len(content) < length:
        content += hashlib.sha256(f"{seed}-{index}".encode()).hexdigest()
        index += 1
    return content[:length]


def test_clean_message_passes():
    assert looks_like_garbage("Workflow'unu kurdum ve çalıştırdım, sonuç hazır.") is None


def test_clean_message_mentioning_tool_in_backticks_passes():
    # A normal explanation referencing a tool name must NOT trip the detector.
    assert looks_like_garbage("`create_workflow` ile workflow'u oluşturdum.") is None


def test_tool_call_as_text_function_form_is_garbage():
    reason = looks_like_garbage("execute_workflow({'workflow_id': 'abc'})")
    assert reason is not None
    assert "execute_workflow" in reason


def test_tool_call_as_text_json_form_is_garbage():
    reason = looks_like_garbage('{"name": "create_workflow", "arguments": {}}')
    assert reason is not None
    assert "create_workflow" in reason


def test_runaway_length_is_garbage():
    assert looks_like_garbage("a" * 8001) == "runaway-length"


def test_excessive_repetition_is_garbage():
    reason = looks_like_garbage("execute now please " * 6)
    assert reason is not None


def test_tool_names_include_core_actions():
    assert {"execute_workflow", "create_workflow", "run_platform_action"} <= CONDUUT_TOOL_NAMES


def test_incremental_guard_detects_tool_name_split_across_chunks():
    guard = IncrementalReliabilityGuard()

    assert guard.feed("I will now execute_work") is None
    assert guard.feed("flow({'workflow_id': 'wf_1'})") == ("tool-call-as-text:execute_workflow")


def test_incremental_guard_detects_json_form_split_across_chunks():
    guard = IncrementalReliabilityGuard()

    assert guard.feed('{"name": "create_work') is None
    assert guard.feed('flow", "arguments": {}}') == "tool-call-as-text:create_workflow"


def test_incremental_guard_allows_backtick_tool_mention_across_chunks():
    guard = IncrementalReliabilityGuard()

    assert guard.feed("I used `create_work") is None
    assert guard.feed("flow` to build it.") is None


def test_incremental_guard_detects_repetition_without_full_content():
    guard = IncrementalReliabilityGuard()

    reason = None
    for chunk in ["execute now ", "please execute ", "now please "] * 5:
        reason = guard.feed(chunk)
        if reason:
            break

    assert reason == "repetition"
    assert len(guard.diagnostics["guard_repeat_fingerprint"]) == 12
    assert guard.diagnostics["guard_repeat_count"] == 4


def test_incremental_guard_allows_repeated_narration_across_model_responses():
    guard = IncrementalReliabilityGuard()
    narration = "Workflow'ları inceliyorum ve sonuçları özetliyorum. "

    for _ in range(6):
        assert guard.feed(narration) is None
        guard.finish_model_response()


def test_incremental_guard_allows_distant_repeated_windows_in_structured_summary():
    guard = IncrementalReliabilityGuard()
    repeated_heading = "Node türü ve durumu: "
    summary = "".join(
        f"{repeated_heading}Webhook {index}: Bu düğüm farklı bir rotanın sonucunu açıklar. "
        for index in range(6)
    )

    assert guard.feed(summary) is None


def test_incremental_guard_detects_tight_repetition_split_across_chunks():
    guard = IncrementalReliabilityGuard()
    repeated = "aynı yanıt tekrar " * 6

    reason = None
    for index in range(0, len(repeated), 7):
        reason = guard.feed(repeated[index : index + 7])
        if reason:
            break

    assert reason == "repetition"


def test_completed_guard_detects_repeated_medium_paragraphs():
    unit = "Bu benzersiz paragraf aynı sonucu yeniden açıklıyor; sıra numarası sabit kalıyor. "

    assert looks_like_garbage(unit * 5) == "repetition"


def test_incremental_guard_detects_repeated_medium_paragraphs_split_across_chunks():
    guard = IncrementalReliabilityGuard()
    unit = "Bu benzersiz paragraf aynı sonucu yeniden açıklıyor; sıra numarası sabit kalıyor. "
    repeated = unit * 5

    reason = None
    for index in range(0, len(repeated), 13):
        reason = guard.feed(repeated[index : index + 13])
        if reason:
            break

    assert reason == "repetition"
    assert guard.diagnostics["guard_repeat_window_chars"] >= 40


def test_incremental_guard_detects_repeated_long_paragraphs():
    guard = IncrementalReliabilityGuard()
    unit = (
        "Bu uzun blok her döngüde aynı araç sonucunu, aynı gerekçeyi ve aynı sonraki adımı "
        "hiçbir yeni bilgi eklemeden yeniden anlatıyor. "
    )

    assert len(unit) > 100
    assert guard.feed(unit * 5) == "repetition"
    assert guard.diagnostics["guard_repeat_window_chars"] >= 80


def test_completed_and_incremental_guards_detect_350_char_period():
    unit = _unique_block(350, "medium-period")
    repeated = unit * 4

    assert looks_like_garbage(repeated) == "repetition"

    guard = IncrementalReliabilityGuard()
    for index in range(0, len(repeated), 29):
        reason = guard.feed(repeated[index : index + 29])
        if reason:
            break

    assert reason == "repetition"
    assert guard.diagnostics["guard_repeat_period_chars"] == 350


def test_three_full_periods_and_partial_fourth_match_are_allowed():
    unit = _unique_block(350, "partial-fourth")
    different_tail = _unique_block(30, "different-tail")
    content = unit * 3 + unit[:320] + different_tail

    assert different_tail != unit[-30:]
    assert looks_like_garbage(content) is None

    guard = IncrementalReliabilityGuard()
    for index in range(0, len(content), 17):
        assert guard.feed(content[index : index + 17]) is None


def test_pending_fourth_period_resolves_only_after_final_chunk():
    unit = _unique_block(350, "pending-period")
    guard = IncrementalReliabilityGuard()

    assert guard.feed(unit * 3 + unit[:320]) is None
    assert guard.feed(unit[320:-1]) is None
    assert guard.feed(unit[-1:]) == "repetition"


def test_completed_and_incremental_guards_detect_near_max_period():
    unit = _unique_block(1800, "near-max-period")
    repeated = unit * 4

    assert len(repeated) < 8000
    assert looks_like_garbage(repeated) == "repetition"

    guard = IncrementalReliabilityGuard()
    for index in range(0, len(repeated), 211):
        reason = guard.feed(repeated[index : index + 211])
        if reason:
            break

    assert reason == "repetition"
    assert guard.diagnostics["guard_repeat_period_chars"] == 1800
    assert guard.diagnostics["guard_repeat_window_chars"] == 1280


def test_large_structured_blocks_with_varied_fields_pass():
    base = _unique_block(1800, "structured-template")
    summary = "".join(base[:900] + str(index) + base[901:] for index in range(4))

    assert len(summary) < 8000
    assert looks_like_garbage(summary) is None

    guard = IncrementalReliabilityGuard()
    for index in range(0, len(summary), 173):
        assert guard.feed(summary[index : index + 173]) is None


def test_near_limit_clean_response_passes_with_tiny_chunks():
    content = _unique_block(7999, "tiny-chunk-performance")

    one_char_guard = IncrementalReliabilityGuard()
    for char in content:
        assert one_char_guard.feed(char) is None

    four_char_guard = IncrementalReliabilityGuard()
    for index in range(0, len(content), 4):
        assert four_char_guard.feed(content[index : index + 4]) is None


def test_incremental_guard_keeps_attempt_length_across_model_response_resets():
    guard = IncrementalReliabilityGuard()
    first_response = " ".join(f"segment-{index:04d}" for index in range(400))[:4001]
    second_response = " ".join(f"result-{index:04d}" for index in range(500))[:4000]

    assert len(first_response) == 4001
    assert len(second_response) == 4000
    assert guard.feed(first_response) is None
    guard.finish_model_response()
    assert guard.feed(second_response) == "runaway-length"
