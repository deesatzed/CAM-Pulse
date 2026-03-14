"""Standalone Multimodal Embedding Forge.

Builds a novel "Forge-32" embedding variant by ingesting:
1) A target repository (code + markdown)
2) External concept notes (e.g., googembed.md)
3) Optional CAM knowledge packs (JSONL export) or optional direct CAM DB read

Outputs:
- forge_metrics.json
- forge_device_spec.json
- forge_index.json
- forge_report.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANDATED_EMBEDDING_MODEL = "gemini-embedding-2-preview"


STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "if", "in", "into", "is", "it", "its", "of", "on", "or", "that", "the", "their",
    "this", "to", "was", "were", "will", "with", "you", "your", "they", "them", "we",
    "our", "can", "not", "do", "does", "did", "so", "than", "then", "also", "all",
    "no", "yes", "via", "using", "use", "used", "more", "most", "other", "any",
}

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]{1,}")


@dataclass
class Document:
    id: str
    title: str
    modality: str
    text: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


class StandaloneEmbeddingEngine:
    """Minimal Gemini embedding engine for standalone Forge."""

    def __init__(
        self,
        model: str,
        dimension: int,
        api_key_env: str,
        task_type: str,
        required_model: str,
    ) -> None:
        if required_model and model != required_model:
            raise RuntimeError(
                f"Embeddings model '{model}' rejected; required model is '{required_model}'"
            )
        self.model_name = model
        self.dimension = dimension
        self.api_key_env = api_key_env
        self.task_type = task_type
        api_key = os.getenv(api_key_env, "")
        if not api_key:
            raise RuntimeError(f"{api_key_env} is required for model '{model}'")
        from google import genai

        self._client = genai.Client(api_key=api_key)

    @staticmethod
    def _extract_values(resp: object) -> list[list[float]]:
        if hasattr(resp, "embeddings") and getattr(resp, "embeddings"):
            values: list[list[float]] = []
            for emb in getattr(resp, "embeddings"):
                emb_values = getattr(emb, "values", None)
                if emb_values is not None:
                    values.append([float(v) for v in emb_values])
            if values:
                return values

        if hasattr(resp, "embedding") and getattr(resp, "embedding") is not None:
            emb = getattr(resp, "embedding")
            emb_values = getattr(emb, "values", None)
            if emb_values is not None:
                return [[float(v) for v in emb_values]]

        return []

    def _normalize_dim(self, vec: list[float]) -> list[float]:
        if len(vec) == self.dimension:
            return vec
        if len(vec) > self.dimension:
            return vec[: self.dimension]
        return vec + [0.0] * (self.dimension - len(vec))

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        from google.genai import types

        cfg = types.EmbedContentConfig(
            output_dimensionality=self.dimension,
            task_type=self.task_type,
        )
        resp = self._client.models.embed_content(
            model=self.model_name,
            contents=[t[:12000] for t in texts],
            config=cfg,
        )
        vectors = self._extract_values(resp)
        if not vectors:
            raise RuntimeError("Gemini embeddings response contained no vectors")
        return [self._normalize_dim(v) for v in vectors]

    def encode(self, text: str) -> list[float]:
        return self.encode_batch([text])[0]


def stable_hash_int(text: str) -> int:
    raw = hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(raw, "little", signed=False)


def tokenize(text: str) -> list[str]:
    toks = [m.group(0).lower() for m in TOKEN_RE.finditer(text)]
    return [t for t in toks if t not in STOP_WORDS and len(t) > 2]


def l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 1e-12:
        return vec[:]
    return [v / norm for v in vec]


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def cosine(a: list[float], b: list[float]) -> float:
    return dot(l2_normalize(a), l2_normalize(b))


def parse_json_list(raw: str) -> list[str]:
    try:
        value = json.loads(raw) if raw else []
        if isinstance(value, list):
            return [str(v) for v in value]
    except Exception:
        pass
    return []


def load_repo_docs(repo_path: Path) -> list[Document]:
    docs: list[Document] = []
    preferred = [
        repo_path / "README.md",
        repo_path / "program.md",
        repo_path / "train.py",
        repo_path / "prepare.py",
    ]
    for path in preferred:
        if path.exists() and path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            docs.append(
                Document(
                    id=f"repo:{path.name}",
                    title=path.name,
                    modality="code" if path.suffix == ".py" else "markdown",
                    text=text[:50000],
                    source=str(path),
                )
            )

    if not docs:
        for path in sorted(repo_path.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".md"}:
                continue
            rel = path.relative_to(repo_path)
            text = path.read_text(encoding="utf-8", errors="replace")
            docs.append(
                Document(
                    id=f"repo:{rel}",
                    title=str(rel),
                    modality="code" if path.suffix == ".py" else "markdown",
                    text=text[:30000],
                    source=str(path),
                )
            )
            if len(docs) >= 12:
                break
    return docs


def load_note_doc(note_path: Path) -> Document:
    text = note_path.read_text(encoding="utf-8", errors="replace")
    return Document(
        id=f"note:{note_path.name}",
        title=note_path.name,
        modality="research_note",
        text=text[:80000],
        source=str(note_path),
    )


def load_knowledge_pack_docs(pack_paths: list[Path], max_docs: int) -> list[Document]:
    docs: list[Document] = []
    for pack_path in pack_paths:
        if not pack_path.exists():
            continue
        with pack_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except Exception:
                    continue
                text = str(row.get("text", ""))
                if len(text.strip()) < 10:
                    continue
                docs.append(
                    Document(
                        id=str(row.get("id", f"pack:{len(docs)}")),
                        title=str(row.get("title", "knowledge item"))[:120],
                        modality=str(row.get("modality", "memory_item")),
                        text=text[:6000],
                        source=str(row.get("source", str(pack_path))),
                        metadata=dict(row.get("metadata", {}) or {}),
                    )
                )
                if len(docs) >= max_docs:
                    return docs
    return docs


def load_cam_db_docs(db_path: Path, max_methodologies: int, max_tasks: int) -> list[Document]:
    docs: list[Document] = []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    meth_rows = cur.execute(
        """
        SELECT id, problem_description, methodology_notes, tags, solution_code,
               success_count, retrieval_count
        FROM methodologies
        ORDER BY success_count DESC, retrieval_count DESC, created_at DESC
        LIMIT ?
        """,
        (max_methodologies,),
    ).fetchall()
    for row in meth_rows:
        tags = parse_json_list(row["tags"])
        text = "\n".join(
            [
                row["problem_description"] or "",
                row["methodology_notes"] or "",
                row["solution_code"] or "",
                "tags: " + ", ".join(tags),
            ]
        )
        docs.append(
            Document(
                id=f"meth:{row['id']}",
                title=(row["problem_description"] or "methodology")[:120],
                modality="memory_methodology",
                text=text[:6000],
                source=f"{db_path}:methodologies",
                metadata={
                    "success_count": int(row["success_count"] or 0),
                    "retrieval_count": int(row["retrieval_count"] or 0),
                    "tags": tags[:12],
                },
            )
        )

    task_rows = cur.execute(
        """
        SELECT id, title, description, status, task_type, recommended_agent,
               execution_steps, acceptance_checks, priority
        FROM tasks
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (max_tasks,),
    ).fetchall()
    for row in task_rows:
        steps = parse_json_list(row["execution_steps"])
        checks = parse_json_list(row["acceptance_checks"])
        text = "\n".join(
            [
                row["title"] or "",
                row["description"] or "",
                f"status={row['status']} type={row['task_type']} agent={row['recommended_agent']}",
                "steps: " + "; ".join(steps[:8]),
                "checks: " + "; ".join(checks[:8]),
            ]
        )
        docs.append(
            Document(
                id=f"task:{row['id']}",
                title=(row["title"] or "task")[:120],
                modality="memory_task",
                text=text[:4000],
                source=f"{db_path}:tasks",
                metadata={
                    "status": row["status"],
                    "task_type": row["task_type"],
                    "priority": int(row["priority"] or 0),
                },
            )
        )

    conn.close()
    return docs


