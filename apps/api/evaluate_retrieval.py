import argparse
import asyncio
import csv
import json
import math
import re
import time
from pathlib import Path
from statistics import mean


VARIANTS = {
    "no_rag": {"retrieve": False, "label": "无 RAG 基线"},
    "dense_only": {"retrieve": True, "use_rerank": False, "use_keyword": False, "label": "dense only"},
    "dense_keyword": {"retrieve": True, "use_rerank": False, "use_keyword": True, "label": "dense + keyword"},
    "dense_rerank": {"retrieve": True, "use_rerank": True, "use_keyword": False, "label": "dense + rerank"},
    "hybrid_rerank": {"retrieve": True, "use_rerank": True, "use_keyword": True, "label": "hybrid + rerank"},
}

VARIANT_ALIASES = {
    "dense": "dense_only",
    "hybrid": "hybrid_rerank",
}

DEFAULT_VARIANTS = ["no_rag", "dense_only", "dense_keyword", "dense_rerank", "hybrid_rerank"]

DOMAIN_TERMS = [
    "BMS",
    "OBC",
    "DCDC",
    "DC/DC",
    "VCU",
    "CAN",
    "HVIL",
    "MCU",
    "READY",
    "SOC",
    "绝缘",
    "互锁",
    "快充",
    "慢充",
    "高压",
    "预充",
    "热管理",
    "水泵",
    "限扭",
    "唤醒",
    "离线",
]


def load_cases(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_query_terms(query: str) -> list[str]:
    terms = set(re.findall(r"\b[PCBU][0-9A-F]{4}\b", query.upper()))
    lowered = query.lower()
    for term in DOMAIN_TERMS:
        if term.lower() in lowered:
            terms.add(term)
    return sorted(terms, key=lambda value: (-len(value), value))[:8]


async def evaluate_variant(cases: list[dict], variant: str, limit: int) -> tuple[list[dict], dict]:
    variant = VARIANT_ALIASES.get(variant, variant)
    options = VARIANTS[variant]
    db = None
    retrieve_fn = None
    if options["retrieve"]:
        from app.db.session import SessionLocal
        from app.rag.service import retrieve as rag_retrieve

        db = SessionLocal()
        retrieve_fn = rag_retrieve
    try:
        rows = []
        for case in cases:
            started_at = time.perf_counter()
            if options["retrieve"]:
                hits = await retrieve_fn(
                    db,
                    case["question"],
                    None,
                    limit=limit,
                    use_rerank=options["use_rerank"],
                    use_keyword=options["use_keyword"],
                )
            else:
                hits = []
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            labels = [_is_relevant(hit, case) for hit in hits]
            safety_score = _safety_evidence_coverage(hits, case)
            row = {
                "variant": variant,
                "variant_label": options["label"],
                "category": case.get("category", ""),
                "case_id": case["id"],
                "question": case["question"],
                "query_terms": ",".join(extract_query_terms(case["question"])),
                "hit_at_1": int(any(labels[:1])),
                "hit_at_3": int(any(labels[:3])),
                "hit_at_5": int(any(labels[:5])),
                "mrr": _reciprocal_rank(labels),
                "ndcg_at_5": _ndcg(labels[:5]),
                "citation_accuracy_at_k": _citation_accuracy(labels[:limit]),
                "keyword_coverage_at_k": _keyword_coverage(hits[:limit], case),
                "safety_evidence_coverage": safety_score if safety_score is not None else "",
                "latency_ms": latency_ms,
                "top_title": hits[0]["title"] if hits else "",
                "top_filename": hits[0]["filename"] if hits else "",
                "top_score": hits[0].get("rerank_score", hits[0].get("score", 0)) if hits else 0,
                "top_vector_score": hits[0].get("vector_score", "") if hits else "",
                "top_rerank_score": hits[0].get("rerank_score", "") if hits else "",
                "top_keyword_matches": ",".join(hits[0].get("keyword_matches", [])) if hits else "",
                "expected_keywords": ",".join(case.get("expected_keywords", [])),
                "expected_documents": ",".join(case.get("expected_documents", [])),
            }
            rows.append(row)
    finally:
        if db:
            db.close()
    summary = {
        "variant": variant,
        "variant_label": options["label"],
        "cases": len(rows),
        "hit_at_1": _mean(rows, "hit_at_1"),
        "hit_at_3": _mean(rows, "hit_at_3"),
        "hit_at_5": _mean(rows, "hit_at_5"),
        "mrr": _mean(rows, "mrr"),
        "ndcg_at_5": _mean(rows, "ndcg_at_5"),
        "citation_accuracy_at_k": _mean(rows, "citation_accuracy_at_k"),
        "keyword_coverage_at_k": _mean(rows, "keyword_coverage_at_k"),
        "safety_evidence_coverage": _mean(rows, "safety_evidence_coverage"),
        "avg_latency_ms": _mean(rows, "latency_ms"),
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


def _citation_accuracy(labels: list[bool]) -> float:
    if not labels:
        return 0.0
    return sum(1 for label in labels if label) / len(labels)


def _keyword_coverage(hits: list[dict], case: dict) -> float:
    expected_keywords = [value.lower() for value in case.get("expected_keywords", [])]
    if not expected_keywords:
        return 0.0
    haystack = "\n".join(_hit_text(hit) for hit in hits).lower()
    matched = sum(1 for keyword in expected_keywords if keyword in haystack)
    return matched / len(expected_keywords)


def _safety_evidence_coverage(hits: list[dict], case: dict) -> float | None:
    safety_terms = [value.lower() for value in case.get("safety_terms", [])]
    if not safety_terms:
        return None
    haystack = "\n".join(_hit_text(hit) for hit in hits).lower()
    matched = sum(1 for term in safety_terms if term in haystack)
    return matched / len(safety_terms)


def _hit_text(hit: dict) -> str:
    metadata = hit.get("metadata") or {}
    return "\n".join([
        hit.get("title", ""),
        hit.get("filename", ""),
        hit.get("content", ""),
        json.dumps(metadata, ensure_ascii=False),
        " ".join(hit.get("keyword_matches", [])),
    ])


def _reciprocal_rank(labels: list[bool]) -> float:
    for index, label in enumerate(labels, start=1):
        if label:
            return 1 / index
    return 0.0


def _ndcg(labels: list[bool]) -> float:
    dcg = sum((1 if label else 0) / math.log2(index + 2) for index, label in enumerate(labels))
    ideal = sum(1 / math.log2(index + 2) for index in range(sum(1 for label in labels if label)))
    return dcg / ideal if ideal else 0.0


def _mean(rows: list[dict], key: str) -> float:
    values = [float(row[key]) for row in rows if row.get(key) not in ("", None)]
    return mean(values) if values else 0.0


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
    parser.add_argument("--variant", choices=sorted(set(VARIANTS) | set(VARIANT_ALIASES) | {"all"}), default="all")
    parser.add_argument("--out", default="retrieval_eval_results.csv")
    parser.add_argument("--summary-out", default="retrieval_eval_summary.json")
    args = parser.parse_args()

    cases = load_cases(Path(args.cases))
    variants = DEFAULT_VARIANTS if args.variant == "all" else [VARIANT_ALIASES.get(args.variant, args.variant)]
    all_rows = []
    summaries = []
    for variant in variants:
        rows, summary = await evaluate_variant(cases, variant, args.limit)
        all_rows.extend(rows)
        summaries.append(summary)

    write_rows(Path(args.out), all_rows)
    Path(args.summary_out).write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
