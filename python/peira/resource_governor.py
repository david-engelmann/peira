"""Named resource governor (R-03): process-level rlimit backstops + death diagnostics.

R-03 adopted a cheap rlimit layer for locally-executed adapters:
``RLIMIT_CPU`` + ``RLIMIT_AS`` + ``RLIMIT_NPROC`` plus the hard-bounded
AIMD controller (:class:`peira.concurrency.AdaptiveConcurrency`). This
module is the named home for that layer. It replaces the inline
``_apply_rlimits`` helper that used to live in ``peira.runner``.

Design notes (read before changing the defaults):

- These are **backstops, not isolation**. ``resource.setrlimit`` applies
  to the whole runner process and adapter code runs in-process (see
  ``docs/Threat-Model.md``). A memory-hungry adapter can still OOM the
  runner before the limit bites; full isolation needs the subprocess
  mode designed in ``docs/Adapter-Isolation.md``.
- ``RLIMIT_NPROC`` is **child-process only**. It counts processes per
  real UID, not per process: applying it to the runner would count the
  user's shell, other lanes, and everything else on the box. It is only
  ever applied inside :meth:`ResourceGovernor.child_preexec`, which is
  meant for ``subprocess.Popen(..., preexec_fn=...)``. :meth:`apply`
  refuses to set it on the current process.
- ``RLIMIT_RSS`` is unenforced on Linux, so ``RLIMIT_AS`` (virtual
  address space) is the working memory knob.
- Fractional values round *up* to the limit's granularity (RLIMIT_CPU
  counts whole seconds); a value like 0.5 can never truncate to a zero
  limit that would kill the process.

Death diagnostics
-----------------
The 2026-09-27 Jev exploratory run died at 612/4000 calls with no error
trail and no OOM signature. The cause was never determined. To make the
next such death diagnosable, :meth:`ResourceGovernor.install_death_handlers`
installs ``SIGTERM``/``SIGINT`` handlers that append a "last words" JSON
record (signal, timestamp, pid) to a file before re-raising with default
disposition. ``SIGKILL`` cannot be caught by definition; when a run dies
with no last-words record and no traceback, check ``dmesg`` for the
OOM-killer and the parent process's logs for an external kill.
"""

from __future__ import annotations

import contextvars
import json
import math
import os
import signal
import time
from dataclasses import dataclass, field


