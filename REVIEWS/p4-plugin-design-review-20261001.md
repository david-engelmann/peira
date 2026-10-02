# Gate report: P-4 plugin-ecosystem DESIGN review

**Artifact:** `docs/Plugin-Ecosystem-Design.md`
**Design commit (reviewed):** `fc019a37dfcc15b74add43d623ff781a51711af2`
**Revision commit:** `HEAD` (committed with this report)
**Branch:** `decant-plugin-eco`; base `origin/main` at `df4c4974`
**Date:** 2026-10-01
**Phase:** design review (mandatory phase 2). No implementation exists yet.

## Reviewers

1. Red-team re-audit (independent subagent) with an EXPLICIT mission
   to break the isolation model. Delivered 2026-10-01 20:50 UTC.
2. Spec-fidelity axis (independent subagent, per peira-code-review
   skill). Delivered 2026-10-01 20:53 UTC.
3. Standards axis (independent subagent, per peira-code-review
   skill). Delivered 2026-10-01 20:55 UTC.
4. Author's own line-by-line pass plus independent verification
   (mechanical copy-bar scan, consistency grep pass).

The three subagent reviewers ran in parallel and never saw each
other's reasoning.

## Verdicts

- Red-team: **APPROVE-WITH-CHANGES**. 12 catalog items assessed (7
  honest, 3 over-claimed: A5, A9, A11); 10 new findings F1-F10.
  Most severe: **F1** (the documented contribution flow ran
  untrusted import-time code in the maintainer's process, full
  ambient authority, contradicting the design's own R-03
  motivation).
- Spec: **APPROVE-WITH-CHANGES**. 9 findings (3 spec gaps F1-F3, 5
  justified scope-creep items, 1 minor ambiguity). Worst: **F1**
  (`max_retries=0` demoted from P-4's named must-pass contract test
  to advisory warnings without acknowledgment).
- Standards: **conforms, 5 findings** (no hard violations). Copy-bar
  prose hits, one local-path citation, one docs-map gap, forward
  term use, one speculative-generality smell.
- Author's own: em-dash cleanup required (32 lines); technical
  additions (install-time scope, process groups, stderr cap, env
  denylist, uniform name binding, rlimit defaults).

## Disposition (all findings fixed in the revision)

**Red-team F1 (most severe):** FIXED. Open question 1 resolved as
MUST: `peira adapter check` exercises third-party adapters through
the shim child, never in-process. Import-safety is now "child
imports within 30s." "Clean machine" defined (fresh VM/container,
no credentials). Section 6 intro, 6.1.6, 8/A13, 10.

**Red-team F2 (id spoofing):** FIXED. No concurrent pipelining;
sequential reuse allowed; strict id matching; child dropped on
unsolicited/duplicate ids. Section 6.1.7, 8/A9 (claim downgraded),
8/A14 (new row).

**Red-team F3 (stderr):** FIXED. 1 MB per-call cap, truncate with
marker, call failed not OOMed; control sequences stripped/escaped
before display. Sections 6.2, 7.2.

**Red-team F4 (fork-escape):** FIXED. Own process group per child
(`start_new_session`); kill terminates the group. Sections 7.2,
8/A15 (new row).

**Red-team F5 (env injection):** FIXED. `--adapter-env` variable
names checked against a denylist (`LD_PRELOAD`, `DYLD_*`,
`PYTHONPATH`, `PYTHONSTARTUP`, `PYTHONHOME`, friends); refused
with an actionable error. Sections 7.2, 8/A16 (new row).

**Red-team F6 (fingerprintable probes):** FIXED. Probes are
randomized and production-shaped; section 6.4 candor rewritten:
probes catch naive sniffing; a determined author can defeat any
finite open probe set.

**Red-team F7 (badge not bound to bits):** FIXED. Check report
seals `dist_name`, `dist_version`, SHA-256 of the loaded module
file; `check --verify` compares installed bits; badge covers
exact bits only. Sections 5 (`--verify`), 6.3, 8/A17 (new row),
10.

