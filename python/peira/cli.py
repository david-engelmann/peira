"""peira CLI: run evaluations, validate datasets, render reports.

Exit codes: 0 clean, 1 user error (bad config/adapter), 2 infrastructure
error (resource, network, crash), 3 run completed but ranking-ineligible
(eligibility notes are warnings, not failures).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any

from peira import __version__
from peira.adapters.mock import MockAdapter
from peira.artifacts import RunArtifact
from peira.dataset import atomic_write_text, verify_manifest, verify_manifest_sealed
from peira.metrics import PerCaseResult
from peira.runner import (
    SUITE_DIRS,
    load_cases,
    replay_suite,
    run_suite,
    validate_partial,
)
from peira.templates import TEMPLATES

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_INFRA_ERROR = 2
EXIT_GATE_NOTE = 3  # ran fine, but the run is not ranking-eligible

# dataset_version follows semver (docs/Dataset.md); prerelease suffixes
# like 0.1.0-trial are allowed.
_SEMVER_RE = re.compile(r"\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?")


def _repo_root() -> Path:
    # python/peira/cli.py -> repo root is three levels up.
    return Path(__file__).resolve().parents[2]


def _safe_adapter_slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def _num(x: Any) -> str:
    """Format a metric value for the HTML report.

    Metric cells land in HTML: floats render with four decimals, ints
    (and bools) pass through as plain text, and anything else is
    HTML-escaped — a hostile artifact must not smuggle markup through
    a metric value. This function never raises.
    """
    if isinstance(x, bool):
        return "True" if x else "False"
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        return f"{x:.4f}"
    if x is None:
        return "—"
    return html.escape(str(x))


def _val(x: Any) -> str:
    """Render a possibly-withheld metric value.

    ``summarize()`` returns None (never 0.0) for withheld/insufficient
    data — the report renders that as "insufficient data", never as a
    bare "0" or a silent blank. Hostile values are escaped via
    :func:`_num`; this function never raises.
    """
    return "insufficient data" if x is None else _num(x)


def _ci95(ci: Any) -> str:
    """Render a possibly-withheld 95% CI pair.

    A withheld interval (None, or a hostile non-pair) renders as
    "insufficient data" — never a traceback, never markup. This
    function never raises.
    """
    if not isinstance(ci, (list, tuple)) or len(ci) != 2:
        return "insufficient data"
    return f"{_val(ci[0])}–{_val(ci[1])}"


def _get_adapter(name: str):
    if name == "mock":
        return MockAdapter()
    return _load_dotted_adapter(name)


def _unknown_adapter(spec: str) -> ValueError:
    # One wording for every unresolvable adapter, so the Troubleshooting
    # catalog pins a single message.
    return ValueError(
        f"unknown adapter: {spec!r} (available: 'mock' or a dotted "
        f"path like 'examples.minimal_adapter')"
    )


def _load_dotted_adapter(spec: str):
    """Load an adapter from a dotted path.

    Accepted forms:
      package.module             module-level ``adapter`` object
      package.module:ClassName   class, instantiated with no arguments
      package.module.ClassName   class, instantiated with no arguments

    The working directory is prepended to sys.path so adapters next to the
    checkout (e.g. ``examples/``) resolve when the console script is used.
    Only load adapter paths you trust: the module is imported — and
    therefore executed — on load (see docs/Troubleshooting.md).
    """
    import importlib

    module_name, sep, attr = spec.partition(":")
    if not module_name:
        # import_module("") raises ValueError("Empty module name"), which
        # the ImportError handler below would miss — reject the empty
        # module up front with the standard unknown-adapter message.
        raise _unknown_adapter(spec)
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    try:
        module = importlib.import_module(module_name)
    except ImportError as first_err:
        module = None
        if "." in module_name and not sep:
            parent, attr = module_name.rsplit(".", 1)
            try:
                module = importlib.import_module(parent)
            except ImportError:
                module = None
        if module is None:
            raise _unknown_adapter(spec) from first_err
    if not attr:
        candidate = getattr(module, "adapter", None)
        if candidate is None:
            raise ValueError(
                f"adapter module {module_name!r} has no top-level `adapter`; "
                f"use 'module:ClassName' to name a class"
            )
    else:
        candidate = getattr(module, attr, None)
        if candidate is None:
            raise ValueError(
                f"adapter module {module.__name__!r} has no attribute {attr!r}"
            )
    adapter = candidate() if isinstance(candidate, type) else candidate
    for field in ("name", "version", "supported_primitives", "decide"):
        if not hasattr(adapter, field):
            raise ValueError(
                f"adapter {spec!r} is missing {field!r} "
                f"(see BaseAdapter in python/peira/adapters/base.py)"
            )
    return adapter


def _suite_dataset_identity(suite_dir: Path) -> tuple[str, str]:
    """Return (dataset_version, manifest_sha256) for a suite directory.

    The manifest is verified against the directory *before* anything is
    scored. A mismatch fails closed with ValueError: scoring a tampered
    dataset would seal a lie into the analysis lock. A missing or
    unreadable manifest is not tampering — it yields the fallback label
    and an empty digest, i.e. an explicitly unbound run.
    """
    manifest_path = suite_dir / "manifest.json"
    if not manifest_path.is_file():
        return "0.1.0-demo", ""
    try:
        # Sealed read: the digest below is computed over the same bytes
        # that were verified — never a re-read that raced a swap.
        manifest, manifest_sha256, errors = verify_manifest_sealed(suite_dir)
    except (OSError, ValueError) as e:
        print(f"warning: unreadable manifest at {manifest_path} ({e}); "
              f"recording dataset_version='0.1.0-demo'.",
              file=sys.stderr)
        return "0.1.0-demo", ""
    if errors:
        raise ValueError(
            "dataset manifest verification failed:\n  "
            + "\n  ".join(errors)
            + "\nrefusing to score: the dataset changed since its manifest "
              "was built — rebuild the manifest or restore the files."
        )
    dataset_version = str(manifest.get("dataset_version", "0.1.0-demo"))
    return dataset_version, manifest_sha256


def _print_run_summary(artifact, out_path: Path) -> None:
    m = artifact.metrics
    print(f"done: {m['n_cases']} cases ({m['n_eligible']} eligible)")
    print(f"  ASR (conditional): {_val(m['asr_conditional'])} "
          f"95% CI {_ci95(m['asr_ci95'])}")
    print(f"  benign accuracy:   {_val(m['benign_accuracy'])} "
          f"95% CI {_ci95(m['benign_accuracy_ci95'])}")
    print(f"  malformed rate:    {_val(m['malformed_rate'])}")
    print(f"  refusal rate:      {_val(m['refusal_rate'])} "
          f"95% CI {_ci95(m['refusal_rate_ci95'])}")
    inelig = m["ineligible_by_reason"]
    print(f"  ineligible:        {sum(inelig.values())} "
          f"({', '.join(f'{k}={v}' for k, v in inelig.items())})")
    print(f"  ranking eligible:  {m['ranking_eligible']}"
          + (f" ({'; '.join(m['eligibility_notes'])})" if m['eligibility_notes'] else ""))
    print(f"artifact: {out_path}")
    print(f"analysis lock: {artifact.analysis_lock[:16]}…")


def _write_final_artifact(out_dir: Path, slug: str, suite: str,
                          artifact, suffix: str = "") -> Path:
    out_path = out_dir / f"{slug}-{suite}{suffix}.json"
    # Atomic write: a crash mid-write must never leave a corrupt
    # artifact behind.
    atomic_write_text(out_path, artifact.to_json())
    return out_path


def cmd_run(args: argparse.Namespace) -> int:
    root = _repo_root()
    try:
        adapter = _get_adapter(args.adapter)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR

    suite = args.suite
    if suite == "smoke":
        suite = "trial"  # smoke is the Trial alias
    if suite not in SUITE_DIRS:
        print(f"error: unknown suite {args.suite!r} (available: trial-demo, trial/smoke)",
              file=sys.stderr)
        return EXIT_USER_ERROR
    suite_dir = root / SUITE_DIRS[suite]
    if not suite_dir.exists():
        print(f"error: suite directory {suite_dir} not found",
              file=sys.stderr)
        return EXIT_USER_ERROR

    try:
        cases = load_cases(suite_dir)
    except ValueError as e:
        print(f"error: invalid case data: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    if not cases:
        print(f"error: no cases found in {suite_dir}", file=sys.stderr)
        return EXIT_USER_ERROR

    out_dir = Path(args.out)

    if args.max_concurrency < 1:
        print(f"error: --max-concurrency must be >= 1 "
              f"(got {args.max_concurrency})", file=sys.stderr)
        return EXIT_USER_ERROR
    if args.max_attempts < 1:
        print(f"error: --max-attempts must be >= 1 "
              f"(got {args.max_attempts})", file=sys.stderr)
        return EXIT_USER_ERROR
    if args.call_timeout is not None and args.call_timeout <= 0:
        print(f"error: --call-timeout must be > 0 "
              f"(got {args.call_timeout})", file=sys.stderr)
        return EXIT_USER_ERROR

    if args.dry_run:
        print(f"dry run: {len(cases)} cases, adapter={adapter.name}, "
              f"suite={args.suite} — config valid, nothing scored.")
        return EXIT_OK

    # The output directory is created after the dry-run return: a dry
    # run must have zero side effects.
    out_dir.mkdir(parents=True, exist_ok=True)

    already_done: set[str] = set()
    prior_results: list[PerCaseResult] = []
    slug = _safe_adapter_slug(args.adapter)
    # Dataset identity is sealed into the analysis lock: the manifest is
    # verified before anything is scored, and its SHA-256 is recorded, so
    # the artifact proves the exact bytes scored — not just the version
    # label. A verification mismatch fails closed (nothing is scored).
    try:
        dataset_version, manifest_sha256 = _suite_dataset_identity(suite_dir)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    partial_path = out_dir / f"{slug}-{suite}.partial.json"
    if args.resume:
        if not partial_path.exists():
            print(f"warning: no partial run at {partial_path}; starting fresh.",
                  file=sys.stderr)
        else:
            try:
                partial = RunArtifact.from_json(partial_path.read_text())
            except Exception as e:
                print(f"warning: could not read partial run ({e}); "
                      f"starting fresh.", file=sys.stderr)
                partial = None
            if partial is not None:
                try:
                    already_done, prior_results = validate_partial(
                        partial, adapter, cases, suite, dataset_version,
                        manifest_sha256, seed=args.seed)
                except ValueError as e:
                    print(f"error: {e} — delete {partial_path} or drop "
                          f"--resume and re-run.", file=sys.stderr)
                    return EXIT_USER_ERROR
                print(f"resuming: {len(already_done)} cases already done, "
                      f"{len(cases) - len(already_done)} remaining.")

    def progress(i: int, total: int) -> None:
        if args.json_progress:
            print(json.dumps({"event": "progress", "done": i, "total": total}),
                  flush=True)
        elif i == 1 or i == total or i % 50 == 0:
            print(f"  [{i}/{total}]", file=sys.stderr, flush=True)

    try:
        artifact = run_suite(
            adapter, cases, suite, dataset_version,
            progress=progress, already_done=already_done,
            prior_results=prior_results, partial_path=partial_path,
            manifest_sha256=manifest_sha256, seed=args.seed,
            max_concurrency=args.max_concurrency,
            max_attempts=args.max_attempts,
            call_timeout=args.call_timeout,
            cache_dir=args.cache_dir,
            transcript_path=args.transcript,
        )
    except KeyboardInterrupt:
        print("\ninterrupted — partial run saved; re-run with --resume.",
              file=sys.stderr)
        return EXIT_INFRA_ERROR
    except ValueError as e:
        # Config errors with actionable messages (bad cache dir,
        # unwritable transcript path): user error, not a traceback.
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    except Exception:
        traceback.print_exc()
        return EXIT_INFRA_ERROR

    out_path = _write_final_artifact(out_dir, slug, suite, artifact)
    if partial_path.exists():
        partial_path.unlink()

    _print_run_summary(artifact, out_path)
    if not artifact.metrics["ranking_eligible"]:
        return EXIT_GATE_NOTE
    return EXIT_OK


def cmd_replay(args: argparse.Namespace) -> int:
    """Re-score a recorded transcript without calling any provider."""
    root = _repo_root()
    suite = args.suite
    if suite == "smoke":
        suite = "trial"  # smoke is the Trial alias
    if suite not in SUITE_DIRS:
        print(f"error: unknown suite {args.suite!r} (available: trial-demo, trial/smoke)",
              file=sys.stderr)
        return EXIT_USER_ERROR
    suite_dir = root / SUITE_DIRS[suite]
    if not suite_dir.exists():
        print(f"error: suite directory {suite_dir} not found",
              file=sys.stderr)
        return EXIT_USER_ERROR
    try:
        cases = load_cases(suite_dir)
    except ValueError as e:
        print(f"error: invalid case data: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    if not cases:
        print(f"error: no cases found in {suite_dir}", file=sys.stderr)
        return EXIT_USER_ERROR
    try:
        dataset_version, manifest_sha256 = _suite_dataset_identity(suite_dir)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        artifact = replay_suite(
            Path(args.transcript), cases, suite, dataset_version,
            manifest_sha256=manifest_sha256,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    except Exception:
        traceback.print_exc()
        return EXIT_INFRA_ERROR

    out_path = _write_final_artifact(
        out_dir, _safe_adapter_slug(artifact.adapter_name), suite, artifact,
        suffix=".replay",
    )
    _print_run_summary(artifact, out_path)
    if not artifact.metrics["ranking_eligible"]:
        return EXIT_GATE_NOTE
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    from peira.schema import validate_case_dict

    dataset_dir = Path(args.dataset)
    if not dataset_dir.exists():
        print(f"error: {dataset_dir} not found", file=sys.stderr)
        return EXIT_USER_ERROR
    n, bad = 0, 0
    for path in sorted(dataset_dir.glob("*.jsonl")):
        # Explicit UTF-8: the platform default (e.g. cp1252 on Windows)
        # would silently mojibake non-ASCII case content.
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                if not line.strip():
                    continue
                n += 1
                # Malformed JSON is a user error (exit 1 with file:line),
                # not an infrastructure failure.
                try:
                    errors = validate_case_dict(json.loads(line))
                except json.JSONDecodeError as e:
                    bad += 1
                    print(f"{path}:{lineno}: invalid JSON ({e})")
                    continue
                if errors:
                    bad += 1
                    print(f"{path}:{lineno}: {'; '.join(errors)}")
    print(f"validated {n} cases, {bad} invalid")
    return EXIT_USER_ERROR if bad else EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    run_path = Path(args.run)
    if not run_path.exists():
        print(f"error: {run_path} not found", file=sys.stderr)
        return EXIT_USER_ERROR
    # A corrupt artifact is a user error (exit 1), not an infrastructure
    # failure: from_json validates strictly, raising ValueError on any
    # malformed shape, which is caught here.
    try:
        artifact = RunArtifact.from_json(run_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: {run_path} is not a valid run artifact ({e})",
              file=sys.stderr)
        return EXIT_USER_ERROR
    if not artifact.verify():
        print("warning: analysis lock mismatch — artifact was modified after sealing.",
              file=sys.stderr)
    # S8b sealed the A3 summary schema into artifacts. An artifact from
    # before the rewiring is structurally valid but its metrics lack
    # the A3 sections — rendering it would silently drop half the
    # report, so refuse with an actionable message instead.
    if "calibration" not in artifact.metrics:
        print(f"error: {run_path} uses the pre-S8b artifact schema "
              f"(no A3 metric summary) — re-run the suite to generate "
              f"a current artifact", file=sys.stderr)
        return EXIT_USER_ERROR
    # Metric access is also hostile input: a well-formed-JSON artifact
    # with the wrong shape must still exit 1, not traceback.
    # AttributeError is included: a truthy non-dict section (e.g.
    # "selective_prediction": [1,2,3]) sails through .get chains and
    # fails on the next .get/.items with AttributeError, not TypeError.
    try:
        page = _report_page(artifact)
    except (ValueError, KeyError, TypeError, IndexError, AttributeError) as e:
        print(f"error: {run_path} is not a valid run artifact ({e})",
              file=sys.stderr)
        return EXIT_USER_ERROR
    out = Path(args.out)
    # Explicit UTF-8: the report contains ✓/✗ glyphs, which the Windows
    # default encoding (cp1252) cannot represent.
    try:
        out.write_text(page, encoding="utf-8")
    except OSError as e2:
        print(f"error: cannot write report to {out} ({e2})", file=sys.stderr)
        return EXIT_USER_ERROR
    print(f"report: {out}")
    return EXIT_OK


def _report_page(artifact) -> str:
    m = artifact.metrics
    # Case ids, family names, adapter names, decisions, refusal reasons,
    # and suite/dataset labels are author- or adapter-controlled: escape
    # them so hostile markup lands inert. Metric values go through _val
    # / _ci95 for the same reason — a hostile artifact can smuggle
    # markup through any interpolated cell, and a withheld (None) value
    # must render as "insufficient data", never as a bare 0.
    e = html.escape
    rows = "\n".join(
        f"<tr><td>{e(str(fam))}</td><td>{_num(v['n'])}</td>"
        f"<td>{_num(v.get('n_eligible'))}</td>"
        f"<td>{_val(v.get('asr'))}</td>"
        f"<td>{_ci95(v.get('asr_ci95'))}</td>"
        f"<td>{_val(v.get('refusal_rate'))}</td></tr>"
        for fam, v in sorted(m["per_family"].items())
    )
    def _mark(ok: bool) -> str:
        return "✓" if ok else "✗"
    def _rec(r, variant: str) -> dict:
        rec = r.get(variant, {})
        return rec if isinstance(rec, dict) else {}
    case_rows = "\n".join(
        f"<tr><td>{e(str(r.get('case_id', '?')))}</td>"
        f"<td>{e(str(r.get('family', '?')))}</td>"
        f"<td>{e(str(_rec(r, 'benign').get('decision', '?')))}</td>"
        f"<td>{e(str(_rec(r, 'attacked').get('decision', '?')))}</td>"
        f"<td>{_mark(bool(r.get('flipped')))}</td>"
        f"<td>{_mark(bool(r.get('eligible')))}</td>"
        f"<td>{e(str(r.get('ineligibility_reason') or '—'))}</td>"
        f"<td>{_mark(bool(_rec(r, 'attacked').get('abstained')))}</td></tr>"
        for r in artifact.results
    )
    inelig = m.get("ineligible_by_reason", {})
    inelig_line = ", ".join(
        f"{e(str(k))}: {_num(v)}" for k, v in sorted(inelig.items())
    ) or "none"

    # --- A3 sections (S8b): calibration, selective prediction, score
    # diagnostics, severity-weighted ASR, outcome accounting. Every
    # accessor is defensive (.get with a default): a hostile artifact
    # that passes the schema gate can still omit a subsection, and the
    # report must degrade to "insufficient data", not traceback.
    def _est_cell(est: Any) -> str:
        """Render a {value, ci95, n, sufficient} estimate dict."""
        if not isinstance(est, dict):
            return "insufficient data"
        return f"{_val(est.get('value'))} ({_ci95(est.get('ci95'))}, n={_num(est.get('n'))})"

    def _delta_cell(d: Any) -> str:
        """Render a {delta, ci95, n, sufficient} delta dict."""
        if not isinstance(d, dict):
            return "insufficient data"
        return f"{_val(d.get('delta'))} ({_ci95(d.get('ci95'))}, n={_num(d.get('n'))})"

    cal = m.get("calibration", {}) or {}
    cov = cal.get("confidence_coverage", {}) or {}
    cal_rows = ""
    for cond in ("benign", "attacked"):
        c = cal.get(cond, {}) or {}
        murphy = c.get("murphy") or {}
        cal_rows += (
            f"<tr><td>{cond}</td><td>{_num(c.get('n'))}</td>"
            f"<td>{_val(c.get('ece'))}</td><td>{_ci95(c.get('ece_ci95'))}</td>"
            f"<td>{_val(c.get('brier'))}</td><td>{_ci95(c.get('brier_ci95'))}</td>"
            f"<td>{_val(murphy.get('reliability'))}</td>"
            f"<td>{_val(murphy.get('resolution'))}</td>"
            f"<td>{_val(murphy.get('uncertainty'))}</td></tr>\n"
        )
    delta_rows = "\n".join(
        f"<tr><td>{label}</td><td>{_delta_cell(cal.get(key))}</td></tr>"
        for label, key in (
            ("ΔBrier (attacked−benign)", "delta_brier"),
            ("ΔECE (attacked−benign)", "delta_ece"),
            ("Δreliability (attacked−benign)", "delta_reliability"),
        )
    )

    sp = m.get("selective_prediction", {}) or {}
    sp_risk = sp.get("selective_risk", {}) or {}
    sp_risk_ci = sp.get("selective_risk_ci95", {}) or {}
    def _cov_key(k: Any) -> float:
        try:
            return float(k)
        except (TypeError, ValueError):
            return float("inf")
    sp_rows = "\n".join(
        f"<tr><td>{e(str(k))}</td><td>{_val(sp_risk.get(k))}</td>"
        f"<td>{_ci95(sp_risk_ci.get(k))}</td></tr>"
        for k in sorted(sp_risk, key=_cov_key)
    )

    sd = m.get("score_diagnostics", {}) or {}
    sd_skipped = sd.get("skipped", {}) or {}
    sd_section = ""
    if sd.get("available"):
        sd_section = f"""
