#!/usr/bin/env python3
"""Validate .coderabbit.yaml guards the advisory-only posture.

CodeRabbit is advisory step 0 on this repo. It must never block merges.
This check fails the build if:
  - the YAML does not parse,
  - reviews.request_changes_workflow is not false,
  - any pre-merge check uses mode "error" (warnings advise, errors would
    imply a blocking posture creeping in through config).

Run: python3 scripts/check_coderabbit_config.py
"""

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML not available; install pyyaml to run this check.")
    sys.exit(1)

REPO = Path(__file__).resolve().parent.parent
CFG = REPO / ".coderabbit.yaml"

errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


class _NoDupLoader(yaml.SafeLoader):
    """YAML loader that rejects duplicate mapping keys.

    yaml.safe_load keeps the last value when a key repeats, so a second
    `reviews:` block could silently discard the first block's settings while
    this check reports success. Fail loudly instead.
    """


def _no_dup_constructor(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in mapping:
            raise yaml.YAMLError(f"duplicate mapping key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_NoDupLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dup_constructor
)


def main() -> int:
    try:
        cfg = yaml.load(CFG.read_text(encoding="utf-8"), Loader=_NoDupLoader)
    except yaml.YAMLError as exc:
        fail(f".coderabbit.yaml does not parse: {exc}")
        cfg = None
    except Exception as exc:  # noqa: BLE001 - report any read failure
        fail(f".coderabbit.yaml could not be read: {exc}")
        cfg = None

    if not isinstance(cfg, dict):
        fail(".coderabbit.yaml top level must be a mapping.")
    else:
        reviews = cfg.get("reviews", {})
        if not isinstance(reviews, dict):
            fail("reviews must be a mapping.")
        else:
            if reviews.get("request_changes_workflow") is not False:
                fail(
                    "reviews.request_changes_workflow must be false "
                    "(CodeRabbit is advisory step 0; it never blocks merges)."
                )
            pmc = reviews.get("pre_merge_checks", {})
            if pmc is None:
                pmc = {}
            if not isinstance(pmc, dict):
                fail("reviews.pre_merge_checks must be a mapping.")
                pmc = {}
            for name, check in pmc.items():
                if isinstance(check, dict) and check.get("mode") == "error":
                    fail(
                        f"pre_merge_checks.{name} uses mode 'error'; "
                        "advisory posture allows warning at most."
                    )
            # custom_checks entries, if any are ever added, get the same rule.
            # In the CodeRabbit schema custom_checks sits at reviews level,
            # not under pre_merge_checks; check both locations.
            for scope in (reviews, pmc):
                custom = scope.get("custom_checks", [])
                if isinstance(custom, list):
                    for check in custom:
                        if isinstance(check, dict) and check.get("mode") == "error":
                            fail(
                                f"custom check {check.get('name', '?')} uses mode 'error'; "
                                "advisory posture allows warning at most."
                            )

    if errors:
        for e in errors:
            print(f"FAIL: {e}")
        return 1
    print("coderabbit config OK: parses, advisory-only, no error-mode checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
