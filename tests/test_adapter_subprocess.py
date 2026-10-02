"""Tests for peira.adapters.subprocess + peira.adapters._shim (P-4).

The end-to-end tests install a tiny fake third-party distribution
(``peira-testplugin``) into the test venv's site-packages: a real
``.dist-info`` with real ``peira.adapters`` entry points, so the shim
child loads it through the genuine ``discovery.load_registered``
path. Everything is removed in tearDown.
"""

import asyncio
import contextlib
import io
import json
import os
import shutil
import sys
import sysconfig
import tempfile
import time
import unittest
import unittest.mock

from peira.adapters import subprocess as sp
from peira.adapters.subprocess import (
    AdapterCallTimeout,
    AdapterProtocolError,
    AdapterRemoteError,
    AdapterSubprocessError,
    SubprocessAdapter,
    build_child_env,
    open_subprocess_adapter,
    strip_control_sequences,
)

PLUGIN_PKG = "peira_testplugin"
PLUGIN_DIST = "peira_testplugin-0.1.dist-info"

PLUGIN_INIT = '''
import os
import time

from peira.adapters.base import CallContext, ChoiceOutput


class _Base:
    version = "0.1-test"
    supported_primitives = frozenset({"choice"})
    confidence_source = "none"
    cache_namespace = ""
    conformance_attestations = {
        "max_retries_0": True,
        "no_network_during_decide": True,
        "no_extra_metadata": True,
    }

    def close(self):
        pass


class GoodAdapter(_Base):
    name = "testplugin-good"

    def decide(self, case_input, primitive, context):
        keys = (sorted(vars(context).keys())
                if hasattr(context, "__dict__")
                else sorted(context.keys()))
        get = (lambda k: getattr(context, k, None))
        return ChoiceOutput(
            decision="approve",
            transcript={
                "seen_env": {
                    k: os.environ.get(k) for k in (
                        "PEIRA_TESTPLUGIN_SECRET",
                        "PEIRA_TESTPLUGIN_EXTRA",
                        "LD_PRELOAD",
                        "PYTHONPATH",
                    )
                },
                "context_keys": keys,
                "call_id": get("call_id"),
            },
        )


class PrinterAdapter(_Base):
    name = "testplugin-printer"

    def decide(self, case_input, primitive, context):
        print("THIS IS NOT JSON {{{ garbage")
        return ChoiceOutput(decision="approve")


class SleeperAdapter(_Base):
    name = "testplugin-sleeper"

    def decide(self, case_input, primitive, context):
        time.sleep(30)
        return ChoiceOutput(decision="approve")


class ExplodingAdapter(_Base):
    name = "testplugin-exploding"

    def decide(self, case_input, primitive, context):
        raise RuntimeError("boom-from-adapter")


class FdHackerAdapter(_Base):
    name = "testplugin-fdhacker"

    def decide(self, case_input, primitive, context):
        # Bypass the print() redirect: raw bytes straight at fd 1.
        os.write(1, b"NOT JSON {{{\\n")
        return ChoiceOutput(decision="approve")
'''

ENTRY_POINTS_TXT = """\
[peira.adapters]
testplugin-good = peira_testplugin:GoodAdapter
testplugin-printer = peira_testplugin:PrinterAdapter
testplugin-sleeper = peira_testplugin:SleeperAdapter
testplugin-exploding = peira_testplugin:ExplodingAdapter
testplugin-fdhacker = peira_testplugin:FdHackerAdapter
"""

METADATA_TXT = """\
Metadata-Version: 2.1
Name: peira-testplugin
Version: 0.1
"""


def site_packages() -> str:
    return sysconfig.get_paths()["purelib"]


