# Release process

**Status** Normative. This document is the release checklist for peira.

## Tag-is-version

The signed git release tag is the single source of truth for the package
version. The repo always carries `0.0.0` in `pyproject.toml` and in
`peira.__version__`. Nothing in the repo invents a version.

At publish time the release tooling materializes `git archive <tag>` into a
pristine temp tree and stamps the tag version into exactly two files:
`pyproject.toml` and `python/peira/__init__.py`. The repo tree itself is
never modified. The Rust crates under `crates/` are versioned independently
(they build the `peira._core` native extension, not the PyPI package) and
are never stamped. The dataset is versioned independently too; see
`docs/Compatibility.md`.

Tags are `v` + semver (`v1.2.3`, `v2.0.0-rc.1`). Tags are annotated and
GPG-signed. A tag is never moved, re-signed, or deleted after publishing.
If a release is bad, the fix is a new version, not a rewritten tag.

## Channels

- A prerelease (`-rc.1`, `-alpha`) never moves the stable channel.
- A stable release becomes `latest` only when it is the highest stable tag.
  A backport (stable but not highest, e.g. `v0.2.5` cut after `v0.3.0`)
  ships on PyPI but never moves the `latest` pointer.

## The pipeline

All release logic lives in `scripts/release/`, one script per step, each
with unit tests in `tests/test_release.py`:

1. `preflight.py` checks the tree is clean, the branch is `main` up to
   date with `origin/main`, the repo still carries `0.0.0`, the tag exists
   and is annotated and signed and points at HEAD, `CHANGELOG.md` has a
   curated section for the version, no install command is pinned to the
   `main` branch, and `uv.lock` is in sync.
2. `build.py` extracts the tag, stamps the version, builds the sdist and
   wheel, asserts the wheel METADATA version equals the tag, and prints
   sha256 checksums for the release record.
3. `release.py --publish` uploads with twine (after a typed tag
   confirmation), then runs the smoke test.
4. `smoke.py` creates a clean venv, installs `peira==<version>` from the
   real PyPI, and asserts the installed package imports, reports the right
   version, and answers `peira --version`.

The default is a dry run. Nothing uploads unless `--publish` is passed.

## Release notes are curated

`CHANGELOG.md` is written by hand for every release. Release notes are
never auto-generated from PR titles. A benchmark whose numbers get cited
owes its readers notes a human actually wrote. Preflight fails the release
when the version section is missing.

## Install paths pin to the release

Users install a version, never a branch: `pip install peira==1.2.3`. No
install command in `README.md` or `docs/` may point at the `main` branch
(no `curl ... /main/install.sh`, no `pip install git+...@main`); preflight
scans for these patterns and fails the release if one appears.

## Docs URLs pin to the release

The `[project.urls]` Documentation link in `pyproject.toml` is pinned to
the release tag, never `main`: the repo carries
`https://github.com/david-engelmann/peira/tree/v0.0.0/docs` and the release
build stamps it to `tree/v1.2.3/docs` for the published wheel, so the PyPI
sidebar always shows the docs as of that release. Preflight also scans
`README.md` and `docs/` for hand-written `tree/main` or `blob/main` links
and fails the release if one appears.

## David's manual steps for a real release

Prerequisites: `pip install build twine`, a GPG key configured for the
sign-off identity, and PyPI credentials in `~/.pypirc` or the environment.

1. Finish the work on `main` and write the `CHANGELOG.md` section for the
   new version by hand. Get the three reviews and the full local gates on
   the final head, per the checkpoint rule.
2. Tag the release from the reviewed main head:
   `git tag -s v1.2.3 -m "peira v1.2.3"` and `git push origin v1.2.3`.
3. Dry run: `python scripts/release/release.py --version v1.2.3`.
   Read the preflight output and the artifact checksums.
4. Publish: `python scripts/release/release.py --version v1.2.3 --publish`.
   Type the tag to confirm the upload, then watch the smoke test install
   from the real PyPI into a clean venv.
5. Announce only after the smoke test passes. The announcement package
   stays under its own sequencing rules; see `docs/Announcement-Package.md`.

`--skip-smoke` exists for one situation: the smoke already passed for this
exact version and these exact artifacts (for example a re-run after a
network drop between upload and smoke). Skipping the smoke for any other
reason defeats the "published but broken" catch the release process exists
for. When the smoke is skipped, say so in the release notes.

## Rollback

There is no un-publish. If a published release is broken, yank it on PyPI
(`yanked` keeps installs reproducible while hiding it from new resolvers)
and cut a new patch version through this same process. The bad tag stays
where it is, annotated with what happened in the next CHANGELOG entry.

## Container images

Container publishing on release tags (GHCR) is a separate decision with
its own lane. When it lands, it keys off these same signed tags and this
same preflight; nothing here conflicts with it.

## What this lane deliberately does not do

- It does not change the build backend. The maturin migration owns
  `build-system` and the hand-rolled extension builder.
- It does not change dependency resolution. The `uv.lock` mechanics from
  the D-40 migration are untouched; this lane only re-resolved the lockfile
  for the `0.0.0` version marker.
- It does not publish anything. The first real publish is David's manual
  run, after the perfection gate.
- The post-publish smoke does not run the README quickstart's
  `peira run --suite trial` step, because the trial dataset ships with the
  repo, not the wheel. The smoke covers the install surface the wheel
  actually provides. If the dataset ever ships inside the wheel, extend
  `scripts/release/smoke.py` with a mock-adapter trial run.
