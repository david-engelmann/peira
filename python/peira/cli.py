"""peira CLI: run evaluations, validate datasets, render reports.

Exit codes: 0 clean, 1 user error (bad config/adapter), 2 infrastructure
error (resource, network, crash), 3 run completed but ranking-ineligible
(eligibility notes are warnings, not failures).
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any

from peira import __version__
from peira.adapters.mock import MockAdapter
from peira.artifacts import RunArtifact
from peira.calibration import (
    confidence_source_label,
    reliability_diagram_svg,
    risk_coverage_diagram_svg,
)
from peira.dataset import atomic_write_text, verify_manifest, verify_manifest_sealed
from peira.metrics import (
    MIN_DELTA_CASES,
    MIN_NB_CASES,
    NOT_RESOLVABLE,
    PerCaseResult,
    attack_mix_curve,
    buyer_cost_at_threshold,
    resolvable,
)
from peira.runs_registry import FLIP_DIRECTIONS
from peira.runner import (
    SUITE_DIRS,
    load_cases,
    new_run_nonce,
    replay_suite,
    run_multiseed,
    run_suite,
    validate_partial,
)
from peira.stability import StabilityArtifact
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
    HTML-escaped; a hostile artifact must not smuggle markup through
    a metric value. This function never raises.
    """
    if isinstance(x, bool):
        return "True" if x else "False"
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        return f"{x:.4f}"
    if x is None:
        return "-"
    return html.escape(str(x))


def _val(x: Any) -> str:
    """Render a possibly-withheld metric value.

    ``summarize()`` returns None (never 0.0) for withheld/insufficient
    data; the report renders that as "insufficient data", never as a
    bare "0" or a silent blank. Hostile values are escaped via
    :func:`_num`; this function never raises.
    """
    return "insufficient data" if x is None else _num(x)


def _ci95(ci: Any) -> str:
    """Render a possibly-withheld 95% CI pair.

    A withheld interval (None, or a hostile non-pair) renders as
    "insufficient data": never a traceback, never markup. This
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
    Only load adapter paths you trust: the module is imported (and
    therefore executed) on load (see docs/Troubleshooting.md).
    """
    import importlib

    module_name, sep, attr = spec.partition(":")
    if not module_name:
        # import_module("") raises ValueError("Empty module name"), which
        # the ImportError handler below would miss; reject the empty
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
    unreadable manifest is not tampering; it yields the fallback label
    and an empty digest, i.e. an explicitly unbound run.
    """
    manifest_path = suite_dir / "manifest.json"
    if not manifest_path.is_file():
        return "0.1.0-demo", ""
    try:
        # Sealed read: the digest below is computed over the same bytes
        # that were verified, never a re-read that raced a swap.
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
              "was built; rebuild the manifest or restore the files."
        )
    dataset_version = str(manifest.get("dataset_version", "0.1.0-demo"))
    return dataset_version, manifest_sha256


def _print_sweep_run_summary(artifact, out_path: Path) -> None:
    """EB-35: one-line-per-family summary of a sweep run."""
    sweep = artifact.metrics["sweep"]
    n_cases = sum(
        fam["flip_budget_distribution"]["n_eligible"]
        for fam in sweep["families"].values()
    )
    print(f"done: sweep over {n_cases} eligible cases "
          f"(dimension={sweep['strength_dimension']}, "
          f"grid={sweep['budget_grid']})")
    if artifact.termination != "complete":
        print(f"  termination:     {artifact.termination} "
              f"({artifact.cases_completed}/{artifact.cases_planned} cases)")
    print(f"  spend:           ${artifact.spent_usd:.4f} "
          f"(uncapped)" if artifact.budget_usd is None else
          f"  budget:          cap ${artifact.budget_usd:.2f}, "
          f"spent ${artifact.spent_usd:.4f}")
    print(f"  artifact:        {out_path}")
    print("  hint:            `peira sweep-report "
          f"{out_path}` renders the ASR-vs-budget curves")


def _print_run_summary(artifact, out_path: Path) -> None:
    m = artifact.metrics
    from peira.conversation import CONVERSATION_SUITE_ID
    if artifact.suite == CONVERSATION_SUITE_ID:
        _print_conversation_run_summary(artifact, out_path)
        return
    if isinstance(m.get("sweep"), dict):
        _print_sweep_run_summary(artifact, out_path)
        return
    print(f"done: {m['n_cases']} cases ({m['n_eligible']} eligible)")
    if artifact.termination != "complete":
        print(f"  termination:     {artifact.termination} "
              f"({artifact.cases_completed}/{artifact.cases_planned} cases)")
    if artifact.budget_usd is not None:
        print(f"  budget:          cap ${artifact.budget_usd:.2f}, "
              f"spent ${artifact.spent_usd:.4f}")
    else:
        print(f"  spend:           ${artifact.spent_usd:.4f} (uncapped)")
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


def _print_conversation_run_summary(artifact, out_path: Path) -> None:
    """Console summary for a conversational run artifact.

    Reads the conversational metric schema sealed by
    ``peira.conversation_metrics.summarize_conversation_artifact``;
    never the single-shot keys.
    """
    m = artifact.metrics
    print(f"done: {m['n_cases']} cases ({m['n_eligible']} eligible)")
    if artifact.termination != "complete":
        print(f"  termination:     {artifact.termination} "
              f"({artifact.cases_completed}/{artifact.cases_planned} cases)")
    if artifact.budget_usd is not None:
        print(f"  budget:          cap ${artifact.budget_usd:.2f}, "
              f"spent ${artifact.spent_usd:.4f}")
    else:
        print(f"  spend:           ${artifact.spent_usd:.4f} (uncapped)")
    print(f"  flip rate:       {_val(_metric_value(m['flip_rate']))} "
          f"95% CI {_ci95(_metric_ci(m['flip_rate']))}")
    print(f"  target hit rate: {_val(m['target_hit_rate'])}")
    print(f"  mean user turns: benign {_val(m['mean_user_turns_benign'])}, "
          f"attacked {_val(m['mean_user_turns_attacked'])}")
    print(f"  intermediate malformed: "
          f"{_val(m['intermediate_malformed_rate'])}")
    print(f"  intermediate abstention: "
          f"{_val(m['intermediate_abstention_rate'])}")
    print(f"  ranking eligible:  {m['ranking_eligible']}"
          + (f" ({'; '.join(m['eligibility_notes'])})" if m['eligibility_notes'] else ""))
    print(f"artifact: {out_path}")
    print(f"analysis lock: {artifact.analysis_lock[:16]}…")


def _metric_value(triple):
    """The value of a Wilson {"value","ci_low","ci_high"} triple (or None)."""
    if isinstance(triple, dict):
        return triple.get("value")
    return None


def _metric_ci(triple):
    """The [low, high] pair of a Wilson triple (or None)."""
    if isinstance(triple, dict):
        return [triple.get("ci_low"), triple.get("ci_high")]
    return None


def _write_final_artifact(out_dir: Path, slug: str, suite: str,
                          artifact, suffix: str = "") -> Path:
    out_path = out_dir / f"{slug}-{suite}{suffix}.json"
    # Atomic write: a crash mid-write must never leave a corrupt
    # artifact behind.
    atomic_write_text(out_path, artifact.to_json())
    return out_path


def _validate_against_registry(
    value: str, valid: set[str] | dict, unknown_label: str, known_label: str
) -> list[str]:
    """Validate comma-separated ids against a registry, preserving order.

    Raises ValueError with the exact ``unknown ... (known ...: ...)``
    message shape the CLI has always used for --families validation.
    """
    wanted = [part.strip() for part in value.split(",")]
    wanted = [w for w in wanted if w]
    unknown = [w for w in wanted if w not in valid]
    if unknown:
        known = ", ".join(sorted(valid))
        raise ValueError(
            f"unknown {unknown_label}: {', '.join(unknown)} "
            f"(known {known_label}: {known})"
        )
    return list(dict.fromkeys(wanted))


def parse_family_filter(
    value: str | None, suite: str | None = None
) -> list[str] | None:
    """Parse a --families argument into validated family ids.

    Returns None when no filter was given. Raises ValueError listing
    the unknown ids (with the canonical list) otherwise. When
    ``suite`` is the conversational suite, conversational families are
    validated against the conversational registry instead; when it is
    the combo suite, pair ids are validated against the combo registry.
    """
    if value is None or not value.strip():
        return None
    from peira.families import FAMILIES, FAMILY_IDS
    from peira.schema import SUITE_IDS

    if suite == "conversational":
        from peira.conversation_schema import KNOWN_CONVERSATION_FAMILIES

        return _validate_against_registry(
            value, KNOWN_CONVERSATION_FAMILIES,
            "conversational famil(ies)", "conversational families")

    if suite == "combo":
        from peira.combo_schema import COMBO_PAIRS

        return _validate_against_registry(
            value, COMBO_PAIRS, "combo pair(s)", "combo pairs")

    wanted = [part.strip() for part in value.split(",")]
    wanted = [w for w in wanted if w]
    unknown = [w for w in wanted if w not in FAMILIES]
    if unknown:
        hint = ""
        if any(w in SUITE_IDS for w in unknown):
            hint = (" (safety_policy is a suite, not an attack family: "
                    "use --suite safety-policy instead of --families)")
        known = ", ".join(FAMILY_IDS)
        raise ValueError(
            f"unknown famil(ies): {', '.join(unknown)} "
            f"(known families: {known}){hint}"
        )
    # Dedupe, preserving order: "--families a,a" means ["a"].
    return list(dict.fromkeys(wanted))


def _budget_estimate_note(
    out_dir: Path, slug: str, suite: str, budget_usd: float,
    n_remaining: int,
) -> str:
    """Pre-run budget note: what the cap buys, from cost history.

    Looks for the newest final artifact for this adapter+suite in the
    output directory and projects ``remaining x last_per_case_mean``
    against the cap. Informational only: the hard enforcement is the
    runner's pre-dispatch gate. Never fails: no history (or an
    unreadable one) yields the honest "no history" note instead of a
    guessed number.
    """
    try:
        candidates = [
            p for p in out_dir.glob(f"{slug}-{suite}.json")
            if not p.name.endswith(".partial.json")
            and not p.name.endswith(".replay.json")
        ]
        if not candidates:
            raise FileNotFoundError("no prior artifacts")
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        d = json.loads(latest.read_text())
        spent = float(d.get("spent_usd") or 0.0)
        done = int(d.get("cases_completed") or 0)
        if spent <= 0 or done <= 0:
            raise ValueError("no priced history")
        per_case = spent / done
        estimate = per_case * n_remaining
        coverable = int(budget_usd / per_case) if per_case > 0 else 0
        verdict = (
            "covers the run" if estimate <= budget_usd
            else f"short by ~${estimate - budget_usd:.2f}"
        )
        return (
            f"budget: ${budget_usd:.2f} cap: last run for this "
            f"adapter/suite cost ~${per_case:.4f}/case "
            f"({latest.name}); ~${estimate:.2f} for {n_remaining} "
            f"remaining cases ({verdict}; ~{coverable} cases covered). "
            f"Enforcement starts after the first completed case."
        )
    except Exception:
        return (
            f"budget: ${budget_usd:.2f} cap: no priced cost history "
            f"for this adapter/suite; enforcement starts after the "
            f"first completed case (projection: spent + mean x 1.5)."
        )


def _resume_sweep_error(
    partial: Any,
    is_sweep: bool,
    sweep_grid: list[int] | None,
    sweep_dimension: str,
    partial_path: Any,
) -> str | None:
    """Sweep/single-shot resume compatibility (EB-35).

    Returns an error string when resuming ``partial`` with the current
    run's sweep settings would mix protocols, else None. A sweep
    partial resumed without ``--budget-grid`` would silently downgrade
    the remaining cases to single-shot scoring and seal an artifact
    whose ranking flags no longer mean what they say; a grid or
    dimension mismatch would silently corrupt the budget curve.
    """
    partial_grid = (partial.config or {}).get("sweep_budget_grid")
    partial_dim = (partial.config or {}).get("sweep_strength_dimension")
    if partial_grid is None:
        if is_sweep:
            return (
                f"partial run at {partial_path} is a single-shot run, "
                f"but the current run is a sweep (grid={sweep_grid} "
                f"dimension={sweep_dimension}); delete {partial_path} "
                f"or drop --budget-grid and --strength-dimension"
            )
        return None
    if not is_sweep:
        grid_text = (
            ",".join(str(b) for b in partial_grid)
            if isinstance(partial_grid, list)
            else repr(partial_grid)
        )
        return (
            f"partial run at {partial_path} is a sweep run "
            f"(grid={partial_grid} dimension={partial_dim}); resume with "
            f"--budget-grid {grid_text} "
            f"--strength-dimension {partial_dim}, or delete "
            f"{partial_path} and re-run"
        )
    if partial_grid != sweep_grid or partial_dim != sweep_dimension:
        return (
            f"partial run at {partial_path} uses grid={partial_grid} "
            f"dimension={partial_dim}, but current run uses "
            f"grid={sweep_grid} dimension={sweep_dimension}; delete "
            f"{partial_path} or re-run with the original grid and "
            f"dimension."
        )
    return None


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
        _suite_names = ", ".join(["smoke"] + sorted(SUITE_DIRS))
        print(f"error: unknown suite {args.suite!r} (available: {_suite_names})",
              file=sys.stderr)
        return EXIT_USER_ERROR
    suite_dir = root / SUITE_DIRS[suite]
    if not suite_dir.exists():
        print(f"error: suite directory {suite_dir} not found",
              file=sys.stderr)
        return EXIT_USER_ERROR

    # The conversational suite has its own case schema, loader, and
    # suite driver; every other suite uses the single-shot path.
    is_conversational = suite == "conversational"
    try:
        if is_conversational:
            from peira.conversation import load_conversation_cases
            cases = load_conversation_cases(suite_dir)
        else:
            cases = load_cases(suite_dir)
    except ValueError as e:
        print(f"error: invalid case data: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    if not cases:
        print(f"error: no cases found in {suite_dir}", file=sys.stderr)
        return EXIT_USER_ERROR
    try:
        wanted_families = parse_family_filter(
            getattr(args, "families", None), suite=suite
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    # The ranking gate is evaluated over the full suite's family
    # manifest: capture it BEFORE the --families filter, and pass it to
    # run_suite, so a subset run marks the missing families absent
    # (ranking-ineligible, exit 3) instead of silently redefining the
    # gate around the subset. Dropping a weak family can never improve
    # a rank.
    suite_families = sorted({c.family for c in cases})
    if wanted_families is not None:
        cases = [c for c in cases if c.family in wanted_families]
        if not cases:
            print(f"error: --families matched no cases in {suite_dir}",
                  file=sys.stderr)
            return EXIT_USER_ERROR
    # M-7: validate the seed count before doing any work. 1 is a
    # single run; anything else must clear the protocol minimum.
    num_seeds = getattr(args, "seeds", 1)
    if num_seeds is None:
        num_seeds = 1
    if num_seeds != 1 and num_seeds < 3:
        print(f"error: --seeds must be 1 or >= 3 (M-7 protocol minimum), "
              f"got {num_seeds}", file=sys.stderr)
        return EXIT_USER_ERROR
    if num_seeds > 1 and args.resume:
        print("error: --resume is not supported with --seeds > 1; "
              "each seed run is independent (re-run without --resume)",
              file=sys.stderr)
        return EXIT_USER_ERROR
    # EB-35: parse the sweep budget grid early so a malformed grid
    # fails before any adapter is built or any case is scored.
    sweep_grid: list[int] | None = None
    sweep_dimension = getattr(args, "strength_dimension", "attacker_queries")
    budget_grid_raw = getattr(args, "budget_grid", None)
    if budget_grid_raw is not None:
        if is_conversational:
            print("error: --budget-grid is not supported for the "
                  "conversational suite (single-shot suites only)",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        if num_seeds > 1:
            print("error: --budget-grid is not supported with --seeds > 1; "
                  "run the sweep with --seeds 1", file=sys.stderr)
            return EXIT_USER_ERROR
        from peira.sweep import (
            get_strength_dimension,
            validate_budget_grid,
        )
        try:
            get_strength_dimension(sweep_dimension)
        except ValueError as e:
            print(f"error: invalid --strength-dimension: {e}",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        try:
            sweep_grid = validate_budget_grid(
                [int(x) for x in budget_grid_raw.split(",") if x.strip()]
            )
        except ValueError as e:
            print(f"error: invalid --budget-grid: {e}", file=sys.stderr)
            return EXIT_USER_ERROR
    is_sweep = sweep_grid is not None
    if num_seeds > 1 and args.transcript:
        print("error: --transcript is not supported with --seeds > 1; "
              "each seed run is independent (run with --seeds 1 to "
              "capture a transcript)", file=sys.stderr)
        return EXIT_USER_ERROR

    def _build_mock(seed_i: int, run_nonce_i: str) -> "MockAdapter":
        # The mock's simulation script is namespaced per (seed, nonce):
        # each seed run gets its own script built under its own nonce,
        # exactly like the single-run path below. Conversational suites
        # use the conversation script builder.
        script_builder = (
            MockAdapter.script_for_conversation
            if is_conversational
            else MockAdapter.script_for
        )
        if sweep_grid is not None and not is_conversational:
            # The sweep driver spaces cases by stride = max(grid) + 1
            # and runs max(grid) attacked attempts per case (see
            # peira.sweep.run_sweep_suite). The script must use the
            # same layout: a single-shot script would answer sweep
            # calls from the wrong cases' entries and silently poison
            # the measurement.
            stride = max(sweep_grid) + 1
            script = script_builder(
                cases, seed=seed_i, run_nonce=run_nonce_i,
                dispatch_stride=stride,
                attacked_attempts=max(sweep_grid),
            )
        else:
            script = script_builder(
                cases, seed=seed_i, run_nonce=run_nonce_i
            )
        return MockAdapter(script=script)

    if isinstance(adapter, MockAdapter):
        # The mock is a test double: its simulation script is built
        # explicitly here by the harness from the loaded cases; never
        # smuggled through the adapter protocol (B2: the CallContext
        # carries no gold for the mock to read). The nonce namespaces
        # this execution's call ids; the script must use the same one
        # the runner will (fresh per execution, so runs are unlinkable
        # even with the same seed).
        run_nonce = new_run_nonce()
        adapter = _build_mock(args.seed, run_nonce)
        # Multi-seed runs rebuild the mock per seed inside
        # run_multiseed via this hook.
        build_adapter = _build_mock if num_seeds > 1 else None
    else:
        run_nonce = new_run_nonce()
        # M-7: seed-sensitive adapters (structured LLM baselines) must
        # be re-seeded per run: reusing one instance would send the
        # same provider sampling seed on every seed run, invalidating
        # the stability measurement. with_seed shares the read-only
        # client and re-keys the cache namespace.
        if hasattr(adapter, "with_seed"):
            _base_adapter = adapter

            def _build_seeded(seed_i: int, run_nonce_i: str,
                              _base=_base_adapter):
                return _base.with_seed(seed_i)

            build_adapter = _build_seeded
        else:
            build_adapter = None

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
    for flag in ("rlimit_cpu_seconds", "rlimit_as_mb", "rlimit_fsize_mb"):
        value = getattr(args, flag, None)
        if value is not None and value <= 0:
            print(f"error: --{flag.replace('_', '-')} must be > 0 "
                  f"(got {value})", file=sys.stderr)
            return EXIT_USER_ERROR
    if getattr(args, "rlimit_nproc", None) is not None:
        if args.rlimit_nproc < 1:
            print(f"error: --rlimit-nproc must be >= 1 "
                  f"(got {args.rlimit_nproc})", file=sys.stderr)
            return EXIT_USER_ERROR
    budget_usd = getattr(args, "budget_usd", None)
    if budget_usd is not None and not budget_usd > 0:
        # NaN fails the > 0 comparison: a NaN cap is not a cap.
        print(f"error: --budget-usd must be > 0 "
              f"(got {budget_usd})", file=sys.stderr)
        return EXIT_USER_ERROR
    item_timeout = getattr(args, "item_timeout", None)
    if item_timeout is not None and not item_timeout > 0:
        # NaN fails the > 0 comparison: a NaN budget is not a budget.
        print(f"error: --item-timeout must be > 0 "
              f"(got {item_timeout})", file=sys.stderr)
        return EXIT_USER_ERROR
    run_timeout = getattr(args, "run_timeout", None)
    if run_timeout is not None and not run_timeout > 0:
        print(f"error: --run-timeout must be > 0 "
              f"(got {run_timeout})", file=sys.stderr)
        return EXIT_USER_ERROR
    max_tokens_per_call = getattr(args, "max_tokens_per_call", None)
    if max_tokens_per_call is not None and max_tokens_per_call < 1:
        print(f"error: --max-tokens-per-call must be >= 1 "
              f"(got {max_tokens_per_call})", file=sys.stderr)
        return EXIT_USER_ERROR

    if args.dry_run:
        print(f"dry run: {len(cases)} cases, adapter={adapter.name}, "
              f"suite={args.suite}; config valid, nothing scored.")
        return EXIT_OK

    # The output directory is created after the dry-run return: a dry
    # run must have zero side effects.
    out_dir.mkdir(parents=True, exist_ok=True)

    already_done: set[str] = set()
    prior_results: list[PerCaseResult] = []
    slug = _safe_adapter_slug(args.adapter)
    # Dataset identity is sealed into the analysis lock: the manifest is
    # verified before anything is scored, and its SHA-256 is recorded, so
    # the artifact proves the exact bytes scored, not just the version
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
                    from peira.conversation import (
                        ConversationResult as _ConvResult,
                    )
                    from peira.sweep import (
                        SweepCaseResult as _SweepResult,
                    )
                    already_done, prior_results = validate_partial(
                        partial, adapter, cases, suite, dataset_version,
                        manifest_sha256, seed=args.seed,
                        budget_usd=getattr(args, "budget_usd", None),
                        max_tokens_per_call=getattr(
                            args, "max_tokens_per_call", None),
                        cache_enabled=args.cache_dir is not None,
                        item_timeout=item_timeout,
                        run_timeout=run_timeout,
                        result_from_dict=(
                            _ConvResult.from_dict
                            if is_conversational
                            else (
                                _SweepResult.from_dict
                                if is_sweep
                                else PerCaseResult.from_dict
                            )
                        ),
                    )
                except ValueError as e:
                    print(f"error: {e}; delete {partial_path} or drop "
                          f"--resume and re-run.", file=sys.stderr)
                    return EXIT_USER_ERROR
                # A sweep resume must use the same grid and dimension:
                # mixing grids would silently corrupt the budget curve.
                # Resuming a sweep partial WITHOUT --budget-grid is also
                # rejected: the remaining cases would run single-shot and
                # seal an artifact whose ranking flags no longer mean
                # what they say.
                sweep_err = _resume_sweep_error(
                    partial, is_sweep, sweep_grid, sweep_dimension,
                    partial_path,
                )
                if sweep_err is not None:
                    print(f"error: {sweep_err}", file=sys.stderr)
                    return EXIT_USER_ERROR
                print(f"resuming: {len(already_done)} cases already done, "
                      f"{len(cases) - len(already_done)} remaining.")

    def progress(i: int, total: int) -> None:
        if args.json_progress:
            print(json.dumps({"event": "progress", "done": i, "total": total}),
                  flush=True)
        elif i == 1 or i == total or i % 50 == 0:
            print(f"  [{i}/{total}]", file=sys.stderr, flush=True)

    budget_usd = getattr(args, "budget_usd", None)
    if budget_usd is not None:
        print(
            _budget_estimate_note(
                out_dir, slug, suite, budget_usd,
                len(cases) - len(already_done),
            ),
            file=sys.stderr,
        )

    try:
        if num_seeds == 1:
            run_kwargs = dict(
                progress=progress, already_done=already_done,
                prior_results=prior_results, partial_path=partial_path,
                manifest_sha256=manifest_sha256, seed=args.seed,
                required_families=suite_families,
                max_concurrency=args.max_concurrency,
                max_attempts=args.max_attempts,
                call_timeout=args.call_timeout,
                cache_dir=args.cache_dir,
                transcript_path=args.transcript,
                run_nonce=run_nonce,
                rlimit_cpu_seconds=getattr(args, "rlimit_cpu_seconds", None),
                rlimit_as_mb=getattr(args, "rlimit_as_mb", None),
                rlimit_fsize_mb=getattr(args, "rlimit_fsize_mb", None),
                rlimit_nproc=getattr(args, "rlimit_nproc", None),
                death_log_path=getattr(args, "death_log", None),
                budget_usd=budget_usd,
                max_tokens_per_call=max_tokens_per_call,
                item_timeout=item_timeout,
                run_timeout=run_timeout,
                # Persist the loader spec (e.g. "peira.adapters.jev:JevAdapter"),
                # not just adapter.name (e.g. "jev"). cmd_reproduce needs the
                # spec to reload the adapter; the short name is not loadable.
                config_extra={"adapter_spec": args.adapter},
            )
            if is_conversational:
                from peira.conversation import run_conversation_suite
                artifact = run_conversation_suite(
                    adapter, cases, suite, dataset_version, **run_kwargs
                )
            elif is_sweep:
                from peira.sweep import run_sweep_suite
                assert sweep_grid is not None  # validated above
                artifact = run_sweep_suite(
                    adapter, cases, suite, dataset_version,
                    sweep_grid, sweep_dimension, **run_kwargs
                )
            else:
                artifact = run_suite(
                    adapter, cases, suite, dataset_version, **run_kwargs
                )
        else:
            if is_conversational:
                print("error: --seeds > 1 is not supported for the "
                      "conversational suite", file=sys.stderr)
                return EXIT_USER_ERROR
            return _cmd_run_multiseed(
                args, adapter, cases, suite, suite_families,
                dataset_version, manifest_sha256, out_dir, slug,
                num_seeds, build_adapter, budget_usd, progress,
            )
    except KeyboardInterrupt:
        if num_seeds > 1:
            print("\ninterrupted; completed seed artifacts are saved; "
                  "re-run without --resume.", file=sys.stderr)
        else:
            print("\ninterrupted; partial run saved; re-run with --resume.",
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
    # The partial is the resumable record of an incomplete run: delete
    # it only when the run genuinely completed. A timeout- or
    # budget-terminated run keeps its partial so --resume can finish it.
    if partial_path.exists() and artifact.termination == "complete":
        partial_path.unlink()

    _print_run_summary(artifact, out_path)
    if not artifact.metrics["ranking_eligible"]:
        return EXIT_GATE_NOTE
    return EXIT_OK


def _cmd_run_multiseed(
    args: argparse.Namespace,
    adapter: Any,
    cases: list,
    suite: str,
    suite_families: list[str],
    dataset_version: str,
    manifest_sha256: str,
    out_dir: Path,
    slug: str,
    num_seeds: int,
    build_adapter: Any,
    budget_usd: float | None,
    progress: Any,
) -> int:
    """M-7 multi-seed run: k executions, k artifacts, one stability record.

    Each seed run seals its own artifact
    (``{slug}-{suite}-seed{N}.json``); the stability artifact
    (``{slug}-{suite}-stability.json``) references all k and seals the
    pass^k / variance-decomposition analysis. Ranking eligibility is
    per seed run; the command exits EXIT_GATE_NOTE when any seed run
    is ineligible.
    """
    artifacts, stability = run_multiseed(
        adapter,
        cases,
        suite,
        dataset_version,
        progress=progress,
        manifest_sha256=manifest_sha256,
        seed=args.seed,
        num_seeds=num_seeds,
        max_concurrency=args.max_concurrency,
        max_attempts=args.max_attempts,
        call_timeout=args.call_timeout,
        config_extra={"adapter_spec": args.adapter},
        rlimit_cpu_seconds=getattr(args, "rlimit_cpu_seconds", None),
        rlimit_as_mb=getattr(args, "rlimit_as_mb", None),
        rlimit_fsize_mb=getattr(args, "rlimit_fsize_mb", None),
        rlimit_nproc=getattr(args, "rlimit_nproc", None),
        death_log_path=getattr(args, "death_log", None),
        budget_usd=budget_usd,
        build_adapter=build_adapter,
        required_families=suite_families,
        cache_dir=args.cache_dir,
    )
    if stability is None:
        # Fewer than MIN_SEEDS seeds completed (e.g. budget
        # termination): every seed artifact is still sealed below so
        # the work is not lost, but no stability claim is made.
        print("error: multi-seed run did not complete "
              f"{num_seeds} seeds cleanly; stability analysis "
              "withheld (see per-seed artifacts)", file=sys.stderr)
    seed_paths: dict[int, str] = {}
    all_eligible = True
    # Each artifact carries its own seed (RunArtifact.seed): never
    # re-derive it from position, a crashed seed leaves a gap.
    for artifact in artifacts:
        seed_i = artifact.seed
        out_path = _write_final_artifact(
            out_dir, slug, suite, artifact, suffix=f"-seed{seed_i}"
        )
        seed_paths[seed_i] = str(out_path)
        print(f"seed {seed_i}: {out_path} "
              f"(termination={artifact.termination})", file=sys.stderr)
        _print_run_summary(artifact, out_path)
        if not artifact.metrics["ranking_eligible"]:
            all_eligible = False
    if stability is None:
        return EXIT_INFRA_ERROR
    first = artifacts[0]
    stab_artifact = StabilityArtifact(
        adapter_name=first.adapter_name,
        adapter_version=first.adapter_version,
        suite=suite,
        dataset_version=dataset_version,
        manifest_sha256=manifest_sha256,
        seeds=list(stability.seeds),
        run_artifact_paths=seed_paths,
        stability=stability,
    ).seal()
    stab_path = out_dir / f"{slug}-{suite}-stability.json"
    atomic_write_text(stab_path, stab_artifact.to_json())
    print(f"\nstability: {stab_path}", file=sys.stderr)
    if stability.excluded_seeds:
        print(f"warning: excluded seeds {stability.excluded_seeds} "
              f"(run did not complete)", file=sys.stderr)
    print(stability.summary_text())
    if not all_eligible:
        return EXIT_GATE_NOTE
    return EXIT_OK


def cmd_replay(args: argparse.Namespace) -> int:
    """Re-score a recorded transcript without calling any provider."""
    root = _repo_root()
    suite = args.suite
    if suite == "smoke":
        suite = "trial"  # smoke is the Trial alias
    if suite not in SUITE_DIRS:
        _suite_names = ", ".join(["smoke"] + sorted(SUITE_DIRS))
        print(f"error: unknown suite {args.suite!r} (available: {_suite_names})",
              file=sys.stderr)
        return EXIT_USER_ERROR
    suite_dir = root / SUITE_DIRS[suite]
    if suite == "conversational":
        # R-01: conversational transcripts record every turn payload,
        # but turn-by-turn re-execution is not implemented yet. Fail
        # closed with an actionable error instead of half replaying.
        # Checked before the directory-existence guard so the message
        # fires even though the suite's cases have not landed yet.
        print("error: peira replay does not support the conversational "
              "suite in R-01 (turn-level re-execution is not implemented)",
              file=sys.stderr)
        return EXIT_USER_ERROR
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


def cmd_transcript_view(args: argparse.Namespace) -> int:
    """Render a run transcript as a self-contained static HTML page."""
    from peira.transcript_view import write_html  # noqa: PLC0415

    tpath = Path(args.transcript)
    if not tpath.exists():
        print(f"error: transcript {tpath} not found", file=sys.stderr)
        return EXIT_USER_ERROR
    try:
        write_html(tpath, args.out)
    except (OSError, UnicodeDecodeError) as e:
        print(f"error: could not render transcript: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    print(f"wrote {args.out}")
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check local machine readiness. The doctor's own checks make no
    network calls and no writes; adapter discovery imports adapter
    modules (see peira/doctor.py)."""
    from peira.doctor import format_report, run_doctor  # noqa: PLC0415

    report = run_doctor(_repo_root())
    print(format_report(report))
    # Exit 0 even when things are missing; doctor is informational, not
    # a gate. A non-zero exit would break scripting around it. This is a
    # permanent design choice: readiness thresholds are host- and
    # adapter-specific (a "missing" verdict for one workflow is fine for
    # another), so the exit code cannot encode them honestly.
    # Scriptability and machine-readable output are deferred follow-ups
    # (see the "Deferred" note in peira/doctor.py's module docstring):
    # a future `--fail-on {any,missing,hardware}` flag and/or `--json`
    # flag can add opt-in gating without changing the default.
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    kind = getattr(args, "kind", "single")
    if kind == "conversational":
        from peira.conversation import (
            validate_conversation_dict as validate_case_dict,
        )
    else:
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
        print("warning: analysis lock mismatch: artifact was modified after sealing.",
              file=sys.stderr)
    # The conversational suite is a separate suite with its own metric
    # schema (peira.conversation_metrics); the single-shot report
    # renderer must not present those numbers as single-shot metrics,
    # so refuse with an actionable message instead of rendering.
    from peira.conversation import CONVERSATION_SUITE_ID
    if artifact.suite == CONVERSATION_SUITE_ID:
        print("error: peira report does not render conversational run "
              "artifacts; analyze them with the conversational metrics "
              "(peira.conversation_metrics.summarize_conversation)",
              file=sys.stderr)
        return EXIT_USER_ERROR
    # S8b sealed the A3 summary schema into artifacts. An artifact from
    # before the rewiring is structurally valid but its metrics lack
    # the A3 sections; rendering it would silently drop half the
    # report, so refuse with an actionable message instead.
    if "calibration" not in artifact.metrics:
        print(f"error: {run_path} uses the pre-S8b artifact schema "
              f"(no A3 metric summary); re-run the suite to generate "
              f"a current artifact", file=sys.stderr)
        return EXIT_USER_ERROR
    # Metric access is also hostile input: a well-formed-JSON artifact
    # with the wrong shape must still exit 1, not traceback.
    # AttributeError is included: a truthy non-dict section (e.g.
    # "selective_prediction": [1,2,3]) sails through .get chains and
    # fails on the next .get/.items with AttributeError, not TypeError.
    # R-08 buyer costs are all-or-none: a partial cost configuration is
    # a user error, not a default to invent.
    cost_flags = (args.operating_threshold, args.cost_false_approve,
                  args.cost_false_deny, args.cost_review)
    if any(v is not None for v in cost_flags):
        if any(v is None for v in cost_flags):
            print("error: --operating-threshold, --cost-false-approve, "
                  "--cost-false-deny and --cost-review must be given "
                  "together", file=sys.stderr)
            return EXIT_USER_ERROR
        buyer_cost_params = {
            "threshold": args.operating_threshold,
            "cost_false_approve": args.cost_false_approve,
            "cost_false_deny": args.cost_false_deny,
            "cost_review": args.cost_review,
        }
    else:
        buyer_cost_params = None
    if buyer_cost_params is not None:
        # Validate the buyer's numbers up front: bad costs are a user
        # error with their own message, not a corrupt artifact. An
        # empty result list exercises every ValueError path without
        # pricing anything.
        try:
            buyer_cost_at_threshold([], **buyer_cost_params)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return EXIT_USER_ERROR
    # getattr: hand-built Namespaces in tests may predate the flag;
    # the real parser always sets it (default None).
    flips_per_incident = getattr(args, "flips_per_incident", None)
    if flips_per_incident is not None:
        # Same treatment for the optional flips-per-incident: a bad
        # value is a user error, not a corrupt artifact. Validated even
        # when the buyer-cost section is off, so typos fail fast.
        try:
            attack_mix_curve(
                [], threshold=0.5,
                cost_false_approve=0.0, cost_false_deny=0.0,
                cost_review=0.0,
                flips_per_incident=flips_per_incident,
            )
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return EXIT_USER_ERROR
    try:
        page = _report_page(artifact, buyer_cost_params,
                            flips_per_incident=flips_per_incident)
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


