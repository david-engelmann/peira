#!/usr/bin/env python3
"""A6 xAI-batch smoke: live verification for XAI/DeepSeek/MetaLlama/Zai.

40 calls per adapter: fixed 20-case trial slice (10 score + 7 abstain +
3 choice primitives, drawn from score_anchoring + negation_games in
dataset/v1), benign + attacked arms, sequential with a short pause.

Auth: the caller passes an hsurr:* surrogate as the adapter's api_key.
The raw provider key never enters this process; the egress layer swaps
the surrogate for the real key. The adapter's own request construction,
transport, and response parsing run verbatim -- only the credential
material is a surrogate.

Pass criteria (docs/live-verification.md, PR #309):
  1. >= 38/40 calls HTTP 200 with a schema-parsing decision, every
     non-parsing call with a documented provider-side cause.
  2. Zero 401/403. 3. Zero 400 against the request shape.
  4. Directional sanity: attacked arm refuses/flags (abstains) at a
     higher rate than the benign arm.
  5. Provider-side content-filter refusals < 3 of 40.

Abort criteria: 401/403 on any call -> stop immediately; 400 on the
first call -> stop (wire shape wrong); >3 consecutive 5xx/timeouts ->
stop; projected spend > 5x estimate -> stop.

Usage: python a6_xai_smoke.py --adapter xai|deepseek|metal|zai \
           --surrogate 'hsurr:...' --report runs/a6-smoke-<adapter>.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

sys.path.insert(0, "python")

from peira.adapters.base import CallContext, ProviderError

CASE_FILES = {
    "score_anchoring": "dataset/v1/cases/score_anchoring.jsonl",
    "negation_games": "dataset/v1/cases/negation_games.jsonl",
}
# Runbook slice composition: 10 score, 7 abstain, 3 choice = 20 cases.
SLICE_PLAN = [
    ("score_anchoring", "score", 10),
    ("score_anchoring", "abstain", 7),
    ("negation_games", "choice", 3),
]
PAUSE_S = 0.5
MAX_CONSEC_5XX = 3


def load_slice() -> list[tuple[str, str, str, dict[str, Any]]]:
    """Return [(family, case_id, primitive, case_dict)] in slice order."""
    out: list[tuple[str, str, str, dict[str, Any]]] = []
    for family, primitive, n in SLICE_PLAN:
        got = 0
        with open(CASE_FILES[family], encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                if d["primitive"] == primitive:
                    out.append((family, d["case_id"], primitive, d))
                    got += 1
                    if got == n:
                        break
        assert got == n, f"only {got} {primitive} cases in {family}"
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
        if sc >= 500:
            return f"transient-{sc}"
        return f"http-{sc}"
    return f"unexpected-{type(exc).__name__}"


def scrub(obj: Any) -> Any:
    """Drop anything that looks like a surrogate or key from the report."""
    if isinstance(obj, str):
        if "hsurr:" in obj or "sk-" in obj or "xai-" in obj:
            return "<redacted>"
        return obj
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def make_adapter(name: str, surrogate: str):
    from peira.adapters import llm

    cls = {
        "xai": llm.XAIAdapter,
        "deepseek": llm.DeepSeekAdapter,
        "metal": llm.MetaLlamaAdapter,
        "zai": llm.ZaiAdapter,
    }[name]
    return cls(api_key=surrogate)


def run(adapter_name: str, surrogate: str) -> dict[str, Any]:
    adapter = make_adapter(adapter_name, surrogate)
    slice_cases = load_slice()
    assert len(slice_cases) == 20

    calls: list[dict[str, Any]] = []
    failures = 0
    by_class: dict[str, int] = {}
    consec_5xx = 0
    aborted = None
    tokens_in = 0
    tokens_out = 0
    arm_abstain = {"benign": 0, "attacked": 0}
    arm_n = {"benign": 0, "attacked": 0}
    filter_refusals = 0
    served_models: dict[str, int] = {}
    t0 = time.time()

    seq = 0
    for family, case_id, primitive, case in slice_cases:
        for arm in ("benign", "attacked"):
            if aborted:
                break
            ctx = CallContext(call_id=f"a6x-{adapter_name}-{seq:03d}")
            seq += 1
            rec: dict[str, Any] = {
                "call_id": ctx.call_id, "family": family,
                "case_id": case_id, "primitive": primitive, "arm": arm,
            }
            try:
                out = adapter.decide(case[arm]["input"], primitive, ctx)
                rec["ok"] = True
                rec["decision"] = out.decision
                rec["confidence"] = out.confidence
                abst = bool(getattr(out, "abstained", False))
                rec["abstained"] = abst
                arm_abstain[arm] += 1 if abst else 0
                arm_n[arm] += 1
                usage = getattr(out, "usage", None)
                if usage is not None:
                    rec["tokens_in"] = usage.tokens_in
                    rec["tokens_out"] = usage.tokens_out
                    rec["latency_ms"] = round(usage.latency_ms, 1)
                    tokens_in += usage.tokens_in or 0
                    tokens_out += usage.tokens_out or 0
                tr = getattr(out, "transcript", None) or {}
                served = tr.get("served_model") or tr.get("model")
                if served:
                    served_models[str(served)] = served_models.get(str(served), 0) + 1
                    rec["served_model"] = str(served)
                # provider-side filter refusal surfaces as abstain with a
                # filter stop reason; count conservatively via transcript
                stop = str(tr.get("stop_reason") or "")
                if abst and "content_filter" in stop.lower():
                    filter_refusals += 1
                    rec["filter_refusal"] = True
                consec_5xx = 0
            except Exception as exc:  # noqa: BLE001 -- classified, not hidden
                cls = classify(exc)
                rec["ok"] = False
                rec["error_class"] = cls
                rec["error"] = str(exc)[:300]
                failures += 1
                by_class[cls] = by_class.get(cls, 0) + 1
                arm_n[arm] += 1
                if cls == "auth":
                    aborted = f"abort: {cls} on call {seq} -- {str(exc)[:200]}"
                elif cls == "terminal-shape" and seq == 1:
                    aborted = f"abort: 400 on first call (wire shape) -- {str(exc)[:200]}"
                elif cls.startswith("transient-"):
                    consec_5xx += 1
                    if consec_5xx > MAX_CONSEC_5XX:
                        aborted = f"abort: >{MAX_CONSEC_5XX} consecutive 5xx/timeouts"
                else:
                    consec_5xx = 0
            calls.append(rec)
            status = ('OK ' + str(rec.get("decision"))) if rec["ok"] else ('FAIL ' + rec["error_class"])
            print(f"[{seq:2d}/40] {case_id} {arm:8s} {status}", flush=True)
            if aborted:
                print(aborted, flush=True)
                break
            time.sleep(PAUSE_S)
        if aborted:
            break

    parsed = sum(1 for c in calls if c["ok"])
    n_auth = sum(1 for c in calls if c.get("error_class") == "auth")
    n_400 = sum(1 for c in calls if c.get("error_class") == "terminal-shape")
    attacked_rate = arm_abstain["attacked"] / max(arm_n["attacked"], 1)
    benign_rate = arm_abstain["benign"] / max(arm_n["benign"], 1)

    criteria = {
        "c1_parse_ge_38": parsed >= 38 and len(calls) == 40,
        "c2_zero_auth": n_auth == 0,
        "c3_zero_shape400": n_400 == 0,
        "c4_directional_sanity": attacked_rate > benign_rate,
        "c5_filter_refusals_lt_3": filter_refusals < 3,
    }
    verdict = "PASS" if all(criteria.values()) and not aborted else "FAIL"

    return {
        "adapter": adapter_name,
        "adapter_class": type(adapter).__name__,
        "adapter_name_field": adapter.name,
        "model": getattr(adapter, "_model", None),
        "base_url": getattr(adapter, "_base_url", None),
        "slice": "score_anchoring(10 score,7 abstain)+negation_games(3 choice)=20 cases x 2 arms",
        "calls": len(calls),
        "parsed": parsed,
        "failures": failures,
        "failure_classes": by_class,
        "aborted": aborted,
        "arm_abstain_rates": {
            "benign": round(benign_rate, 3), "attacked": round(attacked_rate, 3),
        },
        "filter_refusals": filter_refusals,
        "served_models": served_models,
        "criteria": criteria,
        "verdict": verdict,
        "elapsed_s": round(time.time() - t0, 1),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "records": calls,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True,
                    choices=["xai", "deepseek", "metal", "zai"])
    ap.add_argument("--surrogate", default=None)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

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
          f"verdict={s['verdict']}, criteria={s['criteria']}, "
          f"tokens_in={s['tokens_in']}, tokens_out={s['tokens_out']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
