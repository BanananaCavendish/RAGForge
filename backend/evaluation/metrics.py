"""评估指标:检索侧(recall@k / MRR)与生成侧(忠实度 / 引用准确率)。

口径约定:
- 检索指标在「文档级」计算:同一文档命中的多个 chunk 只算一次,
  retrieved 取去重后的 doc_id 排名前 k。
- 忠实度 = 忠实题数 / 总题数(每题 0/1 再平均)。
- 引用准确率 = 被支撑的引用总数 / 引用总数(汇总口径,避免小样本偏置)。
"""

from dataclasses import dataclass, field


def dedupe_doc_ids(docs) -> list[str]:
    """按 doc_id 去重,保留首次出现顺序(即排名序)。"""
    seen: set[str] = set()
    out: list[str] = []
    for d in docs:
        did = d.metadata.get("doc_id")
        if did and did not in seen:
            seen.add(did)
            out.append(did)
    return out


def recall_at_k(retrieved_ids: list[str], golden_ids: set[str], k: int) -> float:
    """前 k 个去重 doc_id 中命中 golden 的比例。"""
    if not golden_ids:
        return 1.0
    hit = set(retrieved_ids[:k]) & golden_ids
    return len(hit) / len(golden_ids)


def mrr(retrieved_ids: list[str], golden_ids: set[str]) -> float:
    """第一个 golden 命中位置倒数的均值;未命中返回 0。"""
    for i, rid in enumerate(retrieved_ids):
        if rid in golden_ids:
            return 1.0 / (i + 1)
    return 0.0


@dataclass
class RetrievalScores:
    recall: dict[int, float] = field(default_factory=dict)  # {k: 平均 recall@k}
    mrr: float = 0.0

    def accumulate(self, retrieved_ids, golden_ids) -> None:
        golden = set(golden_ids)
        for k in (3, 5, 10):
            self.recall[k] = self.recall.get(k, 0.0) + recall_at_k(retrieved_ids, golden, k)
        self.mrr += mrr(retrieved_ids, golden)

    def finalize(self, n: int) -> dict:
        if n == 0:
            return {}
        return {
            "recall@3": round(self.recall.get(3, 0.0) / n, 4),
            "recall@5": round(self.recall.get(5, 0.0) / n, 4),
            "recall@10": round(self.recall.get(10, 0.0) / n, 4),
            "mrr": round(self.mrr / n, 4),
        }
