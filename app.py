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


def _load_glossary_line() -> str:
    """从语料抽出的章节术语，注入改写 prompt

    中文一词多义、表达发散，英文文档却是固定术语。
    不把术语喂给模型，它会自由翻译成 switch sides，而文档里只有 change ends。
    """
    import json
    from pathlib import Path

    f = Path(__file__).resolve().parent / "tools" / "glossary.json"
    if not f.exists():
        return ""
    terms = json.loads(f.read_text(encoding="utf-8")).get("chapters", [])
    # INTERVAL 是 Law 16.2 的子条款，不在章节标题里，手工补
    if "INTERVAL" not in terms:
        terms.append("INTERVAL")
    return " / ".join(terms)


GLOSSARY_LINE = _load_glossary_line()


def _load_term_map() -> dict:
    """中文说法 → 英文术语

    来源两部分：
      1. tools/term_map.json —— 从章节标题用 LLM 反向生成（覆盖章节级概念）
      2. MANUAL_TERMS —— 手工补子条款级概念（界内/间歇/网柱等，
         它们不是章节标题，自动生成覆盖不到）
    """
    import json
    from pathlib import Path

    auto = {}
    f = Path(__file__).resolve().parent / "tools" / "term_map.json"
    if f.exists():
        auto = json.loads(f.read_text(encoding="utf-8")).get("by_chinese", {})
    return {**auto, **MANUAL_TERMS}


# 子条款级概念：章节标题里没有，但用户经常问
MANUAL_TERMS = {
    "界内": ["on the line", "within the boundary"],
    "界外": ["lands outside the boundaries", "outside the boundary"],
    "出界": ["lands outside the boundaries", "outside the boundary"],
    "边线": ["boundary lines", "on the line"],   # 原文是复数 boundary lines
    "压线": ["on the line"],
    "间歇": ["interval"],
    "发球区": ["service court"],
    "重发": ["let"],
    "网柱": ["posts"],
    "中管": ["shaft"],
    "拍面": ["stringed area"],
    "高远球": ["clear"],
    "杀球": ["smash"],
    "吊球": ["drop shot"],
    "挑球": ["lift"],
    "搓球": ["net shot"],
    "平抽": ["drive"],
}

TERM_MAP = _load_term_map()


def term_queries(question: str) -> list[str]:
    """从中文问题里识别术语，直接给出可检索的英文词

    这是「硬约束」：中文词映射成文档术语，不经过 LLM 翻译。
    实测「球落在边线上算出界吗」走完整改写链路检索不到，
    但直接用 lands outside the boundaries 能命中块 27/469。
    """
    out: list[str] = []
    for zh, ens in TERM_MAP.items():
        if zh in question:
            out.extend(ens)
    return list(dict.fromkeys(out))[:4]      # 去重，最多 4 个

