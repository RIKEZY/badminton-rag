"""
结构感知切块：按 BWF 规则的条款编号切，而不是按字符数切。

为什么这样切：
    按字符切会切在句子中间（he side having...），还会把页眉、多个条款混进同一块。
    按条款切，每条规则独立成块，边界天然干净。

层级前缀：
    9.1.6 单独看只有一句话「整个球必须低于 1.15 米」——低于什么的 1.15 米？它自己没说。
    所以给每块拼上所属章节标题：[Law 9 SERVICE] 9.1.6. the whole shuttle...
    前缀来自文档原文，不是模型生成的，一个字都不会丢。
"""

import re

# 章节标题：9. SERVICE / 16. CONTINUOUS PLAY, MISCONDUCT & PENALTIES
# 要求：行首数字 + 句点 + 空格 + 全大写标题 + 行尾
CHAPTER_RE = re.compile(r"^\s*(\d{1,2})\.\s+([A-Z][A-Z0-9 ,&'\-()/]+?)\s*$")

# 条款编号：9.1.6. / 11.4.2. / 9.1.
# 要求：至少两级编号（避免把 "9." 这种章节标题也当成条款），且以句点+空格结尾
CLAUSE_RE = re.compile(r"^\s*(\d+(?:\.\d+)+)\.\s+")

DEFINITIONS_RE = re.compile(r"^\s*DEFINITIONS\s*$")


def split_page_by_clause(text: str, page: int, source: str) -> list[dict]:
    """
    把一页文本按条款切成若干块。

    返回 [{"source", "page", "clause", "chapter", "text"}, ...]
    """
    lines = text.split("\n")
    chunks: list[dict] = []

    chapter_no = ""
    chapter_title = ""
    clause = ""          # 当前条款编号，空表示还没进入编号区
    buf: list[str] = []  # 当前块累积的行
    in_definitions = False

    def flush():
        """把缓冲区收尾成一块"""
        nonlocal buf
        body = "\n".join(buf).strip()
        if body:
            chunks.append({
                "source": source,
                "page": page,
                "clause": clause,
                "chapter": f"{chapter_no}. {chapter_title}".strip(". ") if chapter_title else "",
                "text": body,
            })
        buf = []

    for line in lines:
        # ---- 章节标题行 ----
        m_ch = CHAPTER_RE.match(line)
        if m_ch:
            flush()
            chapter_no, chapter_title = m_ch.group(1), m_ch.group(2)
            clause = ""
            in_definitions = False
            continue

        # ---- DEFINITIONS 区（没有编号，按行切）----
        if DEFINITIONS_RE.match(line):
            flush()
            in_definitions = True
            clause = "DEFINITIONS"
            continue

        # ---- 条款编号行 ----
        m_cl = CLAUSE_RE.match(line)
        if m_cl:
            flush()
            in_definitions = False
            clause = m_cl.group(1)
            buf = [line]
            continue

        # ---- 普通正文行 ----
        if in_definitions:
            # 术语定义：每行一个术语，单独成块
            stripped = line.strip()
            if not stripped:
                continue
            if buf and not re.match(r"^[A-Z][a-zA-Z' ]{2,30}\s+\S", stripped):
                # 续行（上一行定义的延续）
                buf.append(stripped)
            else:
                flush()
                buf = [stripped]
        else:
            if clause:
                buf.append(line)
            else:
                # 章节引言（如 9. SERVICE 后面的总述段落）
                if line.strip():
                    buf.append(line)

    flush()
    return chunks


def add_prefix(chunk: dict) -> dict:
    """给块加上层级前缀，便于检索时理解上下文"""
    parts = []
    if chunk["chapter"]:
        parts.append(f"Law {chunk['chapter']}")
    if chunk["clause"] and chunk["clause"] != "DEFINITIONS":
        parts.append(chunk["clause"])

    prefix = f"[{' > '.join(parts)}] " if parts else ""
    chunk = dict(chunk)
    chunk["text"] = prefix + chunk["text"]
    chunk["prefix"] = prefix
    return chunk


def _parent(clause: str) -> str:
    """9.1.6 → 9.1；9.1 → 9.1；DEFINITIONS → DEFINITIONS"""
    if not clause or clause == "DEFINITIONS":
        return clause
    parts = clause.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else clause


def merge_siblings(chunks: list[dict], max_len: int = 1200) -> list[dict]:
    """
    把同页、同父级、合起来不超过 max_len 的相邻块合并。

    为什么：9.1 是总述，9.1.1~9.1.8 是它的细则，分开检索会丢上下文。
    一条「neither side shall cause undue delay」单独成块，模型根本不知道在说什么场景。

    但 DEFINITIONS 区不合并：每个术语是独立语义单元，
    合起来会重演「8 个定义挤一块、Rally 被稀释」的老问题。

    引言的归属：
        Law 6/7/14 的编号在 PDF 排版时丢了，只有子项有编号（14.2.1 等）。
        所以「It shall be a let, if:」这句的 clause 是空的，按父级比较永远匹配不上。
        这里用 `or not prev_parent` 让引言块跟着后面的条款走，
        否则会出现「话说到一半」的块——模型看到 `if:` 却没有条件列表。
    """
    out: list[dict] = []
    for c in chunks:
        if out:
            prev = out[-1]
            is_def = prev["clause"] == "DEFINITIONS" or c["clause"] == "DEFINITIONS"
            prev_parent = _parent(prev["clause"])
            curr_parent = _parent(c["clause"])
            same_parent = prev_parent == curr_parent or not prev_parent
            fits = len(prev["text"]) + len(c["text"]) <= max_len
            # 不再限制同页：Law 14 的 14.2.1 在第9页、14.2.7 在第10页，
            # 卡同页会让「let 的条件」永远说不全。跨页后页码记起始页。
            if not is_def and same_parent and fits:
                prev["text"] = prev["text"] + "\n" + c["text"]
                if len(c["clause"].split(".")) < len(prev["clause"].split(".")):
                    prev["clause"] = c["clause"]
                continue
        out.append(dict(c))
    return out


