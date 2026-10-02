"""Subprocess isolation transport for third-party adapters (P-4).

The runner never imports third-party adapter code into its own
process. Instead it spawns ``python -m peira.adapters._shim
<registry id>`` and drives the adapter over a stdio JSONL protocol
(one in-flight request at a time, strict id matching). See
``docs/Plugin-Ecosystem-Design.md`` section 5.

Fail-closed rules implemented here:

- the child gets its own process group; teardown kills the group,
  so orphaned grandchildren cannot survive;
- the child environment is scrubbed (see :func:`build_child_env`);
- on Unix the child caps its own address space before importing the
  adapter (``_shim`` applies the rlimit);
- any protocol violation (unparseable frame, id mismatch, version
  mismatch, timeout) drops the child and raises;
- stderr is drained with a 1 MB cap per call and control sequences
  are stripped before anything reaches logs or errors.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import os
import re
import signal
import sys
import uuid
from dataclasses import dataclass, field

PROTOCOL_VERSION = 1
#: Keys the runner may send inside a CallContext. Anything else is
#: stripped by the child before the adapter sees it (and never sent
#: by the parent in the first place).
PINNED_CONTEXT_KEYS = frozenset({"call_id"})

#: Environment variables never inherited by adapter children. Loading
#: these from the parent environment would let the operator's shell
#: (or an attacker who reached it) inject code into the child:
#: ``LD_PRELOAD``/``DYLD_*`` load arbitrary shared objects,
#: ``PYTHONPATH``/``PYTHONHOME``/``PYTHONSTARTUP`` redirect imports.
ENV_DENYLIST = frozenset(
    {"LD_PRELOAD", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME"}
)
ENV_DENYLIST_PREFIXES = ("DYLD_",)

#: Max bytes of child stderr retained per call.
STDERR_CAP_BYTES = 1_000_000
#: Memory cap the child applies to itself (Unix only).
CHILD_MEM_LIMIT_BYTES = 8192 * 1024 * 1024

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_C0_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_control_sequences(text: str) -> str:
    """Remove ANSI escapes and C0 controls (keeps \\n, \\t)."""
    text = _ANSI_RE.sub("", text)
    return _C0_RE.sub("", text)


class AdapterSubprocessError(Exception):
    """Base for subprocess-transport failures."""


class AdapterProtocolError(AdapterSubprocessError):
    """Framing, id, or version violation: the child is dropped."""


class AdapterCallTimeout(AdapterSubprocessError):
    """A call exceeded its timeout: the child is dropped."""

    def __init__(self, op: str, timeout: float):
        super().__init__(f"adapter child timed out on {op!r} "
                         f"after {timeout:.0f}s")
        self.op = op
        self.timeout = timeout


class AdapterRemoteError(AdapterSubprocessError):
    """The adapter raised inside the child (``ok: false`` frame)."""


def build_child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build the child's environment: parent's minus the denylist.

    ``extra`` (from ``--adapter-env KEY=VALUE``) is applied on top but
    may not reintroduce a denylisted variable.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ENV_DENYLIST
        and not k.startswith(ENV_DENYLIST_PREFIXES)
    }
    for key, value in (extra or {}).items():
        if key in ENV_DENYLIST or key.startswith(ENV_DENYLIST_PREFIXES):
            raise ValueError(
                f"--adapter-env may not set denylisted variable {key!r}"
            )
        env[key] = value
    return env


def _close_transport(child: "_Child") -> None:
    """Close the asyncio subprocess transport while the loop is alive.

    ``proc.wait()`` reaps the child but does not close the transport's
    pipes; left to GC, ``__del__`` fires on a closed loop (warning) and
    the pipe fds leak until then. ``transport.close()`` is idempotent.
    """
    transport = getattr(child.proc, "_transport", None)
    close = getattr(transport, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception:  # noqa: BLE001 - best-effort cleanup
        pass


@dataclass
class _Child:
    proc: asyncio.subprocess.Process
    stderr_buf: bytearray = field(default_factory=bytearray)
    stderr_task: asyncio.Task | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    dropped: bool = False

    async def _drain_stderr(self) -> None:
        try:
            while True:
                chunk = await self.proc.stderr.read(65536)
                if not chunk:
                    break
                # Keep the tail: the exception line of a traceback is
                # at the end, which is what identifies the failure.
                self.stderr_buf = (self.stderr_buf + chunk)[-STDERR_CAP_BYTES:]
        except (asyncio.CancelledError, ValueError):
            pass
        except Exception:
            pass

    def take_stderr(self) -> str:
        raw = bytes(self.stderr_buf)
        del self.stderr_buf[:]
        return strip_control_sequences(
            raw.decode("utf-8", errors="replace"))

    def kill(self) -> None:
        """Drop the child: kill the whole process group, no grace."""
        self.dropped = True
        try:
            if sys.platform == "win32":
                self.proc.terminate()
            else:
                os.killpg(self.proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    async def drop(self) -> None:
        """Kill and reap: SIGKILL the process group, then wait so the
        asyncio transport is torn down on a live loop (no zombies, no
        late ``__del__`` on a closed loop)."""
        self.kill()
        try:
            await asyncio.wait_for(self.proc.wait(), 5.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            pass
        finally:
            _close_transport(self)
            if self.stderr_task is not None:
                self.stderr_task.cancel()

    async def terminate_gracefully(self, grace: float = 2.0) -> None:
        try:
            if sys.platform == "win32":
                self.proc.terminate()
            else:
                os.killpg(self.proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            await asyncio.wait_for(self.proc.wait(), grace)
        except (asyncio.TimeoutError, ProcessLookupError):
            self.kill()
            try:
                await asyncio.wait_for(self.proc.wait(), 5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                pass
        finally:
            _close_transport(self)


async def _spawn_child(registry_id: str,
                       env_extra: dict[str, str] | None = None) -> _Child:
    """Spawn the shim child in its own process group (list-form argv,
    never shell=True)."""
    kwargs: dict = {
        "stdin": asyncio.subprocess.PIPE,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "env": build_child_env(env_extra),
    }
    if sys.platform == "win32":
        import subprocess as _sp

        kwargs["creationflags"] = _sp.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "peira.adapters._shim", registry_id,
        **kwargs,
    )
    child = _Child(proc=proc)
    child.stderr_task = asyncio.ensure_future(child._drain_stderr())
    return child


class SubprocessAdapter:
    """A third-party adapter driven in a subprocess via the shim.

    Async-first: create with :func:`open_subprocess_adapter`, drive
    with :meth:`adecide`, close with :meth:`aclose`. The sync
    :meth:`decide` handles the no-running-loop case (spawn, one call,
    teardown); anything else must use :meth:`adecide`.
    """

    def __init__(self, registry_id: str, *, timeout: float = 300.0,
                 env_extra: dict[str, str] | None = None):
        self._registry_id = registry_id
        self._timeout = timeout
        self._env_extra = env_extra
        self._child: _Child | None = None
        # Populated by the hello handshake.
        self.name: str = registry_id
        self.version: str = ""
        self.supported_primitives: frozenset[str] = frozenset()
        self.confidence_source: str = "none"
        self.cache_namespace: str = ""
        self.attestations: dict[str, bool] = {}
        self.last_stderr: str = ""

    # -- lifecycle -------------------------------------------------

    async def _ensure_child(self) -> _Child:
        if self._child is not None and not self._child.dropped:
            if self._child.proc.returncode is not None:
                raise AdapterSubprocessError(
                    f"adapter child for {self._registry_id!r} exited "
                    f"with code {self._child.proc.returncode}")
            return self._child
        child = await _spawn_child(self._registry_id, self._env_extra)
        self._child = child
        try:
            result = await self._request(child, "hello", {}, 60.0)
        except AdapterSubprocessError:
            await child.drop()
            self._child = None
            raise
        if result.get("protocol") != PROTOCOL_VERSION:
            await child.drop()
            self._child = None
            raise AdapterProtocolError(
                f"adapter child protocol mismatch: got "
                f"{result.get('protocol')!r}, want {PROTOCOL_VERSION}")
        if result.get("name") != self._registry_id:
            # The child enforces this too (discovery.load_registered);
            # belt and suspenders on the parent side.
            await child.drop()
            self._child = None
            raise AdapterProtocolError(
                f"adapter name mismatch: registry {self._registry_id!r} "
                f"served {result.get('name')!r}")
        self.version = str(result.get("version", ""))
        self.supported_primitives = frozenset(
            result.get("supported_primitives", ()))
        self.confidence_source = str(
            result.get("confidence_source", "none"))
        attestations = result.get("attestations", {})
        if not isinstance(attestations, dict):
            await child.drop()
            self._child = None
            raise AdapterProtocolError(
                "adapter child sent a non-dict attestations payload")
        self.attestations = {
            str(k): bool(v) for k, v in attestations.items()
        }
        return child

    async def _request(self, child: _Child, op: str,
                       payload: dict, timeout: float) -> dict:
        """One framed request/response round-trip. No concurrent
        pipelining: the lock serializes callers.

        Any failure except a framed remote error drops the child: a
        half-answered or timed-out child is never reused. Cancellation
        also drops the child (shielded), so a cancelled run cannot
        orphan a process group.
        """
        async with child.lock:
            req_id = uuid.uuid4().hex
            try:
                return await self._request_inner(
                    child, op, payload, timeout, req_id)
            except AdapterRemoteError:
                # Framed ok:false: the child is healthy, the adapter
                # call itself failed. Keep the child up.
                raise
            except BaseException:
                with contextlib.suppress(Exception):
                    await asyncio.shield(child.drop())
                raise

    async def _request_inner(self, child: _Child, op: str,
                             payload: dict, timeout: float,
                             req_id: str) -> dict:
        frame = json.dumps(
            {"id": req_id, "op": op, "payload": payload},
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        try:
            child.proc.stdin.write(frame)
            await child.proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise AdapterSubprocessError(
                f"adapter child for {self._registry_id!r} died: {exc}"
            ) from exc
        try:
            line = await asyncio.wait_for(
                child.proc.stdout.readline(), timeout)
        except asyncio.TimeoutError:
            raise AdapterCallTimeout(op, timeout) from None
        if not line:
            code = child.proc.returncode
            raise AdapterSubprocessError(
                f"adapter child for {self._registry_id!r} closed "
                f"stdout (exit code {code})")
        try:
            resp = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise AdapterProtocolError(
                f"adapter child sent an unparseable frame: {exc}; "
                f"stderr tail: {child.take_stderr()[-2000:]}"
            ) from exc
        if not isinstance(resp, dict) or resp.get("id") != req_id:
            raise AdapterProtocolError(
                "adapter child id mismatch or unsolicited frame: "
                "child dropped")
        self.last_stderr = child.take_stderr()
        if not resp.get("ok"):
            raise AdapterRemoteError(
                f"adapter {self._registry_id!r} failed on {op!r}: "
                f"{resp.get('error', '(no error message)')}; "
                f"stderr tail: {self.last_stderr[-2000:]}")
        result = resp.get("result")
        if not isinstance(result, dict):
            raise AdapterProtocolError(
                "adapter child sent a non-dict result")
        return result

    # -- adapter surface -------------------------------------------

    async def adecide(self, case_input: dict, primitive: str,
                      context) -> object:
        """Drive one decision through the child (async)."""
        child = await self._ensure_child()
        payload = {
            "case_input": case_input,
            "primitive": primitive,
            # Only pinned keys cross the boundary; the child strips
            # anything else as defense in depth.
            "context": {
                k: v for k, v in _context_dict(context).items()
                if k in PINNED_CONTEXT_KEYS
            },
        }
        try:
            result = await self._request(
                child, "decide", payload, self._timeout)
        except AdapterSubprocessError:
            self._child = None
            raise
        return _decode_output(result)

    def decide(self, case_input: dict, primitive: str, context) -> object:
        """Sync wrapper: spawns a child, makes one call, tears down.

        Only valid with no running event loop and no open child; the
        async runner path must use :meth:`adecide`.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "SubprocessAdapter.decide() cannot be used inside a "
                "running event loop; use adecide()")
        if self._child is not None:
            raise RuntimeError(
                "SubprocessAdapter.decide() cannot be used after the "
                "adapter was opened; use adecide()/aclose()")

        async def _run_once():
            try:
                return await self.adecide(case_input, primitive, context)
            finally:
                await self.aclose()

        return asyncio.run(_run_once())

    def close(self) -> None:
        """Sync teardown: kill the process group (no loop needed)."""
        child, self._child = self._child, None
        if child is not None:
            if child.stderr_task is not None:
                child.stderr_task.cancel()
            child.kill()

    async def aclose(self) -> None:
        """Graceful async teardown: ask the child to close, then kill
        the process group if it lingers."""
        child, self._child = self._child, None
        if child is None:
            return
        try:
            await self._request(child, "close", {}, 10.0)
        except AdapterSubprocessError:
            pass
        finally:
            if child.stderr_task is not None:
                child.stderr_task.cancel()
            await child.terminate_gracefully()

    # -- introspection ----------------------------------------------

    @property
    def registry_id(self) -> str:
        return self._registry_id

    @property
    def transport(self) -> str:
        return "subprocess"