@dataclass
class ResourceGovernor:
    """Named rlimit backstop configuration (R-03).

    All limits are opt-in (``None`` = no limit). ``cpu_seconds``,
    ``as_mb`` and ``fsize_mb`` apply to the current process via
    :meth:`apply`; ``nproc`` applies only to subprocess children via
    :meth:`child_preexec` (see the module docstring for why).
    """

    cpu_seconds: float | None = None
    as_mb: float | None = None
    nproc: int | None = None
    fsize_mb: float | None = None
    _death_handler_path: str | None = field(default=None, repr=False, init=False)

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Raise ValueError for non-positive or wrongly-typed limits."""
        for name, value in (
            ("cpu_seconds", self.cpu_seconds),
            ("as_mb", self.as_mb),
            ("nproc", self.nproc),
            ("fsize_mb", self.fsize_mb),
        ):
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be > 0, got {value}")
        if self.nproc is not None and (
            isinstance(self.nproc, bool) or not isinstance(self.nproc, int)
        ):
            raise ValueError(f"nproc must be an integer, got {self.nproc!r}")

    @property
    def configured(self) -> bool:
        """True when at least one limit is set."""
        return any(
            v is not None
            for v in (self.cpu_seconds, self.as_mb, self.nproc, self.fsize_mb)
        )

    @staticmethod
    def _require_resource():
        try:
            import resource
        except ImportError as e:
            raise RuntimeError(
                "rlimits require Unix (the resource module is unavailable)"
            ) from e
        return resource

    @staticmethod
    def _apply_limits(resource, cpu_seconds, as_mb, nproc, fsize_mb) -> None:
        """Apply the given limits via ``resource.setrlimit``.

        Shared by :meth:`apply` (current process, no nproc) and the
        :meth:`child_preexec` closure (child process, with nproc).
        Fractional values round *up* to the limit's granularity.
        """
        if cpu_seconds is not None:
            # Soft and hard set together: SIGXCPU on the soft limit,
            # SIGKILL on the hard limit one second later. RLIMIT_CPU
            # counts whole seconds, so round up: truncating 0.5 to 0
            # would SIGKILL the process immediately.
            secs = math.ceil(cpu_seconds)
            resource.setrlimit(resource.RLIMIT_CPU, (secs, secs))
        if as_mb is not None:
            # RLIMIT_AS caps virtual address space in bytes. Note
            # RLIMIT_RSS is unenforced on Linux, so AS is the working knob.
            as_bytes = math.ceil(as_mb * 1024 * 1024)
            resource.setrlimit(resource.RLIMIT_AS, (as_bytes, as_bytes))
        if nproc is not None:
            resource.setrlimit(resource.RLIMIT_NPROC, (nproc, nproc))
        if fsize_mb is not None:
            # RLIMIT_FSIZE caps any single file write in bytes
            # (EFBIG/SIGXFSZ past the limit): bounds runaway transcript
            # or cache writes.
            fsize_bytes = math.ceil(fsize_mb * 1024 * 1024)
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_bytes, fsize_bytes))

    def apply(self) -> None:
        """Apply the CPU/AS/FSIZE backstops to the current process.

        ``nproc`` is deliberately *not* applied here: it counts per UID,
        so setting it on the runner would throttle the user's whole
        session. Use :meth:`child_preexec` for subprocess children.
        """
        if not self.configured:
            return
        resource = self._require_resource()
        self._apply_limits(
            resource, self.cpu_seconds, self.as_mb, None, self.fsize_mb
        )

    def child_preexec(self):
        """Return a ``preexec_fn`` applying all limits in a child process.

        Applies CPU/AS/FSIZE plus ``nproc`` (the fork-bomb guard), which
        is safe here because the child is a fresh process whose UID
        accounting starts from the child's own subprocess tree.

        The returned closure refuses to run in the process that created
        it (checked via pid): ``RLIMIT_NPROC`` counts per UID, so
        applying it to the runner would throttle the operator's whole
        session. It must only ever run as ``preexec_fn``, after fork.

        Raises RuntimeError on non-Unix platforms (no ``resource``
        module); callers should run unconfined in that case.

        Thread-safety note: CPython documents ``preexec_fn`` as unsafe
        in multithreaded programs (fork while another thread holds a
        lock can wedge the child before exec). The runner dispatches
        adapter calls via ``asyncio.to_thread``; the guard's preexec
        body does no locking itself, but a wedged child is possible in
        principle. The subprocess ``timeout`` bounds the damage.
        """
        self._require_resource()
        parent_pid = os.getpid()
        gov = self

        def _preexec() -> None:
            if os.getpid() == parent_pid:
                raise RuntimeError(
                    "ResourceGovernor child_preexec closure must only run "
                    "as preexec_fn in a forked child, not in the parent"
                )
            import resource

            gov._apply_limits(
                resource, gov.cpu_seconds, gov.as_mb, gov.nproc, gov.fsize_mb
            )

        return _preexec

    def snapshot(self) -> dict:
        """Return the current process's rlimit values (for diagnostics).

        Keys name the rlimit; values are ``(soft, hard)`` in the
        limit's native units (seconds for CPU, bytes for AS/FSIZE,
        count for NPROC) — not the constructor's MB units.
        """
        resource = self._require_resource()
        out = {}
        for attr, name in (
            ("RLIMIT_CPU", "cpu"),
            ("RLIMIT_AS", "as_bytes"),
            ("RLIMIT_NPROC", "nproc"),
            ("RLIMIT_FSIZE", "fsize_bytes"),
        ):
            soft, hard = resource.getrlimit(getattr(resource, attr))
            out[name] = {"soft": soft, "hard": hard}
        return out

    def install_death_handlers(self, path: str | os.PathLike) -> None:
        """Install SIGTERM/SIGINT handlers that log "last words".

        On catchable termination the handler appends a JSON record
        (signal name, timestamp, pid) to ``path`` and then re-raises
        with the default disposition so the process still dies with
        the expected status. ``SIGKILL`` cannot be caught: a death
        with no last-words record and no traceback points at an
        external kill (OOM-killer, parent death, machine restart) —
        check ``dmesg`` and the parent's logs.
        """
        self._death_handler_path = os.fspath(path)

        def _handler(signum, frame):  # noqa: ANN001, ANN202
            record = {
                "event": "peira_last_words",
                "signal": signal.Signals(signum).name,
                "signum": signum,
                "pid": os.getpid(),
                "ts": time.time(),
            }
            try:
                with open(self._death_handler_path, "a",
                          encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")
            except OSError:
                pass
            # Restore default disposition and re-raise so the process
            # dies with the conventional signal status.
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)


_active_governor: contextvars.ContextVar["ResourceGovernor | None"] = (
    contextvars.ContextVar("peira_active_governor", default=None)
)


def set_active_governor(governor: "ResourceGovernor | None"):
    """Set the governor visible to subprocess adapters in this context.

    Returns the token; pass it to :func:`reset_active_governor` when
    the run ends. ``contextvars`` propagate through
    ``asyncio.to_thread``, so adapters running in worker threads see
    the governor the runner installed.
    """
    return _active_governor.set(governor)


def reset_active_governor(token) -> None:
    """Reset the active governor (pair with :func:`set_active_governor`)."""
    _active_governor.reset(token)


def get_active_governor() -> "ResourceGovernor | None":
    """Return the governor installed by the current run, if any."""
    return _active_governor.get()
