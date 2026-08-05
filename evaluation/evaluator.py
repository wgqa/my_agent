from typing import List, Dict
import itertools
from tqdm import tqdm

from core.pipeline import Pipeline
from evaluation.metrics import hit_at_k, recall_at_k, mrr, ndcg_at_k


class QAPair:
    def __init__(self, question: str, relevant_ids: List[str]):
        self.question = question
        self.relevant_ids = relevant_ids


class Evaluator:
    """跨配置运行评估实验"""

    def __init__(self, pipeline: Pipeline, test_set: List[QAPair]):
        self.pipeline = pipeline
        self.test_set = test_set

    def run(self, config_grid: Dict[str, List]) -> List[Dict]:
        """遍历配置组合，返回实验结果列表"""
        # 保护：_apply_config 只改配置字段，不重建切分/Embedding/索引，
        # 跨 chunk_strategy 对比会基于同一份旧索引产生虚假报告
        chunk_strategies = config_grid.get("chunk_strategy")
        if chunk_strategies is not None and len(set(chunk_strategies)) > 1:
            raise ValueError(
                "当前 Evaluator 不支持跨 chunk_strategy 策略评测："
                "切分和索引没有重建，对比结果不可信；"
                "请等待后续 ExperimentRunner 实现实验隔离"
            )

        results = []
        keys = list(config_grid.keys())
        values = list(config_grid.values())

        for combo in tqdm(list(itertools.product(*values)), desc="Running experiments"):
            config = dict(zip(keys, combo))
            self._apply_config(config)

            all_hits = []
            all_recalls = []
            all_mrrs = []
            all_ndcgs = []

            top_k = config.get("top_k", 5)
            for qa in self.test_set:
                retrieved = self.pipeline.retriever.retrieve(qa.question, top_k=top_k)
                retrieved_ids = [
                    d.metadata.get("id", str(i))
                    for i, d in enumerate(retrieved)
                ]

                all_hits.append(hit_at_k(retrieved_ids, qa.relevant_ids))
                all_recalls.append(recall_at_k(retrieved_ids, qa.relevant_ids))
                all_mrrs.append(mrr(retrieved_ids, qa.relevant_ids))
                all_ndcgs.append(ndcg_at_k(retrieved_ids, qa.relevant_ids, k=top_k))

            results.append({
                **config,
                "hit_at_k": sum(all_hits) / len(all_hits),
                "recall_at_k": sum(all_recalls) / len(all_recalls),
                "mrr": sum(all_mrrs) / len(all_mrrs),
                "ndcg": sum(all_ndcgs) / len(all_ndcgs),
            })

        return results

    def _apply_config(self, config: Dict):
        # Phase 2 重写 ExperimentRunner，届时移除这里的 dict 操作
        try:
            if "chunk_strategy" in config:
                self.pipeline.config.chunker_strategy = config["chunk_strategy"]
            if "retriever_strategy" in config:
                self.pipeline.config.retriever_strategy = config["retriever_strategy"]
            if "top_k" in config:
                self.pipeline.config.top_k = config["top_k"]
        except AttributeError:
            pass
        self.pipeline.retriever = self.pipeline._init_retriever()
        # 新 Retriever 的 Hybrid BM25 是空索引，必须重建后再检索，
        # 否则 Hybrid 评测会退化成 Dense-only（Pipeline 只在初始化时重建一次）
        self.pipeline._rebuild_sparse_index()
