#!/usr/bin/env bash
# Demo: PRISM Embeddings — Non-Base-10 Multi-Scale Similarity
#
# Shows:
#   - P-adic ultrametric hierarchy (tree-like code similarity)
#   - RNS channel voting (fault detection via residue number system)
#   - vMF concentration (uncertainty weighting via von Mises-Fisher)
#   - PRISM vs cosine divergence cases
#
# Usage:
#   bash demos/07-prism.sh
#   bash demos/07-prism.sh --verbose

set -euo pipefail
claw prism-demo --verbose "${@}"
