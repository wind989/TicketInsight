"""One-time explicit downloader and verifier for TicketInsight's local Chinese BGE model."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.retrieval import LOCAL_BGE_MODEL, local_model_cache_dir


def main() -> None:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise SystemExit("sentence-transformers is required before downloading the local BGE model") from error

    cache_dir = local_model_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    model = SentenceTransformer(LOCAL_BGE_MODEL, cache_folder=str(cache_dir), local_files_only=False)
    vector = model.encode(["客服工单分析验证"], normalize_embeddings=True, show_progress_bar=False)[0]
    dimension = int(model.get_sentence_embedding_dimension())
    if len(vector) != dimension or dimension != 512:
        raise SystemExit(f"unexpected BGE embedding dimension: {len(vector)} (declared {dimension})")

    report_path = Path("reports/local_bge_model.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "model": LOCAL_BGE_MODEL,
                "cache_dir": str(cache_dir),
                "embedding_dimension": dimension,
                "verification": "loaded_and_encoded_locally",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"model": LOCAL_BGE_MODEL, "cache_dir": str(cache_dir), "dimension": dimension}))


if __name__ == "__main__":
    main()
