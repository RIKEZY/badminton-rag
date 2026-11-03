"""装备结构化查询

设计原则：这里不做语义理解，只做精确匹配。
「88S PRO 的磅数」这种问题交给 SQL，「哪个拍适合进攻」才交给向量检索。
"""
import json
import sqlite3
from pathlib import Path

DB = Path(__file__).parent / "equipment.db"


def _query(sql: str, args=()):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def normalize(s: str) -> str:
    """型号归一化：去空格、转大写、去掉常见分隔符

    官网写 'ASTROX 100 ZZ'，用户输入 '100ZZ'、'100 zz'、'ast 100zz' 都要能命中。
    不做这一步，精确查询在实际使用中会大面积失败。
    """
    return (s or "").upper().replace(" ", "").replace("-", "").replace("_", "")


def search_model(keyword: str) -> list[dict]:
    """按型号模糊查找，忽略空格与大小写差异"""
    kw = f"%{normalize(keyword)}%"
    return _query(
        "SELECT * FROM rackets "
        "WHERE REPLACE(REPLACE(UPPER(model),' ',''),'-','') LIKE ? "
        "   OR REPLACE(REPLACE(UPPER(full_title),' ',''),'-','') LIKE ? "
        "ORDER BY LENGTH(model)",
        (kw, kw),
    )


def tension_of(model: str, weight: str | None = None):
    """查磅数；指定 weight（如 '4U'）时只返回该规格"""
    rows = search_model(model)
    if not rows:
        return None
    out = []
    for r in rows:
        tj = json.loads(r["tension_json"] or "{}")
        if weight:
            out.append({"model": r["model"], "weight": weight,
                        "range": tj.get(weight), "raw": r["tension_raw"]})
        else:
            out.append({"model": r["model"], "all": tj, "raw": r["tension_raw"]})
    return out


def filter_by(stiffness: str | None = None, brand: str | None = None,
              min_tension: int | None = None) -> list[dict]:
    """按属性筛选：硬度 / 品牌 / 磅数下限"""
    rows = _query("SELECT * FROM rackets")
    out = []
    for r in rows:
        if stiffness and stiffness not in (r["stiffness"] or ""):
            continue
        if brand and brand not in (r["brand"] or ""):
            continue
        if min_tension is not None:
            tj = json.loads(r["tension_json"] or "{}")
            if not any(v[1] and v[1] >= min_tension for v in tj.values()):
                continue
        out.append(r)
    return out


def brief(r: dict) -> str:
    return (f"{r['brand']} {r['model']:<20} "
            f"磅数 {r['tension_raw'][:22]:<24} 手感 {r['stiffness'] or '-'}")


if __name__ == "__main__":
    print("=== 精确查型号：88S PRO ===")
    for r in search_model("88S PRO"):
        print(" ", brief(r))

    print("\n=== 查磅数：ASTROX 88S PRO 的 4U ===")
    print(" ", tension_of("88S PRO", "4U"))

    print("\n=== 对比：88D TOUR 的 4U（名字只差一个字母）===")
    print(" ", tension_of("88D TOUR", "4U"))

    print("\n=== 按属性筛：手感为「硬」的球拍 ===")
    hard = filter_by(stiffness="硬")
    print(f"  共 {len(hard)} 款：")
    for r in hard[:6]:
        print("  ", brief(r))