def build_base_embeddings(
    docs: list[Document], base_dim: int, max_vocab: int
) -> tuple[list[list[float]], list[list[str]], dict[str, int]]:
    token_lists = [tokenize(doc.text) for doc in docs]
    df: Counter[str] = Counter()
    for toks in token_lists:
        df.update(set(toks))

    n_docs = len(docs)
    tf_global: Counter[str] = Counter()
    for toks in token_lists:
        tf_global.update(toks)

    vocab = [
        tok
        for tok, _ in tf_global.most_common(max_vocab)
        if df[tok] >= 2 and tok not in STOP_WORDS
    ]
    vocab_set = set(vocab)
    doc_freq = {tok: df[tok] for tok in vocab}

    embeddings: list[list[float]] = []
    for toks in token_lists:
        tf = Counter(t for t in toks if t in vocab_set)
        vec = [0.0] * base_dim
        for tok, cnt in tf.items():
            idf = math.log((1.0 + n_docs) / (1.0 + doc_freq[tok])) + 1.0
            weight = (1.0 + math.log(float(cnt))) * idf
            idx = stable_hash_int(tok) % base_dim
            sgn = 1.0 if (stable_hash_int(tok + "|sgn") % 2 == 0) else -1.0
            vec[idx] += sgn * weight
        embeddings.append(l2_normalize(vec))

    return embeddings, token_lists, doc_freq