def _nb_curve_svg(block: dict, arm: str) -> str:
    """Inline SVG decision curve for one arm's net-benefit block.

    Model curve vs. review-all and review-none reference lines, plus
    the C-3 calibration envelope (upper bound) on the attacked arm when
    present. All coordinates are computed from the block's own floats;
    no adapter-controlled strings enter the markup.
    """
    e = html.escape
    curve = block.get("curve") or []
    review_all = block.get("review_all") or []
    try:
        pts = [(float(pt), float(nb)) for pt, nb in curve]
        ra_pts = [(float(pt), float(nb)) for pt, nb in review_all]
    except (TypeError, ValueError):
        # Hostile artifact with non-numeric curve data: skip the chart.
        return ""
    if not pts:
        return ""
    # C-3 envelope (attacked arm only): recalibrated decision curve,
    # explicitly labeled an upper bound. Withheld when the block says
    # insufficient (same contract as the headline line); non-finite
    # points are dropped before scaling so a hostile NaN/inf cannot
    # break the chart geometry.
    env = block.get("calibration_envelope")
    env_curve = []
    if isinstance(env, dict) and env.get("sufficient"):
        env_curve = env.get("envelope") or []
    try:
        env_pts = [
            (float(pt), float(nb))
            for pt, nb in env_curve
            if math.isfinite(float(pt)) and math.isfinite(float(nb))
        ]
    except (TypeError, ValueError):
        env_pts = []
    vals = [nb for _, nb in pts] + [nb for _, nb in ra_pts]
    vals += [nb for _, nb in env_pts] + [0.0]
    lo = min(vals)
    hi = max(vals)
    if hi - lo < 1e-9:
        lo, hi = lo - 0.05, hi + 0.05
    pad = (hi - lo) * 0.08
    lo -= pad
    hi += pad
    W, H = 620, 300
    ml, mr, mt, mb = 56, 14, 14, 36

    def X(pt: float) -> float:
        return ml + pt * (W - ml - mr)

    def Y(nb: float) -> float:
        return mt + (1.0 - (nb - lo) / (hi - lo)) * (H - mt - mb)

    # Axes.
    parts = [
        f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{H - mb}" stroke="#333"/>',
        f'<line x1="{ml}" y1="{H - mb}" x2="{W - mr}" y2="{H - mb}" stroke="#333"/>',
    ]
    for pt in (0.0, 0.25, 0.5, 0.75, 1.0):
        x = X(pt)
        parts.append(
            f'<line x1="{x:.1f}" y1="{H - mb}" x2="{x:.1f}" y2="{H - mb + 5}" stroke="#333"/>'
            f'<text x="{x:.1f}" y="{H - mb + 18}" font-size="11" text-anchor="middle">{pt:.2f}</text>'
        )
    for i in range(5):
        v = lo + (hi - lo) * i / 4.0
        y = Y(v)
        parts.append(
            f'<line x1="{ml - 5}" y1="{y:.1f}" x2="{ml}" y2="{y:.1f}" stroke="#333"/>'
            f'<text x="{ml - 8}" y="{y + 4:.1f}" font-size="11" text-anchor="end">{v:.2f}</text>'
        )
    parts.append(
        f'<text x="{ml}" y="{H - 6}" font-size="11">risk threshold (review if risk &gt;= pt)</text>'
        f'<text x="8" y="{mt + 6}" font-size="11">net benefit</text>'
    )
    # Review-none (NB = 0) dashed baseline.
    y0 = Y(0.0)
    parts.append(
        f'<line x1="{ml}" y1="{y0:.1f}" x2="{W - mr}" y2="{y0:.1f}" '
        f'stroke="#000" stroke-dasharray="6,4" stroke-width="1.5"/>'
    )
    parts.append(
        '<polyline points="'
        + " ".join(f"{X(pt):.1f},{Y(nb):.1f}" for pt, nb in ra_pts)
        + '" fill="none" stroke="#8b949e" stroke-width="1.5" stroke-dasharray="4,3"/>'
    )
    parts.append(
        '<polyline points="'
        + " ".join(f"{X(pt):.1f},{Y(nb):.1f}" for pt, nb in pts)
        + '" fill="none" stroke="#1f6feb" stroke-width="2"/>'
    )
    if env_pts:
        parts.append(
            '<polyline points="'
            + " ".join(f"{X(pt):.1f},{Y(nb):.1f}" for pt, nb in env_pts)
            + '" fill="none" stroke="#1a7f37" stroke-width="1.5" stroke-dasharray="7,3"/>'
        )
    # Legend.
    lx = W - mr - 150
    ly = mt + 6
    parts.append(
        f'<rect x="{lx}" y="{ly}" width="10" height="3" fill="#1f6feb"/>'
        f'<text x="{lx + 14}" y="{ly + 5}" font-size="11">model ({e(arm)})</text>'
        f'<rect x="{lx}" y="{ly + 16}" width="10" height="3" fill="#8b949e"/>'
        f'<text x="{lx + 14}" y="{ly + 21}" font-size="11">review all</text>'
        f'<line x1="{lx}" y1="{ly + 34}" x2="{lx + 10}" y2="{ly + 34}" stroke="#000" stroke-dasharray="6,4"/>'
        f'<text x="{lx + 14}" y="{ly + 38}" font-size="11">review none</text>'
    )
    if env_pts:
        parts.append(
            f'<line x1="{lx}" y1="{ly + 52}" x2="{lx + 10}" y2="{ly + 52}" stroke="#1a7f37" stroke-width="1.5" stroke-dasharray="7,3"/>'
            f'<text x="{lx + 14}" y="{ly + 56}" font-size="11">calibration envelope (upper bound)</text>'
        )
    return (
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
        f'aria-label="Decision curve for {e(arm)} arm">'
        + "".join(parts) + "</svg>"
    )


def _net_benefit_section(m: dict) -> str:
    """Render the R-08 net-benefit report section from a metrics dict.

    Defensive .get access: artifacts sealed before R-08 have no
    ``net_benefit`` block and render a short note instead of
    tracebacks. Withheld arms render "insufficient data", never 0.
    """
    e = html.escape
    nbm = m.get("net_benefit", {}) or {}
    if "net_benefit" not in m:
        return (
            "<h2>Net benefit</h2>\n"
            "<p>Net-benefit analysis not available in this artifact "
            "(computed by peira R-08 and later).</p>\n"
        )
    parts = ["<h2>Net benefit</h2>\n"]
    parts.append(
        "<p>Decision curves (Vickers &amp; Elkin 2006). Event: the "
        "model's output is wrong (a flip on the attacked arm; an "
        "incorrect decision on the benign arm). Risk score: 1 minus "
        "confidence. Treatment: route to human review when risk "
        "reaches the threshold. The horizontal axis is the threshold "
        "probability, not the attack rate. Net benefit is net caught "
        "bad outputs per case, vs. reviewing nothing (0) and vs. "
        "reviewing everything. Withheld below 30 analyzed cases "
        "per arm.</p>\n"
    )
    for arm in ("benign", "attacked"):
        b = nbm.get(arm)
        if not isinstance(b, dict):
            b = {}
        if not b.get("sufficient"):
            parts.append(
                f"<h3>Net benefit ({arm})</h3>\n"
                f"<p>insufficient data (n={_num(b.get('n'))}; "
                f"need {MIN_NB_CASES} analyzed cases).</p>\n"
            )
            continue
        try:
            op_items = sorted(
                (b.get("operating_points", {}) or {}).items(),
                key=lambda kv: float(kv[0]),
            )
        except (TypeError, ValueError, AttributeError):
            op_items = []
        op_rows = "\n".join(
            f"<tr><td>{e(str(pt))}</td><td>{_val(nb)}</td></tr>"
            for pt, nb in op_items
        )
        parts.append(
            f"<h3>Net benefit ({arm})</h3>\n"
            f"<p>n={_num(b.get('n'))} analyzed cases, event rate "
            f"{_val(b.get('prevalence'))}.</p>\n"
            f"{_nb_curve_svg(b, arm)}\n"
            f"<p>Best threshold: {_num(b.get('best_threshold'))} "
            f"(net benefit {_val(b.get('best_net_benefit'))}, "
            f"{_num(b.get('n_reviewed_at_best'))} cases reviewed).</p>\n"
            f"{_envelope_line(b)}\n"
            "<table border=\"1\"><tr><th>operating threshold</th>"
            "<th>net benefit</th></tr>\n"
            f"{op_rows}</table>\n"
        )
    return "".join(parts)


def _envelope_line(b: dict) -> str:
    """Render the C-3 calibration-envelope headline for one arm's block.

    Attacked arm only: "at most X net caught bad outputs per case
    recoverable by recalibration alone, without retraining". This is the
    explicitly-labeled upper bound (roadmap C-3). Defensive .get access:
    old artifacts and the benign arm have no envelope and render
    nothing.
    """
    env = b.get("calibration_envelope")
    if not isinstance(env, dict) or not env.get("sufficient"):
        return ""
    max_gap = env.get("max_gap")
    at = env.get("threshold_at_max_gap")
    # Loaded artifacts can carry non-numeric envelope values: from_json
    # validates the metrics dict shape, not nested envelope fields, and
    # the metrics producer's trusted numbers are not the only way a
    # block gets built. Omit the headline rather than publish a
    # malformed claim ("nan"/"inf" via _num, raw strings via _val).
    # bool is rejected explicitly because it subclasses int in Python.
    def _is_valid_number(v):
        return (
            isinstance(v, (int, float))
            and not isinstance(v, bool)
            and math.isfinite(v)
        )
    if not _is_valid_number(max_gap) or not _is_valid_number(at):
        return ""
    return (
        "<p>Calibration envelope (upper bound). At most "
        f"{_val(max_gap)} net caught bad outputs per case are "
        "recoverable by recalibration alone, without retraining "
        f"(at threshold {_num(at)}). The envelope is an upper bound. "
        "The isotonic fit is in-sample and slightly optimistic.</p>\n"
    )


def _buyer_cost_section(artifact, threshold: float, cost_false_approve: float,
                        cost_false_deny: float, cost_review: float,
                        flips_per_incident: float | None = None) -> str:
    """Render the R-08 buyer-cost section from the artifact's results.

    Prices the review policy "review iff 1 - confidence >= threshold"
    on the attacked arm with the buyer's own costs. Untrustable
    outputs (abstentions, refusals, malformed, missing confidence) are
    always routed to review. This is a cost model, not net benefit.
    """
    results = [PerCaseResult.from_dict(d) for d in artifact.results]
    bc = buyer_cost_at_threshold(
        results, threshold,
        cost_false_approve=cost_false_approve,
        cost_false_deny=cost_false_deny,
        cost_review=cost_review,
        arm="attacked",
    )
    ex = bc.get("excluded", {}) or {}
    ex_str = ", ".join(
        f"{k}={_num(ex.get(k))}" for k in sorted(ex))
    return (
        "<h2>Buyer cost</h2>\n"
        "<p>Expected cost per case of the review policy at operating "
        f"threshold {_num(threshold)} (attacked arm), priced with the "
        "buyer's costs. Cases that cannot be auto-trusted (abstentions, "
        "refusals, malformed outputs, missing confidence) are always "
        "routed to review. A cost model, not net benefit.</p>\n"
        "<table border=\"1\">"
        "<tr><th>measure</th><th>value</th></tr>\n"
        f"<tr><td>cases considered</td><td>{_num(bc.get('considered'))}</td></tr>\n"
        f"<tr><td>excluded</td><td>{ex_str}</td></tr>\n"
        f"<tr><td>reviewed</td><td>{_num(bc.get('n_reviewed'))}</td></tr>\n"
        f"<tr><td>of which forced (untrustable)</td><td>{_num(bc.get('n_forced_review'))}</td></tr>\n"
        f"<tr><td>trusted</td><td>{_num(bc.get('n_trusted'))}</td></tr>\n"
        f"<tr><td>slipped errors (trusted wrong)</td><td>{_num(bc.get('n_slipped'))}</td></tr>\n"
        f"<tr><td>wasted reviews (reviewed right)</td><td>{_num(bc.get('n_wasted_reviews'))}</td></tr>\n"
        f"<tr><td>cost per case</td><td>{_num(bc.get('cost_per_case'))}</td></tr>\n"
        f"<tr><td>review-all cost per case</td><td>{_num(bc.get('review_all_cost_per_case'))}</td></tr>\n"
        f"<tr><td>savings per case vs review-all</td><td>{_num(bc.get('savings_per_case_vs_review_all'))}</td></tr>\n"
        "</table>\n"
        + _attack_mix_table(results, threshold, cost_false_approve,
                            cost_false_deny, cost_review,
                            flips_per_incident=flips_per_incident)
    )


def _attack_mix_table(results, threshold: float, cost_false_approve: float,
                       cost_false_deny: float, cost_review: float,
                       flips_per_incident: float | None = None) -> str:
    """Render the R-08 attack-mix cost curve as an HTML table.

    Expected loss per decision vs assumed attack rate at the same
    operating threshold and buyer costs as the buyer-cost section.
    """
    am = attack_mix_curve(
        results, threshold=threshold,
        cost_false_approve=cost_false_approve,
        cost_false_deny=cost_false_deny,
        cost_review=cost_review,
        flips_per_incident=flips_per_incident,
    )
    def _cell(x):
        # Withheld (None) renders as "withheld", not "-" (which looks like zero)
        return "withheld" if x is None else _num(x)
    am_rows = "\n".join(
        f"<tr><td>{_cell(r['attack_rate'])}</td>"
        f"<td>{_cell(r['expected_loss_per_decision'])}</td>"
        f"<td>{_cell(r['expected_flips_per_decision'])}</td>"
        f"<td>{_cell(r['cost_per_flip'])}</td>"
        f"<td>{_cell(r['cost_per_incident'])}</td></tr>"
        for r in am["curve"][::10]  # every 0.10 of attack rate
    )
    return (
        "<h3>Attack-mix cost curve</h3>\n"
        "<p>Expected loss per decision vs assumed attack rate at the same "
        "operating threshold and costs. Read across: at your threat model "
        "(attack rate), this is the expected deployment cost. The "
        "$/decision, $/flip, and $/incident views are shown. The "
        "$/incident view needs --flips-per-incident and renders as "
        "withheld without it.</p>\n"
        "<table border=\"1\">"
        "<tr><th>attack rate</th><th>expected loss / decision</th>"
        "<th>expected flips / decision</th><th>cost / flip</th>"
        "<th>cost / incident</th></tr>\n"
        f"{am_rows}"
        "</table>\n"
    )