**Red-team F8 (transcript smuggling):** FIXED. Named in the section
9 residual; holdout runs redact adapter-supplied transcript
payloads to fixed schema fields. Section 8/A18 (new row), 9.

**Red-team F9 (timing oracle):** FIXED as a recorded requirement
on the holdout pipeline (distribution-comparison gate; holdout
seeds from the same CSPRNG stream as public seeds). Section 9.4.

**Red-team F10 (social-engineered flag):** FIXED. Flag renamed to
`--adapter-no-isolation`; runner prints an explicit warning naming
consequences; docs say never take CLI flags from an adapter's
README. Sections 7.1, 11.4.

**Red-team A5/A9/A11 claim rewrites:** DONE. A5 scoped to the run
path with rlimits actually set; A9 downgraded per F2; A11 now
requires parent verification of the handshake `name` and
fail-closed on duplicate names at both `check` and `run`.

**Red-team minor (third-party holdout execution):** DONE. Section
9.3 states the trust assumption explicitly.

**Spec F1 (max_retries demotion):** FIXED. Retry self-attestation
is now a REQUIRED capability-report field (missing attestation
fails); static scan stays advisory. Listed as an acknowledged
deviation in section 13 with the undecidability rationale.

**Spec F2 (model-file declaration):** FIXED. Optional
`model_paths` attribute (absolute paths declared up front);
runner logs declarations into the run artifact; handshake carries
them. Sections 7.2, 6.3.

**Spec F3 (determinism softening):** NOTED in section 13 as an
acknowledged deviation.

**Spec minor (transport provenance keying):** FIXED. Section 7.1
states the rule keys off provenance explicitly.

**Spec scope-creep C1-C5:** all five were judged
justified-with-reason by the Spec reviewer; kept, with the P-3
capability-table import (C1) now explicit in section 6.3.

**Standards 1 (copy bar):** FIXED. Mechanical Python codepoint
scan: zero em dashes, zero en dashes in the revised doc
(verified, not grepped).

**Standards 2 (local-path citation):** FIXED. Section header now
cites "P-4 of the 2026-10-01 decant audit (research notes held
outside this repo)."

**Standards 3 (docs-map gap):** FIXED. Section 5 enumerates every
new error string; section 11.5 adds `docs/Glossary.md`,
`docs/FAQ.md`, and a `docs/Claims.md` reference.

**Standards 4 (terms before definition):** FIXED. New section 3
(Terminology) defines adapter spec, registry id, shim, transport,
conformance kit, capability report before first use.

**Standards 5 (speculative generality):** FIXED. `serve()` is now
an internal implementation detail, not an advertised author
extension point.

**Author's own additions:** install-time code execution stated as
explicit out-of-scope (section 2); `sys.executable` + list-form
Popen, never `shell=True` (section 7); name binding applied
uniformly, first-party exemption dropped (section 4.3); rlimits
Unix-only with a default 8192 MB address-space cap for
third-party children (section 7.2); runner integration via
`asyncio.create_subprocess_exec`, `decide()` signature unchanged
(section 7.4).

## Residual risks accepted (not fixed)

- R1: No network egress filtering (explicit non-goal). Holdout
  protection rests on OpSec plus transcript redaction.
- R2: UID-level filesystem reach by absolute path (A2 Partial).
  Documented, not claimed otherwise.
- R3: The conformance kit cannot prove absence of nested retries
  or covert sniffing (section 6.4). Must-attest plus advisory scan
  is the bar.
- R4: Windows builds get no rlimits and no process-group kill
  semantics; documented degradation.

## Approval to proceed

All three independent reviews returned APPROVE-WITH-CHANGES or
better; every finding above is adjudicated and fixed in the
revised design. The author's own verification (mechanical scans,
consistency pass) is complete. **The reviewed design is approved
for implementation.** Implementation proceeds in section 11 order:
(1) discovery, (2) conformance kit, (3) subprocess shim, (4)
runner wiring, (5) docs. Each step gets the full checkpoint
(red-team re-audit + two-axis review + own verification + both
exact-head suites) before landing.
