"""
批量评测：自动跑 10 题，算 Recall@5。

它做什么：
    对每道题 → 改写 → 向量检索 + BM25 检索 → RRF 融合 → 生成回答
    自动判断「期望的块有没有进 top5」，最后汇总命中率。

它不做什么：
    「回答对不对」还是要你自己判断。脚本只负责检索层的指标。

跑法（CMD）：
    cd /d F:/WorkPlace/Python/badminton-rag
    .venv/Scripts/python.exe run_eval.py
"""

import os

from dotenv import load_dotenv
from openai import OpenAI

from index_builder import build_chunks, build_vectors
from answer_generator import build_context, chat_extra, generate
from hybrid import (bm25_search_idx, build_bm25, fuse_by_language,
                    rrf_fuse, vector_search_idx)

load_dotenv()

TOP_K = 5
# 只跑前 N 题：仅规则语料时用 RAG_EVAL_LIMIT=9 跳过 #10（它必须靠 itto）
LIMIT = int(os.getenv("RAG_EVAL_LIMIT", "10"))
CHAT_MODEL = os.getenv("DEEPSEEK_MODEL", "").strip()
CHAT_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "").strip()

# (问题, 期望出处列表)。出处 = (文件, 页码, 关键词)
# 判定要求三件事同时成立：文件名对、页码 ±1、文本含关键词
# 为什么要关键词：一页有 2-3 个块，只比页码会把页眉块也算成命中
EVAL_SET = [
    # ---- 规则类（4 题，全部换了新问法，不与旧题重复）----
    ("单打发球方得分为 0 时，从哪个发球区发球？",
     [("badminton_rules.pdf", 6, "respective right"),
      ("wiki_badminton_zh.txt", 1, "偶数")]),
    ("一局比赛中，60 秒的间歇出现在什么时候？",
     [("badminton_rules.pdf", 10, "60 seconds")]),
    ("网柱应该放在哪条线上？",
     [("badminton_rules.pdf", 1, "doubles side lines")]),
    ("什么情况下判发球区错误？",
     [("badminton_rules.pdf", 8, "out of turn")]),

    # ---- 技术教学类（3 题，考中文技术文档）----
    ("反手高远球的击球点应该在身体哪个位置？",
     [("tech_high_clear.txt", 1, "右前上方"),
      ("tech_high_clear.txt", 1, "右肩上方")]),
    ("正手高远球最容易犯的错误有哪些？",
     [("tech_high_clear.txt", 1, "击球点选择不当")]),
    ("头顶高远球和反手高远球的主要区别是什么？",
     [("tech_high_clear.txt", 1, "主动")]),

    # ---- 装备参数类（2 题，考数值型知识）----
    ("4U 规格的球拍建议拉多少磅？",
     [("gear_rackets.txt", 1, "20-28")]),
    ("球拍的中管硬度分哪几档？",
     [("gear_rackets.txt", 1, "Extra Stiff")]),

    # ---- 数值 / 跨文档（1 题）----
    ("标准羽毛球的重量范围和羽毛长度是多少？",
     [("badminton_rules.pdf", 2, "4.74"),
      ("wiki_badminton_zh.txt", 1, "4.74")]),
]

REWRITE_PROMPT = (
    "把用户的中文羽毛球规则问题，改写成 3 个不同的英文检索语句。"
    "每句用不同措辞，并且覆盖问题涉及的不同关键词——"
    "尤其是规则文档里可能出现的专业术语（如 toss / service / interval / fault）。"
    "每行一句，不要编号，不要解释，只输出 3 行英文。"
)

SYSTEM_PROMPT = (
    "你是羽毛球规则助手。只根据用户提供的资料回答，"
    "资料里没有就说不知道，不要编。回答时注明来自第几页。"
)