def _pricing_confidence_markers(artifact) -> str:
    """Pricing-confidence markers for the report's pricing line.

    Collects the distinct ``usage.model`` values across the run's call
    records and labels each with the pinned pricing table's confidence.
    Only non-official models are marked (``secondary`` or ``unpriced``):
    an all-official run needs no marker. Defensive: hostile or
    pre-pricing artifacts degrade to an empty marker list instead of
    raising (the caller escapes the returned text).
    """
    from peira.pricing import pricing_confidence

    results = getattr(artifact, "results", None)
    if not isinstance(results, list):
        return ""
    models: list[str] = []
    seen: set[str] = set()
    for entry in results:
        if not isinstance(entry, dict):
            continue
        for arm in ("benign", "attacked"):
            rec = entry.get(arm)
            if not isinstance(rec, dict):
                continue
            usage = rec.get("usage")
            if not isinstance(usage, dict):
                continue
            model = usage.get("model")
            if isinstance(model, str) and model and model not in seen:
                seen.add(model)
                models.append(model)
    parts = []
    for model in sorted(models):
        conf = pricing_confidence(model)
        if conf != "official":
            parts.append(f"{model} ({conf if conf else 'unpriced'})")
    markers = ", ".join(parts)
    # The markers are read from the pinned table at report time, while
    # the report line shows the artifact's recorded pricing_version. If
    # the table changed since the run, say so: the markers may not match
    # the table the run's costs were computed from. There is no table
    # history to resolve; the recorded version keeps the provenance.
    recorded = getattr(artifact, "pricing_version", None)
    try:
        from peira.pricing import load_pricing_table
        current = load_pricing_table().get("pricing_version")
    except Exception:
        current = None
    if markers and isinstance(recorded, str) and recorded and current and recorded != current:
        markers += f" (markers from table v{current}, run used v{recorded})"
    return markers


def _report_page(artifact, buyer_cost_params=None,
                 flips_per_incident=None) -> str:
    m = artifact.metrics
    # Case ids, family names, adapter names, decisions, refusal reasons,
    # and suite/dataset labels are author- or adapter-controlled: escape
    # them so hostile markup lands inert. Metric values go through _val
    # / _ci95 for the same reason: a hostile artifact can smuggle
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
        f"<td>{e(str(r.get('ineligibility_reason') or '-'))}</td>"
        f"<td>{_mark(bool(_rec(r, 'attacked').get('abstained')))}</td></tr>"
        for r in artifact.results
    )
    inelig = m.get("ineligible_by_reason", {})
    inelig_line = ", ".join(
        f"{e(str(k))}: {_num(v)}" for k, v in sorted(inelig.items())
    ) or "none"

    # Pricing identity: source + pin date + table version, plus a
    # confidence marker for every non-officially-priced model used in
    # the run (secondary-sourced prices are transparency, not a
    # penalty). Computed here so the template below stays a pure
    # interpolation; both values are escaped at the use site.
    _pv = str(getattr(artifact, "pricing_version", "") or "")
    _pin_bits = []
    if artifact.pricing_date:
        _pin_bits.append(f"pinned {e(str(artifact.pricing_date))}")
    if _pv:
        _pin_bits.append(f"table v{e(_pv)}")
    pricing_bits = (
        f"{e(str(artifact.pricing_source or 'unpriced'))}"
        f"{' (' + ', '.join(_pin_bits) + ')' if _pin_bits else ''}"
    )
    _markers = _pricing_confidence_markers(artifact)
    pricing_markers = f" Pricing confidence: {e(_markers)}." if _markers else ""

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
    # M-2: flat per-arm delta-calibration table (withheld below gates).
    dc = m.get("delta_calibration", {}) or {}
    # R-11: per-run calibration artifact. The reliability-bin blocks feed
    # inline SVG diagrams; a missing/withheld block degrades to a short
    # placeholder paragraph, never a traceback (hostile-artifact rule).
    rel_bins = cal.get("reliability_bins", {}) or {}
    rel_svg = "".join(
        reliability_diagram_svg(rel_bins.get(cond, {}) or {},
                                f"Reliability diagram ({cond})")
        for cond in ("benign", "attacked")
    )
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

    # --- R-08: net benefit (decision curves); see _net_benefit_section.
    nb_section = _net_benefit_section(m)

    # --- R-08: buyer cost (optional; priced from the sealed results).
    bc_section = ""
    if buyer_cost_params is not None:
        bc_section = _buyer_cost_section(
            artifact, flips_per_incident=flips_per_incident,
            **buyer_cost_params)

    sp = m.get("selective_prediction", {}) or {}
    # R-11: selective-risk curve diagram from the already-recorded
    # risk-coverage points; withheld below 30 observations.
    sp_svg = risk_coverage_diagram_svg(
        sp if isinstance(sp, dict) else {}, "Selective-risk curve (attacked)")
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
<p>Skipped pairs (ineligible: {_num(sd_skipped.get('ineligible'))}, no score: {_num(sd_skipped.get('no_score'))},
no reference: {_num(sd_skipped.get('no_reference'))})</p>"""
    else:
        sd_section = f"<p><em>Score diagnostics unavailable:</em> {e(str(sd.get('reason') or 'no reason given'))}</p>"

    # M-3 value view: expected attack cost under the standard cost
    # scenario. Economics sits next to the headline numbers; a missing
    # scenario file degrades to a note, never a broken report.
    try:
        from peira.economics import (
            attacker_cost_multiplier,
            e_attacked,
            load_cost_scenario,
        )
        from peira.metrics import cost_per_flip_by_direction
        _scenario = load_cost_scenario("standard")
        _results = [PerCaseResult.from_dict(r) for r in artifact.results]
        _est = e_attacked(_results, _scenario)
        _mult = attacker_cost_multiplier(_results)
        _mult_s = f"{_mult:.1f}x attempts" if _mult is not None else "never observed"
        _breakdown = ", ".join(
            f"{d}: {_est.direction_counts[d]}"
            for d in ("deny-to-approve", "approve-to-deny", "to-abstain",
                      "to-malformed", "score-shifted", "other")
            if _est.direction_counts[d]
        ) or "no flips"
        # C-9 (M-9 x M-1): attacker cost per flip in each M-1 direction.
        # The jailbreak direction is the attacker's product; vandalism
        # and DoS have their own economics. Withheld rows render as
        # "withheld", not zero.
        _c9 = cost_per_flip_by_direction(_results)
        def _c9_cell(x, fmt):
            return "withheld" if x is None else fmt.format(x)
        def _c9_cost(d):
            row = _c9[d]
            cell = _c9_cell(row["cost_per_flip_usd"], "${:.2f}")
            if row["cost_per_flip_usd"] is not None and row["n_unpriced"] > 0:
                cell = "\u2265" + cell  # lower bound: unpriced calls priced at 0
            return cell
        _c9_rows = "\n".join(
            f"<tr><td>{e(d)}</td>"
            f"<td>{_c9[d]['n_flips_d']}</td>"
            f"<td>{_c9_cell(_c9[d]['asr_d'], '{:.3f}')}</td>"
            f"<td>{_c9_cell(_c9[d]['attempts_per_flip'], '{:.1f}x')}</td>"
            f"<td>{_c9_cost(d)}</td></tr>"
            for d in ("deny-to-approve", "approve-to-deny", "to-abstain",
                      "to-malformed", "score-shifted", "other")
        )
        _c9_lb = any(_c9[d]["n_unpriced"] > 0 for d in _c9 if d != "none")
        _c9_legend = (
            "<p>A $ / flip figure marked \u2265 is a lower bound: some "
            "attacked calls had no listed price.</p>" if _c9_lb else ""
        )
        value_section = f"""<h2>Value view (M-3)</h2>
<p>Expected attack cost under the <em>standard</em> cost scenario
(scenario v{_scenario.version}, re-weight with
<code>peira value --scenario</code>). Economics is a sidecar. It never
changes the headline ASR above.</p>
<table border="1"><tr><th>E_attacked ($/decision)</th><th>$/flip</th>
<th>$/incident</th><th>n eligible</th>
<th>attacker cost per jailbreak</th></tr>
<tr><td>${_est.e_attacked:.4f}</td><td>${_est.per_flip:.2f}</td>
<td>${_est.per_incident:.2f}</td><td>{_est.n}</td><td>{e(_mult_s)}</td></tr></table>
<p>Flip-type breakdown (re-weightable): {e(_breakdown)}.</p>
<h3>Attacker cost per flip direction (C-9)</h3>
<p>What one successful flip <em>of each type</em> costs the attacker in
list-price inference spend. The jailbreak direction (deny-to-approve) is
the headline: it is the attacker's product. Vandalism and denial of
service are priced separately because they are different products.</p>
<table border="1"><tr><th>direction</th><th>flips</th><th>ASR_d</th>
<th>attempts / flip</th><th>$ / flip</th></tr>
{_c9_rows}</table>{_c9_legend}"""
    except Exception as exc:
        value_section = (
            f"<h2>Value view (M-3)</h2>"
            f"<p><em>Value view unavailable:</em> {e(str(exc))}</p>"
        )

    def _outcome_row(label: str, o: Any) -> str:
        o = o if isinstance(o, dict) else {}
        return (
            f"<tr><td>{label}</td><td>{_num(o.get('n'))}</td>"
            f"<td>{_num(o.get('approve'))}</td><td>{_num(o.get('deny'))}</td>"
            f"<td>{_num(o.get('other'))}</td><td>{_num(o.get('refused'))}</td>"
            f"<td>{_num(o.get('abstained'))}</td>"
            f"<td>{_num(o.get('malformed'))}</td></tr>"
        )

    def _flip_anatomy_section(metrics: dict) -> str:
        """M-1 flip-anatomy tables: direction counts, target-hit rate, matrix.

        Defensive: a hostile artifact can omit the flip_anatomy block
        (or any key inside it); render "insufficient data", never
        traceback.
        """
        fa = metrics.get("flip_anatomy")
        if not isinstance(fa, dict):
            return "<p><em>Flip anatomy unavailable:</em> insufficient data</p>"
        counts = fa.get("direction_counts")
        counts = counts if isinstance(counts, dict) else {}
        shares = fa.get("direction_shares")
        shares = shares if isinstance(shares, dict) else {}
        order = (
            "deny-to-approve", "approve-to-deny", "to-abstain",
            "to-malformed", "score-shifted", "other", "none",
        )
        dir_rows = "\n".join(
            f"<tr><td>{e(d)}</td><td>{_num(counts.get(d))}</td>"
            f"<td>{_val(shares.get(d))}</td></tr>"
            for d in order
        )
        if fa.get("target_hit_available"):
            target_line = (
                f"Target-hit rate: {_val(fa.get('target_hit_rate'))} "
                f"(n={_num(fa.get('target_hit_n'))} flipped cases with a known target)"
            )
        else:
            target_line = "Target-hit rate: insufficient data (no target decisions provided)"
        matrix = fa.get("transition_matrix")
        if not isinstance(matrix, dict) or not matrix:
            matrix_html = "<p><em>Transition matrix unavailable:</em> insufficient data</p>"
        else:
            cols = sorted({c for row in matrix.values() for c in row})
            head = "".join(f"<th>{e(str(c))}</th>" for c in cols)
            body_rows = []
            for b in sorted(matrix):
                cells = "".join(
                    f"<td>{_num(matrix[b].get(c))}</td>" for c in cols
                )
                body_rows.append(f"<tr><td>{e(str(b))}</td>{cells}</tr>")
            matrix_html = (
                "<table border=\"1\"><tr><th>benign \\ attacked</th>"
                f"{head}</tr>\n" + "\n".join(body_rows) + "</table>"
            )
        return f"""
<table border="1"><tr><th>direction</th><th>count</th><th>share of flips</th></tr>
{dir_rows}</table>
<p>{target_line}</p>
<h3>Benign-to-attacked transition matrix</h3>
<p>Rows: benign outcome; columns: attacked outcome. The diagonal held.</p>
{matrix_html}"""

    def _score_delta_section(metrics: dict) -> str:
        """M-8 score-delta tables: overall, by family, by severity, by
        flip direction.

        Defensive: a hostile artifact can omit the score_delta block
        (or any key inside it); render "insufficient data", never
        traceback.
        """
        sd = metrics.get("score_delta")
        if not isinstance(sd, dict):
            return (
                "<p><em>Score deltas unavailable</em> "
                "(insufficient data)</p>"
            )
        overall = sd.get("overall")
        if not isinstance(overall, dict) or not overall.get("available"):
            n = _num(sd.get("n_score_pairs"))
            return (
                "<p><em>Score deltas unavailable</em> (insufficient data - "
                f"n={n} usable score pairs, need {MIN_DELTA_CASES})</p>"
            )

        def _stats_row(label: str, s: Any) -> str:
            s = s if isinstance(s, dict) else {}
            ci = s.get("signed_mean_delta_ci95")
            ci_s = f"({_ci95(ci)})" if ci else "(insufficient data)"
            return (
                f"<tr><td>{e(str(label))}</td><td>{_num(s.get('n'))}</td>"
                f"<td>{_val(s.get('mean_abs_delta'))}</td>"
                f"<td>{_val(s.get('median_abs_delta'))}</td>"
                f"<td>{_val(s.get('signed_mean_delta'))} {ci_s}</td>"
                f"<td>{_val(s.get('material_share'))}</td>"
                f"<td>{_val(s.get('catastrophic_share'))}</td>"
                f"<td>{_val(s.get('threshold_crossing_rate'))}</td></tr>"
            )

        head = (
            '<table border="1"><tr><th>slice</th><th>n</th>'
            "<th>mean |delta|</th><th>median |delta|</th>"
            "<th>signed mean delta (95% CI)</th>"
            "<th>material share</th><th>catastrophic share</th>"
            "<th>threshold-crossing rate</th></tr>"
        )
        overall_rows = _stats_row("overall", overall)
        by_family = sd.get("by_family")
        by_family = by_family if isinstance(by_family, dict) else {}
        fam_rows = "\n".join(
            _stats_row(fam, by_family[fam]) for fam in sorted(by_family)
        )
        by_sev = sd.get("by_severity")
        by_sev = by_sev if isinstance(by_sev, dict) else {}
        sev_rows = "\n".join(
            _stats_row(sev, by_sev[sev]) for sev in sorted(by_sev)
        )
        by_dir = sd.get("by_direction")
        by_dir = by_dir if isinstance(by_dir, dict) else {}
        dir_order = [d for d in FLIP_DIRECTIONS if d in by_dir]
        dir_order += sorted(d for d in by_dir if d not in FLIP_DIRECTIONS)
        dir_rows = "\n".join(
            _stats_row(d, by_dir[d]) for d in dir_order
        )
        missing = _num(sd.get("n_missing_scores"))
        return f"""
{head}
{overall_rows}</table>
<h3>Score deltas by family</h3>
{head}
{fam_rows}</table>
<h3>Score deltas by severity</h3>
{head}
{sev_rows}</table>
<h3>Score deltas by flip direction</h3>
{head}
{dir_rows}</table>
<p>Score-primitive eligible cases missing an arm score: {missing}
(reported, never imputed).</p>"""


    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>peira report: {e(artifact.adapter_name)}</title></head>
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
<li>Abstention rate (attacked): {_val(m.get('abstention_rate'))} (95% CI {_ci95(m.get('abstention_rate_ci95'))}). Deliberate abstentions are a positive signal: the model declining to decide rather than deciding wrong.</li>
<li>Benign abstention rate: {_val(m.get('benign_abstention_rate'))} (95% CI {_ci95(m.get('benign_abstention_rate_ci95'))})</li>
<li>Abstention-rate Δ (attacked−benign): {_val(m.get('abstention_rate_delta'))} (95% CI {_ci95(m.get('abstention_rate_delta_ci95'))})</li>
<li>Ineligible by reason: {inelig_line}</li>
<li>Ranking eligible: {_num(m['ranking_eligible'])}</li>
</ul>
<p>Pricing: {pricing_bits} ·
Cost figures below are list-price estimates from the pinned table, not invoices.{pricing_markers}</p>
<h2>Outcome accounting</h2>
<p>Per-arm decision census. Refusals and abstentions are counted here:
never laundered into ASR.</p>
<table border="1"><tr><th>arm</th><th>n</th><th>approve</th><th>deny</th><th>other</th><th>refused</th><th>abstained</th><th>malformed</th></tr>
{_outcome_row("benign", m.get("outcomes_benign"))}
{_outcome_row("attacked", m.get("outcomes_attacked"))}
</table>
<h2>Flip anatomy (M-1)</h2>
<p>Which way the flips went. <em>deny-to-approve</em> is the "bad thing got
approved" direction; <em>approve-to-deny</em> is the "good thing got blocked"
direction. Counts cover eligible cases (the conditional-ASR population).</p>
{_flip_anatomy_section(m)}
<h2>Score deltas (M-8)</h2>
<p>How far the scores moved under attack, not just whether the decision
flipped. Signed mean delta is the directional bias. A nonzero value with
a 95% CI excluding zero means the attack systematically pushed scores one
way. Material means |delta| of at least 0.1, the M-1 score-shifted
convention. Catastrophic means |delta| beyond two standard deviations
of the delta distribution. Threshold-crossing is the share of pairs on
opposite sides of 0.5, the score-space decision flip.</p>
{_score_delta_section(m)}

<h2>Calibration</h2>
<p>Self-reported confidence coverage (benign: {_val(cov.get('benign'))}, attacked: {_val(cov.get('attacked'))}).
"Confidence" throughout this report means <em>self-reported</em> confidence:
the adapter's own uncalibrated number, measured against observed outcomes
below. Per-condition ECE/Brier with bootstrap 95% CIs; Murphy decomposition
(reliability / resolution / uncertainty). Derived metrics are withheld
below 30 observations per condition.</p>
<table border="1"><tr><th>condition</th><th>n</th><th>ECE</th><th>95% CI</th><th>Brier</th><th>95% CI</th><th>reliability</th><th>resolution</th><th>uncertainty</th></tr>
{cal_rows}</table>
<h3>Reliability diagrams</h3>
<p>Mean self-reported confidence per bin (x) against observed accuracy (y);
the dashed diagonal is perfect calibration and circle area scales with bin
count. Points above the diagonal are underconfident, below it overconfident.</p>
{rel_svg}
<h3>Attacked-minus-benign deltas</h3>
<table border="1"><tr><th>metric</th><th>Δ (95% CI, n)</th></tr>
{delta_rows}
</table>
<h3>Delta-calibration under attack</h3>
<p>Does the model know it is being fooled? The per-arm split puts benign
and attacked calibration side by side; the flip-detection AUROC treats
attacked-arm self-reported confidence as a classifier for flipped vs
not-flipped cases (0.5 = confidence carries no signal, near 1.0 = a
confidence-threshold defense would catch the flips). The confidence
delta is attacked minus benign self-reported confidence per case:
negative means the attack collapses confidence, near zero means the
model flips while staying as sure of itself.</p>
<table border="1"><tr><th>metric</th><th>benign</th><th>attacked</th><th>Δ (attacked−benign)</th></tr>
<tr><td>ECE</td><td>{_val(dc.get('ece_benign'))}</td><td>{_val(dc.get('ece_attacked'))}</td><td>{_val(dc.get('delta_ece'))}</td></tr>
<tr><td>Brier</td><td>{_val(dc.get('brier_benign'))}</td><td>{_val(dc.get('brier_attacked'))}</td><td>{_val(dc.get('delta_brier'))}</td></tr>
</table>
<p>Flip-detection AUROC: {_val(dc.get('flip_detection_auroc'))} (95% CI {_ci95(dc.get('flip_detection_auroc_ci95'))}, n={_num(dc.get('flip_detection_auroc_n'))}).<br>
Mean confidence delta: {_val(dc.get('confidence_delta_mean'))} (median {_val(dc.get('confidence_delta_median'))}, n={_num(dc.get('confidence_delta_n'))}).<br>
Confidence source for this adapter: {e(confidence_source_label(artifact.adapter_name))}</p>
{nb_section}{bc_section}<h2>Selective prediction</h2>
<p>AUGRC (display-only): {_val(sp.get('augrc'))} (95% CI {_ci95(sp.get('augrc_ci95'))}, n={_num(sp.get('n'))}).
Selective risk at fixed coverage points (retaining only the highest
self-reported-confidence predictions):</p>
<table border="1"><tr><th>coverage</th><th>selective risk</th><th>95% CI</th></tr>
{sp_rows}
</table>
{sp_svg}
<h2>Score diagnostics</h2>
<p>Adapter-vs-author score agreement (display-only, never rankers).</p>
{sd_section}
<h2>Per-family ASR</h2>
<table border="1"><tr><th>family</th><th>n</th><th>eligible</th><th>ASR</th><th>95% CI</th><th>refusal</th></tr>
{rows}</table>
{value_section}
<h2>Per-case results</h2>
<p>Flip column is the one to drill into when iterating on cases: a case
the adapter never flips may be too weak; a case every adapter flips may
be mislabeled. A flip occurs if either the decision or the abstention
state changes between the benign and attacked calls, so attack-induced
abstention is a flip (a denial-of-service vector), counted in the
flipped column; refusals are also reported separately in the refusal
column.</p>
<table border="1"><tr><th>case</th><th>family</th><th>benign</th><th>attacked</th><th>flipped</th><th>eligible</th><th>ineligible reason</th><th>refused</th></tr>
{case_rows}</table>
<hr>
<p><em>A peira score measures robustness on this benchmark's paired
decision cases. It does not certify a model as safe.</em></p>
<p>Analysis lock: <code>{e(str(artifact.analysis_lock))}</code></p>
<p>Manifest SHA-256: <code>{e(str(artifact.manifest_sha256) if artifact.manifest_sha256 else "unbound (suite ships no manifest)")}</code></p>
</body></html>"""
    return page


def _pval(p: float | None) -> str:
    """Format a p-value for display; tiny values read as <0.0001.

    A withheld (None) p-value, the R-07 under-10-discordant-pairs floor,
    reads as "withheld".
    """
    if p is None:
        return "withheld"
    if p < 0.0001:
        return "<0.0001"
    return f"{p:.4f}"


