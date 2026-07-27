from typing import List, Dict


def generate_report(results: List[Dict]) -> str:
    """生成 Markdown 格式的对比报告"""
    if not results:
        return "No results."

    report = ["# 评估对比报告\n"]
    report.append(f"共 {len(results)} 组实验\n")

    headers = list(results[0].keys())
    report.append("| " + " | ".join(headers) + " |")
    report.append("| " + " | ".join(["---"] * len(headers)) + " |")

    sorted_results = sorted(results, key=lambda r: r.get("hit_rate", 0), reverse=True)
    for r in sorted_results:
        row = []
        for h in headers:
            val = r.get(h, "")
            if isinstance(val, float):
                row.append(f"{val:.3f}")
            else:
                row.append(str(val))
        report.append("| " + " | ".join(row) + " |")

    report.append(f"\n## 最佳配置\n")
    best = sorted_results[0]
    report.append(f"- Hit Rate: {best.get('hit_rate', 0):.3f}")
    report.append(f"- MRR: {best.get('mrr', 0):.3f}")
    report.append(f"- NDCG@5: {best.get('ndcg', 0):.3f}")

    return "\n".join(report)
