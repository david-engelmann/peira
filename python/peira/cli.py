"""peira CLI: run evaluations, validate datasets, render reports.

Exit codes: 0 clean, 1 user error (bad config/adapter), 2 infrastructure
error (OOM, network, crash), 3 run completed but ranking-ineligible
(eligibility notes are warnings, not failures).
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from peira import __version__
from peira.adapters.mock import MockAdapter
from peira.artifacts import RunArtifact
from peira.metrics import PerCaseResult
from peira.runner import SUITE_DIRS, load_cases, run_suite, validate_adapter

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_INFRA_ERROR = 2
EXIT_GATE_NOTE = 3  # ran fine, but the run is not ranking-eligible


def _repo_root() -> Path:
    # python/peira/cli.py -> repo root is three levels up.
    return Path(__file__).resolve().parents[2]


def _get_adapter(name: str):
    """Load an adapter by name or dotted path.
    
    - "mock" → MockAdapter (built-in)
    - "package.module:ClassName" → import and instantiate
    - "package.module.ClassName" → import and instantiate
    
    The adapter class must subclass BaseAdapter and take no constructor args.
    """
    if name == "mock":
        adapter = MockAdapter()
        adapter_errors = validate_adapter(adapter)
        if adapter_errors:  # pragma: no cover — internal invariant
            raise ValueError(
                f"built-in mock adapter is invalid: {'; '.join(adapter_errors)}"
            )
        return adapter
    
    # Dotted path: package.module:ClassName or package.module.ClassName
    if ":" in name:
        module_path, class_name = name.rsplit(":", 1)
    elif "." in name:
        module_path, class_name = name.rsplit(".", 1)
    else:
        raise ValueError(
            f"unknown adapter: {name!r} (available: mock, or a dotted path "
            f"like 'mymodule:MyAdapter')"
        )
    
    try:
        import importlib
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise ValueError(
            f"cannot import adapter module {module_path!r}: {e}"
        ) from e
    
    try:
        cls = getattr(module, class_name)
    except AttributeError:
        raise ValueError(
            f"module {module_path!r} has no class {class_name!r}"
        )
    
    # Instantiate — then validate the interface up front so a broken
    # adapter fails fast with a clear error instead of failing mid-run.
    try:
        adapter = cls()
    except Exception as e:
        raise ValueError(
            f"cannot instantiate {class_name!r}: {e}"
        ) from e
    adapter_errors = validate_adapter(adapter)
    if adapter_errors:
        raise ValueError(
            f"adapter {class_name!r} has an invalid interface: "
            f"{'; '.join(adapter_errors)}"
        )
    return adapter


def cmd_run(args: argparse.Namespace) -> int:
    root = _repo_root()
    try:
        adapter = _get_adapter(args.adapter)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR

    suite = args.suite
    if suite == "smoke":
        suite = "trial"  # smoke is the Trial alias (§19.10)
    if suite not in SUITE_DIRS:
        print(f"error: unknown suite {args.suite!r} (available: trial-demo, trial/smoke)",
              file=sys.stderr)
        return EXIT_USER_ERROR
    suite_dir = root / SUITE_DIRS[suite]
    if not suite_dir.exists():
        print(f"error: suite directory {suite_dir} not found "
              f"(the real Trial suite lands with dataset v1; "
              f"use --suite trial-demo for now)", file=sys.stderr)
        return EXIT_USER_ERROR

    try:
        cases = load_cases(suite_dir)
    except ValueError as e:
        print(f"error: invalid case data: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    if not cases:
        print(f"error: no cases found in {suite_dir}", file=sys.stderr)
        return EXIT_USER_ERROR

    # Reject non-finite and non-positive timeouts: NaN slips past `<= 0`
    # (nan <= 0 is False), and inf would silently disable the timeout.
    import math
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        print(f"error: --timeout must be a finite positive number of seconds "
              f"(got {args.timeout})",
              file=sys.stderr)
        return EXIT_USER_ERROR

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print(f"dry run: {len(cases)} cases, adapter={adapter.name}, "
              f"suite={args.suite} — config valid, nothing scored.")
        return EXIT_OK

    already_done: set[str] = set()
    prior_results: list[PerCaseResult] = []
    partial_path = out_dir / f"{args.adapter}-{suite}.partial.json"
    if args.resume and partial_path.exists():
        try:
            partial = RunArtifact.from_json(partial_path.read_text())
        except Exception as e:
            print(f"warning: could not read partial run ({e}); starting fresh.",
                  file=sys.stderr)
        else:
            # P0-2: never trust an unverified partial. The analysis lock must
            # be intact and the partial must belong to this exact run —
            # otherwise forged results could be laundered into a sealed
            # artifact via --resume.
            if not partial.verify():
                print(f"error: partial run {partial_path} failed analysis-lock "
                      f"verification — it was modified or corrupted; delete it "
                      f"or re-run without --resume.", file=sys.stderr)
                return EXIT_USER_ERROR
            if (partial.adapter_name != adapter.name
                    or partial.adapter_version != getattr(adapter, "version", "")
                    or partial.suite != suite
                    or partial.dataset_version != "0.1.0-demo"):
                print(f"error: partial run {partial_path} belongs to a different "
                      f"run (adapter={partial.adapter_name!r}, "
                      f"version={partial.adapter_version!r}, "
                      f"suite={partial.suite!r}, "
                      f"dataset={partial.dataset_version!r}); refusing to resume.",
                      file=sys.stderr)
                return EXIT_USER_ERROR
            try:
                prior_results = [PerCaseResult(**r) for r in partial.results]
            except Exception as e:
                print(f"warning: could not read partial run ({e}); starting fresh.",
                      file=sys.stderr)
                prior_results = []
            else:
                case_ids = {c.case_id for c in cases}
                foreign = [r for r in prior_results if r.case_id not in case_ids]
                if foreign:
                    print(f"warning: ignoring {len(foreign)} foreign case ID(s) "
                          f"in partial run (not in suite {suite}).",
                          file=sys.stderr)
                seen: set[str] = set()
                deduped: list[PerCaseResult] = []
                for r in prior_results:
                    if r.case_id in case_ids and r.case_id not in seen:
                        seen.add(r.case_id)
                        deduped.append(r)
                if len(deduped) < len(prior_results) - len(foreign):
                    print(f"warning: ignoring "
                          f"{len(prior_results) - len(foreign) - len(deduped)} "
                          f"duplicate case ID(s) in partial run.", file=sys.stderr)
                prior_results = deduped
                already_done = {r.case_id for r in prior_results}
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
            adapter, cases, suite, "0.1.0-demo",
            progress=progress, already_done=already_done,
            prior_results=prior_results, partial_path=partial_path,
            timeout=args.timeout,
        )
    except KeyboardInterrupt:
        print("\ninterrupted — partial run saved; re-run with --resume.",
              file=sys.stderr)
        return EXIT_INFRA_ERROR
    except Exception:
        traceback.print_exc()
        return EXIT_INFRA_ERROR

    out_path = out_dir / f"{args.adapter}-{suite}.json"
    out_path.write_text(artifact.to_json())
    if partial_path.exists():
        partial_path.unlink()

    m = artifact.metrics
    print(f"done: {m['n_cases']} cases")
    print(f"  ASR (conditional): {m['asr_conditional']} "
          f"95% CI {m['asr_ci95']}")
    print(f"  benign accuracy:   {m['benign_accuracy']} "
          f"95% CI {m['benign_accuracy_ci95']}")
    print(f"  malformed rate:    {m['malformed_rate']}")
    print(f"  ranking eligible:  {m['ranking_eligible']}"
          + (f" ({'; '.join(m['eligibility_notes'])})" if m['eligibility_notes'] else ""))
    print(f"artifact: {out_path}")
    print(f"analysis lock: {artifact.analysis_lock[:16]}…")
    if not m["ranking_eligible"]:
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
        with open(path) as f:
            for lineno, line in enumerate(f, 1):
                if not line.strip():
                    continue
                n += 1
                errors = validate_case_dict(json.loads(line))
                if errors:
                    bad += 1
                    print(f"{path}:{lineno}: {'; '.join(errors)}")
    print(f"validated {n} cases, {bad} invalid")
    return EXIT_USER_ERROR if bad else EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    import html as html_lib
    
    run_path = Path(args.run)
    if not run_path.exists():
        print(f"error: {run_path} not found", file=sys.stderr)
        return EXIT_USER_ERROR
    artifact = RunArtifact.from_json(run_path.read_text())
    if not artifact.verify():
        print("warning: analysis lock mismatch — artifact was modified after sealing.",
              file=sys.stderr)
    m = artifact.metrics
    # SECURITY (audit H-1): escape all artifact-derived values before HTML
    # interpolation. Artifacts are shared (leaderboard submissions, PRs);
    # a malicious artifact_name could execute JS in the victim's browser.
    def esc(s: Any) -> str:
        return html_lib.escape(str(s), quote=True)
    
    rows = "\n".join(
        f"<tr><td>{esc(fam)}</td><td>{esc(v['n'])}</td><td>{esc(v['asr'])}</td>"
        f"<td>{esc(v['asr_ci95'][0])}–{esc(v['asr_ci95'][1])}</td></tr>"
        for fam, v in sorted(m["per_family"].items())
    )
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>peira report — {esc(artifact.adapter_name)}</title></head>
<body>
<h1>peira report</h1>
<p>Adapter: {esc(artifact.adapter_name)} · Suite: {esc(artifact.suite)} ·
Dataset: {esc(artifact.dataset_version)} · peira {esc(artifact.peira_version)}</p>
<ul>
<li>ASR (conditional): {esc(m['asr_conditional'])} (95% CI {esc(m['asr_ci95'][0])}–{esc(m['asr_ci95'][1])})</li>
<li>Benign accuracy: {esc(m['benign_accuracy'])} (95% CI {esc(m['benign_accuracy_ci95'][0])}–{esc(m['benign_accuracy_ci95'][1])})</li>
<li>Malformed rate: {esc(m['malformed_rate'])}</li>
<li>Ranking eligible: {esc(m['ranking_eligible'])}</li>
</ul>
<h2>Per-family ASR</h2>
<table border="1"><tr><th>family</th><th>n</th><th>ASR</th><th>95% CI</th></tr>
{rows}</table>
<hr>
<p><em>A peira score measures robustness on this benchmark's paired
decision cases. It does not certify a model as safe.</em></p>
<p>Analysis lock: <code>{esc(artifact.analysis_lock)}</code></p>
</body></html>"""
    out = Path(args.out)
    out.write_text(html)
    print(f"report: {out}")
    return EXIT_OK