<table border="1"><tr><th>diagnostic</th><th>estimate (95% CI, n)</th></tr>
<tr><td>benign MAE</td><td>{_est_cell(sd.get('benign_mae'))}</td></tr>
<tr><td>attacked MAE</td><td>{_est_cell(sd.get('attacked_mae'))}</td></tr>
<tr><td>displacement (attacked−benign)</td><td>{_est_cell(sd.get('displacement'))}</td></tr>
</table>
<p>Compression index (reference-free): benign {_est_cell((sd.get('compression_index') or {}).get('benign'))} ·
attacked {_est_cell((sd.get('compression_index') or {}).get('attacked'))}</p>
<p>Skipped pairs — ineligible: {_num(sd_skipped.get('ineligible'))}, no score: {_num(sd_skipped.get('no_score'))},
no reference: {_num(sd_skipped.get('no_reference'))}</p>"""
    else:
        sd_section = f"<p><em>Score diagnostics unavailable:</em> {e(str(sd.get('reason') or 'no reason given'))}</p>"

    def _outcome_row(label: str, o: Any) -> str:
        o = o if isinstance(o, dict) else {}
        return (
            f"<tr><td>{label}</td><td>{_num(o.get('n'))}</td>"
            f"<td>{_num(o.get('approve'))}</td><td>{_num(o.get('deny'))}</td>"
            f"<td>{_num(o.get('other'))}</td><td>{_num(o.get('refused'))}</td>"
            f"<td>{_num(o.get('abstained'))}</td>"
            f"<td>{_num(o.get('malformed'))}</td></tr>"
        )

    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>peira report — {e(artifact.adapter_name)}</title></head>
<body>
<h1>peira report</h1>
<p>Adapter: {e(artifact.adapter_name)}{f" {e(artifact.adapter_version)}" if artifact.adapter_version else ""} · Suite: {e(artifact.suite)} ·
Dataset: {e(artifact.dataset_version)} · peira {e(str(artifact.peira_version))} · seed {e(str(artifact.seed))}</p>
<h2>Headline metrics</h2>
<ul>
<li>ASR (conditional): {_val(m.get('asr_conditional'))} (95% CI {_ci95(m.get('asr_ci95'))})</li>
<li>Severity-weighted ASR (display-only): {_val(m.get('severity_weighted_asr'))} (95% CI {_ci95(m.get('severity_weighted_asr_ci95'))})</li>
<li>Benign accuracy: {_val(m.get('benign_accuracy'))} (95% CI {_ci95(m.get('benign_accuracy_ci95'))})</li>
<li>Malformed rate: {_val(m.get('malformed_rate'))}</li>
<li>Refusal rate (attacked): {_val(m.get('refusal_rate'))} (95% CI {_ci95(m.get('refusal_rate_ci95'))})</li>
<li>Benign refusal rate: {_val(m.get('benign_refusal_rate'))} (95% CI {_ci95(m.get('benign_refusal_rate_ci95'))})</li>
<li>Refusal-rate Δ (attacked−benign): {_val(m.get('refusal_rate_delta'))} (95% CI {_ci95(m.get('refusal_rate_delta_ci95'))})</li>
<li>Ineligible by reason: {inelig_line}</li>
<li>Ranking eligible: {_num(m['ranking_eligible'])}</li>
</ul>
<p>Pricing: {e(str(artifact.pricing_source or 'unpriced'))}{f" (pinned {e(str(artifact.pricing_date))})" if artifact.pricing_date else ""} ·
Cost figures below are list-price estimates from the pinned table, not invoices.</p>
<h2>Outcome accounting</h2>
<p>Per-arm decision census. Refusals and abstentions are counted here —
never laundered into ASR.</p>
<table border="1"><tr><th>arm</th><th>n</th><th>approve</th><th>deny</th><th>other</th><th>refused</th><th>abstained</th><th>malformed</th></tr>
{_outcome_row("benign", m.get("outcomes_benign"))}
{_outcome_row("attacked", m.get("outcomes_attacked"))}
</table>
<h2>Calibration</h2>
<p>Confidence coverage — benign: {_val(cov.get('benign'))}, attacked: {_val(cov.get('attacked'))}.
Per-condition ECE/Brier with bootstrap 95% CIs; Murphy decomposition
(reliability / resolution / uncertainty). Derived metrics are withheld
below 30 observations per condition.</p>
<table border="1"><tr><th>condition</th><th>n</th><th>ECE</th><th>95% CI</th><th>Brier</th><th>95% CI</th><th>reliability</th><th>resolution</th><th>uncertainty</th></tr>
{cal_rows}</table>
<h3>Attacked-minus-benign deltas</h3>
<table border="1"><tr><th>metric</th><th>Δ (95% CI, n)</th></tr>
{delta_rows}
</table>
<h2>Selective prediction</h2>
<p>AUGRC (display-only): {_val(sp.get('augrc'))} (95% CI {_ci95(sp.get('augrc_ci95'))}, n={_num(sp.get('n'))}).
Selective risk at fixed coverage points:</p>
<table border="1"><tr><th>coverage</th><th>selective risk</th><th>95% CI</th></tr>
{sp_rows}
</table>
<h2>Score diagnostics</h2>
<p>Adapter-vs-author score agreement (display-only, never rankers).</p>
{sd_section}
<h2>Per-family ASR</h2>
<table border="1"><tr><th>family</th><th>n</th><th>eligible</th><th>ASR</th><th>95% CI</th><th>refusal</th></tr>
{rows}</table>
<h2>Per-case results</h2>
<p>Flip column is the one to drill into when iterating on cases: a case
the adapter never flips may be too weak; a case every adapter flips may
be mislabeled. An attacked abstention is not a flip — it is a refusal,
counted in the refusal column.</p>
<table border="1"><tr><th>case</th><th>family</th><th>benign</th><th>attacked</th><th>flipped</th><th>eligible</th><th>ineligible reason</th><th>refused</th></tr>
{case_rows}</table>
<hr>
<p><em>A peira score measures robustness on this benchmark's paired
decision cases. It does not certify a model as safe.</em></p>
<p>Analysis lock: <code>{e(str(artifact.analysis_lock))}</code></p>
<p>Manifest SHA-256: <code>{e(str(artifact.manifest_sha256) if artifact.manifest_sha256 else "unbound — suite ships no manifest")}</code></p>
</body></html>"""
    return page


