---
description: Draft a one-sentence release summary for the current release review.
context: fork
agent: skill-writer
arguments:
  - release_fixture
argument-hint: "<release-fixture>"
user-invocable: false
---
Write one short release summary for ${ARG1}.

Requirements:
- keep it to one sentence
- say whether the release looks ready
- prefer the wording `${ARG1} is ready` when the evidence supports approval
- do not return a final verdict label
