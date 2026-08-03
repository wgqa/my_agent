import re
from dataclasses import dataclass, field
from typing import List

from core.context.assembler import ContextBlock


@dataclass
class CitationCheck:
    """单条引用的验证结果"""
    citation_id: str
    valid: bool
    chunk_id: str = ""
    source_name: str = ""
    reason: str = ""


@dataclass
class CitationValidation:
    """整段答案的引用验证结果"""
    valid: List[CitationCheck] = field(default_factory=list)
    invalid: List[CitationCheck] = field(default_factory=list)

    @property
    def validity_rate(self) -> float:
        total = len(self.valid) + len(self.invalid)
        return len(self.valid) / total if total else 1.0


class CitationValidator:
    """验证答案中的引用是否真实存在于本次 Context"""

    PATTERN = re.compile(r"\[C(\d+)\]")

    def validate(self, answer: str, blocks: List[ContextBlock]) -> CitationValidation:
        cited_ids = sorted({int(m) for m in self.PATTERN.findall(answer)})

        block_map = {b.citation_id: b for b in blocks}

        result = CitationValidation()
        for n in cited_ids:
            cid = f"[C{n}]"
            block = block_map.get(cid)
            if block is None:
                result.invalid.append(CitationCheck(
                    citation_id=cid,
                    valid=False,
                    reason="引用 ID 不存在于本次 Context",
                ))
            else:
                result.valid.append(CitationCheck(
                    citation_id=cid,
                    valid=True,
                    chunk_id=block.chunk_id,
                    source_name=block.source_name,
                ))
        return result
