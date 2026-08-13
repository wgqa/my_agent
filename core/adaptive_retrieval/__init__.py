"""G3-ADAPT-06A：确定性 Adaptive Retrieval 策略导出。"""

from core.adaptive_retrieval.policy import (
    ADAPTIVE_RETRIEVAL_POLICY_VERSION,
    RETRIEVAL_STRATEGIES,
    STRATEGY_REASON_CODES,
    resolve_initial_strategy,
)

__all__ = [
    "ADAPTIVE_RETRIEVAL_POLICY_VERSION",
    "RETRIEVAL_STRATEGIES",
    "STRATEGY_REASON_CODES",
    "resolve_initial_strategy",
]
