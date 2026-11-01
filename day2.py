"""
Day 2 · 把长文档切成小块

为什么必须切：
Day 1 把整份 2.5 万字符塞给模型，一次 6915 token。
语料加到 30 篇就是 70 万字符，塞不进去，而且贵。
切块之后每次只喂最相关的几块，上下文能从几万字降到两千字。

这一步先不做检索，只做两件事：
1. 把 data/ 里所有文件读成「带出处」的文本（出处 = 文件名 + 第几页）
2. 切成固定大小、带重叠的块，打印统计

为什么要重叠：一句话被切在两块中间，两块都读不懂。
重叠 100 字，等于让相邻两块共享一段上下文。

运行：
    python day2.py
"""

import os
import re
import sys
from pathlib import Path

from pypdf import PdfReader

HERE = Path(__file__).parent
# 允许用环境变量切换语料目录，方便做「全语料 vs 仅规则」的对照实验
DATA_DIR = Path(os.getenv("RAG_DATA_DIR") or (HERE / "data"))

CHUNK_SIZE = 500   # 每块目标字符数
OVERLAP = 100      # 相邻块重叠字符数

# PDF 页眉长这样：
#   BWF Statutes, Section 4.1: Law of Badminton                Page 5 of 14
#   BWF Statutes, Section 4.1.1: Instructions to Technical Officials (ITTO) Page 15 of 42
# 这些行含 BWF / Law / Badminton 等高频词，会被 BM25 当成强相关，
# 还会和正文混进同一块，把真正的内容挤出 top5。切块前必须删掉。
HEADER_RE = re.compile(r"Page\s+\d+\s+of\s+\d+", re.IGNORECASE)


def strip_header(text: str) -> str:
    """删掉含「Page X of Y」的页眉行"""
    kept = [line for line in text.split("\n") if not HEADER_RE.search(line)]
    return "\n".join(kept).strip()


# ---------------------------------------------------------------- 读文件

def read_pdf(path: Path) -> list[tuple[int, str]]:
    """返回 [(页码, 该页文本)]。页码留着，Day 5 要用它标来源。"""
    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = strip_header((page.extract_text() or "").strip())
        if text:
            pages.append((i, text))
    return pages


def read_text_file(path: Path) -> list[tuple[int, str]]:
    """txt / md 没有页的概念，统一记成第 1 页。"""
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    return [(1, text)] if text else []


def load_documents() -> list[dict]:
    """
    扫 data/ 目录，返回 [{"source": 文件名, "page": 页码, "text": 文本}, ...]
    一个 PDF 会拆成多条，一条对应一页。
    """
    if not DATA_DIR.exists():
        sys.exit(f"找不到目录：{DATA_DIR}")

    docs = []
    files = sorted(p for p in DATA_DIR.iterdir() if p.is_file())
    for path in files:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            pages = read_pdf(path)
        elif suffix in (".txt", ".md"):
            pages = read_text_file(path)
        else:
            print(f"跳过（不支持的类型）：{path.name}")
            continue

        for page_no, text in pages:
            docs.append({"source": path.name, "page": page_no, "text": text})

        if pages:
            print(f"  {path.name:<28} {len(pages):>3} 页  "
                  f"{sum(len(t) for _, t in pages):>7} 字符")
        else:
            print(f"  {path.name:<28} 没提取到文字，跳过")

    return docs


# ---------------------------------------------------------------- 切块

def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> list[str]:
    """
    按字符切，带重叠。

    为什么不用「按段落切」：PDF 提取出来的文本段落边界很乱，
    先按固定长度切，跑通了再优化——Day 7 就是干这个的。

    步长 = size - overlap。块0 是 [0:500]，块1 是 [400:900]，以此类推。
    """
    if len(text) <= size:
        return [text]

    step = size - overlap
    chunks = []
    start = 0
    while start < len(text):
        piece = text[start:start + size].strip()
        if piece:
            chunks.append(piece)
        if start + size >= len(text):
            break
        start += step
    return chunks


# ---------------------------------------------------------------- 主流程

def main() -> None:
    print(f"扫描目录：{DATA_DIR}\n")
    docs = load_documents()

    if not docs:
        sys.exit("data/ 里没有可用文件。放 PDF 或 txt 进去再跑。")

    total_chars = sum(len(d["text"]) for d in docs)
    print(f"\n共 {len(docs)} 个文档单元，{total_chars} 字符")
    print(f"切块参数：{CHUNK_SIZE} 字/块，重叠 {OVERLAP} 字\n")

    all_chunks = []
    for doc in docs:
        for piece in chunk_text(doc["text"]):
            all_chunks.append({
                "source": doc["source"],
                "page": doc["page"],
                "text": piece,
            })

    print(f"切成 {len(all_chunks)} 块\n")
    print("-" * 70)

    # 先看前 5 块长什么样，确认切出来的东西还是人话
    for i, c in enumerate(all_chunks[:5]):
        preview = c["text"][:60].replace("\n", " ")
        print(f"[{i}] {c['source']} 第{c['page']}页  {len(c['text'])}字")
        print(f"    {preview}...")
        print()

    # 顺手报一下长度分布，太长太短的块后面会害你
    lengths = [len(c["text"]) for c in all_chunks]
    print("-" * 70)
    print(f"块长度：最短 {min(lengths)}  最长 {max(lengths)}  "
          f"平均 {sum(lengths) // len(lengths)}")

    tiny = sum(1 for n in lengths if n < 100)
    if tiny:
        print(f"其中 {tiny} 块不到 100 字（多半是页眉页脚或表格残渣）")

    print("\nDay 2 完成。下一步：给这些块算 embedding，用语义而不是关键词找相关块。")


if __name__ == "__main__":
    main()
