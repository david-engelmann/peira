"""peira CLI: run evaluations, validate datasets, render reports.

Exit codes: 0 clean, 1 user error (bad config/adapter), 2 infrastructure
error (resource, network, crash), 3 run completed but ranking-ineligible
(eligibility notes are warnings, not failures).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from pathlib import Path

from peira import __version__
from peira.adapters.mock import MockAdapter
from peira.artifacts import RunArtifact
from peira.metrics import PerCaseResult
from peira.runner import SUITE_DIRS, load_cases, run_suite, validate_partial
from peira.templates import TEMPLATES

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_INFRA_ERROR = 2
EXIT_GATE_NOTE = 3  # ran fine, but the run is not ranking-eligible


def _repo_root() -> Path:
    # python/peira/cli.py -> repo root is three levels up.
    return Path(__file__).resolve().parents[2]


def _safe_adapter_slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def _get_adapter(name: str):
    if name == "mock":
        return MockAdapter()
    return _load_dotted_adapter(name)


def _load_dotted_adapter(spec: str):
    """Load an adapter from a dotted path.

    Accepted forms:
      package.module             module-level ``adapter`` object
      package.module:ClassName   class, instantiated with no arguments
      package.module.ClassName   class, instantiated with no arguments

    The working directory is prepended to sys.path so adapters next to the
    checkout (e.g. ``examples/``) resolve when the console script is used.
    """
    import importlib

    module_name, sep, attr = spec.partition(":")
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
            raise ValueError(
                f"unknown adapter: {spec!r} (available: 'mock' or a dotted "
                f"path like 'examples.minimal_adapter')"
            ) from first_err
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
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print(f"dry run: {len(cases)} cases, adapter={adapter.name}, "
              f"suite={args.suite} — config valid, nothing scored.")
        return EXIT_OK

    already_done: set[str] = set()
    prior_results: list[PerCaseResult] = []
    slug = _safe_adapter_slug(args.adapter)
    # The dataset version is part of the analysis lock: read it from the
    # suite's manifest when one exists, so runs always bind the exact
    # dataset bytes they scored.
    dataset_version = "0.1.0-demo"
    manifest_path = suite_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            dataset_version = str(
                json.loads(manifest_path.read_text(encoding="utf-8"))
                .get("dataset_version", dataset_version)
            )
        except (OSError, ValueError) as e:
            print(f"warning: unreadable manifest at {manifest_path} ({e}); "
                  f"recording dataset_version={dataset_version!r}.",
                  file=sys.stderr)
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
                        partial, adapter, cases, suite, dataset_version)
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
        )
    except KeyboardInterrupt:
        print("\ninterrupted — partial run saved; re-run with --resume.",
              file=sys.stderr)
        return EXIT_INFRA_ERROR
    except Exception:
        traceback.print_exc()
        return EXIT_INFRA_ERROR

    out_path = out_dir / f"{slug}-{suite}.json"
    out_path.write_text(artifact.to_json())
    if partial_path.exists():
        partial_path.unlink()

    m = artifact.metrics
    print(f"done: {m['n_cases']} cases")
    print(f"  ASR (conditional): {m['asr_conditional']} "
          f"95% CI {m['asr_ci95']}")
    tsr = m["targeted_attack_success"]
    print(f"  targeted success:  {tsr if tsr is not None else 'n/a'} "
          f"(n_targeted={m['n_targeted']})")
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
        f"<tr><td>{fam}</td><td>{v['n']}</td>"
        f"<td>{v.get('n_eligible', '—')}</td>"
        f"<td>{v['asr']}</td>"
        f"<td>{v['asr_ci95'][0]}–{v['asr_ci95'][1]}</td>"
        f"<td>{v.get('targeted', '—') if v.get('targeted') is not None else '—'}</td></tr>"
        for fam, v in sorted(m["per_family"].items())
    )
    def _mark(ok: bool) -> str:
        return "✓" if ok else "✗"
    case_rows = "\n".join(
        f"<tr><td>{r.get('case_id', '?')}</td><td>{r.get('family', '?')}</td>"
        f"<td>{_mark(bool(r.get('benign_correct')))}</td>"
        f"<td>{_mark(bool(r.get('attacked_flipped')))}</td>"
        f"<td>{_mark(bool(r.get('attacked_targeted')))}</td>"
        f"<td>{_mark(not bool(r.get('malformed')))}</td></tr>"
        for r in artifact.results
    )
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>peira report — {artifact.adapter_name}</title></head>
<body>
<h1>peira report</h1>
<p>Adapter: {artifact.adapter_name}{f" {artifact.adapter_version}" if artifact.adapter_version else ""} · Suite: {artifact.suite} ·
Dataset: {artifact.dataset_version} · peira {artifact.peira_version}</p>
<ul>
<li>ASR (conditional): {m['asr_conditional']} (95% CI {m['asr_ci95'][0]}–{m['asr_ci95'][1]})</li>
<li>Benign accuracy: {m['benign_accuracy']} (95% CI {m['benign_accuracy_ci95'][0]}–{m['benign_accuracy_ci95'][1]})</li>
<li>Malformed rate: {m['malformed_rate']}</li>
<li>Ranking eligible: {m['ranking_eligible']}</li>
</ul>
<h2>Per-family ASR</h2>
<table border="1"><tr><th>family</th><th>n</th><th>eligible</th><th>ASR</th><th>95% CI</th><th>targeted</th></tr>
{rows}</table>
<h2>Per-case results</h2>
<p>✓ = benign correct / attacked flipped / reached target / well-formed.
The flip column is the one to drill into when iterating on cases: a case
the adapter never flips may be too weak; a case every adapter flips may
be mislabeled.</p>
<table border="1"><tr><th>case</th><th>family</th><th>benign ok</th><th>flipped</th><th>targeted</th><th>well-formed</th></tr>
{case_rows}</table>
<hr>
<p><em>A peira score measures robustness on this benchmark's paired
decision cases. It does not certify a model as safe.</em></p>
<p>Analysis lock: <code>{artifact.analysis_lock}</code></p>
</body></html>"""
    out = Path(args.out)
    # Explicit UTF-8: the report contains ✓/✗ glyphs, which the Windows
    # default encoding (cp1252) cannot represent.
    out.write_text(html, encoding="utf-8")
    print(f"report: {out}")
    return EXIT_OK