def build_external_base_embeddings(
    docs: list[Document],
    engine: StandaloneEmbeddingEngine,
) -> tuple[list[list[float]], list[list[str]], dict[str, int]]:
    token_lists = [tokenize(doc.text) for doc in docs]
    df: Counter[str] = Counter()
    for toks in token_lists:
        df.update(set(toks))

    texts = [doc.text[:4000] for doc in docs]
    try:
        embeddings = engine.encode_batch(texts)
    except Exception:
        # Fall back to single-call path for partial robustness.
        embeddings = [engine.encode(t[:3000]) for t in texts]

    doc_freq = dict(df)
    return embeddings, token_lists, doc_freq


def select_anchor_terms(
    docs: list[Document],
    token_lists: list[list[str]],
    doc_freq: dict[str, int],
    max_anchors: int,
) -> list[str]:
    tf_global: Counter[str] = Counter()
    modality_presence: dict[str, set[str]] = defaultdict(set)
    for doc, toks in zip(docs, token_lists):
        tf_global.update(toks)
        for tok in set(toks):
            modality_presence[tok].add(doc.modality)

    scored: list[tuple[float, str]] = []
    n_docs = len(docs)
    for tok, tf in tf_global.items():
        if tok not in doc_freq:
            continue
        modalities = modality_presence[tok]
        if len(modalities) < 2:
            continue
        idf = math.log((1.0 + n_docs) / (1.0 + doc_freq[tok])) + 1.0
        modal_entropy = math.log(1.0 + len(modalities))
        score = float(tf) * idf * modal_entropy
        scored.append((score, tok))
    scored.sort(reverse=True)
    return [tok for _, tok in scored[:max_anchors]]


def make_anchor_vectors(
    anchors: list[str],
    token_lists: list[list[str]],
    embeddings: list[list[float]],
) -> list[list[float]]:
    vectors: list[list[float]] = []
    for tok in anchors:
        selected = [vec for toks, vec in zip(token_lists, embeddings) if tok in toks]
        if not selected:
            continue
        dim = len(selected[0])
        avg = [0.0] * dim
        for vec in selected:
            for i, value in enumerate(vec):
                avg[i] += value
        inv = 1.0 / float(len(selected))
        vectors.append(l2_normalize([v * inv for v in avg]))
    return vectors


