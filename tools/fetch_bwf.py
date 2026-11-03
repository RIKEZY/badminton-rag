"""从 BWF 官方下载核心文档并提取为纯文本

只取和问答场景相关、且不涉及大量表格的文档。
BWF 文档是权威来源，比自媒体文章可靠得多。
"""
import urllib.request
from pathlib import Path

from pypdf import PdfReader

HERE = Path(__file__).parent
RAW = HERE / "pdf"
TXT = HERE / "txt"

BASE = "https://extranet.bwf.sport/docs/document-system/81/1466/{sec}/{name}"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0"}

DOCS = [
    # 裁判执行
    ("itto", "1470", "Section%204.1.1%20-%20Instructions%20to%20Technical%20Officials%20%28ITTO%29%20-%20Effective%2023%20October%202026%20V1.0.pdf"),
    # 赛事规程
    ("gcr", "1471", "Section%205.1%20-%20General%20Competition%20Regulations%20-%20Effective%2023%20October%202026%20V9.0.pdf"),
    # 积分排名
    ("ranking", "1471", "Section%205.3.3.1%20-%20World%20Ranking%20System%20-%2026%20April%202026%20V6.0.pdf"),
    # 术语表
    ("vocabulary", "1470", "Section%204.1.5%20-%20Vocabulary%20-%20Effective%2023%20October%202026%20V1.0.pdf"),
    # 规则 2027 新版（和现行版形成版本对照）
    ("laws_2027", "1470", "Section%204.1%20-%20Laws%20of%20Badminton%20-%20Effective%2004%20January%202027%20V2.pdf"),
    # 场馆设施规格
    ("facilities", "1471", "Section%205.3.4%20-%20Specs%20for%20Int_l%20Standard%20Facilities%20-%20Effective%2001%20January%202027%20V1.0.pdf"),
]


def download(key: str, sec: str, name: str) -> Path | None:
    RAW.mkdir(exist_ok=True)
    f = RAW / f"{key}.pdf"
    if f.exists() and f.stat().st_size > 10000:
        print(f"  {key}: 已存在（{f.stat().st_size // 1024} KB）")
        return f
    try:
        req = urllib.request.Request(BASE.format(sec=sec, name=name), headers=UA)
        with urllib.request.urlopen(req, timeout=90) as r:
            data = r.read()
        f.write_bytes(data)
        print(f"  {key}: 下载成功（{len(data) // 1024} KB）")
        return f
    except Exception as e:
        print(f"  {key}: 失败 {type(e).__name__} {str(e)[:60]}")
        return None


def extract(key: str, pdf: Path) -> int:
    TXT.mkdir(exist_ok=True)
    try:
        reader = PdfReader(str(pdf))
        pages = [(p.extract_text() or "").strip() for p in reader.pages]
        text = "\n\n".join(pages)
        # 去掉 BWF 每页的页眉（和现有语料同样的污染源）
        import re
        text = re.sub(r"BWF Statutes, Section [\d.]+:[^\n]*\n", "", text)
        text = re.sub(r"In Force:[^\n]*\n", "", text)
        out = TXT / f"bwf_{key}.txt"
        out.write_text(text, encoding="utf-8")
        print(f"  {key}: {len(reader.pages)} 页 → {len(text)} 字")
        return len(text)
    except Exception as e:
        print(f"  {key}: 解析失败 {type(e).__name__}")
        return 0


if __name__ == "__main__":
    print("下载：")
    files = {}
    for key, sec, name in DOCS:
        p = download(key, sec, name)
        if p:
            files[key] = p

    print("\n提取文本：")
    total = 0
    for key, pdf in files.items():
        total += extract(key, pdf)

    print(f"\n合计 {total} 字，输出目录 {TXT}")