@contextlib.contextmanager
def _install_lock():
    """Serialize the fake-plugin install across xdist workers.

    Workers share the machine's site-packages: one worker's
    rmtree/reinstall racing another worker's running child (which
    imports the plugin) corrupts the install. The lock is a
    directory (atomic mkdir, cross-platform); a holder that died
    mid-install is detected via mtime staleness.
    """
    lock_dir = os.path.join(tempfile.gettempdir(),
                            "peira-testplugin-install.lock")
    deadline = time.time() + 120
    while True:
        try:
            os.mkdir(lock_dir)
            break
        except FileExistsError:
            try:
                age = time.time() - os.stat(lock_dir).st_mtime
            except OSError:
                age = 0
            if age > 60:
                shutil.rmtree(lock_dir, ignore_errors=True)
                continue
            if time.time() > deadline:
                raise RuntimeError(
                    "timed out waiting for the test-plugin install lock")
            time.sleep(0.2)
    try:
        yield
    finally:
        shutil.rmtree(lock_dir, ignore_errors=True)


class PluginInstallMixin:
    @classmethod
    def setUpClass(cls):
        sp_dir = site_packages()
        cls._pkg_dir = os.path.join(sp_dir, PLUGIN_PKG)
        cls._dist_dir = os.path.join(sp_dir, PLUGIN_DIST)
        # Under xdist the dist-info is left in place (removing it
        # races other workers' running tests); without xdist the
        # class cleans up after itself.
        cls._leave_installed = "PYTEST_XDIST_WORKER" in os.environ
        with _install_lock():
            # Clean stale remains of a crashed run first.
            for path in (cls._pkg_dir, cls._dist_dir):
                shutil.rmtree(path, ignore_errors=True)
            os.makedirs(cls._pkg_dir)
            with open(os.path.join(cls._pkg_dir, "__init__.py"), "w",
                      encoding="utf-8") as f:
                f.write(PLUGIN_INIT)
            os.makedirs(cls._dist_dir)
            with open(os.path.join(cls._dist_dir, "METADATA"), "w",
                      encoding="utf-8") as f:
                f.write(METADATA_TXT)
            with open(os.path.join(cls._dist_dir, "entry_points.txt"), "w",
                      encoding="utf-8") as f:
                f.write(ENTRY_POINTS_TXT)
        # importlib.metadata scans sys.path per call; no cache to bust,
        # but drop any already-imported plugin module.
        sys.modules.pop(PLUGIN_PKG, None)

    @classmethod
    def tearDownClass(cls):
        for mod in [m for m in sys.modules if m.startswith(PLUGIN_PKG)]:
            del sys.modules[mod]
        if not cls._leave_installed:
            for path in (cls._pkg_dir, cls._dist_dir):
                shutil.rmtree(path, ignore_errors=True)


class EnvScrubbingTest(unittest.TestCase):
    def test_denylist_is_scrubbed(self):
        with unittest.mock.patch.dict(os.environ, {
            "LD_PRELOAD": "/tmp/evil.so",
            "PYTHONPATH": "/tmp/evil",
            "PYTHONSTARTUP": "/tmp/evil.py",
            "PYTHONHOME": "/tmp/evilhome",
            "DYLD_INSERT_LIBRARIES": "/tmp/evil.dylib",
            "PEIRA_KEEP_ME": "yes",
        }):
            env = build_child_env()
        for var in ("LD_PRELOAD", "PYTHONPATH", "PYTHONSTARTUP",
                    "PYTHONHOME", "DYLD_INSERT_LIBRARIES"):
            self.assertNotIn(var, env)
        self.assertEqual(env["PEIRA_KEEP_ME"], "yes")

    def test_extra_env_passes_through(self):
        env = build_child_env({"PEIRA_TESTPLUGIN_EXTRA": "1"})
        self.assertEqual(env["PEIRA_TESTPLUGIN_EXTRA"], "1")

    def test_extra_env_cannot_set_denylisted(self):
        with self.assertRaises(ValueError):
            build_child_env({"LD_PRELOAD": "/tmp/evil.so"})
        with self.assertRaises(ValueError):
            build_child_env({"DYLD_FOO": "x"})


class StripControlSequencesTest(unittest.TestCase):
    def test_ansi_and_c0_stripped(self):
        dirty = "\x1b[31mred\x1b[0m\x07bell\x00null\nkept\n"
        clean = strip_control_sequences(dirty)
        self.assertEqual(clean, "redbellnull\nkept\n")
        self.assertNotIn("\x1b", clean)


