import argparse
import asyncio
import csv
import json
import math
from pathlib import Path
from statistics import mean

from app.db.session import SessionLocal
from app.rag.service import retrieve


VARIANTS = {
    "dense": {"use_rerank": False, "use_keyword": False},
    "dense_rerank": {"use_rerank": True, "use_keyword": False},
    "hybrid_rerank": {"use_rerank": True, "use_keyword": True},
}


def load_cases(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


async def evaluate_variant(cases: list[dict], variant: str, limit: int) -> tuple[list[dict], dict]:
    options = VARIANTS[variant]
    db = SessionLocal()
    try:
        rows = []
        for case in cases:
            hits = await retrieve(db, case["question"], None, limit=limit, **options)
            labels = [_is_relevant(hit, case) for hit in hits]
            row = {
                "variant": variant,
                "case_id": case["id"],
                "question": case["question"],
                "hit_at_1": int(any(labels[:1])),
                "hit_at_3": int(any(labels[:3])),
                "hit_at_5": int(any(labels[:5])),
                "mrr": _reciprocal_rank(labels),
                "ndcg_at_5": _ndcg(labels[:5]),
                "top_title": hits[0]["title"] if hits else "",
                "top_filename": hits[0]["filename"] if hits else "",
                "top_score": hits[0].get("rerank_score", hits[0].get("score", 0)) if hits else 0,
                "top_keyword_matches": ",".join(hits[0].get("keyword_matches", [])) if hits else "",
            }
            rows.append(row)
    finally:
        db.close()
    summary = {
        "variant": variant,
        "cases": len(rows),
        "hit_at_1": mean(row["hit_at_1"] for row in rows) if rows else 0,
        "hit_at_3": mean(row["hit_at_3"] for row in rows) if rows else 0,
        "hit_at_5": mean(row["hit_at_5"] for row in rows) if rows else 0,
        "mrr": mean(row["mrr"] for row in rows) if rows else 0,
        "ndcg_at_5": mean(row["ndcg_at_5"] for row in rows) if rows else 0,
    }
    return rows, summary


def _is_relevant(hit: dict, case: dict) -> bool:
    metadata = hit.get("metadata") or {}
    haystack = "\n".join([
        hit.get("title", ""),
        hit.get("filename", ""),
        hit.get("content", ""),
        json.dumps(metadata, ensure_ascii=False),
    ]).lower()
    expected_keywords = [value.lower() for value in case.get("expected_keywords", [])]
    expected_documents = [value.lower() for value in case.get("expected_documents", [])]
    keyword_match = any(keyword in haystack for keyword in expected_keywords)
    document_match = any(document in haystack for document in expected_documents)
    return keyword_match and (document_match or not expected_documents)


def _reciprocal_rank(labels: list[bool]) -> float:
    for index, label in enumerate(labels, start=1):
        if label:
            return 1 / index
    return 0.0


def _ndcg(labels: list[bool]) -> float:
    dcg = sum((1 if label else 0) / math.log2(index + 2) for index, label in enumerate(labels))
    ideal = sum(1 / math.log2(index + 2) for index in range(sum(1 for label in labels if label)))
    return dcg / ideal if ideal else 0.0


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate NEV RAG retrieval variants.")
    parser.add_argument("--cases", default=str(Path(__file__).with_name("evaluation_cases.json")))
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--variant", choices=list(VARIANTS) + ["all"], default="all")
    parser.add_argument("--out", default="retrieval_eval_results.csv")
    args = parser.parse_args()

    cases = load_cases(Path(args.cases))
    variants = list(VARIANTS) if args.variant == "all" else [args.variant]
    all_rows = []
    summaries = []
    for variant in variants:
        rows, summary = await evaluate_variant(cases, variant, args.limit)
        all_rows.extend(rows)
        summaries.append(summary)

    write_rows(Path(args.out), all_rows)
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
