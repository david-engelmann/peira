"""Test validation of parity records. The examples contain no checkpoint measurements."""

import hashlib
import json
from argparse import Namespace

import pytest

from scripts import hf_score_parity as parity


@pytest.fixture
def comparison(tmp_path, monkeypatch):
    inputs, manifest = parity.inputs_for("probes")
    name = "granite-guardian-hap"
    cls = parity.ADAPTERS[name]
    base_versions = {"transformers": "4.57.6", "tokenizers": "0.22.2",
                     "huggingface-hub": "0.36.2", "torch": "2.14.1"}
    candidate_versions = dict(base_versions, transformers="5.24.0", tokenizers="0.23.3")
    candidate_versions["huggingface-hub"] = "2.4.0"

    def lock(versions):
        return "".join(f'[[package]]\nname = "{k}"\nversion = "{v}"\n'
                       for k, v in versions.items()).encode()

    base_source, candidate_source = b"baseline adapter", b"candidate adapter"
    baseline_files = {"uv.lock": lock(base_versions), parity.ADAPTER_PATH: base_source}
    monkeypatch.setattr(parity, "baseline_file", baseline_files.__getitem__)
    monkeypatch.setattr(parity, "ROOT", tmp_path)
    (tmp_path / "uv.lock").write_bytes(lock(candidate_versions))
    adapter_file = tmp_path / parity.ADAPTER_PATH
    adapter_file.parent.mkdir(parents=True)
    adapter_file.write_bytes(candidate_source)
    args = Namespace(baseline=tmp_path / "v4", candidate=tmp_path / "v5", adapter=name,
                     corpus="probes")
    for directory, versions, source in ((args.baseline, base_versions, base_source),
                                        (args.candidate, candidate_versions, candidate_source)):
        rows = {key: {"scores": {"p_malicious": 0.125, "p_safe": 0.875}, "confidence": 0.75,
                      "decision": "other", "abstained": False, "input_tokens": 3,
                      "output_tokens": 0} for key, _ in inputs}
        record = {"adapter": name, "model": cls.HF_MODEL_ID, "revision": cls.HF_REVISION,
                  "corpus": args.corpus, "manifest": manifest, "inputs_sha256": parity.digest(inputs),
                  "transformers": versions["transformers"], "huggingface_hub": versions["huggingface-hub"],
                  "tokenizers": versions["tokenizers"], "torch_distribution": versions["torch"],
                  "adapter_source_sha256": hashlib.sha256(source).hexdigest(),
                  "execution": {"parameters": [["cpu", "torch.float32"]], "cpu": "test CPU",
                                "torch": versions["torch"]},
                  "rows": rows}
        directory.mkdir()
        (directory / f"{name}.json").write_text(json.dumps(record))
    return args, inputs, manifest


def test_probes_report_partial_scope(comparison, capsys):
    parity.compare(*comparison)
    assert "Partial diagnostic parity" in capsys.readouterr().out


@pytest.mark.parametrize("field,value,error", [
    ("revision", "wrong", "revision"),
    ("inputs_sha256", "", "inputs_sha256"),
    ("transformers", "4.57.6", "transformers"),
    ("rows", {}, "missing or unexpected case arms"),
    ("execution", {"parameters": [["cuda:0", "torch.bfloat16"]], "cpu": "test CPU",
                   "torch": "2.14.1"}, "execution environments differ"),
])
def test_mismatched_records_rejected(comparison, field, value, error):
    args, inputs, manifest = comparison
    path = args.candidate / f"{args.adapter}.json"
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match=error):
        parity.compare(args, inputs, manifest)


@pytest.mark.parametrize("path,value", [
    (("decision",), "abstain"), (("confidence",), 0.751), (("input_tokens",), 4),
    (("scores", "p_safe"), 0.875000001), (("scores", "p_malicious"), 0.125000001),
])
def test_score_drift_rejected(comparison, path, value):
    args, inputs, manifest = comparison
    output = args.candidate / f"{args.adapter}.json"
    record = json.loads(output.read_text())
    value_dict = record["rows"][inputs[0][0]]
    for key in path[:-1]:
        value_dict = value_dict[key]
    value_dict[path[-1]] = value
    output.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="changed output"):
        parity.compare(args, inputs, manifest)


def test_one_adapter_cannot_satisfy_all_model_comparison(comparison):
    args, inputs, manifest = comparison
    args.adapter = None
    with pytest.raises(FileNotFoundError):
        parity.compare(args, inputs, manifest)

@pytest.mark.parametrize("side", ["baseline", "candidate"])
@pytest.mark.parametrize("key", ["tokenizers", "huggingface_hub", "torch_distribution", "adapter_source_sha256"])
def test_each_side_must_match_its_source_and_lock(comparison, side, key):
    args, inputs, manifest = comparison
    path = getattr(args, side) / f"{args.adapter}.json"
    record = json.loads(path.read_text())
    record[key] = "unexpected"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match=key):
        parity.compare(args, inputs, manifest)