def rewrite(chat_client, question: str) -> list[str]:
    """
    一次调用生成 3 个不同表述。

    为什么要多个：实测同一个问题连跑 5 次，改写输出有 3 次带 toss、2 次不带，
    导致检索结果在 7/9 到 9/9 之间摆动。单个表述不可靠，用 3 个覆盖不确定性。
    注意是「一次调用输出 3 行」，不是调 3 次——成本只多几行输出 token。
    """
    resp = chat_client.chat.completions.create(
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


def is_hit(hits, expected) -> bool:
    """
    判定命中：top5 里有一块，文件名对 + 页码 ±1 + 文本含关键词，三者同时成立。

    为什么不能只看页码：一页有 2-3 个块，页眉块也算「第 N 页」，
    会把完全无关的内容判成命中（之前 9/10 里有 4 个就是这么来的）。
    """
    for _, idx in hits:
        c = chunks[idx]
        text_lower = c["text"].lower()
        for fname, page, keyword in expected:
            if (c["source"] == fname
                    and abs(c["page"] - page) <= 1
                    and keyword.lower() in text_lower):
                return True
    return False


def diagnose(hits, expected) -> str:
    """没命中时，说清楚是页码没到还是内容不对"""
    for _, idx in hits:
        c = chunks[idx]
        for fname, page, keyword in expected:
            if c["source"] == fname and abs(c["page"] - page) <= 1:
                return f"页码到了（{fname} 第{page}页），但块里没有「{keyword}」"
    return "top5 里没有期望的文件和页码"


def main() -> None:
    global chunks

    chunks = build_chunks()
    embed_client = OpenAI(
        api_key=os.getenv("SILICONFLOW_API_KEY", "").strip(),
        base_url=os.getenv("EMBED_BASE_URL", "https://api.siliconflow.cn/v1").strip(),
    )
    chat_client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        base_url=CHAT_BASE_URL,
    )

    vecs = build_vectors(chunks, embed_client)
    bm25 = build_bm25(chunks)

    subset = EVAL_SET[:LIMIT]
    print(f"\n共 {len(chunks)} 块，{len(subset)} 道题\n" + "=" * 62)

    hit_count = 0
    details = []

    for i, (question, expected) in enumerate(subset, 1):
        print(f"\n[{i}/{len(subset)}] {question}")
        try:
            queries = rewrite(chat_client, question)
            for i, q in enumerate(queries, 1):
                print(f"  改写{i}: {q}")

            # 中文侧：向量 + BM25（jieba 分词）
            zh_lists = [
                vector_search_idx(embed_client, chunks, vecs, question, k=TOP_K),
                bm25_search_idx(bm25, chunks, question, k=TOP_K),
            ]
            # 英文侧：每个改写表述各走向量 + BM25
            en_lists = []
            for q in queries:
                en_lists.append(vector_search_idx(embed_client, chunks, vecs, q, k=TOP_K))
                en_lists.append(bm25_search_idx(bm25, chunks, q, k=TOP_K))

            fused = fuse_by_language(zh_lists, en_lists, top_n=TOP_K)

            hit = is_hit(fused, expected)
            hit_count += hit
            details.append((question, hit))

            print(f"  {'✅ 命中' if hit else '❌ 未命中'}")
            for _, idx in fused:
                c = chunks[idx]
                text_lower = c["text"].lower()
                has_kw = any(k.lower() in text_lower for _, _, k in expected)
                flag = "[含关键词]" if has_kw else "[  无   ]"
                dtype = c.get("doc_type", "?")
                print(f"     {flag} {dtype} 第{c['page']:>2}页 "
                      f"{c['text'][:44].replace(chr(10), ' ')}")
            if not hit:
                print(f"     → {diagnose(fused, expected)}")

            # 生成回答，供人工判断准确率（脚本不判对错，只给素材）
            hits = [(score, chunks[idx]) for score, idx in fused]
            answer, tokens = generate(chat_client, question, build_context(hits))
            print(f"  回答: {answer.replace(chr(10), ' ')[:300]}")
            print(f"  ({tokens} token)")
        except Exception as e:
            print(f"  ⚠️ 出错: {type(e).__name__}: {e}")
            details.append((question, False))

    print("\n" + "=" * 62)
    print(f"Recall@{TOP_K}: {hit_count}/{len(subset)}"
          f"  ({hit_count / len(subset) * 100:.0f}%)")
    print("\n未命中的题：")
    for q, hit in details:
        if not hit:
            print(f"  - {q}")


if __name__ == "__main__":
    main()