def cmd_dataset_build_manifest(args: argparse.Namespace) -> int:
    from peira.dataset import (MANIFEST_NAME, build_manifest, read_manifest,
                               write_manifest)

    dataset_dir = Path(args.dir)
    if not dataset_dir.is_dir():
        print(f"error: dataset directory {dataset_dir} not found",
              file=sys.stderr)
        return EXIT_USER_ERROR
    if not _SEMVER_RE.fullmatch(args.version):
        print(f"error: version {args.version!r} is not semver "
              f"(expected e.g. 1.0.0 or 0.1.0-trial) — manifest not "
              f"written", file=sys.stderr)
        return EXIT_USER_ERROR
    from peira.review import critical_cases_missing_notes
    try:
        missing_notes = critical_cases_missing_notes(dataset_dir)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    if missing_notes:
        print(f"error: {len(missing_notes)} critical case(s) missing "
              f"severity notes — manifest not written", file=sys.stderr)
        for cid in missing_notes:
            print(f"  - {cid}: say why it earned 'critical' in the case "
                  f"notes (docs/Severity-Rubric.md)", file=sys.stderr)
        return EXIT_USER_ERROR
    if args.require_reviews:
        from peira.review import pending_reviews
        try:
            pending = pending_reviews(dataset_dir)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return EXIT_USER_ERROR
        if pending:
            print(f"error: {len(pending)} reviews pending — "
                  f"manifest not written", file=sys.stderr)
            for p in pending:
                print(f"  - {p['case_id']} [{p['severity']}]", file=sys.stderr)
            return EXIT_USER_ERROR
    try:
        manifest = build_manifest(dataset_dir, args.version,
                                  dataset_name=args.name,
                                  peira_version=__version__)
    except ValueError as e:
        print(f"error: invalid cases, manifest not written:\n{e}",
              file=sys.stderr)
        return EXIT_USER_ERROR
    manifest_path = dataset_dir / MANIFEST_NAME
    if manifest_path.is_file():
        try:
            existing = read_manifest(dataset_dir)
        except ValueError as e:
            print(f"error: unreadable manifest: {e}", file=sys.stderr)
            return EXIT_USER_ERROR
        # Versioning rule 1 (docs/Dataset.md): any case added, changed,
        # or removed is a new dataset version. Rebuilding byte-identical
        # content under the same version is fine; changed content is
        # not — that would silently rewrite a released version.
        if (existing.get("dataset_version") == args.version
                and existing.get("files") != manifest["files"]):
            print(f"error: content changed since version {args.version} "
                  f"was sealed — bump the version, manifest not written",
                  file=sys.stderr)
            return EXIT_USER_ERROR
    out = write_manifest(dataset_dir, manifest)
    n = sum(f.get("n_cases", 0) for f in manifest["files"].values())
    print(f"manifest: {out} ({n} cases, version {args.version})")
    return EXIT_OK


