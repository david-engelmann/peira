"""Tests for `peira doctor` (peira/doctor.py and the CLI wiring).

The doctor is read-only: no network, no downloads, no file writes.
Tests assert that property where feasible and never depend on the
machine's actual hardware beyond "the probe doesn't crash".
"""

import os
from pathlib import Path

import pytest

from peira import doctor
from peira.doctor import (
    AdapterReadiness,
    CheckResult,
    SystemInfo,
    check_adapter,
    check_pricing,
    check_system,
    discover_adapters,
    format_report,
    probe_gpu,
    probe_system,
    run_doctor,
)


# ---------------------------------------------------------------------------
# System probes: never crash, never take long
# ---------------------------------------------------------------------------

class TestProbes:
    def test_probe_system_never_raises(self):
        info = probe_system()
        assert isinstance(info, SystemInfo)
        assert isinstance(info.python_version, str)

    def test_probe_gpu_never_raises(self):
        # May be None (no GPU) or a string; must not raise or hang.
        result = probe_gpu()
        assert result is None or isinstance(result, str)

    def test_check_system_all_statuses_valid(self):
        info = probe_system()
        for c in check_system(info):
            assert c.status in ("ok", "warn", "fail", "unknown"), c

    def test_check_system_python_version_gate(self):
        info = SystemInfo(python_version="3.11.0")
        py = next(c for c in check_system(info) if c.name == "Python")
        assert py.status == "fail"
        info = SystemInfo(python_version="3.12.3")
        py = next(c for c in check_system(info) if c.name == "Python")
        assert py.status == "ok"

    def test_check_system_ram_thresholds(self):
        warn = next(c for c in check_system(SystemInfo(ram_available_gb=6.0))
                    if c.name == "RAM")
        assert warn.status == "warn"
        fail = next(c for c in check_system(SystemInfo(ram_available_gb=2.0))
                    if c.name == "RAM")
        assert fail.status == "fail"
        ok = next(c for c in check_system(SystemInfo(ram_available_gb=32.0))
                  if c.name == "RAM")
        assert ok.status == "ok"
        unknown = next(c for c in check_system(SystemInfo(ram_available_gb=None))
                       if c.name == "RAM")
        assert unknown.status == "unknown"

    def test_check_system_disk_threshold(self):
        warn = next(c for c in check_system(SystemInfo(disk_free_gb=5.0))
                    if c.name == "Disk")
        assert warn.status == "warn"
        ok = next(c for c in check_system(SystemInfo(disk_free_gb=100.0))
                  if c.name == "Disk")
        assert ok.status == "ok"

    def test_check_system_gpu(self):
        ok = next(c for c in check_system(SystemInfo(gpu="NVIDIA Test (8GB)"))
                  if c.name == "GPU")
        assert ok.status == "ok"
        warn = next(c for c in check_system(SystemInfo(gpu=None))
                    if c.name == "GPU")
        assert warn.status == "warn"


# ---------------------------------------------------------------------------
# Adapter discovery
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_discovers_known_adapters(self):
        classes, failed = discover_adapters()
        names = {c.name for c in classes}
        # A representative sample across all adapter modules.
        for expected in ("mock", "laya", "kev", "semif", "openjev-sglang",
                         "jev", "openai-structured", "moonshot-structured",
                         "anthropic-structured", "google-structured",
                         "shieldstral"):
            assert expected in names, f"{expected} not discovered: {names}"
        assert not failed, f"modules failed to import: {failed}"

    def test_skips_abstract_bases(self):
        classes, _ = discover_adapters()
        names = {c.name for c in classes}
        assert "local-systemone" not in names
        assert "hf-base" not in names
        assert "structured-llm-base" not in names

    def test_no_duplicate_names(self):
        classes, _ = discover_adapters()
        names = [c.name for c in classes]
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Requirement checking
# ---------------------------------------------------------------------------

class _FakeAdapter:
    name = "fake"