def make_residual_rows(base_dim: int, residual_dim: int) -> list[list[float]]:
    rows: list[list[float]] = []
    for i in range(residual_dim):
        row = [0.0] * base_dim
        for j in range(base_dim):
            h = stable_hash_int(f"forge_row_{i}_col_{j}")
            row[j] = (float((h % 2000) - 1000)) / 1000.0
        rows.append(l2_normalize(row))
    return rows


def build_forge_vectors(
    base_embeddings: list[list[float]],
    anchor_vectors: list[list[float]],
    residual_rows: list[list[float]],
    anchor_weight: float = 1.0,
    residual_weight: float = 1.0,
) -> list[list[float]]:
    forged: list[list[float]] = []
    for vec in base_embeddings:
        anchor_channel = [cosine(vec, a) for a in anchor_vectors]
        residual_channel = [dot(vec, r) for r in residual_rows]
        # Device output variant: anchor + residual, both normalized independently.
        anchor_norm = l2_normalize(anchor_channel) if anchor_channel else []
        residual_norm = l2_normalize(residual_channel)
        if anchor_norm:
            anchor_norm = [anchor_weight * x for x in anchor_norm]
        residual_norm = [residual_weight * x for x in residual_norm]
        forged.append(l2_normalize(anchor_norm + residual_norm))
    return forged


