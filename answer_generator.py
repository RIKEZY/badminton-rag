"""
上下文拼装与答案生成

把检索到的块拼成上下文，交给模型生成答案；带出处（文件名 + 页码），
流式输出并统计 token。

相对「整份文档直接塞给模型」的差别：
    整份文档   14 万字符 → 38,607 token
    top5 检索  约 1000 字符 → 约 400 token

运行：
    python answer_generator.py
"""
from hybrid import (bm25_search_idx, build_bm25, fuse_by_language,
                    rrf_fuse, vector_search_idx)
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

from index_builder import build_chunks, build_vectors, search

load_dotenv()

EMBED_KEY = os.getenv("SILICONFLOW_API_KEY", "").strip()
EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "https://api.siliconflow.cn/v1").strip()
CHAT_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
CHAT_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
CHAT_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()

# 推理型模型（如硅基流动的 DeepSeek-V4-Flash）默认会先"思考"再回答，
# 在 RAG 场景下这段思考对答案没有贡献，却要多等 3-4 秒。
# 置 true 可关闭（仅部分供应商支持该参数；官方 deepseek-chat 本身不思考，设了也无害）。
DISABLE_THINKING = os.getenv("CHAT_DISABLE_THINKING", "").strip().lower() in ("1", "true", "yes")


def chat_extra() -> dict:
    """返回额外的请求参数；不关闭思考时是空字典，可直接 ** 展开"""
    return {"extra_body": {"enable_thinking": False}} if DISABLE_THINKING else {}

TOP_K = 5


# ============================================================ 你要写的第 1 个

def build_context(hits: list[tuple[float, dict]]) -> str:
    """
    把检索结果拼成一段文字，交给模型当资料。

    hits 长这样：[ (0.719, {"source": "badminton_rules.pdf", "page": 5, "text": "..."}), ... ]

    提示：
    - 每一块前面加上来源标记，格式自己定，比如 [资料1 | badminton_rules.pdf 第5页]
      这样模型回答时能引用，生成阶段要用
    - 块之间用空行隔开，别黏成一坨
    - 返回值是一整个字符串

    验收：打印出来能看出"哪句话来自哪个文件第几页"
    """
    # TODO: 在这里写
    context = ""
    for i, (score, hit) in enumerate(hits, 1):
        string = f"[资料{i} | {hit['source']} 第{hit['page']}页]\n{hit['text']}\n\n"

        context += string
    return context


# ============================================================ 你要写的第 2 个

def generate(chat_client: OpenAI, question: str, context: str) -> tuple[str, int]:
    """
    调 DeepSeek，让它只根据 context 回答问题。

    返回 (回答文字, 消耗的 token 数)

    提示：
    - 参考 examples/minimal_demo.py 里 client.chat.completions.create 的写法
    - system 消息里要约束：只根据资料回答，资料里没有就说不知道
    - 温度设 0，减少胡编
    - 返回值里 resp.usage.total_tokens 就是 token 数

    验收：问一个资料里没有的问题，它应该说"不知道"而不是编一个
    """
    # TODO: 在这里写

    resp = chat_client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {
                "role": "system",
                "content": "你是羽毛球规则助手。只根据用户提供的资料回答，"
                           "资料里没有就说不知道，不要编。回答时注明来自第几页。",
            },
            {"role": "user", "content": f"资料：\n{context}\n\n问题：{question}"},
        ],
        temperature=0,
        **chat_extra(),
    )
    return resp.choices[0].message.content, resp.usage.total_tokens


def generate_stream(chat_client: OpenAI, question: str, context: str,
                    usage_out: dict | None = None, system_prompt: str | None = None):
    """
    流式版本：逐段 yield 文字，供 st.write_stream 消费。

    与 generate() 的区别只在传输方式——模型生成的顺序和内容不变，
    但前端可以边收边渲染，用户不用盯着转圈等 3-5 秒。

    如果服务端支持 stream_options 里的 include_usage，
    最后一个 chunk 会带 usage，写进 usage_out 供调用方取用。
    兼容层不支持时会自动退回不带 usage 的流，不会报错。
    """
    kwargs = dict(
        model=CHAT_MODEL,
        messages=[
            {
                "role": "system",
                "content": system_prompt or (
                    "你是羽毛球规则助手。只根据用户提供的资料回答，"
                    "资料里没有就说不知道，不要编。回答时注明来自第几页。"
                ),
            },
            {"role": "user", "content": f"资料：\n{context}\n\n问题：{question}"},
        ],
        temperature=0,
        stream=True,
        **chat_extra(),
    )

    try:
        stream = chat_client.chat.completions.create(
            **kwargs, stream_options={"include_usage": True}
        )
    except Exception:
        stream = chat_client.chat.completions.create(**kwargs)

    for chunk in stream:
        usage = getattr(chunk, "usage", None)
        if usage and usage_out is not None:
            usage_out["total_tokens"] = usage.total_tokens
        if chunk.choices:
            piece = chunk.choices[0].delta.content
            if piece:
                yield piece