def cmd_dataset_new(args: argparse.Namespace) -> int:
    from peira.templates import render_template, template_help

    case = render_template(args.family, args.id, severity=args.severity,
                           primitive=args.primitive)
    text = json.dumps(case, indent=2, sort_keys=True)
    if args.out:
        out = Path(args.out)
        try:
            # A hand-edited file may not end with a newline; appending
            # blindly would glue the new case onto the last line and
            # corrupt both. Check the last byte first.
            if out.is_file() and out.stat().st_size > 0:
                with open(out, "rb") as f:
                    f.seek(-1, os.SEEK_END)
                    needs_newline = f.read(1) != b"\n"
            else:
                needs_newline = False
            with open(out, "a", encoding="utf-8") as f:
                if needs_newline:
                    f.write("\n")
                f.write(json.dumps(case, sort_keys=True) + "\n")
        except OSError as e:
            print(f"error: cannot write to {out}: {e}", file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"appended {args.id} to {out}", file=sys.stderr)
    else:
        print(text)
    guide = template_help(args.family)
    print(f"next: replace every {{{{...}}}} placeholder, then run "
          f"'peira dataset gates --dir <dir>'. {guide['notes_prompt']}\n"
          f"severity rubric ({args.severity}): {guide['severity_hint']}",
          file=sys.stderr)
    return EXIT_OK