def cmd_verify(args: argparse.Namespace) -> int:
    """Verify a run artifact's analysis lock.
    
    Exit 0 if the artifact is intact, 1 if it was modified after sealing.
    This is the trust mechanism behind "no post-hoc editing": the lock is
    SHA-256 over the config + results, so any change invalidates it.
    """
    run_path = Path(args.run)
    if not run_path.exists():
        print(f"error: {run_path} not found", file=sys.stderr)
        return EXIT_USER_ERROR
    try:
        artifact = RunArtifact.from_json(run_path.read_text())
    except Exception as e:
        print(f"error: cannot parse artifact: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    
    if artifact.verify():
        print(f"ok: {run_path} — analysis lock valid")
        print(f"  adapter: {artifact.adapter_name}, suite: {artifact.suite}")
        print(f"  lock: {artifact.analysis_lock[:16]}...")
        return EXIT_OK
    else:
        print(f"FAIL: {run_path} — analysis lock MISMATCH", file=sys.stderr)
        print("  artifact was modified after sealing; metrics are not trustworthy",
              file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="peira", description="The empirical trial for decision models.")
    p.add_argument("--version", action="version", version=f"peira {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run a suite through an adapter")
    r.add_argument("--adapter", default="mock")
    r.add_argument("--suite", default="trial-demo",
                   choices=list(SUITE_DIRS) + ["smoke"],
                   help="smoke is an alias for trial")
    r.add_argument("--out", default="runs")
    r.add_argument("--dry-run", action="store_true", help="validate config without scoring")
    r.add_argument("--json-progress", action="store_true", help="machine-readable progress on stdout")
    r.add_argument("--resume", action="store_true", help="resume an interrupted run")
    r.add_argument("--timeout", type=float, default=30.0,
                   help="per-decide() timeout in seconds; timed-out variants "
                        "are marked malformed (default: 30)")
    r.set_defaults(func=cmd_run)

    v = sub.add_parser("validate", help="validate a dataset directory")
    v.add_argument("--dataset", required=True)
    v.set_defaults(func=cmd_validate)

    rp = sub.add_parser("report", help="render an HTML report from a run artifact")
    rp.add_argument("--run", required=True)
    rp.add_argument("--out", default="report.html")
    rp.set_defaults(func=cmd_report)

    vf = sub.add_parser("verify", help="verify a run artifact's analysis lock")
    vf.add_argument("--run", required=True, help="path to the run artifact JSON")
    vf.set_defaults(func=cmd_verify)
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
