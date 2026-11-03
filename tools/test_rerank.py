"""测试硅基流动的 rerank 接口"""
import json
import os
import urllib.request

from dotenv import load_dotenv

load_dotenv()

KEY = os.getenv("SILICONFLOW_API_KEY", "").strip()
URL = "https://api.siliconflow.cn/v1/rerank"

QUERY = "60 秒的间歇出现在什么时候？"
DOCS = [
    "A game shall be won by the side which first scores 21 points. "
    "When the leading side reaches 11 points, there shall be an interval of 60 seconds.",
    "The Umpire shall call the score clearly. During the interval the Umpire shall "
    "ensure that the players do not receive coaching.",
    "The posts shall be placed on the doubles side lines.",
]

payload = {
    "model": "BAAI/bge-reranker-v2-m3",
    "query": QUERY,
    "documents": DOCS,
    "top_n": 3,
    "return_documents": False,
}

req = urllib.request.Request(
    URL,
    data=json.dumps(payload).encode(),
    headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    print("接口正常，返回：")
    for item in data.get("results", []):
        i = item["index"]
        print(f"  排名{item['relevance_score']:.4f}  文档{i}  {DOCS[i][:60]}")
    print("\n完整响应键：", list(data.keys()))
    print("usage:", data.get("usage") or data.get("meta") or "-")
except Exception as e:
    print("失败：", type(e).__name__, str(e)[:200])
    try:
        print("响应体：", e.read().decode()[:300])
    except Exception:
        pass