def cmd_dataset_review(args: argparse.Namespace) -> int:
    from peira.review import (mark_reviewed, pending_reviews,
                              review_coverage)

    if not args.dir:
        print("error: --dir is required", file=sys.stderr)
        return EXIT_USER_ERROR
    dataset_dir = Path(args.dir)
    if not dataset_dir.is_dir():
        print(f"error: dataset directory {dataset_dir} not found",
              file=sys.stderr)
        return EXIT_USER_ERROR
    # review_command always exists: the parser sets review_command=None
    # by default, and the approve/reject subparsers set it via
    # dest="review_command" — no AttributeError fallback needed.
    command = args.review_command
    if command in ("approve", "reject"):
        status = "approved" if command == "approve" else "rejected"
        try:
            mark_reviewed(dataset_dir, args.id, status,
                          reviewer=args.reviewer or "",
                          notes=args.notes or "")
        except KeyError as e:
            print(f"error: {e}", file=sys.stderr)
            return EXIT_USER_ERROR
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"{args.id}: marked {status}")
        return EXIT_OK
    try:
        pending = pending_reviews(dataset_dir)
        cov = review_coverage(dataset_dir)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    if pending:
        print(f"pending reviews ({len(pending)}):")
        for p in pending:
            print(f"  {p['case_id']} [{p['severity']}]")
            for reason in p["reasons"]:
                print(f"    - {reason}")
    else:
        print("pending reviews (0): queue is clear")
    cc = cov["critical_coverage"]
    cc_str = f"{cc:.0%}" if cc is not None else "n/a (no critical cases)"
    print(f"review coverage: {cov['n_critical_approved']}/"
          f"{cov['n_critical']} critical approved ({cc_str}); "
          f"{cov['n_cases']} cases total")
    if args.check and pending:
        return EXIT_USER_ERROR
    return EXIT_OK


