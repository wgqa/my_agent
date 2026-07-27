from typing import List
import numpy as np

from core.loader.base import Document


def check_chunk_quality(chunks: List[Document]) -> dict:
    """质控检查：分块一致性、空块、长度分布"""
    lengths = [len(c.content) for c in chunks]
    return {
        "length_cv": float(np.std(lengths) / max(np.mean(lengths), 1)),
        "empty_chunks": sum(1 for c in chunks if not c.content.strip()),
        "min_len": min(lengths) if lengths else 0,
        "max_len": max(lengths) if lengths else 0,
        "total_chunks": len(chunks),
    }
