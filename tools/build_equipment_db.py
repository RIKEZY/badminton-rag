"""把抓到的装备数据整理成 SQLite 表

数据来源：
    尤尼克斯 31 款球拍 —— tools/yonex_clean.json（官网抓取）
    李宁 3 款球拍 —— 搜索结果人工整理（参数来自李宁官网/百度百科/搜狐）

设计要点：
    1. 建议磅数是「多规格」的（4U 20-28 / 3U 21-29），除了原文再存一份解析后的 JSON，
       否则「88S PRO 4U 拉多少磅」这种问题没法精确回答
    2. 保留 source 字段，因为同一个型号在不同来源上参数会冲突
       （战戟8000 中杆硬度：李宁官网「软」，百度百科「适中」）
"""
import json
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "yonex_clean.json"
DB = HERE / "equipment.db"

DDL = """
CREATE TABLE IF NOT EXISTS rackets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    brand         TEXT NOT NULL,
    series        TEXT,
    model         TEXT NOT NULL,
    full_title    TEXT,
    weights       TEXT,
    tension_raw   TEXT,
    tension_json  TEXT,
    stiffness     TEXT,
    balance_point TEXT,
    length        TEXT,
    frame_material TEXT,
    shaft_material TEXT,
    color         TEXT,
    origin        TEXT,
    product_code  TEXT,
    url           TEXT,
    source        TEXT
);
CREATE INDEX IF NOT EXISTS idx_model ON rackets(model);
CREATE INDEX IF NOT EXISTS idx_brand ON rackets(brand);
"""


def parse_tension(raw: str) -> dict:
    """把 '4U 20-28 3U 21-29' 解析成 {'4U': [20, 28], '3U': [21, 29]}"""
    out = {}
    for w, lo, hi in re.findall(r"([345]U)\s*(\d+)\s*[-–~]\s*(\d+)", raw or ""):
        out[w] = [int(lo), int(hi)]
    for w, hi in re.findall(r"([345]U)\s*≤\s*(\d+)", raw or ""):
        out.setdefault(w, [None, int(hi)])
    return out


def split_title(title: str):
    """'【天斧系列】ASTROX 88S PRO羽毛球拍' → ('天斧', 'ASTROX 88S PRO')"""
    m = re.match(r"【(.+?)系列】\s*(.+?)(?:羽毛球拍)?$", title)
    if m:
        return m.group(1), m.group(2).strip()
    return None, title.replace("羽毛球拍", "").strip()


def from_yonex():
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    out = []
    for r in rows:
        if "羽毛球拍" not in r["title"]:
            continue
        p = r["params"]
        series, model = split_title(r["title"])
        frame = p.get("拍框") or p.get("材质") or ""
        shaft = p.get("拍杆") or ""
        out.append({
            "brand": "尤尼克斯",
            "series": series,
            "model": model,
            "full_title": r["title"],
            "weights": p.get("规格", ""),
            "tension_raw": p.get("建议磅数", ""),
            "stiffness": p.get("击球手感", ""),
            "balance_point": "",
            "length": p.get("长度", ""),
            "frame_material": frame,
            "shaft_material": shaft,
            "color": p.get("颜色", ""),
            "origin": p.get("产地", ""),
            "product_code": p.get("商品代码", ""),
            "url": r["url"],
            "source": "尤尼克斯官网",
        })
    return out


# 李宁三款：参数来自搜索结果（李宁官网 / 百度百科 / 搜狐 / 优个网），
# 同一字段多来源不一致时保留两种说法
LN = [
    {
        "brand": "李宁", "series": "战戟", "model": "战戟8000",
        "full_title": "李宁 战戟8000（HALBERTEC 8000）",
        "weights": "3U / 4U",
        "tension_raw": "3U ≤31 4U ≤30",
        "stiffness": "软（官网）/ 适中（百科）",
        "balance_point": "3U 298mm / 4U 290mm",
        "length": "673mm",
        "frame_material": "碳纤维（流体盒式拍框，76 孔）",
        "shaft_material": "碳纤维",
        "color": "青玉蓝 / 荧光耀粉",
        "origin": "",
        "product_code": "",
        "url": "https://store.lining.com/goods/detail?spuId=10723488",
        "source": "李宁官网+百度百科",
    },
    {
        "brand": "李宁", "series": "雷霆", "model": "雷霆80",
        "full_title": "李宁 雷霆80（AXFORCE 80）",
        "weights": "3U / 4U / 5U",
        "tension_raw": "3U ≤31 4U ≤30 5U ≤29",
        "stiffness": "适中",
        "balance_point": "300-304mm",
        "length": "675mm",
        "frame_material": "M40X + 高强度碳纤维",
        "shaft_material": "M46 + 高弹碳纤维（6.6mm）",
        "color": "黑金",
        "origin": "",
        "product_code": "",
        "url": "",
        "source": "李宁官网+搜狐",
    },
    {
        "brand": "李宁", "series": "风刃", "model": "风刃900",
        "full_title": "李宁 风刃900（3D CALIBAR 900）",
        "weights": "W2（4U，83g）",
        "tension_raw": "≤32",
        "stiffness": "偏硬",
        "balance_point": "308mm",
        "length": "675mm",
        "frame_material": "碳纤维",
        "shaft_material": "碳纤维",
        "color": "灰金",
        "origin": "",
        "product_code": "",
        "url": "",
        "source": "优个网+知乎",
    },
]


def main():
    if DB.exists():
        DB.unlink()
    conn = sqlite3.connect(DB)
    conn.executescript(DDL)

    rows = from_yonex() + LN
    for r in rows:
        r["tension_json"] = json.dumps(parse_tension(r["tension_raw"]), ensure_ascii=False)

    cols = ["brand", "series", "model", "full_title", "weights", "tension_raw", "tension_json",
            "stiffness", "balance_point", "length", "frame_material", "shaft_material",
            "color", "origin", "product_code", "url", "source"]
    conn.executemany(
        f"INSERT INTO rackets ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r.get(c, "") for c in cols) for r in rows],
    )
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM rackets").fetchone()[0]
    print(f"入库 {total} 款球拍 → {DB}")
    print("\n按品牌：")
    for b, n in conn.execute("SELECT brand, COUNT(*) FROM rackets GROUP BY brand"):
        print(f"  {b}: {n}")
    print("\n解析磅数样例：")
    for m, t, j in conn.execute(
            "SELECT model, tension_raw, tension_json FROM rackets "
            "WHERE model LIKE '%88%' LIMIT 3"):
        print(f"  {m:<20} {t:<24} → {j}")
    conn.close()


if __name__ == "__main__":
    main()
