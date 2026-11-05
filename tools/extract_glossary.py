"""从原文提取术语表

踩过的坑：先按 chunk 的层级前缀提取章节名，结果 `CHANGE OF ENDS` 和 `INTERVAL`
都不在里面——因为 Law 8 只有两行，切块时被合并进 Law 7，章节标题丢了。

改为直接从原始 txt 里扫 "N. TITLE" 模式，不依赖切块结果。
"""
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data_rules_only"

# 形如 "8. CHANGE OF ENDS" 或 "9. SERVICE" 的章节标题
CHAPTER = re.compile(r"^\s*(\d{1,2})\.\s+([A-Z][A-Z0-9 ,'\-&]{3,52})\s*$", re.M)

chapters = Counter()
for f in DATA.glob("*.txt"):
    text = f.read_text(encoding="utf-8", errors="ignore")
    for m in CHAPTER.finditer(text):
        title = re.sub(r"\s+", " ", m.group(2)).strip(" ,")
        if 3 <= len(title) <= 52:
            chapters[title] += 1

# 常见概念里，术语表必须覆盖的（人工校验用）
MUST_HAVE = [
    "CHANGE OF ENDS", "INTERVAL", "SERVICE", "SCORING SYSTEM", "FAULTS", "LETS",
    "DOUBLES", "SINGLES", "SHUTTLE", "RACKET", "COURT AND COURT EQUIPMENT",
    "OFFICIALS AND THEIR DECISIONS", "CONTINUOUS PLAY, MISCONDUCT",
]

print(f"从原文提取 {len(chapters)} 个章节标题\n")
print("必含术语检查：")
for t in MUST_HAVE:
    print(f"  {'✅' if t in chapters else '❌'}  {t}")

print("\n全部章节标题：")
for t, n in sorted(chapters.items()):
    print(f"  {n:>2}×  {t}")

glossary = {"chapters": sorted(chapters)}
out = ROOT / "tools" / "glossary.json"
out.write_text(json.dumps(glossary, ensure_ascii=False, indent=1), encoding="utf-8")

joined = " / ".join(sorted(chapters))
print(f"\n拼成一行：{len(joined)} 字符")
print(f"已保存 {out}")
