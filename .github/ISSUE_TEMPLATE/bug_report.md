name: Bug report
description: Something in peira isn't working as documented
title: "[bug] "
labels: ["bug"]
body:
  - type: markdown
    attributes:
      value: |
        Thanks for reporting. Peira is maintained by one person, so the
        most useful reports are the ones that reproduce.
  - type: input
    id: version
    attributes:
      label: peira version
      description: Output of `peira --version`
      placeholder: "0.3.0"
    validations:
      required: true
  - type: dropdown
    id: backend
    attributes:
      label: Backend
      options:
        - pure Python (default install)
        - Rust accelerator (`peira._core` built)
        - not sure
    validations:
      required: true
  - type: textarea
    id: command
    attributes:
      label: Command that failed
      description: The exact command line, plus any dataset/adapter involved
      placeholder: |
        peira run --adapter mock --suite trial-demo --out runs
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: What you expected
      description: What the docs (or your reading of them) say should happen
    validations:
      required: true
  - type: textarea
    id: actual
    attributes:
      label: What happened instead
      description: Paste the full error output or describe the wrong behavior
      render: shell
    validations:
      required: true
  - type: textarea
    id: repro
    attributes:
      label: Minimal reproduction
      description: |
        The smallest steps that trigger it. If it needs a case file,
        paste the smallest case JSON that reproduces it (redact anything
        private — case content is data, not credentials).
