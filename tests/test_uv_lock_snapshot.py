"""Tests for scripts/uv_lock_snapshot.py (run with: python -m pytest tests).

The converter builds the dependency graph that dependency review
and Dependabot alerts judge, so its failure behaviour matters as
much as its happy path: a lock shape it cannot represent honestly
must raise SystemExit rather than emit a wrong graph. The synthetic
locks below pin each documented rule; the final class runs the
converter against the repository's real uv.lock and derives its
expectations from the lock itself.
"""

import importlib.util
import tomllib
import unittest
from pathlib import Path


def _load_script():
    path = (Path(__file__).resolve().parents[1] / "scripts"
            / "uv_lock_snapshot.py")
    spec = importlib.util.spec_from_file_location("uv_lock_snapshot", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


conv = _load_script()
REGISTRY = {"registry": "https://pypi.org/simple"}


def pkg(name, version="1.0", deps=(), optional=None, dev=None, source=None):
    entry = {"name": name, "version": version,
             "source": REGISTRY if source is None else source,
             "dependencies": list(deps)}
    if optional:
        entry["optional-dependencies"] = optional
    if dev:
        entry["dev-dependencies"] = dev
    return entry


def root_pkg(deps=(), optional=None, dev=None):
    entry = pkg("theroot", "0.0.0", deps, optional, dev,
                source={"editable": "."})
    return entry


def dep(name, version=None, extra=None):
    entry = {"name": name}
    if version is not None:
        entry["version"] = version
    if extra is not None:
        entry["extra"] = extra
    return entry


def manifest(lock):
    return conv.build_manifest(lock)["uv.lock"]["resolved"]


class TestDirectSetsAndScopes(unittest.TestCase):
    def test_runtime_dev_and_transitive_scopes(self):
        lock = {"package": [
            root_pkg(deps=[dep("a")],
                     optional={"dev": [dep("t")], "hf": [dep("b")]}),
            pkg("a", deps=[dep("c")]),
            pkg("b"),
            pkg("t", deps=[dep("d")]),
            pkg("c"),
            pkg("d"),
        ]}
        m = manifest(lock)
        self.assertEqual(m["pkg:pypi/a@1.0"]["relationship"], "direct")
        self.assertEqual(m["pkg:pypi/a@1.0"]["scope"], "runtime")
        self.assertEqual(m["pkg:pypi/b@1.0"]["scope"], "runtime")
        self.assertEqual(m["pkg:pypi/t@1.0"]["relationship"], "direct")
        self.assertEqual(m["pkg:pypi/t@1.0"]["scope"], "development")
        self.assertEqual(m["pkg:pypi/c@1.0"]["relationship"], "indirect")
        self.assertEqual(m["pkg:pypi/c@1.0"]["scope"], "runtime")
        self.assertEqual(m["pkg:pypi/d@1.0"]["scope"], "development")

    def test_runtime_wins_over_development(self):
        # "shared" is a dev-group direct dependency and also a plain
        # dependency of a runtime package: scope promotes to runtime,
        # relationship stays direct.
        lock = {"package": [
            root_pkg(deps=[dep("a")], optional={"dev": [dep("shared")]}),
            pkg("a", deps=[dep("shared")]),
            pkg("shared"),
        ]}
        m = manifest(lock)
        self.assertEqual(m["pkg:pypi/shared@1.0"]["scope"], "runtime")
        self.assertEqual(m["pkg:pypi/shared@1.0"]["relationship"], "direct")

    def test_root_dev_dependencies_group_is_development(self):
        lock = {"package": [
            root_pkg(dev={"group": [dep("t")]}),
            pkg("t"),
        ]}
        m = manifest(lock)
        self.assertEqual(m["pkg:pypi/t@1.0"]["scope"], "development")
        self.assertEqual(m["pkg:pypi/t@1.0"]["relationship"], "direct")


class TestFailClosed(unittest.TestCase):
    def test_dangling_transitive_entry_fails(self):
        lock = {"package": [
            root_pkg(deps=[dep("a")]),
            pkg("a", deps=[dep("ghost")]),
        ]}
        with self.assertRaises(SystemExit):
            manifest(lock)

    def test_dangling_root_entry_fails(self):
        lock = {"package": [root_pkg(deps=[dep("ghost")])]}
        with self.assertRaises(SystemExit):
            manifest(lock)

    def test_pinned_version_absent_fails(self):
        lock = {"package": [
            root_pkg(deps=[dep("a")]),
            pkg("a", deps=[dep("b", version="2.0")]),
            pkg("b", version="1.0"),
        ]}
        with self.assertRaises(SystemExit):
            manifest(lock)

    def test_missing_root_fails(self):
        with self.assertRaises(SystemExit):
            manifest({"package": [pkg("a")]})

    def test_multiple_roots_fail(self):
        lock = {"package": [
            root_pkg(),
            pkg("other", source={"virtual": "."}),
        ]}
        with self.assertRaises(SystemExit):
            manifest(lock)

    def test_non_registry_source_fails(self):
        lock = {"package": [
            root_pkg(deps=[dep("a")]),
            pkg("a", source={"git": "https://example.com/a.git"}),
        ]}
        with self.assertRaises(SystemExit):
            manifest(lock)

    def test_normalization_collision_fails(self):
        lock = {"package": [
            root_pkg(deps=[dep("foo-bar")]),
            pkg("Foo_Bar"),
            pkg("foo-bar"),
        ]}
        with self.assertRaises(SystemExit):
            manifest(lock)


class TestExtras(unittest.TestCase):
    def test_extras_from_plain_dependencies(self):
        # The torch -> cuda-toolkit shape: the extra's dependencies
        # live in the target's optional-dependencies.
        lock = {"package": [
            root_pkg(deps=[dep("t")]),
            pkg("t", deps=[dep("k", extra=["cudart"])]),
            pkg("k", optional={"cudart": [dep("n")]}),
            pkg("n"),
        ]}
        m = manifest(lock)
        self.assertIn("pkg:pypi/n@1.0",
                      m["pkg:pypi/k@1.0"]["dependencies"])

    def test_extras_requested_from_inside_an_optional_group(self):
        # Regression test: the entry requesting b[feat] sits inside
        # a's own optional-dependencies group. Collecting extra
        # requests from plain dependencies only would silently drop
        # the b -> r edge.
        lock = {"package": [
            root_pkg(optional={"top": [dep("a", extra=["inner"])]}),
            pkg("a", optional={"inner": [dep("b", extra=["feat"])]}),
            pkg("b", optional={"feat": [dep("r")]}),
            pkg("r"),
        ]}
        m = manifest(lock)
        self.assertIn("pkg:pypi/r@1.0",
                      m["pkg:pypi/b@1.0"]["dependencies"])
        self.assertEqual(m["pkg:pypi/r@1.0"]["scope"], "runtime")

    def test_unrequested_group_contributes_no_edges(self):
        lock = {"package": [
            root_pkg(deps=[dep("k")]),
            pkg("k", optional={"never": [dep("n")]}),
            pkg("n"),
        ]}
        m = manifest(lock)
        self.assertNotIn("pkg:pypi/n@1.0",
                         m["pkg:pypi/k@1.0"]["dependencies"])
        self.assertEqual(m["pkg:pypi/n@1.0"]["scope"], "unknown")


class TestGraphShape(unittest.TestCase):
    def test_unpinned_entry_edges_to_every_locked_version(self):
        lock = {"package": [
            root_pkg(deps=[dep("a")]),
            pkg("a", deps=[dep("multi")]),
            pkg("multi", version="1.0"),
            pkg("multi", version="2.0"),
        ]}
        m = manifest(lock)
        self.assertEqual(m["pkg:pypi/a@1.0"]["dependencies"],
                         ["pkg:pypi/multi@1.0", "pkg:pypi/multi@2.0"])

    def test_unreachable_package_gets_unknown_scope(self):
        lock = {"package": [
            root_pkg(deps=[dep("a")]),
            pkg("a"),
            pkg("orphan"),
        ]}
        m = manifest(lock)
        self.assertEqual(m["pkg:pypi/orphan@1.0"]["scope"], "unknown")
        self.assertEqual(m["pkg:pypi/orphan@1.0"]["relationship"],
                         "indirect")


class TestRealLock(unittest.TestCase):
    """The repository's own uv.lock, expectations derived in place."""

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "uv.lock"
        if not path.exists():
            raise unittest.SkipTest("uv.lock not present")
        cls.lock = tomllib.loads(path.read_bytes().decode())

    def test_every_non_root_package_is_resolved(self):
        packages = self.lock["package"]
        non_root = [p for p in packages
                    if "editable" not in p.get("source", {})
                    and "virtual" not in p.get("source", {})]
        self.assertEqual(len(manifest(self.lock)), len(non_root))

    def test_direct_sets_match_the_roots_own_declaration(self):
        root = next(p for p in self.lock["package"]
                    if "editable" in p.get("source", {})
                    or "virtual" in p.get("source", {}))
        want_runtime, want_dev = set(), set()
        for e in root.get("dependencies", []):
            want_runtime.add(conv.normalize(e["name"]))
        for group, entries in root.get(
                "optional-dependencies", {}).items():
            target = want_dev if group == "dev" else want_runtime
            for e in entries:
                target.add(conv.normalize(e["name"]))
        for entries in root.get("dev-dependencies", {}).values():
            for e in entries:
                want_dev.add(conv.normalize(e["name"]))
        m = manifest(self.lock)
        got_runtime = {u.split("/")[1].split("@")[0] for u, v in
                       m.items() if v["relationship"] == "direct"
                       and v["scope"] == "runtime"}
        got_dev = {u.split("/")[1].split("@")[0] for u, v in
                   m.items() if v["relationship"] == "direct"
                   and v["scope"] == "development"}
        self.assertEqual(got_runtime, want_runtime)
        self.assertEqual(got_dev, want_dev - want_runtime)

    def test_no_dangling_edges_and_no_unknown_scopes(self):
        m = manifest(self.lock)
        for url, entry in m.items():
            for target in entry["dependencies"]:
                self.assertIn(target, m)
            self.assertNotEqual(entry["scope"], "unknown",
                                f"{url} unexpectedly unreachable")


if __name__ == "__main__":
    unittest.main()