class ShimEndToEndTest(PluginInstallMixin, unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_hello_decide_close_round_trip(self):
        async def go():
            adapter = await open_subprocess_adapter("testplugin-good")
            try:
                self.assertEqual(adapter.name, "testplugin-good")
                self.assertEqual(adapter.version, "0.1-test")
                self.assertEqual(adapter.supported_primitives,
                                 frozenset({"choice"}))
                self.assertEqual(
                    adapter.attestations["max_retries_0"], True)
                from peira.adapters.base import CallContext, ChoiceOutput
                out = await adapter.adecide(
                    {"text": "hello", "options": ["approve", "deny"]},
                    "choice",
                    CallContext(call_id="call-1"),
                )
                self.assertIsInstance(out, ChoiceOutput)
                self.assertEqual(out.decision, "approve")
                return out.transcript
            finally:
                await adapter.aclose()

        transcript = self._run(go())
        # The child saw exactly the pinned context keys.
        self.assertEqual(transcript["context_keys"], ["call_id"])
        self.assertEqual(transcript["call_id"], "call-1")

    def test_env_scrubbing_end_to_end(self):
        async def go():
            with unittest.mock.patch.dict(os.environ, {
                "PEIRA_TESTPLUGIN_SECRET": "s3cr3t",
                "PEIRA_TESTPLUGIN_EXTRA": "nope",
                "LD_PRELOAD": "/tmp/evil.so",
            }):
                adapter = await open_subprocess_adapter(
                    "testplugin-good",
                    env_extra={"PEIRA_TESTPLUGIN_EXTRA": "yes"})
                try:
                    from peira.adapters.base import CallContext
                    out = await adapter.adecide(
                        {"text": "x", "options": ["approve", "deny"]},
                        "choice", CallContext(call_id="c"))
                    return out.transcript["seen_env"]
                finally:
                    await adapter.aclose()

        seen = self._run(go())
        self.assertEqual(seen["PEIRA_TESTPLUGIN_SECRET"], "s3cr3t")
        self.assertEqual(seen["PEIRA_TESTPLUGIN_EXTRA"], "yes")
        self.assertIsNone(seen["LD_PRELOAD"])
        self.assertIsNone(seen["PYTHONPATH"])

    def test_unknown_registry_id_fails(self):
        async def go():
            with self.assertRaises(AdapterSubprocessError):
                await open_subprocess_adapter("no-such-plugin-xyz")
        self._run(go())

    def test_adapter_print_goes_to_stderr_not_protocol(self):
        # print() is redirected onto the drained stderr stream: the
        # call succeeds and the output shows up in last_stderr.
        async def go():
            adapter = await open_subprocess_adapter("testplugin-printer")
            from peira.adapters.base import CallContext, ChoiceOutput
            out = await adapter.adecide(
                {"text": "x", "options": ["approve", "deny"]},
                "choice", CallContext(call_id="c"))
            self.assertIsInstance(out, ChoiceOutput)
            self.assertIn("THIS IS NOT JSON", adapter.last_stderr)
            await adapter.aclose()
        self._run(go())

    def test_raw_fd_write_corrupts_channel_and_drops_child(self):
        # An adapter that bypasses the print redirect and writes raw
        # bytes to fd 1 corrupts framing: fail closed, drop the child.
        async def go():
            adapter = await open_subprocess_adapter("testplugin-fdhacker")
            from peira.adapters.base import CallContext
            with self.assertRaises(AdapterProtocolError):
                await adapter.adecide(
                    {"text": "x", "options": ["approve", "deny"]},
                    "choice", CallContext(call_id="c"))
            await adapter.aclose()
        self._run(go())

    def test_slow_child_times_out_and_is_dropped(self):
        async def go():
            adapter = await open_subprocess_adapter(
                "testplugin-sleeper", timeout=2.0)
            from peira.adapters.base import CallContext
            with self.assertRaises(AdapterCallTimeout):
                await adapter.adecide(
                    {"text": "x", "options": ["approve", "deny"]},
                    "choice", CallContext(call_id="c"))
            await adapter.aclose()
        self._run(go())

    @unittest.skipIf(sys.platform == "win32",
                     "process groups are Unix-only")
    def test_cancelled_call_drops_child(self):
        # Cancelling adecide mid-call must not orphan the child: the
        # shielded drop kills the process group.
        async def go():
            from peira.adapters.base import CallContext
            adapter = await open_subprocess_adapter(
                "testplugin-sleeper", timeout=60.0)
            child = adapter._child
            task = asyncio.ensure_future(adapter.adecide(
                {"text": "x", "options": ["approve", "deny"]},
                "choice", CallContext(call_id="c")))
            await asyncio.sleep(2.0)  # let the call reach the child
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            with self.assertRaises(ProcessLookupError):
                os.killpg(child.proc.pid, 0)
            await adapter.aclose()
        self._run(go())

    def test_adapter_exception_is_framed(self):
        async def go():
            adapter = await open_subprocess_adapter("testplugin-exploding")
            from peira.adapters.base import CallContext
            with self.assertRaises(AdapterRemoteError) as ctx:
                await adapter.adecide(
                    {"text": "x", "options": ["approve", "deny"]},
                    "choice", CallContext(call_id="c"))
            self.assertIn("boom-from-adapter", str(ctx.exception))
            await adapter.aclose()
        self._run(go())

    def test_sync_decide_spawns_and_tears_down(self):
        from peira.adapters.base import CallContext, ChoiceOutput
        adapter = SubprocessAdapter("testplugin-good")
        out = adapter.decide(
            {"text": "x", "options": ["approve", "deny"]},
            "choice", CallContext(call_id="c"))
        self.assertIsInstance(out, ChoiceOutput)
        self.assertIsNone(adapter._child)

    @unittest.skipIf(sys.platform == "win32",
                     "process groups are Unix-only")
    def test_child_runs_in_own_process_group(self):
        async def go():
            adapter = await open_subprocess_adapter("testplugin-good")
            child = adapter._child
            self.assertIsNotNone(child)
            # The child is the leader of its own process group.
            self.assertEqual(os.getpgid(child.proc.pid), child.proc.pid)
            await adapter.aclose()
            # After teardown the group is gone.
            with self.assertRaises(ProcessLookupError):
                os.killpg(child.proc.pid, 0)
        self._run(go())


class RequestFramingTest(unittest.TestCase):
    """Parent-side protocol strictness against stubbed children."""

    def _fake_child(self, response_lines):
        proc = unittest.mock.Mock()
        proc.pid = 999999
        proc.returncode = None
        stdin = unittest.mock.Mock()

        async def fake_drain():
            pass

        stdin.drain = fake_drain

        async def fake_readline():
            if response_lines:
                return response_lines.pop(0)
            return b""

        proc.stdin = stdin
        proc.stdout = unittest.mock.Mock()
        proc.stdout.readline = fake_readline
        proc.stderr = unittest.mock.Mock()

        async def fake_read(_n):
            return b""

        proc.stderr.read = fake_read
        child = sp._Child(proc=proc)
        killed = []
        child.kill = lambda: killed.append(True)  # noqa: E731

        async def fake_drop():
            child.kill()

        child.drop = fake_drop
        return child, killed, stdin

    def test_id_mismatch_drops_child(self):
        async def go():
            adapter = SubprocessAdapter("x")
            child, killed, _ = self._fake_child([
                b'{"id": "wrong-id", "ok": true, "result": {}}\n',
            ])
            with self.assertRaises(AdapterProtocolError):
                await adapter._request(child, "hello", {}, 5.0)
            self.assertTrue(killed)
        asyncio.run(go())

    def test_unparseable_frame_drops_child(self):
        async def go():
            adapter = SubprocessAdapter("x")
            child, killed, _ = self._fake_child([b"not json\n"])
            with self.assertRaises(AdapterProtocolError):
                await adapter._request(child, "hello", {}, 5.0)
            self.assertTrue(killed)
        asyncio.run(go())

    def test_ok_false_raises_remote_error_without_drop(self):
        async def go():
            adapter = SubprocessAdapter("x")
            child, killed, _ = self._fake_child([])
            # Patch readline to echo the request id with ok:false.
            written = {}

            async def fake_drain():
                pass

            def fake_write(data):
                written["frame"] = json.loads(data.decode())

            child.proc.stdin.write = fake_write
            child.proc.stdin.drain = fake_drain

            async def fake_readline():
                req_id = written["frame"]["id"]
                return (json.dumps(
                    {"id": req_id, "ok": False,
                     "error": "RuntimeError: boom"}).encode() + b"\n")

            child.proc.stdout.readline = fake_readline
            with self.assertRaises(AdapterRemoteError) as ctx:
                await adapter._request(child, "decide", {}, 5.0)
            self.assertIn("boom", str(ctx.exception))
            # A framed remote error is not a protocol violation: the
            # child stays up for the next call.
            self.assertFalse(killed)
        asyncio.run(go())


class ShimServeLoopTest(unittest.TestCase):
    """The child's serve loop: framing, key pinning, error frames."""

    def _drive(self, frames, adapter):
        from peira.adapters import _shim

        stdin = io.BytesIO(b"".join(frames))
        stdout = io.BytesIO()

        class FakeStdin:
            buffer = stdin

        class FakeStdout:
            buffer = stdout

        with unittest.mock.patch.object(_shim.sys, "stdin", FakeStdin()), \
                unittest.mock.patch.object(_shim.sys, "stdout",
                                            FakeStdout()), \
                unittest.mock.patch.object(_shim, "_PROTO_OUT", stdout):
            rc = _shim._serve(adapter, {})
        stdout.seek(0)
        responses = [json.loads(line) for line in stdout.read().split(b"\n")
                     if line.strip()]
        return rc, responses

    def test_context_stripped_to_pinned_keys(self):
        seen = {}

        class EchoAdapter:
            name = "echo"
            version = "1"
            supported_primitives = frozenset({"choice"})
            confidence_source = "none"

            def decide(self, case_input, primitive, context):
                seen["keys"] = sorted(vars(context).keys())
                seen["call_id"] = context.call_id
                from peira.adapters.base import ChoiceOutput
                return ChoiceOutput(decision="approve")

        frames = [
            json.dumps({
                "id": "r1", "op": "decide",
                "payload": {
                    "case_input": {"text": "x"},
                    "primitive": "choice",
                    "context": {"call_id": "c1", "suite_id": "trial",
                                "arm": "t0"},
                },
            }).encode() + b"\n",
            json.dumps({"id": "r2", "op": "close",
                        "payload": {}}).encode() + b"\n",
        ]
        rc, responses = self._drive(frames, EchoAdapter())
        self.assertEqual(rc, 0)
        self.assertEqual(seen["keys"], ["call_id"])
        self.assertEqual(seen["call_id"], "c1")
        decide_resp = next(r for r in responses if r["id"] == "r1")
        self.assertTrue(decide_resp["ok"])
        self.assertEqual(decide_resp["result"]["type"], "ChoiceOutput")

    def test_unknown_op_is_framed_error(self):
        class NullAdapter:
            name = "null"
            version = "1"
            supported_primitives = frozenset()
            confidence_source = "none"

        frames = [
            json.dumps({"id": "r1", "op": "frobnicate",
                        "payload": {}}).encode() + b"\n",
            json.dumps({"id": "r2", "op": "close",
                        "payload": {}}).encode() + b"\n",
        ]
        _, responses = self._drive(frames, NullAdapter())
        err = next(r for r in responses if r["id"] == "r1")
        self.assertFalse(err["ok"])
        self.assertIn("unknown op", err["error"])

    def test_unparseable_frame_does_not_kill_serve_loop(self):
        class NullAdapter:
            name = "null"
            version = "1"
            supported_primitives = frozenset()
            confidence_source = "none"

        frames = [
            b"this is not json\n",
            json.dumps({"id": "r1", "op": "close",
                        "payload": {}}).encode() + b"\n",
        ]
        rc, responses = self._drive(frames, NullAdapter())
        self.assertEqual(rc, 0)
        # The close after the garbage frame still got its response.
        close_resp = next(r for r in responses if r["id"] == "r1")
        self.assertTrue(close_resp["ok"])


if __name__ == "__main__":
    unittest.main()