REWRITE_PROMPT = (
    "把用户的中文羽毛球问题，改写成 3 个不同的英文检索语句。\n\n"
    "【术语要求 —— 最重要】\n"
    "中文表达发散，同一个意思有多种说法；但 BWF 文档使用固定术语。\n"
    "必须使用下面的官方术语，不要自由翻译：\n"
    "  换边 → change ends（不是 switch sides / change sides）\n"
    "  间歇 → interval（不是 break）\n"
    "  发球区 → service court\n"
    "  违例 → fault    重发 → let    得分 → scoring\n"
    "  网柱 → posts    中管 → shaft   拍面 → stringed area\n"
    "  界内 → in       界外 → out     边线 → boundary line / on the line\n\n"
    "文档中的章节术语（改写时优先复用这些词）：\n"
    f"{GLOSSARY_LINE}\n\n"
    "【输出要求】\n"
    "每行一句，不要编号，不要解释，只输出 3 行英文。\n"
    "3 句措辞可以不同，但都必须落在上述官方术语上。"
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
        if ln and len(ln) >= 3 and any(c.isalpha() for c in ln):
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
        # 改写偶尔会返回空串或纯符号，embed_query 拿到空输入会返回形状不对的向量，
        # 后面 vecs @ q 直接崩。这里挡掉，宁可少一路也不要整条链路挂掉。
        if not q or not q.strip():
            continue
        en_lists.append(vector_search_idx(embed_client, chunks, vecs, q, k=pool))
        en_lists.append(bm25_search_idx(bm25, chunks, q, k=pool))

    # 术语直查：中文术语直接映射英文术语，绕开 LLM 翻译。
    # 单独成组参与融合——并进英文侧会被 6 路改写稀释掉。
    term_lists = [bm25_search_idx(bm25, chunks, tq, k=pool)
                  for tq in term_queries(question)]

    fused = fuse_by_language(zh_lists, en_lists, top_n=pool, term_hit_lists=term_lists)

    if RERANK_ENABLED and fused:
        idx_list = [idx for _, idx in fused]
        docs = [chunks[i]["text"] for i in idx_list]

        # 重排用中文原问。
        #
        # 试过两种增强，都不采用：
        #   双 query（中文 + 英文改写[0]）取最高：能修好「球落在边线上」，
        #       但英文改写每次措辞不同（considered out / count as out），
        #       同一题 3 次跑出 2 种结果，稳定性比单 query 差。
        #   多 query（中文 + 全部改写）取最高：3 次全部失败，且 4.77s/题。
        #       取 max 会把任何一条 query 给高分的块都顶上来，噪声也一起放大。
        #
        # 单 query 的已知缺陷：「球落在边线上算出界吗」这类题，rerank 会偏向
        # 中文块（wiki 的「出界情形」0.42），压掉英文精确答案（0.006）。
        # 这是 rerank 模型的语义判断偏差，不是架构问题——需要更强的模型，
        # 或者按语言分组重排（中文块用中文 query、英文块用英文 query），
        # 后者要解决跨语言分数不可比的问题，暂时不做。
        ranked = rerank_docs(question, docs, top_n=top_k)

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

# 把 Agent 需要的依赖挂到一个固定名字的模块上。
#
# 为什么不能靠 `import app`：项目有 pages/ 目录时，Streamlit 走 _mpa_v1 分支，
# page.run() 创建的 __main__ 模块**不注册进 sys.modules**，
# 于是 agent_tools 里 `sys.modules["__main__"]` 检查落空 → 回退 import app
# → 整个脚本被二次执行 → 侧边栏控件重复注册 → StreamlitDuplicateElementId。
# 主动挂一个 _rag_app 模块，路径与 Streamlit 的运行方式无关。
import sys as _sys
import types as _types

_shared = _sys.modules.get("_rag_app")
if _shared is None:
    _shared = _types.ModuleType("_rag_app")
    _sys.modules["_rag_app"] = _shared
_shared.chunks = chunks
_shared.retrieve = retrieve
_shared.chat_client = chat_client
_shared.build_context = build_context
_shared.generate = generate
_shared.generate_stream = generate_stream

# 每个浏览器会话一个 ID，用于按会话聚合日志（不记 IP）
if "sid" not in st.session_state:
    from tools.query_log import new_session_id
    st.session_state.sid = new_session_id()

with st.sidebar:
    st.header("设置")
    top_k = st.slider("检索块数", min_value=3, max_value=10, value=5, key="sb_top_k")
    show_debug = st.toggle("显示检索过程", value=True, key="sb_show_debug")

    st.divider()
    use_agent = st.toggle(
        "启用 Agent 路由",
        value=False,
        help="开启后先判断问题类型：问具体型号走数据库精确查询，问泛化问题走向量检索",
        key="sb_use_agent",
    )

    st.divider()
    st.caption("语料构成")
    from collections import Counter
    counts = Counter(c.get("doc_type", "其他") for c in chunks)
    for dtype, n in counts.most_common():
        st.caption(f"· {dtype}：{n} 块")
    st.caption(f"合计 {len(chunks)} 块")
    st.caption("装备库：34 款球拍")

    # 查询统计不在主页展示——那是所有用户提问的记录，只在 pages/1_admin.py
    # 里凭管理员密码查看，避免把别人的提问暴露给每个访客。

st.title("🏸 羽毛球知识助手")
st.caption("覆盖规则条文、技术动作、装备参数、裁判执行、赛事规程五类资料。回答会标注出处页码。")

with st.form("ask", clear_on_submit=False):
    question = st.text_input(
        "你的问题",
        placeholder="例如：反手高远球的击球点应该在身体哪个位置？",
        key="q_input",
    )
    submitted = st.form_submit_button("提问", type="primary", key="q_submit")

if submitted and question.strip():
    question = question.strip()
    import time

    from tools.query_log import log_query

    t_start = time.time()

    if use_agent:
        import agent_core

        # 决策循环：模型每轮看到已有观察，决定查什么 / 是否够了
        with st.spinner("Agent 思考中…"):
            steps, evidence = agent_core.gather(question)

        tool_steps = [s for s in steps if s["action"] != "answer"]
        with st.expander(f"Agent 执行过程（{len(tool_steps)} 次工具调用）", expanded=True):
            for i, s in enumerate(steps, 1):
                if s["action"] == "answer":
                    st.caption(f"{i}. **判断可以作答** — {s['summary']}")
                    continue
                args = s.get("args") or {}
                arg = args.get("model") or args.get("query") or ""
                st.caption(f"{i}. `{s['action']}`（{arg}） → {s['summary']}")

        st.subheader("回答")
        usage = {}
        with st.spinner("生成中…"):
            answer = st.write_stream(agent_core.stream_answer(question, evidence, usage))

        elapsed = int((time.time() - t_start) * 1000)
        route_str = "+".join(s["action"] for s in tool_steps) or "none"
        hit = bool(tool_steps) and "未收录型号" not in (evidence or "")
        log_query(question, "agent", route_str, answer, elapsed,
                  usage.get("total_tokens"), hit, st.session_state.sid)

        col1, col2, col3 = st.columns(3)
        col1.metric("工具调用", len(tool_steps))
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
