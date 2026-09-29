---
title: FAQ
---

# FAQ

## Is peira an attack tool

No. It is a measurement harness. The attacks are published so
defenders can test their decision models against them, the same way
crash-test dummies are published so car makers can test cars. Nothing
here helps anyone build a better attack. It measures whether models
hold their decisions under known ones.

## Does a good score certify a model as safe

No. A peira score measures robustness on these paired decision cases
only. It says nothing about open-ended generation, real deployment
risk, or attacks outside the measured families. Do not read a
leaderboard row as a safety certificate.

## How much does a full run cost

The mock adapter costs nothing but time. Local Hugging Face adapters
cost electricity after a one-time weight download. Hosted runs cost
whatever your provider charges for roughly 4,000 decisions, that is
2,000 public cases times the benign and attacked pair. Start with
the 12-case trial demo. It is free and offline. On paid runs, set
`--budget-usd` to cap spend. A budget-stopped run is analyzable but
never rankable.

## Can I run fully offline

Yes. The base install plus the mock adapter never touches the
network. Local Hugging Face adapters download weights once, then run
offline. Only hosted API adapters need network access.

## How do I add my model

Write an adapter, about 30 lines. The repo ships a minimal example
to copy. Save it as a Python file and pass it to peira run with
`--adapter`. If your adapter implements only some primitives (Choice,
Score, Abstain), coverage is reported honestly per primitive instead
of penalized.

## What is the difference between the Public and Holdout views

The Public view shows runs on the public case set. It is for
development and open comparison. The Holdout view governs the ranked
result and uses cases the adapters have never seen. The two are never
blended into one number. A model that shines on Public but drops on
Holdout is telling you something about generalization, and that is
exactly what the split is for.

## Why did my score change between peira versions

Scores are tied to the dataset version and the peira version, both
sealed in the run artifact. Dataset changes are versioned. The
leaderboard keeps one row per adapter and dataset-version pair, so a
new dataset version means a new row, not a rewritten history.

## Why is my adapter listed as partial coverage

It does not implement every primitive. That is fine. Coverage is
reported honestly per primitive instead of penalized.

## Where do questions go

GitHub Discussions in the Q&A category for questions, Issues for
bugs, and private security advisories for security issues. See the
repo's SECURITY.md for the advisory process.
