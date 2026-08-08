"""评估主入口:检索消融(recall@k / MRR)+ 生成质量(忠实度 / 引用准确率)。

跑完后:
  - 终端打印 Markdown 指标表
  - 写 data/eval/report.json(README 直接引用这份数字)

用法:python scripts/run_eval.py [--limit N] [--skip-generation]
"""

import sys
import time
from pathlib import Path

# Windows 控制台默认 GBK,打印 emoji/生僻字会崩;统一重配置为 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from backend.core import config
from backend.evaluation.judge import judge_citations, judge_faithful
from backend.evaluation.metrics import RetrievalScores, dedupe_doc_ids
from backend.services.rag_service import get_service
from backend.services.retrieval import (
    build_hybrid_retriever,
    build_reranked_retriever,
    build_vector_retriever,
)

STRATEGIES = ("vector", "hybrid", "hybrid+rerank")


def load_golden() -> list[dict]:
    path = config.GOLDEN_DIR / "golden_qa.json"
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 题(默认全部)")
    parser.add_argument("--skip-generation", action="store_true", help="跳过 LLM 生成与判分")
    args = parser.parse_args()

    config.validate_config()
    golden = load_golden()
    if args.limit:
        golden = golden[: args.limit]

    service = get_service()
    manager = service.manager

    # golden 文件名 → doc_id(经 manifest 解析,避免把哈希写进 golden)
    name_to_id = {info["filename"]: doc_id for doc_id, info in manager.manifest.items()}
    missing = {f for qa in golden for f in qa["expected_files"]} - set(name_to_id)
    if missing:
        print(f"⚠️ golden 引用的文档未入库: {missing}")

    retrievers = {
        "vector": build_vector_retriever(manager, k=10),
        "hybrid": build_hybrid_retriever(manager, k=10),
        "hybrid+rerank": build_reranked_retriever(manager, top_k=5, k=10),
    }
    scores = {name: RetrievalScores() for name in STRATEGIES}

    generation = []  # 每题: {question, context, answer}

    print(f"\n📋 golden 集: {len(golden)} 题\n")
    for qa in golden:
        q = qa["question"]
        golden_ids = {name_to_id[f] for f in qa["expected_files"] if f in name_to_id}
        for name, retriever in retrievers.items():
            docs = retriever.invoke(q)
            scores[name].accumulate(dedupe_doc_ids(docs), golden_ids)

        if not args.skip_generation:
            result = service.answer(session_id=f"eval-{qa['id']}", question=q)
            generation.append({"question": q, "context": result["context"], "answer": result["answer"]})

    # ── 检索指标表 ────────────────────────────────────────────────
    rows = []
    for name in STRATEGIES:
        rows.append({**scores[name].finalize(len(golden)), "strategy": name})
    print("### 检索消融(文档级 recall@k / MRR)")
    header = ["strategy", "recall@3", "recall@5", "recall@10", "mrr"]
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for r in rows:
        print(f"| {r['strategy']} | {r['recall@3']} | {r['recall@5']} | {r['recall@10']} | {r['mrr']} |")

    # ── 生成质量(LLM-as-judge)────────────────────────────────────
    gen_report = None
    if generation:
        print("\n### 生成质量(LLM-as-judge)")
        faithful_ok = 0
        cit_ok = cit_total = 0
        details = []
        for i, g in enumerate(generation, 1):
            f = judge_faithful(g["context"], g["answer"])
            c = judge_citations(g["context"], g["answer"])
            faithful_ok += 1 if f.faithful else 0
            for item in c.citations:
                cit_total += 1
                cit_ok += 1 if item.supported else 0
            details.append(
                {
                    "question": g["question"],
                    "faithful": f.faithful,
                    "faithful_reason": f.reason,
                    "citations": [item.model_dump() for item in c.citations],
                }
            )
            print(f"  [{i}/{len(generation)}] 忠实={f.faithful}  引用支撑={cit_ok}/{cit_total}")
            time.sleep(0.2)  # 轻微限速,避免触发 API 频率限制

        gen_report = {
            "faithfulness": round(faithful_ok / len(generation), 4),
            "citation_accuracy": round(cit_ok / cit_total, 4) if cit_total else None,
            "answers_judged": len(generation),
            "details": details,
        }

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "golden_count": len(golden),
        "retrieval": rows,
        "generation": gen_report,
    }
    config.EVAL_DIR.mkdir(parents=True, exist_ok=True)
    out = config.EVAL_DIR / "report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 已写入 {out}")


if __name__ == "__main__":
    main()
