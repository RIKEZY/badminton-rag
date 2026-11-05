"""
最小可运行示例：读 PDF → 直接问模型

不带检索、不带切块，整份文档塞进上下文。用来验证「API 通不通」这一环——
出问题时能立刻分清是 PDF 没读出来、API 没通、还是检索逻辑的问题。

生产链路（app.py）不会这样用：整份文档 14 万字符 = 38,607 token，
既贵又超出有效上下文。这里只是链路最短的冒烟测试。

运行：
    pip install -r requirements.txt
    copy .env.example .env    (然后填入你的 key)
    python examples/minimal_demo.py
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

# 本文件在 examples/ 下，数据目录在项目根
ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / "data" / "badminton_rules.pdf"

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
