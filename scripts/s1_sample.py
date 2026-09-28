#!/usr/bin/env python3
"""Seeded stratified sampler for the S-1 re-audit (protocol section 4).

Draws a fixed number of cases per family with random.Random(seed),
uniform without replacement within each family file. The exclusion
set is NEVER invented by this script: --exclude must point at a
committed s1/exclusions.json (assembling it, from the audit's 50
sampled IDs plus the IDs of cases PR-5 corrected in place, is an
explicit pre-step per protocol section 10), and the script fails
loudly if the file is missing or malformed.

Determinism: the draw depends only on the seed, the per-family
count, the family-file line order, and the exclusion list. The
output manifest records all of these, so the draw is reproducible.
The manifest carries a draw timestamp; pass --timestamp to override
it, which makes the output byte-identical across runs with the same
inputs (used by the determinism tests).

Cross-version note: random.Random's exact sample() sequence is
stable in practice but only random() is guaranteed stable across
CPython versions; the manifest records the PRNG name for this
reason. Reproduce with the same interpreter version for
byte-identical results.

Usage:
    scripts/s1_sample.py --seed 20260928 --per-family 20 \\
        --exclude s1/exclusions.json --out s1/reaudit_sample.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s1_common as C  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_family_frames(cases_dir: Path) -> dict[str, list[str]]:
    """Map family -> ordered case IDs, in JSONL line order per family file."""
    frames: dict[str, list[str]] = {}
    for path in sorted(cases_dir.glob("*.jsonl")):
        family = path.stem
        ids: list[str] = []
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                case = json.loads(line)
                cid = case.get("case_id")
                if not cid:
                    raise ValueError(f"{path.name}:{lineno}: missing case_id")
                ids.append(cid)
        if family in frames:
            raise ValueError(f"duplicate family file for {family}")
        frames[family] = ids
    if not frames:
        raise ValueError(f"no family JSONL files in {cases_dir}")
    return frames


def load_exclusions(path: Path) -> dict:
    """Load and validate the committed exclusion set."""
    if not path.is_file():
        raise SystemExit(
            f"error: exclusions file not found: {path}\n"
            "Assembling s1/exclusions.json (the audit's 50 sampled IDs plus "
            "the IDs of cases PR-5 corrected in place) is an explicit "
            "pre-step: the file must be committed before sampling so the "
            "exclusion set is auditable. This script never invents it."
        )
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"error: {path} is not valid JSON: {e}")
    excluded = doc.get("excluded_ids")
    if not isinstance(excluded, list) or not excluded:
        raise SystemExit(
            f"error: {path} must contain a non-empty 'excluded_ids' list"
        )
    if len(set(excluded)) != len(excluded):
        raise SystemExit(f"error: {path} 'excluded_ids' contains duplicates")
    return {"excluded_ids": sorted(set(excluded)), "sources": doc.get("sources", {})}


def draw_sample(
    frames: dict[str, list[str]],
    excluded: set[str],
    seed: int,
    per_family: int,
) -> dict[str, list[str]]:
    """Seeded stratified draw: per_family IDs per family, without replacement.

    Excluded IDs are removed from each family's frame first, so
    replacements for excluded IDs are drawn automatically from the
    same family.
    """
    rng = random.Random(seed)
    sample: dict[str, list[str]] = {}
    for family in sorted(frames):
        frame = [cid for cid in frames[family] if cid not in excluded]
        if len(frame) < per_family:
            raise SystemExit(
                f"error: family {family}: frame has {len(frame)} eligible "
                f"cases after exclusions, need {per_family}"
            )
        sample[family] = rng.sample(frame, per_family)
    return sample


def build_manifest(
    sample: dict[str, list[str]],
    frames: dict[str, list[str]],
    exclusions: dict,
    seed: int,
    per_family: int,
    cases_dir: Path,
    exclusions_path: Path,
    timestamp: str | None,
) -> dict:
    cases = [
        {"case_id": cid, "family": family}
        for family in sorted(sample)
        for cid in sample[family]
    ]
    return {
        "tool": "scripts/s1_sample.py",
        "protocol": "S-1 re-grade protocol (2026-09-28), section 4",
        "seed": seed,
        "prng": "random.Random (CPython stdlib Mersenne Twister)",
        "per_family": per_family,
        "cases_dir": str(cases_dir),
        "family_files": {
            family: f"{family}.jsonl" for family in sorted(frames)
        },
        "family_file_order": "JSONL line order within each family file",
        "frames": {family: frames[family] for family in sorted(frames)},
        "exclusions_file": str(exclusions_path),
        "excluded_ids": exclusions["excluded_ids"],
        "exclusion_sources": exclusions["sources"],
        "n_excluded": len(exclusions["excluded_ids"]),
        "drawn_utc": timestamp or C.utc_now(),
        "n": len(cases),
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, required=True,
                   help="RNG seed (protocol fixes 20260928)")
    p.add_argument("--per-family", type=int, required=True,
                   help="cases per family (protocol fixes 20)")
    p.add_argument("--exclude", required=True,
                   help="committed s1/exclusions.json (never invented)")
    p.add_argument("--out", required=True, help="output sample manifest JSON")
    p.add_argument("--cases", default=str(REPO_ROOT / "dataset" / "v1" / "cases"),
                   help="dataset cases directory")
    p.add_argument("--timestamp", default=None,
                   help="override draw timestamp (for byte-identical reruns)")
    args = p.parse_args(argv)

    if args.per_family < 1:
        raise SystemExit("error: --per-family must be >= 1")

    cases_dir = Path(args.cases)
    if not cases_dir.is_dir():
        raise SystemExit(f"error: cases directory not found: {cases_dir}")

    frames = load_family_frames(cases_dir)
    exclusions = load_exclusions(Path(args.exclude))
    sample = draw_sample(frames, set(exclusions["excluded_ids"]),
                         args.seed, args.per_family)
    manifest = build_manifest(
        sample, frames, exclusions, args.seed, args.per_family,
        cases_dir, Path(args.exclude), args.timestamp,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"wrote {out}: n={manifest['n']} "
          f"({args.per_family}/family x {len(frames)} families), "
          f"excluded={manifest['n_excluded']}, seed={args.seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