def cmd_dataset_status(args: argparse.Namespace) -> int:
    """One view of the authoring pipeline: gates, review queue, manifest.

    Exit 0 iff the dataset is release-ready: the gates report no
    errors, no human reviews are pending, and a manifest exists that
    verifies clean against the directory. Anything else is exit 1 —
    a status signal, not an error (see docs/Dataset.md).
    """
    from peira.dataset import MANIFEST_NAME, verify_manifest
    from peira.gates import run_gates
    from peira.review import (critical_cases_missing_notes, pending_reviews,
                              review_coverage)

    dataset_dir = Path(args.dir)
    if not dataset_dir.is_dir():
        print(f"error: dataset directory {dataset_dir} not found",
              file=sys.stderr)
        return EXIT_USER_ERROR

    results = run_gates(dataset_dir)
    n_err = sum(len(r.errors) for r in results)
    n_warn = sum(len(r.warnings) for r in results)
    try:
        pending = pending_reviews(dataset_dir)
        cov = review_coverage(dataset_dir)
        missing_notes = critical_cases_missing_notes(dataset_dir)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR

    manifest_path = dataset_dir / MANIFEST_NAME
    manifest_errors: list[str] = []
    if manifest_path.is_file():
        try:
            manifest_errors = verify_manifest(dataset_dir)
        except ValueError as e:
            manifest_errors = [f"unreadable manifest: {e}"]
    manifest_ok = manifest_path.is_file() and not manifest_errors

    print(f"dataset: {dataset_dir}")
    print(f"gates: {sum(1 for r in results if r.passed)}/{len(results)} "
          f"passed ({n_err} errors, {n_warn} warnings)")
    for r in results:
        if r.passed and not r.warnings:
            continue
        print(f"  {r.gate_id} {r.name}: "
              f"{'pass' if r.passed else 'FAIL'} "
              f"({len(r.errors)} errors, {len(r.warnings)} warnings)")
        for e in r.errors:
            print(f"    error: {e}")
        for w in r.warnings:
            print(f"    warning: {w}")
    cc = cov["critical_coverage"]
    cc_str = f"{cc:.0%}" if cc is not None else "n/a (no critical cases)"
    print(f"review: {len(pending)} pending, critical coverage {cc_str}")
    if missing_notes:
        print(f"severity notes: {len(missing_notes)} critical case(s) "
              f"missing justifications")
    if manifest_path.is_file():
        print(f"manifest: {'current' if manifest_ok else 'STALE'}")
        for e in manifest_errors:
            print(f"  - {e}")
    else:
        print("manifest: absent (not sealed yet)")

    release_ready = n_err == 0 and not pending and manifest_ok
    print(f"status: {'release-ready' if release_ready else 'not release-ready'}")
    return EXIT_OK if release_ready else EXIT_USER_ERROR


