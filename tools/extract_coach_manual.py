"""从 BWF 教练手册提取技术/战术/体能/伤病章节

手册 282 页，但只有一部分对问答有用：
    Module 1-4   概述、教练原则、教练流程、教小孩 → 教学法，跳过
    Module 5-11  表现因素、技术、战术、体能、心理、伤病 → 保留
    Module 12-13 竞赛形式（和 GCR 重复）、残障羽毛球 → 跳过

页码映射：手册页码 + 22 = PDF 页码（手册 p47 在 PDF 第 69 页）
"""
import re
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "tools" / "pdf" / "bwf_coach_education_coaches_manual_l1-2nd-edition-midres.pdf"
OUT = ROOT / "data_rules_only" / "bwf_coach_l1.txt"

# 手册 p47（Module 5 开始）到 p208（Module 11 结束）→ PDF p69-230
START_PDF, END_PDF = 69, 230

# 页眉：「BADMINTON COACH EDUCATION ► COACHES' MANUAL ► LEVEL 1 MODULE N ► XXX」
HEADER_RE = re.compile(
    r"BADMINTON COACH EDUCATION\s*[►>]\s*COACHES?.?\s*MANUAL.*", re.IGNORECASE
)
# 纯页码行（1-3 位数字）
PAGE_NO_RE = re.compile(r"^\s*\d{1,3}\s*$")

reader = PdfReader(str(PDF))
parts = ["羽毛球教练手册（BWF Coach Education Level 1，第二版）",
         "来源：BWF 官方教练教育手册，2026-11-05 提取",
         "说明：仅提取技术、战术、体能、伤病章节；教学法与竞赛组织章节未收录",
         ""]

kept = 0
for i in range(START_PDF - 1, min(END_PDF, len(reader.pages))):
    raw = reader.pages[i].extract_text() or ""
    lines = []
    for ln in raw.split("\n"):
        s = ln.strip()
        if not s:
            continue
        if HEADER_RE.search(s):
            continue
        if PAGE_NO_RE.match(s):
            continue
        lines.append(s)
    if not lines:
        continue
    parts.append("\n".join(lines))
    kept += 1

text = "\n\n".join(parts)
text = re.sub(r"\n{3,}", "\n\n", text)
OUT.write_text(text, encoding="utf-8")

print(f"提取 {kept} 页，{len(text):,} 字符")
print(f"已写入 {OUT.name}")
print()
print("=== 开头预览 ===")
print(text[:600])