# ============================================================ 下面的不用改

def main() -> None:
    if not EMBED_KEY:
        sys.exit("缺少 SILICONFLOW_API_KEY")
    if not CHAT_KEY:
        sys.exit("缺少 DEEPSEEK_API_KEY")

    embed_client = OpenAI(api_key=EMBED_KEY, base_url=EMBED_BASE_URL)
    chat_client = OpenAI(api_key=CHAT_KEY, base_url=CHAT_BASE_URL)

    #切块
    chunks = build_chunks()
    #将切块向量化 创建向量缓存
    vecs = build_vectors(chunks, embed_client)

    #进行bm25创建索引
    bm25 = build_bm25(chunks)

    print("\n" + "=" * 60)
    print(f"检索 {TOP_K} 块 → 交给 DeepSeek 回答。输入 q 退出。")
    print("=" * 60)

    while True:
        try:
            question = input("\n问题> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question.lower() == "q":
            break

        #输入问题，将中文转为英文
        resp_zh_to_en = chat_client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": """
# Role
你是一个世界羽联（BWF）的资深双语裁判，同时也是 RAG 系统的跨语言检索词生成器。

# Task
用户会输入关于羽毛球规则的中文问题。你需要将这句话**原原本本地直译为英文**。
不要精简句子结构，不要提取关键词，保留原句的疑问语气和所有修饰成分。
你唯一需要干预的是：**将中文里口语化的表达和特殊专有名词，强制替换为世界羽联（BWF）官方规则的标准英文术语。**

# Constraints
1. 必须使用 BWF 官方术语（如：发球违例->service fault，脚踩线->foot fault，界外球->out，过网击球->over the net，偷后场->deceptive serve，换发球->change of service 等）。
2. 如果遇到没有官方对应词的中文俚语（如“接杀”、“放网”），请用最贴近规则描述的直白英文翻译（如 "receive smash", "net shot"），务必让英文读者能看懂这个动作。
3. 翻译要连贯，不要变成生硬的单词堆砌，要像真正的英文裁判在提问一样。
4. 只输出翻译后的英文问句，不要输出任何解释、前缀或标点符号以外的内容，绝对不要包含中文。

# Examples
用户输入：单打发球的时候我可以跳起来发吗？
输出：Can I jump off the ground when serving in singles?

用户输入：杀球的时候球拍碰到网算犯规吗？
输出：Is it a fault if my racket touches the net during a smash?

用户输入：球打在边线上算界内还是界外？
输出：Is the shuttlecock in or out if it lands on the boundary line?

用户输入：双打偷后场发球有什么规定？
输出：What are the rules for a deceptive serve to the back boundary in doubles?

# Initialization
请等待用户输入中文问题，然后严格执行直译与术语替换任务。

# Output
输出 3 行，每行一个不同的英文检索表述。用不同措辞，覆盖问题涉及的不同关键词。
不要编号，不要解释，只输出 3 行英文。""",
                },
                {"role": "user", "content": question},
            ],
            temperature=0,
        )
        raw_en = (resp_zh_to_en.choices[0].message.content or "").strip()
        queries = []
        for ln in raw_en.split("\n"):
            ln = ln.strip().lstrip("0123456789.-、) ").strip()
            if ln and any(c.isalpha() for c in ln):
                queries.append(ln)
        queries = queries[:3] or [question]
        for i, q in enumerate(queries, 1):
            print(f"  改写{i}> {q}")

        #纯向量检索
        # hits = search(embed_client, chunks, vecs, translated_question, top_k=TOP_K)

        #加入rrf融合 向量+bm25
        # 双语四路检索：中英各走向量 + BM25，两级 RRF 融合
        zh_lists = [
            vector_search_idx(embed_client, chunks, vecs, question, k=TOP_K),
            bm25_search_idx(bm25, chunks, question, k=TOP_K),
        ]
        en_lists = []
        for q in queries:
            en_lists.append(vector_search_idx(embed_client, chunks, vecs, q, k=TOP_K))
            en_lists.append(bm25_search_idx(bm25, chunks, q, k=TOP_K))
        fused = fuse_by_language(zh_lists, en_lists, top_n=TOP_K)

        hits = [(score, chunks[idx]) for score, idx in fused]


        print(f"\n检索到 {len(hits)} 块：")
        for score, c in hits:
            print(f"  {score:.3f}  {c['source']} 第{c['page']}页  "
                  f"{c['text'][:40].replace(chr(10), ' ')}...")

        context = build_context(hits)
        print(f"\n上下文长度：{len(context)} 字符")

        answer, tokens = generate(chat_client, question, context)
        print(f"\n回答：\n{answer}")
        print(f"\n（本次 {tokens} token）")


if __name__ == "__main__":
    main()
