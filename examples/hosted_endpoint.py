"""Hosted-endpoint adapter pattern.

Point peira at any HTTP decision endpoint. Copy this pattern for your own
hosted model.

SECURITY NOTE: This example does NOT enforce HTTPS or block internal URLs.
If you adapt this pattern, add your own SSRF protections: validate that
ENDPOINT uses https://, block private/loopback addresses, and never pass
user-controlled URLs.
"""

import json
import urllib.request

from peira.adapters.base import ChoiceOutput

ENDPOINT = "https://your-decision-endpoint.example.com/decide"
TIMEOUT_S = 30


class HostedAdapter:
    name = "hosted-demo"
    supported_primitives = frozenset({"choice"})

    def decide(self, case_input, primitive):
        assert primitive == "choice"
        req = urllib.request.Request(
            ENDPOINT,
            data=json.dumps({"input": case_input}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            body = json.loads(resp.read())
        # Your endpoint returns {"decision": ..., "confidence": ...}.
        return ChoiceOutput(
            decision=str(body["decision"]),
            confidence=float(body["confidence"]),
        )


adapter = HostedAdapter()
