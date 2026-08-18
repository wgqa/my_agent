"""G5-APP-04: RAG Agent Demo Console（Streamlit）。

把三种正式后端能力接到网页：
  ① Basic RAG              → POST /query
  ② Agentic RAG            → POST /agent/query
  ③ Structured Tool Agent  → POST /tool-agent/query

HTTP 全部走 ui.api_client.ApiClient；页面渲染走 ui.renderers。
UI 只展示 API 返回的事实：不推断 CoT、不展示 Prompt、不展示 API key。
"""

import streamlit as st

from ui import renderers
from ui.api_client import ApiClient, ApiError

MODES = {
    "Basic RAG": "检索 → Rerank → Generate",
    "Agentic RAG": "Planner → Adaptive Retrieval → Verification → Answer",
    "Structured Tool Agent": "Decision → Tool → Observation → Final",
}
MODE_KEY = {
    "Basic RAG": "basic",
    "Agentic RAG": "agent",
    "Structured Tool Agent": "tool_agent",
}
DEFAULT_API_URL = "http://localhost:8000"


def _init_state() -> None:
    if "api_client" not in st.session_state:
        st.session_state.api_client = ApiClient(DEFAULT_API_URL)
    if "messages_by_mode" not in st.session_state:
        st.session_state.messages_by_mode = {"basic": [], "agent": [], "tool_agent": []}


def _show_error(err: ApiError) -> None:
    if err.kind == "connection_error":
        st.error("无法连接 API，请先启动后端")
    elif err.kind == "timeout":
        st.error("请求超时")
    elif err.kind == "http_error" and err.status == 503:
        st.error("运行时当前不可用")
        if err.detail:
            st.caption(str(err.detail)[:200])
    elif err.kind == "http_error":
        st.error(err.message)
        if err.detail:
            st.caption(str(err.detail)[:200])
    else:  # invalid_response
        st.error(err.message)


# ── 提交 ────────────────────────────────────────────────────────

def _submit(question: str, mode: str, top_k: int) -> dict:
    client = st.session_state.api_client
    try:
        if mode == "basic":
            result = client.query(question, top_k)
            renderers.render_basic_result(result)
            return {"content": result.get("answer", ""), "kind": "basic", "result": result}
        if mode == "agent":
            result = client.agent_query(question, top_k)
            renderers.render_agent_result(result)
            return {"content": "", "kind": "agent", "result": result}
        result = client.tool_agent_query(question)
        renderers.render_tool_result(result)
        return {"content": "", "kind": "tool_agent", "result": result}
    except ApiError as err:
        _show_error(err)
        return {"content": f"❌ {err.message}", "kind": mode, "result": None}


def _render_message(msg: dict) -> None:
    if msg.get("role") == "user":
        with st.chat_message("user"):
            st.markdown(msg.get("content", ""))
        return
    with st.chat_message("assistant"):
        result = msg.get("result")
        kind = msg.get("kind")
        if result and kind == "basic":
            renderers.render_basic_result(result)
        elif result and kind == "agent":
            renderers.render_agent_result(result)
        elif result and kind == "tool_agent":
            renderers.render_tool_result(result)
        else:
            content = msg.get("content", "")
            if content:
                st.markdown(content)


# ── 侧边栏 ─────────────────────────────────────────────────────

def _sidebar() -> tuple[str, int]:
    with st.sidebar:
        st.title("⚙️ RAG Agent Console")
        api_url = st.text_input("API 地址", value=DEFAULT_API_URL)
        st.session_state.api_client.base_url = api_url.rstrip("/")

        st.divider()
        try:
            health = st.session_state.api_client.health()
            st.success(f"✅ 服务正常  |  文档数: {health.get('docs_count', '?')}")
            st.caption(
                f"Embedding: {health.get('embedding_provider')}  |  "
                f"检索: {health.get('retriever_strategy')}  |  "
                f"生成: {health.get('generator_provider')}"
            )
        except ApiError:
            st.error("❌ 服务不可用 — 请确认后端已启动")

        st.divider()
        mode = st.radio(
            "运行模式",
            list(MODES.keys()),
            help="选择要使用的后端链路",
        )
        st.caption(MODES[mode])

        top_k = 5
        if MODE_KEY[mode] != "tool_agent":
            top_k = st.slider("检索数量 (top_k)", min_value=1, max_value=10, value=5)
        st.divider()
        if st.button("清空对话"):
            st.session_state.messages_by_mode[MODE_KEY[mode]] = []
            st.rerun()
    return mode, top_k


# ── 知识库 Tab ─────────────────────────────────────────────────

def _tab_knowledge_base() -> None:
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("上传文件")
        uploaded = st.file_uploader(
            "选择文件上传到知识库",
            type=["txt", "md", "pdf", "py", "js", "java"],
        )
        if uploaded is not None:
            with st.spinner(f"正在索引 {uploaded.name}..."):
                try:
                    result = st.session_state.api_client.index_file(
                        uploaded.getvalue(), uploaded.name
                    )
                    st.success(
                        f"✅ {result.get('file_name', uploaded.name)} 索引完成 — "
                        f"生成 {result.get('chunks', '?')} 个块"
                    )
                except ApiError as err:
                    _show_error(err)
    with col2:
        st.subheader("知识库状态")
        try:
            stats = st.session_state.api_client.stats()
            st.metric("文档块总数", stats.get("documents_count", "?"))
            with st.expander("当前配置"):
                st.json(stats.get("config", {}))
        except ApiError:
            st.info("无法获取知识库状态")


# ── Console Tab ────────────────────────────────────────────────

def _tab_console(mode: str, top_k: int) -> None:
    key = MODE_KEY[mode]
    messages = st.session_state.messages_by_mode[key]

    for msg in messages:
        _render_message(msg)

    if prompt := st.chat_input("输入你的问题..."):
        messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("处理中..."):
                reply = _submit(prompt, MODE_KEY[mode], top_k)
        messages.append({"role": "assistant", **reply})
        st.session_state.messages_by_mode[key] = messages


# ── 主入口 ─────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(page_title="RAG Agent Demo Console", layout="wide")
    _init_state()
    mode, top_k = _sidebar()

    st.title("📚 RAG Agent Demo Console")
    tab_kb, tab_console = st.tabs(["📥 知识库", "🤖 Agent Console"])

    with tab_kb:
        _tab_knowledge_base()
    with tab_console:
        _tab_console(mode, top_k)


if __name__ == "__main__":
    main()