class TestRequirements:
    def test_env_var_present(self, monkeypatch):
        monkeypatch.setenv("PEIRA_DOCTOR_TEST_KEY", "secret-value")

        class A(_FakeAdapter):
            @classmethod
            def doctor_requirements(cls):
                return [{"kind": "env_var", "name": "PEIRA_DOCTOR_TEST_KEY"}]

        result = check_adapter(A, SystemInfo())
        assert result.status == "ready"

    def test_env_var_missing_never_prints_value(self, monkeypatch):
        monkeypatch.delenv("PEIRA_DOCTOR_TEST_KEY", raising=False)

        class A(_FakeAdapter):
            @classmethod
            def doctor_requirements(cls):
                return [{"kind": "env_var", "name": "PEIRA_DOCTOR_TEST_KEY",
                         "hint": "export PEIRA_DOCTOR_TEST_KEY=..."}]

        result = check_adapter(A, SystemInfo())
        assert result.status == "missing_api_key"
        assert "PEIRA_DOCTOR_TEST_KEY" in result.detail
        # The value must never appear anywhere in the verdict.
        assert "secret" not in result.detail + result.hint

    def test_env_var_any_of_group(self, monkeypatch):
        monkeypatch.delenv("PEIRA_DOC_A", raising=False)
        monkeypatch.setenv("PEIRA_DOC_B", "x")

        class A(_FakeAdapter):
            @classmethod
            def doctor_requirements(cls):
                return [{"kind": "env_var", "name": "PEIRA_DOC_A"},
                        {"kind": "env_var", "name": "PEIRA_DOC_B"}]

        result = check_adapter(A, SystemInfo())
        assert result.status == "ready"

    def test_python_package(self):
        class A(_FakeAdapter):
            @classmethod
            def doctor_requirements(cls):
                return [{"kind": "python_package", "name": "os"}]

        assert check_adapter(A, SystemInfo()).status == "ready"

        class B(_FakeAdapter):
            @classmethod
            def doctor_requirements(cls):
                return [{"kind": "python_package",
                         "name": "peira_nonexistent_pkg_xyz"}]

        result = check_adapter(B, SystemInfo())
        assert result.status == "missing_dependency"
        assert "peira_nonexistent_pkg_xyz" in result.detail

    def test_binary_with_alternatives(self):
        # `sh` exists on every POSIX test machine.
        class A(_FakeAdapter):
            @classmethod
            def doctor_requirements(cls):
                return [{"kind": "binary", "name": "peira-nope-xyz",
                         "alternatives": ["sh"]}]

        assert check_adapter(A, SystemInfo()).status == "ready"

        class B(_FakeAdapter):
            @classmethod
            def doctor_requirements(cls):
                return [{"kind": "binary", "name": "peira-nope-xyz"}]

        result = check_adapter(B, SystemInfo())
        assert result.status == "missing_dependency"

    def test_ram_requirement(self):
        class A(_FakeAdapter):
            @classmethod
            def doctor_requirements(cls):
                return [{"kind": "ram_gb", "min": 1.0}]

        assert check_adapter(A, SystemInfo(ram_available_gb=16.0)).status == "ready"
        result = check_adapter(A, SystemInfo(ram_available_gb=0.5))
        assert result.status == "insufficient_hardware"

    def test_gpu_requirement(self):
        class A(_FakeAdapter):
            @classmethod
            def doctor_requirements(cls):
                return [{"kind": "gpu"}]

        assert check_adapter(A, SystemInfo(gpu="NVIDIA X")).status == "ready"
        result = check_adapter(A, SystemInfo(gpu=None))
        assert result.status == "insufficient_hardware"

    def test_mixed_problems_classify_as_dependency(self, monkeypatch):
        monkeypatch.delenv("PEIRA_DOCTOR_TEST_KEY", raising=False)

        class A(_FakeAdapter):
            @classmethod
            def doctor_requirements(cls):
                return [{"kind": "env_var", "name": "PEIRA_DOCTOR_TEST_KEY"},
                        {"kind": "python_package",
                         "name": "peira_nonexistent_pkg_xyz"}]

        result = check_adapter(A, SystemInfo())
        assert result.status == "missing_dependency"

    def test_no_requirements_is_unknown(self):
        result = check_adapter(_FakeAdapter, SystemInfo())
        assert result.status == "unknown"

    def test_generic_env_var_inference(self, monkeypatch):
        monkeypatch.delenv("PEIRA_DOC_GENERIC", raising=False)

        class A(_FakeAdapter):
            _env_vars = ("PEIRA_DOC_GENERIC",)

        result = check_adapter(A, SystemInfo())
        assert result.status == "missing_api_key"

    def test_broken_doctor_requirements_is_unknown(self):
        class A(_FakeAdapter):
            @classmethod
            def doctor_requirements(cls):
                raise RuntimeError("boom")

        result = check_adapter(A, SystemInfo())
        # Falls back to generic inference (no _env_vars) -> unknown.
        assert result.status == "unknown"

    def test_hints_deduped(self):
        class A(_FakeAdapter):
            @classmethod
            def doctor_requirements(cls):
                return [
                    {"kind": "python_package", "name": "peira_nope_1",
                     "hint": "same hint"},
                    {"kind": "python_package", "name": "peira_nope_2",
                     "hint": "same hint"},
                ]

        result = check_adapter(A, SystemInfo())
        assert result.hint.count("same hint") == 1


