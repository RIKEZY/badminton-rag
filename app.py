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
# v2 = 含 BWF 官方文档的 649 块语料（rules = 旧的 82 块，保留供对照）
os.environ.setdefault("RAG_DATA_DIR", "data_rules_only")
os.environ.setdefault("RAG_TAG", "v2")

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

# Cross-encoder 重排：融合后多取候选，重排再截断
RERANK_ENABLED = os.getenv("RAG_RERANK", "").strip().lower() in ("1", "true", "yes")
RERANK_POOL = int(os.getenv("RERANK_POOL", "20"))
from rerank import rerank as rerank_docs

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
    """双语多路检索 + 两级 RRF 融合（可选 cross-encoder 重排）"""
    queries = rewrite_queries(chat_client, question)

    # 开了重排就多召回一些候选，给 reranker 留出重排空间
    pool = RERANK_POOL if RERANK_ENABLED else top_k

    zh_lists = [
        vector_search_idx(embed_client, chunks, vecs, question, k=pool),
        bm25_search_idx(bm25, chunks, question, k=pool),
    ]
    en_lists = []
    for q in queries:
        en_lists.append(vector_search_idx(embed_client, chunks, vecs, q, k=pool))
        en_lists.append(bm25_search_idx(bm25, chunks, q, k=pool))

    fused = fuse_by_language(zh_lists, en_lists, top_n=pool)

    if RERANK_ENABLED and fused:
        idx_list = [idx for _, idx in fused]
        ranked = rerank_docs(question, [chunks[i]["text"] for i in idx_list], top_n=top_k)
        if ranked:
            return queries, [(score, chunks[idx_list[i]]) for i, score in ranked]
        # 重排失败就退回原顺序，不中断流程

    return queries, [(score, chunks[idx]) for score, idx in fused[:top_k]]


# ---------------- 页面 ----------------

if not EMBED_KEY or not CHAT_KEY:
    st.error("缺少 API Key。请在 .env 里配置 SILICONFLOW_API_KEY 和 DEEPSEEK_API_KEY。")
    st.stop()

chunks, embed_client, vecs, bm25 = load_index()
chat_client = OpenAI(api_key=CHAT_KEY, base_url=CHAT_BASE_URL)

# 每个浏览器会话一个 ID，用于按会话聚合日志（不记 IP）
if "sid" not in st.session_state:
    from tools.query_log import new_session_id
    st.session_state.sid = new_session_id()

with st.sidebar:
    st.header("设置")
    top_k = st.slider("检索块数", min_value=3, max_value=10, value=5)
    show_debug = st.toggle("显示检索过程", value=True)

    st.divider()
    use_agent = st.toggle(
        "启用 Agent 路由",
        value=False,
        help="开启后先判断问题类型：问具体型号走数据库精确查询，问泛化问题走向量检索",
    )

    st.divider()
    st.caption("语料构成")
    from collections import Counter
    counts = Counter(c.get("doc_type", "其他") for c in chunks)
    for dtype, n in counts.most_common():
        st.caption(f"· {dtype}：{n} 块")
    st.caption(f"合计 {len(chunks)} 块")
    st.caption("装备库：34 款球拍")

    st.divider()
    with st.expander("📋 查询统计", expanded=False):
        from tools.query_log import recent, stats

        s = stats()
        st.caption(f"总提问 {s['total']} 次 · 今日 {s['today']} 次 · 会话 {s['sessions']} 个")
        if s["routes"]:
            st.caption("**路由分布**")
            for r, c in s["routes"][:5]:
                st.caption(f"· {r or '-'}：{c}")
        if s["top_questions"]:
            st.caption("**高频问题**")
            for q, c in s["top_questions"][:3]:
                st.caption(f"· {c}× {q[:24]}")
        if s["total"]:
            st.caption("**最近提问**")
            for r in recent(5):
                mark = "" if r["hit"] else " ⚠️未命中"
                st.caption(f"· {r['ts'][11:16]} `{r['route'][:16]}` "
                           f"{r['question'][:22]}{mark}")

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
    import time

    from tools.query_log import log_query

    t_start = time.time()

    if use_agent:
        import agent_core

        with st.spinner("判断问题类型…"):
            calls = agent_core.route(question)

        desc = " + ".join(
            f"`{c['tool']}`（{(c.get('args') or {}).get('model') or (c.get('args') or {}).get('query') or ''}）"
            for c in calls
        )
        st.caption(f"Agent 路由：{desc}")

        st.subheader("回答")
        usage = {}
        with st.spinner("执行中…"):
            answer = st.write_stream(agent_core.run_stream(question, calls, usage))

        elapsed = int((time.time() - t_start) * 1000)
        route_str = "+".join(c["tool"] for c in calls)
        hit = "没有找到型号" not in (answer or "")
        log_query(question, "agent", route_str, answer, elapsed,
                  usage.get("total_tokens"), hit, st.session_state.sid)

        col1, col2, col3 = st.columns(3)
        col1.metric("工具调用", len(calls))
        col2.metric("token 消耗", usage.get("total_tokens") or "—")
        col3.metric("耗时", f"{elapsed} ms")

    else:
        with st.spinner("检索中…"):
            queries, hits = retrieve(question, top_k)

        st.subheader("回答")
        usage = {}
        with st.spinner("生成中…"):
            answer = st.write_stream(
                generate_stream(chat_client, question, build_context(hits), usage)
            )

        elapsed = int((time.time() - t_start) * 1000)
        log_query(question, "v1", "search_docs", answer, elapsed,
                  usage.get("total_tokens"), True, st.session_state.sid)

        col1, col2, col3 = st.columns(3)
        col1.metric("检索块数", len(hits))
        col2.metric("token 消耗", usage.get("total_tokens") or "—")
        col3.metric("耗时", f"{elapsed} ms")

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
