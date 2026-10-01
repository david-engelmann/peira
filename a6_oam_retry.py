#!/usr/bin/env python3
"""Retry pass for failed smoke calls: replays (case_id, arm) pairs from a
report's failed records with the same adapter + surrogate, then merges."""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, "python")
sys.path.insert(0, ".")

from a6_oam_smoke import load_slice, classify, scrub  # noqa: E402
from peira.adapters.base import CallContext  # noqa: E402


def main() -> int:
    report_path = sys.argv[1]
    adapter_name = sys.argv[2]
    r = json.load(open(report_path, encoding="utf-8"))
    failed = [(c["call_id"], c["case_id"], c["arm"]) for c in r["records"]
              if not c["ok"]]
    print(f"retrying {len(failed)} failed calls")
    surrogate = os.environ.get("PEIRA_SMOKE_SURROGATE")
    assert surrogate, "need PEIRA_SMOKE_SURROGATE"

    if adapter_name == "omni":
        from peira.adapters.omni_moderation import OmniModerationAdapter

        adapter = OmniModerationAdapter(api_key=surrogate)
        primitive = "abstain"
    else:
        from peira.adapters.llm import AnthropicAdapter

        adapter = AnthropicAdapter(api_key=surrogate)
        primitive = "choice"

    # index inputs by (case_id, arm)
    inputs: dict[tuple[str, str], dict] = {}
    for family in ("score_anchoring", "negation_games"):
        for case in load_slice(family, primitive, 10):
            for arm in ("benign", "attacked"):
                inputs[(case["case_id"], arm)] = case[arm]["input"]

    new_records = []
    for call_id, case_id, arm in failed:
        ctx = CallContext(call_id=call_id)
        rec = {"call_id": call_id, "case_id": case_id, "arm": arm,
               "retry": True}
        try:
            out = adapter.decide(inputs[(case_id, arm)], primitive, ctx)
            rec["ok"] = True
            rec["decision"] = out.decision
            rec["confidence"] = out.confidence
            usage = getattr(out, "usage", None)
            if usage is not None:
                rec["tokens_in"] = usage.tokens_in
                rec["tokens_out"] = usage.tokens_out
                rec["latency_ms"] = round(usage.latency_ms, 1)
            tr = getattr(out, "transcript", None) or {}
            rec["served_model"] = tr.get("served_model") or tr.get("model")
        except Exception as exc:  # noqa: BLE001
            rec["ok"] = False
            rec["error_class"] = classify(exc)
            rec["error"] = str(exc)[:300]
        new_records.append(rec)
        print(f"{call_id} {case_id} {arm}: "
              f"{'OK ' + str(rec.get('decision')) if rec['ok'] else 'FAIL ' + rec['error_class']}",
              flush=True)
        time.sleep(0.5)

    # merge: replace failed records with retry outcomes
    by_id = {c["call_id"]: c for c in new_records}
    merged = [by_id.get(c["call_id"], c) for c in r["records"]]
    failures = sum(1 for c in merged if not c["ok"])
    by_class: dict[str, int] = {}
    for c in merged:
        if not c["ok"]:
            by_class[c["error_class"]] = by_class.get(c["error_class"], 0) + 1
    r["records"] = scrub(merged)
    r["failures"] = failures
    r["failure_classes"] = by_class
    r["verdict"] = "PASS" if failures < 3 else "FAIL"
    r["retries"] = len(new_records)
    r["tokens_in"] = sum(c.get("tokens_in", 0) for c in merged if c.get("ok"))
    r["tokens_out"] = sum(c.get("tokens_out", 0) for c in merged if c.get("ok"))
    json.dump(r, open(report_path, "w", encoding="utf-8"), indent=2)
    print(f"\nafter retry: {40 - failures}/40 parsed, failures={failures}, "
          f"verdict={r['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
