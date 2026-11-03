"""Cross-encoder 重排

为什么需要：
    向量检索判断的是「语义相近」，判断不了「这段文字是否回答了这个问题」。
    扩语料后出现同一概念的多个视角（规则条文 / 裁判手册 / 赛事规程），
    语义都很近，但只有一份是用户要的答案。

实测对比（问题：60 秒的间歇出现在什么时候？）：
    规则条文（Law 16.2.1）      rerank 0.7259
    裁判手册（间歇时裁判做什么）  rerank 0.0001
    网柱条文                     rerank 0.0000
    向量检索给这三块的分数是同一量级，分不开。

用法：
    融合后取一个较大的候选池（默认 20），重排后再截断到 top_k。
"""
import json
import os
import urllib.request

RERANK_URL = "https://api.siliconflow.cn/v1/rerank"
DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"


def rerank(query: str, docs: list[str], top_n: int | None = None,
           model: str | None = None, api_key: str | None = None,
           timeout: int = 30) -> list[tuple[int, float]]:
    """对候选文档重排，返回 [(原下标, 相关度)]，按相关度降序。

    失败时返回空列表，调用方应降级到原始顺序。
    """
    if not docs:
        return []

    key = (api_key or os.getenv("SILICONFLOW_API_KEY", "")).strip()
    if not key:
        return []

    payload = {
        "model": model or os.getenv("RERANK_MODEL", DEFAULT_MODEL),
        "query": query,
        "documents": docs,
        "top_n": top_n or len(docs),
        "return_documents": False,
    }

    try:
        req = urllib.request.Request(
            RERANK_URL,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return [(item["index"], float(item["relevance_score"]))
                for item in data.get("results", [])]
    except Exception:
        return []


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    q = "60 秒的间歇出现在什么时候？"
    ds = [
        "When the leading side reaches 11 points, there shall be an interval of 60 seconds.",
        "During the interval the Umpire shall ensure that the players do not receive coaching.",
        "The posts shall be placed on the doubles side lines.",
    ]
    for idx, score in rerank(q, ds):
        print(f"  {score:.4f}  {ds[idx][:70]}")
