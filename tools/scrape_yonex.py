"""yonex.cn 商品抓取 v2

改进：
1. 标签允许字间空格（官网是「拍      框：」，不是「拍框：」）
2. HTML 落盘缓存，改解析逻辑不用重新抓
3. 只抓需要的品类（球拍/球鞋/羽毛球/球线），避免拉全网球高尔夫
"""
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://www.yonex.cn/home/index/mall_detail/id/{}"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
HERE = Path(__file__).parent
CACHE = HERE / "html_cache"
OUT = HERE / "yonex_clean.json"

LABELS = ["产地", "商品代码", "拍框", "拍杆", "击球手感", "长度", "规格",
          "建议磅数", "颜色", "材质", "鞋面", "中底", "外底", "尺码", "型号"]


def label_pat(lab: str) -> str:
    r"""把「拍框」变成「拍\s*框」，兼容官网字间空格"""
    return r"\s*".join(re.escape(c) for c in lab)


PATS = [(lab, label_pat(lab)) for lab in LABELS]
ALT = "|".join(p for _, p in PATS)


def clean(html: str) -> str:
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<[^>]+>", "\n", html)
    html = html.replace("&nbsp;", " ").replace("&amp;", "&")
    return html


def get_html(i: int) -> str | None:
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"{i}.html"
    if f.exists():
        return f.read_text(encoding="utf-8", errors="ignore")
    try:
        req = urllib.request.Request(BASE.format(i), headers=UA)
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read().decode("utf-8", "ignore")
        f.write_text(html, encoding="utf-8")
        return html
    except Exception:
        return None


def parse(i: int):
    html = get_html(i)
    if not html:
        return None
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    title = re.sub(r"\s+", " ", m.group(1)).strip().replace("Yonex-", "").strip() if m else ""
    if not title or "404" in title:
        return None

    text = clean(html)
    params = {}
    for lab, pat in PATS:
        mm = re.search(pat + r"\s*[：:]\s*([^\n]{1,100}?)(?=\n|\s*(" + ALT + r")\s*[：:]|$)",
                       text, re.S)
        if mm:
            v = re.sub(r"\s{2,}", " ", mm.group(1)).strip()
            if v and v not in ("立即购买", "TOP"):
                params[lab] = v

    return {"id": i, "title": title, "url": BASE.format(i), "params": params}


def main():
    ids = range(1, 1501)
    rows, done = [], 0
    with ThreadPoolExecutor(max_workers=5) as ex:
        for r in ex.map(parse, ids):
            done += 1
            if r:
                rows.append(r)
            if done % 300 == 0:
                print(f"进度 {done}/1500，有效 {len(rows)}", flush=True)

    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成 {len(rows)} 个商品 → {OUT}")

    racks = [r for r in rows if "羽毛球拍" in r["title"]]
    print(f"\n羽毛球拍 {len(racks)} 款，参数完整度：")
    from collections import Counter
    c = Counter()
    for r in racks:
        for k in r["params"]:
            c[k] += 1
    for k, n in c.most_common():
        print(f"  {k}: {n}/{len(racks)}")

    print("\n样例：")
    for r in racks[:2]:
        print(f"  [{r['id']}] {r['title']}")
        for k, v in r["params"].items():
            print(f"      {k}: {v[:55]}")


if __name__ == "__main__":
    main()
