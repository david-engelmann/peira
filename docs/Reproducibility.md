# Reproducibility

Two artifacts pin the peira environment so a run can be reproduced
exactly: the Python lockfiles and the Docker image. Both are built from
the same pinned inputs and both are verified in CI.

## Python lockfiles

`requirements/` holds pip-tools lockfiles generated from
`pyproject.toml` with `pip-compile --generate-hashes`:

| File | Contents | Install with |
| --- | --- | --- |
| `base.lock` | The base package. Empty by design: the base tier has zero third-party runtime dependencies (AGENTS.md protects this invariant). | `pip install -e .` |
| `dev.lock` | Base plus the `dev` extra: pytest, pytest-xdist, pytest-timeout. Hash-pinned. This is what CI installs. | `pip install --require-hashes -r requirements/dev.lock` then `pip install -e . --no-deps` |
| `all.lock` | Everything: `dev` plus the `hf`, `openai`, `anthropic`, and `google` extras. Version-pinned (not hash-pinned: hashing torch's CUDA tree needs multi-GB downloads at lock time). Large: pulls torch. | `pip install -r requirements/all.lock` then `pip install -e . --no-deps` |

`--require-hashes` makes the install tamper-evident: pip refuses any
wheel whose hash is not in the lockfile. The lockfiles are resolved for
CPython 3.12, the version CI runs.

### Regenerating

After changing dependencies in `pyproject.toml`:

```bash
pip install pip-tools
pip-compile --generate-hashes --output-file=requirements/base.lock pyproject.toml
pip-compile --generate-hashes --extra dev --output-file=requirements/dev.lock pyproject.toml
pip-compile --extra all --extra dev --output-file=requirements/all.lock pyproject.toml
```

`all.lock` is version-pinned without hashes: `--generate-hashes`
against torch's CUDA dependency tree downloads gigabytes of wheels at
lock time, which is impractical. The Dockerfile installs whichever
lockfile carries hashes with `--require-hashes` and the rest with
plain version pins.

Commit the regenerated lockfiles in the same PR as the
`pyproject.toml` change. Reviewers check that the diff only touches
the intended packages.

### Lockfile drift warning

A run on a machine whose torch, transformers, or numpy differs from
`requirements/all.lock` is still a valid run, but its numbers may not
reproduce on a pinned install. The runner warns at run start when an
adapter that executes the local ML stack (the Hugging Face adapters
in `python/peira/adapters/hf.py`, marked with `uses_local_ml_stack`)
drifts from the lockfile. The warning is advisory and never fails the
run. API adapters get no warning. The local environment does not
score their calls. The installed versions are already sealed in the
artifact's environment fingerprint, so drift is detectable after the
fact from the artifact alone.

## Determinism verification

`scripts/check_determinism.py` proves reruns reproduce. It runs the
deterministic mock adapter twice as real CLI invocations with
different `--max-concurrency` values, then compares the two sealed
artifacts with `peira.repro`. Decisions, seeds, and flags must match
exactly. Float metrics compare within 1e-9. Each artifact's own
analysis lock must verify. The `determinism` CI job runs it on every
push and PR. Run it locally with `python3
scripts/check_determinism.py`. The normalization it applies is the
executable form of `docs/Execution-Contract.md`. Wall-clock timing
and the AIMD controller's live limit are excluded there and here.

## Docker image

`Dockerfile` is a multi-stage build:

1. **rust-builder** (`rust:1.98.1-slim-bookworm`, matching
   `rust-toolchain.toml`): compiles the optional PyO3 accelerator
   (`peira._core`) from `crates/peira-python` against the pinned
   `Cargo.lock`.
2. **runtime** (`python:3.12-slim-bookworm`): installs the pinned
   lockfile with `--require-hashes`, installs peira editable from the
   `/peira` checkout (editable is load-bearing: the CLI resolves
   dataset paths from the repo root relative to the package files),
   copies the built `_core` extension next to the package exactly as
   `scripts/build_core_ext.py` does, and ships the versioned datasets
   so trial runs work out of the box. Runs as a non-root `peira` user
   with `peira` as the entrypoint.

### Build

```bash
docker build -t peira:local .
```

With the full adapter extras (Hugging Face + LLM baselines):

```bash
docker build -t peira:local --build-arg EXTRAS_LOCK=all.lock .
```

### Run

```bash
docker run --rm peira:local run --adapter mock --suite trial --seed 0 --out /tmp/runs
```

Exit 3 is the expected result: the run completes but the 100-case
Trial sits below the ranking floors, so it is ranking-ineligible (the
same convention the README quickstart documents).

To persist artifacts outside the container, mount a volume:

```bash
docker run --rm -v "$PWD/runs:/home/peira/runs" peira:local \
  run --adapter mock --suite trial --seed 0 --out /home/peira/runs
```

### What the image contains and what it does not

The image contains the peira package at the built commit, its
pinned Python dependencies, the compiled Rust accelerator, and the
datasets as committed. It does not contain API keys (pass them with
`-e`), the private holdout (never baked into any image), or a pushed
registry tag. Images are built, never pushed. Registry pushes stay
manual until an external reproducibility request asks for one.

## CI

`.github/workflows/docker-build.yml` builds the image on every push
to main and every PR, then smoke-tests it: the Rust extension must
import and the mock trial run must complete. The job is build-only.
Nothing leaves the runner.
