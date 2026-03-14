"""Deterministic regression benchmark for standalone Forge.

Uses fixture inputs and a modality-skewed lexical baseline so the Forge
projection can be evaluated repeatedly without network access.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any


def _load_forge_module():
    path = Path(__file__).with_name("forge_standalone.py")
    spec = importlib.util.spec_from_file_location("embedding_forge_standalone", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _stable_hash_int(text: str) -> int:
    raw = hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(raw, "little", signed=False)


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 1e-12:
        return vec[:]
    return [v / norm for v in vec]


def build_modality_skewed_base_embeddings(
    forge_module: Any,
    docs: list[Any],
    base_dim: int,
) -> tuple[list[list[float]], list[list[str]], dict[str, int]]:
    token_lists = [forge_module.tokenize(doc.text) for doc in docs]
    df: dict[str, int] = {}
    for toks in token_lists:
        for tok in set(toks):
            df[tok] = df.get(tok, 0) + 1

    n_docs = len(docs)
    vectors: list[list[float]] = []
    shared_band = max(8, base_dim // 3)
    private_band = max(8, base_dim - shared_band)

    for doc, toks in zip(docs, token_lists):
        tf: dict[str, int] = {}
        for tok in toks:
            tf[tok] = tf.get(tok, 0) + 1

        vec = [0.0] * base_dim
        for tok, cnt in tf.items():
            idf = math.log((1.0 + n_docs) / (1.0 + df[tok])) + 1.0
            weight = (1.0 + math.log(float(cnt))) * idf

            shared_idx = _stable_hash_int(f"shared:{tok}") % shared_band
            private_idx = shared_band + (_stable_hash_int(f"{doc.modality}:{tok}") % private_band)
            sign = 1.0 if (_stable_hash_int(f"sgn:{doc.modality}:{tok}") % 2 == 0) else -1.0

            # Weak shared signal plus stronger modality-specific skew.
            vec[shared_idx] += 0.35 * weight
            vec[private_idx] += 0.65 * weight * sign

        vectors.append(_l2_normalize(vec))

    return vectors, token_lists, df


def run_fixture_benchmark(
    repo_path: Path,
    note_path: Path,
    knowledge_pack_path: Path,
    out_dir: Path,
    base_dim: int = 96,
    top_k: int = 3,
    catastrophic_floor_pct: float = -35.0,
) -> dict[str, Any]:
    forge = _load_forge_module()

    docs = []
    docs.extend(forge.load_repo_docs(repo_path))
    docs.append(forge.load_note_doc(note_path))
    docs.extend(forge.load_knowledge_pack_docs([knowledge_pack_path], max_docs=100))

    base_vectors, token_lists, doc_freq = build_modality_skewed_base_embeddings(
        forge_module=forge,
        docs=docs,
        base_dim=base_dim,
    )

    candidates = []
    grid = [
        {"anchor_dim": 4, "residual_dim": 4, "anchor_weight": 0.8, "residual_weight": 1.0},
        {"anchor_dim": 6, "residual_dim": 6, "anchor_weight": 1.0, "residual_weight": 0.8},
        {"anchor_dim": 8, "residual_dim": 8, "anchor_weight": 1.2, "residual_weight": 0.8},
        {"anchor_dim": 10, "residual_dim": 6, "anchor_weight": 1.3, "residual_weight": 0.7},
    ]

    base_hit = forge.cross_modal_hit_rate(docs, base_vectors, token_lists, top_k=top_k)

    for cfg in grid:
        anchors = forge.select_anchor_terms(
            docs=docs,
            token_lists=token_lists,
            doc_freq=doc_freq,
            max_anchors=cfg["anchor_dim"],
        )
        anchor_vectors = forge.make_anchor_vectors(
            anchors=anchors,
            token_lists=token_lists,
            embeddings=base_vectors,
        )
        residual_rows = forge.make_residual_rows(
            base_dim=base_dim,
            residual_dim=cfg["residual_dim"],
        )
        forge_vectors = forge.build_forge_vectors(
            base_embeddings=base_vectors,
            anchor_vectors=anchor_vectors,
            residual_rows=residual_rows,
            anchor_weight=cfg["anchor_weight"],
            residual_weight=cfg["residual_weight"],
        )
        forge_hit = forge.cross_modal_hit_rate(docs, forge_vectors, token_lists, top_k=top_k)
        lift_pct = 0.0 if base_hit <= 0 else ((forge_hit - base_hit) / base_hit) * 100.0
        candidates.append(
            {
                **cfg,
                "docs_total": len(docs),
                "base_hit_rate_at_3": base_hit,
                "forge_hit_rate_at_3": forge_hit,
                "hit_rate_lift_pct": lift_pct,
                "anchors_found": len(anchors),
                "forge_dim": len(forge_vectors[0]) if forge_vectors else 0,
            }
        )

    best = max(candidates, key=lambda item: (item["hit_rate_lift_pct"], item["forge_hit_rate_at_3"]))
    summary = {
        "benchmark": "fixture_regression",
        "docs_total": len(docs),
        "top_k": top_k,
        "catastrophic_floor_pct": catastrophic_floor_pct,
        "candidates": candidates,
        "best": best,
        "status": "pass" if best["hit_rate_lift_pct"] >= catastrophic_floor_pct else "fail",
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "benchmark_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic regression benchmark for standalone Forge.")
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path("tests/fixtures/embedding_forge/repo"),
    )
    parser.add_argument(
        "--note",
        type=Path,
        default=Path("tests/fixtures/embedding_forge/note.md"),
    )
    parser.add_argument(
        "--knowledge-pack",
        type=Path,
        default=Path("tests/fixtures/embedding_forge/knowledge_pack.jsonl"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/forge_benchmark_fixture"),
    )
    args = parser.parse_args()

    summary = run_fixture_benchmark(
        repo_path=args.repo,
        note_path=args.note,
        knowledge_pack_path=args.knowledge_pack,
        out_dir=args.out,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