def split_by_paragraph(pages: list[tuple[int, str]], source: str, max_len: int = 800) -> list[dict]:
    """
    没有条款编号的文档（百科、教学文章）按段落切。

    为什么需要回退：结构感知切块依赖「条款编号」这个标记。
    维基百科这类文档没有编号，硬用条款逻辑会把整篇切成一块（几万字）。
    按空行分段是这类文档唯一可靠的结构信号。
    """
    out: list[dict] = []
    for page_no, text in pages:
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

        # 把过短的段落（章节标题行，如「三、装备参数」）并到下一段，
        # 否则会切出一堆纯标题块，检索时全是噪声。
        # 阈值 50 是试出来的：30 时「一、YONEX ASTROX 100ZZ（天斧系列 · 进攻型）」这种
        # 32-38 字的型号标题仍会单独成块，导致型号名和参数分离。
        merged: list[str] = []
        buf = ""
        for p in paras:
            if len(p) < 50:
                buf += p + "\n"
            else:
                merged.append((buf + p).strip())
                buf = ""
        if buf:
            merged.append(buf.strip())

        for para in merged:
            if len(para) <= max_len:
                out.append({"source": source, "page": page_no,
                            "clause": "", "chapter": "", "text": para})
            else:
                # 段落本身超长，再按字符切
                step = max_len - 100
                for start in range(0, len(para), step):
                    piece = para[start:start + max_len].strip()
                    if piece:
                        out.append({"source": source, "page": page_no,
                                    "clause": "", "chapter": "", "text": piece})
    return out


def guess_doc_type(source: str) -> str:
    """
    按文件名推断文档类型。

    为什么需要：现在语料里混了规则、技术教学、装备参数、百科四类，
    检索时如果不标注来源类型，就看不出「技术问题是否命中了技术块」。
    这个字段只用于观测，不影响检索逻辑。
    """
    low = source.lower()
    if "itto" in low:
        return "裁判"
    if any(k in low for k in ("gcr", "ranking", "tour")):
        return "赛事"
    if "facilit" in low:
        return "场馆"
    if any(k in low for k in ("badminton_rules", "laws", "vocab", "variations", "irs")):
        return "规则"
    if "tech_" in low:
        return "技术"
    if "gear_" in low:
        return "装备"
    if "wiki_" in low:
        return "百科"
    return "其他"


def chunk_document(pages: list[tuple[int, str]], source: str) -> list[dict]:
    """
    一整个文档 → 切块列表。

    先按条款编号切；如果这份文档几乎没有编号（结构标记覆盖率 < 30%），
    说明它不是规范类文档，回退到按段落切。
    """
    raw = []
    for page_no, text in pages:
        raw.extend(split_page_by_clause(text, page_no, source))

    dtype = guess_doc_type(source)
    with_clause = sum(1 for c in raw if c["clause"] and c["clause"] != "DEFINITIONS")
    if raw and with_clause < len(raw) * 0.3:
        # 无结构文档：段落切，不再做父级合并（避免把不同主题的段落黏在一起）
        result = [add_prefix(c) for c in split_by_paragraph(pages, source)]
    else:
        result = [add_prefix(c) for c in merge_siblings(raw)]

    for c in result:
        c["doc_type"] = dtype
    return result


def quality_report(chunks: list[dict], original_chars: int) -> None:
    """切块质量检查：长度分布、断词、覆盖率"""
    if not chunks:
        print("没有切出任何块")
        return

    lengths = [len(c["text"]) for c in chunks]
    total = sum(lengths)

    # 断词：块以正文小写字母开头（排除前缀），说明切在了词中间
    broken = 0
    for c in chunks:
        body = c["text"][len(c.get("prefix", "")):]
        if body[:1].islower():
            broken += 1

    # 没有条款号的块（引言、定义区）
    no_clause = sum(1 for c in chunks if not c["clause"])

    print(f"块数        : {len(chunks)}")
    print(f"长度        : 最短 {min(lengths)} / 最长 {max(lengths)} / 平均 {total // len(lengths)}")
    print(f"总字符      : {total:,}（原文 {original_chars:,}，比率 {total / original_chars:.2f}）")
    print(f"小写开头块  : {broken}  ← 切在词中间的信号，越少越好")
    print(f"无条款号块  : {no_clause}  ← 引言、定义区")
    print(f"超过 800 字 : {sum(1 for n in lengths if n > 800)}")
    print(f"不足 100 字 : {sum(1 for n in lengths if n < 100)}")
