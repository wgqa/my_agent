from typing import List, Dict


class QueryRewriter:
    """把依赖历史的问题改写为独立问句（最小实现）"""

    def rewrite(self, history: List[Dict], current_query: str) -> str:
        """有历史且当前问题含指代词时改写，否则原样返回"""
        if not history:
            return current_query

        indicators = ["它", "他", "她", "这", "那", "上述", "上面", "该"]
        if not any(ind in current_query for ind in indicators):
            return current_query

        last_user_q = ""
        for m in reversed(history):
            if m.get("role") == "user":
                last_user_q = m.get("content", "")
                break

        if not last_user_q:
            return current_query

        return f"{last_user_q.rstrip('？?')}和{current_query.rstrip('？?')}的区别是什么"
