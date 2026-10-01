#!/usr/bin/env python3
"""A6 follow-up smoke: live verification for openai-moderation + anthropic.

40 calls per adapter: 20-case slice (10 score_anchoring + 10 negation_games
from dataset/v1), benign + attacked arms, sequential with a short pause.

Auth: the caller passes an hsurr:* surrogate as the adapter's api_key. The
raw provider key never enters this process; the egress layer swaps the
surrogate for the real key. The adapter's own request construction,
transport, and response parsing run verbatim -- only the credential
material is a surrogate.

Verdict bar (same as the A6 OpenRouter lane): PASS when provider/model
failures are < 3 of 40. Refusals that surface as abstain outputs count as
parsed, not failures.

Usage: python a6_oam_smoke.py --adapter omni|anthropic --surrogate 'hsurr:...'
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

sys.path.insert(0, "python")

from peira.adapters.base import CallContext, ProviderError

CASE_FILES = {
    "score_anchoring": "dataset/v1/cases/score_anchoring.jsonl",
    "negation_games": "dataset/v1/cases/negation_games.jsonl",
}
SLICE_N = 10
PAUSE_S = 0.5
FAILURE_BUDGET = 3  # < 3 failures of 40 => PASS


def load_slice(family: str, primitive: str, n: int) -> list[dict[str, Any]]:
    out = []
    with open(CASE_FILES[family], encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d["primitive"] == primitive:
                out.append(d)
                if len(out) == n:
                    break
    assert len(out) == n, f"only {len(out)} {primitive} cases in {family}"
    return out


def classify(exc: BaseException) -> str:
    if isinstance(exc, ProviderError):
        sc = exc.status_code
        if sc in (401, 403):
            return "auth"
        if sc in (400, 404, 422):
            return "terminal-shape"
        if sc is None:
            return "schema-validation"
        return f"transient-{sc}"
    return f"unexpected-{type(exc).__name__}"


def scrub(obj: Any) -> Any:
    """Drop anything that looks like a surrogate or key from the report."""
    if isinstance(obj, str):
        if "hsurr:" in obj or "sk-" in obj or "sk-ant-" in obj:
            return "<redacted>"
        return obj
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def run(adapter_name: str, surrogate: str) -> dict[str, Any]:
    if adapter_name == "omni":
        from peira.adapters.omni_moderation import OmniModerationAdapter

        adapter = OmniModerationAdapter(api_key=surrogate)
        primitive = "abstain"
    elif adapter_name == "anthropic":
        from peira.adapters.llm import AnthropicAdapter

        adapter = AnthropicAdapter(api_key=surrogate)
        primitive = "choice"
    else:
        raise ValueError(adapter_name)

    cases: list[tuple[str, str, dict[str, Any]]] = []
    for family in ("score_anchoring", "negation_games"):
        for case in load_slice(family, primitive, SLICE_N):
            for arm in ("benign", "attacked"):
                cases.append((case["case_id"], arm, case[arm]["input"]))

    calls: list[dict[str, Any]] = []
    failures = 0
    by_class: dict[str, int] = {}
    tokens_in = 0
    tokens_out = 0
    t0 = time.time()
    for i, (case_id, arm, case_input) in enumerate(cases):
        ctx = CallContext(call_id=f"a6oam-{adapter_name}-{i:03d}")
        rec: dict[str, Any] = {
            "call_id": ctx.call_id, "case_id": case_id, "arm": arm,
        }
        try:
            out = adapter.decide(case_input, primitive, ctx)
            rec["ok"] = True
            rec["decision"] = out.decision
            rec["confidence"] = out.confidence
            rec["abstained"] = bool(getattr(out, "abstained", False))
            usage = getattr(out, "usage", None)
            if usage is not None:
                rec["tokens_in"] = usage.tokens_in
                rec["tokens_out"] = usage.tokens_out
                rec["latency_ms"] = round(usage.latency_ms, 1)
                tokens_in += usage.tokens_in or 0
                tokens_out += usage.tokens_out or 0
            tr = getattr(out, "transcript", None) or {}
            # served-model evidence, nothing credential-bearing
            rec["served_model"] = tr.get("served_model") or tr.get("model")
        except Exception as exc:  # noqa: BLE001 -- classified, not hidden
            cls = classify(exc)
            rec["ok"] = False
            rec["error_class"] = cls
            rec["error"] = str(exc)[:300]
            failures += 1
            by_class[cls] = by_class.get(cls, 0) + 1
        calls.append(rec)
        print(f"[{i+1:2d}/40] {case_id} {arm:8s} "
              f"{'OK ' + str(rec.get('decision')) if rec['ok'] else 'FAIL ' + rec['error_class']}",
              flush=True)
        time.sleep(PAUSE_S)

    return {
        "adapter": adapter_name,
        "adapter_class": type(adapter).__name__,
        "adapter_name_field": adapter.name,
        "model": getattr(adapter, "_model", "omni-moderation-latest"),
        "primitive": primitive,
        "calls": len(calls),
        "parsed": sum(1 for c in calls if c["ok"]),
        "failures": failures,
        "failure_classes": by_class,
        "verdict": "PASS" if failures < FAILURE_BUDGET else "FAIL",
        "elapsed_s": round(time.time() - t0, 1),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "records": calls,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True, choices=["omni", "anthropic"])
    ap.add_argument("--surrogate", default=None)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()
    import os

    surrogate = args.surrogate or os.environ.get("PEIRA_SMOKE_SURROGATE")
    if not surrogate:
        raise SystemExit("need --surrogate or PEIRA_SMOKE_SURROGATE")
    result = run(args.adapter, surrogate)
    result = scrub(result)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    s = result
    print(f"\n{s['adapter']}: {s['parsed']}/{s['calls']} parsed, "
          f"failures={s['failures']} {s['failure_classes']}, "
          f"verdict={s['verdict']}, tokens_in={s['tokens_in']}, "
          f"tokens_out={s['tokens_out']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