def overlap_score(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


def cross_modal_hit_rate(
    docs: list[Document], vectors: list[list[float]], token_lists: list[list[str]], top_k: int
) -> float:
    token_sets = [set(toks) for toks in token_lists]
    total = 0
    hits = 0
    for i, doc in enumerate(docs):
        positives = [
            j
            for j, other in enumerate(docs)
            if j != i
            and other.modality != doc.modality
            and overlap_score(token_sets[i], token_sets[j]) >= 0.08
        ]
        if not positives:
            continue
        total += 1
        sims = []
        for j, other_vec in enumerate(vectors):
            if j == i:
                continue
            sims.append((cosine(vectors[i], other_vec), j))
        sims.sort(reverse=True)
        top = [idx for _, idx in sims[:top_k]]
        if any(idx in positives for idx in top):
            hits += 1
    return (hits / total) if total > 0 else 0.0


def top_neighbors(vectors: list[list[float]], idx: int, n: int) -> list[tuple[int, float]]:
    sims: list[tuple[int, float]] = []
    for j, vec in enumerate(vectors):
        if j == idx:
            continue
        sims.append((j, cosine(vectors[idx], vec)))
    sims.sort(key=lambda x: x[1], reverse=True)
    return sims[:n]


def modality_counts(docs: list[Document]) -> dict[str, int]:
    c = Counter(doc.modality for doc in docs)
    return dict(sorted(c.items(), key=lambda kv: kv[0]))


def write_artifacts(
    out_dir: Path,
    docs: list[Document],
    anchors: list[str],
    base_vectors: list[list[float]],
    forge_vectors: list[list[float]],
    token_lists: list[list[str]],
    metrics: dict[str, Any],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    index = []
    for doc, toks, fvec in zip(docs, token_lists, forge_vectors):
        top_terms = [tok for tok, _ in Counter(toks).most_common(10)]
        index.append(
            {
                "id": doc.id,
                "title": doc.title,
                "modality": doc.modality,
                "source": doc.source,
                "top_terms": top_terms,
                "forge32": [round(x, 6) for x in fvec],
            }
        )

    (out_dir / "forge_index.json").write_text(
        json.dumps(index, indent=2),
        encoding="utf-8",
    )

    spec = {
        "name": "Forge-32",
        "description": "Anchor-plus-residual multimodal device-output embedding variant",
        "base_dim": len(base_vectors[0]) if base_vectors else 0,
        "output_dim": len(forge_vectors[0]) if forge_vectors else 0,
        "anchor_count": len(anchors),
        "anchor_terms": anchors,
        "channels": [
            {
                "name": "anchor_channel",
                "dim": len(anchors),
                "semantics": "Cross-modal concept anchors learned from repo+notes+memory",
            },
            {
                "name": "residual_channel",
                "dim": (len(forge_vectors[0]) - len(anchors)) if forge_vectors else 0,
                "semantics": "Deterministic compressed residual signal",
            },
        ],
        "metrics": metrics,
    }
    (out_dir / "forge_device_spec.json").write_text(
        json.dumps(spec, indent=2),
        encoding="utf-8",
    )
    (out_dir / "forge_metrics.json").write_text(
        json.dumps(metrics, indent=2),
        encoding="utf-8",
    )

    # Report with sample nearest-neighbor behavior.
    report_lines = [
        "# Multimodal Embedding Forge Report",
        "",
        "## Summary",
        f"- Total docs ingested: {metrics['docs_total']}",
        f"- Modalities: {json.dumps(metrics['modality_counts'])}",
        f"- Base retrieval hit@3: {metrics['base_hit_rate_at_3']:.4f}",
        f"- Forge retrieval hit@3: {metrics['forge_hit_rate_at_3']:.4f}",
        f"- Lift: {metrics['hit_rate_lift_pct']:.2f}%",
        "",
        "## Forge-32 Device",
        "- Composition: anchor channel + residual channel",
        f"- Anchor terms ({len(anchors)}): " + ", ".join(anchors),
        "",
        "## Sample Neighbors (Forge-32)",
    ]

    interesting = []
    for i, doc in enumerate(docs):
        if doc.modality in {"code", "research_note", "memory_methodology"}:
            interesting.append(i)
    interesting = interesting[:3]
    for i in interesting:
        report_lines.append("")
        report_lines.append(f"### {docs[i].id} ({docs[i].modality})")
        report_lines.append(f"- Title: {docs[i].title}")
        for idx, sim in top_neighbors(forge_vectors, i, 3):
            report_lines.append(
                f"- Neighbor: {docs[idx].id} [{docs[idx].modality}] sim={sim:.4f}"
            )

    (out_dir / "forge_report.md").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )


def build_showpiece(
    repo_path: Path,
    note_path: Path,
    cam_db_path: Path | None,
    knowledge_pack_paths: list[Path],
    out_dir: Path,
    max_methodologies: int,
    max_tasks: int,
    base_dim: int,
    anchor_dim: int,
    residual_dim: int,
    anchor_weight: float,
    residual_weight: float,
    embedding_model: str,
    required_embedding_model: str,
    embedding_api_key_env: str,
    embedding_task_type: str,
) -> dict[str, Any]:
    docs = []
    docs.extend(load_repo_docs(repo_path))
    docs.append(load_note_doc(note_path))
    docs.extend(load_knowledge_pack_docs(knowledge_pack_paths, max_docs=max_methodologies + max_tasks))
    if cam_db_path is not None and cam_db_path.exists():
        docs.extend(
            load_cam_db_docs(
                cam_db_path,
                max_methodologies=max_methodologies,
                max_tasks=max_tasks,
            )
        )

    emb_engine = StandaloneEmbeddingEngine(
        model=embedding_model,
        required_model=required_embedding_model,
        dimension=base_dim,
        api_key_env=embedding_api_key_env,
        task_type=embedding_task_type,
    )
    base_vectors, token_lists, doc_freq = build_external_base_embeddings(
        docs=docs,
        engine=emb_engine,
    )
    anchors = select_anchor_terms(
        docs=docs,
        token_lists=token_lists,
        doc_freq=doc_freq,
        max_anchors=anchor_dim,
    )
    anchor_vectors = make_anchor_vectors(
        anchors=anchors,
        token_lists=token_lists,
        embeddings=base_vectors,
    )
    residual_rows = make_residual_rows(base_dim=base_dim, residual_dim=residual_dim)
    forge_vectors = build_forge_vectors(
        base_embeddings=base_vectors,
        anchor_vectors=anchor_vectors,
        residual_rows=residual_rows,
        anchor_weight=anchor_weight,
        residual_weight=residual_weight,
    )

    base_hit = cross_modal_hit_rate(
        docs=docs, vectors=base_vectors, token_lists=token_lists, top_k=3
    )
    forge_hit = cross_modal_hit_rate(
        docs=docs, vectors=forge_vectors, token_lists=token_lists, top_k=3
    )
    lift_pct = 0.0
    if base_hit > 0:
        lift_pct = ((forge_hit - base_hit) / base_hit) * 100.0

    metrics = {
        "docs_total": len(docs),
        "modality_counts": modality_counts(docs),
        "anchors_found": len(anchors),
        "base_hit_rate_at_3": base_hit,
        "forge_hit_rate_at_3": forge_hit,
        "hit_rate_lift_pct": lift_pct,
        "base_dim": base_dim,
        "forge_dim": len(forge_vectors[0]) if forge_vectors else 0,
        "anchor_weight": anchor_weight,
        "residual_weight": residual_weight,
        "embedding_model": embedding_model,
    }
    write_artifacts(
        out_dir=out_dir,
        docs=docs,
        anchors=anchors,
        base_vectors=base_vectors,
        forge_vectors=forge_vectors,
        token_lists=token_lists,
        metrics=metrics,
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the standalone Multimodal Embedding Forge.")
    parser.add_argument("--repo", type=Path, default=Path("autoresearch-macos"))
    parser.add_argument("--note", type=Path, default=Path("googembed.md"))
    parser.add_argument(
        "--knowledge-pack",
        type=Path,
        action="append",
        default=[],
        help="Optional JSONL knowledge pack(s), typically exported from CAM.",
    )
    parser.add_argument(
        "--cam-db",
        type=Path,
        default=None,
        help="Optional direct CAM DB path for transitional compatibility.",
    )
    parser.add_argument("--out", type=Path, default=Path("data/forge_showpiece"))
    parser.add_argument("--max-methodologies", type=int, default=120)
    parser.add_argument("--max-tasks", type=int, default=120)
    parser.add_argument("--base-dim", type=int, default=192)
    parser.add_argument("--anchor-dim", type=int, default=16)
    parser.add_argument("--residual-dim", type=int, default=16)
    parser.add_argument("--anchor-weight", type=float, default=1.0)
    parser.add_argument("--residual-weight", type=float, default=1.0)
    parser.add_argument("--embedding-model", type=str, default=MANDATED_EMBEDDING_MODEL)
    parser.add_argument("--required-embedding-model", type=str, default=MANDATED_EMBEDDING_MODEL)
    parser.add_argument("--embedding-api-key-env", type=str, default="GOOGLE_API_KEY")
    parser.add_argument("--embedding-task-type", type=str, default="RETRIEVAL_DOCUMENT")
    args = parser.parse_args()

    metrics = build_showpiece(
        repo_path=args.repo,
        note_path=args.note,
        cam_db_path=args.cam_db,
        knowledge_pack_paths=args.knowledge_pack,
        out_dir=args.out,
        max_methodologies=args.max_methodologies,
        max_tasks=args.max_tasks,
        base_dim=args.base_dim,
        anchor_dim=args.anchor_dim,
        residual_dim=args.residual_dim,
        anchor_weight=args.anchor_weight,
        residual_weight=args.residual_weight,
        embedding_model=args.embedding_model,
        required_embedding_model=args.required_embedding_model,
        embedding_api_key_env=args.embedding_api_key_env,
        embedding_task_type=args.embedding_task_type,
    )
    print("Forge complete")
    print(json.dumps(metrics, indent=2))
    print(f"Artifacts written to: {args.out}")


if __name__ == "__main__":
    main()
