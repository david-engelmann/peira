# FAQ

**Is peira a red-team / attack tool?**
No. It's a measurement harness. The attacks are published so defenders can
test their decision models against them — the same way crash-test dummies
are published so car makers can test cars.

**Does a good score certify my model as safe?**
No. A peira score measures robustness on this benchmark's paired decision
cases. It says nothing about open-ended generation, real deployment risk,
or attacks outside the 10 families. See the non-certification notice in the
README.

**How much does a full run cost?**
The mock adapter costs nothing but time. Local HF adapters and hosted
adapters are planned; hosted runs will cost whatever your provider
charges for ~5,000 decisions. Start with the trial-demo fixture
(12 cases) — it's free and offline.

**Can I run fully offline?**
Yes. `pip install -e .` from a checkout (no extras) + the mock adapter
never touches the network. (Local HF adapters are planned.) Only hosted
adapters need API access.

**How do I add my model?**
Write an adapter — about 30 lines. See `examples/minimal_adapter.py`,
then save yours as `my_adapter.py` and run
`peira run --adapter my_adapter --suite trial-demo`.

**Why did my score change between peira versions?**
Scores are tied to the dataset version and the peira version (both in the
run artifact). Check the CHANGELOG; dataset changes are versioned and the
planned leaderboard will keep one row per (adapter, dataset version) pair.

**Why is my adapter listed as "partial coverage"?**
Your adapter doesn't implement every primitive (Choice/Score/Noul).
That's fine — coverage is reported honestly per primitive instead of
penalized.

**Where do questions go?**
GitHub Discussions (Q&A category). Bugs go in Issues. Security issues go
through private security advisories — see SECURITY.md.
