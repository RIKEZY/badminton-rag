"""
Day 1 · 羽毛球知识问答 · 第一步

这一版只做两件事：
1. 把一个 PDF 读成纯文本
2. 把文本塞给 DeepSeek，问一个固定问题

为什么先做这个：出问题时你知道是哪一环坏了。
一上来就写检索，跑不通你会分不清是 PDF 没读出来、还是 API 没通、还是检索逻辑错了。

运行：
    pip install -r requirements.txt
    copy .env.example .env    (然后填入你的 key)
    python day1.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pypdf import PdfReader

load_dotenv()

API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()

HERE = Path(__file__).parent
PDF_PATH = HERE / "data" / "badminton_rules.pdf"

# 先固定一个问题，等跑通了再改成 input() 让你随便问
QUESTION = "羽毛球比赛中，一局打到 20 平之后，需要领先几分才能获胜？"


def check_config() -> None:
    if not API_KEY:
        sys.exit(
            "缺少 DEEPSEEK_API_KEY\n"
            "把 .env.example 复制成 .env，把你的 key 填进去"
        )
    if not PDF_PATH.exists():
        sys.exit(
            f"找不到 PDF：{PDF_PATH}\n"
            f"把羽毛球规则 PDF 放进 data/ 目录，改名为 {PDF_PATH.name}"
        )


def read_pdf(path: Path) -> list[tuple[int, str]]:
    """返回 [(页码, 该页文本), ...]"""
    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        pages.append((i, text))
    return pages


def main() -> None:
    check_config()

    print(f"读取 PDF：{PDF_PATH.name}")
    pages = read_pdf(PDF_PATH)
    total_chars = sum(len(t) for _, t in pages)
    print(f"共 {len(pages)} 页，提取到 {total_chars} 个字符")

    empty = [i for i, t in pages if len(t) < 20]
    if empty:
        print(f"注意：{len(empty)} 页几乎没提取到文字，页码 {empty[:10]}")
        print("  扫描版 PDF 需要先 OCR，这一版先跳过这些页")

    context = "\n\n".join(f"[第 {i} 页]\n{t}" for i, t in pages if len(t) >= 20)
    if not context:
        sys.exit("整份 PDF 都没提取到文字，换一份可复制文本的 PDF")

    print(f"上下文长度：{len(context)} 字符")
    print(f"提问：{QUESTION}\n")

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "你是羽毛球规则助手。只根据用户提供的资料回答，"
                           "资料里没有就说不知道，不要编。回答时注明来自第几页。",
            },
            {"role": "user", "content": f"资料：\n{context}\n\n问题：{QUESTION}"},
        ],
        temperature=0,
    )

    print("回答：")
    print(resp.choices[0].message.content)
    print(f"\n本次 token 消耗：{resp.usage.total_tokens}")


if __name__ == "__main__":
    main()