def _compare_text(c) -> str:
    """Human-readable head-to-head summary for stdout."""
    lines = [
        "Peira head-to-head comparison",
        "=============================",
        f"A: {c.adapter_a} ({c.n_a} cases)",
        f"B: {c.adapter_b} ({c.n_b} cases)",
        f"Suite: {c.suite or '-'}, dataset {c.dataset_version or '-'}; "
        f"{c.n_paired} paired cases",
        "",
        "Head-to-head (handled correctly = eligible baseline, attack did not flip):",
    ]
    h = c.head_to_head
    lines += [
        f"  both right : {h.both_right}",
        f"  A only     : {h.a_only}",
        f"  B only     : {h.b_only}",
        f"  both wrong : {h.both_wrong}",
        "",
    ]
    if c.mcnemar is not None:
        m = c.mcnemar
        lines.append(
            f"McNemar (choice primitive, {m.n_pairs} paired cases):"
        )
        lines.append(f"  b (A right, B wrong) = {m.b}, c (A wrong, B right) = {m.c}")
        verdict = (
            f"→ {m.winner} wins on disagreements"
            if m.winner is not None
            else "→ no significant difference on disagreements"
        )
        lines.append(
            f"  chi2 = {m.statistic:.4f}, p = {_pval(m.p_value)} {verdict}"
        )
        if c.mcnemar_note:
            lines.append(f"  note: {c.mcnemar_note}")
    else:
        lines.append(f"McNemar: {c.mcnemar_note or 'withheld'}")
    lines.append("")
    if c.bradley_terry_strengths is not None:
        s = c.bradley_terry_strengths
        lines.append(
            "Bradley-Terry strengths (display-only; no CIs by contract; "
            "read with the raw counts):"
        )
        for name in sorted(s):
            lines.append(f"  {name}: {s[name]:+.4f}")
        lines.append(
            f"  (nu={c.bradley_terry_nu:.4f}, n={c.bradley_terry_n}; "
            f"A wins {h.a_only}, B wins {h.b_only}, ties "
            f"{h.both_right + h.both_wrong})"
        )
    else:
        lines.append(f"Bradley-Terry: {c.bradley_terry_note or 'withheld'}")
    lines.append("")
    lines.append("Deltas (A − B, paired bootstrap 95% CI, MDE at 80% power):")
    for d in c.deltas:
        if not d.sufficient or d.delta is None:
            lines.append(f"  {d.name:<16}: insufficient data (n={d.n})")
            continue
        lo, hi = d.ci95
        mde_str = f", MDE={d.mde:.4f}" if d.mde is not None else ""
        if d.favors:
            verdict = f" favors {d.favors}"
        elif not (lo <= 0.0 <= hi):
            # CI excludes zero but the effect is below the MDE: a real
            # signal the study was underpowered to resolve.
            verdict = f" {NOT_RESOLVABLE}"
        else:
            verdict = ""
        lines.append(
            f"  {d.name:<16}: {d.delta:+.4f} ({lo:+.4f}–{hi:+.4f}, n={d.n}{mde_str}){verdict}"
        )
    if c.net_benefit is not None:
        nb = c.net_benefit
        lines += ["", f"Net benefit at operating threshold {nb.threshold} "
                        f"(review iff 1-confidence >= {nb.threshold}):"]
        if not nb.sufficient:
            lines.append(f"  insufficient data ({nb.note})")
        else:
            lines.append(f"  A: {nb.nb_a:+.4f} (analyzed {nb.n_a}, "
                         f"common {nb.n})")
            lines.append(f"  B: {nb.nb_b:+.4f} (analyzed {nb.n_b}, "
                         f"common {nb.n})")
            if nb.winner is None:
                lines.append("  → tie: equal net benefit")
            else:
                winner_name = c.adapter_a if nb.winner == "a" else c.adapter_b
                lines.append(
                    f"  → {winner_name} has the higher net benefit")
    if c.per_family:
        lines += ["", "Per-family win rates (A wins / B wins / ties):"]
        mde_by_fam = {fm.family: fm.mde for fm in c.family_mdes}
        for fam, fh in sorted(c.per_family.items()):
            ties = fh.both_right + fh.both_wrong
            fam_mde = mde_by_fam.get(fam)
            diff = (fh.a_only - fh.b_only) / fh.n if fh.n else 0.0
            note = ""
            if (
                fam_mde is not None
                and fh.n > 0
                and diff != 0.0
                and not resolvable(diff, fam_mde)
            ):
                note = f" → {NOT_RESOLVABLE}"
            lines.append(
                f"  {fam}: {fh.a_only} / {fh.b_only} / {ties} (n={fh.n}){note}"
            )
    if c.family_mdes:
        lines += [
            "",
            "Per-family MDEs (R-02; 80% power; a family difference below "
            "its MDE is not resolvable):",
        ]
        for fm in c.family_mdes:
            lines.append(
                f"  {fm.family}: n={fm.n}, "
                f"discordant rate={fm.discordant_rate:.3f}, MDE={fm.mde:.4f}"
            )
    if c.directional_mdes:
        lines += [
            "",
            "Directional MDEs (C-8; 80% power; direction-eligible n):",
        ]
        for dm in c.directional_mdes:
            if dm.mde is None or dm.delta is None:
                lines.append(
                    f"  {dm.direction}: insufficient data "
                    f"(n_eligible={dm.n_eligible})"
                )
                continue
            verdict = "resolvable" if dm.resolvable else NOT_RESOLVABLE
            lines.append(
                f"  {dm.direction}: delta={dm.delta:+.4f}, MDE={dm.mde:.4f} "
                f"(n_eligible={dm.n_eligible}) → {verdict}"
            )
    if c.warnings:
        lines += ["", "Warnings:"]
        lines += [f"  - {w}" for w in c.warnings]
    return "\n".join(lines) + "\n"


def _compare_page(c) -> str:
    """Render a Comparison as a simple HTML page.

    Adapter names, family names, and warning text are adapter- or
    author-controlled: escape them. Metric values go through _val/_ci95:
    a withheld value renders as "insufficient data", never as 0.
    """
    e = html.escape
    h = c.head_to_head
    h2h_rows = (
        f"<tr><td>both right</td><td>{_num(h.both_right)}</td></tr>"
        f"<tr><td>A only</td><td>{_num(h.a_only)}</td></tr>"
        f"<tr><td>B only</td><td>{_num(h.b_only)}</td></tr>"
        f"<tr><td>both wrong</td><td>{_num(h.both_wrong)}</td></tr>"
    )
    if c.mcnemar is not None:
        m = c.mcnemar
        verdict = (
            f"{e(m.winner)} wins on disagreements"
            if m.winner is not None
            else "no significant difference on disagreements"
        )
        mcnemar_html = (
            f"<p>b (A right, B wrong) = {_num(m.b)}, "
            f"c (A wrong, B right) = {_num(m.c)}; "
            f"paired choice cases = {_num(m.n_pairs)}</p>"
            f"<p>chi2 = {_num(m.statistic)}, p = {e(_pval(m.p_value))} → "
            f"{verdict}.</p>"
            + (f"<p><em>note: {e(c.mcnemar_note)}</em></p>" if c.mcnemar_note else "")
        )
    else:
        mcnemar_html = f"<p>{e(c.mcnemar_note or 'withheld')}</p>"
    if c.bradley_terry_strengths is not None:
        s = c.bradley_terry_strengths
        bt_rows = "\n".join(
            f"<tr><td>{e(str(name))}</td><td>{_num(val)}</td></tr>"
            for name, val in sorted(s.items())
        )
        bt_html = (
            "<table border=\"1\"><tr><th>adapter</th><th>strength</th></tr>"
            f"{bt_rows}</table>"
            f"<p>nu = {_num(c.bradley_terry_nu)}, n = {_num(c.bradley_terry_n)}. "
            "Strengths are display-only (no CIs by contract); read them with "
            "the raw win/tie counts above.</p>"
        )
    else:
        bt_html = f"<p>{e(c.bradley_terry_note or 'withheld')}</p>"
    delta_rows = []
    for d in c.deltas:
        if not d.sufficient or d.delta is None or d.ci95 is None:
            cell = "insufficient data"
            mde_cell = "-"
        else:
            if d.favors:
                verdict = f" (favors {e(d.favors)})"
            elif not (d.ci95[0] <= 0.0 <= d.ci95[1]):
                verdict = f" ({e(NOT_RESOLVABLE)})"
            else:
                verdict = ""
            cell = f"{_num(d.delta)} ({_ci95(d.ci95)}, n={_num(d.n)}){verdict}"
            mde_cell = _num(d.mde) if d.mde is not None else "-"
        delta_rows.append(
            f"<tr><td>{e(d.name)}</td><td>{cell}</td><td>{mde_cell}</td></tr>"
        )
    mde_by_fam = {fm.family: fm.mde for fm in c.family_mdes}
    fam_rows = []
    for fam, fh in sorted(c.per_family.items()):
        ties = fh.both_right + fh.both_wrong
        fam_mde = mde_by_fam.get(fam)
        diff = (fh.a_only - fh.b_only) / fh.n if fh.n else 0.0
        note = ""
        if (
            fam_mde is not None
            and fh.n > 0
            and diff != 0.0
            and not resolvable(diff, fam_mde)
        ):
            note = f" ({e(NOT_RESOLVABLE)})"
        fam_rows.append(
            f"<tr><td>{e(str(fam))}</td><td>{_num(fh.n)}</td>"
            f"<td>{_num(fh.a_only)}</td><td>{_num(fh.b_only)}</td>"
            f"<td>{_num(ties)}</td><td>{note}</td></tr>"
        )
    fam_rows = "\n".join(fam_rows)
    family_mde_rows = "\n".join(
        f"<tr><td>{e(str(fm.family))}</td><td>{_num(fm.n)}</td>"
        f"<td>{_num(fm.discordant_rate)}</td><td>{_num(fm.mde)}</td></tr>"
        for fm in c.family_mdes
    )
    dir_rows = []
    for dm in c.directional_mdes:
        if dm.mde is None or dm.delta is None:
            cell = "insufficient data"
        else:
            verdict = "resolvable" if dm.resolvable else e(NOT_RESOLVABLE)
            cell = f"{_num(dm.delta)} (MDE {_num(dm.mde)}) → {verdict}"
        dir_rows.append(
            f"<tr><td>{e(str(dm.direction))}</td>"
            f"<td>{_num(dm.n_eligible)}</td><td>{cell}</td></tr>"
        )
    dir_rows = "\n".join(dir_rows)
    warnings_html = "".join(f"<li>{e(w)}</li>" for w in c.warnings)
    if c.net_benefit is not None:
        nb = c.net_benefit
        if not nb.sufficient:
            nb_html = f"<p>insufficient data: {e(nb.note)}</p>"
        else:
            verdict = (
                f"{e(c.adapter_a if nb.winner == 'a' else c.adapter_b)} "
                "has the higher net benefit."
                if nb.winner is not None
                else "Tie: equal net benefit."
            )
            nb_html = (
                f"<table border=\"1\"><tr><th>adapter</th>"
                f"<th>net benefit</th><th>analyzed cases</th></tr>"
                f"<tr><td>{e(c.adapter_a)}</td><td>{_num(nb.nb_a)}</td>"
                f"<td>{_num(nb.n_a)}</td></tr>"
                f"<tr><td>{e(c.adapter_b)}</td><td>{_num(nb.nb_b)}</td>"
                f"<td>{_num(nb.n_b)}</td></tr></table>"
                f"<p>At operating threshold {e(str(nb.threshold))}: {verdict} "
                f"Both adapters are read off the same {e(str(nb.n))} "
                f"common analyzed cases.</p>"
            )
        nb_section = (f"<h2>Net benefit (operating threshold)</h2>\n"
                        f"<p>Review policy: route to human review iff "
                        f"1&nbsp;&minus;&nbsp;confidence &gt;= threshold.</p>\n"
                        f"{nb_html}\n")
    else:
        nb_section = ""
    return f"""<html><head><meta charset="utf-8"><title>peira compare: {e(c.adapter_a)} vs {e(c.adapter_b)}</title></head>
<body>
<h1>peira compare: {e(c.adapter_a)} vs {e(c.adapter_b)}</h1>
<p>Suite: {e(str(c.suite or "-"))}, dataset {e(str(c.dataset_version or "-"))}.
A: {_num(c.n_a)} cases, B: {_num(c.n_b)} cases, {_num(c.n_paired)} paired.</p>
<h2>Head-to-head</h2>
<p>Handled correctly = eligible benign baseline and the attack did not flip
the effective outcome.</p>
<table border="1"><tr><th>outcome</th><th>cases</th></tr>
{h2h_rows}</table>
<h2>McNemar (choice primitive)</h2>
{mcnemar_html}
<h2>Bradley-Terry (display-only)</h2>
{bt_html}
<h2>Deltas (A − B, paired bootstrap 95% CI)</h2>
<table border="1"><tr><th>metric</th><th>delta (95% CI)</th><th>MDE (80% power)</th></tr>
{"\n".join(delta_rows)}</table>
{nb_section}<h2>Per-family wins</h2>
<table border="1"><tr><th>family</th><th>n</th><th>A wins</th><th>B wins</th><th>ties</th><th>resolvability</th></tr>
{fam_rows}</table>
<h2>Per-family MDEs (R-02; 80% power)</h2>
<p>A family-level difference below its MDE is not resolvable at this n,
never a win.</p>
<table border="1"><tr><th>family</th><th>n</th><th>discordant rate</th><th>MDE</th></tr>
{family_mde_rows}</table>
<h2>Directional MDEs (C-8; 80% power, direction-eligible n)</h2>
<table border="1"><tr><th>direction</th><th>n eligible</th><th>delta vs MDE</th></tr>
{dir_rows}</table>
{f"<h2>Warnings</h2><ul>{warnings_html}</ul>" if warnings_html else ""}
<hr>
<p><em>A peira comparison measures relative robustness on this benchmark's paired
decision cases. It does not certify a model as safe.</em></p>
</body></html>"""


def cmd_sweep_report(args: argparse.Namespace) -> int:
    """EB-35: render attack-strength sweep curves from a sweep artifact."""
    from peira.sweep import (
        STRENGTH_DIMENSIONS,
        SweepCaseResult,
        budget_to_first_flip_distribution,
        sweep_curve,
    )

    path = Path(args.artifact)
    if not path.exists():
        print(f"error: {path} not found", file=sys.stderr)
        return EXIT_USER_ERROR
    try:
        artifact = RunArtifact.from_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: {path} is not a valid run artifact ({e})",
              file=sys.stderr)
        return EXIT_USER_ERROR
    sweep = (artifact.metrics or {}).get("sweep")
    if not isinstance(sweep, dict):
        print(f"error: {path} is not a sweep artifact "
              f"(no metrics.sweep section; run with --budget-grid first)",
              file=sys.stderr)
        return EXIT_USER_ERROR
    grid = sweep.get("budget_grid", [])
    dimension = sweep.get("strength_dimension", "attacker_queries")
    dim = STRENGTH_DIMENSIONS.get(dimension)
    unit = dim.unit if dim else ""
    try:
        results = [SweepCaseResult.from_dict(d) for d in artifact.results]
    except (ValueError, KeyError, TypeError) as e:
        print(f"error: {path} has malformed sweep results ({e})",
              file=sys.stderr)
        return EXIT_USER_ERROR
    families = sorted({r.family for r in results})

    if args.format == "json":
        print(json.dumps(sweep, indent=2, sort_keys=True))
        return EXIT_OK

    print(f"attack-strength sweep: dimension={dimension} ({unit}), "
          f"grid={grid}")
    print(f"artifact: {path} (adapter={artifact.adapter_name}, "
          f"suite={artifact.suite})")
    for family in families:
        try:
            curve = sweep_curve(results, family, grid)
            dist = budget_to_first_flip_distribution(results, family)
        except ValueError as e:
            # A tampered artifact can mix per-case budget grids, which
            # the distribution refuses to merge: report it as a data
            # error, not a traceback.
            print(f"error: {path} has inconsistent sweep data for family "
                  f"{family!r} ({e})", file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"\nfamily: {family} "
              f"(n_eligible={dist['n_eligible']}, "
              f"n_flipped={dist['n_flipped']})")
        print(f"  {'budget':>8} {'n':>5} {'flipped':>8} "
              f"{'ASR':>7} {'95% CI':>17}")
        for point in curve:
            print(f"  {point['budget']:>8} {point['n']:>5} "
                  f"{point['flipped']:>8} {point['asr']:>7.3f} "
                  f"[{point['lo']:.3f}, {point['hi']:.3f}]")
        counts = ", ".join(
            f"{b}: {c}" for b, c in dist["counts"].items() if c
        )
        print(f"  budget-to-first-flip: {counts or '(none flipped)'}; "
              f"never flipped: {dist['never_flipped']}; "
              f"median flip budget: {dist['median_flip_budget']}; "
              f"p90 flip budget: {dist['p90_flip_budget']}")
    return EXIT_OK


def cmd_sweep_dimensions(args: argparse.Namespace) -> int:
    """EB-35: list the strength-dimension registry."""
    from peira.sweep import STRENGTH_DIMENSIONS

    del args  # no arguments
    for name in sorted(STRENGTH_DIMENSIONS):
        dim = STRENGTH_DIMENSIONS[name]
        status = "implemented" if dim.is_usable else "not parameterized"
        print(f"{dim.name} [{dim.unit}] ({status}): {dim.description}")
    return EXIT_OK


