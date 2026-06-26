#!/usr/bin/env python3
"""Analyze Conduut agent JSONL logs for the model bake-off (DeepSeek vs others).

Reads ``logs/agent/conduut-agent.jsonl`` (+ rotated ``*.jsonl.N``), groups events
by model (taken from the bound log context), and reports the three bake-off
concerns from knowledge-database/model-cost-research-2026-06.md:

  1. Tool-call reliability  — failed runs: malformed model responses, budget
     overruns, run errors (a high rate here is the DeepSeek #1244 risk).
  2. Build quality          — deterministic repairs (repair.py) and sandbox
     self-repair outcomes (ADR-0014: passed/failed/needs_attention/retry).
  3. Token cost             — input/output/cache tokens + estimated USD per model.

Token data only exists for runs logged AFTER the runner usage-logging change
(this branch); older runs show under "runs" but contribute no tokens/cost.

Usage:
  python scripts/analyze_bakeoff_logs.py
  python scripts/analyze_bakeoff_logs.py --since 2026-06-24T00:00:00
  python scripts/analyze_bakeoff_logs.py --model deepseek-v4-pro
  python scripts/analyze_bakeoff_logs.py --log path/to/conduut-agent.jsonl
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from collections import Counter, defaultdict

# USD per 1M tokens. Keep in sync with model-cost-research-2026-06.md.
# cache_read = cache-hit input price (DeepSeek $0.0028/M). Sonnet/Haiku/GPT rows
# are for side-by-side comparison when those models also appear in the logs.
PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {"input": 0.14, "cache_read": 0.0028, "output": 0.28},
    "deepseek-v4-pro": {"input": 0.435, "cache_read": 0.0028, "output": 0.87},
    "claude-sonnet-4-6": {"input": 3.0, "cache_read": 0.30, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 1.0, "cache_read": 0.10, "output": 5.0},
    "gpt-5-mini": {"input": 0.25, "cache_read": 0.025, "output": 2.0},
}

# A failed/incomplete run (proxy for tool-call / build reliability).
FAIL_EVENTS = {
    "agent_unexpected_model_behavior",  # invalid response / malformed tool call / retries exhausted
    "agent_usage_limit_exceeded",  # did not converge within request/tool-call budget
    "agent_run_error",  # provider/transport/other error
    "agent_model_config_error",  # bad model/key config
}


def _default_logs() -> list[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    base = os.path.join(root, "logs", "agent", "conduut-agent.jsonl")
    return [base, *sorted(glob.glob(base + ".*"))]


def _iter_lines(paths: list[str]):
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        yield json.loads(raw)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            continue


def _is_num(val: object) -> bool:
    """True for a real numeric log value (not bool, not missing/redacted str)."""
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def _num(ev: dict, key: str) -> int:
    """Read a numeric log field, treating missing/redacted/bool values as 0."""
    val = ev.get(key)
    return int(val) if _is_num(val) else 0


def _estimate_cost(model: str, tok: dict[str, int]) -> float | None:
    price = PRICING.get(model)
    if not price:
        return None
    cache_read = tok.get("cache_read", 0)
    billable_input = max(tok.get("input", 0) - cache_read, 0)
    return (
        billable_input * price["input"]
        + cache_read * price["cache_read"]
        + tok.get("output", 0) * price["output"]
    ) / 1_000_000


def _new_model_stats() -> dict:
    return {
        "runs": 0,
        "fails": 0,
        "fail_types": Counter(),
        "tool_calls": Counter(),
        "repaired_runs": 0,
        "repairs": Counter(),
        "sandbox": Counter(),
        "tokens": Counter(),
        "cost": 0.0,
        "runs_with_tokens": 0,
    }


def analyze(paths: list[str], since: str | None, only_model: str | None):
    by_model: dict[str, dict] = defaultdict(_new_model_stats)
    router_tiers: Counter = Counter()
    router_fallbacks = 0
    n8n: Counter = Counter()
    scanned = 0

    for ev in _iter_lines(paths):
        ts = ev.get("timestamp", "")
        if since and ts and ts < since:
            continue
        scanned += 1
        name = ev.get("event")
        model = ev.get("model")

        if name == "router_classified":
            router_tiers[ev.get("tier", "?")] += 1
            continue
        if name == "router_fallback":
            router_fallbacks += 1
            continue
        if isinstance(name, str) and name.startswith("n8n_workflow_"):
            n8n[name] += 1

        if model is None:
            continue
        if only_model and model != only_model:
            continue
        m = by_model[model]

        if name == "agent_run_finished":
            m["runs"] += 1
            # Token fields are tok_in/tok_out/tok_cache_read (renamed to dodge the
            # log redactor). Older runs predate usage logging or were redacted ->
            # _num returns 0 and the run is not counted as priced.
            if _is_num(ev.get("tok_in")):
                m["runs_with_tokens"] += 1
                tok = {
                    "input": _num(ev, "tok_in"),
                    "output": _num(ev, "tok_out"),
                    "cache_read": _num(ev, "tok_cache_read"),
                }
                for key, val in tok.items():
                    m["tokens"][key] += val
                cost = _estimate_cost(model, tok)
                if cost is not None:
                    m["cost"] += cost
        elif name in FAIL_EVENTS:
            m["fails"] += 1
            m["fail_types"][name] += 1
        elif name == "agent_tool_call_started":
            m["tool_calls"][ev.get("tool", "?")] += 1
        elif name == "workflow_repaired":
            m["repaired_runs"] += 1
            for item in ev.get("repairs", []) or []:
                kind = item.split("'", 1)[0].strip() if isinstance(item, str) else str(item)[:50]
                m["repairs"][kind] += 1
        elif name == "sandbox_test_finished":
            if ev.get("skipped"):
                m["sandbox"]["skipped"] += 1
            elif ev.get("passed"):
                m["sandbox"]["passed"] += 1
            else:
                m["sandbox"]["failed"] += 1
        elif name == "sandbox_test_failed_retry":
            m["sandbox"]["retry"] += 1
        elif name == "sandbox_test_needs_attention":
            m["sandbox"]["needs_attention"] += 1
        elif name == "sandbox_test_skipped_on_error":
            m["sandbox"]["error_skipped"] += 1

    return by_model, router_tiers, router_fallbacks, n8n, scanned


def _fmt_counter(counter: Counter, top: int = 6) -> str:
    if not counter:
        return "(none)"
    return ", ".join(f"{k}={v}" for k, v in counter.most_common(top))


def report(by_model, router_tiers, router_fallbacks, n8n, scanned, paths):
    print("=" * 78)
    print("CONDUUT BAKE-OFF LOG ANALYSIS")
    print(f"logs: {', '.join(p for p in paths if os.path.exists(p)) or '(none found)'}")
    print(f"lines scanned: {scanned}")
    print("=" * 78)

    print("\n## ROUTER (classifier model)")
    print(f"  tier distribution: {_fmt_counter(router_tiers)}")
    print(f"  router_fallback (classifier failed -> forced MEDIUM): {router_fallbacks}")

    if not by_model:
        print("\n(no model-scoped runs in range)")
        return

    for model in sorted(by_model):
        m = by_model[model]
        runs = m["runs"]
        fails = m["fails"]
        total = runs + fails
        rate = f"{(fails / total * 100):.1f}%" if total else "n/a"
        print("\n" + "-" * 78)
        print(f"## MODEL: {model}")
        print(f"  runs finished: {runs}   failed runs: {fails}   fail rate: {rate}")
        if m["fail_types"]:
            print(f"  fail types: {_fmt_counter(m['fail_types'])}")

        tc = m["tool_calls"]
        print(f"  tool calls: {sum(tc.values())} total  [{_fmt_counter(tc, 8)}]")

        print(
            f"  deterministic repairs: {sum(m['repairs'].values())} across "
            f"{m['repaired_runs']} runs  [{_fmt_counter(m['repairs'])}]"
        )

        sb = m["sandbox"]
        print(
            "  sandbox: "
            f"passed={sb.get('passed', 0)} failed={sb.get('failed', 0)} "
            f"needs_attention={sb.get('needs_attention', 0)} retry={sb.get('retry', 0)} "
            f"skipped={sb.get('skipped', 0)} error_skipped={sb.get('error_skipped', 0)}"
        )

        tok = m["tokens"]
        rwt = m["runs_with_tokens"]
        if rwt:
            avg_in = tok["input"] / rwt
            avg_out = tok["output"] / rwt
            priced = "" if model in PRICING else "  (no price row — cost N/A)"
            print(
                f"  tokens ({rwt} priced runs): in={tok['input']:,} out={tok['output']:,} "
                f"cache_read={tok['cache_read']:,}  | avg/run in={avg_in:,.0f} out={avg_out:,.0f}"
            )
            print(
                f"  est. cost: ${m['cost']:.4f} total   ${m['cost'] / rwt:.5f}/run{priced}"
            )
        else:
            print("  tokens: none logged (runs predate usage logging)")

    if n8n:
        print("\n" + "-" * 78)
        print(f"## n8n SIDE EFFECTS: {_fmt_counter(n8n, 10)}")

    print("\n" + "=" * 78)
    print("Concern map: fail rate + fail types -> tool-call reliability (#1);")
    print("repairs + sandbox -> build quality (#2); tokens + est. cost -> spend (#3).")
    print("=" * 78)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", action="append", help="log file(s); default: logs/agent/*.jsonl*")
    ap.add_argument("--since", help="ISO timestamp lower bound, inclusive (e.g. 2026-06-24)")
    ap.add_argument("--model", help="restrict model-scoped stats to this model id")
    args = ap.parse_args()

    paths = args.log or _default_logs()
    results = analyze(paths, args.since, args.model)
    report(*results, paths)


if __name__ == "__main__":
    main()
