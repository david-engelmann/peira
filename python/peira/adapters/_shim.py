"""Subprocess child for third-party adapters (P-4).

Invoked as ``python -m peira.adapters._shim <registry id>`` by the
parent (see ``peira.adapters.subprocess``); never run by hand. The
child imports the adapter, then serves a stdio JSONL protocol:

- parent -> child: ``{"id", "op", "payload"}`` with ``op`` in
  ``hello`` | ``decide`` | ``close``;
- child -> parent: ``{"id", "ok": true, "result": {...}}`` or
  ``{"id", "ok": false, "error": "..."}``.

This module is internal: the serve loop is private and nothing here
is importable surface for adapter authors.

Safety notes:

- the memory cap is applied to the child itself BEFORE the adapter
  module is imported (Unix only);
- the adapter is loaded through ``discovery.load_registered``, so
  the name-vs-attribute binding is enforced before serving;
- the context is stripped to the pinned key set before the adapter
  sees it (defense in depth; the parent already only sends those);
- stdout is the protocol channel: it is write-protected at startup
  (see ``_protect_protocol_channel``) so adapter ``print`` calls land
  in the drained/capped stderr stream instead of corrupting framing.
  An adapter that bypasses this and writes raw bytes to file
  descriptor 1 corrupts the channel anyway; the parent drops the
  child on any unparseable frame (fail-closed).
"""

from __future__ import annotations

import dataclasses
import io
import json
import sys

# Binary handle to the protocol pipe, saved before sys.stdout is
# moved (see _protect_protocol_channel). _write uses this, never
# sys.stdout.buffer, so adapter-level stdout redirection cannot
# divert or corrupt protocol frames.
_PROTO_OUT: io.BufferedWriter | None = None


def _protect_protocol_channel() -> None:
    """Write-protect the protocol channel.

    Rebinds the text-mode ``sys.stdout`` onto the stderr pipe (line
    buffered) so adapter ``print`` calls land in the parent's
    drained, capped, control-sequence-stripped stderr stream. The
    binary protocol writer keeps the saved pipe handle.
    """
    global _PROTO_OUT
    _PROTO_OUT = sys.stdout.buffer
    sys.stdout = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", line_buffering=True)


def _apply_child_limits() -> None:
    """Cap this process's address space (Unix only), before the
    adapter module is imported."""
    if sys.platform == "win32":
        return
    import resource  # noqa: PLC0415

    from peira.adapters.subprocess import (  # noqa: PLC0415
        CHILD_MEM_LIMIT_BYTES,
    )

    resource.setrlimit(
        resource.RLIMIT_AS,
        (CHILD_MEM_LIMIT_BYTES, CHILD_MEM_LIMIT_BYTES),
    )


def _load_adapter(registry_id: str):
    from peira.adapters import discovery  # noqa: PLC0415

    resolved = discovery.resolve_spec(registry_id)
    if resolved.kind != "registry":
        raise SystemExit(
            f"error: the shim only serves registry ids, got "
            f"{registry_id!r} (kind {resolved.kind})"
        )
    return discovery.load_registered(resolved.registration)


def _module_provenance(adapter) -> dict:
    """SHA-256 + path of the loaded adapter module file.

    Computed here (in the child) because the parent must never
    import the module to locate it. Failures degrade to empty
    strings rather than failing the handshake: provenance gaps are
    reported by the conformance kit, not hidden.
    """
    import hashlib  # noqa: PLC0415
    import inspect  # noqa: PLC0415

    path = ""
    digest = ""
    try:
        path = inspect.getfile(type(adapter))
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
    except (OSError, TypeError):
        pass
    return {"path": path, "sha256": digest}


def _sampling_posture(adapter):
    posture = getattr(adapter, "sampling_posture", None)
    return posture if posture in ("deterministic", "sampling") else None


def _read_attestations(adapter) -> dict[str, bool]:
    raw = getattr(adapter, "conformance_attestations", None)
    if not isinstance(raw, dict):
        return {}
    return {str(k): bool(v) for k, v in raw.items()}


def _write(frame: dict) -> None:
    data = json.dumps(frame, separators=(",", ":")).encode("utf-8")
    try:
        assert _PROTO_OUT is not None
        _PROTO_OUT.write(data + b"\n")
        _PROTO_OUT.flush()
    except (BrokenPipeError, ValueError, AssertionError):
        # Parent is gone (or startup failed); nothing left to serve.
        raise SystemExit(0)


