# syntax=docker/dockerfile:1
# peira reproducible environment.
#
# Multi-stage build:
#   1. rust-builder -- compiles the optional PyO3 accelerator (peira._core)
#      from crates/peira-python against the pinned Cargo.lock.
#   2. runtime     -- Python 3.12 + pip-installed peira with its pinned
#      lockfile, the built Rust extension, and the versioned datasets.
#
# Build-only by default: no image is pushed to any registry. See
# .github/workflows/docker-build.yml and docs/Reproducibility.md.
#
#   docker build -t peira:local .
#   docker build -t peira:local --build-arg EXTRAS_LOCK=all.lock .
#   docker run --rm peira:local run --adapter mock --suite trial --seed 0 --out /tmp/runs

# ---------------------------------------------------------------------------
# Stage 1: build the Rust accelerator.
# ---------------------------------------------------------------------------
FROM rust:1.98.1-slim-bookworm AS rust-builder

# PyO3's build script needs a Python interpreter to query (it does not
# link libpython on Linux with the extension-module feature, so the
# -dev headers are unnecessary).
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build

# The Rust toolchain is pinned by rust-toolchain.toml (1.98.1) and every
# crate dependency by Cargo.lock; copying the manifests first keeps the
# dependency layer cacheable.
COPY Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY crates/ crates/

RUN cargo build --release -p peira-python

# ---------------------------------------------------------------------------
# Stage 2: Python runtime.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# Which pinned lockfile to install. `dev.lock` (the default) covers the
# base package plus the test tooling CI uses; `all.lock` adds the
# Hugging Face and LLM-adapter extras (large: pulls torch).
ARG EXTRAS_LOCK=dev.lock

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /peira

# Install the pinned third-party dependencies first: this layer only
# rebuilds when the lockfiles change, not on every code edit.
# dev.lock (the default) carries --generate-hashes pins, so
# --require-hashes makes the install tamper-evident. all.lock is
# version-pinned only: hash-pinning torch's CUDA tree would require
# multi-GB downloads at lock time (see docs/Reproducibility.md).
COPY requirements/ requirements/
RUN if grep -q -- "--hash" "requirements/${EXTRAS_LOCK}"; then \
      pip install --require-hashes -r "requirements/${EXTRAS_LOCK}"; \
    else \
      pip install -r "requirements/${EXTRAS_LOCK}"; \
    fi

# Install peira itself, editable from the /peira checkout. The editable
# install is load-bearing, not a shortcut: cli.py and dataset.py resolve
# the repo root as three levels up from python/peira/cli.py, so the
# package must live in the checkout layout rather than site-packages.
# The base tier has zero third-party runtime dependencies by design (see
# AGENTS.md); --no-deps keeps it that way and lets the lockfile stay the
# single source of truth for everything else.
COPY pyproject.toml README.md ./
COPY python/ python/
RUN pip install -e . --no-deps

# Install the Rust accelerator built in stage 1 next to the checked-out
# package, exactly as scripts/build_core_ext.py does for a local
# checkout. The extension suffix is computed, not hardcoded, so the
# Dockerfile survives Python upgrades.
COPY --from=rust-builder /build/target/release/lib_core.so /tmp/lib_core.so
RUN EXT_SUFFIX=$(python3 -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))") && \
    cp /tmp/lib_core.so "/peira/python/peira/_core$EXT_SUFFIX" && \
    rm /tmp/lib_core.so && \
    python3 -c "from peira._rust import RUST_AVAILABLE; assert RUST_AVAILABLE, 'Rust extension failed to import'"

# Ship the versioned datasets so suite runs work out of the box.
# They are part of the repo snapshot; refresh by rebuilding.
COPY dataset/ dataset/

# The CLI writes run artifacts wherever --out points; default to a
# writable home for the non-root user.
RUN useradd --create-home --shell /bin/bash peira && \
    chown -R peira:peira /peira /home/peira
USER peira
WORKDIR /home/peira

ENTRYPOINT ["peira"]
CMD ["--help"]
