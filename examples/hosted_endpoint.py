"""Hosted-endpoint adapter pattern.

Point peira at any HTTP decision endpoint. Protect your endpoint as you
would any public API: only https URLs, no credentials in the case files,
timeouts enforced. Copy this pattern for your own hosted model.

Concurrency notes (the runner dispatches calls concurrently):

- ``decide()`` runs on worker threads — keep it thread-safe. This
  example keeps no per-call state, so it is safe as written.
- Map HTTP failures to ``ProviderError`` with the real status code so
  the runner can classify them: 408/409/429/5xx and timeouts retry
  with backoff; 400/401/403/404/422 never retry. Do NOT retry inside
  the adapter — the runner owns the retry policy (configure your HTTP
  client / SDK for 0-1 internal retries), and layered retries would
  defeat the runner's congestion control.
- To attach the raw request/response to the transcript, return them on
  the output's ``transcript`` field — e.g.
  ``ChoiceOutput(decision=..., confidence=..., transcript={"request":
  ..., "response": body})``. They ride the return value, so they are
  captured atomically with the call and never affect scoring.
"""

import json
import urllib.error
import urllib.request

from peira.adapters.base import ChoiceOutput, ProviderError

ENDPOINT = "https://your-decision-endpoint.example.com/decide"
TIMEOUT_S = 30


class HostedAdapter:
    name = "hosted-demo"
    version = "1.0.0-pinned"  # exact — never an alias
    supported_primitives = frozenset({"choice"})

    def decide(self, case_input, primitive):
        assert primitive == "choice"
        req = urllib.request.Request(
            ENDPOINT,
            data=json.dumps({"input": case_input}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            # The status code is the retry signal: the runner retries
            # 408/409/429/5xx and never retries 400/401/403/404/422.
            raise ProviderError(
                f"endpoint returned HTTP {e.code}", status_code=e.code
            ) from e
        except (urllib.error.URLError, TimeoutError) as e:
            # Connection failures and timeouts are transient.
            raise ProviderError(f"endpoint unreachable: {e}") from e
        # Your endpoint returns {"decision": ..., "confidence": ...}.
        return ChoiceOutput(
            decision=str(body["decision"]),
            confidence=float(body["confidence"]),
            # transcript={"request": {...}, "response": body},  # optional
        )


adapter = HostedAdapter()
