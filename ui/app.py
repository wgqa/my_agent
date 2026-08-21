"""G7-UI-01: Chat-first RAG Agent product UI.

The page keeps the existing API contract and safe response boundary while
organising the demo around session-local conversations instead of debug tabs.
"""

from __future__ import annotations

import html
import os
from uuid import uuid4

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
MODE_LABEL_BY_KEY = {value: label for label, value in MODE_KEY.items()}
MODE_FEATURE = {
    "Basic RAG": "basic_rag",
    "Agentic RAG": "agentic_rag",
    "Structured Tool Agent": "structured_tool_agent",
}
MODE_FEATURE_BY_KEY = {value: MODE_FEATURE[label] for label, value in MODE_KEY.items()}
DEFAULT_API_URL = os.getenv("RAG_API_URL", "http://localhost:8000")
MAX_TITLE_LENGTH = 36


def _conversation(mode: str = "basic") -> dict:
    conversation_id = uuid4().hex[:10]
    return {
        "id": conversation_id,
        "title": "New conversation",
        "mode": mode,
        "messages": [],
    }


def _init_state() -> None:
    if not hasattr(st.session_state, "api_client"):
        st.session_state.api_client = ApiClient(DEFAULT_API_URL)

    if not hasattr(st.session_state, "conversations"):
        legacy = getattr(st.session_state, "messages_by_mode", None)
        conversations = {}
        if isinstance(legacy, dict):
            for mode in ("basic", "agent", "tool_agent"):
                messages = legacy.get(mode) or []
                if messages:
                    item = _conversation(mode)
                    item["messages"] = list(messages)
                    conversations[item["id"]] = item
        if not conversations:
            item = _conversation()
            conversations[item["id"]] = item
        st.session_state.conversations = conversations

    if not hasattr(st.session_state, "active_conversation_id"):
        st.session_state.active_conversation_id = next(
            iter(st.session_state.conversations)
        )
    if st.session_state.active_conversation_id not in st.session_state.conversations:
        st.session_state.active_conversation_id = next(
            iter(st.session_state.conversations)
        )

    if not hasattr(st.session_state, "runtime_capabilities"):
        st.session_state.runtime_capabilities = None
    if not hasattr(st.session_state, "runtime_health"):
        st.session_state.runtime_health = None
    if not hasattr(st.session_state, "project_identity"):
        st.session_state.project_identity = None
    if not hasattr(st.session_state, "api_available"):
        st.session_state.api_available = False
    if not hasattr(st.session_state, "top_k"):
        st.session_state.top_k = 5


def _active_conversation() -> dict:
    if not hasattr(st.session_state, "conversations"):
        legacy = getattr(st.session_state, "messages_by_mode", {})
        mode = "basic"
        conversations = {}
        if isinstance(legacy, dict):
            for legacy_mode in ("basic", "agent", "tool_agent"):
                if legacy.get(legacy_mode):
                    item = _conversation(legacy_mode)
                    item["messages"] = list(legacy[legacy_mode])
                    conversations[item["id"]] = item
                    mode = legacy_mode
        if not conversations:
            item = _conversation(mode)
            conversations[item["id"]] = item
        st.session_state.conversations = conversations
        st.session_state.active_conversation_id = next(iter(conversations))
    return st.session_state.conversations[st.session_state.active_conversation_id]


def _new_conversation(mode: str | None = None) -> str:
    if mode is None:
        mode = _active_conversation().get("mode", "basic")
    item = _conversation(mode)
    st.session_state.conversations[item["id"]] = item
    st.session_state.active_conversation_id = item["id"]
    return item["id"]


def _switch_conversation(conversation_id: str) -> None:
    if conversation_id in st.session_state.conversations:
        st.session_state.active_conversation_id = conversation_id


def _title_for_question(question: str) -> str:
    compact = " ".join(question.split())
    if len(compact) <= MAX_TITLE_LENGTH:
        return compact or "New conversation"
    return compact[: MAX_TITLE_LENGTH - 1].rstrip() + "…"


def _feature_enabled(feature: str) -> bool:
    capabilities = getattr(st.session_state, "runtime_capabilities", None)
    if not isinstance(capabilities, dict):
        return False
    features = capabilities.get("features")
    return isinstance(features, dict) and features.get(feature) is True


def _read_capabilities(client: ApiClient) -> dict | None:
    try:
        result = client.capabilities()
    except ApiError:
        return None
    return result if isinstance(result, dict) else None


def _read_project(client: ApiClient) -> dict | None:
    try:
        result = client.project()
    except ApiError:
        return None
    return result if isinstance(result, dict) else None


def _refresh_runtime(client: ApiClient) -> None:
    try:
        st.session_state.runtime_health = client.health()
        st.session_state.api_available = True
    except ApiError:
        st.session_state.runtime_health = None
        st.session_state.api_available = False
    st.session_state.runtime_capabilities = _read_capabilities(client)
    st.session_state.project_identity = _read_project(client)


