# FAQ

**Is peira a red-team / attack tool?**
No. It's a measurement harness. The attacks are published so defenders can
test their decision models against them, the same way crash-test dummies
are published so car makers can test cars.

**Does a good score certify my model as safe?**
No. A peira score measures robustness on this benchmark's paired decision
cases. It says nothing about open-ended generation, real deployment risk,
or attacks outside the 10 v1 families (200 cases each). The separate
safety-policy suite covers classifier guardrails. See the non-certification notice in the
README.

**How much does a full run cost?**
The mock adapter costs nothing but time. Local HF adapters cost nothing
but electricity. Hosted runs cost whatever your provider charges per call.
A full v1 run is ~4,000 decisions (2,000 public cases x benign/attacked pair).
A full v2 run is ~7,700 decisions (3,861 cases x pair). Start
with the trial-demo fixture (12 cases). It's free and offline.

**Can I run fully offline?**
Yes. `pip install -e .` from a checkout (no extras) + the mock adapter
never touches the network. Local HF adapters download weights once, then
run offline. Only hosted adapters need API access.

**How do I add my model?**
Write an adapter (about 30 lines). See `examples/minimal_adapter.py`,
then save yours as `my_adapter.py` and run
`peira run --adapter my_adapter --suite trial-demo`.

**Why did my score change between peira versions?**
Scores are tied to the dataset version and the peira version (both in the
run artifact). Check the CHANGELOG. Dataset changes are versioned and the
planned leaderboard will keep one row per (adapter, dataset version) pair.

**How do I plug in my own model without forking peira?**
Ship it as a package with a `peira.adapters` entry point, then
`peira adapter check <your-id>` and `peira run --adapter <your-id>`.
Your adapter runs isolated in a subprocess by default. The full
author guide is `docs/third-party-adapters.md`.

**Is the subprocess isolation a security sandbox?**
No. It is blast-radius containment and killability: your adapter
runs in its own process with a scrubbed environment, its own
process group, and per-child resource limits, so a hung or greedy
adapter cannot take down the run. It does not filter syscalls or
network egress, and it does not change UIDs. A malicious adapter
can still do anything its UID can do. Only run adapters you trust.

**Why did `peira adapter check` refuse my dotted path?**
The kit tests what the runner will actually do, so it needs a
registered id for the shim and the name-vs-attribute binding.
Register the `peira.adapters` entry point first, then check the
registry id.

**My adapter passed `check`, then I shipped a new version. Is the badge still good?**
No. The check report seals the SHA-256 of the module file that was
actually loaded. The badge covers exact bits only. Re-run
`peira adapter check` for the new version. Anyone can confirm the
installed bits match a report with
`peira adapter check --verify <report>`.

**Why is my adapter listed as "partial coverage"?**
Your adapter doesn't implement every primitive (Choice/Score/Abstain).
That's fine. Coverage is reported honestly per primitive instead of
penalized.

**Where do questions go?**
GitHub Discussions (Q&A category). Bugs go in Issues. Security issues go
through private security advisories (see SECURITY.md).
