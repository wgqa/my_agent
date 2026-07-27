import streamlit as st
import requests
from pathlib import Path

API_URL = "http://localhost:8000"

st.set_page_config(
    page_title="RAG 知识库",
    page_icon="📚",
    layout="wide",
)

# ── 初始化 session state ──
if "messages" not in st.session_state:
    st.session_state.messages = []
if "api_url" not in st.session_state:
    st.session_state.api_url = API_URL


def api_base() -> str:
    return st.session_state.api_url


def call_health() -> dict | None:
    try:
        r = requests.get(f"{api_base()}/health", timeout=5)
        return r.json() if r.ok else None
    except Exception:
        return None


def call_stats() -> dict | None:
    try:
        r = requests.get(f"{api_base()}/stats", timeout=5)
        return r.json() if r.ok else None
    except Exception:
        return None


def call_index(file_bytes: bytes, filename: str) -> dict | None:
    try:
        r = requests.post(
            f"{api_base()}/index/file",
            files={"file": (filename, file_bytes)},
            timeout=60,
        )
        return r.json() if r.ok else {"error": r.text}
    except Exception as e:
        return {"error": str(e)}


def call_query(question: str, top_k: int) -> dict | None:
    try:
        r = requests.post(
            f"{api_base()}/query",
            json={"question": question, "top_k": top_k},
            timeout=120,
        )
        return r.json() if r.ok else {"error": r.text}
    except Exception as e:
        return {"error": str(e)}


# ── 侧边栏 ──
with st.sidebar:
    st.title("⚙️ 设置")
    st.text_input("API 地址", value=api_base(), key="api_url")

    st.divider()
    health = call_health()
    if health:
        st.success(f"✅ 服务正常  |  文档数: {health['docs_count']}")
        st.caption(
            f"Embedding: {health['embedding_provider']}  |  "
            f"检索: {health['retriever_strategy']}  |  "
            f"生成: {health['generator_provider']}"
        )
    else:
        st.error("❌ 服务不可用 — 请确认 API 已启动")

    st.divider()
    top_k = st.slider("检索数量 (top_k)", min_value=1, max_value=10, value=5)
    st.caption("知识库文件:")
    st.code(".txt  .md  .pdf  .py  .js  .java")

# ── 主界面 ──
st.title("📚 RAG 知识库问答系统")

tab_index, tab_query = st.tabs(["📥 知识库管理", "💬 问答"])

# ════════════════════════════════════════
# Tab 1: 知识库管理
# ════════════════════════════════════════
with tab_index:
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("上传文件")
        uploaded_file = st.file_uploader(
            "选择文件上传到知识库",
            type=["txt", "md", "pdf", "py", "js", "java"],
        )

        if uploaded_file is not None:
            with st.spinner(f"正在索引 {uploaded_file.name}..."):
                result = call_index(uploaded_file.getvalue(), uploaded_file.name)
            if result:
                if "error" in result:
                    st.error(f"索引失败: {result['error']}")
                else:
                    st.success(
                        f"✅ {result['file_name']} 索引完成 — "
                        f"生成 {result['chunks']} 个块"
                    )
            else:
                st.error("索引失败: API 无响应")

    with col2:
        st.subheader("知识库状态")
        stats = call_stats()
        if stats:
            st.metric("文档块总数", stats.get("documents_count", 0))
            with st.expander("当前配置"):
                st.json(stats.get("config", {}))
        else:
            st.info("无法获取知识库状态")

# ════════════════════════════════════════
# Tab 2: 问答
# ════════════════════════════════════════
with tab_query:
    # 显示对话历史
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if "sources" in msg:
                with st.expander(f"📎 来源 ({len(msg['sources'])} 个)"):
                    for i, src in enumerate(msg["sources"]):
                        st.markdown(
                            f"**#{i+1}** — 来源: `{src['source']}`  "
                            f"(score: {src['score']:.3f})"
                        )
                        st.text(src["content"])

    # 输入框
    if prompt := st.chat_input("输入你的问题..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("思考中..."):
                result = call_query(prompt, top_k)

            if result and "error" not in result:
                answer = result["answer"]
                sources = result.get("sources", [])
                st.markdown(answer)
                if sources:
                    with st.expander(f"📎 来源 ({len(sources)} 个)"):
                        for i, src in enumerate(sources):
                            st.markdown(
                                f"**#{i+1}** — `{src['source']}`  "
                                f"(score: {src['score']:.3f})"
                            )
                            st.text(src["content"])
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer,
                    "sources": sources,
                })
            else:
                err_msg = result.get("error", "API 无响应") if result else "API 无响应"
                st.error(f"查询失败: {err_msg}")
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"❌ {err_msg}",
                })

    # 清空对话按钮
    if st.session_state.messages:
        if st.button("清空对话"):
            st.session_state.messages = []
            st.rerun()
