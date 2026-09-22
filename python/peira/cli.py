"""peira CLI: run evaluations, validate datasets, render reports.

Exit codes: 0 clean, 1 user error (bad config/adapter), 2 infrastructure
error (OOM, network, crash).
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from peira import __version__
from peira.adapters.mock import MockAdapter
from peira.artifacts import RunArtifact
from peira.runner import SUITE_DIRS, load_cases, run_suite

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_INFRA_ERROR = 2


def _repo_root() -> Path:
    # python/peira/cli.py -> repo root is three levels up.
    return Path(__file__).resolve().parents[2]


def _get_adapter(name: str):
    if name == "mock":
        return MockAdapter()
    raise ValueError(f"unknown adapter: {name!r} (available: mock)")


def cmd_run(args: argparse.Namespace) -> int:
    root = _repo_root()
    try:
        adapter = _get_adapter(args.adapter)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR

    if args.suite not in SUITE_DIRS:
        print(f"error: unknown suite {args.suite!r} (available: {', '.join(SUITE_DIRS)})",
              file=sys.stderr)
        return EXIT_USER_ERROR
    suite_dir = root / SUITE_DIRS[args.suite]
    if not suite_dir.exists():
        print(f"error: suite directory {suite_dir} not found", file=sys.stderr)
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
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print(f"dry run: {len(cases)} cases, adapter={adapter.name}, "
              f"suite={args.suite} — config valid, nothing scored.")
        return EXIT_OK

    already_done: set[str] = set()
    partial_path = out_dir / f"{args.adapter}-{args.suite}.partial.json"
    if args.resume and partial_path.exists():
        try:
            partial = RunArtifact.from_json(partial_path.read_text())
            already_done = {r["case_id"] for r in partial.results}
            print(f"resuming: {len(already_done)} cases already done, "
                  f"{len(cases) - len(already_done)} remaining.")
        except Exception as e:
            print(f"warning: could not read partial run ({e}); starting fresh.",
                  file=sys.stderr)

    def progress(i: int, total: int) -> None:
        if args.json_progress:
            print(json.dumps({"event": "progress", "done": i, "total": total}),
                  flush=True)
        elif i == 1 or i == total or i % 50 == 0:
            print(f"  [{i}/{total}]", file=sys.stderr, flush=True)

    try:
        artifact = run_suite(
            adapter, cases, args.suite, "0.1.0-demo",
            progress=progress, already_done=already_done,
        )
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return EXIT_INFRA_ERROR
    except Exception:
        traceback.print_exc()
        return EXIT_INFRA_ERROR

    out_path = out_dir / f"{args.adapter}-{args.suite}.json"
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
    run_path = Path(args.run)
    if not run_path.exists():
        print(f"error: {run_path} not found", file=sys.stderr)
        return EXIT_USER_ERROR
    artifact = RunArtifact.from_json(run_path.read_text())
    if not artifact.verify():
        print("warning: analysis lock mismatch — artifact was modified after sealing.",
              file=sys.stderr)
    m = artifact.metrics
    rows = "\n".join(
        f"<tr><td>{fam}</td><td>{v['n']}</td><td>{v['asr']}</td>"
        f"<td>{v['asr_ci95'][0]}–{v['asr_ci95'][1]}</td></tr>"
        for fam, v in sorted(m["per_family"].items())
    )
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>peira report — {artifact.adapter_name}</title></head>
<body>
<h1>peira report</h1>
<p>Adapter: {artifact.adapter_name} · Suite: {artifact.suite} ·
Dataset: {artifact.dataset_version} · peira {artifact.peira_version}</p>
<ul>
<li>ASR (conditional): {m['asr_conditional']} (95% CI {m['asr_ci95'][0]}–{m['asr_ci95'][1]})</li>
<li>Benign accuracy: {m['benign_accuracy']} (95% CI {m['benign_accuracy_ci95'][0]}–{m['benign_accuracy_ci95'][1]})</li>
<li>Malformed rate: {m['malformed_rate']}</li>
<li>Ranking eligible: {m['ranking_eligible']}</li>
</ul>
<h2>Per-family ASR</h2>
<table border="1"><tr><th>family</th><th>n</th><th>ASR</th><th>95% CI</th></tr>
{rows}</table>
<hr>
<p><em>A peira score measures robustness on this benchmark's paired
decision cases. It does not certify a model as safe.</em></p>
<p>Analysis lock: <code>{artifact.analysis_lock}</code></p>
</body></html>"""
    out = Path(args.out)
    out.write_text(html)
    print(f"report: {out}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="peira", description="The empirical trial for decision models.")
    p.add_argument("--version", action="version", version=f"peira {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run a suite through an adapter")
    r.add_argument("--adapter", default="mock")
    r.add_argument("--suite", default="trial-demo", choices=list(SUITE_DIRS))
    r.add_argument("--out", default="runs")
    r.add_argument("--dry-run", action="store_true", help="validate config without scoring")
    r.add_argument("--json-progress", action="store_true", help="machine-readable progress on stdout")
    r.add_argument("--resume", action="store_true", help="resume an interrupted run")
    r.set_defaults(func=cmd_run)

    v = sub.add_parser("validate", help="validate a dataset directory")
    v.add_argument("--dataset", required=True)
    v.set_defaults(func=cmd_validate)

    rp = sub.add_parser("report", help="render an HTML report from a run artifact")
    rp.add_argument("--run", required=True)
    rp.add_argument("--out", default="report.html")
    rp.set_defaults(func=cmd_report)
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
