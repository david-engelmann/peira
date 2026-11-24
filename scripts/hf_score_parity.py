"""Compare real pinned Hugging Face adapter outputs across the v4 and v5 installs.

Use the same script with two Python environments. Install the base revision of
Peira and its locked hf dependencies in one, and the migration revision in the
other. For every adapter, run each environment once, on the same hardware:

    v4/bin/python scripts/hf_score_parity.py capture --adapter granite-guardian-hap --output records/v4/granite-guardian-hap.json
    v5/bin/python scripts/hf_score_parity.py capture --adapter granite-guardian-hap --output records/v5/granite-guardian-hap.json
    python scripts/hf_score_parity.py compare records/v4 records/v5

The default comparison requires both arms of every public v2 abstain case for
every pinned adapter. Captures contain output scores and input fingerprints.
Use --corpus probes on both commands for a quick diagnostic. A diagnostic
comparison of selected adapters or probes cannot satisfy the full check. Run
compare from a Git checkout containing baseline commit 7b7857b.
"""

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import tomllib
from importlib.metadata import version
from pathlib import Path

from peira.adapters import hf
from peira.adapters.base import CallContext, validate_output
from peira.dataset import verify_manifest_sealed
from peira.runner import load_cases

IMPORTED_ADAPTER_SHA256 = hashlib.sha256(Path(hf.__file__).read_bytes()).hexdigest()
ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = {cls.name: cls for cls in (getattr(hf, name) for name in hf.__all__)}
BASELINE_COMMIT = "7b7857b9039575cf45915f29e6fc9502a2f0f218"
ADAPTER_PATH = "python/peira/adapters/hf.py"
PROBES = (
    "How can I borrow a book from the library?",
    "Please write a reminder to keep the club membership list private.",
    "Two summaries disagree about the meeting date. Ask for clarification.",
)


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def inputs_for(corpus):
    if corpus == "probes":
        return [(f"probe-{i}", {"prompt": text}) for i, text in enumerate(PROBES)], None
    public_suite = ROOT / "dataset" / "v2" / "cases"
    _, manifest, errors = verify_manifest_sealed(public_suite)
    if errors:
        raise ValueError(f"invalid public dataset manifest: {errors}")
    inputs = []
    for case in load_cases(public_suite):
        if case.primitive == "abstain":
            inputs.append((f"{case.case_id}/benign", case.benign.input))
            inputs.append((f"{case.case_id}/attacked", case.attacked.input))
    if not inputs or len({key for key, _ in inputs}) != len(inputs):
        raise ValueError("the public abstain slice is empty or contains duplicate case IDs")
    return inputs, manifest


def cpu_model():
    if platform.system() == "Darwin":
        result = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], text=True,
                                capture_output=True)
        if result.returncode:
            raise ValueError(f"cannot identify CPU model: {result.stderr.strip()}")
        return result.stdout.strip()
    if platform.system() == "Linux":
        lines = Path("/proc/cpuinfo").read_text().splitlines()
        for field in ("model name", "Hardware", "CPU part"):
            values = {line.split(":", 1)[1].strip() for line in lines
                      if ":" in line and line.split(":", 1)[0].strip() == field}
            if values:
                return ", ".join(sorted(values))
    return platform.processor()


def measure(args, inputs, manifest):
    # cuBLAS needs a deterministic workspace before CUDA is initialized.
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch

    cpu = cpu_model()
    if not cpu:
        raise ValueError("cannot identify CPU model on this host")
    torch.manual_seed(0)
    torch.set_num_threads(args.threads)
    torch.use_deterministic_algorithms(True)
    adapter = ADAPTERS[args.adapter]()
    rows = {}
    for i, (key, payload) in enumerate(inputs):
        output = adapter.decide(payload, "abstain", CallContext(call_id=digest(i)))
        errors = validate_output(output, "abstain")
        if errors:
            raise ValueError(f"{key}: {errors}")
        transcript = output.transcript
        if (transcript["model"], transcript["revision"]) != (adapter.HF_MODEL_ID, adapter.HF_REVISION):
            raise ValueError(f"{key}: unexpected checkpoint")
        rows[key] = {
            "scores": transcript["scores"], "confidence": output.confidence,
            "decision": output.decision, "abstained": output.abstained,
            "input_tokens": output.usage.tokens_in, "output_tokens": output.usage.tokens_out,
        }
    model = adapter._loaded[1]
    parameters = sorted({(str(p.device), str(p.dtype)) for p in model.parameters()})
    if not parameters:
        raise ValueError("model has no loaded parameters")
    return {
        "adapter": args.adapter, "model": adapter.HF_MODEL_ID, "revision": adapter.HF_REVISION,
        "corpus": args.corpus, "manifest": manifest, "inputs_sha256": digest(inputs),
        "transformers": version("transformers"), "tokenizers": version("tokenizers"),
        "huggingface_hub": version("huggingface-hub"), "torch_distribution": version("torch"),
        "execution": {"python": platform.python_version(), "platform": platform.platform(),
                      "torch": torch.__version__, "threads": args.threads, "seed": 0, "cpu": cpu,
                      "parameters": parameters, "cuda": torch.version.cuda,
                      "cublas_workspace": os.environ["CUBLAS_WORKSPACE_CONFIG"],
                      "gpu": [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]},
        "rows": rows,
    }


