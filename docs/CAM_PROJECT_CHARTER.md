# CAM Project Charter

This document defines the product expectations CAM must continue to satisfy.

It exists to prevent drift as CAM assimilates more repos, methodologies, and workflow layers.

## Purpose

CAM is meant to be:

1. a system that learns reusable software-building knowledge from repos and prior work
2. a system that reassesses old knowledge when new tasks arrive
3. a system that turns that learning into real repo work
4. a system that validates results instead of trusting model narration

## Core Expectations

### 1. Learning must produce structured reusable knowledge

CAM must not treat repo ingestion as simple note-taking.

Expected outcome:
- methodologies saved to memory
- capability enrichment
- action templates where concrete runbooks are derivable
- visible delta after mining

## 2. Reassessment must reactivate old knowledge

CAM must not leave prior methodologies as dead archive items.

Expected outcome:
- prior knowledge can be re-ranked against a new task
- reassessment can explain why a methodology matters now
- future-candidate capabilities remain visible until proven or demoted

## 3. Execution claims must be honest

CAM must not claim build/improvement capability when the runtime has no real path to modify files.

Expected outcome:
- execution workflows fail fast when no executable build path exists
- successful execution is only counted when the repo materially changes
- validation remains the source of truth over agent narration

## 4. Standalone output means runtime independence

A generated app may be built by CAM, but it must not depend on CAM runtime code unless explicitly requested.

Expected outcome:
- generated apps do not import `claw.*` for normal runtime behavior
- create specs can require standalone output
- validation can flag runtime dependence on CAM

## 5. Proof standards must outrank aspiration

CAM should distinguish between:
- implemented
- tested
- proven by direct execution
- still experimental

Expected outcome:
- public docs state honest capability boundaries
- workflows that are planning/spec-only are labeled as such
- benchmarks are reported honestly even when they do not improve results

## Non-Goals

CAM is not meant to be:
- just a repo summarizer
- just a RAG shell
- just a wrapper around hosted models
- a system that claims autonomous builder capability without a real write path

## Enforced Checks

These are current code-level guardrails backing this charter:

- `cam doctor expectations`
  - reports whether current runtime satisfies core product expectations
- `cam doctor audit`
  - reports whether high-trust methodologies are backed by attributed expectation-matched evidence
- `cam create --execute`
  - refuses execution when no executable build path exists
- `cam quickstart --execute`
  - refuses execution when no executable build path exists
- `cam enhance`
  - refuses non-dry-run execution when no executable build path exists
- workspace diff verification
  - rejects agent claims if no real repo files changed
- `cam validate`
  - treats unchanged repos and failed checks as hard failures

## Required Operating Rule

Before treating a workflow as real builder behavior, CAM must satisfy both:

1. an executable build path exists
2. validation proves the repo actually changed and checks passed

If either is false, the workflow must be treated as planning/spec-only.

## Evidence Rule

CAM must not treat a methodology as high-trust merely because it has raw success counters.

High-trust promotion and operator trust should prefer:

1. attributed usage evidence
2. expectation-match evidence
3. validated outcomes

`cam doctor audit` is the operator-facing check for this rule.