def cmd_dataset_build_manifest(args: argparse.Namespace) -> int:
    from peira.dataset import MANIFEST_NAME, build_manifest, write_manifest

    dataset_dir = Path(args.dir)
    if not dataset_dir.is_dir():
        print(f"error: dataset directory {dataset_dir} not found",
              file=sys.stderr)
        return EXIT_USER_ERROR
    if args.require_reviews:
        from peira.review import pending_reviews
        try:
            pending = pending_reviews(dataset_dir)
        except ValueError as e:
            print(f"error: unreadable review state: {e}", file=sys.stderr)
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
            with open(out, "a", encoding="utf-8") as f:
                f.write(json.dumps(case, sort_keys=True) + "\n")
        except OSError as e:
            print(f"error: cannot write to {out}: {e}", file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"appended {args.id} to {out}", file=sys.stderr)
    else:
        print(text)
    guide = template_help(args.family)
    print(f"next: replace every {{{{...}}}} placeholder, then run "
          f"'peira dataset gates --dir <dir>'. {guide['notes_prompt']}",
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
    try:
        command = args.review_command
    except AttributeError:
        command = None
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
            print(f"error: unreadable review state: {e}", file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"{args.id}: marked {status}")
        return EXIT_OK
    try:
        pending = pending_reviews(dataset_dir)
        cov = review_coverage(dataset_dir)
    except ValueError as e:
        print(f"error: unreadable review state: {e}", file=sys.stderr)
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
                   "package.module.ClassName")
    r.add_argument("--suite", default="trial-demo",
                   choices=list(SUITE_DIRS) + ["smoke"],
                   help="smoke is an alias for trial")
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
