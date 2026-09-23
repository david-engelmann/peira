name: Feature request
description: An idea for peira — a metric, a gate, a case family, tooling
title: "[feat] "
labels: ["enhancement"]
body:
  - type: dropdown
    id: area
    attributes:
      label: Area
      options:
        - Dataset / case authoring
        - Metrics / methodology
        - Runner / adapters
        - Report / leaderboard
        - Docs
        - Other
    validations:
      required: true
  - type: textarea
    id: problem
    attributes:
      label: What problem does this solve?
      description: |
        One paragraph, concrete. "It would be nice if" is fine, but say
        who benefits and when.
    validations:
      required: true
  - type: textarea
    id: proposal
    attributes:
      label: What are you proposing?
      description: |
        The change, as specifically as you can. If it touches a frozen
        interface (case schema, adapter contract, artifact format),
        say so — those need a decision record, not just code.
  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives you've considered
      description: What else could solve it, and why this is better.