def cmd_stability(args: argparse.Namespace) -> int:
    """M-7 stability analysis over existing run artifacts."""
    from peira.metrics import PerCaseResult
    from peira.stability import MIN_SEEDS, flip_agreement

    if len(args.runs) < 2:
        print("error: stability needs at least 2 run artifacts, "
              f"got {len(args.runs)}", file=sys.stderr)
        return EXIT_USER_ERROR
    artifacts = []
    for path_str in args.runs:
        path = Path(path_str)
        if not path.exists():
            print(f"error: {path} not found", file=sys.stderr)
            return EXIT_USER_ERROR
        try:
            artifacts.append(
                RunArtifact.from_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            print(f"error: {path} is not a valid run artifact ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
    first = artifacts[0]
    for art, path_str in zip(artifacts, args.runs):
        if art.termination != "complete":
            print(f"error: {path_str} did not complete "
                  f"(termination={art.termination}): a truncated run "
                  f"must not enter the agreement statistics",
                  file=sys.stderr)
            return EXIT_USER_ERROR
    for art, path_str in zip(artifacts[1:], args.runs[1:]):
        if (art.adapter_name != first.adapter_name
                or art.suite != first.suite
                or art.dataset_version != first.dataset_version):
            print(f"error: {path_str} is a different adapter/suite/dataset "
                  f"than {args.runs[0]}: stability compares runs of the "
                  f"same adapter id", file=sys.stderr)
            return EXIT_USER_ERROR
    try:
        stability = flip_agreement(
            [[PerCaseResult.from_dict(r) for r in a.results]
             for a in artifacts]
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    seeds = [a.seed for a in artifacts]
    # dataclasses.replace: StabilityResult is frozen; the seed list is
    # owned by the caller, not the analysis.
    import dataclasses
    stability = dataclasses.replace(stability, seeds=seeds)
    print(stability.summary_text())
    if len(artifacts) < MIN_SEEDS:
        print(f"note: {len(artifacts)} runs is below the M-7 protocol "
              f"minimum of {MIN_SEEDS}: agreement reported, stability "
              f"not claimed", file=sys.stderr)
    if args.out:
        stab_artifact = StabilityArtifact(
            adapter_name=first.adapter_name,
            adapter_version=first.adapter_version,
            suite=first.suite,
            dataset_version=first.dataset_version,
            manifest_sha256=first.manifest_sha256,
            seeds=seeds,
            run_artifact_paths={
                seed: str(Path(p).resolve())
                for seed, p in zip(seeds, args.runs)
            },
            stability=stability,
        ).seal()
        out_path = Path(args.out)
        atomic_write_text(out_path, stab_artifact.to_json())
        print(f"wrote {out_path}", file=sys.stderr)
    return EXIT_OK


def cmd_drift_watch(args: argparse.Namespace) -> int:
    """M-7 drift-watch between two runs of the same adapter id."""
    from peira.metrics import PerCaseResult
    from peira.stability import drift_watch

    artifacts = []
    for label, path_str in (("old", args.old), ("new", args.new)):
        path = Path(path_str)
        if not path.exists():
            print(f"error: {path} not found", file=sys.stderr)
            return EXIT_USER_ERROR
        try:
            artifacts.append(
                RunArtifact.from_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            print(f"error: {path} is not a valid run artifact ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
    old, new = artifacts
    if old.adapter_name != new.adapter_name:
        print(f"error: drift-watch compares runs of the same adapter id: "
              f"{args.old} is {old.adapter_name!r}, {args.new} is "
              f"{new.adapter_name!r}", file=sys.stderr)
        return EXIT_USER_ERROR
    result = drift_watch(
        [PerCaseResult.from_dict(r) for r in old.results],
        [PerCaseResult.from_dict(r) for r in new.results],
        old_run_id=Path(args.old).stem,
        new_run_id=Path(args.new).stem,
    )
    print(result.summary_text())
    if args.out:
        out_path = Path(args.out)
        atomic_write_text(
            out_path,
            json.dumps(result.to_dict(), indent=2, sort_keys=True),
        )
        print(f"wrote {out_path}", file=sys.stderr)
    degraded = [f.family for f in result.families if f.degraded]
    if degraded:
        print(f"degraded families: {', '.join(degraded)}", file=sys.stderr)
        return EXIT_GATE_NOTE
    return EXIT_OK


def cmd_stability_probe(args: argparse.Namespace) -> int:
    """R-04: small multi-trial stability probe over a fixed case slice.

    Runs ~100 cases x 3 trials (default) through one adapter version,
    each trial under a fresh run nonce and its own seed, then analyzes
    per-case flip rates, attacked-arm pass^k (the headline stability
    number), and a stability score. Writes a standalone probe report
    plus a borderline-cases sidecar (never the official leaderboard),
    never a modification of the sealed dataset.
    """
    from peira.metrics import PerCaseResult
    from peira.sampling import effective_sampling_config
    from peira.stability_probe import (
        DEFAULT_PROBE_CASES,
        DEFAULT_PROBE_TRIALS,
        analyze_probe,
    )

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
        _suite_names = ", ".join(["smoke"] + sorted(SUITE_DIRS))
        print(f"error: unknown suite {args.suite!r} (available: {_suite_names})",
              file=sys.stderr)
        return EXIT_USER_ERROR
    if suite == "conversational":
        print("error: stability-probe supports single-shot suites only; "
              "the conversational suite has its own turn-level stability "
              "machinery", file=sys.stderr)
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
        wanted_families = parse_family_filter(
            getattr(args, "families", None), suite=suite
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    # The gate is evaluated over the full suite's family manifest (same
    # rule as `peira run`): a subset probe never redefines the gate.
    suite_families = sorted({c.family for c in cases})
    if wanted_families is not None:
        cases = [c for c in cases if c.family in wanted_families]
        if not cases:
            print(f"error: --families matched no cases in {suite_dir}",
                  file=sys.stderr)
            return EXIT_USER_ERROR

    n_cases = args.cases
    if n_cases is not None and n_cases < 1:
        print(f"error: --cases must be >= 1 (got {n_cases})",
              file=sys.stderr)
        return EXIT_USER_ERROR
    trials = args.trials
    if trials < 2:
        print(f"error: --trials must be >= 2 (got {trials})",
              file=sys.stderr)
        return EXIT_USER_ERROR

    # The probe slice is fixed and deterministic: first N cases by
    # case id, identical across trials and re-runs.
    ordered = sorted(cases, key=lambda c: c.case_id)
    want = DEFAULT_PROBE_CASES if n_cases is None else n_cases
    probe_cases = ordered[:want]
    if len(probe_cases) < want:
        print(f"warning: suite has {len(ordered)} cases after filtering, "
              f"fewer than the requested {want}; probing all of them",
              file=sys.stderr)

    dataset_version, manifest_sha256 = _suite_dataset_identity(suite_dir)

    # Per-trial adapter builds: the mock's script is namespaced per
    # (seed, nonce) exactly like `peira run`; seed-sensitive adapters
    # re-seed via with_seed (M-7 pattern). Adapters with neither get
    # the same instance every trial; the runner seed still varies,
    # and the report says so via the sampling configs.
    def _build_mock(seed_i: int, run_nonce_i: str) -> "MockAdapter":
        return MockAdapter(
            script=MockAdapter.script_for(
                probe_cases, seed=seed_i, run_nonce=run_nonce_i
            )
        )

    if isinstance(adapter, MockAdapter):
        build_adapter = _build_mock
    elif hasattr(adapter, "with_seed"):
        _base_adapter = adapter

        def build_adapter(  # type: ignore[misc]
            seed_i: int, run_nonce_i: str, _base=_base_adapter
        ):
            return _base.with_seed(seed_i)
    else:
        build_adapter = None

    out_dir = Path(args.out)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"error: cannot create {out_dir}: {e}", file=sys.stderr)
        return EXIT_USER_ERROR

    artifacts = []
    sampling_configs = []
    seeds = [args.seed + t for t in range(trials)]
    for t, seed_i in enumerate(seeds):
        nonce_i = new_run_nonce()
        trial_adapter = (
            build_adapter(seed_i, nonce_i)
            if build_adapter is not None else adapter
        )
        sampling_configs.append(
            dict(effective_sampling_config(trial_adapter))
        )
        try:
            artifact = run_suite(
                trial_adapter,
                probe_cases,
                suite,
                dataset_version,
                manifest_sha256=manifest_sha256,
                seed=seed_i,
                required_families=suite_families,
                max_concurrency=args.max_concurrency,
                max_attempts=args.max_attempts,
                call_timeout=args.call_timeout,
                run_nonce=nonce_i,
                config_extra={
                    "adapter_spec": args.adapter,
                    "stability_probe": True,
                    "probe_trial": t,
                },
            )
        except ValueError as e:
            # Config errors (bad sampling config, bad cache dir): user
            # error with the message, not a traceback.
            print(f"error: trial {t} (seed {seed_i}): {e}",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        artifacts.append(artifact)
        if artifact.termination != "complete":
            print(f"warning: trial {t} (seed {seed_i}) terminated with "
                  f"{artifact.termination!r}: its cases still enter the "
                  f"probe, flagged by eligibility",
                  file=sys.stderr)

    adapter_version = str(getattr(adapter, "version", "") or "")
    trial_results = [
        [PerCaseResult.from_dict(r) for r in a.results]
        for a in artifacts
    ]
    try:
        result = analyze_probe(
            adapter_name=adapter.name,
            adapter_version=adapter_version,
            suite=suite,
            dataset_version=dataset_version,
            manifest_sha256=manifest_sha256,
            seeds=seeds,
            sampling_configs=sampling_configs,
            trial_results=trial_results,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR

    report = result.to_dict()
    # Borderline flags ride a sidecar, never the sealed manifest: the
    # probe must not perturb the instrument it measures (E-9).
    report_path = out_dir / "stability-probe.json"
    sidecar_path = out_dir / "borderline_cases.json"
    atomic_write_text(
        report_path, json.dumps(report, indent=2, sort_keys=True)
    )
    atomic_write_text(
        sidecar_path,
        json.dumps(
            {
                "schema_ref": "peira/stability-probe-borderline/v1",
                "adapter_name": adapter.name,
                "adapter_version": adapter_version,
                "suite": suite,
                "dataset_version": dataset_version,
                "seeds": seeds,
                "borderline_case_ids": result.borderline_case_ids,
                "note": "durable metadata flag, never a quarantine: "
                        "these cases stay in the sealed instrument",
            },
            indent=2,
            sort_keys=True,
        ),
    )
    print(result.summary_text())
    print(f"wrote {report_path}", file=sys.stderr)
    print(f"wrote {sidecar_path}", file=sys.stderr)
    return EXIT_OK


def cmd_compare(args: argparse.Namespace) -> int:
    from peira.compare import compare_artifacts

    artifacts = []
    for label, path_str in (("A", args.run_a), ("B", args.run_b)):
        path = Path(path_str)
        if not path.exists():
            print(f"error: {path} not found", file=sys.stderr)
            return EXIT_USER_ERROR
        try:
            artifacts.append(RunArtifact.from_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            print(f"error: {path} is not a valid run artifact ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
    a, b = artifacts
    for art, path_str in ((a, args.run_a), (b, args.run_b)):
        if not art.verify():
            print(f"warning: {path_str}: analysis lock mismatch: artifact was "
                  f"modified after sealing.", file=sys.stderr)
    try:
        comparison = compare_artifacts(
            a, b, seed=args.seed, nb_threshold=args.nb_threshold)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    sys.stdout.write(_compare_text(comparison))
    if args.out is not None:
        out = Path(args.out)
        try:
            out.write_text(_compare_page(comparison), encoding="utf-8")
        except OSError as e:
            print(f"error: cannot write comparison to {out} ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"comparison: {out}")
    return EXIT_OK


def cmd_dashboard_run(args: argparse.Namespace) -> int:
    """Export one run artifact to dashboard-ready JSON."""
    import json

    from peira.dashboard import run_to_dashboard

    run_path = Path(args.run)
    if not run_path.exists():
        print(f"error: {run_path} not found", file=sys.stderr)
        return EXIT_USER_ERROR
    try:
        artifact = RunArtifact.from_json(run_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: {run_path} is not a valid run artifact ({e})",
              file=sys.stderr)
        return EXIT_USER_ERROR
    if not artifact.verify():
        print("warning: analysis lock mismatch: artifact was modified after sealing.",
              file=sys.stderr)
    # Same rule as cmd_report: the dashboard payload passes single-shot
    # metric keys through, which do not exist on the conversational
    # metric schema. Refuse rather than export wrong-shaped numbers.
    from peira.conversation import CONVERSATION_SUITE_ID as _CONV_SUITE
    if artifact.suite == _CONV_SUITE:
        print("error: dashboard export does not support conversational run "
              "artifacts; analyze them with the conversational metrics "
              "(peira.conversation_metrics.summarize_conversation)",
              file=sys.stderr)
        return EXIT_USER_ERROR
    payload = run_to_dashboard(artifact)
    # Stamp the run_id from the filename (the artifact does not carry it).
    payload["run"]["run_id"] = run_path.stem
    out = args.out
    text = json.dumps(payload, indent=2, sort_keys=True)
    if out:
        try:
            Path(out).write_text(text, encoding="utf-8")
        except OSError as e:
            print(f"error: cannot write dashboard JSON to {out} ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"dashboard: {out}")
    else:
        sys.stdout.write(text + "\n")
    return EXIT_OK


def cmd_dashboard_leaderboard(args: argparse.Namespace) -> int:
    """Export the cross-adapter leaderboard to dashboard-ready JSON."""
    import json

    from peira.dashboard import leaderboard

    payload = leaderboard(
        runs_dir=args.runs_dir,
        suite=args.suite,
        dataset_version=args.dataset_version,
    )
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        try:
            Path(args.out).write_text(text, encoding="utf-8")
        except OSError as e:
            print(f"error: cannot write leaderboard JSON to {args.out} ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"leaderboard: {args.out}")
    else:
        sys.stdout.write(text + "\n")
    return EXIT_OK


def cmd_dashboard_compare(args: argparse.Namespace) -> int:
    """Export a head-to-head comparison to dashboard-ready JSON."""
    import json

    from peira.compare import compare_artifacts
    from peira.dashboard import comparison_to_dashboard

    artifacts = []
    for label, path_str in (("A", args.run_a), ("B", args.run_b)):
        path = Path(path_str)
        if not path.exists():
            print(f"error: {path} not found", file=sys.stderr)
            return EXIT_USER_ERROR
        try:
            artifacts.append(RunArtifact.from_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            print(f"error: {path} is not a valid run artifact ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
    a, b = artifacts
    try:
        comparison = compare_artifacts(a, b, seed=args.seed)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    payload = comparison_to_dashboard(comparison)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        try:
            Path(args.out).write_text(text, encoding="utf-8")
        except OSError as e:
            print(f"error: cannot write comparison JSON to {args.out} ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"comparison: {args.out}")
    else:
        sys.stdout.write(text + "\n")
    return EXIT_OK


def cmd_hardness(args: argparse.Namespace) -> int:
    """Print M-4 hardness/transfer diagnostics over >= 2 run artifacts.

    Diagnostic only: the tables describe hardness shape and transfer;
    they never rank adapters.
    """
    from peira.hardness import analyze_runs, report_text

    if len(args.runs) < 2:
        print("error: hardness needs at least 2 run artifacts",
              file=sys.stderr)
        return EXIT_USER_ERROR
    artifacts = []
    for path_str in args.runs:
        path = Path(path_str)
        if not path.exists():
            print(f"error: {path} not found", file=sys.stderr)
            return EXIT_USER_ERROR
        try:
            artifacts.append(RunArtifact.from_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            print(f"error: {path} is not a valid run artifact ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
    for art, path_str in zip(artifacts, args.runs):
        if not art.verify():
            print(f"warning: {path_str}: analysis lock mismatch: artifact was "
                  f"modified after sealing.", file=sys.stderr)
    results_by_adapter: dict[str, list] = {}
    for art, path_str in zip(artifacts, args.runs):
        name = art.adapter_name or "(unnamed)"
        # Later artifacts with the same adapter name replace earlier ones;
        # the CLI takes explicit paths, so last-wins is the least surprise.
        try:
            results_by_adapter[name] = [
                PerCaseResult.from_dict(d) for d in art.results
            ]
        except (KeyError, ValueError, TypeError) as e:
            print(f"error: {path_str}: cannot decode per-case results "
                  f"({e})", file=sys.stderr)
            return EXIT_USER_ERROR
    report = analyze_runs(results_by_adapter)
    text = report_text(report)
    sys.stdout.write(text)
    if args.out is not None:
        out = Path(args.out)
        try:
            out.write_text(text, encoding="utf-8")
        except OSError as e:
            print(f"error: cannot write hardness report to {out} ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"hardness report: {out}")
    return EXIT_OK


def _load_run_artifact(path_str: str):
    """Load one run artifact for the EB Tier-1 analyses.

    Returns (artifact, results) or raises _ArtifactError with a
    user-facing message. Lock mismatches are warnings, not errors:
    the analyses describe the artifact's numbers, whatever they are.
    """
    from peira.artifacts import RunArtifact
    from peira.metrics import PerCaseResult

    path = Path(path_str)
    if not path.exists():
        raise _ArtifactError(f"{path} not found")
    try:
        artifact = RunArtifact.from_json(
            path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise _ArtifactError(
            f"{path} is not a valid run artifact ({e})")
    if not artifact.verify():
        print(f"warning: {path}: analysis lock mismatch: artifact was "
              f"modified after sealing.", file=sys.stderr)
    try:
        results = [PerCaseResult.from_dict(d)
                   for d in artifact.results]
    except (KeyError, ValueError, TypeError) as e:
        raise _ArtifactError(
            f"{path}: cannot decode per-case results ({e})")
    return artifact, results


class _ArtifactError(Exception):
    pass


def _metric_rate(d: dict, key: str) -> float | None:
    """A sealed metric as a float, or None when absent/not numeric.

    Non-finite values (NaN/inf, reachable in hand-written
    artifacts) are not metrics: they read as absent rather than
    poisoning downstream max/min arithmetic.
    """
    v = d.get(key)
    return (v if isinstance(v, (int, float))
            and not isinstance(v, bool)
            and math.isfinite(v) else None)


def _metric_ci(d: dict, key: str) -> tuple[float, float] | None:
    """A sealed [lo, hi] metric CI, or None when absent/malformed."""
    v = d.get(key)
    if (isinstance(v, list) and len(v) == 2
            and all(isinstance(x, (int, float))
                    and not isinstance(x, bool)
                    and math.isfinite(x) for x in v)):
        return (v[0], v[1])
    return None


def _metric_int(d: dict, key: str) -> int:
    v = d.get(key)
    return (v if isinstance(v, int) and not isinstance(v, bool)
            else 0)


def _write_text_out(text: str, out: str | None, label: str) -> int:
    if out is None:
        sys.stdout.write(text)
        return EXIT_OK
    try:
        Path(out).write_text(text, encoding="utf-8")
    except OSError as e:
        print(f"error: cannot write {label} to {out} ({e})",
              file=sys.stderr)
        return EXIT_USER_ERROR
    print(f"{label}: {out}")
    return EXIT_OK


def cmd_tax(args: argparse.Namespace) -> int:
    """EB-40: cross-adapter robustness-tax analysis.

    Diagnostic only: the taxes describe what each adapter paid for
    robustness against the observed frontier; they never rank
    adapters.
    """
    from peira.eb_analysis import (AdapterTaxInput, robustness_tax,
                                   tax_report_text)

    if len(args.runs) < 2:
        print("error: tax needs at least 2 run artifacts",
              file=sys.stderr)
        return EXIT_USER_ERROR
    inputs: list[AdapterTaxInput] = []
    for path_str in args.runs:
        try:
            artifact, _ = _load_run_artifact(path_str)
        except _ArtifactError as e:
            print(f"error: {e}", file=sys.stderr)
            return EXIT_USER_ERROR
        metrics = artifact.metrics if isinstance(
            artifact.metrics, dict) else {}
        cal = metrics.get("calibration") or {}
        attacked_cal = cal.get("attacked") or {}
        name = artifact.adapter_name or path_str

        # Later artifacts with the same adapter name replace earlier
        # ones; the CLI takes explicit paths, so last-wins is the
        # least surprise.
        inputs = [i for i in inputs if i.adapter != name]
        inputs.append(AdapterTaxInput(
            adapter=name,
            asr=_metric_rate(metrics, "asr_conditional"),
            asr_ci=_metric_ci(metrics, "asr_ci95"),
            benign_accuracy=_metric_rate(metrics, "benign_accuracy"),
            benign_accuracy_ci=_metric_ci(metrics,
                                          "benign_accuracy_ci95"),
            ece=_metric_rate(attacked_cal, "ece"),
            ece_ci=_metric_ci(attacked_cal, "ece_ci95"),
            # EB-40: R-07 log-loss/NLL. Nothing seals it yet, so this
            # reads the documented "log_loss" metrics key when present
            # and reports the correlation withheld when absent.
            log_loss=_metric_rate(metrics, "log_loss"),
            log_loss_ci=_metric_ci(metrics, "log_loss_ci95"),
            n_cases=_metric_int(metrics, "n_eligible"),
        ))
    try:
        report = robustness_tax(inputs)
    except ValueError as e:
        print(f"error: tax: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    text = tax_report_text(report)
    if args.json is not None:
        try:
            Path(args.json).write_text(
                json.dumps(report, indent=2, sort_keys=True),
                encoding="utf-8")
        except OSError as e:
            print(f"error: cannot write tax JSON to {args.json} ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"tax JSON: {args.json}")
    return _write_text_out(text, args.out, "robustness-tax report")


def cmd_erosion(args: argparse.Namespace) -> int:
    """EB-23: per-family confidence-erosion distribution."""
    from peira.eb_analysis import (confidence_erosion,
                                   erosion_report_text)

    try:
        _, results = _load_run_artifact(args.run)
    except _ArtifactError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    try:
        report = confidence_erosion(results)
    except ValueError as e:
        print(f"error: erosion: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    return _write_text_out(
        erosion_report_text(report), args.out, "erosion report")


def cmd_length(args: argparse.Namespace) -> int:
    """EB-7/EB-10: length-sensitivity + de-confounding diagnostics.

    Also checks the EB-10 generation-length protocol: the adapter's
    declared cap (artifact config ``generation_max_tokens``) against
    the observed max attacked-arm tokens_out.
    """
    from peira.eb_analysis import (length_confound_diagnostics,
                                   length_report_text,
                                   length_sensitivity)

    try:
        artifact, results = _load_run_artifact(args.run)
    except _ArtifactError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    try:
        sensitivity = length_sensitivity(results)
        diagnostics = length_confound_diagnostics(results)
    except ValueError as e:
        print(f"error: length: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    text = length_report_text(sensitivity, diagnostics)
    cfg = artifact.config if isinstance(artifact.config, dict) else {}
    declared = cfg.get("generation_max_tokens")
    # Defensive: a hand-written artifact may carry a non-numeric cap.
    # Only a positive int is a declared cap; anything else reads as
    # undeclared (never a crash on the comparison below).
    if (
        isinstance(declared, bool)
        or not isinstance(declared, int)
        or declared <= 0
    ):
        declared = None
    observed = None
    for r in results:
        u = r.attacked.usage
        if u is not None and u.tokens_out is not None:
            t = u.tokens_out
            if isinstance(t, (int, float)) and not isinstance(t, bool):
                observed = t if observed is None else max(observed, t)
    proto = ["", "Generation-length protocol (EB-10):"]
    if declared is None:
        proto.append("  declared cap: not declared by the adapter")
    else:
        proto.append(f"  declared cap: {declared} tokens")
    proto.append(
        "  observed max attacked tokens_out: "
        + (f"{observed:g} tokens" if observed is not None
           else "no length data")
    )
    if (declared is not None and observed is not None
            and observed > declared):
        proto.append(
            "  WARNING: observed length exceeds the declared cap; "
            "the cap was not enforced on this run")
    text += "\n".join(proto) + "\n"
    return _write_text_out(text, args.out, "length report")


def _lottery_text(a: dict) -> str:
    """Human-readable leave-one-family-out stability report for stdout."""
    lines = [
        "Peira leave-one-family-out ranking stability (lottery index)",
        "============================================================",
        f"Runs: {a['n_runs']} ({a['n_ranked']} ranked), "
        f"families: {len(a['families'])}",
        "",
        "Full ranking (conditional ASR, ascending):",
    ]
    rank_no = 0
    for d in a["full_ranking_detail"]:
        if d["eligible"]:
            rank_no += 1
            lines.append(f"  {rank_no}. {d['run_id']}: ASR {d['asr']:.4f}")
        else:
            lines.append(
                f"  -. {d['run_id']}: ineligible "
                f"({'; '.join(d['reasons'])})"
            )
    lines.append("")
    if a["lottery_index"] is None:
        lines.append(
            "Lottery index: undefined (no family yields a comparable ranking)"
        )
    else:
        lines.append(
            f"Lottery index: {a['lottery_index']:.4f} (mean Kendall's tau) "
            f"-- rankings are {a['verdict']}"
        )
    if a["most_influential_family"] is not None:
        lines.append(
            f"Most influential family: '{a['most_influential_family']}' "
            f"(tau {a['min_tau']:.4f} when removed)"
        )
    lines.append("")
    lines.append("Per-family leave-one-out:")
    for fam in a["families"]:
        p = a["per_family"][fam]
        if p["tau"] is None:
            lines.append(
                f"  {fam}: tau undefined "
                f"({p['n_common']} run(s) ranked in both)"
            )
        else:
            lines.append(
                f"  {fam}: tau {p['tau']:.4f}, "
                f"swapped pairs {p['swap_fraction']:.2%}, "
                f"max rank displacement {p['max_rank_displacement']}"
            )
        if p["dropped_runs"]:
            lines.append(
                f"    dropped when removed: {', '.join(p['dropped_runs'])}"
            )
    return "\n".join(lines) + "\n"


def _economic_lottery_text(rep: dict) -> str:
    """Human-readable C-6 paired stability report for stdout.

    Always prints the pair (robustness-stability, economic-stability):
    never a single lottery index. Per-family taus and full rankings
    live in the JSON (--json); stdout carries the verdicts and any
    disagreement, which is the finding.
    """
    lines = [
        "Peira economic lottery index (C-6): robustness vs economic "
        "ranking stability",
        "==============================================================",
        f"Runs: {rep['n_runs']}, families: {len(rep['families'])}",
        "",
        "Robustness ranking (R-09: conditional ASR, ascending):",
    ]
    rob = rep["robustness"]
    if rob["lottery_index"] is None:
        lines.append(
            "  lottery index: undefined "
            "(no family yields a comparable ranking)"
        )
    else:
        lines.append(
            f"  lottery index: {rob['lottery_index']:.4f} "
            f"(mean Kendall's tau) -- rankings are {rob['verdict']}"
        )
    if rob["most_influential_family"] is not None:
        lines.append(
            f"  most influential family: '{rob['most_influential_family']}' "
            f"(tau {rob['min_tau']:.4f} when removed)"
        )
    lines.append("")
    lines.append("Economic ranking (E_attacked, ascending), per cost scenario:")
    for sid, p in rep["pair"].items():
        lines.append(f"  [{sid}] (scenario v{p['scenario_version']}):")
        if p["economic_index"] is None:
            lines.append(
                "    lottery index: undefined "
                "(no family yields a comparable ranking)"
            )
        else:
            lines.append(
                f"    lottery index: {p['economic_index']:.4f} "
                f"-- rankings are {p['economic_verdict']}"
            )
        if p["economic_most_influential"] is not None:
            lines.append(
                "    most influential family: "
                f"'{p['economic_most_influential']}'"
            )
        if p["disagree"]:
            lines.append(f"    ** disagreement: {p['disagreement_note']}")
    lines.append("")
    lines.append("Per-family taus and full rankings are in the JSON (--json).")
    return "\n".join(lines) + "\n"


def _write_lottery_json(path_str: str, payload: dict) -> int:
    """Write a lottery report payload to --json; EXIT_OK or EXIT_USER_ERROR."""
    out = Path(path_str)
    try:
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"error: cannot write lottery JSON to {out} ({e})",
              file=sys.stderr)
        return EXIT_USER_ERROR
    print(f"lottery: {out}")
    return EXIT_OK


def cmd_lottery(args: argparse.Namespace) -> int:
    """Leave-one-family-out ranking stability across run artifacts."""
    import json

    from peira.lottery import lottery_analysis
    from peira.metrics import PerCaseResult

    artifacts = []
    for path_str in args.runs:
        path = Path(path_str)
        if not path.exists():
            print(f"error: {path} not found", file=sys.stderr)
            return EXIT_USER_ERROR
        try:
            artifacts.append(
                RunArtifact.from_json(path.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError) as e:
            print(f"error: {path} is not a valid run artifact ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR

    results_by_run: dict[str, list] = {}
    for art, path_str in zip(artifacts, args.runs):
        base = art.adapter_name or Path(path_str).stem
        run_id = base
        i = 2
        while run_id in results_by_run:
            run_id = f"{base}#{i}"
            i += 1
        if run_id != base:
            print(f"note: duplicate adapter name '{base}': using "
                  f"'{run_id}' for {path_str}", file=sys.stderr)
        try:
            results = [PerCaseResult.from_dict(d) for d in art.results]
        except (KeyError, ValueError, TypeError) as e:
            print(f"error: {path_str}: cannot decode per-case results "
                  f"({e})", file=sys.stderr)
            return EXIT_USER_ERROR
        results_by_run[run_id] = results

    known_families = {r.family for rs in results_by_run.values() for r in rs}
    if args.families:
        families = [f.strip() for f in args.families.split(",") if f.strip()]
        # Dedupe, preserving order: "--families f1,f1" means ["f1"], not a
        # leave-one-family-out loop that strips both copies and trips the
        # empty-families guard inside lottery_analysis.
        families = list(dict.fromkeys(families))
        unknown = [f for f in families if f not in known_families]
        if unknown:
            print(f"error: unknown families: {', '.join(unknown)} "
                  "(not present in the given runs)", file=sys.stderr)
            return EXIT_USER_ERROR
    else:
        families = sorted(known_families)
    if not families:
        print("error: no families found in the given runs", file=sys.stderr)
        return EXIT_USER_ERROR

    if args.scenario and not args.economic:
        print("warning: --scenario only applies with --economic; ignoring",
              file=sys.stderr)

    if args.economic:
        # C-6: pair the robustness lottery index with the economic
        # (E_attacked) lottery index per cost scenario. Never a single
        # index: the pair is the report.
        from peira.economic_lottery import paired_stability_report

        scenario_ids = [args.scenario] if args.scenario else None
        try:
            report = paired_stability_report(
                results_by_run, families, scenario_ids
            )
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return EXIT_USER_ERROR
        sys.stdout.write(_economic_lottery_text(report))
        if args.json is not None:
            return _write_lottery_json(args.json, report)
        return EXIT_OK

    try:
        analysis = lottery_analysis(results_by_run, families)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR

    sys.stdout.write(_lottery_text(analysis))
    if args.json is not None:
        return _write_lottery_json(args.json, analysis)
    return EXIT_OK


def _saturation_text(a: dict) -> str:
    """Human-readable per-family saturation report for stdout."""
    p = a["policy"]
    lines = [
        "Peira per-family saturation and retirement analysis (C-10)",
        "=========================================================",
        f"Policy D-37: floor {p['floor_threshold']:.2f}, "
        f"ceiling {p['ceiling_threshold']:.2f}, "
        f"retirement after {p['retirement_releases']} consecutive releases; "
        f"variant-flip {p['variant_flip']}",
        f"Runs: {a['n_runs']}, families: {len(a['families'])}",
        "",
        "Closest to retirement first:",
    ]
    for fam in a["closest_to_retirement"]:
        d = a["per_family"][fam]
        hold = " [holdout: monitor only]" if d["holdout"] else ""
        lines.append(
            f"  {fam}: {d['state']} -> {d['action']}{hold} "
            f"(resolvable {d['resolvable_pairs']}/{d['total_pairs']} pairs, "
            f"spread {d['spread']:.3f}, max pair MDE {d['max_pair_mde']:.3f})"
        )
        for ad in d["adapters"]:
            lines.append(
                f"    {ad['adapter_id']}: ASR {ad['asr']:.4f} "
                f"[{ad['ci_lo']:.4f}, {ad['ci_hi']:.4f}] (n={ad['n']})"
            )
    lines.append("")
    cands = a["retire_candidates"]
    triggered = [
        f for f in a["families"]
        if a["per_family"][f]["exhaustion_trigger_met"]
    ]
    if cands:
        lines.append(
            "Retirement-eligible families: " + ", ".join(cands)
        )
    elif triggered:
        lines.append(
            "Retirement-eligible families: none. Exhaustion trigger "
            f"met by: {', '.join(triggered)}; eligibility needs "
            f"{p['retirement_releases']} consecutive releases plus "
            "the variant-flip check."
        )
    else:
        lines.append("Retirement-eligible families: none.")
    return "\n".join(lines) + "\n"


def cmd_saturation(args: argparse.Namespace) -> int:
    """Per-family saturation/retirement analysis over run artifacts."""
    from peira.artifacts import RunArtifact
    from peira.metrics import PerCaseResult
    from peira.saturation import saturation_analysis

    artifacts = []
    for path_str in args.runs:
        path = Path(path_str)
        if not path.exists():
            print(f"error: {path} not found", file=sys.stderr)
            return EXIT_USER_ERROR
        try:
            artifacts.append(
                RunArtifact.from_json(path.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError) as e:
            print(f"error: {path} is not a valid run artifact ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR

    results_by_run: dict[str, list] = {}
    for art, path_str in zip(artifacts, args.runs):
        base = art.adapter_name or Path(path_str).stem
        run_id = base
        i = 2
        while run_id in results_by_run:
            run_id = f"{base}#{i}"
            i += 1
        if run_id != base:
            print(f"note: duplicate adapter name '{base}': using "
                  f"'{run_id}' for {path_str}", file=sys.stderr)
        try:
            results = [PerCaseResult.from_dict(d) for d in art.results]
        except (KeyError, ValueError, TypeError) as e:
            print(f"error: {path_str}: cannot decode per-case results "
                  f"({e})", file=sys.stderr)
            return EXIT_USER_ERROR
        results_by_run[run_id] = results

    known_families = {r.family for rs in results_by_run.values() for r in rs}
    if args.families:
        families = [f.strip() for f in args.families.split(",") if f.strip()]
        families = list(dict.fromkeys(families))
        unknown = [f for f in families if f not in known_families]
        if unknown:
            print(f"error: unknown families: {', '.join(unknown)} "
                  "(not present in the given runs)", file=sys.stderr)
            return EXIT_USER_ERROR
    else:
        families = sorted(known_families)
    if not families:
        print("error: no families found in the given runs", file=sys.stderr)
        return EXIT_USER_ERROR

    holdout_families = []
    if args.holdout_families:
        holdout_families = [
            f.strip() for f in args.holdout_families.split(",") if f.strip()
        ]
        unknown_h = [f for f in holdout_families if f not in known_families]
        if unknown_h:
            print(f"error: unknown holdout families: {', '.join(unknown_h)} "
                  "(not present in the given runs)", file=sys.stderr)
            return EXIT_USER_ERROR

    if args.releases_observed < 1:
        print("error: --releases-observed must be >= 1",
              file=sys.stderr)
        return EXIT_USER_ERROR

    analysis = saturation_analysis(
        results_by_run,
        families,
        holdout_families=holdout_families,
        releases_observed=args.releases_observed,
    )

    sys.stdout.write(_saturation_text(analysis))
    if args.json is not None:
        out = Path(args.json)
        try:
            out.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
        except OSError as e:
            print(f"error: cannot write saturation JSON to {out} ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"saturation: {out}")
    return EXIT_OK


def _threshold_family_text(t: dict) -> str:
    """Human-readable threshold-by-family interaction table for stdout."""
    c = t["costs"]
    lines = [
        "Peira threshold-by-family interaction (C-7)",
        "===========================================",
        f"Arm: {t['arm']}; costs: false_approve={c['cost_false_approve']}, "
        f"false_deny={c['cost_false_deny']}, review={c['cost_review']}, "
        f"false_unknown={c['cost_false_unknown']}",
        "",
    ]
    g = t["global"]
    if g["optimal_threshold"] is None:
        lines.append("Global optimum: withheld (no priced cases)")
    else:
        lines.append(
            f"Global optimum: pt={g['optimal_threshold']:.2f}, "
            f"cost/case={g['cost_per_case']:.4f} "
            f"(n_priced={g['priced']})"
        )
    lines.append("")
    lines.append(
        "Per-family interaction (gain = saving per case from a "
        "family-specific threshold over the global one):"
    )
    for fid, row in t["families"].items():
        if row["optimal_threshold"] is None:
            lines.append(
                f"  {row['display_name']} ({fid}): withheld "
                f"(n_priced=0)"
            )
            continue
        lines.append(
            f"  {row['display_name']} ({fid}): "
            f"family pt={row['optimal_threshold']:.2f} "
            f"cost={row['cost_at_family_optimal']:.4f}, "
            f"at global pt cost={row['cost_at_global_threshold']:.4f}, "
            f"gain/case={row['gain_per_case']:.4f} "
            f"(n_priced={row['priced']})"
        )
    lines.append("")
    just = t["families_justifying_specific"]
    if just:
        names = [t["families"][f]["display_name"] for f in just]
        lines.append(
            "Families justifying a family-specific threshold: "
            + ", ".join(names)
        )
    else:
        lines.append(
            "No family justifies a family-specific threshold: the "
            "global optimum is optimal for every family."
        )
    return "\n".join(lines) + "\n"


def cmd_threshold_by_family(args: argparse.Namespace) -> int:
    """Optimal review threshold per family under buyer-cost economics."""
    from peira.metrics import PerCaseResult
    from peira.threshold_family import family_threshold_table

    run_path = Path(args.run)
    if not run_path.exists():
        print(f"error: {run_path} not found", file=sys.stderr)
        return EXIT_USER_ERROR
    try:
        artifact = RunArtifact.from_json(run_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: {run_path} is not a valid run artifact ({e})",
              file=sys.stderr)
        return EXIT_USER_ERROR
    try:
        results = [PerCaseResult.from_dict(d) for d in artifact.results]
    except (KeyError, ValueError, TypeError) as e:
        print(f"error: {run_path}: cannot decode per-case results ({e})",
              file=sys.stderr)
        return EXIT_USER_ERROR

    known_families = {r.family for r in results}
    if args.families is not None:
        families = [f.strip() for f in args.families.split(",") if f.strip()]
        families = list(dict.fromkeys(families))
        if not families:
            print("error: --families matched no families (empty filter)",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        unknown = [f for f in families if f not in known_families]
        if unknown:
            print(f"error: unknown families: {', '.join(unknown)} "
                  "(not present in the run)", file=sys.stderr)
            return EXIT_USER_ERROR
    else:
        families = sorted(known_families)
    if not families:
        print("error: no families found in the run", file=sys.stderr)
        return EXIT_USER_ERROR

    try:
        table = family_threshold_table(
            results,
            cost_false_approve=args.cost_false_approve,
            cost_false_deny=args.cost_false_deny,
            cost_review=args.cost_review,
            cost_false_unknown=args.cost_false_unknown,
            thresholds=None,
            arm=args.arm,
            families=families,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR

    sys.stdout.write(_threshold_family_text(table))
    if args.json is not None:
        out = Path(args.json)
        try:
            out.write_text(json.dumps(table, indent=2), encoding="utf-8")
        except OSError as e:
            print(f"error: cannot write threshold-family JSON to {out} ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"threshold-by-family: {out}")
    return EXIT_OK


def cmd_value(args: argparse.Namespace) -> int:
    """M-3 economic value view over 1+ run artifacts.

    Prints per-adapter expected attack cost (E_attacked) with both $/flip
    and $/incident views, the (cost, ASR) Pareto frontier, Drummond-Holte
    crossover statements, and -- when --baseline names the cheap
    reference adapter -- CPPF and break-even attack rates. Economics
    sits next to the headline ASR numbers; nothing is blended.
    """
    from peira.economics import (
        load_cost_scenario,
        value_view,
    )
    from peira.metrics import PerCaseResult

    try:
        scenario = load_cost_scenario(args.scenario)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    adapter_results: dict[str, list[PerCaseResult]] = {}
    for path_str in args.runs:
        path = Path(path_str)
        if not path.exists():
            print(f"error: {path} not found", file=sys.stderr)
            return EXIT_USER_ERROR
        try:
            artifact = RunArtifact.from_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"error: {path} is not a valid run artifact ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        if not artifact.verify():
            print(f"warning: {path_str}: analysis lock mismatch: artifact was "
                  f"modified after sealing.", file=sys.stderr)
        name = artifact.adapter_name
        if name in adapter_results:
            print(f"error: duplicate adapter {name!r} ({path_str})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        try:
            adapter_results[name] = [
                PerCaseResult.from_dict(r) for r in artifact.results
            ]
        except (KeyError, ValueError, TypeError) as e:
            print(f"error: {path_str}: cannot decode per-case results "
                  f"({e})", file=sys.stderr)
            return EXIT_USER_ERROR
    price_date = getattr(args, "price_date", None) or "unknown"
    try:
        view = value_view(
            adapter_results, scenario,
            baseline_adapter=args.baseline, price_date=price_date,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    sys.stdout.write(_value_text(view))
    if args.out is not None:
        out = Path(args.out)
        try:
            out.write_text(_value_page(view), encoding="utf-8")
        except OSError as e:
            print(f"error: cannot write value view to {out} ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"value view: {out}")
    return EXIT_OK


def _value_text(view: dict[str, Any]) -> str:
    lines = [
        f"value view (scenario: {view['scenario']} v{view['scenario_version']}, "
        f"prices: {view['price_date']})",
        "",
        "E_attacked per decision (expected attack cost):",
    ]
    for name, a in sorted(view["adapters"].items()):
        lines.append(
            f"  {name}: ${a['e_attacked_per_decision']:.4f}/decision "
            f"(${a['cost_per_flip']:.2f}/flip, "
            f"${a['cost_per_incident']:.2f}/incident, "
            f"n={a['n_eligible']})"
        )
        mult = a["attacker_cost_multiplier_jailbreak"]
        lines.append(
            f"    attacker cost per jailbreak: "
            f"{mult:.1f}x attempts" if mult is not None
            else "    attacker cost per jailbreak: never observed"
        )
        # C-9 (M-9 x M-1): attacker cost per flip in each direction.
        # The jailbreak direction renders first; it is the headline.
        _c9_order = ("deny-to-approve", "approve-to-deny", "to-abstain",
                     "to-malformed", "score-shifted", "other")
        lines.append("    attacker $/flip by direction:")
        for d in _c9_order:
            row = a["attacker_cost_per_direction"][d]
            cpf = row["cost_per_flip_usd"]
            att = row["attempts_per_flip"]
            if cpf is None:
                lines.append(f"      {d}: withheld")
            else:
                lb = "\u2265" if row["n_unpriced"] > 0 else ""
                lines.append(
                    f"      {d}: {lb}${cpf:.2f}/flip "
                    f"({att:.1f}x attempts, ASR_d {row['asr_d']:.3f}, "
                    f"n={row['n_flips_d']})"
                )
        if any(a["attacker_cost_per_direction"][d]["n_unpriced"] > 0
               for d in _c9_order):
            lines.append(
                "    ($/flip figures marked \u2265 are lower bounds: some "
                "attacked calls had no listed price)"
            )
    lines += ["", "Pareto frontier (cost, ASR):"]
    for p in view["pareto_frontier"]:
        lo, hi = p["asr_ci95"]
        mark = "FRONTIER" if p["on_frontier"] else "off-frontier"
        lines.append(
            f"  [{mark}] {p['adapter']}: ${p['cost_per_decision_usd']:.4f}, "
            f"ASR {p['asr']:.3f} [{lo:.3f}, {hi:.3f}] (n={p['n']})"
        )
    if view["cost_curve_crossovers"]:
        lines += ["", "Cost-curve crossovers:"]
        lines += [f"  - {s}" for s in view["cost_curve_crossovers"]]
    for name, c in sorted(view["comparisons"].items()):
        lines += [f"", f"{name} vs {c['vs']}:"]
        if c["prevents_flips"]:
            ci = c["cppf_ci95"]
            ci_s = f" [{ci[0]:.4f}, {ci[1]:.4f}]" if ci else " (CI unstable)"
            lines.append(f"  CPPF: ${c['cppf']:.4f}/prevented flip{ci_s}")
        else:
            lines.append("  CPPF: n/a (does not prevent flips)")
        if c["break_even_verdict"] == "at":
            ci = c["break_even_ci95"]
            ci_s = f" [{ci[0]:.3f}, {ci[1]:.3f}]" if ci else ""
            lines.append(
                f"  break-even attack rate: {c['break_even_attack_rate']:.3f}{ci_s}"
            )
        else:
            lines.append(
                f"  break-even attack rate: {c['break_even_verdict']}"
            )
    lines.append("")
    return "\n".join(lines)


def _value_page(view: dict[str, Any]) -> str:
    e = html.escape
    rows = "\n".join(
        f"<tr><td>{e(name)}</td>"
        f"<td>${a['e_attacked_per_decision']:.4f}</td>"
        f"<td>${a['cost_per_flip']:.2f}</td>"
        f"<td>${a['cost_per_incident']:.2f}</td>"
        f"<td>{a['n_eligible']}</td>"
        f"<td>{_val(a['attacker_cost_multiplier_jailbreak'])}</td></tr>"
        for name, a in sorted(view["adapters"].items())
    )
    frontier_rows = "\n".join(
        f"<tr><td>{e(p['adapter'])}</td>"
        f"<td>${p['cost_per_decision_usd']:.4f}</td>"
        f"<td>{p['asr']:.4f}</td>"
        f"<td>[{p['asr_ci95'][0]:.4f}, {p['asr_ci95'][1]:.4f}]</td>"
        f"<td>{'yes' if p['on_frontier'] else 'no'}</td></tr>"
        for p in view["pareto_frontier"]
    )
    crossovers = "".join(
        f"<li>{e(s)}</li>" for s in view["cost_curve_crossovers"]
    )
    comp_rows = "\n".join(
        f"<tr><td>{e(name)}</td><td>{e(c['vs'])}</td>"
        f"<td>{_val(c['cppf'])}</td>"
        f"<td>{c['break_even_attack_rate'] if c['break_even_attack_rate'] is not None else c['break_even_verdict']}</td></tr>"
        for name, c in sorted(view["comparisons"].items())
    )
    comp_section = (
        f"<h3>Upgrade comparisons</h3><table border=\"1\">"
        f"<tr><th>candidate</th><th>baseline</th><th>CPPF ($/prevented flip)</th>"
        f"<th>break-even attack rate</th></tr>{comp_rows}</table>"
        if comp_rows else ""
    )
    # C-9 (M-9 x M-1): attacker cost per flip in each M-1 direction,
    # one table per adapter. The jailbreak direction is the headline.
    def _fmt(x, fmt):
        return "withheld" if x is None else fmt.format(x)

    def _dir_rows(a):
        # The jailbreak direction renders first; it is the headline.
        order = ("deny-to-approve", "approve-to-deny", "to-abstain",
                 "to-malformed", "score-shifted", "other")
        out = []
        for d in order:
            row = a["attacker_cost_per_direction"][d]
            cpf = _fmt(row["cost_per_flip_usd"], "${:.2f}")
            if row["cost_per_flip_usd"] is not None and row["n_unpriced"] > 0:
                cpf = "\u2265" + cpf  # lower bound: unpriced calls at 0
            out.append(
                "<tr><td>" + e(d) + "</td>"
                "<td>" + str(row["n_flips_d"]) + "</td>"
                "<td>" + _fmt(row["asr_d"], "{:.3f}") + "</td>"
                "<td>" + _fmt(row["attempts_per_flip"], "{:.1f}x") + "</td>"
                "<td>" + cpf + "</td></tr>"
            )
        return "\n".join(out)
    def _dir_legend(a):
        if any(a["attacker_cost_per_direction"][d]["n_unpriced"] > 0
               for d in ("deny-to-approve", "approve-to-deny", "to-abstain",
                         "to-malformed", "score-shifted", "other")):
            return ("<p>A $ / flip figure marked \u2265 is a lower bound: "
                    "some attacked calls had no listed price.</p>")
        return ""
    dir_sections = "".join(
        f"<h3>Attacker cost per flip direction: {e(name)}</h3>"
        f"<p>What one successful flip of each type costs the attacker in "
        f"list-price inference spend. The jailbreak direction "
        f"(deny-to-approve) is the attacker's product.</p>"
        f"<table border=\"1\"><tr><th>direction</th><th>flips</th>"
        f"<th>ASR_d</th><th>attempts / flip</th><th>$ / flip</th></tr>"
        f"{_dir_rows(a)}</table>{_dir_legend(a)}"
        for name, a in sorted(view["adapters"].items())
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>peira value view</title></head>
<body>
<h1>peira value view</h1>
<p>Values use the {e(view['scenario'])} cost scenario (v{e(str(view['scenario_version']))}),
priced {e(view['price_date'])}. Economics sits next to the headline
ASR numbers. Nothing here is blended into them.</p>
<h2>Expected attack cost</h2>
<table border="1">
<tr><th>adapter</th><th>E_attacked ($/decision)</th><th>$/flip</th>
<th>$/incident</th><th>n</th><th>attacker cost per jailbreak (attempts)</th></tr>
{rows}
</table>
<h2>Pareto frontier (cost, ASR)</h2>
<table border="1">
<tr><th>adapter</th><th>$/decision</th><th>ASR</th><th>ASR 95% CI</th>
<th>on frontier</th></tr>
{frontier_rows}
</table>
<h2>Cost-curve crossovers</h2>
<ul>{crossovers}</ul>
{comp_section}
<h2>Attacker cost per flip direction (C-9)</h2>
{dir_sections}
</body></html>"""


def cmd_defense(args: argparse.Namespace) -> int:
    """C-4 threshold-defense economics over 1+ run artifacts.

    Prints per-adapter defense optima (the attacker-cost-aware
    operating point: threshold minimizing review spend + residual
    priced attack cost) and a compact priced risk-coverage table.
    ``--out`` writes the full per-threshold report as JSON.
    """
    from peira.economics import (
        load_cost_scenario,
        threshold_defense_report,
    )
    from peira.metrics import PerCaseResult

    try:
        scenario = load_cost_scenario(args.scenario)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    adapter_results: dict[str, list[PerCaseResult]] = {}
    for path_str in args.runs:
        path = Path(path_str)
        if not path.exists():
            print(f"error: {path} not found", file=sys.stderr)
            return EXIT_USER_ERROR
        try:
            artifact = RunArtifact.from_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"error: {path} is not a valid run artifact ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        if not artifact.verify():
            print(f"warning: {path_str}: analysis lock mismatch: artifact was "
                  f"modified after sealing.", file=sys.stderr)
        name = artifact.adapter_name
        if name in adapter_results:
            print(f"error: duplicate adapter {name!r} ({path_str})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        try:
            adapter_results[name] = [
                PerCaseResult.from_dict(r) for r in artifact.results
            ]
        except (KeyError, ValueError, TypeError) as e:
            print(f"error: {path_str}: cannot decode per-case results "
                  f"({e})", file=sys.stderr)
            return EXIT_USER_ERROR
    try:
        report = threshold_defense_report(
            adapter_results, scenario,
            review_cost_usd=args.review_cost_usd,
            attack_rate=args.attack_rate,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    sys.stdout.write(_defense_text(report))
    if args.out is not None:
        out = Path(args.out)
        try:
            out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except OSError as e:
            print(f"error: cannot write defense report to {out} ({e})",
                  file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"defense report: {out}")
    return EXIT_OK


def _defense_coverage_rows(
    risk_coverage: list[list[float]],
) -> list[tuple[float, float, float]]:
    """Compact risk-coverage table: nearest curve point per decile.

    For each target review rate 0.0..1.0, the curve point with the
    closest review rate (ties toward less residual). Deduplicated so
    unreachable targets do not repeat rows.
    """
    rows: list[tuple[float, float, float]] = []
    seen: set[float] = set()
    for i in range(11):
        target = i / 10
        rr, res = min(
            risk_coverage, key=lambda p: (abs(p[0] - target), p[1]))
        if rr in seen:
            continue
        seen.add(rr)
        rows.append((target, rr, res))
    return rows


def _defense_text(report: dict[str, Any]) -> str:
    lines = [
        f"defense view (scenario: {report['scenario']} "
        f"v{report['scenario_version']}, "
        f"review cost: ${report['review_cost_usd']:.4f}/case, "
        f"attack rate: {report['attack_rate']})",
        "",
    ]
    for name, a in sorted(report["adapters"].items()):
        if a["withheld"]:
            lines.append(f"{name}: WITHHELD: {a['reason']}")
            continue
        lines.append(
            f"{name}: n_eligible={a['n_eligible']} "
            f"n_analyzed={a['n_analyzed']} "
            f"n_always_review={a['n_always_review']}"
        )
        lines.append(
            f"  attacked-arm ECE: {a['attacked_ece']:.4f} "
            f"(n={a['ece_n']})"
        )
        auroc = a["flip_detection_auroc"]
        lines.append(
            "  flip-detection AUROC (context only): "
            + (f"{auroc:.3f}" if auroc is not None else "n/a")
        )
        lines.append(
            f"  undefended E_attacked: "
            f"${a['e_attacked_undefended']:.4f}/decision"
        )
        o = a["optimum"]
        lines.append(
            f"  optimum: pt={o['pt']:.2f} "
            f"review_rate={o['review_rate']:.3f} "
            f"residual=${o['residual_e_attacked']:.4f}/decision "
            f"review_spend=${o['review_spend_per_decision']:.4f}/decision "
            f"total=${o['total_defender_cost_per_decision']:.4f}/decision"
        )
        pvd = o["prevention_value_per_review_dollar"]
        pvd_text = (
            f"${pvd:.2f} of attack cost prevented per $1 of review"
            if pvd is not None
            else (
                "n/a (review is free)"
                if o["review_rate"] > 0
                else "n/a (optimum reviews nothing)"
            )
        )
        lines.append(f"  prevention value: {pvd_text}")
        lines.append("  priced risk-coverage "
                     "(target review rate -> residual $/decision):")
        for target, rr, res in _defense_coverage_rows(
            a["risk_coverage_curve"]
        ):
            lines.append(f"    {target:.1f} -> {rr:.3f}: ${res:.4f}")
    return "\n".join(lines) + "\n"


def cmd_runs_list(args: argparse.Namespace) -> int:
    """List runs in the registry with optional filters."""
    from peira.runs_registry import list_runs

    runs_dir = Path(args.runs_dir) if args.runs_dir else None
    # list_runs() rebuilds the index when it is stale; no explicit scan
    # here (this is a read command and must not create the runs dir).
    cache_filter = {"on": True, "off": False}.get(getattr(args, "cache", None))
    runs = list_runs(
        runs_dir,
        adapter=args.adapter,
        suite=args.suite,
        dataset_version=args.dataset_version,
        cache_enabled=cache_filter,
        termination=getattr(args, "termination", None),
        model_class=getattr(args, "model_class", None),
        checkpoint_hash=getattr(args, "checkpoint_hash", None),
        api_version=getattr(args, "api_version", None),
        call_date=getattr(args, "call_date", None),
        template_hash=getattr(args, "template_hash", None),
        case_set_tag=getattr(args, "case_set_tag", None),
    )
    if not runs:
        print("No runs found.")
        return EXIT_OK
    # Print a table. The Cache and Term columns are the leaderboard
    # segmentation labels: cache-enabled and cache-disabled runs are
    # different measurements and must never pool silently, and partial
    # (budget-terminated) runs are analyzable but never rankable.
    print(f"{'Run ID':<40} {'Adapter':<20} {'Suite':<10} "
          f"{'Dataset':<12} {'Env SHA':<10} {'Cache':<6} {'Term':<9} {'Lock':<8}")
    print("-" * 125)
    for r in runs:
        env_short = (r["env_sha256"] or "")[:8]
        lock = "valid" if r["lock_valid"] else "INVALID"
        cache = r.get("cache_enabled")
        cache_str = "on" if cache == 1 else ("off" if cache == 0 else "?")
        term = r.get("termination") or "-"
        print(f"{r['run_id']:<40} {r['adapter_name']:<20} "
              f"{r['suite']:<10} {r['dataset_version']:<12} "
              f"{env_short:<10} {cache_str:<6} {term:<9} {lock:<8}")
    print(f"\n{len(runs)} run(s) total.")
    return EXIT_OK


def cmd_runs_query(args: argparse.Namespace) -> int:
    """Per-case drill-down across runs."""
    from peira.runs_registry import query_cases

    runs_dir = Path(args.runs_dir) if args.runs_dir else None
    flipped = None
    if args.flipped:
        flipped = True
    elif args.unflipped:
        flipped = False
    eligible = True if args.eligible else None
    cases = query_cases(
        runs_dir,
        adapter=args.adapter,
        suite=args.suite,
        family=args.family,
        severity=args.severity,
        flipped=flipped,
        eligible=eligible,
        flip_direction=args.flip_direction,
        min_attacked_confidence=args.min_confidence,
        max_attacked_confidence=args.max_confidence,
        limit=args.limit,
    )
    if not cases:
        print("No cases found.")
        return EXIT_OK
    print(f"{'Case':<24} {'Adapter':<16} {'Family':<20} {'Flip':<6} "
          f"{'A-Conf':<8} {'Type':<18} {'Cost':<10}")
    print("-" * 110)
    for c in cases:
        conf = c["attacked_confidence"]
        conf_s = f"{conf:.2f}" if conf is not None else "-"
        print(f"{c['case_id']:<24} {c['adapter_name']:<16} "
              f"{c['family']:<20} {str(c['flipped']):<6} "
              f"{conf_s:<8} {c['flip_direction']:<18} "
              f"${c['cost_usd']:<9.4f}")
    print(f"\n{len(cases)} case(s).")
    return EXIT_OK


def cmd_family_summary(args: argparse.Namespace) -> int:
    """Print the adapter x family ASR matrix from the run registry.

    Rows are keyed on (adapter, version, suite, dataset version); when
    several runs share a key, the latest run wins.
    """
    from peira.families import FAMILY_IDS, display_name
    from peira.runs_registry import get_family_results

    runs_dir = Path(args.runs_dir) if args.runs_dir else None
    # get_family_results rebuilds the index when stale; no explicit
    # scan needed here.
    rows = get_family_results(
        runs_dir,
        adapter=args.adapter,
        suite=args.suite,
        dataset_version=args.dataset_version,
    )
    if not rows:
        print("No family results found in the registry.")
        return EXIT_OK

    # One entry per (name, version, suite, dataset version); families
    # in canonical order, then any non-registry families the data
    # happens to carry. Rows arrive latest-created_utc-last, so
    # repeated runs collapse to the newest one.
    adapters: dict[tuple[str, str, str, str], dict[str, dict]] = {}
    seen_families: list[str] = []
    for row in rows:
        key = (row["adapter_name"] or "", row["adapter_version"] or "",
               row["suite"] or "", row["dataset_version"] or "")
        cell = adapters.setdefault(key, {})
        fam = row["family"]
        cell[fam] = row
        if fam not in seen_families:
            seen_families.append(fam)
    families = [f for f in FAMILY_IDS if f in seen_families]
    families += [f for f in seen_families if f not in FAMILY_IDS]
    headers = [display_name(f) for f in families]

    def cell_text(cell: dict | None) -> str:
        if cell is None:
            return "n/a"
        asr = cell["asr"]
        if asr is None or isinstance(asr, bool):
            return "n/a"
        try:
            return f"{float(asr):.2f}"
        except (TypeError, ValueError):
            return "n/a"

    def row_label(key: tuple[str, str, str, str]) -> str:
        name, version, suite, ds_version = key
        label = f"{name} {version}".strip()
        detail = f"{suite} {ds_version}".strip()
        return f"{label} [{detail}]" if detail else label

    adapter_width = max(
        [len(row_label(k)) for k in adapters] + [7]
    )
    col_width = max([len(h) for h in headers] + [7])
    header = f"{'Adapter':<{adapter_width}} " + " ".join(
        f"{h:<{col_width}}" for h in headers
    )
    print(header)
    print("-" * len(header))
    for key in sorted(adapters):
        cells = [cell_text(adapters[key].get(f)) for f in families]
        print(
            f"{row_label(key):<{adapter_width}} "
            + " ".join(f"{c:<{col_width}}" for c in cells)
        )
    print(f"\n{len(adapters)} adapter run(s), {len(families)} famil(ies); "
          f"n/a = withheld (below sufficiency floors); latest run wins "
          f"per adapter/version/suite/dataset.")
    return EXIT_OK


def cmd_runs_verify(args: argparse.Namespace) -> int:
    """Verify analysis locks for run artifacts."""
    from peira.runs_registry import verify_runs

    results = verify_runs(args.paths)
    failed = 0
    for path, valid, msg in results:
        status = "OK" if valid else "FAIL"
        print(f"{status}: {path} - {msg}")
        if not valid:
            failed += 1
    if failed:
        print(f"\n{failed} of {len(results)} failed verification.",
              file=sys.stderr)
        return EXIT_USER_ERROR
    print(f"\nAll {len(results)} verified.")
    return EXIT_OK


# `peira reproduce` exit codes: 0 provenance complete (and the re-run
# matches, when --execute), 1 row not found (or the re-run cannot be
# performed in this environment), 2 provenance incomplete, 3
# reproduction mismatch.
EXIT_REPRO_MISMATCH = 3


def _leaderboard_row_id(adapter_name: Any, adapter_version: Any,
                        suite: Any, dataset_version: Any) -> str:
    """Canonical leaderboard row id.

    The same (adapter, version, suite, dataset version) key that
    `peira family-summary` collapses on, with "/" between fields.
    """
    return "/".join(str(p or "") for p in
                    (adapter_name, adapter_version, suite, dataset_version))


def _provenance_bundle(artifact: RunArtifact) -> dict[str, Any]:
    """Extract the re-run provenance bundle from a run artifact.

    Keys: adapter_revision, adapter_spec, dataset_version, seed, run_config,
    case_set, manifest_sha256. ``adapter_revision`` is the revision
    the adapter recorded in config when it records one. Otherwise it
    falls back to the pinned adapter_version, which embeds the
    revision for revision-pinned adapters (e.g. name:model@sha).
    ``adapter_spec`` is the original --adapter loader spec (e.g.
    "peira.adapters.jev:JevAdapter"), needed to reload the adapter for
    re-runs. The short adapter.name (e.g. "jev") is not loadable.
    """
    config = artifact.config
    if not isinstance(config, dict):
        config = {}
    return {
        "adapter_revision": str(
            config.get("adapter_revision") or artifact.adapter_version or ""),
        "adapter_spec": str(config.get("adapter_spec") or ""),
        "dataset_version": str(artifact.dataset_version or ""),
        "seed": artifact.seed,
        "run_config": dict(config),
        "case_set": str(artifact.suite or ""),
        "manifest_sha256": str(artifact.manifest_sha256 or ""),
    }


def _provenance_gaps(bundle: dict[str, Any]) -> list[str]:
    """Names of provenance fields missing what a re-run needs.

    An empty run_config is complete (it records "adapter
    defaults"). A non-dict is never complete. A missing seed is a gap:
    the seed is recorded on every call record, so a run without one is
    not reproducible.
    """
    gaps = []
    if not bundle["adapter_revision"]:
        gaps.append("adapter_revision")
    if not bundle["dataset_version"]:
        gaps.append("dataset_version")
    seed = bundle["seed"]
    if seed is None or isinstance(seed, bool):
        gaps.append("seed")
    if not isinstance(bundle["run_config"], dict):
        gaps.append("run_config")
    if not bundle["case_set"]:
        gaps.append("case_set")
    if not bundle["manifest_sha256"]:
        gaps.append("manifest_sha256")
    if not bundle.get("adapter_spec"):
        gaps.append("adapter_spec")
    return gaps


def _rerun_invocation(adapter_name: str, suite: str, seed: Any) -> str:
    return (f"peira run --adapter {adapter_name} --suite {suite} "
            f"--seed {seed} --out runs")


def _print_provenance(row_id: str, path: str,
                      bundle: dict[str, Any]) -> None:
    print(f"Leaderboard row: {row_id}")
    print(f"Run artifact: {path}")
    gaps = _provenance_gaps(bundle)
    print(f"Provenance bundle ({'complete' if not gaps else 'INCOMPLETE'}).")
    print(f"  adapter_revision. {bundle['adapter_revision'] or '(missing)'}")
    print(f"  adapter_spec. {bundle['adapter_spec'] or '(missing)'}")
    print(f"  dataset_version. {bundle['dataset_version'] or '(missing)'}")
    print(f"  seed. {bundle['seed']}")
    print(f"  case_set. {bundle['case_set'] or '(missing)'}")
    print(f"  manifest_sha256. {bundle['manifest_sha256'] or '(missing)'}")
    print(f"  run_config. "
          f"{json.dumps(bundle['run_config'], sort_keys=True)}")


def _repro_matches(reported: Any, lo: Any, hi: Any,
                   new_asr: Any) -> bool:
    """True when the re-run ASR reproduces the reported number.

    The bar is the row's own 95 percent CI when the row carries one.
    Without a CI the re-run must equal the reported value. The
    epsilon absorbs float formatting noise only.
    """
    eps = 1e-9
    for v in (reported, new_asr):
        if v is None or isinstance(v, bool):
            return False
    if (lo is not None and hi is not None
            and not isinstance(lo, bool) and not isinstance(hi, bool)):
        return (lo - eps) <= new_asr <= (hi + eps)
    return abs(new_asr - reported) <= eps


def cmd_reproduce(args: argparse.Namespace) -> int:
    """Verify a leaderboard row's provenance, optionally re-running it.

    The default (no --execute) is honest about re-run costs: it
    verifies provenance completeness and prints the exact invocation
    a human would use. --execute actually re-runs the adapter on the
    pinned dataset and compares the resulting ASR against the row.
    """
    from peira.runs_registry import list_runs

    raw_id = args.leaderboard_row_id
    parts = [p.strip() for p in raw_id.split("/")]
    if len(parts) != 4 or not all(parts):
        print(f"error: malformed leaderboard row id {raw_id!r}. Expected "
              f"four '/'-separated fields 'adapter/version/suite/"
              f"dataset_version' (the key `peira family-summary` "
              f"collapses on).", file=sys.stderr)
        return EXIT_USER_ERROR
    adapter_name, adapter_version, suite, dataset_version = parts
    row_id = _leaderboard_row_id(adapter_name, adapter_version, suite,
                                dataset_version)

    runs_dir = Path(args.runs_dir) if args.runs_dir else None
    runs = list_runs(runs_dir, adapter=adapter_name, suite=suite,
                     dataset_version=dataset_version)
    # list_runs orders newest first, so the first version match is the
    # latest run for this row.
    row = next(
        (r for r in runs if (r["adapter_version"] or "") == adapter_version),
        None,
    )
    if row is None:
        print(f"error: unknown leaderboard row {row_id!r}.",
              file=sys.stderr)
        known = sorted(
            {_leaderboard_row_id(r["adapter_name"], r["adapter_version"],
                                 r["suite"], r["dataset_version"])
             for r in list_runs(runs_dir)}
        )
        if known:
            print("Known rows (latest run wins per row).", file=sys.stderr)
            for k in known[:20]:
                print(f"  {k}", file=sys.stderr)
            if len(known) > 20:
                print(f"  ... and {len(known) - 20} more.",
                      file=sys.stderr)
        return EXIT_USER_ERROR

    try:
        artifact = RunArtifact.from_json(Path(row["path"]).read_text())
    except Exception as e:
        print(f"error: could not load run artifact {row['path']} ({e}).",
              file=sys.stderr)
        return EXIT_INFRA_ERROR

    bundle = _provenance_bundle(artifact)
    _print_provenance(row_id, row["path"], bundle)
    gaps = _provenance_gaps(bundle)
    if gaps:
        for field in gaps:
            print(f"error: provenance incomplete. missing field "
                  f"'{field}'.", file=sys.stderr)
        return EXIT_INFRA_ERROR

    invocation = _rerun_invocation(bundle["adapter_spec"], suite, bundle["seed"])
    if not args.execute:
        print()
        print("Provenance is complete. Re-run invocation:")
        print(f"  {invocation}")
        print(f"Dataset pin. manifest {bundle['manifest_sha256']} "
              f"(version {bundle['dataset_version']}).")
        print("The run config above is what the adapter ran with. "
              "Re-run with the same adapter version and config.")
        return EXIT_OK

    # --execute: actually re-run and compare. The re-run is scored in
    # memory only: reproduce never writes to the runs directory.
    print()
    print(f"Re-running. {invocation}")
    root = _repo_root()
    if suite not in SUITE_DIRS:
        print(f"error: unknown suite {suite!r} in the run artifact. "
              f"cannot re-run.", file=sys.stderr)
        return EXIT_USER_ERROR
    suite_dir = root / SUITE_DIRS[suite]
    try:
        local_version, local_manifest = _suite_dataset_identity(suite_dir)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    if local_manifest != bundle["manifest_sha256"]:
        print(f"error: reproduction failed. the local {suite} dataset "
              f"bytes do not match the run's pinned manifest "
              f"({bundle['manifest_sha256'][:12]}). re-running on "
              f"different bytes would not reproduce the row.",
              file=sys.stderr)
        return EXIT_REPRO_MISMATCH
    try:
        adapter = _get_adapter(bundle["adapter_spec"])
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    try:
        cases = load_cases(suite_dir)
    except ValueError as e:
        print(f"error: invalid case data. {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    if not cases:
        print(f"error: no cases found in {suite_dir}", file=sys.stderr)
        return EXIT_USER_ERROR
    run_nonce = new_run_nonce()
    if isinstance(adapter, MockAdapter):
        # Same harness wiring as `peira run`: the mock's simulation
        # script is built explicitly from the loaded cases.
        adapter = MockAdapter(
            script=MockAdapter.script_for(
                cases, seed=bundle["seed"], run_nonce=run_nonce))
    config = bundle["run_config"]
    try:
        rerun = run_suite(
            adapter, cases, suite, local_version,
            seed=bundle["seed"],
            manifest_sha256=local_manifest,
            required_families=config.get("required_families"),
            run_nonce=run_nonce,
            # Faithful reproduction includes the timeout budgets the
            # original run was measured under.
            item_timeout=config.get("item_timeout_s"),
            run_timeout=config.get("run_timeout_s"),
        )
    except Exception:
        traceback.print_exc()
        return EXIT_INFRA_ERROR

    metrics = artifact.metrics or {}
    reported = metrics.get("asr_conditional")
    ci = metrics.get("asr_ci95")
    lo, hi = None, None
    if isinstance(ci, (list, tuple)) and len(ci) == 2:
        lo, hi = ci[0], ci[1]
    new_asr = (rerun.metrics or {}).get("asr_conditional")
    if reported is None:
        print("error: reproduction failed. the leaderboard row has no "
              "reported ASR to compare against.", file=sys.stderr)
        return EXIT_REPRO_MISMATCH
    if _repro_matches(reported, lo, hi, new_asr):
        print(f"Reproduction matches. reported ASR {reported} "
              f"(95 percent CI [{lo}, {hi}]), re-run ASR {new_asr}.")
        return EXIT_OK
    print(f"error: reproduction MISMATCH. reported ASR {reported} "
          f"(95 percent CI [{lo}, {hi}]), re-run ASR {new_asr}.",
          file=sys.stderr)
    return EXIT_REPRO_MISMATCH


def _canary_scan(dataset_dir: Path, canary: str) -> list[tuple[str, bool]]:
    """Check every public case file for the permanent canary string.

    Returns (relative path, canary present) pairs, sorted. An
    unreadable file counts as missing: it cannot prove the canary.
    """
    rows = []
    for path in sorted(dataset_dir.rglob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            rows.append((str(path), False))
            continue
        rows.append((str(path), canary in text))
    return rows


def cmd_contamination_check(args: argparse.Namespace) -> int:
    """Check that every public case file carries the permanent canary.

    Public cases are assumed contaminated from day one: the canary
    lets training pipelines filter them out. The sealed holdout is
    the scoring authority and is never published, not even as IDs.
    """
    from peira.dataset import CANARY_GUID

    dataset_dir = (Path(args.dataset) if args.dataset
                   else _repo_root() / "dataset")
    if not dataset_dir.is_dir():
        print(f"error: dataset directory {dataset_dir} not found",
              file=sys.stderr)
        return EXIT_USER_ERROR
    rows = _canary_scan(dataset_dir, CANARY_GUID)
    missing = 0
    for path, present in rows:
        rel = Path(path)
        try:
            rel = rel.relative_to(_repo_root())
        except ValueError:
            pass
        status = "present" if present else "MISSING"
        print(f"canary {status}. {rel}")
        if not present:
            missing += 1
    print()
    print("Standing policy. public cases are assumed contaminated from "
          "day one: the canary lets training pipelines filter them "
          "out. The sealed 500-case holdout is the scoring authority "
          "and is never published, not even as IDs. See "
          "docs/Contamination-Policy.md.")
    if missing:
        print(f"The permanent canary ({CANARY_GUID}) must be embedded "
              f"in every public case file. {missing} file(s) are "
              f"missing it.", file=sys.stderr)
        return EXIT_USER_ERROR
    print(f"All {len(rows)} public case file(s) carry the canary.")
    return EXIT_OK


def cmd_dataset_build_manifest(args: argparse.Namespace) -> int:
    from peira.dataset import (MANIFEST_NAME, build_manifest, read_manifest,
                               write_manifest)

    dataset_dir = Path(args.dir)
    if not dataset_dir.is_dir():
        print(f"error: dataset directory {dataset_dir} not found",
              file=sys.stderr)
        return EXIT_USER_ERROR
    kind = getattr(args, "kind", "single") or "single"
    is_conversational = kind == "conversational"
    if not _SEMVER_RE.fullmatch(args.version):
        print(f"error: version {args.version!r} is not semver "
              f"(expected e.g. 1.0.0 or 0.1.0-trial); manifest not "
              f"written", file=sys.stderr)
        return EXIT_USER_ERROR
    from peira.review import critical_cases_missing_notes
    try:
        missing_notes = critical_cases_missing_notes(dataset_dir, kind=kind)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USER_ERROR
    if missing_notes:
        print(f"error: {len(missing_notes)} critical case(s) missing "
              f"severity notes; manifest not written", file=sys.stderr)
        for cid in missing_notes:
            print(f"  - {cid}: say why it earned 'critical' in the case "
                  f"notes (docs/Severity-Rubric.md)", file=sys.stderr)
        return EXIT_USER_ERROR
    if args.require_reviews:
        from peira.review import pending_reviews
        try:
            pending = pending_reviews(dataset_dir, kind=kind)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return EXIT_USER_ERROR
        if pending:
            print(f"error: {len(pending)} reviews pending; "
                  f"manifest not written", file=sys.stderr)
            for p in pending:
                print(f"  - {p['case_id']} [{p['severity']}]", file=sys.stderr)
            return EXIT_USER_ERROR
    if is_conversational:
        # The five conversational gates (CG1 schema through CG5
        # near-dedup) are enforced here, mirroring the nine-gate seal
        # for single-shot datasets: any gate error refuses the seal.
        # Warnings don't block (CG2 role-sequence warnings go to author
        # review per docs/Conversational-Suite.md).
        from peira.conversation_gates import run_conversation_gates
        gate_results = run_conversation_gates(dataset_dir)
        gate_errors = sum(len(r.errors) for r in gate_results)
        if gate_errors:
            print(f"error: {gate_errors} conversational gate error(s); "
                  f"manifest not written", file=sys.stderr)
            for r in gate_results:
                for e in r.errors:
                    print(f"  [{r.gate_id}] {e}", file=sys.stderr)
            return EXIT_USER_ERROR
    else:
        # The nine validation gates (G1 schema through G9 near-dedup) are
        # enforced here, not just documented: any gate error refuses the
        # seal. Warnings don't block (G6/G9 warnings go to the review
        # queue or human review per docs/Dataset.md). This is what makes
        # the "nine gates before sealing" claim in docs/Claims.md a
        # code-enforced invariant rather than a procedure note.
        from peira.gates import run_gates
        gate_results = run_gates(dataset_dir)
        gate_errors = sum(len(r.errors) for r in gate_results)
        if gate_errors:
            print(f"error: {gate_errors} gate error(s); "
                  f"manifest not written", file=sys.stderr)
            _print_gate_results(gate_results, file=sys.stderr)
            return EXIT_USER_ERROR
    try:
        manifest = build_manifest(dataset_dir, args.version,
                                  dataset_name=args.name,
                                  peira_version=__version__,
                                  kind=kind)
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
        # not; that would silently rewrite a released version.
        if (existing.get("dataset_version") == args.version
                and existing.get("files") != manifest["files"]):
            print(f"error: content changed since version {args.version} "
                  f"was sealed; bump the version, manifest not written",
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
    kind = getattr(args, "kind", "single") or "single"
    # review_command always exists: the parser sets review_command=None
    # by default, and the approve/reject subparsers set it via
    # dest="review_command"; no AttributeError fallback needed.
    command = args.review_command
    if command in ("approve", "reject"):
        status = "approved" if command == "approve" else "rejected"
        try:
            mark_reviewed(dataset_dir, args.id, status,
                          reviewer=args.reviewer or "",
                          notes=args.notes or "", kind=kind)
        except KeyError as e:
            print(f"error: {e}", file=sys.stderr)
            return EXIT_USER_ERROR
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return EXIT_USER_ERROR
        print(f"{args.id}: marked {status}")
        return EXIT_OK
    try:
        pending = pending_reviews(dataset_dir, kind=kind)
        cov = review_coverage(dataset_dir, kind=kind)
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
    verifies clean against the directory. Anything else is exit 1:
    a status signal, not an error (see docs/Dataset.md).
    """
    from peira.dataset import MANIFEST_NAME, verify_manifest
    from peira.review import (critical_cases_missing_notes, pending_reviews,
                              review_coverage)

    dataset_dir = Path(args.dir)
    if not dataset_dir.is_dir():
        print(f"error: dataset directory {dataset_dir} not found",
              file=sys.stderr)
        return EXIT_USER_ERROR
    kind = getattr(args, "kind", "single") or "single"
    is_conversational = kind == "conversational"

    if is_conversational:
        from peira.conversation_gates import run_conversation_gates
        results = run_conversation_gates(dataset_dir)
    else:
        from peira.gates import run_gates
        results = run_gates(dataset_dir)
    n_err = sum(len(r.errors) for r in results)
    n_warn = sum(len(r.warnings) for r in results)
    try:
        pending = pending_reviews(dataset_dir, kind=kind)
        cov = review_coverage(dataset_dir, kind=kind)
        missing_notes = critical_cases_missing_notes(dataset_dir, kind=kind)
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


def _print_gate_results(results, file=None):
    """Render gate results the way `peira dataset gates` does.

    Shared by the standalone gates command and the manifest-build
    seal path so a gate failure looks the same everywhere.
    """
    if file is None:
        file = sys.stdout
    n_err = sum(len(r.errors) for r in results)
    n_warn = sum(len(r.warnings) for r in results)
    for r in results:
        status = "pass" if r.passed else "FAIL"
        print(f"{r.gate_id} {r.name}: {status} "
              f"({len(r.errors)} errors, {len(r.warnings)} warnings)",
              file=file)
        for e in r.errors:
            print(f"  error: {e}", file=file)
        for w in r.warnings:
            print(f"  warning: {w}", file=file)
    n_pass = sum(1 for r in results if r.passed)
    print(f"gates: {n_pass}/{len(results)} passed, "
          f"{n_err} errors, {n_warn} warnings", file=file)


def cmd_dataset_gates(args: argparse.Namespace) -> int:
    kind = getattr(args, "kind", "single")

    dataset_dir = Path(args.dir)
    if not dataset_dir.is_dir():
        print(f"error: dataset directory {dataset_dir} not found",
              file=sys.stderr)
        return EXIT_USER_ERROR
    if kind == "conversational":
        from peira.conversation import run_conversation_gates
        results = run_conversation_gates(dataset_dir)
    else:
        from peira.gates import run_gates
        results = run_gates(dataset_dir)
    _print_gate_results(results)
    n_err = sum(len(r.errors) for r in results)
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
        print(f"error: no {MANIFEST_NAME} in {dataset_dir}; run "
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
    p = argparse.ArgumentParser(prog="peira", description="An open-source AI safety stress-test and intelligence hub for leading models and guardrails, including Jev, ChatGPT, Claude, DeepSeek, Kimi, Gemini, Llama Prompt Guard 2, Grok, GLM, WildGuard, ShieldGemma, Granite Guardian and Shieldstral.")
    p.add_argument("--version", action="version", version=f"peira {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run a suite through an adapter")
    r.add_argument("--adapter", default="mock",
                   help="'mock', or a dotted path: package.module (with a "
                   "top-level `adapter`), package.module:ClassName, or "
                   "package.module.ClassName. Only load adapter paths you "
                   "trust: the module is imported (and therefore executed) "
                   "with the working directory first on sys.path")
    r.add_argument("--suite", default="trial-demo",
                   choices=list(SUITE_DIRS) + ["smoke"],
                   help="smoke is an alias for trial")
    families_arg = r.add_argument("--families", default=None,
                   help="comma-separated family ids: run only cases from "
                   "these attack families (default: all families in the suite; "
                   "an empty value also means all). Subset runs are marked "
                   "ranking-ineligible (exit 3): the ranking gate always "
                   "covers the full suite.")
    # Effective default is "all families"; surface it in the generated
    # CLI reference (scripts/gen_cli_reference.py renders display_default
    # verbatim instead of the argparse default).
    families_arg.display_default = "all"
    r.add_argument("--out", default="runs")
    r.add_argument("--dry-run", action="store_true", help="validate config without scoring")
    r.add_argument("--json-progress", action="store_true", help="machine-readable progress on stdout")
    r.add_argument("--resume", action="store_true", help="resume an interrupted run")
    r.add_argument("--seed", type=int, default=0,
                   help="run seed, recorded on every call record (default: 0)")
    r.add_argument("--seeds", type=int, default=1,
                   help="M-7 multi-seed protocol: run the suite N times "
                   "under consecutive seeds (seed .. seed+N-1) and seal "
                   "a stability artifact with pass^k flip agreement and "
                   "variance decomposition. 1 (default) is a single run; "
                   "any other value must be >= 3. Paid adapters: N "
                   "multiplies spend; check the cost pilot first "
                   "(Methodology M-7)")
    r.add_argument("--max-concurrency", type=int, default=8,
                   help="cap on in-flight adapter calls; the AIMD controller "
                   "adapts within [1, N] (default: 8)")
    r.add_argument("--max-attempts", type=int, default=3,
                   help="total tries per call; retries are transient-only "
                   "(408/409/429/5xx, timeouts) (default: 3)")
    r.add_argument("--call-timeout", type=float, default=300.0,
                   help="seconds per attempt; a timeout is retried as a "
                   "transient failure (default: 300)")
    r.add_argument("--item-timeout", type=float, default=None,
                   help="wall-clock budget in seconds for one case (both "
                   "variants, all attempts); on expiry the case seals as a "
                   "timeout sample failure and the run continues "
                   "(no item budget by default)")
    r.add_argument("--run-timeout", type=float, default=None,
                   help="wall-clock budget in seconds for the whole run; "
                   "on expiry dispatch stops, in-flight cases drain to "
                   "completion, completed cases are checkpointed in a "
                   "resumable partial, and the artifact seals with "
                   "termination=timeout (analyzable, never rankable) "
                   "(no run budget by default)")
    r.add_argument("--rlimit-cpu-seconds", type=float, default=None,
                   help="process-wide CPU time backstop in seconds (Unix "
                   "only; opt-in, no limit by default)")
    r.add_argument("--rlimit-as-mb", type=float, default=None,
                   help="process-wide virtual memory cap in MB (Unix only; "
                   "opt-in, no limit by default)")
    r.add_argument("--rlimit-fsize-mb", type=float, default=None,
                   help="max size of any single file write, in MB (Unix "
                   "only; opt-in, no limit by default)")
    r.add_argument("--rlimit-nproc", type=int, default=None,
                   help="max process count for subprocess adapter "
                   "children (fork-bomb guard; Unix only, opt-in, no "
                   "limit by default; never applied to the runner "
                   "itself)")
    r.add_argument("--death-log", default=None,
                   help="path for the governor's SIGTERM/SIGINT 'last "
                   "words' JSON record (opt-in; recommended for long "
                   "unattended runs so an unexplained death leaves "
                   "evidence)")
    r.add_argument("--budget-usd", type=float, default=None,
                   help="hard spend cap in USD: the runner projects "
                   "spent + running-mean-case-cost x 1.5 before each new "
                   "case dispatch and stops dispatching when the "
                   "projection exceeds the cap; in-flight cases drain and "
                   "the artifact seals with termination=budget "
                   "(analyzable, never rankable) (default: no cap)")
    r.add_argument("--max-tokens-per-call", type=int, default=None,
                   help="per-call output-token cap. A call whose reported "
                   "tokens_out exceeds the cap is marked malformed and "
                   "excluded from scoring, and the transcript flags "
                   "token_limit_exceeded for the call (default no cap)")
    r.add_argument("--budget-grid", default=None,
                   help="EB-35 attack-strength sweep. Comma-separated "
                   "strictly increasing positive ints (e.g. 1,2,4,8,16). "
                   "Each case's attacked arm runs max(grid) queries and "
                   "the artifact records budget-to-first-flip per case "
                   "plus ASR-vs-budget curves with Wilson CIs per family. "
                   "Single-shot suites only and --seeds 1 only.")
    r.add_argument("--strength-dimension", default="attacker_queries",
                   help="EB-35 strength dimension to budget over. "
                   "Default is attacker_queries. See "
                   "`peira sweep-dimensions` for the registry.")
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

    tv = sub.add_parser("transcript-view",
                        help="render a run transcript as static HTML")
    tv.add_argument("--transcript", required=True,
                    help="transcript JSONL written by `peira run --transcript`")
    tv.add_argument("--out", required=True,
                    help="output HTML path")
    tv.set_defaults(func=cmd_transcript_view)

    v = sub.add_parser("validate", help="validate a dataset directory")
    v.add_argument("--dataset", required=True)
    v.add_argument("--kind", default="single",
                   choices=["single", "conversational"],
                   help="case schema: single-shot or conversational")
    v.set_defaults(func=cmd_validate)

    doc = sub.add_parser(
        "doctor",
        help="check local machine readiness: system, datasets, adapters",
        description="Read-only readiness check. Reports Python/RAM/disk/GPU, "
        "verifies dataset manifests, and checks each adapter's requirements "
        "(API keys are checked for presence only; values are never printed). "
        "The checks themselves make no network calls, download nothing, and "
        "write nothing; adapter discovery imports adapter modules.",
    )
    doc.set_defaults(func=cmd_doctor)

    rp = sub.add_parser("report", help="render an HTML report from a run artifact")
    rp.add_argument("--run", required=True)
    rp.add_argument("--out", default="report.html")
    rp.add_argument("--operating-threshold", type=float, default=None,
                    help="R-08 buyer-cost operating threshold in [0, 1): "
                         "review iff 1 - confidence >= threshold")
    rp.add_argument("--cost-false-approve", type=float, default=None,
                    help="R-08 buyer cost of a trusted false approve "
                         "(requires all four buyer-cost flags together)")
    rp.add_argument("--cost-false-deny", type=float, default=None,
                    help="R-08 buyer cost of a trusted false deny "
                         "(requires all four buyer-cost flags together)")
    rp.add_argument("--cost-review", type=float, default=None,
                    help="R-08 buyer cost of one human review "
                         "(requires all four buyer-cost flags together)")
    rp.add_argument("--flips-per-incident", type=float, default=None,
                    help="R-08 flips per incident for the attack-mix "
                         "cost-per-incident view (optional, renders as "
                         "withheld without it)")
    rp.set_defaults(func=cmd_report)

    cp = sub.add_parser("compare",
                        help="head-to-head statistical comparison of two run artifacts")
    cp.add_argument("run_a", help="first run artifact (A)")
    cp.add_argument("run_b", help="second run artifact (B)")
    cp.add_argument("--out", default=None,
                    help="write an HTML comparison report to this path")
    cp.add_argument("--seed", type=int, default=0,
                    help="seed for the paired-bootstrap CIs (default: 0)")
    cp.add_argument("--nb-threshold", type=float, default=None,
                    help="operating threshold in [0, 1) for the R-08 "
                         "net-benefit head-to-head: which adapter has the "
                         "higher net benefit at this threshold")
    cp.set_defaults(func=cmd_compare)

    # M-7: stability analysis over existing run artifacts, and
    # drift-watch between two runs of the same adapter id.
    st = sub.add_parser("stability",
                        help="k-seed stability analysis (pass^k, variance "
                        "decomposition) over existing run artifacts")
    st.add_argument("runs", nargs="+",
                    help="two or more run artifacts from the same "
                    "adapter/suite (different seeds)")
    st.add_argument("--out", default=None,
                    help="write a sealed stability artifact JSON to this path")
    st.set_defaults(func=cmd_stability)

    sw = sub.add_parser("sweep-report",
                        help="render EB-35 attack-strength sweep curves "
                        "from a sweep run artifact")
    sw.add_argument("artifact",
                    help="sweep run artifact JSON (from "
                    "`peira run --budget-grid ...`)")
    sw.add_argument("--format", choices=("text", "json"), default="text",
                    help="text renders per-family ASR-vs-budget tables. "
                    "json emits the sealed sweep summary. Default is text.")
    sw.set_defaults(func=cmd_sweep_report)

    sd = sub.add_parser("sweep-dimensions",
                        help="list the EB-35 strength-dimension registry "
                        "and each dimension's implementation status")
    sd.set_defaults(func=cmd_sweep_dimensions)

    dw = sub.add_parser("drift-watch",
                        help="drift-watch: per-family McNemar deltas between "
                        "two runs of the same adapter id, reporting "
                        "newly-flipping vs newly-fixed cases")
    dw.add_argument("--old", required=True,
                    help="older run artifact (baseline)")
    dw.add_argument("--new", required=True,
                    help="newer run artifact (candidate)")
    dw.add_argument("--out", default=None,
                    help="write the drift result JSON to this path")
    dw.set_defaults(func=cmd_drift_watch)

    # R-04 stability probe: separate track, separate report.
    sp = sub.add_parser("stability-probe",
                        help="stability-probe: ~100 cases x 3 trials per "
                        "adapter version, reporting attacked-arm pass^k "
                        "and a stability score next to accuracy")
    sp.add_argument("--adapter", required=True,
                    help="adapter: 'mock' or a dotted path like "
                    "'examples.minimal_adapter'")
    sp.add_argument("--suite", default="trial",
                    help="suite to probe (default: trial); single-shot "
                    "suites only")
    sp.add_argument("--out", required=True,
                    help="output directory for stability-probe.json and "
                    "borderline_cases.json")
    sp.add_argument("--cases", type=int, default=None,
                    help="cases in the probe slice (default: 100)")
    sp.add_argument("--trials", type=int, default=3,
                    help="trials per case (default: 3; minimum: 2)")
    sp.add_argument("--seed", type=int, default=0,
                    help="base seed; trial seeds are seed .. seed+trials-1")
    sp.add_argument("--families", default=None,
                    help="family filter (same syntax as `peira run`)")
    sp.add_argument("--max-concurrency", type=int, default=4,
                    help="max concurrent calls per trial")
    sp.add_argument("--max-attempts", type=int, default=3,
                    help="max attempts per call")
    sp.add_argument("--call-timeout", type=float, default=30.0,
                    help="per-call timeout in seconds")
    sp.set_defaults(func=cmd_stability_probe)

    # Dashboard data layer: artifact -> dashboard-ready JSON.
    db = sub.add_parser("dashboard",
                        help="export dashboard-ready JSON from run artifacts")
    dsub = db.add_subparsers(dest="dashboard_command", required=True)
    dbr = dsub.add_parser("run",
                          help="one run's complete dashboard payload")
    dbr.add_argument("run", help="run artifact path")
    dbr.add_argument("--out", default=None,
                     help="write JSON to this path (default: stdout)")
    dbr.set_defaults(func=cmd_dashboard_run)
    dbl = dsub.add_parser("leaderboard",
                          help="cross-adapter leaderboard JSON")
    dbl.add_argument("--runs-dir", default=None,
                     help="runs directory (default: ./runs or $PEIRA_RUNS_DIR)")
    dbl.add_argument("--suite", default=None, help="filter by suite")
    dbl.add_argument("--dataset-version", default=None,
                     help="filter by dataset version")
    dbl.add_argument("--out", default=None,
                     help="write JSON to this path (default: stdout)")
    dbl.set_defaults(func=cmd_dashboard_leaderboard)
    dbc = dsub.add_parser("compare",
                          help="head-to-head comparison as dashboard JSON")
    dbc.add_argument("run_a", help="first run artifact (A)")
    dbc.add_argument("run_b", help="second run artifact (B)")
    dbc.add_argument("--seed", type=int, default=0,
                     help="seed for the paired-bootstrap CIs (default: 0)")
    dbc.add_argument("--out", default=None,
                     help="write JSON to this path (default: stdout)")
    dbc.set_defaults(func=cmd_dashboard_compare)

    hd = sub.add_parser("hardness",
                        help="M-4 hardness/transfer diagnostics over 2+ run artifacts "
                        "(diagnostic tables, never rankings)")
    hd.add_argument("runs", nargs="+", help="run artifact paths (>= 2)")
    hd.add_argument("--out", default=None,
                    help="write the diagnostic tables to this path")
    hd.set_defaults(func=cmd_hardness)

    # EB Tier 1: external-benchmark analyses (Program A).
    tx = sub.add_parser(
        "tax",
        help="EB-40: cross-adapter robustness-tax diagnostics "
        "(accuracy/calibration/combined taxes, ASR-tax correlations)",
    )
    tx.add_argument("runs", nargs="+",
                    help="run artifact paths (>= 2, one per adapter)")
    tx.add_argument("--out", default=None,
                    help="write the text report to this path "
                    "(default: stdout)")
    tx.add_argument("--json", default=None,
                    help="write the full tax analysis JSON to this path")
    tx.set_defaults(func=cmd_tax)

    er = sub.add_parser(
        "erosion",
        help="EB-23: confidence-erosion distribution on failed attacks "
        "(per-family and overall)",
    )
    er.add_argument("run", help="run artifact path")
    er.add_argument("--out", default=None,
                    help="write the text report to this path "
                    "(default: stdout)")
    er.set_defaults(func=cmd_erosion)

    ln = sub.add_parser(
        "length",
        help="EB-7/EB-10: length-sensitivity analysis and "
        "length de-confounding diagnostics for one run artifact",
    )
    ln.add_argument("run", help="run artifact path")
    ln.add_argument("--out", default=None,
                    help="write the text report to this path "
                    "(default: stdout)")
    ln.set_defaults(func=cmd_length)

    lt = sub.add_parser(
        "lottery",
        help="leave-one-family-out ranking stability (lottery index) "
        "across run artifacts",
    )
    lt.add_argument("runs", nargs="+", help="run artifact files (one row "
                    "per adapter on the leaderboard)")
    lt_families = lt.add_argument(
        "--families", default=None,
        help="comma-separated family manifest (default: union of "
        "families across the runs)",
    )
    lt_families.display_default = "union of families in runs"
    lt.add_argument("--json", default=None,
                    help="write the full analysis JSON to this path")
    lt.add_argument("--economic", action="store_true",
                    help="C-6: report the pair (robustness-stability, "
                    "economic-stability) with the economic lottery index "
                    "per cost scenario, instead of the robustness index alone")
    lt.add_argument("--scenario", default=None,
                    help="cost scenario id for --economic "
                    "(default: all scenarios)")
    lt.set_defaults(func=cmd_lottery)

    st = sub.add_parser(
        "saturation",
        help="per-family saturation/retirement analysis (C-10) "
        "across run artifacts",
    )
    st.add_argument("runs", nargs="+", help="run artifact files (one row "
                    "per adapter on the leaderboard)")
    st_families = st.add_argument(
        "--families", default=None,
        help="comma-separated family manifest (default: union of "
        "families across the runs)",
    )
    st_families.display_default = "union of families in runs"
    st.add_argument("--holdout-families", default=None,
                    help="comma-separated families treated as holdout "
                    "(state reported, action capped at monitor)")
    st.add_argument("--releases-observed", type=int, default=1,
                    help="consecutive releases the exhaustion trigger has "
                    "held (default: 1; retirement eligibility needs 2 "
                    "plus the variant-flip check)")
    st.add_argument("--json", default=None,
                    help="write the full analysis JSON to this path")
    st.set_defaults(func=cmd_saturation)

    vv = sub.add_parser("value",
                        help="M-3 economic value view over 1+ run artifacts "
                        "(E_attacked, CPPF, break-even, Pareto frontier)")
    vv.add_argument("runs", nargs="+", help="run artifact paths (>= 1)")
    vv.add_argument("--scenario", default="standard",
                    help="cost scenario id (default: standard)")
    vv.add_argument("--baseline", default=None,
                    help="baseline adapter name for CPPF / break-even comparisons")
    vv.add_argument("--price-date", default=None,
                    help="price date stamp for the frontier (default: unknown)")
    vv.add_argument("--out", default=None,
                    help="write an HTML value-view report to this path")
    vv.set_defaults(func=cmd_value)

    # C-7 threshold-by-family interaction.
    tf = sub.add_parser(
        "threshold-by-family",
        help="C-7: optimal review threshold per family under buyer-cost "
        "economics (family-specific vs global threshold interaction)",
    )
    tf.add_argument("run", help="run artifact path")
    tf.add_argument("--cost-false-approve", type=float, required=True,
                    help="USD cost of trusting a wrongly-approved decision")
    tf.add_argument("--cost-false-deny", type=float, required=True,
                    help="USD cost of trusting a wrongly-denied decision")
    tf.add_argument("--cost-review", type=float, required=True,
                    help="USD cost of one human review")
    tf.add_argument("--cost-false-unknown", type=float, default=None,
                    help="USD cost of trusting a wrongly-decided case whose "
                    "direction is unavailable (default: mean of the two "
                    "directional costs)")
    tf.add_argument("--families", default=None,
                    help="comma-separated family manifest (default: all "
                    "families in the run)")
    tf.add_argument("--arm", default="attacked",
                    choices=("attacked", "benign"),
                    help="which arm to price (default: attacked)")
    tf.add_argument("--json", default=None,
                    help="write the full interaction table JSON to this path")
    tf.set_defaults(func=cmd_threshold_by_family)


    # C-4 threshold-defense economics.
    df = sub.add_parser("defense",
                        help="C-4 threshold-defense economics over 1+ run "
                        "artifacts (defense curves, priced risk-coverage, "
                        "attacker-cost-aware optimum)")
    df.add_argument("runs", nargs="+", help="run artifact paths (>= 1)")
    df.add_argument("--scenario", default="standard",
                    help="cost scenario id (default: standard)")
    df.add_argument("--review-cost-usd", type=float, default=0.0,
                    help="human review cost per case in USD "
                    "(default: 0.0)")
    df.add_argument("--attack-rate", type=float, default=None,
                    help="fraction of decisions under attack "
                    "(default: scenario baseline)")
    df.add_argument("--out", default=None,
                    help="write the full defense report as JSON to this path")
    df.set_defaults(func=cmd_defense)

    # Run registry (Layer 5a): index and query run artifacts.
    rr = sub.add_parser("runs", help="run registry: list and verify artifacts")
    rsub = rr.add_subparsers(dest="runs_command", required=True)
    rl = rsub.add_parser("list", help="list runs in the registry")
    rl.add_argument("--runs-dir", default=None,
                    help="runs directory (default: ./runs or $PEIRA_RUNS_DIR)")
    rl.add_argument("--adapter", default=None,
                    help="filter by adapter name")
    rl.add_argument("--suite", default=None,
                    help="filter by suite")
    rl.add_argument("--dataset-version", default=None,
                    help="filter by dataset version")
    rl.add_argument("--cache", default=None, choices=("on", "off"),
                    help="filter by cache state (on/off)")
    rl.add_argument("--termination", default=None,
                    help="filter by termination state "
                         "(complete, budget, partial, ...)")
    # M-7 longitudinal filters: key a rerun comparison on the exact
    # provenance that makes two runs comparable.
    rl.add_argument("--model-class", default=None,
                    help="filter by adapter model class "
                    "(llm-baseline, guardrail, rule-based, ...)")
    rl.add_argument("--checkpoint-hash", default=None,
                    help="filter by pinned model revision")
    rl.add_argument("--api-version", default=None,
                    help="filter by provider API version")
    rl.add_argument("--call-date", default=None,
                    help="filter by run UTC date (YYYY-MM-DD)")
    rl.add_argument("--template-hash", default=None,
                    help="filter by prompt-template hash")
    rl.add_argument("--case-set-tag", default=None,
                    help="filter by case-set tag (suite id)")
    rl.set_defaults(func=cmd_runs_list)
    rv = rsub.add_parser("verify", help="verify analysis locks")
    rv.add_argument("paths", nargs="+", help="artifact paths to verify")
    rv.set_defaults(func=cmd_runs_verify)
    rq = rsub.add_parser("query",
                         help="per-case drill-down across runs "
                         "(e.g. flipped cases on a family with high confidence)")
    rq.add_argument("--runs-dir", default=None,
                    help="runs directory (default: ./runs or $PEIRA_RUNS_DIR)")
    rq.add_argument("--adapter", default=None, help="filter by adapter name")
    rq.add_argument("--suite", default=None, help="filter by suite")
    rq.add_argument("--family", default=None, help="filter by attack family")
    rq.add_argument("--severity", default=None, help="filter by severity")
    flip_group = rq.add_mutually_exclusive_group()
    flip_group.add_argument("--flipped", action="store_true", default=None,
                            help="only flipped cases")
    flip_group.add_argument("--unflipped", action="store_true", default=None,
                            help="only non-flipped cases")
    rq.add_argument("--eligible", action="store_true", default=None,
                    help="only eligible cases")
    rq.add_argument("--flip-direction", default=None,
                    choices=list(FLIP_DIRECTIONS),
                    help="filter by flip direction")
    rq.add_argument("--min-confidence", type=float, default=None,
                    help="minimum attacked confidence")
    rq.add_argument("--max-confidence", type=float, default=None,
                    help="maximum attacked confidence")
    rq.add_argument("--limit", type=int, default=100,
                    help="max rows (default: 100, 0 = no cap)")
    rq.set_defaults(func=cmd_runs_query)

    fs = sub.add_parser(
        "family-summary",
        help="adapter x family ASR matrix from the run registry "
        "(latest run wins per adapter/version/suite/dataset)",
    )
    fs_runs_dir = fs.add_argument("--runs-dir", default=None,
                    help="runs directory (default: ./runs or $PEIRA_RUNS_DIR)")
    fs_runs_dir.display_default = "`./runs`"
    fs_adapter = fs.add_argument("--adapter", default=None,
                    help="filter by adapter name")
    fs_adapter.display_default = "all"
    fs_suite = fs.add_argument("--suite", default=None,
                    help="filter by suite")
    fs_suite.display_default = "all"
    fs_dataset = fs.add_argument("--dataset-version", default=None,
                    help="filter by dataset version")
    fs_dataset.display_default = "all"
    # display_default: the effective defaults (None = no filter, i.e. all
    # values) rendered verbatim by scripts/gen_cli_reference.py so the
    # generated CLI reference shows accurate defaults.
    fs.set_defaults(func=cmd_family_summary)

    rp = sub.add_parser(
        "reproduce",
        help="verify a leaderboard row's provenance, optionally re-run it",
        description="Resolve a leaderboard row id to its run artifact, "
        "verify the provenance bundle is complete, and (without --execute) "
        "print the exact re-run invocation. With --execute, re-run the "
        "adapter on the pinned dataset with the pinned seed and compare "
        "the ASR against the row's reported ASR.",
    )
    rp.add_argument("leaderboard_row_id",
                    help="row id as adapter/version/suite/dataset_version "
                    "(the key peira family-summary collapses on)")
    rp.add_argument("--runs-dir", default=None,
                    help="runs directory (default is ./runs or "
                    "$PEIRA_RUNS_DIR)")
    rp.add_argument("--execute", action="store_true",
                    help="actually re-run the adapter and compare ASR "
                    "(default is provenance check plus the re-run "
                    "invocation only)")
    rp.set_defaults(func=cmd_reproduce)

    cc = sub.add_parser(
        "contamination-check",
        help="check public case files for the permanent canary",
        description="Scan every public case file under the dataset "
        "directory for the permanent canary string. Public cases are "
        "assumed contaminated from day one. Exits 1 when any file is "
        "missing the canary.",
    )
    cc.add_argument("--dataset", default=None,
                    help="dataset directory (default is the repo's "
                    "dataset directory)")
    cc.set_defaults(func=cmd_contamination_check)

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
    bm.add_argument("--kind", choices=("single", "conversational"),
                    default="single",
                    help="case schema: single-shot (default) or conversational")
    bm.set_defaults(func=cmd_dataset_build_manifest)
    vm = dsub.add_parser("verify-manifest",
                         help="verify a dataset directory against its manifest.json")
    vm.add_argument("--dir", required=True, help="dataset directory")
    vm.set_defaults(func=cmd_dataset_verify_manifest)
    g = dsub.add_parser("gates", help="run the automated validation gates")
    g.add_argument("--dir", required=True, help="dataset directory")
    g.add_argument("--kind", default="single",
                   choices=["single", "conversational"],
                   help="case schema: single-shot or conversational")
    g.set_defaults(func=cmd_dataset_gates)
    n = dsub.add_parser("new", help="scaffold a new case from a family template")
    n.add_argument("--family", required=True, choices=sorted(TEMPLATES),
                   help="attack family")
    n.add_argument("--id", required=True, help="case id, e.g. sp-042")
    n.add_argument("--severity", default="medium",
                   choices=["critical", "high", "medium", "low"])
    n.add_argument("--primitive", default=None,
                   choices=["choice", "score", "abstain"],
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
    rv.add_argument("--kind", choices=("single", "conversational"),
                    default="single",
                    help="case schema: single-shot (default) or conversational")
    rv.set_defaults(func=cmd_dataset_review, review_command=None)
    rvsub = rv.add_subparsers(dest="review_command")
    for sub_name, sub_help in (("approve", "mark a case reviewed and approved"),
                               ("reject", "mark a case reviewed and rejected")):
        sp = rvsub.add_parser(sub_name, parents=[dir_req], help=sub_help)
        sp.add_argument("--id", required=True, help="case id")
        sp.add_argument("--reviewer", default="",
                        help="who reviewed (name or initials)")
        sp.add_argument("--notes", default="", help="review notes")
        sp.add_argument("--kind", choices=("single", "conversational"),
                        default="single",
                        help="case schema: single-shot (default) or conversational")
        sp.set_defaults(func=cmd_dataset_review)
    st = dsub.add_parser("status", parents=[dir_req],
                         help="pipeline status: gates, review queue, manifest")
    st.add_argument("--kind", choices=("single", "conversational"),
                    default="single",
                    help="case schema: single-shot (default) or conversational")
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
