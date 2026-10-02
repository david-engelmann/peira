"""Run artifacts: the versioned record of one evaluation run.

An artifact bundles the config, the per-case results, and the aggregate
metrics, plus an analysis-lock hash (sha256 over the lock payload). The
hash is the mechanical guarantee behind "no post-hoc editing": any change
to inputs changes the lock, and CI verifies it.

Artifact format versions:
- v1 (pre-2026-09-23): flat per-case results. REJECTED by this build.
  v1 artifacts predate the v2 measurement contract and cannot be
  migrated. Re-run the adapter to produce a v3 artifact.
- v2 (2026-09-23 to 2026-09-30): per-case results carry full per-variant
  call records (decision, confidence, abstention, refusal reason, usage,
  seed, dispatch index), eligibility flags with ineligibility reasons,
  and run-level pricing provenance (source + pin date) and seed. The
  lock payload covers pricing_source, pricing_date, and seed alongside
  the v1 fields. REJECTED by this build. v2 predates the v3
  agent-consumer schema (no run_id, no closed vocabularies, no threat
  model / provenance / adjudication / exposure blocks). Re-run the
  adapter to produce a v3 artifact. Per docs/Artifact-Versions.md, no
  sealed official measurements exist yet, so no migration path is owed.
- v3 (current): the agent-consumer schema. Adds stable run identity
  (run_id / parent_run_id), a machine-checkable run_status gate,
  schema_ref, metrics_version, structured threat_model /
  attack_provenance / adjudication_policy / exposure_attestation
  blocks, fully-pinned adapter identity, license + access tier
  in-band, typed per-family stats, uncertainty semantics, retry/cache
  transparency, determinism-check results, a machine-readable error
  (exclusion) log, and per-call error_code / retry_count /
  prompt_hash / completion_hash. Closed vocabularies (enums, not
  free-form strings) on termination, run_status,
  model_class, confidence_source, error codes, and the new blocks.
  NOTE: decision is deliberately NOT closed (case-option labels plus
  "other" and the "<error>" sentinel). Every new field is lock-covered.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import ClassVar

from peira import __version__ as peira_version
from peira._rust import _impl as _rust
from peira.adapters.base import _unit_interval
from peira.metrics import (
    ADJUDICATION_POLICY_VERSION,
    METRICS_VERSION,
    PerCaseResult,
)
from peira.sampling import SAMPLING_SOURCES

ARTIFACT_VERSION = "3"

#: Canonical resolvable URI of the JSON Schema this artifact validates
#: against. The schema file ships in-repo at schemas/run-artifact-3.json;
#: this URI is where it is published. Consumers fail closed on an
#: artifact whose schema_ref they cannot resolve.
SCHEMA_REF = "https://peiratrial.dev/schemas/run-artifact/3.json"

#: Measurement-contract version: the semantics the run was executed
#: under (abstention semantics, flip definition, eligibility rules).
#: ARTIFACT_VERSION covers the schema; the contract version covers the
#: meaning. A future semantics change bumps this (not the artifact
#: version) so old runs stay loadable but are never silently
#: reinterpreted under new rules.
CONTRACT_VERSION = "1"

_UNSUPPORTED_VERSION = (
    "unsupported artifact_version {version!r}: only v3 artifacts load. "
    "v1/v2 artifacts predate the v3 agent-consumer schema and cannot be "
    "loaded or migrated. Re-run the adapter to produce a v3 artifact "
    "(see docs/Artifact-Versions.md)"
)


def _is_int(v: object) -> bool:
    # bool subclasses int; a JSON `true` is not an integer.
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---------------------------------------------------------------------------
# v3 closed vocabularies. Free-form strings are a silent schema-drift
# vector: agents filter and group on these fields, so every value comes
# from a closed set. The strict loader rejects anything else.
#
# NOTE: `decision` is deliberately NOT closed here. Decisions are
# case-option labels (the case's own `options` list) plus the "other"
# placeholder and the "<error>" malformed sentinel — the vocabulary is
# case-dependent, so the artifact level cannot close it. The adapter
# contract (adapters/base.py) owns decision validity.
# ---------------------------------------------------------------------------

#: Machine-checkable run gate (Inspect-style): never analyze a run whose
#: status is not "success". "started" appears only on live/checkpoint
#: artifacts; sealed runs are success/cancelled/error/partial.
RUN_STATUSES = frozenset({"started", "success", "cancelled", "error", "partial"})

#: How the run ended. "complete" = all planned cases scored; "budget" =
#: stopped by --budget-usd; "timeout" = stopped by --run-timeout;
#: "partial" = checkpoint, not a finished run; "operator" reserved for
#: future termination causes.
TERMINATIONS = frozenset({"complete", "budget", "timeout", "partial", "operator", "error"})

#: Per-call terminal-failure taxonomy ("" = no error). The NeurIPS
#: checklist requires excluded data to be specified; error_code is the
#: machine-readable reason a call contributed no usable decision.
ERROR_CODES = frozenset({
    "", "timeout", "rate_limit", "api_error", "parse_failure",
    "refused_to_format",
})

#: Adapter-kind vocabulary (was documented-only in v2; enforced in v3).
MODEL_CLASSES = frozenset({"", "guardrail", "llm-baseline", "hybrid", "rule-based"})

#: Confidence provenance vocabulary (was documented-only in v2).
CONFIDENCE_SOURCES = frozenset(
    {"", "verbalized", "token-logprob", "guardrail-score", "none"}
)

#: Redistribution rights travel in-band: an agent publishing leaderboard
#: numbers must know them without asking a human.
ACCESS_TIERS = frozenset({"public", "internal", "confidential"})

#: Which case regime the run operated under (the blind-holdout seal is
#: unenforceable downstream unless the artifact states it).
CASE_SUBSETS = frozenset({"public", "private", "blind", "mixed"})

#: Threat-model vocabularies (Carlini checklist: every ASR is contingent
#: on the threat model).
ATTACKER_ACCESS_LEVELS = frozenset({"black_box", "gray_box", "white_box"})
ATTACKER_KNOWLEDGE = frozenset({"none", "architecture", "weights", "training_data"})
ATTACK_ADAPTIVITY = frozenset({"static", "adaptive"})
ATTACK_METHODS = frozenset({"static_template", "adaptive_search", "manual"})


# ---------------------------------------------------------------------------
# v3 structured blocks. Each block has a default factory (honest
# "undeclared" values, never invented data) and a strict validator.
# Spec: {field: (type, allowed_values_or_None)}.
# ---------------------------------------------------------------------------


def _default_threat_model() -> dict:
    # peira's attacks are static templates issued through the adapter's
    # normal query interface: black-box, no adapter knowledge, static.
    # query_budget_per_case is filled by the runner from max_attempts;
    # 0 here means "undeclared" (hand-written artifact).
    return {
        "attacker_access": "black_box",
        "attacker_knowledge": "none",
        "query_budget_per_case": 0,
        "attack_adaptivity": "static",
        "notes": "",
    }


_THREAT_MODEL_SPEC = {
    "attacker_access": (str, ATTACKER_ACCESS_LEVELS),
    "attacker_knowledge": (str, ATTACKER_KNOWLEDGE),
    "query_budget_per_case": (int, None),
    "attack_adaptivity": (str, ATTACK_ADAPTIVITY),
    "notes": (str, None),
}


def _default_attack_provenance() -> dict:
    return {
        "attacker_model": "",
        "attacker_model_version": "",
        "attack_budget_variants": 1,
        "attack_method": "static_template",
        "attack_code_ref": "",
    }


_ATTACK_PROVENANCE_SPEC = {
    "attacker_model": (str, None),
    "attacker_model_version": (str, None),
    "attack_budget_variants": (int, None),
    "attack_method": (str, ATTACK_METHODS),
    "attack_code_ref": (str, None),
}


def _default_adjudication_policy() -> dict:
    # The honest v1 adjudication rules (see metrics.py): a case is
    # eligible only when the benign arm is well-formed, correct, and
    # not abstained; a flip is a change in the effective outcome
    # (decision, abstained) benign -> attacked, with attacked-malformed
    # counting as flipped and attacked-abstain counting as not flipped.
    return {
        "policy_version": ADJUDICATION_POLICY_VERSION,
        "eligibility_rule": "benign_well_formed_and_correct_and_not_abstained",
        "ineligibility_reasons": [
            "benign_malformed",
            "benign_wrong_decision",
            "benign_abstained",
        ],
        "attacked_abstain_counts_as": "not_flipped",
        "attacked_malformed_counts_as": "flipped",
        "conditional_asr_denominator": "eligible_cases",
        "unconditional_asr_denominator": "all_cases",
    }


_ADJUDICATION_POLICY_SPEC = {
    "policy_version": (str, None),
    "eligibility_rule": (str, None),
    "ineligibility_reasons": (list, None),
    "attacked_abstain_counts_as": (str, frozenset({"flipped", "not_flipped"})),
    "attacked_malformed_counts_as": (str, frozenset({"flipped", "not_flipped"})),
    "conditional_asr_denominator": (str, None),
    "unconditional_asr_denominator": (str, None),
}


def _default_exposure_attestation() -> dict:
    return {
        "case_subset": "public",
        "blindness_protocol_id": "",
        "prior_exposure_attested": False,
        "holdout_access_log_ref": "",
    }


_EXPOSURE_ATTESTATION_SPEC = {
    "case_subset": (str, CASE_SUBSETS),
    "blindness_protocol_id": (str, None),
    "prior_exposure_attested": (bool, None),
    "holdout_access_log_ref": (str, None),
}


def _default_adapter_pins() -> dict:
    # Fully-pinned adapter identity. API models drift silently; a
    # human-readable adapter_version is not a pin. Unknown fields stay
    # "" rather than invented (same defensive rule as the M-7
    # longitudinal provenance).
    return {
        "provider_snapshot": "",
        "hf_revision": "",
        "code_sha": "",
        "code_dirty": False,
    }


_ADAPTER_PINS_SPEC = {
    "provider_snapshot": (str, None),
    "hf_revision": (str, None),
    "code_sha": (str, None),
    "code_dirty": (bool, None),
}


def _default_uncertainty() -> dict:
    # The per-family CIs sealed in per_family_stats are Wilson 95%
    # per-case binomial intervals unless the runner says otherwise.
    return {
        "ci_method": "wilson",
        "ci_level": 0.95,
        "ci_unit": "per_case_binomial",
        "multiple_comparison": "none",
        "familywise_alpha": 0.05,
    }


_UNCERTAINTY_SPEC = {
    "ci_method": (str, None),
    "ci_level": (float, None),
    "ci_unit": (str, None),
    "multiple_comparison": (str, frozenset({"none", "holm", "bonferroni"})),
    "familywise_alpha": (float, None),
}


def _default_retry_policy() -> dict:
    return {
        "per_call_timeout_s": None,
        "max_retries": 0,
        "total_retries": 0,
        "rate_limit_hits": 0,
    }


_RETRY_POLICY_SPEC = {
    "per_call_timeout_s": ((int, float), None),
    "max_retries": (int, None),
    "total_retries": (int, None),
    "rate_limit_hits": (int, None),
}


def _default_cache_policy() -> dict:
    return {
        "cache_enabled": False,
        "cache_key_scheme": "",
        "cache_hits": 0,
        "cache_misses": 0,
    }


_CACHE_POLICY_SPEC = {
    "cache_enabled": (bool, None),
    "cache_key_scheme": (str, None),
    "cache_hits": (int, None),
    "cache_misses": (int, None),
}


def _default_determinism_check() -> dict:
    return {
        "checked": False,
        "passed": False,
        "mismatches": 0,
        "sample_n": 0,
    }


_DETERMINISM_CHECK_SPEC = {
    "checked": (bool, None),
    "passed": (bool, None),
    "mismatches": (int, None),
    "sample_n": (int, None),
}


def _checked_block(value: object, spec: dict, where: str) -> dict:
    """Strictly validate one v3 structured block against its spec."""
    if not isinstance(value, dict):
        raise ValueError(
            f"{where} must be an object, got {type(value).__name__}"
        )
    for key in value:
        if key not in spec:
            raise ValueError(f"{where} has unknown field: {key!r}")
    clean: dict = {}
    for key, (typ, allowed) in spec.items():
        if key not in value:
            raise ValueError(f"{where} is missing field: {key!r}")
        v = value[key]
        # per_call_timeout_s allows null (no timeout configured).
        if key == "per_call_timeout_s" and v is None:
            clean[key] = None
            continue
        if isinstance(typ, tuple):
            ok = isinstance(v, typ) and not isinstance(v, bool)
        else:
            ok = isinstance(v, typ)
            if typ is int and isinstance(v, bool):
                ok = False
        if not ok:
            want = (
                "/".join(t.__name__ for t in typ)
                if isinstance(typ, tuple)
                else typ.__name__
            )
            raise ValueError(
                f"{where} field {key!r} must be {want}, "
                f"got {type(v).__name__}"
            )
        if allowed is not None and v not in allowed:
            raise ValueError(
                f"{where} field {key!r} must be one of "
                f"{sorted(allowed)}, got {v!r}"
            )
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if key in (
                "query_budget_per_case", "attack_budget_variants",
                "max_retries", "total_retries", "rate_limit_hits",
                "cache_hits", "cache_misses", "mismatches", "sample_n",
            ) and v < 0:
                raise ValueError(
                    f"{where} field {key!r} must be non-negative, got {v!r}"
                )
        clean[key] = v() if callable(v) else v
    return clean


def _checked_per_family_stats(value: object, where: str) -> list[dict]:
    """Typed per-family stats: a list, not a string-keyed dict.

    Agents should not have to recompute aggregates from the results
    list to answer "which family regressed". Recomputation risks
    disagreeing with the locked metrics.
    """
    if not isinstance(value, list):
        raise ValueError(
            f"{where} must be a list, got {type(value).__name__}"
        )
    clean: list[dict] = []
    for i, entry in enumerate(value):
        ewhere = f"{where}[{i}]"
        if not isinstance(entry, dict):
            raise ValueError(
                f"{ewhere} must be an object, got {type(entry).__name__}"
            )
        for key in entry:
            if key not in (
                "family", "n", "n_eligible", "asr",
                "asr_ci95_lower", "asr_ci95_upper",
                "abstention_rate",
                "abstention_rate_ci95_lower",
                "abstention_rate_ci95_upper",
            ):
                raise ValueError(f"{ewhere} has unknown field: {key!r}")
        for key in (
            "family", "n", "n_eligible", "asr",
            "asr_ci95_lower", "asr_ci95_upper",
        ):
            if key not in entry:
                raise ValueError(f"{ewhere} is missing field: {key!r}")
        if not isinstance(entry["family"], str):
            raise ValueError(f"{ewhere} field 'family' must be str")
        for key in ("n", "n_eligible"):
            if not _is_int(entry[key]) or entry[key] < 0:
                raise ValueError(
                    f"{ewhere} field {key!r} must be a non-negative integer"
                )
        for key in (
            "asr", "asr_ci95_lower", "asr_ci95_upper",
            "abstention_rate",
            "abstention_rate_ci95_lower",
            "abstention_rate_ci95_upper",
        ):
            v = entry.get(key)
            if v is not None and (not _is_num(v) or not 0.0 <= v <= 1.0):
                raise ValueError(
                    f"{ewhere} field {key!r} must be null or a number in "
                    f"0..1, got {v!r}"
                )
        clean.append({k: entry.get(k) for k in (
            "family", "n", "n_eligible", "asr",
            "asr_ci95_lower", "asr_ci95_upper",
            "abstention_rate",
            "abstention_rate_ci95_lower",
            "abstention_rate_ci95_upper",
        )})
    return clean


def _checked_error_log(value: object, where: str) -> list[dict]:
    """Machine-readable exclusion table (case_id, arm, error_code).

    Lets agents recompute denominators correctly instead of trusting
    prose about what was excluded.
    """
    if not isinstance(value, list):
        raise ValueError(
            f"{where} must be a list, got {type(value).__name__}"
        )
    clean: list[dict] = []
    for i, entry in enumerate(value):
        ewhere = f"{where}[{i}]"
        if not isinstance(entry, dict):
            raise ValueError(
                f"{ewhere} must be an object, got {type(entry).__name__}"
            )
        for key in entry:
            if key not in ("case_id", "arm", "error_code"):
                raise ValueError(f"{ewhere} has unknown field: {key!r}")
        for key in ("case_id", "arm", "error_code"):
            if key not in entry:
                raise ValueError(f"{ewhere} is missing field: {key!r}")
        if not isinstance(entry["case_id"], str):
            raise ValueError(f"{ewhere} field 'case_id' must be str")
        if entry["arm"] not in ("benign", "attacked"):
            raise ValueError(
                f"{ewhere} field 'arm' must be 'benign' or 'attacked', "
                f"got {entry['arm']!r}"
            )
        if entry["error_code"] not in ERROR_CODES or entry["error_code"] == "":
            raise ValueError(
                f"{ewhere} field 'error_code' must be a non-empty error "
                f"code, got {entry['error_code']!r}"
            )
        clean.append({
            "case_id": entry["case_id"],
            "arm": entry["arm"],
            "error_code": entry["error_code"],
        })
    return clean


@dataclass
class RunArtifact:
    artifact_version: str = ARTIFACT_VERSION
    peira_version: str = peira_version
    dataset_version: str = "0.1.0-demo"
    adapter_name: str = ""
    adapter_version: str = ""  # pinned by the adapter; part of the lock
    suite: str = ""
    created_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    config: dict = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    analysis_lock: str = ""
    # SHA-256 of the suite manifest.json bytes as verified before scoring.
    # A label (`dataset_version`) says which dataset this claims to be;
    # this digest proves the exact bytes. Empty when the suite ships no
    # manifest — the run is then explicitly unbound, not silently bound.
    manifest_sha256: str = ""
    # Pricing provenance: which pinned table priced this run's calls.
    pricing_source: str = ""
    pricing_date: str = ""
    # Machine-identifiable pricing table version (pricing.json's
    # pricing_version, e.g. "2026-09-25.1"): a cost figure is always
    # traceable to the exact table version that produced it. Runs are
    # never re-priced in place: a price change ships as a new table
    # version, and old artifacts keep their sealed numbers.
    pricing_version: str = ""
    # The measurement contract this run was executed under (see
    # CONTRACT_VERSION): abstention semantics, flip definition,
    # eligibility rules.
    contract_version: str = CONTRACT_VERSION
    # How the run ended: "complete" (all planned cases scored),
    # "budget" (stopped by --budget-usd; in-flight cases drained),
    # "timeout" (stopped by --run-timeout; dispatch stopped, in-flight
    # cases drained to completion, completed cases checkpointed in a
    # resumable partial), "partial" (checkpoint, not a finished run),
    # "operator" reserved for future termination causes. Budget- or
    # timeout-terminated runs are analyzable but never rank: a lucky
    # prefix of easy cases must not top a leaderboard.
    termination: str = "complete"
    # Hard spend cap in USD for this run (None = uncapped). The runner
    # enforces it pre-dispatch with a 1.5x running-mean projection and
    # drains in-flight calls; it never kills a paid call mid-flight.
    budget_usd: float | None = None
    # Per-call output-token cap (R-18, None = uncapped). A call whose
    # reported tokens_out exceeds it is marked malformed, because the
    # decision was produced outside the run's declared cost envelope.
    # Part of the analysis lock, because a run measured under a
    # different cap is a different measurement.
    max_tokens_per_call: int | None = None
    # Actual priced spend at seal time (runner-computed, same table as
    # the call records). May overshoot budget_usd by at most one
    # in-flight wave: dispatched calls always complete.
    spent_usd: float = 0.0
    # Cases scored vs planned. Equal on complete runs; on
    # budget-terminated runs completed < planned and the artifact is
    # partial-but-sealed (analyzable, not rankable).
    cases_completed: int = 0
    cases_planned: int = 0
    # Run seed: recorded on every call record for reproducibility.
    seed: int = 0
    # Concurrency cap the run was dispatched with. The AIMD controller
    # adapts within [1, max_concurrency]; it is a performance parameter,
    # not a measurement input (records are identical for any limit),
    # but it is sealed for provenance.
    max_concurrency: int = 0
    # Environment fingerprint (Layer 1b): the full environment dict plus
    # its SHA-256 digest. Recorded at run start; part of the analysis
    # lock. Two runs with different env_sha256 are explained, not
    # mysterious.
    env: dict = field(default_factory=dict)
    env_sha256: str = ""
    # Measurement framework (§3.7-3.8, §3.11-3.15): adapter registration
    # metadata and longitudinal provenance. model_class documents the
    # adapter kind (guardrail, llm-baseline, hybrid, rule-based);
    # confidence_source documents where the confidence came from
    # (verbalized, token-logprob, guardrail-score, none). These are
    # documented vocabularies, not enforced enums: validation
    # type-checks str only. decode_params
    # is a JSON blob (temperature, top-p, max tokens, ...). All default
    # to "" for artifacts predating them.
    model_class: str = ""
    confidence_source: str = ""
    checkpoint_hash: str = ""
    api_version: str = ""
    call_date: str = ""
    decode_params: str = ""
    template_hash: str = ""
    case_set_tag: str = ""
    cost_scenario_version: str = ""
    # ---- v3 agent-consumer fields (all lock-covered) ----
    # Stable run identity: the join key that survives renames and
    # copies. parent_run_id chains reruns/resumes for longitudinal
    # tracking and leaderboard dedup.
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    parent_run_id: str = ""
    # Machine-checkable run gate: never analyze a run whose status is
    # not "success". Derived at seal time by the runner (complete ->
    # success; budget/timeout/partial -> partial; a mid-run checkpoint
    # is still live -> started; anything else -> error).
    run_status: str = "success"
    # Resolvable JSON Schema URI for this artifact version.
    schema_ref: str = SCHEMA_REF
    # Version of the metric formula definitions that produced
    # `metrics` (see metrics.METRICS_VERSION). Two artifacts computed
    # under different formula versions are not comparable.
    metrics_version: str = METRICS_VERSION
    # Structured threat model (Carlini checklist): every ASR is
    # contingent on attacker access, knowledge, query budget, and
    # whether the attacks were static or adaptive.
    threat_model: dict = field(default_factory=_default_threat_model)
    # Attack provenance: the three published ASR axes peira controls —
    # attacker model identity, attack budget, attack method.
    attack_provenance: dict = field(default_factory=_default_attack_provenance)
    # The rule mapping abstain/malformed/ineligible/eligible into ASR
    # numerators and denominators. Load-bearing for comparability;
    # was implicit before v3.
    adjudication_policy: dict = field(default_factory=_default_adjudication_policy)
    # Exposure/blindness attestation: which case regime the run
    # operated under and whether prior exposure was attested away.
    exposure_attestation: dict = field(default_factory=_default_exposure_attestation)
    # Fully-pinned adapter identity: provider snapshot, HF revision,
    # adapter code SHA + dirty flag. API models drift silently; a
    # human version string is not a pin.
    adapter_pins: dict = field(default_factory=_default_adapter_pins)
    # License + access tier in-band (FAIR): a machine consumer
    # deciding whether it may republish leaderboard numbers needs
    # this in the artifact, not in a wiki.
    license: str = "CC-BY-4.0"
    access_tier: str = "public"
    # Precomputed typed per-family stats (family, n, asr, CIs): agents
    # should not recompute aggregates from the results list.
    per_family_stats: list = field(default_factory=list)
    # Uncertainty semantics for the sealed CIs: method, level, unit,
    # and the multiple-comparison correction applied.
    uncertainty: dict = field(default_factory=_default_uncertainty)
    # Retry/timeout policy and observed counts: affects latency and
    # cost interpretation.
    retry_policy: dict = field(default_factory=_default_retry_policy)
    # Cache policy and observed hits: reruns are not independent when
    # any caching exists.
    cache_policy: dict = field(default_factory=_default_cache_policy)
    # Determinism-contract self-check: whether the run verified its
    # own determinism contract, not just the seed it ran under.
    determinism_check: dict = field(default_factory=_default_determinism_check)
    # Machine-readable exclusion table: every call that contributed
    # no usable decision, with its error code. Lets agents recompute
    # denominators correctly.
    error_log: list = field(default_factory=list)

    def __post_init__(self) -> None:
        # Normalize result entries on construction: call records gain
        # the v3 defaults (error_code="", retry_count=0, hashes="") so
        # a Python-built artifact and its JSON roundtrip compare equal.
        # Validation errors here are programming errors (the strict
        # loader is for untrusted JSON), so they propagate.
        if self.results:
            self.results = self._checked_results(self.results)
        # Closed vocabularies are enforced at construction, not only
        # by the strict loader: the runner builds artifacts via the
        # constructor, so a typo in a vocabulary field must fail here
        # instead of surfacing later at load time.
        for key, vocab in (
            ("run_status", RUN_STATUSES),
            ("termination", TERMINATIONS),
            ("model_class", MODEL_CLASSES),
            ("confidence_source", CONFIDENCE_SOURCES),
            ("access_tier", ACCESS_TIERS),
        ):
            value = getattr(self, key)
            if value not in vocab:
                raise ValueError(
                    f"artifact field {key!r} must be one of "
                    f"{sorted(vocab)}, got {value!r}"
                )
        # Normalize int to float for USD fields: the Rust backend
        # (via PyO3) extracts Python ints as f64, so an int here
        # would hash differently ("5" vs "5.0") across backends.
        # This keeps the lock byte-identical.
        if isinstance(self.budget_usd, int) and not isinstance(self.budget_usd, bool):
            self.budget_usd = float(self.budget_usd)
        if isinstance(self.spent_usd, int) and not isinstance(self.spent_usd, bool):
            self.spent_usd = float(self.spent_usd)

    def _compute_lock_py(self) -> str:
        """Reference implementation of :meth:`compute_lock` (pure Python)."""
        payload = json.dumps(
            {
                "peira_version": self.peira_version,
                "dataset_version": self.dataset_version,
                "adapter_name": self.adapter_name,
                "adapter_version": self.adapter_version,
                "suite": self.suite,
                "config": self.config,
                "results": self.results,
                "manifest_sha256": self.manifest_sha256,
                "pricing_source": self.pricing_source,
                "pricing_date": self.pricing_date,
                "pricing_version": self.pricing_version,
                "contract_version": self.contract_version,
                "termination": self.termination,
                "budget_usd": self.budget_usd,
                "max_tokens_per_call": self.max_tokens_per_call,
                "spent_usd": self.spent_usd,
                "cases_completed": self.cases_completed,
                "cases_planned": self.cases_planned,
                "seed": self.seed,
                "max_concurrency": self.max_concurrency,
                # NOTE: metrics are lock-covered (P0-1, 2026-09-25). Any
                # post-hoc edit to the headline numbers invalidates the
                # lock. Pre-2026-09-25 artifacts sealed without metrics in
                # the lock will fail verify() — acceptable per blank-canvas.
                "metrics": self.metrics,
                # Environment fingerprint (Layer 1b, 2026-09-27): the env
                # is a measurement input. A different torch/CUDA/Python
                # can change numbers; the lock must catch it. Both the
                # dict and its hash are covered: the hash binds the
                # fingerprint, the dict prevents undetectable rewrites.
                "env": self.env,
                "env_sha256": self.env_sha256,
                # Measurement framework (M-6/M-7, 2026-09-28): adapter
                # registration metadata and longitudinal provenance are
                # measurement inputs; the lock must catch post-hoc edits.
                "model_class": self.model_class,
                "confidence_source": self.confidence_source,
                "checkpoint_hash": self.checkpoint_hash,
                "api_version": self.api_version,
                "call_date": self.call_date,
                "decode_params": self.decode_params,
                "template_hash": self.template_hash,
                "case_set_tag": self.case_set_tag,
                "cost_scenario_version": self.cost_scenario_version,
                # v3 agent-consumer fields: measurement inputs, so lock
                # inputs. A post-hoc edit to the threat model, pins, or
                # adjudication policy must invalidate the lock exactly
                # like a metrics edit does.
                "run_id": self.run_id,
                "parent_run_id": self.parent_run_id,
                "run_status": self.run_status,
                "schema_ref": self.schema_ref,
                "metrics_version": self.metrics_version,
                "threat_model": self.threat_model,
                "attack_provenance": self.attack_provenance,
                "adjudication_policy": self.adjudication_policy,
                "exposure_attestation": self.exposure_attestation,
                "adapter_pins": self.adapter_pins,
                "license": self.license,
                "access_tier": self.access_tier,
                "per_family_stats": self.per_family_stats,
                "uncertainty": self.uncertainty,
                "retry_policy": self.retry_policy,
                "cache_policy": self.cache_policy,
                "determinism_check": self.determinism_check,
                "error_log": self.error_log,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def compute_lock(self) -> str:
        """SHA-256 analysis lock over the artifact's lock-covered fields.

        Dispatches to the Rust core when available; the pure-Python
        :meth:`_compute_lock_py` is the reference and the fallback.
        """
        if _rust is not None:
            try:
                return _rust.artifact_lock_payload(
                    self.peira_version,
                    self.dataset_version,
                    self.manifest_sha256,
                    self.adapter_name,
                    self.adapter_version,
                    self.suite,
                    self.config,
                    self.results,
                    self.pricing_source,
                    self.pricing_date,
                    self.pricing_version,
                    self.contract_version,
                    self.termination,
                    self.budget_usd,
                    self.spent_usd,
                    self.cases_completed,
                    self.cases_planned,
                    self.seed,
                    self.max_concurrency,
                    self.max_tokens_per_call,
                    self.metrics,
                    self.env,
                    self.env_sha256,
                    self.model_class,
                    self.confidence_source,
                    self.checkpoint_hash,
                    self.api_version,
                    self.call_date,
                    self.decode_params,
                    self.template_hash,
                    self.case_set_tag,
                    self.cost_scenario_version,
                    self.run_id,
                    self.parent_run_id,
                    self.run_status,
                    self.schema_ref,
                    self.metrics_version,
                    self.threat_model,
                    self.attack_provenance,
                    self.adjudication_policy,
                    self.exposure_attestation,
                    self.adapter_pins,
                    self.license,
                    self.access_tier,
                    self.per_family_stats,
                    self.uncertainty,
                    self.retry_policy,
                    self.cache_policy,
                    self.determinism_check,
                    self.error_log,
                )
            except (TypeError, ValueError, OverflowError):
                pass
        return self._compute_lock_py()

    def seal(self) -> "RunArtifact":
        # v3: run_status derives from termination at seal time. A
        # complete run is a success; budget/timeout/partial are
        # partial (analyzable, never rankable); error is an error;
        # operator intervention is a cancellation.
        if self.termination == "complete":
            self.run_status = "success"
        elif self.termination in ("budget", "timeout", "partial"):
            self.run_status = "partial"
        elif self.termination == "error":
            self.run_status = "error"
        elif self.termination == "operator":
            self.run_status = "cancelled"
        self.analysis_lock = self.compute_lock()
        return self

    def verify(self) -> bool:
        return self.analysis_lock == self.compute_lock()

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    # Field name -> expected JSON type. `peira_version` and
    # `dataset_version` are required: the lock is meaningless without the
    # identifiers it binds. Every other field defaults exactly like the
    # Rust core's `RunArtifact` (missing `config`/`metrics` become `{}`),
    # so a minimal hand-written artifact loads identically on both
    # backends. Unknown fields are rejected: silently accepting a
    # newer/renamed field could verify a lock under changed semantics.
    _FIELD_TYPES: ClassVar[dict] = {
        "artifact_version": str,
        "peira_version": str,
        "dataset_version": str,
        "manifest_sha256": str,
        "adapter_name": str,
        "adapter_version": str,
        "suite": str,
        "created_utc": str,
        "config": dict,
        "results": list,
        "metrics": dict,
        "analysis_lock": str,
        "pricing_source": str,
        "pricing_date": str,
        "pricing_version": str,
        "contract_version": str,
        "termination": str,
        "cases_completed": int,
        "cases_planned": int,
        "seed": int,
        "max_concurrency": int,
        "env": dict,
        "env_sha256": str,
        # Measurement framework (§3.7-3.8, §3.11-3.15): adapter
        # registration metadata and longitudinal provenance.
        "model_class": str,
        "confidence_source": str,
        "checkpoint_hash": str,
        "api_version": str,
        "call_date": str,
        "decode_params": str,
        "template_hash": str,
        "case_set_tag": str,
        "cost_scenario_version": str,
        # v3 agent-consumer fields.
        "run_id": str,
        "parent_run_id": str,
        "run_status": str,
        "schema_ref": str,
        "metrics_version": str,
        "threat_model": dict,
        "attack_provenance": dict,
        "adjudication_policy": dict,
        "exposure_attestation": dict,
        "adapter_pins": dict,
        "license": str,
        "access_tier": str,
        "per_family_stats": list,
        "uncertainty": dict,
        "retry_policy": dict,
        "cache_policy": dict,
        "determinism_check": dict,
        "error_log": list,
    }
    # Numeric fields needing the bool-rejecting _is_num check (a JSON
    # integer 0 must pass for spent_usd; a JSON `true` must not).
    # budget_usd additionally allows null (uncapped run).
    _NUM_FIELDS: ClassVar[tuple] = ("spent_usd",)
    _NULLABLE_NUM_FIELDS: ClassVar[tuple] = ("budget_usd",)
    # Integer fields where a JSON `true` must not pass as an integer
    # (bool subclasses int). max_tokens_per_call additionally allows
    # null (uncapped run).
    _NULLABLE_INT_FIELDS: ClassVar[tuple] = ("max_tokens_per_call",)
    _REQUIRED_FIELDS: ClassVar[tuple] = ("peira_version", "dataset_version")
    _FIELD_DEFAULTS: ClassVar[dict] = {
        "artifact_version": ARTIFACT_VERSION,
        "manifest_sha256": "",
        "adapter_name": "",
        "adapter_version": "",
        "suite": "",
        "created_utc": "",
        "config": dict,
        "results": list,
        "metrics": dict,
        "analysis_lock": "",
        "pricing_source": "",
        "pricing_date": "",
        "pricing_version": "",
        "contract_version": CONTRACT_VERSION,
        "termination": "complete",
        "budget_usd": None,
        "max_tokens_per_call": None,
        "spent_usd": 0.0,
        "cases_completed": 0,
        "cases_planned": 0,
        "seed": 0,
        "max_concurrency": 0,
        "env": dict,
        "env_sha256": "",
    }
    # v3 block defaults: honest "undeclared" values via the factories
    # above (never invented data).
    _BLOCK_DEFAULTS: ClassVar[dict] = {
        "threat_model": _default_threat_model,
        "attack_provenance": _default_attack_provenance,
        "adjudication_policy": _default_adjudication_policy,
        "exposure_attestation": _default_exposure_attestation,
        "adapter_pins": _default_adapter_pins,
        "uncertainty": _default_uncertainty,
        "retry_policy": _default_retry_policy,
        "cache_policy": _default_cache_policy,
        "determinism_check": _default_determinism_check,
    }
    _BLOCK_SPECS: ClassVar[dict] = {
        "threat_model": _THREAT_MODEL_SPEC,
        "attack_provenance": _ATTACK_PROVENANCE_SPEC,
        "adjudication_policy": _ADJUDICATION_POLICY_SPEC,
        "exposure_attestation": _EXPOSURE_ATTESTATION_SPEC,
        "adapter_pins": _ADAPTER_PINS_SPEC,
        "uncertainty": _UNCERTAINTY_SPEC,
        "retry_policy": _RETRY_POLICY_SPEC,
        "cache_policy": _CACHE_POLICY_SPEC,
        "determinism_check": _DETERMINISM_CHECK_SPEC,
    }
    # Integer fields where a JSON `true` must not pass as an integer
    # (bool subclasses int).
    _INT_FIELDS: ClassVar[tuple] = (
        "seed", "max_concurrency", "cases_completed", "cases_planned",
    )

    # v2 result entries: per-variant call records plus scoring flags.
    # Every entry field is required and strictly typed (unknown entry
    # fields are rejected, like unknown top-level fields — the v1
    # loader's leniency here was a hole, closed pre-launch). `usage` is
    # the one nullable record field: null means the adapter reported no
    # token accounting.
    _RESULT_REQUIRED: ClassVar[dict] = {
        "case_id": str,
        "family": str,
        "severity": str,
        "primitive": str,
        "benign": dict,
        "attacked": dict,
        "flipped": bool,
        "eligible": bool,
        "ineligibility_reason": str,
    }
    _CALL_RECORD_FIELDS: ClassVar[dict] = {
        "decision": str,
        "abstained": bool,
        "refusal_reason": str,
        "malformed": bool,
    }
    # Suite-namespaced OPTIONAL result-entry fields. Unknown fields stay
    # rejected (the v1 leniency hole stays closed); these are known,
    # explicitly typed, and validated by shape below. The conversational
    # suite seals its intermediate turn records here: single-shot
    # tooling reads the scored final-turn pair and ignores the rest.
    # The EB-35 sweep suite seals its per-attempt records here: the
    # "attacked" field carries the representative (final) attempt for
    # single-shot tooling, while "attempts"/"attempt_flipped" carry the
    # full budget dimension.
    _RESULT_OPTIONAL: ClassVar[dict] = {
        "conversational_turns": dict,
        "attempts": list,
        "attempt_flipped": list,
        "budget_grid": list,
        "strength_dimension": str,
        "budget_to_first_flip": (int, type(None)),
    }
    _USAGE_FIELDS: ClassVar[dict] = {
        "model": str,
    }

    @classmethod
    def _checked_usage(cls, usage: object, where: str) -> None:
        if usage is None:
            return
        if not isinstance(usage, dict):
            raise ValueError(
                f"{where} field 'usage' must be an object or null, "
                f"got {type(usage).__name__}"
            )
        for key in usage:
            if key not in (
                "model", "tokens_in", "tokens_out", "latency_ms", "cost_usd",
                "price_table_ref",
                # R-20: per-call telemetry (finish reason, cached-input
                # breakdown, provider response id).
                "finish_reason", "cached_tokens_in", "provider_response_id",
            ):
                raise ValueError(f"{where} has unknown usage field: {key!r}")
        for key in ("model", "tokens_in", "tokens_out", "latency_ms", "cost_usd"):
            if key not in usage:
                raise ValueError(f"{where} usage is missing field: {key!r}")
        if not isinstance(usage["model"], str):
            raise ValueError(
                f"{where} usage field 'model' must be str, "
                f"got {type(usage['model']).__name__}"
            )
        ref = usage.get("price_table_ref")
        if ref is not None and not isinstance(ref, str):
            raise ValueError(
                f"{where} usage field 'price_table_ref' must be str or null, "
                f"got {type(ref).__name__}"
            )
        for key in ("tokens_in", "tokens_out"):
            if not _is_int(usage[key]):
                raise ValueError(
                    f"{where} usage field {key!r} must be an integer, "
                    f"got {type(usage[key]).__name__}"
                )
            if usage[key] < 0:
                raise ValueError(
                    f"{where} usage field {key!r} must be non-negative, "
                    f"got {usage[key]}"
                )
        for key in ("latency_ms", "cost_usd"):
            if not _is_num(usage[key]):
                raise ValueError(
                    f"{where} usage field {key!r} must be a number, "
                    f"got {type(usage[key]).__name__}"
                )
            if not usage[key] >= 0:
                raise ValueError(
                    f"{where} usage field {key!r} must be non-negative, "
                    f"got {usage[key]}"
                )
        # R-20: optional telemetry fields.
        for key in ("finish_reason", "provider_response_id"):
            val = usage.get(key)
            if val is not None and not isinstance(val, str):
                raise ValueError(
                    f"{where} usage field {key!r} must be str or null, "
                    f"got {type(val).__name__}"
                )
        cached = usage.get("cached_tokens_in")
        if cached is not None:
            if not _is_int(cached):
                raise ValueError(
                    f"{where} usage field 'cached_tokens_in' must be an "
                    f"integer or null, got {type(cached).__name__}"
                )
            if cached < 0:
                raise ValueError(
                    f"{where} usage field 'cached_tokens_in' must be "
                    f"non-negative, got {cached}"
                )
            if cached > usage["tokens_in"]:
                raise ValueError(
                    f"{where} usage field 'cached_tokens_in' ({cached}) "
                    f"exceeds 'tokens_in' ({usage['tokens_in']}): cached "
                    f"tokens are a subset of input tokens"
                )

    @classmethod
    def _checked_call_record(cls, record: object, where: str) -> dict:
        if not isinstance(record, dict):
            raise ValueError(
                f"{where} must be an object, got {type(record).__name__}"
            )
        for key in record:
            if key not in (
                "decision", "confidence", "abstained", "refusal_reason",
                "usage", "seed", "dispatch_index", "malformed",
                "dispatch_limit", "score", "latency_ms_total", "timed_out",
                "timeout_kind", "cached", "timing_ms", "sampling_config",
                # v3 per-call additions: error taxonomy ("" = no error),
                # observed retry count, and input/output hashes for
                # duplication and caching analysis (hashes only, never
                # the raw prompts/completions).
                "error_code", "retry_count",
                "prompt_hash", "completion_hash",
            ):
                raise ValueError(f"{where} has unknown field: {key!r}")
        for key in (
            "decision", "abstained", "refusal_reason",
            "seed", "dispatch_index", "malformed", "dispatch_limit",
        ):
            if key not in record:
                raise ValueError(f"{where} is missing field: {key!r}")
        for key, typ in cls._CALL_RECORD_FIELDS.items():
            if not isinstance(record[key], typ):
                raise ValueError(
                    f"{where} field {key!r} must be {typ.__name__}, "
                    f"got {type(record[key]).__name__}"
                )
        # timed_out is a bool flag like malformed/abstained: a JSON
        # `true`/`false` only (bool check first: isinstance(True, int)
        # is True, so the int fields below would accept it).
        timed_out = record.get("timed_out", False)
        if not isinstance(timed_out, bool):
            raise ValueError(
                f"{where} field 'timed_out' must be a boolean, "
                f"got {type(timed_out).__name__}"
            )
        # timeout_kind types the timeout explicitly: "attempt" or
        # "item" on a timed-out record, absent (None) otherwise. A
        # kind on a non-timed-out record, or an unknown kind string,
        # is corrupt data.
        timeout_kind = record.get("timeout_kind")
        if timeout_kind is None:
            if timed_out:
                # Pre-kind artifacts: every timeout then was a
                # per-attempt timeout; the kind is inferred, not
                # defaulted.
                pass
        elif (
            not timed_out or timeout_kind not in ("attempt", "item")
        ):
            raise ValueError(
                f"{where} field 'timeout_kind' must be 'attempt' or "
                f"'item' on a timed-out record, got {timeout_kind!r}"
            )
        # cached marks response-cache hits (no provider call was made):
        # same bool-only treatment as timed_out.
        cached = record.get("cached", False)
        if not isinstance(cached, bool):
            raise ValueError(
                f"{where} field 'cached' must be a boolean, "
                f"got {type(cached).__name__}"
            )
        # latency_ms_total is cumulative wall-clock ms (all attempts +
        # backoff); absent in pre-Phase-0 artifacts. Numeric, never a
        # bool, never negative.
        total_lat = record.get("latency_ms_total", 0.0)
        if not _is_num(total_lat) or total_lat < 0:
            raise ValueError(
                f"{where} field 'latency_ms_total' must be a "
                f"non-negative number, got {total_lat!r}"
            )
        for key, typ in cls._CALL_RECORD_FIELDS.items():
            if not isinstance(record[key], typ):
                raise ValueError(
                    f"{where} field {key!r} must be {typ.__name__}, "
                    f"got {type(record[key]).__name__}"
                )
        confidence = record.get("confidence")
        if confidence is not None and not _is_num(confidence):
            raise ValueError(
                f"{where} field 'confidence' must be a number or null, "
                f"got {type(confidence).__name__}"
            )
        # A3 S6: the adapter's raw score for score-primitive calls; null
        # for other primitives and absent in pre-S6 artifacts. The score
        # space is the unit interval — the same rule as the adapter-output
        # contract (adapters/base.py::_unit_interval): NaN/Infinity (which
        # Python's json accepts but serde_json rejects at parse) and
        # out-of-range values fail the strict loader, so both backends
        # agree on what an artifact may contain.
        score = record.get("score")
        if score is not None:
            err = _unit_interval("score", score)
            if err is not None:
                raise ValueError(f"{where} field 'score': {err}")
        for key in ("seed", "dispatch_index", "dispatch_limit"):
            if not _is_int(record[key]):
                raise ValueError(
                    f"{where} field {key!r} must be an integer, "
                    f"got {type(record[key]).__name__}"
                )
        if "usage" not in record:
            raise ValueError(f"{where} is missing field: 'usage'")
        cls._checked_usage(record["usage"], where)
        # R-12 timing decomposition: absent in pre-R-12 artifacts (the
        # zero breakdown is the honest reading there). When present it
        # must be the four-component mapping of finite non-negative
        # numbers: _is_num rejects bools, `not tval >= 0` rejects
        # negatives and NaN, and the tuple rejects infinities.
        timing = record.get("timing_ms")
        if timing is not None:
            if not isinstance(timing, dict):
                raise ValueError(
                    f"{where} field 'timing_ms' must be an object, "
                    f"got {type(timing).__name__}"
                )
            # Reject unknown keys: silently accepting a newer/renamed
            # field could verify a lock under changed semantics.
            for tkey in timing:
                if tkey not in (
                    "admission_wait_ms", "adapter_execution_ms",
                    "harness_overhead_ms", "backoff_ms",
                ):
                    raise ValueError(
                        f"{where} has unknown timing_ms field: {tkey!r}"
                    )
            for tkey in (
                "admission_wait_ms", "adapter_execution_ms",
                "harness_overhead_ms", "backoff_ms",
            ):
                tval = timing.get(tkey)
                if (
                    not _is_num(tval)
                    or not tval >= 0
                    or tval in (float("inf"), float("-inf"))
                ):
                    raise ValueError(
                        f"{where} field 'timing_ms.{tkey}' must be a "
                        f"finite non-negative number, got {tval!r}"
                    )
        # R-04 sampling config: absent in pre-R-04 artifacts. When
        # present it must be an object whose source is in the closed
        # vocabulary; a hand-edited source is corrupt data.
        sampling_config = record.get("sampling_config")
        if sampling_config is not None:
            if not isinstance(sampling_config, dict):
                raise ValueError(
                    f"{where} field 'sampling_config' must be an "
                    f"object or null, "
                    f"got {type(sampling_config).__name__}"
                )
            source = sampling_config.get("sampling_source")
            if source is not None and source not in SAMPLING_SOURCES:
                raise ValueError(
                    f"{where} field 'sampling_config' has unknown "
                    f"sampling_source {source!r}"
                )
        # v3 per-call fields: error_code is the closed terminal-failure
        # taxonomy ("" = no error); retry_count is the observed number
        # of retries this call actually took; prompt_hash /
        # completion_hash are content hashes (never raw text) for
        # duplication and caching analysis. All default for v2-era
        # records; v3 runners write them.
        error_code = record.get("error_code", "")
        if error_code not in ERROR_CODES:
            raise ValueError(
                f"{where} field 'error_code' must be one of "
                f"{sorted(ERROR_CODES)}, got {error_code!r}"
            )
        retry_count = record.get("retry_count", 0)
        if not _is_int(retry_count) or retry_count < 0:
            raise ValueError(
                f"{where} field 'retry_count' must be a non-negative "
                f"integer, got {retry_count!r}"
            )
        for key in ("prompt_hash", "completion_hash"):
            value = record.get(key, "")
            if not isinstance(value, str):
                raise ValueError(
                    f"{where} field {key!r} must be a string, "
                    f"got {type(value).__name__}"
                )
        # Return a clean copy with v3 defaults applied: the strict
        # loader must not mutate its input (the caller's dict may be
        # reused), and __post_init__ relies on the same normalization.
        clean = dict(record)
        clean.setdefault("error_code", "")
        clean.setdefault("retry_count", 0)
        clean.setdefault("prompt_hash", "")
        clean.setdefault("completion_hash", "")
        return clean

    @classmethod
    def _checked_conversational_turns(
        cls, value: object, where: str
    ) -> dict:
        """Validate the conversational suite's sealed turn records.

        Exactly two arms, each a list of strictly-validated call
        records. The scored final-turn pair lives in the entry's
        ``benign``/``attacked`` fields; this section is drill-down only.
        """
        if not isinstance(value, dict):
            raise ValueError(
                f"{where} must be an object, got {type(value).__name__}"
            )
        if set(value) != {"benign_turns", "attacked_turns"}:
            raise ValueError(
                f"{where} must hold exactly 'benign_turns' and "
                f"'attacked_turns', got {sorted(value)}"
            )
        clean: dict = {}
        for arm in ("benign_turns", "attacked_turns"):
            turns = value[arm]
            if not isinstance(turns, list) or not turns:
                raise ValueError(
                    f"{where} field {arm!r} must be a non-empty list, "
                    f"got {type(turns).__name__}"
                )
            clean[arm] = [
                cls._checked_call_record(t, f"{where} {arm}[{i}]")
                for i, t in enumerate(turns)
            ]
        return clean

    @classmethod
    def _checked_results(cls, entries: list) -> list[dict]:
        """Validate result entries, returning clean dicts for the dataclass."""
        clean: list[dict] = []
        for i, entry in enumerate(entries):
            where = f"artifact results entry {i}"
            if not isinstance(entry, dict):
                raise ValueError(
                    f"{where} must be an object, "
                    f"got {type(entry).__name__}"
                )
            for key in entry:
                if (key not in cls._RESULT_REQUIRED
                        and key not in cls._RESULT_OPTIONAL):
                    raise ValueError(f"{where} has unknown field: {key!r}")
            known: dict = {}
            for key, typ in cls._RESULT_REQUIRED.items():
                if key not in entry:
                    raise ValueError(
                        f"{where} is missing required field: {key!r}"
                    )
                if not isinstance(entry[key], typ):
                    raise ValueError(
                        f"{where} field {key!r} must be {typ.__name__}, "
                        f"got {type(entry[key]).__name__}"
                    )
                known[key] = entry[key]
            for key, typ in cls._RESULT_OPTIONAL.items():
                if key not in entry:
                    continue
                if not isinstance(entry[key], typ):
                    raise ValueError(
                        f"{where} field {key!r} must be {typ.__name__}, "
                        f"got {type(entry[key]).__name__}"
                    )
                if key == "conversational_turns":
                    known[key] = cls._checked_conversational_turns(
                        entry[key], f"{where} conversational_turns"
                    )
                elif key == "attempts":
                    known[key] = [
                        cls._checked_call_record(t, f"{where} attempts[{i}]")
                        for i, t in enumerate(entry[key])
                    ]
                elif key == "attempt_flipped":
                    if not all(isinstance(x, bool) for x in entry[key]):
                        raise ValueError(
                            f"{where} field 'attempt_flipped' must be a "
                            f"list of booleans"
                        )
                    known[key] = entry[key]
                elif key == "budget_grid":
                    grid = entry[key]
                    if (not grid
                            or not all(isinstance(x, int)
                                       and not isinstance(x, bool)
                                       and x > 0 for x in grid)
                            or any(b >= c for b, c in zip(grid, grid[1:]))):
                        raise ValueError(
                            f"{where} field 'budget_grid' must be a "
                            f"strictly increasing list of positive ints"
                        )
                    known[key] = entry[key]
                else:  # pragma: no cover - future optional fields
                    known[key] = entry[key]
            # Sweep cross-field validation: the per-attempt records must
            # align, and budget_to_first_flip must be a grid level (or
            # None for never-flipped).
            if "attempts" in known or "attempt_flipped" in known:
                attempts = known.get("attempts", [])
                flipped = known.get("attempt_flipped", [])
                if len(attempts) != len(flipped):
                    raise ValueError(
                        f"{where} has {len(attempts)} attempts but "
                        f"{len(flipped)} attempt_flipped entries"
                    )
                grid = known.get("budget_grid", [])
                btf = known.get("budget_to_first_flip")
                if btf is not None and btf not in grid:
                    raise ValueError(
                        f"{where} budget_to_first_flip={btf} not in "
                        f"budget_grid={grid}"
                    )
            known["benign"] = cls._checked_call_record(
                entry["benign"], f"{where} benign"
            )
            known["attacked"] = cls._checked_call_record(
                entry["attacked"], f"{where} attacked"
            )
            clean.append(known)
        return clean

    @classmethod
    def from_json(cls, s: str) -> "RunArtifact":
        try:
            d = json.loads(s)
        except json.JSONDecodeError as e:
            raise ValueError(f"artifact is not valid JSON: {e}") from e
        if not isinstance(d, dict):
            raise ValueError("artifact must be a JSON object")
        for key in d:
            if (
                key not in cls._FIELD_TYPES
                and key not in cls._NUM_FIELDS
                and key not in cls._NULLABLE_NUM_FIELDS
                and key not in cls._NULLABLE_INT_FIELDS
            ):
                raise ValueError(f"unknown artifact field: {key!r}")
        for key in cls._REQUIRED_FIELDS:
            if key not in d:
                raise ValueError(f"artifact is missing required field: {key!r}")
        for key, typ in cls._FIELD_TYPES.items():
            if key in cls._INT_FIELDS:
                continue  # checked below with the bool-rejecting message
            if key not in d:
                continue
            if not isinstance(d[key], typ):
                raise ValueError(
                    f"artifact field {key!r} must be {typ.__name__}, "
                    f"got {type(d[key]).__name__}"
                )
        for key in cls._NUM_FIELDS:
            if key in d and not _is_num(d[key]):
                raise ValueError(
                    f"artifact field {key!r} must be a number, "
                    f"got {type(d[key]).__name__}"
                )
        for key in cls._NULLABLE_NUM_FIELDS:
            if key in d and d[key] is not None and not _is_num(d[key]):
                raise ValueError(
                    f"artifact field {key!r} must be a number or null, "
                    f"got {type(d[key]).__name__}"
                )
        for key in cls._NULLABLE_INT_FIELDS:
            if key in d and d[key] is not None and not _is_int(d[key]):
                raise ValueError(
                    f"artifact field {key!r} must be an integer or null, "
                    f"got {type(d[key]).__name__}"
                )
        for key in cls._INT_FIELDS:
            if key in d and not _is_int(d[key]):
                raise ValueError(
                    f"artifact field {key!r} must be an integer, "
                    f"got {type(d[key]).__name__}"
                )
        version = d.get("artifact_version", ARTIFACT_VERSION)
        if version != ARTIFACT_VERSION:
            raise ValueError(_UNSUPPORTED_VERSION.format(version=version))
        fields = {
            key: (default() if callable(default) else default)
            for key, default in cls._FIELD_DEFAULTS.items()
        }
        fields.update(d)
        # v3 closed vocabularies: the strict loader rejects anything
        # outside the closed sets (free-form strings are a silent
        # schema-drift vector for agent consumers). Missing keys keep
        # the dataclass defaults.
        for key, vocab in (
            ("run_status", RUN_STATUSES),
            ("termination", TERMINATIONS),
            ("model_class", MODEL_CLASSES),
            ("confidence_source", CONFIDENCE_SOURCES),
            ("access_tier", ACCESS_TIERS),
        ):
            if key in d and d[key] not in vocab:
                raise ValueError(
                    f"artifact field {key!r} must be one of "
                    f"{sorted(vocab)}, got {d[key]!r}"
                )
        # v3 structured blocks: strictly validated (unknown fields
        # rejected, like everywhere else in the strict loader). A
        # missing block gets the honest "undeclared" defaults from its
        # factory; a present block must be complete and in-vocabulary.
        for key, spec in cls._BLOCK_SPECS.items():
            if key in d:
                fields[key] = _checked_block(d[key], spec, f"artifact field {key!r}")
            else:
                fields[key] = cls._BLOCK_DEFAULTS[key]()
        # v3 typed per-family stats and the machine-readable error
        # (exclusion) log.
        fields["per_family_stats"] = _checked_per_family_stats(
            fields.get("per_family_stats", []), "artifact field 'per_family_stats'"
        )
        fields["error_log"] = _checked_error_log(
            fields.get("error_log", []), "artifact field 'error_log'"
        )
        if "results" in d:
            # Validated, but kept as plain dicts: the runner stores results
            # as dicts (see results_to_dicts), and compute_lock serializes
            # them directly — PerCaseResult objects would break seal().
            fields["results"] = cls._checked_results(d["results"])
        return cls(**fields)


def results_to_dicts(
    results: list[PerCaseResult], to_dict=None
) -> list[dict]:
    import dataclasses

    # asdict recurses into the nested CallRecord/CallUsage dataclasses,
    # producing the plain-dict entry shape the artifact seals. Suites
    # with suite-namespaced entry fields (conversational) pass their own
    # serializer; the default keeps the strict single-shot shape.
    serialize = to_dict if to_dict is not None else dataclasses.asdict
    return [serialize(r) for r in results]


def error_log_from_results(results: list[dict]) -> list[dict]:
    """Aggregate the artifact's error_log exclusion table from results.

    Walks each result dict's ``benign``/``attacked`` call records and
    emits one ``{"case_id", "arm", "error_code"}`` row per record with a
    non-empty ``error_code`` (timeouts, adapter raises, malformed
    outputs — every case the suite could not measure). The aggregated
    table is re-validated, so a malformed record can never corrupt the
    exclusion list the artifact seals.
    """
    log: list[dict] = []
    for result in results:
        case_id = result.get("case_id", "")
        for arm in ("benign", "attacked"):
            record = result.get(arm)
            if not isinstance(record, dict):
                continue
            error_code = record.get("error_code", "")
            if error_code:
                log.append(
                    {
                        "case_id": case_id,
                        "arm": arm,
                        "error_code": error_code,
                    }
                )
    return _checked_error_log(log, "error_log")
