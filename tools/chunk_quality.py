"""
切块质量检查：只看 badminton_rules.pdf，确认切得对不对。

跑法（CMD）：
    cd /d F:/WorkPlace/Python/badminton-rag
    .venv/Scripts/python.exe test_chunker.py
"""

import sys
from pathlib import Path

# 本脚本在 tools/ 下，业务模块在项目根
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chunker import chunk_document, quality_report
from document_loader import DATA_DIR, read_pdf

pdf = DATA_DIR / "badminton_rules.pdf"
pages = read_pdf(pdf)
original_chars = sum(len(t) for _, t in pages)

print(f"原文：{pdf.name}  {len(pages)} 页  {original_chars:,} 字符\n")

chunks = chunk_document(pages, pdf.name)
quality_report(chunks, original_chars)

print("\n" + "=" * 62)
print("前 10 块长什么样")
print("=" * 62)
for i, c in enumerate(chunks[:10]):
    print(f"\n[{i}] 第{c['page']}页  条款={c['clause'] or '(引言)'}  章={c['chapter']}")
    print(f"    {c['text'][:170].replace(chr(10), ' ')}")

print("\n" + "=" * 62)
print("关键内容是否各自独立成块")
print("=" * 62)
checks = [
    ("Rally 定义", "Rally A sequence"),
    ("16 根羽毛", "16 feathers"),
    ("20 平领先 2 分", "two point lead"),
    ("发球高度 1.15 米", "1.15 metres"),
    ("掷币", "toss shall be conducted"),
    ("第三局 11 分换边", "first scores 11 points"),
]
for label, kw in checks:
    hits = [c for c in chunks if kw.lower() in c["text"].lower()]
    if hits:
        c = hits[0]
        print(f"  ✅ {label:<16} 条款={c['clause']:<8} 长度={len(c['text']):<4} 块内唯一={len(hits) == 1}")
    else:
        print(f"  ❌ {label:<16} 没找到「{kw}」")
