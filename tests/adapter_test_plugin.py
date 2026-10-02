"""Shared fake third-party distribution for adapter plugin tests.

Installs a real ``peira_testplugin`` dist-info (real entry points)
into the test venv's site-packages so the shim child loads it
through the genuine ``discovery.load_registered`` path. Imported by
the plugin test modules; not collected as a test itself.
"""

import contextlib
import os
import shutil
import sys
import sysconfig
import tempfile
import time

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
    conformance_attestations = {"retry_posture": True}

    def close(self):
        pass


class GoodAdapter(_Base):
    """Well-behaved adapter; echoes what the child process sees."""
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


# --- conformance-kit fixtures ------------------------------------


class ConfGoodAdapter(_Base):
    """Passes every conformance suite."""
    name = "testplugin-conf-good"

    def decide(self, case_input, primitive, context):
        return ChoiceOutput(decision="approve", confidence=0.9)


class ConfNondeterministicAdapter(_Base):
    """Fails deterministic replay: alternates decisions."""
    name = "testplugin-conf-nondeterministic"

    def __init__(self):
        self._n = 0

    def decide(self, case_input, primitive, context):
        self._n += 1
        return ChoiceOutput(
            decision="approve" if self._n % 2 else "deny")


class ConfSmugglerAdapter(_Base):
    """Fails no_identifier_smuggling: echoes the call_id verbatim."""
    name = "testplugin-conf-smuggler"

    def decide(self, case_input, primitive, context):
        return ChoiceOutput(
            decision="approve",
            transcript={"debug_call_id": context.call_id},
            refusal_reason="",
        )


class ConfNoAttestAdapter(_Base):
    """Fails the must-attest gate: declares no attestations."""
    name = "testplugin-conf-noattest"
    conformance_attestations = {}

    def decide(self, case_input, primitive, context):
        return ChoiceOutput(decision="approve")


class ConfMetaLeakAdapter(_Base):
    """Fails metadata_invariance: detects probe-shaped call ids
    (simulates an adapter that sniffs trial metadata)."""
    name = "testplugin-conf-metaleak"

    def decide(self, case_input, primitive, context):
        import re
        if re.fullmatch(r"meta-[0-9a-f]{32}", context.call_id):
            return ChoiceOutput(decision="deny")
        return ChoiceOutput(decision="approve")


class ConfSamplerAdapter(_Base):
    """Declares sampling and wobbles: determinism passes."""
    name = "testplugin-conf-sampler"
    sampling_posture = "sampling"

    def __init__(self):
        self._n = 0

    def decide(self, case_input, primitive, context):
        self._n += 1
        return ChoiceOutput(
            decision="approve" if self._n % 2 else "deny")


class ConfSamplerSteadyAdapter(_Base):
    """Declares sampling but is secretly deterministic: warning."""
    name = "testplugin-conf-sampler-steady"
    sampling_posture = "sampling"

    def decide(self, case_input, primitive, context):
        return ChoiceOutput(decision="approve")


class ConfJunkSnifferAdapter(_Base):
    """Fails junk_keys_ignored: sniffs injected case_input keys."""
    name = "testplugin-conf-junk-sniffer"

    def decide(self, case_input, primitive, context):
        if "_suite_id" in case_input:
            return ChoiceOutput(decision="deny")
        return ChoiceOutput(decision="approve")
'''

ENTRY_POINTS_TXT = """\
[peira.adapters]
testplugin-good = peira_testplugin:GoodAdapter
testplugin-printer = peira_testplugin:PrinterAdapter
testplugin-sleeper = peira_testplugin:SleeperAdapter
testplugin-exploding = peira_testplugin:ExplodingAdapter
testplugin-fdhacker = peira_testplugin:FdHackerAdapter
testplugin-conf-good = peira_testplugin:ConfGoodAdapter
testplugin-conf-nondeterministic = peira_testplugin:ConfNondeterministicAdapter
testplugin-conf-smuggler = peira_testplugin:ConfSmugglerAdapter
testplugin-conf-noattest = peira_testplugin:ConfNoAttestAdapter
testplugin-conf-metaleak = peira_testplugin:ConfMetaLeakAdapter
testplugin-conf-sampler = peira_testplugin:ConfSamplerAdapter
testplugin-conf-sampler-steady = peira_testplugin:ConfSamplerSteadyAdapter
testplugin-conf-junk-sniffer = peira_testplugin:ConfJunkSnifferAdapter
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