def _render_project_identity(project: dict) -> None:
    """Compatibility renderer retained for the existing UI unit contract."""
    project_name = project.get("project_name")
    if not isinstance(project_name, str) or not project_name:
        return
    suffix = " (default)" if project.get("source") == "default_repo" else ""
    st.markdown("#### Engineering Project")
    st.caption(f"✓ {project_name}{suffix}")


def _render_project_tag(project: dict | None) -> None:
    if not isinstance(project, dict):
        return
    name = project.get("project_name")
    if isinstance(name, str) and name:
        st.caption(f"Project: {name}")


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
    else:
        st.error(err.message)


def _submit(
    question: str,
    mode: str,
    top_k: int,
    *,
    history=None,
    render: bool = True,
) -> dict:
    feature = MODE_FEATURE_BY_KEY.get(mode)
    if feature and hasattr(st.session_state, "runtime_capabilities"):
        if not _feature_enabled(feature):
            message = f"{MODE_LABEL_BY_KEY.get(mode, mode)} runtime 当前不可用"
            if render:
                st.warning(message)
            return {"content": message, "kind": mode, "result": None}

    client = st.session_state.api_client
    try:
        if mode == "basic":
            result = client.query(question, top_k)
            if render:
                renderers.render_basic_result(result)
            return {"content": result.get("answer", ""), "kind": mode, "result": result}
        if mode == "agent":
            if history:
                result = client.agent_query(question, top_k, history=history)
            else:
                result = client.agent_query(question, top_k)
            if render:
                renderers.render_agent_result(result)
            return {"content": result.get("answer", "") or "", "kind": mode, "result": result}
        result = client.tool_agent_query(question)
        if render:
            renderers.render_tool_result(result)
        return {"content": result.get("answer", "") or "", "kind": "tool_agent", "result": result}
    except ApiError as err:
        if render:
            _show_error(err)
        return {"content": f"❌ {err.message}", "kind": mode, "result": None}


def _render_user_message(content: str) -> None:
    _, column = st.columns([1, 3])
    with column:
        st.markdown(
            f'<div class="user-bubble">{html.escape(content)}</div>',
            unsafe_allow_html=True,
        )


def _render_assistant_message(message: dict) -> None:
    column, _ = st.columns([3, 1])
    with column:
        result = message.get("result")
        kind = message.get("kind")
        if result and kind == "basic":
            renderers.render_basic_result(result)
        elif result and kind == "agent":
            renderers.render_agent_result(result)
        elif result and kind == "tool_agent":
            renderers.render_tool_result(result)
        elif message.get("content"):
            st.markdown(message["content"])


def _render_message(message: dict) -> None:
    if message.get("role") == "user":
        _render_user_message(message.get("content", ""))
    else:
        _render_assistant_message(message)


def _render_knowledge_base(client: ApiClient) -> None:
    st.markdown("##### Knowledge Base")
    if not _feature_enabled("indexing"):
        st.caption("Indexing capability is currently unavailable")
    else:
        uploaded = st.file_uploader(
            "Upload a document",
            type=["txt", "md", "pdf", "py", "js", "java"],
            key="knowledge_base_upload",
        )
        if uploaded is not None:
            with st.spinner(f"正在索引 {uploaded.name}..."):
                try:
                    result = client.index_file(uploaded.getvalue(), uploaded.name)
                    st.success(
                        f"{result.get('file_name', uploaded.name)} 已索引 · "
                        f"{result.get('chunks', '?')} chunks"
                    )
                except ApiError as err:
                    _show_error(err)
    try:
        stats = client.stats()
        st.caption(f"Documents: {stats.get('documents_count', '?')}")
        with st.expander("Configuration", expanded=False):
            st.json(stats.get("config", {}))
    except ApiError:
        st.caption("Knowledge Base status unavailable")


def _tab_knowledge_base() -> None:
    """Legacy test/embedding entry point; the product UI calls this from Settings."""
    _render_knowledge_base(st.session_state.api_client)


def _render_settings(client: ApiClient) -> None:
    with st.expander("Settings", expanded=False):
        api_url = st.text_input("API address", value=client.base_url, key="settings_api_url")
        if api_url.rstrip("/") != client.base_url:
            client.base_url = api_url.rstrip("/")
            _refresh_runtime(client)
        st.markdown("##### System Status")
        health = getattr(st.session_state, "runtime_health", None)
        if isinstance(health, dict):
            st.caption(
                f"{health.get('status', 'ready')} · docs {health.get('docs_count', '?')} · "
                f"{health.get('generator_provider', '?')}"
            )
            st.caption(
                f"Embedding {health.get('embedding_provider', '?')} · "
                f"retriever {health.get('retriever_strategy', '?')}"
            )
        else:
            st.caption("API unavailable")
        capabilities = getattr(st.session_state, "runtime_capabilities", None)
        if isinstance(capabilities, dict):
            feature_state = capabilities.get("features") or {}
            st.caption("Runtime capabilities")
            for label, feature in (
                ("Basic RAG", "basic_rag"),
                ("Agentic RAG", "agentic_rag"),
                ("Structured Tool Agent", "structured_tool_agent"),
                ("Indexing", "indexing"),
            ):
                state = "available" if feature_state.get(feature) is True else "unavailable"
                st.caption(f"{label}: {state}")
        st.session_state.top_k = int(
            st.number_input(
                "Retrieval limit",
                min_value=1,
                max_value=10,
                value=int(st.session_state.top_k),
                step=1,
            )
        )
        _render_knowledge_base(client)