def _error(req_id, message: str) -> None:
    from peira.adapters.subprocess import (  # noqa: PLC0415
        strip_control_sequences,
    )

    _write({"id": req_id, "ok": False,
            "error": strip_control_sequences(str(message))})


def _serve(adapter, attestations: dict[str, bool]) -> int:
    from peira.adapters.base import CallContext  # noqa: PLC0415
    from peira.adapters.subprocess import (  # noqa: PLC0415
        PINNED_CONTEXT_KEYS,
        PROTOCOL_VERSION,
    )

    stdin = sys.stdin.buffer
    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            _error(None, "unparseable frame")
            continue
        if not isinstance(msg, dict):
            _error(None, "frame must be a JSON object")
            continue
        req_id = msg.get("id")
        op = msg.get("op")
        payload = msg.get("payload", {})
        if not isinstance(req_id, str) or not isinstance(op, str) \
                or not isinstance(payload, dict):
            _error(req_id if isinstance(req_id, str) else None,
                    "frame needs string id, string op, dict payload")
            continue
        try:
            if op == "hello":
                _write({
                    "id": req_id, "ok": True, "result": {
                        "protocol": PROTOCOL_VERSION,
                        "name": adapter.name,
                        "version": adapter.version,
                        "supported_primitives": sorted(
                            adapter.supported_primitives),
                        "confidence_source": getattr(
                            adapter, "confidence_source", "none"),
                        "attestations": attestations,
                        # Declared sampling posture for the
                        # conformance kit's determinism suite
                        # (design 6.1.3).
                        "sampling_posture": _sampling_posture(adapter),
                        # Provenance for the check report (F7): the
                        # SHA-256 of the loaded module file, so
                        # `peira adapter check --verify` can confirm
                        # the sealed report still matches disk.
                        "module": _module_provenance(adapter),
                    },
                })
            elif op == "decide":
                _handle_decide(req_id, payload, adapter, CallContext,
                               PINNED_CONTEXT_KEYS)
            elif op == "close":
                close = getattr(adapter, "close", None)
                if callable(close):
                    close()
                _write({"id": req_id, "ok": True, "result": {}})
                return 0
            else:
                _error(req_id, f"unknown op {op!r}")
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001 - framed to the parent
            _error(req_id, f"{type(exc).__name__}: {exc}")
    return 0


def _handle_decide(req_id, payload, adapter, CallContext,
                   pinned_keys) -> None:
    case_input = payload.get("case_input")
    primitive = payload.get("primitive")
    context = payload.get("context")
    if not isinstance(case_input, dict):
        _error(req_id, "decide payload needs a dict case_input")
        return
    if not isinstance(primitive, str):
        _error(req_id, "decide payload needs a string primitive")
        return
    if not isinstance(context, dict) or \
            not isinstance(context.get("call_id"), str):
        _error(req_id,
               "decide payload needs a context dict with a call_id")
        return
    # Strip to the pinned key set before the adapter sees it.
    ctx = CallContext(
        **{k: v for k, v in context.items() if k in pinned_keys})
    try:
        output = adapter.decide(case_input, primitive, ctx)
    except Exception as exc:  # noqa: BLE001 - framed to the parent
        _error(req_id, f"{type(exc).__name__}: {exc}")
        return
    from peira.adapters.base import (  # noqa: PLC0415
        AbstainOutput,
        ChoiceOutput,
        ScoreOutput,
    )

    if not isinstance(output, (ChoiceOutput, ScoreOutput, AbstainOutput)):
        _error(req_id,
               f"adapter returned {type(output).__name__}, not an "
               f"AdapterOutput")
        return
    _write({
        "id": req_id, "ok": True, "result": {
            "type": type(output).__name__,
            "output": dataclasses.asdict(output),
        },
    })


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {sys.executable} -m peira.adapters._shim "
              f"<registry id>", file=sys.stderr)
        return 2
    registry_id = argv[1]
    _apply_child_limits()
    # Protect the protocol channel before the adapter module is
    # imported: import-time print() calls must not corrupt framing.
    _protect_protocol_channel()
    try:
        adapter = _load_adapter(registry_id)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - child startup failure
        print(f"error: could not load adapter {registry_id!r}: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    attestations = _read_attestations(adapter)
    return _serve(adapter, attestations)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
