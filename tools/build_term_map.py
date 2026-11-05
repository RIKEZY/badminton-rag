"""从章节标题反向生成中文说法（元数据反向映射）

思路：文档章节标题是英文术语（CHANGE OF ENDS），
反推用户可能用哪些中文词来问（换边 / 交换场地 / 换场）。
这样得到的映射表覆盖面广，而且和文档术语天然对齐。

输出 tools/term_map.json
"""
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
GLOSSARY = json.loads((ROOT / "tools" / "glossary.json").read_text(encoding="utf-8"))

CHAT_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
CHAT_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "").strip()
CHAT_MODEL = os.getenv("DEEPSEEK_MODEL", "").strip()
client = OpenAI(api_key=CHAT_KEY, base_url=CHAT_BASE_URL)

# 只保留和「打球的人」相关的术语，赛事运营类跳过
SKIP = {
    "ADVERTISING IN THE PLAYING AREA", "CLOTHING REGULATIONS FOR UMPIRES WHERE A UNIF",
    "DIVISION OF PRIZE MONEY", "JURISDICTION, PLAYER ENTRY REGISTRATION AND PENALTY",
    "ONLINE ENTRIES AND CONTROL OF ENTRIES", "PLAYER AND COACH CLOTHING AND EQUIPMENT",
    "PLAYER AGE LIMITS IN TOURNAMENTS", "PRIZE MONEY", "PROMOTIONS AND REDRAWS",
    "PURPOSE AND APPLICABILITY OF THE REGULATIONS", "SANCTION", "THE DRAW",
    "TOURNAMENT AND PLAYER RIGHTS", "VIRTUAL IMAGING OR ADVERTISING",
    "WITHDRAWAL FEES", "WITHDRAWALS AND PROMOTIONS", "INVITATIONS AND TOURNAMENT PROSPECTUS",
    "IMPLEMENTATION, MODIFICATION AND PENALTIES", "INTEGRITY", "INTRODUCTION",
    "MANAGEMENT OF TOURNAMENTS", "QUALIFYING", "RESULTS", "RANKING IN TOURNAMENTS PLAYED IN GROUPS",
}

PROMPT = """下面是一个羽毛球规则文档的章节标题（英文术语）。
请为每个术语给出中国球友最可能用来提问的 2-3 个中文说法。

要求：
1. 用球友日常口语，不是官方译名。比如 CHANGE OF ENDS → 换边 / 交换场地 / 换场
2. 只输出 JSON，格式：{"英文术语": ["中文说法1", "中文说法2"]}
3. 不要解释

术语列表：
__TERMS__"""

terms = [t for t in GLOSSARY["chapters"] if t not in SKIP]
print(f"待处理术语 {len(terms)} 个（跳过 {len(GLOSSARY['chapters']) - len(terms)} 个赛事运营类）")

resp = client.chat.completions.create(
    model=CHAT_MODEL,
    messages=[{"role": "user", "content": PROMPT.replace("__TERMS__", "\n".join(terms))}],
    temperature=0,
    extra_body={"enable_thinking": False} if os.getenv("CHAT_DISABLE_THINKING") else None,
)
raw = (resp.choices[0].message.content or "").strip()
raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.M).strip()

try:
    mapping = json.loads(raw)
except json.JSONDecodeError:
    print("解析失败，原始输出：")
    print(raw[:800])
    raise SystemExit(1)

# 反向：中文说法 → 英文术语
reverse = {}
for en, zhs in mapping.items():
    for zh in zhs:
        reverse.setdefault(zh, []).append(en)

out = {"by_chapter": mapping, "by_chinese": reverse}
dst = ROOT / "tools" / "term_map.json"
dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

print(f"\n生成 {len(mapping)} 个英文术语 → {len(reverse)} 个中文说法")
print("\n样例：")
for zh in list(reverse)[:12]:
    print(f"  {zh:<10} → {reverse[zh]}")
print(f"\n已保存 {dst}")