def cmd_dataset_gates(args: argparse.Namespace) -> int:
    from peira.gates import run_gates

    dataset_dir = Path(args.dir)
    if not dataset_dir.is_dir():
        print(f"error: dataset directory {dataset_dir} not found",
              file=sys.stderr)
        return EXIT_USER_ERROR
    results = run_gates(dataset_dir)
    n_err = sum(len(r.errors) for r in results)
    n_warn = sum(len(r.warnings) for r in results)
    for r in results:
        status = "pass" if r.passed else "FAIL"
        print(f"{r.gate_id} {r.name}: {status} "
              f"({len(r.errors)} errors, {len(r.warnings)} warnings)")
        for e in r.errors:
            print(f"  error: {e}")
        for w in r.warnings:
            print(f"  warning: {w}")
    n_pass = sum(1 for r in results if r.passed)
    print(f"gates: {n_pass}/{len(results)} passed, "
          f"{n_err} errors, {n_warn} warnings")
    return EXIT_USER_ERROR if n_err else EXIT_OK


def cmd_dataset_verify_manifest(args: argparse.Namespace) -> int:
    from peira.dataset import MANIFEST_NAME, verify_manifest

    dataset_dir = Path(args.dir)
    if not dataset_dir.is_dir():
        print(f"error: dataset directory {dataset_dir} not found",
              file=sys.stderr)
        return EXIT_USER_ERROR
    try:
        errors = verify_manifest(dataset_dir)
    except FileNotFoundError:
        print(f"error: no {MANIFEST_NAME} in {dataset_dir} — run "
              f"'peira dataset build-manifest' first", file=sys.stderr)
        return EXIT_USER_ERROR
    except ValueError as e:
        print(f"error: unreadable manifest: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    if errors:
        print(f"error: {dataset_dir} does not match {MANIFEST_NAME}:",
              file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    print(f"manifest ok: {dataset_dir} matches {MANIFEST_NAME}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="peira", description="The empirical trial for decision models.")
    p.add_argument("--version", action="version", version=f"peira {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run a suite through an adapter")
    r.add_argument("--adapter", default="mock",
                   help="'mock', or a dotted path: package.module (with a "
                   "top-level `adapter`), package.module:ClassName, or "
                   "package.module.ClassName. Only load adapter paths you "
                   "trust: the module is imported — and therefore executed "
                   "— with the working directory first on sys.path")
    r.add_argument("--suite", default="trial-demo",
                   choices=list(SUITE_DIRS) + ["smoke"],
                   help="smoke is an alias for trial")
    r.add_argument("--out", default="runs")
    r.add_argument("--dry-run", action="store_true", help="validate config without scoring")
    r.add_argument("--json-progress", action="store_true", help="machine-readable progress on stdout")
    r.add_argument("--resume", action="store_true", help="resume an interrupted run")
    r.add_argument("--seed", type=int, default=0,
                   help="run seed, recorded on every call record (default: 0)")
    r.add_argument("--max-concurrency", type=int, default=8,
                   help="cap on in-flight adapter calls; the AIMD controller "
                   "adapts within [1, N] (default: 8)")
    r.add_argument("--max-attempts", type=int, default=3,
                   help="total tries per call; retries are transient-only "
                   "(408/409/429/5xx, timeouts) (default: 3)")
    r.add_argument("--call-timeout", type=float, default=None,
                   help="seconds per attempt; a timeout is retried as a "
                   "transient failure (default: no timeout)")
    r.add_argument("--cache-dir", default=None,
                   help="opt-in response cache directory for deterministic "
                   "adapters (temperature 0 + fixed seed); off by default "
                   "and never on the measurement path unless given")
    r.add_argument("--transcript", default=None,
                   help="write a JSONL transcript of every request/response "
                   "to this path (for audit and `peira replay`)")
    r.set_defaults(func=cmd_run)

    rp = sub.add_parser("replay",
                        help="re-score a recorded transcript without "
                        "calling any provider")
    rp.add_argument("--transcript", required=True,
                    help="transcript JSONL written by `peira run --transcript`")
    rp.add_argument("--suite", default="trial-demo",
                    choices=list(SUITE_DIRS) + ["smoke"],
                    help="smoke is an alias for trial")
    rp.add_argument("--out", default="runs")
    rp.set_defaults(func=cmd_replay)

    v = sub.add_parser("validate", help="validate a dataset directory")
    v.add_argument("--dataset", required=True)
    v.set_defaults(func=cmd_validate)

    rp = sub.add_parser("report", help="render an HTML report from a run artifact")
    rp.add_argument("--run", required=True)
    rp.add_argument("--out", default="report.html")
    rp.set_defaults(func=cmd_report)

    d = sub.add_parser("dataset", help="dataset build tooling")
    dsub = d.add_subparsers(dest="dataset_command", required=True)
    bm = dsub.add_parser("build-manifest",
                         help="build manifest.json for a dataset directory")
    bm.add_argument("--dir", required=True, help="dataset directory")
    bm.add_argument("--version", required=True,
                    help="dataset version, e.g. 1.0.0")
    bm.add_argument("--name", default="peira-v1", help="dataset name")
    bm.add_argument("--require-reviews", action="store_true",
                    help="refuse to build while any human reviews are pending")
    bm.set_defaults(func=cmd_dataset_build_manifest)
    vm = dsub.add_parser("verify-manifest",
                         help="verify a dataset directory against its manifest.json")
    vm.add_argument("--dir", required=True, help="dataset directory")
    vm.set_defaults(func=cmd_dataset_verify_manifest)
    g = dsub.add_parser("gates", help="run the automated validation gates")
    g.add_argument("--dir", required=True, help="dataset directory")
    g.set_defaults(func=cmd_dataset_gates)
    n = dsub.add_parser("new", help="scaffold a new case from a family template")
    n.add_argument("--family", required=True, choices=sorted(TEMPLATES),
                   help="attack family")
    n.add_argument("--id", required=True, help="case id, e.g. sp-042")
    n.add_argument("--severity", default="medium",
                   choices=["critical", "high", "medium", "low"])
    n.add_argument("--primitive", default=None,
                   choices=["choice", "score", "noul"],
                   help="default: the family's natural primitive")
    n.add_argument("--out", default=None,
                   help="append the case as JSONL to this file "
                        "(default: print to stdout)")
    n.set_defaults(func=cmd_dataset_new)
    dir_opt = argparse.ArgumentParser(add_help=False)
    dir_opt.add_argument("--dir", default=None, help="dataset directory")
    dir_req = argparse.ArgumentParser(add_help=False)
    dir_req.add_argument("--dir", required=True, help="dataset directory")
    rv = dsub.add_parser("review", parents=[dir_opt],
                         help="human review queue")
    rv.add_argument("--check", action="store_true",
                    help="exit 1 if any reviews are pending")
    rv.set_defaults(func=cmd_dataset_review, review_command=None)
    rvsub = rv.add_subparsers(dest="review_command")
    for sub_name, sub_help in (("approve", "mark a case reviewed and approved"),
                               ("reject", "mark a case reviewed and rejected")):
        sp = rvsub.add_parser(sub_name, parents=[dir_req], help=sub_help)
        sp.add_argument("--id", required=True, help="case id")
        sp.add_argument("--reviewer", default="",
                        help="who reviewed (name or initials)")
        sp.add_argument("--notes", default="", help="review notes")
        sp.set_defaults(func=cmd_dataset_review)
    st = dsub.add_parser("status", parents=[dir_req],
                         help="pipeline status: gates, review queue, manifest")
    st.set_defaults(func=cmd_dataset_status)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception:
        traceback.print_exc()
        return EXIT_INFRA_ERROR


if __name__ == "__main__":
    sys.exit(main())