# ---------------------------------------------------------------------------
# Real adapters declare sane requirements
# ---------------------------------------------------------------------------

class TestRealAdapterRequirements:
    def test_all_real_adapters_check_without_crashing(self):
        classes, _ = discover_adapters()
        info = probe_system()
        for cls in classes:
            result = check_adapter(cls, info)
            assert isinstance(result, AdapterReadiness)
            assert result.status in (
                "ready", "missing_dependency", "missing_api_key",
                "insufficient_hardware", "unknown"), (cls.name, result)

    def test_llm_adapters_use_env_var_inference(self):
        from peira.adapters.llm import OpenAIAdapter
        assert OpenAIAdapter._env_vars == ("OPENAI_API_KEY",)
        # No explicit doctor_requirements: generic inference applies.
        assert "doctor_requirements" not in OpenAIAdapter.__dict__

    def test_mock_is_unknown_not_ready(self):
        from peira.adapters.mock import MockAdapter
        result = check_adapter(MockAdapter, SystemInfo())
        assert result.status == "unknown"


# ---------------------------------------------------------------------------
# Pricing / datasets
# ---------------------------------------------------------------------------

class TestPricing:
    def test_pricing_table_loads(self):
        results = check_pricing()
        assert len(results) == 1
        assert results[0].status == "ok"
        assert "models priced" in results[0].detail


class TestDatasets:
    def test_check_datasets_runs(self):
        from peira.cli import _repo_root
        results = doctor.check_datasets(_repo_root())
        assert results, "expected at least one suite check"
        for r in results:
            assert r.status in ("ok", "warn", "fail", "unknown"), r


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

class TestFormat:
    def test_format_report_structure(self):
        report = run_doctor(Path("."))
        text = format_report(report)
        for heading in ("Peira Doctor", "System:", "Installation:",
                        "Dataset:", "Pricing:", "Adapters:", "Summary:"):
            assert heading in text, f"missing {heading}"

    def test_format_never_crashes_on_empty(self):
        text = format_report(doctor.DoctorReport())
        assert "Peira Doctor" in text
        assert "0/0 adapters ready" in text

    def test_format_adapter_status_labels(self):
        report = doctor.DoctorReport(adapters=[
            AdapterReadiness("a", "ready", "all requirements met"),
            AdapterReadiness("b", "missing_api_key", "KEY not set",
                             "export KEY=..."),
        ])
        text = format_report(report)
        assert "a: ✓ READY" in text
        assert "b: ✗ MISSING API KEY" in text
        assert "1/2 adapters ready" in text


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

class TestCli:
    def test_doctor_subcommand_wired(self):
        from peira.cli import build_parser
        args = build_parser().parse_args(["doctor"])
        assert args.func.__name__ == "cmd_doctor"

    def test_cmd_doctor_exits_zero(self, capsys):
        from peira.cli import cmd_doctor, _repo_root
        import argparse
        rc = cmd_doctor(argparse.Namespace())
        assert rc == 0
        out = capsys.readouterr().out
        assert "Peira Doctor" in out

    def test_doctor_makes_no_network_calls(self, monkeypatch):
        """Fail the test if doctor touches the network."""
        import socket
        real_create = socket.socket

        def boom(*a, **k):
            raise AssertionError("doctor made a network call")

        monkeypatch.setattr(socket, "socket", boom)
        # urllib uses socket.socket internally; also block urlopen directly.
        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", boom)
        report = run_doctor(Path("."))
        assert report.adapters, "expected adapters to be checked"

    def test_doctor_writes_no_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        before = set(tmp_path.iterdir())
        run_doctor(tmp_path)
        assert set(tmp_path.iterdir()) == before