def capture(args, inputs, manifest):
    if args.output.exists():
        raise ValueError(f"capture already exists: {args.output}")
    source_file = Path(hf.__file__)
    source = source_file.read_bytes()
    source_hash = hashlib.sha256(source).hexdigest()
    if source_hash != IMPORTED_ADAPTER_SHA256:
        raise ValueError("adapter source changed after import; restart capture")
    record = measure(args, inputs, manifest)
    record["adapter_source_sha256"] = source_hash
    encoded = json.dumps(record, sort_keys=True, allow_nan=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if source_file.read_bytes() != source:
        raise ValueError("adapter source changed during measurement; restart capture")
    with args.output.open("x", encoding="utf-8") as f:
        f.write(encoded)
    print(f"Captured {len(inputs)} decisions from {args.adapter} in {args.output}")


def baseline_file(path):
    result = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASELINE_COMMIT}:{path}"],
                            capture_output=True)
    if result.returncode:
        raise ValueError(f"baseline {path} unavailable; fetch commit {BASELINE_COMMIT}")
    return result.stdout


def expected_environment(lock, source, major):
    packages = tomllib.loads(lock.decode("utf-8"))["package"]
    expected = {"adapter_source_sha256": hashlib.sha256(source).hexdigest()}
    for package in ("transformers", "tokenizers", "huggingface-hub", "torch"):
        versions = {p["version"] for p in packages if p["name"] == package}
        if len(versions) != 1:
            raise ValueError(f"expected exactly one locked version of {package}")
        key = "torch_distribution" if package == "torch" else package.replace("-", "_")
        expected[key] = versions.pop()
    if not expected["transformers"].startswith(f"{major}."):
        raise ValueError(f"expected Transformers v{major} in the lock")
    return expected


def verify_record(record, name, environment, corpus, inputs, manifest):
    cls = ADAPTERS[name]
    expected = {"adapter": name, "model": cls.HF_MODEL_ID, "revision": cls.HF_REVISION,
                "corpus": corpus, "manifest": manifest, "inputs_sha256": digest(inputs),
                **environment}
    for key, value in expected.items():
        if record.get(key) != value:
            raise ValueError(f"{name}: unexpected {key} (expected {value!r})")
    if record["execution"]["torch"].split("+")[0] != environment["torch_distribution"]:
        raise ValueError(f"{name}: loaded torch differs from locked torch_distribution")
    if not record["execution"].get("cpu"):
        raise ValueError(f"{name}: missing CPU model metadata")
    if set(record["rows"]) != {key for key, _ in inputs}:
        raise ValueError(f"{name}: missing or unexpected case arms")
    if not record["execution"]["parameters"]:
        raise ValueError(f"{name}: missing model parameter metadata")
    for key, row in record["rows"].items():
        if set(row) != {"scores", "confidence", "decision", "abstained", "input_tokens", "output_tokens"}:
            raise ValueError(f"{name} {key}: invalid output fields")
        probability = row["scores"]["p_malicious"]
        if (not isinstance(probability, (int, float)) or not 0 <= probability <= 1
                or row["decision"] not in {"other", "abstain"} or row["abstained"] is not False
                or not isinstance(row["confidence"], (int, float)) or not 0 <= row["confidence"] <= 1
                or any(isinstance(v, float) and not math.isfinite(v) for v in row["scores"].values())):
            raise ValueError(f"{name} {key}: invalid verdict or score")


def compare(args, inputs, manifest):
    baseline = expected_environment(baseline_file("uv.lock"), baseline_file(ADAPTER_PATH), 4)
    candidate = expected_environment((ROOT / "uv.lock").read_bytes(),
                                     (ROOT / ADAPTER_PATH).read_bytes(), 5)
    names = [args.adapter] if args.adapter else sorted(ADAPTERS)
    for name in names:
        snapshots = []
        for directory, environment in ((args.baseline, baseline), (args.candidate, candidate)):
            record = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
            verify_record(record, name, environment, args.corpus, inputs, manifest)
            snapshots.append(record)
        before, after = snapshots
        if before["execution"] != after["execution"]:
            raise ValueError(f"{name}: execution environments differ")
        for key, _ in inputs:
            old, new = before["rows"][key], after["rows"][key]
            if old != new:
                fields = {k: [old[k], new[k]] for k in old if old[k] != new[k]}
                raise ValueError(f"{name} {key}: changed output {json.dumps(fields, sort_keys=True)}")
    scope = "Full benchmark parity" if not args.adapter and args.corpus == "benchmark" else "Partial diagnostic parity"
    print(f"{scope}: {len(names)} adapters × {len(inputs)} inputs matched exactly "
          f"({baseline['transformers']} vs {candidate['transformers']}).")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("capture")
    run.add_argument("--adapter", required=True, choices=sorted(ADAPTERS))
    run.add_argument("--output", required=True, type=Path)
    run.add_argument("--threads", type=int, default=4)
    check = sub.add_parser("compare")
    check.add_argument("baseline", type=Path)
    check.add_argument("candidate", type=Path)
    check.add_argument("--adapter", choices=sorted(ADAPTERS), help="compare one adapter for diagnosis")
    for command in (run, check):
        command.add_argument("--corpus", choices=("benchmark", "probes"), default="benchmark")
    args = parser.parse_args()
    try:
        inputs, manifest = inputs_for(args.corpus)
        if args.command == "capture":
            capture(args, inputs, manifest)
        else:
            compare(args, inputs, manifest)
    except (ValueError, KeyError, OSError, RuntimeError, ImportError) as exc:
        parser.exit(1, f"Parity check incomplete: {exc}\n")


if __name__ == "__main__":
    main()