async def open_subprocess_adapter(
    registry_id: str,
    *,
    timeout: float = 300.0,
    env_extra: dict[str, str] | None = None,
) -> SubprocessAdapter:
    """Connect to a third-party adapter: spawn the shim child and run
    the hello handshake (protocol version + name binding)."""
    adapter = SubprocessAdapter(
        registry_id, timeout=timeout, env_extra=env_extra)
    try:
        await adapter._ensure_child()
    except AdapterSubprocessError:
        await adapter.aclose()
        raise
    return adapter


def _context_dict(context) -> dict:
    if isinstance(context, dict):
        return context
    if dataclasses.is_dataclass(context):
        return dataclasses.asdict(context)
    return {"call_id": getattr(context, "call_id", "")}


def _decode_output(result: dict) -> object:
    """Rebuild the AdapterOutput dataclass from the child's frame."""
    from peira.adapters.base import (  # noqa: PLC0415
        AbstainOutput,
        ChoiceOutput,
        ScoreOutput,
    )

    kinds = {
        "ChoiceOutput": ChoiceOutput,
        "ScoreOutput": ScoreOutput,
        "AbstainOutput": AbstainOutput,
    }
    kind = result.get("type")
    cls = kinds.get(kind)
    if cls is None:
        raise AdapterProtocolError(
            f"adapter child returned unknown output type {kind!r}")
    fields = result.get("output")
    if not isinstance(fields, dict):
        raise AdapterProtocolError(
            "adapter child returned a non-dict output payload")
    try:
        return cls(**fields)
    except TypeError as exc:
        raise AdapterProtocolError(
            f"adapter child output failed validation: {exc}") from exc
