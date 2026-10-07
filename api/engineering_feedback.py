"""Deterministic product feedback; never an answer or a decision fallback."""

from __future__ import annotations

from typing import Any, Mapping


# Only stable public outcome codes select copy. No exception text, trace,
# model rationale, paths or credentials enter these messages.
_REFUSALS = {
    "INSUFFICIENT_EVIDENCE_TO_FINALIZE": (
        "暂时无法给出可靠结论", "这次取得的资料还不足以支持所问结论。",
        ("确认对话绑定的是目标项目，并补充具体的文件路径、函数名或报错。",
         "如果问题依赖外部资料，可在知识库上传相关文档后再提问。"), "revise"),
    "INSUFFICIENT_INFORMATION": (
        "还需要一些具体信息", "系统本次未能明确要分析的对象或具体情况，还需要一些信息。",
        ("请补充目标文件或函数、预期行为与实际现象；遇到报错时可附上报错内容。",), "revise"),
    "UNSUPPORTED_REQUEST": (
        "本次请求未能继续处理", "系统本次将请求判定为超出支持范围，因此停止了分析。",
        ("可以补充文件路径与具体分析目标后再提问，例如解释某个函数的实现或检查配置。",
         "当前支持读取和分析项目；修改文件与执行命令需要在外部完成。"), "revise"),
    "UNSAFE_REQUEST": (
        "本次请求未通过安全判断", "系统本次将请求判定为存在安全风险，已停止处理。",
        ("可以说明合法的排查或防护目标，询问风险分析或安全的修复建议。",), None),
    "AGENT_BUDGET_EXCEEDED": (
        "本次分析已达到运行上限", "系统已停止继续检索或读取，尚未形成完整结论。",
        ("把问题拆成一个具体目标，或提供文件路径、函数名以缩小分析范围。",), "revise"),
    "AGENT_DUPLICATE_TOOL_CALL": (
        "本次分析未能继续推进", "分析停在重复的检索或读取步骤，暂时未形成结论。",
        ("补充更明确的文件路径、函数名或关键词，帮助系统定位新的资料。",), "revise"),
    "AGENT_TOOL_ERROR_LIMIT": (
        "资料读取遇到问题", "本次检索或读取多次出错，系统已停止分析。",
        ("检查本地项目目录是否可访问、文件路径是否正确；涉及 Git 时确认目录属于 Git 仓库。",), "revise"),
    "ENGINEERING_RUN_DEADLINE_EXCEEDED": (
        "本次分析超时", "本次分析超过运行时限，尚未形成完整结论。",
        ("可以稍后重新尝试，或把问题缩小到一个文件、函数或具体配置。",), "retry"),
    "ENGINEERING_RUN_CANCELLED": (
        "本次分析已停止", "任务收到停止信号，尚未完成。",
        ("如果仍需继续，可重新填写并发送问题。",), "retry"),
}

_FAILURES = {
    "ACTION_TIMEOUT": (
        "模型响应超时", "本次请求未能在等待时限内取得模型结果。",
        ("可以稍后重新尝试，或把问题拆成更具体的一步。",), "retry"),
    "ACTION_PROVIDER_ERROR": (
        "模型服务暂时不可用", "本次请求未能从模型服务取得有效结果。",
        ("可以稍后重试；持续出现时，请检查后端的模型服务配置与连接。",), "retry"),
    "ACTION_PARSE_FAILED": (
        "本次回答生成失败", "系统未能解析有效的分析结果，因此没有发布答案。",
        ("可以重新尝试，或把问题拆成一个更具体的目标。",), "retry"),
}


def engineering_feedback(result: Mapping[str, Any]) -> dict[str, Any] | None:
    status = result.get("status")
    reason = result.get("reason_code")
    failure = result.get("failure_code")
    if status == "refused":
        entry = _REFUSALS.get(reason if isinstance(reason, str) else None, (
            "本次暂未形成可靠结论", "系统未能完成这次请求。",
            ("确认项目与问题范围，补充相关资料或更具体的背景后再提问。",), "revise"))
    elif status == "failed":
        entry = _FAILURES.get(failure if isinstance(failure, str) else None, (
            "本次分析未完成", "系统遇到了问题，尚未发布可靠答案。",
            ("可以稍后重新尝试；持续出现时，请检查后端服务状态。",), "retry"))
    else:
        return None
    title, message, next_steps, action = entry
    return {"title": title, "message": message, "next_steps": list(next_steps), "action": action}


def feedback_content(result: Mapping[str, Any]) -> str:
    feedback = engineering_feedback(result)
    if feedback is None:
        return result.get("answer") or ""
    return "\n".join((feedback["title"], feedback["message"],
                      *("建议：" + step for step in feedback["next_steps"])))


def present_conversation(detail: dict) -> dict:
    """Present old stored refusals without rewriting history or its context."""
    messages = []
    for message in detail["messages"]:
        result = message.get("result")
        if message.get("role") == "assistant" and isinstance(result, dict):
            feedback = engineering_feedback(result)
            if feedback is not None:
                message = {**message, "content": feedback_content(result),
                           "result": {**result, "feedback": feedback}}
        messages.append(message)
    return {**detail, "messages": messages}
