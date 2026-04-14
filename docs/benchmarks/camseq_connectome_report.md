# CAM-SEQ Connectome Benchmark Report

## Pilot Suite
- tasks: 6
- archetype accuracy: 1.00
- slot precision: 0.73
- slot recall: 0.96
- critical-slot recall: 1.00

## Full Suite
- tasks: 24
- archetype accuracy: 0.96
- slot precision: 0.80
- slot recall: 0.98
- critical-slot recall: 1.00

## Planning Ablation
- archetype uplift: 0.96
- slot precision uplift: 0.05
- slot recall uplift: 0.24
- critical-slot recall uplift: 0.17

## Connectome + Recipe Ablation
- baseline selected: comp_transfer
- learned selected: comp_direct
- recipe selected: comp_direct
- recipe active: True
- recipe sample size: 3
- recipe confidence basis: language_match, text_overlap, framework_match, symbol_receipt, test_evidence, recipe_family_preference

## Live Reviewed-Run Harness
- run count: 4
- completed runs: 4
- connectomes: 4
- active recipes: 1
- fourth packet confidence basis: abstract_job_match, text_overlap, symbol_receipt, test_evidence, recipe_family_preference
- workspace mutations: 24
- final landing count: 6

## Seeded Retrograde Cases
- case count: 4
- average confidence: 0.91
- top cause kinds: counterfactual, proof_gate, slot_execution
- top cause distribution: counterfactual:1, proof_gate:2, slot_execution:1
- root summary distribution: counterfactual:1, proof_gate:2, slot_execution:1
- recommended action distribution: promote or switch to the direct-fit runner-up path:1, reduce retry pressure by narrowing the slot adaptation scope:1, tighten proof gates or remove the risky implementation path:2
- dominant cluster distribution: proof:2, runtime:1, transfer:1
- confidence band distribution: high:3, medium:1
- calibration distribution: mixed:1, stable:3
- stability distribution: competitive:2, fragile:2

## Local Security Lane
- Semgrep default path: Docker runner
- CodeQL default path: deferred/advanced