def _sidebar() -> int:
    client = st.session_state.api_client
    _refresh_runtime(client)
    with st.sidebar:
        st.markdown("<div class='product-mark'>RAG Agent</div>", unsafe_allow_html=True)
        if st.button("＋ New chat", use_container_width=True):
            _new_conversation()
            st.rerun()
        st.markdown("##### Conversations")
        st.caption("Today")
        for conversation_id, conversation in st.session_state.conversations.items():
            label = conversation.get("title") or "New conversation"
            if conversation_id == st.session_state.active_conversation_id:
                st.markdown(
                    f"<div class='active-conversation'>{html.escape(label)}</div>",
                    unsafe_allow_html=True,
                )
            elif st.button(label, key=f"conversation_{conversation_id}", use_container_width=True):
                _switch_conversation(conversation_id)
                st.rerun()
        st.markdown("<div class='sidebar-spacer'></div>", unsafe_allow_html=True)
        st.caption("User · Local session")
        _render_settings(client)
    return int(st.session_state.top_k)


def _render_empty_conversation() -> None:
    st.markdown(
        "<div class='empty-state'><h2>How can I help?</h2>"
        "<p>Ask about your documents, retrieval, or project code.</p></div>",
        unsafe_allow_html=True,
    )


def _tab_console(mode: str, top_k: int) -> None:
    if mode in MODE_KEY:
        mode = MODE_KEY[mode]
    conversation = _active_conversation()
    for message in conversation.get("messages", []):
        _render_message(message)
    feature = MODE_FEATURE_BY_KEY[mode]
    if not _feature_enabled(feature):
        st.warning(f"{MODE_LABEL_BY_KEY[mode]} runtime 当前不可用，请检查后端运行时初始化状态。")
        return
    if not getattr(st.session_state, "api_available", True):
        st.error("API unavailable. Start the backend to begin a conversation.")
        return
    if not conversation.get("messages"):
        _render_empty_conversation()
    prompt = st.chat_input("Message RAG Agent")
    if prompt:
        previous_messages = [
            {"role": item.get("role"), "content": item.get("content", "")}
            for item in conversation.get("messages", [])[-20:]
            if item.get("role") in ("user", "assistant") and item.get("content", "").strip()
        ]
        conversation["messages"].append({"role": "user", "content": prompt})
        if conversation.get("title") == "New conversation":
            conversation["title"] = _title_for_question(prompt)
        reply = _submit(
            prompt,
            mode,
            top_k,
            history=previous_messages if mode == "agent" else None,
            render=False,
        )
        conversation["messages"].append({"role": "assistant", **reply})
        st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="RAG Agent",
        page_icon="✦",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] { border-right: 1px solid rgba(120, 130, 145, .16); }
        [data-testid="stSidebar"] .block-container { padding-top: 2rem; }
        .product-mark { font-size: 1.25rem; font-weight: 700; letter-spacing: .01em; margin-bottom: 1.25rem; }
        .active-conversation { background: rgba(70, 90, 110, .11); border-radius: 7px; padding: .55rem .7rem; margin: .15rem 0; font-size: .9rem; }
        .sidebar-spacer { min-height: 12vh; }
        .user-bubble { background: #e8eef4; border-radius: 14px 14px 3px 14px; padding: .72rem .9rem; margin: .4rem 0 1.1rem auto; max-width: 40rem; width: fit-content; }
        .empty-state { text-align: center; padding: 15vh 1rem 8vh; color: #536170; }
        .empty-state h2 { color: #1d2a36; font-weight: 650; }
        [data-testid="stChatInput"] { padding-bottom: 1rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _init_state()
    top_k = _sidebar()
    conversation = _active_conversation()
    st.title("RAG Agent")
    _render_project_tag(st.session_state.project_identity)
    mode_labels = list(MODES)
    current_label = MODE_LABEL_BY_KEY.get(conversation.get("mode", "basic"), "Basic RAG")
    selected_label = st.radio(
        "Mode",
        mode_labels,
        index=mode_labels.index(current_label),
        horizontal=True,
        label_visibility="collapsed",
    )
    conversation["mode"] = MODE_KEY[selected_label]
    st.caption(MODES[selected_label])
    _tab_console(conversation["mode"], top_k)


if __name__ == "__main__":
    main()
