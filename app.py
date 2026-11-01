"""
羽毛球知识助手 · Web 界面

本地运行：
    .venv/Scripts/python.exe -m streamlit run app.py

部署到 Streamlit Community Cloud 时，需要在 Secrets 里配置：
    SILICONFLOW_API_KEY
    DEEPSEEK_API_KEY
    DEEPSEEK_BASE_URL
    DEEPSEEK_MODEL
"""

import os

# 必须在 import day3 之前设置：day3 在模块加载时就会读这两个变量决定语料目录和缓存名
os.environ.setdefault("RAG_DATA_DIR", "data_rules_only")
os.environ.setdefault("RAG_TAG", "rules")

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

from day3 import build_chunks, build_vectors
from day4 import build_context, generate, generate_stream, chat_extra
from hybrid import (bm25_search_idx, build_bm25, fuse_by_language,
                    vector_search_idx)

load_dotenv()

EMBED_KEY = os.getenv("SILICONFLOW_API_KEY", "").strip()
EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "https://api.siliconflow.cn/v1").strip()
CHAT_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
CHAT_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "").strip()
CHAT_MODEL = os.getenv("DEEPSEEK_MODEL", "").strip()

REWRITE_PROMPT = (
    "把用户的中文羽毛球问题，改写成 3 个不同的英文检索语句。"
    "每句用不同措辞，并且覆盖问题涉及的不同关键词——"
    "尤其是规则文档里可能出现的专业术语（如 toss / service / interval / fault）。"
    "每行一句，不要编号，不要解释，只输出 3 行英文。"
)

st.set_page_config(page_title="羽毛球知识助手", page_icon="🏸", layout="wide")


@st.cache_resource(show_spinner="正在加载语料索引…")
def load_index():
    """索引只加载一次，Streamlit 每次交互都会重跑脚本，不缓存会很慢"""
    chunks = build_chunks()
    embed_client = OpenAI(api_key=EMBED_KEY, base_url=EMBED_BASE_URL)
    vecs = build_vectors(chunks, embed_client)
    bm25 = build_bm25(chunks)
    return chunks, embed_client, vecs, bm25


def rewrite_queries(client, question: str) -> list[str]:
    """一次调用生成 3 个英文表述，吸收 LLM 输出的不确定性"""
    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": REWRITE_PROMPT},
            {"role": "user", "content": question},
        ],
        temperature=0,
        **chat_extra(),
    )
    raw = (resp.choices[0].message.content or "").strip()
    lines = []
    for ln in raw.split("\n"):
        ln = ln.strip().lstrip("0123456789.-、) ").strip()
        if ln and any(c.isalpha() for c in ln):
            lines.append(ln)
    return lines[:3] or [question]


def retrieve(question: str, top_k: int):
    """双语多路检索 + 两级 RRF 融合"""
    queries = rewrite_queries(chat_client, question)

    zh_lists = [
        vector_search_idx(embed_client, chunks, vecs, question, k=top_k),
        bm25_search_idx(bm25, chunks, question, k=top_k),
    ]
    en_lists = []
    for q in queries:
        en_lists.append(vector_search_idx(embed_client, chunks, vecs, q, k=top_k))
        en_lists.append(bm25_search_idx(bm25, chunks, q, k=top_k))

    fused = fuse_by_language(zh_lists, en_lists, top_n=top_k)
    return queries, [(score, chunks[idx]) for score, idx in fused]


# ---------------- 页面 ----------------

if not EMBED_KEY or not CHAT_KEY:
    st.error("缺少 API Key。请在 .env 里配置 SILICONFLOW_API_KEY 和 DEEPSEEK_API_KEY。")
    st.stop()

chunks, embed_client, vecs, bm25 = load_index()
chat_client = OpenAI(api_key=CHAT_KEY, base_url=CHAT_BASE_URL)

with st.sidebar:
    st.header("设置")
    top_k = st.slider("检索块数", min_value=3, max_value=10, value=5)
    show_debug = st.toggle("显示检索过程", value=True)

    st.divider()
    st.caption("语料构成")
    from collections import Counter
    counts = Counter(c.get("doc_type", "其他") for c in chunks)
    for dtype, n in counts.most_common():
        st.caption(f"· {dtype}：{n} 块")
    st.caption(f"合计 {len(chunks)} 块")

st.title("🏸 羽毛球知识助手")
st.caption("覆盖规则条文、技术动作、装备参数三类资料。回答会标注出处页码。")

with st.form("ask", clear_on_submit=False):
    question = st.text_input(
        "你的问题",
        placeholder="例如：反手高远球的击球点应该在身体哪个位置？",
    )
    submitted = st.form_submit_button("提问", type="primary")

if submitted and question.strip():
    question = question.strip()
    with st.spinner("检索中…"):
        queries, hits = retrieve(question, top_k)

    st.subheader("回答")
    usage: dict = {}
    # 模型是推理型，首字前有 3-5 秒思考期，用 spinner 覆盖这段空白
    with st.spinner("生成中…"):
        answer = st.write_stream(
            generate_stream(chat_client, question, build_context(hits), usage)
        )

    col1, col2, col3 = st.columns(3)
    col1.metric("检索块数", len(hits))
    col2.metric("token 消耗", usage.get("total_tokens") or "—")
    col3.metric("语料规模", f"{len(chunks)} 块")

    if show_debug:
        with st.expander("查看检索过程", expanded=False):
            st.markdown("**改写表述**")
            for i, q in enumerate(queries, 1):
                st.caption(f"{i}. {q}")

            st.markdown("**命中片段**")
            for score, c in hits:
                dtype = c.get("doc_type", "?")
                head = f"`{dtype}` 第 {c['page']} 页 · 融合分 {score:.4f}"
                st.markdown(head)
                st.caption(c["text"][:160].replace("\n", " "))
                st.divider()
